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
    record_categorisation,
)
from app.config import get_settings
from app.errors import ApiError
from app.providers.base import AIMessage, AIRequest, Capabilities, JsonSchemaFormat
from app.providers.segmentation import data_uri
from app.workers.categorise import prepare_image
from app.workers.shell_fit import fit_to_shell
from app.workers.render import (
    RENDER_MEDIA_KIND,
    GarmentRenderer,
)

#: Model and prompt version, recorded on every run so a change in behaviour
#: can be attributed to a change in the prompt.
OUTFIT_MODEL = "muse-spark-1.3"
OUTFIT_PROMPT_VERSION = "outfit-detect/v1"
OUTFIT_PURPOSE = "wardrobe.detect_outfit"

#: Raised from 4096 on 2026-10-29, against the expectation that it would come
#: down. `scripts/measure_detection.py` ran fourteen real photographs through
#: the live detector: completions ran 763 to **3460** tokens, mean 1549, which
#: left the old ceiling with 1.18x headroom on the worst case rather than the
#: generous margin it looked like.
#:
#: The worst case was a two-person photograph, and nothing stops somebody
#: uploading one. One token over and the model returns empty with
#: ``finish_reason: length`` — not an error naming the cause, which is the
#: failure this codebase has already shipped three times at 512, 1200 and
#: 2048.
#:
#: Reasoning is most of that completion (1453 of 1526 on a single dress) and
#: the vendor reports it as a breakdown of `completion_tokens` rather than in
#: addition to it, so this one number bounds both. Two times the measured
#: worst case, rounded up to the next power of two.
OUTFIT_MAX_TOKENS = 8192
OUTFIT_TEMPERATURE = 0.0

#: More than this in one photograph and the tail is almost always a
#: misreading: a belt loop counted as a belt, a shadow as a second shoe.
#: Capping also bounds the segmentation spend for one upload.
MAX_GARMENTS = 8

#: How much of a garment the photograph shows, worst case last.
#:
#: This decides whether the wardrobe gets a cut-out of the real garment or a
#: render of one like it, so it is a judgement about the *photograph*, not
#: about how confident the model is that the garment is there. A shirt almost
#: entirely behind a tote is `mostly_hidden` however certain the model is that
#: it is a shirt.
VISIBILITY_LABELS: tuple[str, ...] = ("clear", "partly_hidden", "mostly_hidden")

#: What a garment gets when the model declines to judge. The forgiving default:
#: it keeps the real cut-out, which is only wrong in the cases this feature
#: exists to catch, and never spends on a render that was not asked for.
DEFAULT_VISIBILITY = "clear"

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
    "'brown leather tote'. It must name one garment, never a list.\n"
    "\n"
    "`visibility` decides what the wardrobe ends up showing, so judge the "
    "photograph rather than your own certainty. Ask only this: if this "
    "garment were cut out along its visible edges and shown on its own, would "
    "it still look like the garment? Say 'clear' when its outline is "
    "essentially complete, 'partly_hidden' when something overlaps it but its "
    "shape still reads, and 'mostly_hidden' when the cut-out would be a "
    "fragment — a shirt behind a bag, trousers crossed by a desk. A garment "
    "you are certain about can still be mostly hidden."
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
                    "visibility",
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
                    "visibility": {
                        "type": "string",
                        "enum": list(VISIBILITY_LABELS),
                        "description": (
                            "How much of this garment the photograph actually "
                            "shows. 'clear' when its outline is essentially "
                            "complete. 'partly_hidden' when something overlaps "
                            "it but its shape still reads. 'mostly_hidden' "
                            "when cutting it out would leave a fragment that "
                            "does not read as the garment."
                        ),
                    },
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
    #: One of :data:`VISIBILITY_LABELS`.
    visibility: str = DEFAULT_VISIBILITY

    @property
    def needs_render(self) -> bool:
        """True when cutting this garment out would not produce the garment."""
        from app.workers.render import RENDER_WHEN_VISIBILITY

        return self.visibility in RENDER_WHEN_VISIBILITY


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
            reasoning_effort=get_settings().model_reasoning_effort,
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
                    # An unrecognised value falls back rather than raising: a
                    # garment is still worth recording when the only thing
                    # the model got wrong is how hidden it said it was.
                    visibility=(
                        raw.get("visibility")
                        if raw.get("visibility") in VISIBILITY_LABELS
                        else DEFAULT_VISIBILITY
                    ),
                )
            )

        return OutfitDetection(
            worn=bool(payload.get("worn")), garments=tuple(garments)
        )


