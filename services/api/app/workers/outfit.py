"""Reading a whole outfit out of one photograph of someone wearing it.

The single-garment classifier assumes a flat lay or a hanger shot: one
photograph, one thing. A photograph of a person wearing clothes is the far
more natural way to add to a wardrobe, and it contains three to six garments
that each need their own entry, their own slot and their own cut-out.

So this is a fan-out, not a different classifier. One vision call lists what
is being worn, and then each listed garment goes through the *existing*
segmentation path with its own noun phrase. Nothing about cut-outs or
compositing is re-implemented here.

**The cost shape matters and is why detection is one call, not many.**
`sam-3.1` takes a single noun phrase per request, so N garments means N
segmentation calls at $0.0025 each. Detecting first and segmenting only what
was actually found keeps a four-garment outfit at roughly one cent; asking
the segmenter to look for every category in the taxonomy would cost thirty
times that and find nothing most of the time.

**What this deliberately does not claim.** It reports garments, not people. No
attribute of the wearer is inferred or stored: not body shape, not skin tone,
not age, not gender. The prompt forbids it and the schema has nowhere to put
it, which is the only version of that promise worth making (ADR-010).
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from typing import Any

from app.domain.garment_media import (
    CATEGORY_LABELS,
    COLOUR_LABELS,
    MATERIAL_LABELS,
    PATTERN_LABELS,
    SLOT_LABELS,
    CategorisationResult,
)
from app.errors import ApiError
from app.providers.base import AIMessage, AIRequest, Capabilities, JsonSchemaFormat
from app.providers.segmentation import data_uri
from app.workers.categorise import prepare_image

#: Model and prompt version, recorded on every run so a change in behaviour
#: can be attributed to a change in the prompt.
OUTFIT_MODEL = "muse-spark-1.3"
OUTFIT_PROMPT_VERSION = "outfit-detect/v1"
OUTFIT_PURPOSE = "wardrobe.detect_outfit"

#: Reasoning tokens count against this, and the model spends them before it
#: emits anything. A list of six garments is longer than one garment, so this
#: is above the single-garment budget for the same measured reason.
OUTFIT_MAX_TOKENS = 4096
OUTFIT_TEMPERATURE = 0.0

#: More than this in one photograph and the tail is almost always a
#: misreading: a belt loop counted as a belt, a shadow as a second shoe.
#: Capping also bounds the segmentation spend for one upload.
MAX_GARMENTS = 8

OUTFIT_SYSTEM = (
    "You identify garments in a photograph so they can be catalogued in "
    "someone's own wardrobe.\n"
    "\n"
    "Report only garments that are being worn or carried and are clearly "
    "visible. Do not report a garment you are inferring rather than seeing: "
    "if trousers are hidden behind a desk, they are not in the photograph.\n"
    "\n"
    "Never describe the person. Do not report, imply, or take into account "
    "their body, age, gender, ethnicity, or appearance. You are looking at "
    "clothes.\n"
    "\n"
    "`noun_phrase` is how the garment will be cut out of the photograph, so "
    "it must be two or three plain words naming the garment and its most "
    "distinguishing visible feature, such as 'white button-up shirt' or "
    "'brown leather tote'. It must name one garment, never a list."
)

OUTFIT_USER_TEXT = (
    "List every garment worn or carried in this photograph, one entry each."
)


def _enum(values: tuple[str, ...], description: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values), "description": description}


def _confidence(description: str) -> dict[str, Any]:
    return {"type": "number", "minimum": 0, "maximum": 1, "description": description}


OUTFIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["worn", "items"],
    "properties": {
        "worn": {
            "type": "boolean",
            "description": (
                "True when a person is wearing the garments. False for a flat "
                "lay, a hanger shot, or a single garment photographed alone."
            ),
        },
        "items": {
            "type": "array",
            "maxItems": MAX_GARMENTS,
            "description": "One entry per visible garment.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "noun_phrase",
                    "slot",
                    "category",
                    "colour",
                    "pattern",
                    "apparent_material",
                    "confidence",
                ],
                "properties": {
                    "noun_phrase": {
                        "type": "string",
                        "maxLength": 40,
                        "description": (
                            "Two or three plain words naming this garment, used "
                            "to cut it out of the photograph."
                        ),
                    },
                    "slot": _enum(SLOT_LABELS, "Which wardrobe slot it fills."),
                    "category": _enum(CATEGORY_LABELS, "Garment type, closed list."),
                    "colour": _enum(COLOUR_LABELS, "Dominant colour family."),
                    "pattern": _enum(PATTERN_LABELS, "Dominant surface pattern."),
                    "apparent_material": _enum(
                        MATERIAL_LABELS,
                        "What the surface looks like. An appearance class only; "
                        "never a fibre-composition claim.",
                    ),
                    "confidence": _confidence("Confidence this garment is present."),
                },
            },
        },
    },
}

OUTFIT_RESPONSE_FORMAT = JsonSchemaFormat(
    name="outfit_detection", json_schema=OUTFIT_SCHEMA, strict=True
)


@dataclass(frozen=True, slots=True)
class DetectedGarment:
    """One garment read out of a photograph, with how to cut it out."""

    noun_phrase: str
    classification: CategorisationResult
    confidence: float


@dataclass(frozen=True, slots=True)
class OutfitDetection:
    """Everything one photograph turned out to contain."""

    worn: bool
    garments: tuple[DetectedGarment, ...]

    @property
    def is_single_garment(self) -> bool:
        """True when this is an ordinary one-garment photo after all.

        The caller uses this to fall back to the single-garment path rather
        than paying for a fan-out of one.
        """
        return not self.worn or len(self.garments) <= 1


class MetaOutfitDetector:
    """Lists the garments in a photograph, via the chat model."""

    def __init__(
        self,
        provider: Any,
        *,
        model: str = OUTFIT_MODEL,
        prompt_version: str = OUTFIT_PROMPT_VERSION,
    ) -> None:
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version

    def build_request(self, *, image: bytes, content_type: str) -> AIRequest:
        # Downscaled first, for the same reason the single-garment path does
        # it: a base64 data URI is counted as prompt text, so a full-size
        # photograph reserves about a million tokens against the minute
        # budget and the queue rate-limits itself after a handful of uploads.
        sent, sent_type = prepare_image(image, content_type=content_type)
        return AIRequest(
            model=self._model,
            system=OUTFIT_SYSTEM,
            messages=(
                AIMessage(
                    "user",
                    [
                        {"type": "text", "text": OUTFIT_USER_TEXT},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri(sent, content_type=sent_type)},
                        },
                    ],
                ),
            ),
            needs=Capabilities(
                text_in=True, image_in=True, text_out=True, structured_output=True
            ),
            response_format=OUTFIT_RESPONSE_FORMAT,
            max_completion_tokens=OUTFIT_MAX_TOKENS,
            temperature=OUTFIT_TEMPERATURE,
            prompt_version=self._prompt_version,
            purpose=OUTFIT_PURPOSE,
        )

    async def detect(
        self,
        *,
        image: bytes,
        content_type: str,
        user_id: uuid.UUID | None = None,
    ) -> OutfitDetection:
        import json

        response = await self._provider.complete(
            self.build_request(image=image, content_type=content_type),
            user_id=user_id,
        )
        try:
            payload = json.loads(response.text or "")
        except (TypeError, ValueError) as exc:
            raise ApiError(
                "The outfit detector did not return JSON.",
                code="outfit_detection_unreadable",
                status_code=502,
            ) from exc

        if not isinstance(payload, dict):
            raise ApiError(
                "The outfit detector returned something that is not an object.",
                code="outfit_detection_unreadable",
                status_code=502,
            )

        garments: list[DetectedGarment] = []
        for raw in (payload.get("items") or [])[:MAX_GARMENTS]:
            if not isinstance(raw, dict):
                continue
            phrase = str(raw.get("noun_phrase") or "").strip()
            if not phrase:
                continue
            # Constructing the result *is* the validation: `__post_init__`
            # refuses any label outside the closed sets, so nothing
            # out-of-taxonomy can reach the wardrobe however the model
            # phrases it. One confidence covers all five fields because the
            # detector reports presence rather than grading each attribute,
            # and inventing five separate numbers from one would overstate
            # what it actually said.
            confidence = float(raw.get("confidence") or 0.0)
            try:
                classification = CategorisationResult(
                    slot=str(raw.get("slot") or ""),
                    category=str(raw.get("category") or ""),
                    colour=str(raw.get("colour") or ""),
                    pattern=str(raw.get("pattern") or ""),
                    apparent_material=str(raw.get("apparent_material") or ""),
                    slot_confidence=confidence,
                    category_confidence=confidence,
                    colour_confidence=confidence,
                    pattern_confidence=confidence,
                    material_confidence=confidence,
                    model=self._model,
                    prompt_version=self._prompt_version,
                )
            except Exception:
                # One unreadable entry must not discard the rest of the
                # outfit; a photo yielding three of four garments is worth
                # far more than none.
                continue
            garments.append(
                DetectedGarment(
                    noun_phrase=phrase,
                    classification=classification,
                    confidence=confidence,
                )
            )

        return OutfitDetection(
            worn=bool(payload.get("worn")), garments=tuple(garments)
        )


__all__ = [
    "MAX_GARMENTS",
    "OUTFIT_MAX_TOKENS",
    "OUTFIT_MODEL",
    "OUTFIT_PROMPT_VERSION",
    "OUTFIT_PURPOSE",
    "OUTFIT_RESPONSE_FORMAT",
    "OUTFIT_SCHEMA",
    "OUTFIT_SYSTEM",
    "DetectedGarment",
    "crop_to_subject",
    "MetaOutfitDetector",
    "OutfitDetection",
]


def crop_to_subject(
    image: bytes, records: Any, *, margin: float = 0.06
) -> bytes:
    """Crop a cut-out down to the garment it contains.

    The compositor returns a full-frame image because the mask is expressed in
    the source photograph's coordinates. That is right for a single garment
    photographed alone, and wrong for a piece of an outfit: a pair of shoes
    isolated from a full-length photograph occupies perhaps 3% of the frame,
    so a wardrobe tile showing it is 97% empty ground and reads as broken.

    The margin is a fraction of the subject's own size rather than a fixed
    number of pixels, so a tote and a pair of shoes get visually comparable
    breathing room instead of the smaller one looking cramped.

    Returns the original bytes unchanged if there is nothing to crop to, since
    a slightly roomy tile beats a failed one.
    """
    boxes = [r.box for r in (records or []) if getattr(r, "box", None) is not None]
    if not boxes:
        return image

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard dependency
        return image

    with Image.open(io.BytesIO(image)) as opened:
        frame = opened.convert("RGB")
        width, height = frame.size

        left = max(0, min(b.x1 for b in boxes))
        top = max(0, min(b.y1 for b in boxes))
        right = min(width, max(b.x2 for b in boxes) + 1)
        bottom = min(height, max(b.y2 for b in boxes) + 1)
        if right <= left or bottom <= top:
            return image

        pad_x = round((right - left) * margin)
        pad_y = round((bottom - top) * margin)
        box = (
            max(0, left - pad_x),
            max(0, top - pad_y),
            min(width, right + pad_x),
            min(height, bottom + pad_y),
        )

        buffer = io.BytesIO()
        frame.crop(box).save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


# --------------------------------------------------------------------------- #
# the fan-out
# --------------------------------------------------------------------------- #
DETECT_OUTFIT_JOB_KIND = "wardrobe.detect_outfit"


async def detect_outfit(
    session: Any,
    job: Any,
    *,
    detector: MetaOutfitDetector,
    segmenter: Any,
    store: Any = None,
) -> dict[str, Any]:
    """Turn one photograph of a worn outfit into one garment per piece.

    The source photograph is never consumed: it stays exactly as uploaded, and
    each garment gets its *own* cut-out asset derived from it. So a detection
    that misreads one piece costs that piece, not the photo.

    Partial success is the normal outcome and is reported as such. A tote
    half-behind a hip may not segment cleanly while the shirt and trousers do,
    and three garments in the wardrobe is a far better answer than a failed
    job and none.
    """
    import sqlalchemy as sa

    from app.domain.jobs import guard_write
    from app.errors import CapabilityUnavailable
    from app.models.garment import Garment
    from app.models.media_asset import MediaAsset
    from app.providers.segmentation import (
        CUTOUT_BACKGROUND,
        CUTOUT_CONTENT_TYPE,
        SegmentationUnavailable,
    )
    from app.workers.categorise import UnavailableMediaStore, read_payload

    store = store or UnavailableMediaStore()
    payload = read_payload(job)

    asset = await guard_write(
        session,
        payload.asset_id,
        version=payload.asset_version,
        user_id=payload.user_id,
    )

    try:
        image = await store.read(asset)
    except CapabilityUnavailable as exc:
        return {"detected": False, "reason": exc.code}

    detection = await detector.detect(
        image=image,
        content_type=asset.content_type or CUTOUT_CONTENT_TYPE,
        user_id=payload.user_id,
    )

    if detection.is_single_garment:
        # Not a worn outfit after all. Falling through to the ordinary
        # single-garment path is cheaper and more accurate than fanning out
        # over one item, and leaves the existing categorise job to do its job.
        return {
            "detected": True,
            "worn": detection.worn,
            "garments": len(detection.garments),
            "reason": "single_garment",
        }

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for piece in detection.garments:
        classification = piece.classification
        try:
            result = await segmenter.cutout(
                image=image,
                prompt=piece.noun_phrase,
                content_type=asset.content_type or CUTOUT_CONTENT_TYPE,
                background=CUTOUT_BACKGROUND,
                user_id=payload.user_id,
                job_id=job.id,
            )
        except (SegmentationUnavailable, CapabilityUnavailable) as exc:
            # The garment is still real and still worth recording; it just
            # has no cut-out. It keeps the source photograph.
            result = None
            reason = exc.code
        else:
            reason = result.reason or ""

        cutout_asset_id = None
        if result is not None and result.image is not None:
            piece_image = crop_to_subject(result.image, result.records)
            key = f"{asset.storage_key or asset.id}/piece/{uuid.uuid4().hex[:12]}.png"
            try:
                await store.write(
                    key, piece_image, content_type=CUTOUT_CONTENT_TYPE
                )
                derived = MediaAsset(
                    user_id=asset.user_id,
                    kind=asset.kind,
                    status="ready",
                    content_type=CUTOUT_CONTENT_TYPE,
                    max_bytes=len(piece_image),
                    byte_size=len(piece_image),
                    storage_key=key,
                    version=1,
                    publication_consent=False,
                )
                session.add(derived)
                await session.flush()
                cutout_asset_id = derived.id
            except CapabilityUnavailable as exc:
                reason = exc.code

        # Each piece's own image is its cut-out, not the group photograph.
        #
        # They cannot all point `media_asset_id` at the source: a partial
        # unique index enforces one garment per photograph, which is right for
        # a flat lay (it stops a double-tap creating two rows) and wrong for a
        # worn photo that legitimately contains four garments. Pointing each
        # piece at its own cut-out satisfies the constraint honestly rather
        # than working around it, and it is also what the wardrobe should
        # show: the trousers, not the person wearing them.
        #
        # A piece with no cut-out gets NULL, which the index excludes, so an
        # unisolatable garment is still recorded rather than dropped.
        garment = Garment(
            user_id=payload.user_id,
            media_asset_id=cutout_asset_id,
            background_removed_asset_id=cutout_asset_id,
            name=piece.noun_phrase[:160],
            category=classification.category,
            availability="available",
            confirmed_attributes={},
            inferred_attributes=classification.inferred_attributes(),
            categorisation_confidence=classification.category_confidence,
            inference_confidence=classification.confidence,
            inference_version=OUTFIT_PROMPT_VERSION,
        )
        session.add(garment)
        await session.flush()

        entry = {
            "garment_id": str(garment.id),
            "name": garment.name,
            "slot": classification.slot,
            "category": classification.category,
            "cut_out": cutout_asset_id is not None,
        }
        if cutout_asset_id is None:
            entry["reason"] = reason or "no_subject_found"
            skipped.append(entry)
        created.append(entry)

    # The row the upload created stood for "a photograph of clothes". The
    # pieces now stand for the clothes, so leaving it would show the user a
    # fifth wardrobe item that is a picture of themselves. Soft-deleted, not
    # erased: the photograph it points at is untouched and is still the
    # evidence every piece was derived from.
    if created:
        await session.execute(
            sa.update(Garment)
            .where(Garment.id == payload.garment_id, Garment.deleted_at.is_(None))
            .values(deleted_at=sa.func.now())
        )

    await session.commit()

    return {
        "detected": True,
        "worn": True,
        "garments": len(created),
        "without_cutout": len(skipped),
        "items": created,
    }
