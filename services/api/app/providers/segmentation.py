"""Garment segmentation and cut-out compositing with ``sam-3.1`` (ADR-005).

Every constant here is a **verified vendor fact**, fetched from
``https://dev.meta.ai/docs`` on 2026-10-27, and several are not what the shape
of the rest of the Meta surface would lead you to guess:

* **There is no segmentation endpoint.** ``sam-3.1`` is served by the generic
  Responses API — ``POST https://api.meta.ai/v1/responses`` — not by a
  ``/segment`` path (``/docs/sam/overview``, ``/docs/sam/segmenting``).
* **The masks come back as special-token text inside ``output_text``.** Not
  polygons, not COCO RLE on the wire, not a base64 PNG, not a URL. One line per
  image (one per frame for video), each line a comma-separated list of
  ``id<|box…|><|mask…|>`` records (``/docs/sam/reading-segmentation``).
* **The mask payload is base85**, and the payload itself can contain ``!`` and
  ``~``, so the encoding marker is **only the first character** after ``H,W,``.
  A base64 regex does not match it. Meta ships the decoder as
  ``meta-sam-parser`` on PyPI; we use it rather than reverse-engineering the
  compression, because the published docs state the layout nowhere and a
  hand-rolled guess that *almost* works produces subtly wrong cut-outs.
* ``metadata.include_confidence`` is the **string** ``"true"``; other values
  return HTTP 400. ``metadata.mask_encoding`` is ``"one_bit"`` or ``"lossless"``.
* **A missing concept is a success, not an error**: ``response.completed`` with
  an empty ``output_text``. That is a first-class outcome here
  (:attr:`SegmentationResult.found` is ``False``) and must never be retried as
  though it were a failure — the retry costs $0.0025 and returns the same
  nothing.
* **One noun phrase per request.** ``"bus, bicycle"`` returns zero matches, so
  :func:`validate_noun_phrase` refuses list syntax locally rather than paying
  for an empty answer.
* **Results are non-deterministic**: box coordinates, mask edges, and
  occasionally which objects are found vary between runs. Cut-outs are therefore
  cached on a content hash, so a retried job reproduces the previous cut-out
  instead of silently producing a different one.
* $2.50 per 1,000 images, 3,000 RPM, **per team not per key** — so the
  reservation is keyed on the team, exactly as for the text models (ADR-007).

``muse-image-1.0`` is **disqualified** for this job and is not used, even as a
fallback: ``mask`` returns 400 ``unsupported_parameter``, the ``background``
response field is documented as "always ``opaque``" so it cannot emit alpha at
all, and the model "can rearrange the layout and redraw contents rather than
reproduce your inputs exactly" at "the generator's own resolution". A
re-synthesised garment is a different garment.

The original is never touched. A cut-out is an additional artifact; §5 requires
a usable original to survive when optional processing fails, and failure here is
expected often enough to design for — a white garment on a white background
returns no subject at all, and a hanger touching the shoulder line is likely to
merge into the subject.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.errors import ApiError, CapabilityUnavailable
from app.providers.base import (
    AIRunRecorder,
    InMemoryUsageStore,
    InvalidProviderRequest,
    UsageStore,
    image_cost_micro_minor,
)
from app.providers.meta import META_BASE_URL, META_MODELS, MetaProvider

logger = logging.getLogger(__name__)

#: Verified. The generic Responses API; there is no segmentation path.
RESPONSES_PATH = "/responses"

SAM_MODEL = "sam-3.1"

#: Verified: $2.50 / 1,000 images == 250_000 micro-minor units per image.
#: The catalogue in ``app.providers.meta`` is the single source; this restates it
#: for readers and asserts the two agree, so a price edit in one place cannot
#: leave the other silently wrong.
SAM_PRICE_MICRO_MINOR_PER_IMAGE = 250_000

#: Verified accepted values for ``metadata.mask_encoding``.
MASK_ENCODINGS: tuple[str, ...] = ("one_bit", "lossless")

#: Verified encoding markers, as they appear in the payload after ``H,W,``.
MARKER_LOSSLESS = "~"
MARKER_ONE_BIT = "!"

#: The only keys we send to ``/responses`` for a segmentation call. An
#: allowlist by name, for the same reason the chat body has one (ADR-007): a
#: filtered dict is one forgotten key away from a 400.
SEGMENTATION_BODY_ALLOWLIST: frozenset[str] = frozenset(
    {"model", "input", "metadata", "stream", "store"}
)

#: The warm off-white the app's surfaces use. A solid, theme-appropriate ground
#: rather than transparency: a PNG with alpha renders differently on every
#: surface it is composited onto, and a wardrobe grid wants one consistent one.
CUTOUT_BACKGROUND = "#F2EDE5"

#: Whether a cut-out gets a contact shadow, and how strong.
#:
#: This is not decoration. Depop A/B tested background removal with no shadow
#: and measured 9% adoption against flat listing and sales metrics; the
#: published diagnosis was that "without a shadow, products looked like they
#: were floating in space, unnatural and unconvincing. An image that looks too
#: artificially edited can undermine the trust that peer-to-peer selling
#: depends on." The same feature with a generated shadow returned +1.5% items
#: listed. So the hard cut-out on a flat ground is the version that failed,
#: and the shadow is what makes the cut-out usable rather than an extra
#: (ADR-019).
#:
#: A *contact* shadow, not a drop shadow: tight under the garment with no
#: horizontal offset, because a diagonal offset implies a light source the
#: photograph does not have and reads as a sticker on a page.
#:
#: All three numbers are ASSUMED and expressed as fractions of the image so
#: they hold at any resolution. Revisit with real garment photographs.
#: How far down the shadow sits, as a fraction of image height.
SHADOW_OFFSET_RATIO = 0.012
#: Blur radius, as a fraction of the shorter side. Soft enough to read as
#: contact rather than as a second, darker garment.
SHADOW_BLUR_RATIO = 0.018
#: Peak opacity. Past roughly 0.35 the garment starts to look like it is
#: floating above the page rather than resting on it, which is the problem
#: the shadow exists to solve.
SHADOW_OPACITY = 0.28
#: How far the shadow darkens the ground colour. Derived from the background
#: rather than fixed, so a shadow is never a grey smudge on warm paper: pure
#: black against #F2EDE5 reads as dirt.
SHADOW_DARKEN = 0.45

CUTOUT_CONTENT_TYPE = "image/png"

#: Versioned so an :class:`~app.models.ai_run.AIRun` can be traced back to the
#: exact prompt construction that produced it.
SEGMENTATION_PROMPT_VERSION = "segmentation_v1"

PURPOSE = "wardrobe.background_removal"

#: Characters that turn a noun phrase into a list or a question. Verified: a
#: list prompt returns zero matches and a question is unreliable.
_PROMPT_REJECTS = re.compile(r"[,;+/?!\n\r]|\band\b|\bor\b", re.IGNORECASE)
MAX_PROMPT_LENGTH = 80

#: A short noun phrase per closed category (``app.domain.garment_media``).
#: Chosen to be concrete nouns rather than our internal labels: "knitwear" is a
#: retail category, "knitted jumper" is a thing in a photograph.
CATEGORY_NOUN_PHRASE: Mapping[str, str] = {
    "shirt": "shirt",
    "tshirt": "t-shirt",
    "knitwear": "knitted jumper",
    "sweatshirt": "sweatshirt",
    "blouse": "blouse",
    "dress": "dress",
    "trousers": "trousers",
    "jeans": "jeans",
    "skirt": "skirt",
    "shorts": "shorts",
    "blazer": "blazer",
    "jacket": "jacket",
    "coat": "coat",
    "shoes": "shoes",
    "bag": "bag",
    "accessory": "accessory",
}

#: Fallback by slot when no category is known yet — categorisation and
#: background removal are independent jobs and either may run first.
SLOT_NOUN_PHRASE: Mapping[str, str] = {
    "tops": "top",
    "bottoms": "trousers",
    "outerwear": "jacket",
    "shoes": "shoes",
    "accessories": "accessory",
}

#: Weakest useful prompt. Documented to work less well than a concrete noun,
#: which is why categorisation is queued alongside background removal.
GENERIC_NOUN_PHRASE = "garment"

# One price, two readers. If the catalogue and this module ever disagree, the
# import fails here rather than a month of segmentation being billed at the
# wrong rate in the ledger.
assert (
    META_MODELS[SAM_MODEL].capabilities.price_micro_minor_per_image
    == SAM_PRICE_MICRO_MINOR_PER_IMAGE
), "sam-3.1 price disagrees with the Meta model catalogue"


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class SegmentationUnavailable(CapabilityUnavailable):
    """Segmentation cannot run in this build or with this configuration.

    Distinct from a provider *failure* because the response differs: a failure
    is worth retrying, a missing capability is not. Both leave the garment
    working on its original photograph.
    """

    code = "segmentation_unavailable"
    default_message = "Garment segmentation is not available in this build."


class InvalidSegmentationPrompt(InvalidProviderRequest):
    code = "invalid_segmentation_prompt"
    default_message = "A segmentation prompt must be one short noun phrase."


class MalformedSegmentation(ApiError):
    """The provider answered, but not in the documented grammar."""

    status_code = 502
    code = "malformed_segmentation"
    default_message = "The segmentation response could not be read."


# --------------------------------------------------------------------------- #
# the documented record shapes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True, kw_only=True)
class Box:
    """One detection box, in **source pixels** — verified, not normalised.

    ``frame_width`` / ``frame_height`` are the ``w=`` and ``h=`` fields, which
    exist precisely so coordinates can be mapped onto an image that has since
    been resized. ``x2``/``y2`` are inclusive, which is why the documented
    examples satisfy ``H == y2 - y1 + 1``.
    """

    x1: int
    y1: int
    x2: int
    y2: int
    frame_width: int
    frame_height: int
    confidence: float | None = None

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1 + 1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1 + 1)

    def intersects(self, other: Box) -> bool:
        return not (
            self.x2 < other.x1
            or other.x2 < self.x1
            or self.y2 < other.y1
            or other.y2 < self.y1
        )

    def scaled_to(self, width: int, height: int) -> Box:
        """Map onto an image of a different size, if the frame disagrees."""
        if (self.frame_width, self.frame_height) in ((width, height), (0, 0)):
            return self
        sx = width / self.frame_width
        sy = height / self.frame_height
        return Box(
            x1=round(self.x1 * sx),
            y1=round(self.y1 * sy),
            x2=round(self.x2 * sx),
            y2=round(self.y2 * sy),
            frame_width=width,
            frame_height=height,
            confidence=self.confidence,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MaskRecord:
    """One object: its box, and a row-major 0/1 raster of ``height x width``.

    The raster's extent is read from the parser's ``bounds``, never assumed to
    equal the box. The docs describe the two as independent even though all
    seven published examples have them equal, and the ``x=0;y=0`` carried on the
    mask token is always literally zero — placement comes from the paired box.
    """

    object_id: int
    box: Box
    height: int
    width: int
    encoding: str = MARKER_LOSSLESS
    #: ``height * width`` bytes, each 0 or 1, row-major.
    raster: bytes = b""
    confidence: float | None = None

    def __post_init__(self) -> None:
        expected = self.height * self.width
        if self.raster and len(self.raster) != expected:
            raise MalformedSegmentation(
                f"mask raster is {len(self.raster)} bytes, expected {expected} "
                f"for {self.height}x{self.width}"
            )

    @property
    def score(self) -> float:
        """Confidence, or zero when it was not requested."""
        return self.confidence if self.confidence is not None else 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class SegmentationResult:
    records: tuple[MaskRecord, ...] = ()
    model: str = SAM_MODEL
    response_id: str | None = None
    cost_micro_minor: int = 0
    #: True when the cut-out came from the cache and nothing was billed.
    cached: bool = False

    @property
    def found(self) -> bool:
        """Whether any object matched.

        ``False`` is a documented, billed, non-error outcome: a white garment on
        a white background returns no subject rather than a poor mask.
        """
        return bool(self.records)


@dataclass(frozen=True, slots=True, kw_only=True)
class CutoutResult:
    """A finished cut-out, or an honest account of why there isn't one.

    ``image is None`` is a *successful* outcome with ``reason`` set — the
    concept was absent, or the backend is not configured. The caller's correct
    response is to keep the original, not to retry, which is why this is a
    value rather than an exception.
    """

    #: PNG bytes of the garment on a solid ground, or ``None``.
    image: bytes | None = None
    provider: str = ""
    model: str = ""
    records: tuple[MaskRecord, ...] = ()
    cost_micro_minor: int = 0
    cached: bool = False
    #: ``None`` on success; otherwise a stable code such as ``no_subject_found``.
    reason: str | None = None
    response_id: str | None = None

    @property
    def found(self) -> bool:
        return self.image is not None


@runtime_checkable
class SegmentationProvider(Protocol):
    """One way to turn a photograph into a cut-out.

    An interface rather than a single class because the economics change with
    scale, and the switch should be configuration rather than a rewrite. At
    ``docs/performance/capacity.md`` scenario C — 9,000 uploads/day — ``sam-3.1``
    costs **$22/day**, which is not worth a GPU. At scenario D — 225,000
    uploads/day — the same unconditional segmentation costs **$562/day**, which
    is where a self-hosted model starts paying for itself. The trigger is a
    measurement, so the seam exists before the measurement does.

    Implementations:

    * :class:`MetaSamProvider` — the default, ``sam-3.1`` (ADR-005).
    * :class:`BiRefNetProvider` — the chosen self-host path. A stub.
    """

    name: str
    model: str

    async def cutout(
        self,
        *,
        image: bytes,
        prompt: str,
        content_type: str = ...,
        background: str = ...,
        user_id: uuid.UUID | None = ...,
        job_id: uuid.UUID | None = ...,
    ) -> CutoutResult: ...


# --------------------------------------------------------------------------- #
# prompt construction
# --------------------------------------------------------------------------- #
def validate_noun_phrase(prompt: str) -> str:
    """Refuse locally what the vendor answers with zero matches.

    Verified: a comma/semicolon/plus list returns no records at all, and
    commands and questions are unreliable. Each of those is $0.0025 and a round
    trip spent learning something we already knew.
    """
    # Checked on the *trimmed* string rather than the collapsed one: collapsing
    # whitespace first would turn "coat\nshoes" — a two-item list — into the
    # perfectly legitimate-looking "coat shoes".
    trimmed = str(prompt).strip()
    if not trimmed:
        raise InvalidSegmentationPrompt("A segmentation prompt cannot be empty.")
    if _PROMPT_REJECTS.search(trimmed):
        raise InvalidSegmentationPrompt(
            "sam-3.1 takes one concept per request: lists, questions and "
            "conjunctions return no matches. Make a separate call per garment.",
            detail={"prompt": trimmed[:MAX_PROMPT_LENGTH]},
        )
    text = " ".join(trimmed.split())
    if len(text) > MAX_PROMPT_LENGTH:
        raise InvalidSegmentationPrompt(
            f"A segmentation prompt is at most {MAX_PROMPT_LENGTH} characters; "
            "sam-3.1 wants a short noun phrase."
        )
    return text


def garment_noun_phrase(*, category: str | None = None, slot: str | None = None) -> str:
    """The noun phrase to segment a garment of this category or slot with."""
    if category:
        phrase = CATEGORY_NOUN_PHRASE.get(str(category).strip().lower())
        if phrase:
            return phrase
    if slot:
        phrase = SLOT_NOUN_PHRASE.get(str(slot).strip().lower())
        if phrase:
            return phrase
    return GENERIC_NOUN_PHRASE


def data_uri(image: bytes, *, content_type: str = "image/png") -> str:
    """A base64 ``data:`` URI, which the docs accept in place of a public URL.

    Preferred over a public URL: our originals are private, and handing the
    vendor a signed URL would widen who can read a user's photograph.
    """
    import base64

    return f"data:{content_type};base64,{base64.b64encode(image).decode('ascii')}"


def build_segmentation_body(
    *,
    prompt: str,
    image_url: str,
    mask_encoding: str = "one_bit",
    include_confidence: bool = True,
    stream: bool = False,
) -> dict[str, Any]:
    """The verified request body, assembled from named fields only.

    ``include_confidence`` is sent as the **string** ``"true"`` — a boolean
    returns HTTP 400. Nothing iterates a caller-supplied mapping, so a field
    added later cannot reach the wire without someone writing the line.
    """
    phrase = validate_noun_phrase(prompt)
    if mask_encoding not in MASK_ENCODINGS:
        raise InvalidProviderRequest(
            f"mask_encoding must be one of {MASK_ENCODINGS}, got {mask_encoding!r}"
        )
    if not image_url:
        raise InvalidProviderRequest("a segmentation request needs an image")

    metadata: dict[str, str] = {"mask_encoding": mask_encoding}
    if include_confidence:
        metadata["include_confidence"] = "true"

    body: dict[str, Any] = {
        "model": SAM_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": phrase},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
        "metadata": metadata,
        # Sent explicitly rather than relying on a default that could change:
        # a user's garment photograph is not ours to leave on a vendor's disk.
        "store": False,
    }
    if stream:
        body["stream"] = True

    leaked = set(body) - SEGMENTATION_BODY_ALLOWLIST
    if leaked:  # pragma: no cover - a programming error, not an input error
        raise InvalidProviderRequest(
            f"refusing to send non-allowlisted parameters: {sorted(leaked)}"
        )
    return body


# --------------------------------------------------------------------------- #
# reading the response
# --------------------------------------------------------------------------- #
def extract_output_text(payload: Mapping[str, Any]) -> str:
    """Join every ``output_text`` part of a Responses API payload.

    Tolerant of a top-level ``output_text`` convenience field because the SDKs
    synthesise one, but the ``output`` array is the documented source.
    """
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for part in item.get("content") or []:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                chunks.append(str(part.get("text") or ""))
    if not chunks:
        direct = payload.get("output_text")
        if isinstance(direct, str):
            chunks.append(direct)
    return "".join(chunks)


@runtime_checkable
class SegmentationParser(Protocol):
    """Turns one image's special-token line into typed records.

    A protocol so the unit suite injects a stub and needs neither the vendor
    package nor a network stack. The deployed implementation is
    :class:`MetaSamParser`.
    """

    def parse(self, text: str) -> tuple[MaskRecord, ...]: ...


class MetaSamParser:
    """Adapter over Meta's own parser — ``meta-sam-parser`` on PyPI.

    The payload's base85 variant and compression are **not stated** anywhere in
    the published docs; ``/docs/sam/reading-segmentation`` directs the reader to
    ``decode_mask_to_raster`` instead. So this delegates rather than guessing: a
    hand-rolled decoder that is 95% right yields cut-outs with torn edges and no
    error to point at.

    Pin ``>= 0.0.6``. Earlier releases report every line carrying a ``c=``
    confidence as malformed and return no records, which looks exactly like
    "the model found nothing".

    The attribute names used below (``parse_image_stream``,
    ``decode_mask_to_raster``, ``record.mask``, ``mask.bounds``) are the ones the
    published docs name. They are **unverified at runtime** in this build: the
    package is not installed here, so the import failure degrades to
    :class:`SegmentationUnavailable` and the garment keeps its original.
    """

    #: The constraint to keep in sync with pyproject.
    REQUIREMENT = "meta-sam-parser>=0.0.6"

    def __init__(self, module: Any | None = None) -> None:
        self._module = module

    def module(self) -> Any:
        if self._module is None:
            try:
                import meta_sam_parser  # type: ignore[import-not-found]
            except ImportError as exc:
                raise SegmentationUnavailable(
                    "Mask decoding needs Meta's parser; install "
                    f"{self.REQUIREMENT}.",
                    detail={"requirement": self.REQUIREMENT},
                ) from exc
            self._module = meta_sam_parser
        return self._module

    def parse(self, text: str) -> tuple[MaskRecord, ...]:
        if not text.strip():
            return ()
        module = self.module()
        try:
            parsed = module.parse_image_stream(text)
            records: list[MaskRecord] = []
            for item in parsed:
                box = item.box
                mask = item.mask
                # The bounds' origin is intentionally discarded: the docs state
                # placement comes from the paired box, and the mask token's
                # ``x=0;y=0`` is always literally zero.
                _origin_y, _origin_x, height, width = _bounds_of(mask)
                raster = bytes(module.decode_mask_to_raster(mask))
                records.append(
                    MaskRecord(
                        object_id=int(getattr(item, "object_id", 0) or 0),
                        box=Box(
                            x1=int(box.x1),
                            y1=int(box.y1),
                            x2=int(box.x2),
                            y2=int(box.y2),
                            frame_width=int(getattr(box, "w", 0) or 0),
                            frame_height=int(getattr(box, "h", 0) or 0),
                            confidence=_confidence_of(box),
                        ),
                        height=height,
                        width=width,
                        encoding=str(getattr(mask, "encoding", MARKER_LOSSLESS)),
                        raster=raster,
                        confidence=_confidence_of(mask) or _confidence_of(box),
                    )
                )
        except SegmentationUnavailable:
            raise
        except MalformedSegmentation:
            raise
        except Exception as exc:  # any parser surprise is one outcome
            raise MalformedSegmentation(
                f"{type(exc).__name__} while reading the segmentation response"
            ) from exc
        return tuple(records)


def _bounds_of(mask: Any) -> tuple[int, int, int, int]:
    """``(top, left, height, width)`` of a parsed mask's raster extent."""
    bounds = getattr(mask, "bounds", None)
    if bounds is None:
        return (0, 0, int(mask.height), int(mask.width))
    if isinstance(bounds, Mapping):
        return (
            int(bounds.get("y", 0)),
            int(bounds.get("x", 0)),
            int(bounds.get("height", bounds.get("h", 0))),
            int(bounds.get("width", bounds.get("w", 0))),
        )
    return (
        int(getattr(bounds, "y", 0)),
        int(getattr(bounds, "x", 0)),
        int(getattr(bounds, "height", getattr(bounds, "h", 0))),
        int(getattr(bounds, "width", getattr(bounds, "w", 0))),
    )