__all__ = [
    "DEFAULT_VISIBILITY",
    "MAX_GARMENTS",
    "OUTFIT_MAX_TOKENS",
    "OUTFIT_MODEL",
    "OUTFIT_PROMPT_VERSION",
    "OUTFIT_PURPOSE",
    "OUTFIT_RESPONSE_FORMAT",
    "OUTFIT_SCHEMA",
    "OUTFIT_SYSTEM",
    "VISIBILITY_LABELS",
    "DetectedGarment",
    "MetaOutfitDetector",
    "OutfitDetection",
    "crop_to_subject",
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


async def _queue_packshots(
    session: Any,
    *,
    user_id: Any,
    made: list[dict[str, Any]],
    source_asset_id: Any,
    source_version: int | None,
) -> int:
    """Queue a wardrobe packshot for each piece. Returns how many.

    **This used to go through the Studio, and the picture was thrown
    away.** `garment_studio.request` produces a `GarmentShot` row -
    a shot somebody asked for on the Studio screen - and nothing
    ever pointed the garment at it. Measured on a real account: nine
    ready packshots, every one linked to a garment, and zero
    garments showing one. The wardrobe kept the segmentation cut-out
    it already had, which is why a pair of white trainers cut from a
    worn photograph appeared as half a shoe.

    So it queues the wardrobe's own packshot job, which repoints
    `background_removed_asset_id` when the picture lands. One
    mechanism produces the garment's picture; the Studio keeps
    making the shots people ask it for.

    **Never fails the detection.** The wardrobe already has its
    garments by the time this runs; a packshot is a better picture
    of one, not the thing itself. A studio that is down costs the
    nicer image and nothing else.
    """
    import logging

    from app.domain.jobs import enqueue
    from app.models.garment import Garment
    from app.workers.packshot import PACKSHOT_JOB_KIND

    queued = 0
    for item in made:
        # A piece nothing could be isolated from was never identified
        # well enough to ask for one by name.
        if not item.get("cut_out"):
            continue
        try:
            garment_id = uuid.UUID(item["garment_id"])
            garment = await session.get(Garment, garment_id)
            if garment is None:
                continue
            # **The original upload, never the cut-out.**
            #
            # A fan-out piece's `media_asset_id` points at its own
            # cut-out - the documented workaround for the one-
            # garment-per-upload index - and those cut-outs are
            # exactly what the packshot exists to improve on. Sending
            # one as the source re-staged a pixelated, part-occluded
            # silhouette and produced a speckled stone blob where a
            # pair of headphones should have been.
            #
            # The photograph is the only thing that still knows what
            # the garment looks like, so the edit reads that and is
            # told which piece to take out of it by name.
            await enqueue(
                session,
                PACKSHOT_JOB_KIND,
                {
                    "garment_id": str(garment_id),
                    "asset_id": str(source_asset_id),
                    "asset_version": source_version,
                    "user_id": str(user_id),
                    "subject": item.get("name") or "the garment",
                },
                idempotency_key=f"{PACKSHOT_JOB_KIND}:{garment_id}",
                # **No head start here.** The intake pipeline delays
                # its packshot so detection and categorisation can
                # settle what the photograph holds. On this path that
                # has already happened - this *is* detection - so a
                # delay would be dead time on a picture somebody is
                # watching a spinner for.
            )
            queued += 1
        except Exception:  # noqa: BLE001 - one piece must not cost the rest
            logging.getLogger(__name__).exception(
                "could not queue a packshot",
                extra={"garment": item["garment_id"]},
            )
    await session.commit()
    return queued


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
    renderer: GarmentRenderer | None = None,
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
        # Not a worn outfit after all, so there is nothing to fan out over.
        #
        # The classification is still written here rather than discarded. The
        # detector has already looked at this photograph and already named the
        # garment in the same closed vocabulary the classifier uses, so
        # leaving it to `categorise` meant paying a second model call for an
        # answer we were holding, and making the user wait out a second round
        # trip to be told it. `categorise` sees the garment is classified and
        # returns without calling anything.
        #
        # Only when the garment has no category yet. A user correction and an
        # earlier run both outrank this.
        sorted_now = False
        if detection.garments:
            piece = detection.garments[0]
            written = await record_categorisation(
                session,
                payload.garment_id,
                piece.classification,
                inference_version=OUTFIT_PROMPT_VERSION,
                only_if_unset=True,
            )
            if written:
                await session.commit()
                sorted_now = True

        return {
            "detected": True,
            "worn": detection.worn,
            "garments": len(detection.garments),
            "reason": "single_garment",
            "sorted_from_detection": sorted_now,
        }

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for piece in detection.garments:
        classification = piece.classification

        # Segmentation can only remove what it can see, so a garment the
        # photograph mostly hides has no cut-out worth having: the mask comes
        # back as a fragment and the wardrobe shows a shirt with a bag-shaped
        # hole in it. Those are drawn instead, from what was read off them,
        # and the cut-out is not attempted — it would be paid for and thrown
        # away.
        piece_image: bytes | None = None
        piece_content_type = CUTOUT_CONTENT_TYPE
        piece_kind = asset.kind
        rendered = False
        reason = ""

        if piece.needs_render and renderer is not None:
            try:
                drawing = await renderer.render(
                    noun_phrase=piece.noun_phrase,
                    classification=classification,
                    user_id=payload.user_id,
                )
            except Exception as exc:  # noqa: BLE001 - see below
                # Deliberately broad. Rendering is the fallback for a garment
                # that cannot be cut out; a fallback that can itself fail the
                # whole job is not one. Whatever went wrong — a refused
                # prompt, a quota, a decode — this piece falls through to the
                # cut-out, and a fragment of the real garment beats nothing.
                reason = getattr(exc, "code", type(exc).__name__)
            else:
                piece_image = drawing.data
                piece_content_type = drawing.content_type
                piece_kind = RENDER_MEDIA_KIND
                rendered = True
                reason = "rendered"

        if piece_image is None:
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
                reason = result.reason or reason or ""
            if result is not None and result.image is not None:
                # Cropped to the garment, then stood upright. A
                # pair of trousers cuts out tall and a pair of shoes
                # cuts out wide, so a wardrobe laid out from one
                # photograph had tiles in two different shapes.
                piece_image = fit_to_shell(
                    crop_to_subject(result.image, result.records),
                    content_type=piece_content_type,
                    portrait=True,
                )

        cutout_asset_id = None
        if piece_image is not None:
            suffix = "webp" if "webp" in piece_content_type else "png"
            key = (
                f"{asset.storage_key or asset.id}/piece/"
                f"{uuid.uuid4().hex[:12]}.{suffix}"
            )
            try:
                await store.write(
                    key, piece_image, content_type=piece_content_type
                )
                derived = MediaAsset(
                    user_id=asset.user_id,
                    # A render is labelled as one. Nothing downstream should
                    # be able to mistake a drawing for the user's photograph.
                    kind=piece_kind,
                    status="ready",
                    content_type=piece_content_type,
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
            # Only true when the stored picture really is a drawing: a render
            # that failed and fell back to a cut-out must not be badged as one.
            image_is_rendered=rendered and cutout_asset_id is not None,
        )
        session.add(garment)
        await session.flush()

        entry = {
            "garment_id": str(garment.id),
            "name": garment.name,
            "slot": classification.slot,
            "category": classification.category,
            "cut_out": cutout_asset_id is not None,
            "visibility": piece.visibility,
            "rendered": rendered,
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

    # One catalogue packshot per piece.
    #
    # **Only on this path, which is the worn one.** A photograph of a
    # garment already lying flat is a packshot; paying a model to
    # redraw it as one buys nothing. A photograph of somebody wearing
    # four things is the opposite case: the cut-outs are shaped round
    # a body, lit by whatever room they were standing in, and often
    # part-occluded by an arm.
    #
    # Per piece rather than one picture of the set, because these are
    # four wardrobe items and a grid showing the same image four
    # times is not a wardrobe. The studio's own packshot still groups
    # everything in its source, which is the right default there: it
    # is making one picture, not filling a cupboard.
    #
    # After the commit, deliberately. The garments are the result and
    # a packshot is an improvement on them, so a studio that is down
    # costs the nicer picture and nothing else.
    packshots = await _queue_packshots(
        session,
        user_id=payload.user_id,
        made=created,
        source_asset_id=payload.asset_id,
        source_version=payload.asset_version,
    )

    return {
        "detected": True,
        "worn": True,
        "packshots": packshots,
        "garments": len(created),
        "without_cutout": len(skipped),
        # Counted separately because it is a different claim about the
        # wardrobe: these tiles show a drawing of a garment like the user's,
        # not a picture of the user's.
        "rendered": sum(1 for item in created if item.get("rendered")),
        "items": created,
    }


# --------------------------------------------------------------------------- #
# the studio's split: one photograph, a picture per garment in it
# --------------------------------------------------------------------------- #
async def split_shots(
    session: Any,
    job: Any,
    *,
    detector: MetaOutfitDetector,
    segmenter: Any,
    store: Any = None,
) -> dict[str, Any]:
    """Shoot each garment in one photograph separately.

    **The studio groups by default and this is the exception.** Handed
    a photograph of a shirt and trousers, the packshot treatment
    returns one picture with both in it, laid out together, because
    the studio is making an image. This is for the other case: the
    same photograph wanted as two catalogue images, one per garment.

    **It never touches the wardrobe.** The intake path also splits a
    worn photograph, and that one creates a garment per piece because
    somebody is filling a cupboard. This one is somebody making
    pictures, often from a camera roll photo that is not theirs to
    own, so it writes cut-outs and shots and no `Garment` rows at all.

    Partial success is the normal outcome and is reported as such: a
    bag half behind a hip may not segment cleanly while the shirt and
    the trousers do, and two packshots beats a failed job and none.
    """
    import uuid as _uuid

    from app.domain import garment_studio
    from app.domain.jobs import guard_write
    from app.errors import CapabilityUnavailable
    from app.models.media_asset import MediaAsset
    from app.providers.segmentation import (
        CUTOUT_BACKGROUND,
        CUTOUT_CONTENT_TYPE,
        SegmentationUnavailable,
    )
    from app.workers.categorise import UnavailableMediaStore
    from app.workers.garment_studio import treatment_by_id

    store = store or UnavailableMediaStore()
    payload = job.payload or {}
    user_id = _uuid.UUID(str(payload["user_id"]))
    treatment = treatment_by_id(str(payload.get("treatment") or "packshot"))
    if treatment is None:
        return {"split": False, "reason": "bad_treatment"}
    brief = payload.get("brief") or None

    asset = await guard_write(
        session,
        _uuid.UUID(str(payload["asset_id"])),
        version=payload.get("asset_version"),
        user_id=user_id,
    )
    try:
        image = await store.read(asset)
    except CapabilityUnavailable as exc:
        return {"split": False, "reason": exc.code}

    detection = await detector.detect(
        image=image,
        content_type=asset.content_type or CUTOUT_CONTENT_TYPE,
        user_id=user_id,
    )
    if not detection.garments:
        return {"split": False, "reason": "no_garments", "shots": 0}

    if detection.is_single_garment:
        # One garment, so splitting is the same request as not
        # splitting - and doing it the long way would pay for a
        # segmentation first. Straight to the ordinary shot.
        shot = await garment_studio.request(
            session,
            user_id=user_id,
            treatment=treatment,
            asset_id=asset.id,
            brief=brief,
        )
        return {"split": False, "reason": "single_garment", "shots": 1,
                "shot_ids": [str(shot.id)]}

    made: list[str] = []
    skipped = 0
    for piece in detection.garments:
        try:
            result = await segmenter.cutout(
                image=image,
                prompt=piece.noun_phrase,
                content_type=asset.content_type or CUTOUT_CONTENT_TYPE,
                background=CUTOUT_BACKGROUND,
                user_id=user_id,
                job_id=job.id,
            )
        except (SegmentationUnavailable, CapabilityUnavailable):
            skipped += 1
            continue
        if result is None or result.image is None:
            skipped += 1
            continue

        piece_image = fit_to_shell(
            crop_to_subject(result.image, result.records),
            content_type=CUTOUT_CONTENT_TYPE,
            portrait=True,
        )
        suffix = "webp" if "webp" in CUTOUT_CONTENT_TYPE else "png"
        key = (
            f"{asset.storage_key or asset.id}/split/"
            f"{_uuid.uuid4().hex[:12]}.{suffix}"
        )
        try:
            await store.write(key, piece_image, content_type=CUTOUT_CONTENT_TYPE)
        except CapabilityUnavailable:
            skipped += 1
            continue

        derived = MediaAsset(
            user_id=asset.user_id,
            # The same kind the intake split writes. A cut-out of a
            # garment is evidence of a garment, and the kind is a
            # boundary: nothing that scans for clothes should pick up
            # an avatar source or a banner, and nothing here should
            # be mistaken for either.
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

        shot = await garment_studio.request(
            session,
            user_id=user_id,
            treatment=treatment,
            asset_id=derived.id,
            brief=brief,
        )
        made.append(str(shot.id))

    await session.commit()
    return {
        "split": True,
        "shots": len(made),
        "without_cutout": skipped,
        "shot_ids": made,
    }


SPLIT_SHOTS_JOB_KIND = "garment.studio_split"