def _confidence_of(token: Any) -> float | None:
    for name in ("confidence", "c"):
        value = getattr(token, name, None)
        if value is not None:
            return float(value)
    return None


# --------------------------------------------------------------------------- #
# choosing records, and compositing
# --------------------------------------------------------------------------- #
def select_records(records: Sequence[MaskRecord]) -> tuple[MaskRecord, ...]:
    """The highest-confidence record, plus anything overlapping it.

    ASSUMED heuristic, chosen against two documented failure modes that pull in
    opposite directions:

    * A hanger touching the shoulder line **merges into the subject**, and other
      furniture in the frame comes back as its own record. Unioning everything
      would paste the room into the cut-out — hence "highest confidence first".
    * A garment occluded in the middle (a belt, a folded sleeve) comes back as
      **two records of the same garment**. Taking only the best one would crop
      half the coat — hence "plus anything overlapping".

    Overlap is the discriminator because a second record of the same garment
    shares its bounding area while an unrelated object in the frame does not.
    """
    if not records:
        return ()
    ordered = sorted(records, key=lambda r: (r.score, r.box.width * r.box.height), reverse=True)
    best = ordered[0]
    chosen = [best]
    chosen.extend(other for other in ordered[1:] if other.box.intersects(best.box))
    return tuple(chosen)


def composite_cutout(
    *,
    original: bytes,
    records: Sequence[MaskRecord],
    background: str = CUTOUT_BACKGROUND,
    shadow: bool = True,
) -> bytes:
    """Paste the masked garment onto a solid ground and return PNG bytes.

    The original bytes are read, never written: the return value is new bytes
    for a new asset.

    ``shadow`` adds the contact shadow and defaults on, because a cut-out
    without one measurably underperforms (see :data:`SHADOW_OPACITY`). It is a
    parameter only so a test can assert the difference.
    """
    try:
        from PIL import Image, ImageChops
    except ImportError as exc:  # pragma: no cover - Pillow is a hard dependency
        raise SegmentationUnavailable(
            "Cut-out compositing needs Pillow; install pillow>=10."
        ) from exc

    if not records:
        raise SegmentationUnavailable(
            "No mask to composite.", detail={"reason": "no_subject"}
        )

    with Image.open(io.BytesIO(original)) as opened:
        source = opened.convert("RGB")
        size = source.size

        combined = Image.new("L", size, 0)
        for record in records:
            box = record.box.scaled_to(*size)
            if record.width <= 0 or record.height <= 0 or not record.raster:
                continue
            patch = Image.frombytes(
                "L",
                (record.width, record.height),
                bytes(255 if value else 0 for value in record.raster),
            )
            # The docs describe the raster extent as independent of the box, so
            # the two are reconciled rather than assumed equal. NEAREST keeps a
            # binary mask binary.
            if patch.size != (box.width, box.height) and box.width and box.height:
                patch = patch.resize((box.width, box.height), Image.NEAREST)
            layer = Image.new("L", size, 0)
            layer.paste(patch, (box.x1, box.y1))
            combined = ImageChops.lighter(combined, layer)

        if not combined.getbbox():
            raise SegmentationUnavailable(
                "The decoded mask selected no pixels.",
                detail={"reason": "empty_mask"},
            )

        canvas = Image.new("RGB", size, background)
        if shadow:
            _paint_contact_shadow(canvas, combined, background=background)
        canvas.paste(source, (0, 0), combined)

        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def _shadow_colour(background: str) -> tuple[int, int, int]:
    """A darker version of the ground, so the shadow stays in the same family."""
    from PIL import ImageColor

    red, green, blue = ImageColor.getrgb(background)[:3]
    return (
        int(red * SHADOW_DARKEN),
        int(green * SHADOW_DARKEN),
        int(blue * SHADOW_DARKEN),
    )


def _paint_contact_shadow(canvas: Any, mask: Any, *, background: str) -> None:
    """Paint the garment's shadow onto ``canvas``, in place, beneath it.

    Built from the garment's own silhouette rather than an ellipse, because a
    generic blob under a specific shape is exactly the "artificially edited"
    look the shadow is there to avoid.

    Clipping at the bottom edge is correct and deliberate: a garment
    photographed to the edge of frame has nowhere for its shadow to fall.
    """
    from PIL import Image, ImageFilter

    width, height = canvas.size
    offset = max(1, round(height * SHADOW_OFFSET_RATIO))
    blur = max(1.0, min(width, height) * SHADOW_BLUR_RATIO)

    # Blur first, then shift. Shifting a hard mask and blurring afterwards
    # bleeds the shadow symmetrically above the garment too, which looks like
    # a halo rather than contact.
    softened = mask.filter(ImageFilter.GaussianBlur(blur))

    shifted = Image.new("L", canvas.size, 0)
    shifted.paste(softened, (0, offset))

    peak = round(255 * SHADOW_OPACITY)
    alpha = shifted.point(lambda value: value * peak // 255)

    canvas.paste(Image.new("RGB", canvas.size, _shadow_colour(background)), (0, 0), alpha)


# --------------------------------------------------------------------------- #
# caching, because the model is not deterministic
# --------------------------------------------------------------------------- #
def content_key(image: bytes, *, prompt: str, mask_encoding: str) -> str:
    """A cache key over the exact inputs that determine the cut-out."""
    digest = hashlib.sha256()
    digest.update(hashlib.sha256(image).digest())
    digest.update(b"\x00")
    digest.update(prompt.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(mask_encoding.encode("ascii"))
    return digest.hexdigest()


@runtime_checkable
class SegmentationCache(Protocol):
    def get(self, key: str) -> tuple[MaskRecord, ...] | None: ...
    def put(self, key: str, records: tuple[MaskRecord, ...]) -> None: ...


@dataclass(slots=True)
class InMemorySegmentationCache:
    """Process-local cache.

    Enough to make a retried job reproduce its own cut-out, which is the
    property that matters: the model is documented as non-deterministic, so an
    unguarded retry silently replaces a cut-out the user already saw.
    """

    entries: dict[str, tuple[MaskRecord, ...]] = field(default_factory=dict)

    def get(self, key: str) -> tuple[MaskRecord, ...] | None:
        return self.entries.get(key)

    def put(self, key: str, records: tuple[MaskRecord, ...]) -> None:
        self.entries[key] = records


# --------------------------------------------------------------------------- #
# the provider
# --------------------------------------------------------------------------- #
class MetaSamProvider:
    """``sam-3.1`` as one adapter, following the :class:`MetaProvider` pattern.

    The default implementation of :class:`SegmentationProvider`.

    Reserve, call, reconcile, record — in that order, and keyed on the **team**,
    because Meta's limits are per team and two keys on one team share one budget
    (ADR-007). An :class:`~app.models.ai_run.AIRun` is mandatory: a $2.50/1000
    call nobody can attribute is a cost nobody can explain.

    ``http`` is injected so the unit suite needs neither a credential nor a
    network stack. Auth and rate limits are taken from a :class:`MetaProvider`
    rather than restated, so there is one definition of each.

    **Known quality limit, stated plainly.** ``sam-3.1`` is a *saliency and
    detection* model, not a matting model. Semi-transparent fabric — lace,
    chiffon, mesh, organza — comes back effectively opaque: the mask is binary,
    so a veil becomes a solid shape. No user-facing copy may claim otherwise.
    True alpha for sheer fabric needs a matting model, which is the one thing
    :class:`BiRefNetProvider`'s Matting variant would add over this.
    """

    name = "meta"
    model = SAM_MODEL

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = META_BASE_URL,
        team_id: str = "default",
        http: Any | None = None,
        usage: UsageStore | None = None,
        recorder: AIRunRecorder | None = None,
        parser: SegmentationParser | None = None,
        cache: SegmentationCache | None = None,
        meta: MetaProvider | None = None,
        mask_encoding: str = "one_bit",
        include_confidence: bool = True,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._usage: UsageStore = usage or InMemoryUsageStore()
        self._recorder = recorder
        self._parser: SegmentationParser = parser or MetaSamParser()
        self._cache: SegmentationCache = cache or InMemorySegmentationCache()
        self._mask_encoding = mask_encoding
        self._include_confidence = include_confidence
        self._timeout_seconds = timeout_seconds
        self.team_id = team_id
        self._meta = meta or MetaProvider(
            api_key=api_key, base_url=base_url, team_id=team_id
        )

    # -- declared facts ---------------------------------------------------- #
    @property
    def spec(self) -> Any:
        return META_MODELS[SAM_MODEL]

    @property
    def capabilities(self) -> Any:
        return self.spec.capabilities

    def segmentation_url(self) -> str:
        return f"{self._base_url}{RESPONSES_PATH}"

    def auth_headers(self) -> dict[str, str]:
        return self._meta.auth_headers()

    def cost_micro_minor(self, images: int = 1) -> int:
        return image_cost_micro_minor(self.capabilities, images=images)

    def client(self) -> Any:
        """A plain ``httpx.AsyncClient``.

        Direct HTTP rather than the ``openai`` SDK, for the same reason
        ``/asr/transcribe`` is a direct call: the body carries string-valued
        ``metadata`` and ``{"type": "message"}`` input items, and the response
        body is special-token text rather than a typed object. Owning the bytes
        is what makes the allowlist assertion meaningful.
        """
        if self._http is None:
            import httpx

            self._http = httpx.AsyncClient(timeout=self._timeout_seconds)
        return self._http

    # -- the call ---------------------------------------------------------- #
    async def segment(
        self,
        *,
        image: bytes,
        prompt: str,
        content_type: str = CUTOUT_CONTENT_TYPE,
        user_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
    ) -> SegmentationResult:
        """Segment one image with one noun phrase.

        Refuses before the network on a bad prompt; returns a result with
        ``found=False`` when the concept is absent, because that is what the
        vendor returns and retrying it buys the same nothing twice.
        """
        phrase = validate_noun_phrase(prompt)
        key = content_key(image, prompt=phrase, mask_encoding=self._mask_encoding)

        cached = self._cache.get(key)
        if cached is not None:
            return SegmentationResult(records=cached, cached=True)

        if self._recorder is None:
            raise RuntimeError(
                "MetaSegmentationProvider.segment requires an AIRunRecorder: an "
                "unaccounted model call is a cost nobody can attribute"
            )

        body = build_segmentation_body(
            prompt=phrase,
            image_url=data_uri(image, content_type=content_type),
            mask_encoding=self._mask_encoding,
            include_confidence=self._include_confidence,
        )

        cost = self.cost_micro_minor(1)
        reservation = await self._usage.reserve(
            team_id=self.team_id,
            model=SAM_MODEL,
            # Verified: billed per image, with no tokens-per-minute limit.
            tokens=0,
            micro_minor=cost,
            limits=self._meta.limits_for(self.spec),
        )
        run = await self._recorder.start(
            user_id=user_id,
            provider=self.name,
            model=SAM_MODEL,
            prompt_version=SEGMENTATION_PROMPT_VERSION,
            purpose=PURPOSE,
            team_id=self.team_id,
            reservation_id=reservation.id,
            currency=self.capabilities.currency,
        )
        if job_id is not None:
            run.job_id = job_id

        try:
            response = await self.client().post(
                self.segmentation_url(), headers=self.auth_headers(), json=body
            )
            response.raise_for_status()
            payload = response.json()
            records = self._parser.parse(extract_output_text(payload))
        except Exception as exc:
            await self._usage.release(reservation)
            await self._recorder.fail(run, code=type(exc).__name__, message=str(exc))
            raise

        await self._usage.reconcile(reservation, tokens=0, micro_minor=cost)
        await self._recorder.finish(
            run,
            images=1,
            cost_micro_minor=cost,
            # An empty answer was still a billed image; recording it as
            # succeeded with zero records is the honest row.
            finish_reason=str(payload.get("status") or "completed"),
            response_id=str(payload.get("id") or "") or None,
        )
        self._cache.put(key, records)
        return SegmentationResult(
            records=records,
            response_id=str(payload.get("id") or "") or None,
            cost_micro_minor=cost,
        )

    async def cutout(
        self,
        *,
        image: bytes,
        prompt: str,
        content_type: str = CUTOUT_CONTENT_TYPE,
        background: str = CUTOUT_BACKGROUND,
        user_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
    ) -> CutoutResult:
        """Segment, then composite.

        ``image is None`` with ``reason="no_subject_found"`` is deliberate rather
        than an exception: a missing concept is a documented, billed, successful
        response and the caller's correct move is to keep the original.
        """
        result = await self.segment(
            image=image,
            prompt=prompt,
            content_type=content_type,
            user_id=user_id,
            job_id=job_id,
        )
        common = {
            "provider": self.name,
            "model": SAM_MODEL,
            "records": result.records,
            "cost_micro_minor": result.cost_micro_minor,
            "cached": result.cached,
            "response_id": result.response_id,
        }
        if not result.found:
            return CutoutResult(image=None, reason="no_subject_found", **common)
        chosen = select_records(result.records)
        return CutoutResult(
            image=composite_cutout(
                original=image, records=chosen, background=background
            ),
            **common,
        )


#: Kept so an existing import keeps working; ``MetaSamProvider`` is the name.
MetaSegmentationProvider = MetaSamProvider


class BiRefNetProvider:
    """Self-hosted BiRefNet. **PLANNED** — not configured, and it refuses.

    Recorded here so the choice is reviewable before anyone needs it, and so
    nobody re-derives it under deadline. It is a stub on purpose: a stub that
    refuses is honest, and a fabricated mask would read as a live integration.

    **Why BiRefNet and not one of the obvious alternatives.**

    * **Licence.** MIT — genuinely commercial-safe, which most of this field is
      not. It is also where Microsoft's own Azure background-removal retirement
      notice points users.
    * **Independently evaluated.** Cloudflare's August 2025 evaluation over
      7,000+ images measured IoU 0.87 / Dice 0.92, against U²-Net collapsing to
      IoU 0.39 on DIS5K. An independent evaluation, not the authors' own.
    * **The finding that decides it for a wardrobe.** On a grey T-shirt, U²-Net
      and IS-Net labelled *only the printed logo* as the salient object and
      returned a mask that omitted the rest of the garment. BiRefNet captured
      the whole shirt. Printed and graphic garments are ordinary in a wardrobe,
      so that is a disqualifying failure rather than a quality quibble.

    **Models that look applicable and are not.** ``u2net_human_seg`` and MODNet
    are *person/portrait* segmentation. A garment photographed flat on a table
    contains no person, so they return nothing useful — which is also why the
    popular React Native "background remover" packages are useless here: they
    wrap on-device selfie segmentation.

    **A licence trap, if ``rembg`` is ever used — including in a fixture.**
    ``rembg``'s default model is now ``bria-rmbg``, **not** ``u2net``: a bare
    ``remove(img)`` silently loads BRIA weights. RMBG-1.4 is non-commercial and
    its licence specifically prohibits "hosting the Foundation Model for access
    or use by others", which is exactly what this app would be doing. RMBG-2.0
    is CC BY-NC behind a checkbox attesting non-commercial use; ticking that for
    a commercial product is a false attestation, which is worse than a bare
    breach. **Never call ``remove()`` without an explicit model argument.**
    Commercial-safe choices are ``u2net``/``u2netp`` and ``isnet-general-use``
    (Apache 2.0) or ``birefnet-*`` (MIT).

    **Quality limit it shares with every option in this class.** These are
    saliency models. Semi-transparent fabric returns effectively opaque from all
    of them except BiRefNet's *Matting* variant. No user-facing copy may promise
    otherwise.
    """

    name = "birefnet"
    model = "birefnet-general"

    #: MIT. Recorded next to the name so a reviewer does not have to look.
    LICENCE = "MIT"

    def __init__(self, *, endpoint: str | None = None) -> None:
        self.endpoint = endpoint

    async def cutout(
        self,
        *,
        image: bytes,
        prompt: str,
        content_type: str = CUTOUT_CONTENT_TYPE,
        background: str = CUTOUT_BACKGROUND,
        user_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
    ) -> CutoutResult:
        raise SegmentationUnavailable(
            "Self-hosted BiRefNet segmentation is not configured in this build.",
            detail={
                "provider": self.name,
                "model": self.model,
                "licence": self.LICENCE,
                "status": "planned",
            },
        )


#: Name → constructor, for a config-driven swap. ``sam-3.1`` is the default
#: because at current volume it is $22/day and a GPU is not.
SEGMENTATION_PROVIDERS: Mapping[str, type] = {
    "meta_sam": MetaSamProvider,
    "birefnet": BiRefNetProvider,
}

DEFAULT_SEGMENTATION_PROVIDER = "meta_sam"


__all__ = [
    "CATEGORY_NOUN_PHRASE",
    "CUTOUT_BACKGROUND",
    "SHADOW_BLUR_RATIO",
    "SHADOW_DARKEN",
    "SHADOW_OFFSET_RATIO",
    "SHADOW_OPACITY",
    "CUTOUT_CONTENT_TYPE",
    "DEFAULT_SEGMENTATION_PROVIDER",
    "GENERIC_NOUN_PHRASE",
    "MARKER_LOSSLESS",
    "MARKER_ONE_BIT",
    "MASK_ENCODINGS",
    "MAX_PROMPT_LENGTH",
    "PURPOSE",
    "RESPONSES_PATH",
    "SAM_MODEL",
    "SAM_PRICE_MICRO_MINOR_PER_IMAGE",
    "SEGMENTATION_BODY_ALLOWLIST",
    "SEGMENTATION_PROMPT_VERSION",
    "SEGMENTATION_PROVIDERS",
    "SLOT_NOUN_PHRASE",
    "BiRefNetProvider",
    "Box",
    "CutoutResult",
    "InMemorySegmentationCache",
    "InvalidSegmentationPrompt",
    "MalformedSegmentation",
    "MaskRecord",
    "MetaSamParser",
    "MetaSamProvider",
    "MetaSegmentationProvider",
    "SegmentationCache",
    "SegmentationParser",
    "SegmentationProvider",
    "SegmentationResult",
    "SegmentationUnavailable",
    "build_segmentation_body",
    "composite_cutout",
    "content_key",
    "data_uri",
    "extract_output_text",
    "garment_noun_phrase",
    "select_records",
    "validate_noun_phrase",
]
