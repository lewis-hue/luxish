"""Auto-categorisation and background removal, as durable jobs.

Neither handler here may run in a request handler. Both call a paid model, and
Cloud Run request timeouts make an inline model call a liability (ADR-013) —
which is why the enqueue path in ``app.domain.garment_media`` is the only way
these are started.

**The label set is closed, and closure is a schema, not a hope.** The classifier
sends a strict ``JsonSchemaFormat`` whose ``slot``, ``category``, ``colour``,
``pattern`` and ``apparent_material`` properties are ``enum``s, with
``"unknown"`` as a member so the model has an honest answer available. Strict
structured output requires a root object with ``additionalProperties: false``
(verified, ADR-007), so the shape is refused at construction if it drifts. What
the model returns is then re-validated against the same Python tuples, because a
provider's schema enforcement is a claim we do not have to take on faith.

**Everything written lands in ``inferred_attributes``.** ADR-010: a user
correction always wins, and the way to guarantee that is to have no code path
that can write ``confirmed_attributes`` from here. ``record_categorisation``
emits one UPDATE and asserts its own column list.

**Background removal degrades; it never blocks.** §5 requires a usable original
to survive when optional processing fails, and failure is the expected case
often enough to design for: no storage backend configured, Meta's parser not
installed, a white garment on a white background returning no subject. Each of
those completes the job with ``background_removed: false`` and leaves the
garment working on the photograph the user took. Only a *transient* fault — a
502, a timeout, a torn response — raises, because only a transient fault is
worth the queue's backoff.

**The write is guarded, twice.** ``guard_write`` runs before the paid call (so we
do not pay to process a deleted photograph) and again in the same transaction as
the write (because a delete can land in between — that is the whole point of
ADR-012). A late job therefore cannot resurrect deleted content.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.garment_media import (
    BACKGROUND_REMOVAL_JOB_KIND,
    CATEGORISE_JOB_KIND,
    CATEGORY_LABELS,
    COLOUR_LABELS,
    MATERIAL_LABELS,
    PATTERN_LABELS,
    SLOT_LABELS,
    CategorisationResult,
    parse_categorisation,
    record_categorisation,
)
from app.domain.jobs import AssetGone, guard_write
from app.errors import ApiError, CapabilityUnavailable
from app.models.garment import Garment
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.providers.base import AIMessage, AIRequest, Capabilities, JsonSchemaFormat
from app.providers.segmentation import (
    CUTOUT_BACKGROUND,
    CUTOUT_CONTENT_TYPE,
    SegmentationProvider,
    SegmentationUnavailable,
    data_uri,
    garment_noun_phrase,
)

logger = logging.getLogger(__name__)

#: Bumped whenever the prompt or the schema changes, and recorded on every
#: :class:`~app.models.ai_run.AIRun` so an output can be traced to what produced
#: it (ADR-010's auditability half).
CATEGORISATION_PROMPT_VERSION = "garment_categorisation_v1"

CATEGORISATION_PURPOSE = "wardrobe.categorise"

#: The default text model: image in, text out, strict structured output.
CATEGORISATION_MODEL = "muse-spark-1.3"

#: A classification is five short labels and five numbers. A generous ceiling
#: here is only a bill.
#: Output budget for one classification.
#:
#: 2048 rather than a figure sized to the JSON, which is about 200 characters.
#: The cap covers **reasoning tokens too**, and `muse-spark-1.3` spends them
#: before it emits anything. At 512 it consumed the entire budget thinking and
#: returned `finish_reason: "length"` with an empty string, so every
#: classification failed with "did not return JSON" while the accounting
#: recorded a successful 512-token call. The failure looked like a parsing bug
#: and was a budget bug.
#:
#: Measured, not guessed: 512 returns nothing, 2048 returns the complete
#: object with room to spare.
CATEGORISATION_MAX_TOKENS = 2048

#: Deterministic as the provider allows. Classification is not a creative task,
#: and the drift this whole module exists to prevent is partly sampling drift.
CATEGORISATION_TEMPERATURE = 0.0

#: Longest edge of the image actually sent, in pixels.
#:
#: Not a cosmetic economy. ``AIRequest.estimated_prompt_tokens`` sizes the
#: team's usage reservation by counting the rendered message content, and a
#: base64 data URI *is* that content — so a 3 MB photograph reserves roughly
#: 1,000,000 tokens against a 4,000,000-per-minute team budget, and the queue
#: rate-limits itself after four garments. 768px is also plainly enough to tell
#: a blazer from a bag, and it cuts the per-call token bill by the same factor.
#: ASSUMED; the number to revisit against measured label accuracy.
CATEGORISATION_MAX_IMAGE_EDGE = 768

#: JPEG quality for the downscaled copy. Classification reads shape, colour
#: family and weave; it does not read print detail.
CATEGORISATION_JPEG_QUALITY = 85


def prepare_image(
    image: bytes,
    *,
    content_type: str,
    max_edge: int = CATEGORISATION_MAX_IMAGE_EDGE,
) -> tuple[bytes, str]:
    """Downscale an original for classification. Never mutates the input.

    Degrades to the original bytes on any failure — an unreadable or exotic
    image should still get a chance at the model, and a refusal here would
    block a garment over an optimisation.
    """
    try:
        import io

        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard dependency
        return image, content_type
    try:
        with Image.open(io.BytesIO(image)) as opened:
            if max(opened.size) <= max_edge:
                return image, content_type
            frame = opened.convert("RGB")
            frame.thumbnail((max_edge, max_edge), Image.LANCZOS)
            buffer = io.BytesIO()
            frame.save(
                buffer,
                format="JPEG",
                quality=CATEGORISATION_JPEG_QUALITY,
                optimize=True,
            )
            return buffer.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 - a resize failure must not block a garment
        logger.info("could not downscale for classification; sending the original")
        return image, content_type


def _enum(values: tuple[str, ...], description: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values), "description": description}


def _confidence(description: str) -> dict[str, Any]:
    return {"type": "number", "minimum": 0, "maximum": 1, "description": description}


#: The strict schema. Every property is in ``required`` and
#: ``additionalProperties`` is false at both levels, which is what Meta's strict
#: mode demands — and, more usefully, what stops the model from answering a
#: question we did not ask.
CATEGORISATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "slot",
        "category",
        "colour",
        "pattern",
        "apparent_material",
        "confidence",
    ],
    "properties": {
        "slot": _enum(SLOT_LABELS, "Which of the five wardrobe slots this garment fills."),
        "category": _enum(CATEGORY_LABELS, "The garment type, from the closed list."),
        "colour": _enum(
            COLOUR_LABELS, "The dominant colour family, not a colour name."
        ),
        "pattern": _enum(PATTERN_LABELS, "The dominant surface pattern."),
        "apparent_material": _enum(
            MATERIAL_LABELS,
            "What the surface looks like in the photograph. An appearance class "
            "only; this is not a fibre-composition claim.",
        ),
        "confidence": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "slot",
                "category",
                "colour",
                "pattern",
                "apparent_material",
            ],
            "properties": {
                "slot": _confidence("Confidence in the slot."),
                "category": _confidence("Confidence in the category."),
                "colour": _confidence("Confidence in the colour family."),
                "pattern": _confidence("Confidence in the pattern."),
                "apparent_material": _confidence("Confidence in the apparent material."),
            },
        },
    },
}

CATEGORISATION_RESPONSE_FORMAT = JsonSchemaFormat(
    name="garment_categorisation", json_schema=CATEGORISATION_SCHEMA, strict=True
)

#: The system prompt. The negative half is as load-bearing as the positive half:
#: a model asked to describe a garment will volunteer a fibre composition and a
#: price, and a user shown "100% merino, £180" will believe it.
CATEGORISATION_SYSTEM = (
    "You classify a single garment photograph for a wardrobe catalogue.\n"
    "\n"
    "Answer only with the enumerated values in the schema. If the photograph "
    "does not let you tell, answer \"unknown\" and give that field a low "
    "confidence — \"unknown\" is a correct answer and a guess is not.\n"
    "\n"
    "Report only what is visible in the image: the garment type, the dominant "
    "colour family, the surface pattern, and what the material appears to be.\n"
    "\n"
    "Never state, estimate or imply fibre composition, garment size or "
    "measurements, waterproofing or water resistance, thermal or insulation "
    "rating, price or resale value, brand, or whether a branded item is "
    "genuine. A photograph cannot establish any of those, and the schema has no "
    "field for them."
)

CATEGORISATION_USER_TEXT = (
    "Classify the garment in this photograph. If more than one garment is "
    "visible, classify the one in the foreground."
)


# --------------------------------------------------------------------------- #
# media bytes
# --------------------------------------------------------------------------- #
@runtime_checkable
class MediaStore(Protocol):
    """Read an original, write a derivative. One interface, two backends.

    Deliberately narrow: a worker needs the bytes of one asset and somewhere to
    put one new object. Anything wider would let a worker enumerate a user's
    media.
    """

    async def read(self, asset: MediaAsset) -> bytes: ...

    async def write(self, key: str, data: bytes, *, content_type: str) -> None: ...


class UnavailableMediaStore:
    """The default. **Not implemented** — object storage has no credential here.

    Refuses loudly rather than returning empty bytes that would be composited
    into a blank cut-out and saved as if it had worked. The refusal is a
    :class:`CapabilityUnavailable`, which both handlers treat as "degrade", so a
    deployment without storage still has a working wardrobe.
    """

    async def read(self, asset: MediaAsset) -> bytes:
        raise CapabilityUnavailable(
            "Reading original media is not implemented in this build "
            "(no object-storage credential configured).",
            detail={"asset_id": str(asset.id), "status": "planned"},
        )

    async def write(self, key: str, data: bytes, *, content_type: str) -> None:
        raise CapabilityUnavailable(
            "Writing derivative media is not implemented in this build "
            "(no object-storage credential configured).",
            detail={"key": key, "status": "planned"},
        )


@dataclass(slots=True)
class InMemoryMediaStore:
    """Process-local store for the test suite and single-process development.

    Labelled ``simulated``, matching ``StubUploadAuthorizer``: nothing here may
    read as a live integration.
    """

    storage_mode = "simulated"
    objects: dict[str, bytes] = field(default_factory=dict)
    content_types: dict[str, str] = field(default_factory=dict)

    async def read(self, asset: MediaAsset) -> bytes:
        key = asset.storage_key or str(asset.id)
        try:
            return self.objects[key]
        except KeyError as exc:
            raise CapabilityUnavailable(
                "The original bytes are not present in this store.",
                detail={"asset_id": str(asset.id), "key": key},
            ) from exc

    async def write(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data
        self.content_types[key] = content_type


# --------------------------------------------------------------------------- #
# the classifier
# --------------------------------------------------------------------------- #
@runtime_checkable
class GarmentClassifier(Protocol):
    async def classify(
        self, *, image: bytes, content_type: str, user_id: uuid.UUID | None = None
    ) -> CategorisationResult: ...


class MetaGarmentClassifier:
    """Classification through :class:`~app.providers.meta.MetaProvider`.

    The provider owns reservation, run accounting and the parameter allowlist;
    this class owns only the prompt and the schema. The sole user-supplied input
    is the photograph itself — no user text enters the prompt — so there is no
    untrusted-text surface here to defend.
    """

    def __init__(
        self,
        provider: Any,
        *,
        model: str = CATEGORISATION_MODEL,
        prompt_version: str = CATEGORISATION_PROMPT_VERSION,
    ) -> None:
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version

    def build_request(self, *, image: bytes, content_type: str) -> AIRequest:
        sent, sent_type = prepare_image(image, content_type=content_type)
        return AIRequest(
            model=self._model,
            system=CATEGORISATION_SYSTEM,
            messages=(
                AIMessage(
                    "user",
                    [
                        {"type": "text", "text": CATEGORISATION_USER_TEXT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_uri(sent, content_type=sent_type)
                            },
                        },
                    ],
                ),
            ),
            needs=Capabilities(
                text_in=True, image_in=True, text_out=True, structured_output=True
            ),
            response_format=CATEGORISATION_RESPONSE_FORMAT,
            max_completion_tokens=CATEGORISATION_MAX_TOKENS,
            temperature=CATEGORISATION_TEMPERATURE,
            prompt_version=self._prompt_version,
            purpose=CATEGORISATION_PURPOSE,
        )

    async def classify(
        self, *, image: bytes, content_type: str, user_id: uuid.UUID | None = None
    ) -> CategorisationResult:
        import json

        response = await self._provider.complete(
            self.build_request(image=image, content_type=content_type), user_id=user_id
        )
        try:
            payload = json.loads(response.text or "")
        except (TypeError, ValueError) as exc:
            raise ApiError(
                "The classifier did not return JSON.",
                status_code=502,
                code="malformed_categorisation",
            ) from exc
        if not isinstance(payload, Mapping):
            raise ApiError(
                "The classifier returned a non-object.",
                status_code=502,
                code="malformed_categorisation",
            )
        # Re-validated against the same closed tuples the schema was built from.
        return parse_categorisation(
            payload, model=response.model, prompt_version=self._prompt_version
        )


# --------------------------------------------------------------------------- #
# job payloads
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True, kw_only=True)
class MediaJobPayload:
    garment_id: uuid.UUID
    asset_id: uuid.UUID
    asset_version: int | None = None
    user_id: uuid.UUID | None = None


def read_payload(job: Job) -> MediaJobPayload:
    raw = job.payload or {}

    def _uuid(name: str, *, required: bool = True) -> uuid.UUID | None:
        value = raw.get(name)
        if value in (None, ""):
            if required:
                raise ValueError(f"job {job.id} carries no {name}")
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))

    version = raw.get("asset_version")
    return MediaJobPayload(
        garment_id=_uuid("garment_id"),  # type: ignore[arg-type]
        asset_id=_uuid("asset_id"),  # type: ignore[arg-type]
        asset_version=int(version) if version is not None else None,
        user_id=_uuid("user_id", required=False),
    )


# --------------------------------------------------------------------------- #
# handler: categorisation
# --------------------------------------------------------------------------- #
async def categorise(
    session: AsyncSession,
    job: Job,
    *,
    classifier: GarmentClassifier,
    store: MediaStore | None = None,
) -> dict[str, Any]:
    """Classify one garment photograph and record the inference.

    Raises :class:`AssetGone` when the photograph was deleted, which the runner
    treats as a discard rather than a failure: the work was correctly thrown
    away, and retrying it against something that no longer exists would be the
    bug.
    """
    store = store or UnavailableMediaStore()
    payload = read_payload(job)
    job_ref, asset_ref = str(job.id), str(payload.asset_id)

    # Cheap pre-check, so a deleted photograph is not paid to be classified.
    asset = await guard_write(
        session,
        payload.asset_id,
        version=payload.asset_version,
        user_id=payload.user_id,
    )
    content_type = asset.content_type or "image/jpeg"

    try:
        image = await store.read(asset)
    except CapabilityUnavailable as exc:
        # No storage backend. The garment keeps working; it is simply
        # uncategorised until one exists. Retrying cannot help.
        logger.info(
            "categorisation skipped: media is unreadable in this build",
            extra={"job_id": job_ref, "asset_id": asset_ref, "code": exc.code},
        )
        return {"categorised": False, "reason": exc.code}

    result = await classifier.classify(
        image=image, content_type=content_type, user_id=payload.user_id
    )

    # The guard again, in the transaction that writes (ADR-012). The model call
    # above takes seconds; a delete can land inside them.
    try:
        await guard_write(
            session,
            payload.asset_id,
            version=payload.asset_version,
            user_id=payload.user_id,
        )
        written = await record_categorisation(
            session,
            payload.garment_id,
            result,
            inference_version=result.prompt_version,
        )
        await session.commit()
    except AssetGone:
        await session.rollback()
        raise

    if not written:
        logger.info(
            "categorisation discarded: the garment is gone",
            extra={"job_id": job_ref, "garment_id": str(payload.garment_id)},
        )
        return {"categorised": False, "reason": "garment_deleted"}

    return {
        "categorised": True,
        "slot": result.slot,
        "category": result.category,
        "category_confidence": result.category_confidence,
        "confidence": result.confidence,
    }


# --------------------------------------------------------------------------- #
# handler: background removal
# --------------------------------------------------------------------------- #
def cutout_storage_key(asset: MediaAsset) -> str:
    """Where the cut-out lives. Keyed on the source version for provenance."""
    return f"cutouts/{asset.user_id}/{asset.id}/v{asset.version}.png"


async def remove_background(
    session: AsyncSession,
    job: Job,
    *,
    segmenter: SegmentationProvider,
    store: MediaStore | None = None,
    background: str = CUTOUT_BACKGROUND,
) -> dict[str, Any]:
    """Produce a cut-out on a solid ground, as a **new** asset.

    The original is never replaced and never deleted: ``media_asset_id`` still
    points at the photograph the user took, and the cut-out is reached through
    ``background_removed_asset_id``. If any part of this fails, the garment is
    exactly as usable as it was before.
    """
    store = store or UnavailableMediaStore()
    payload = read_payload(job)
    job_ref, asset_ref = str(job.id), str(payload.asset_id)

    asset = await guard_write(
        session,
        payload.asset_id,
        version=payload.asset_version,
        user_id=payload.user_id,
    )

    garment = await session.scalar(
        sa.select(Garment).where(
            Garment.id == payload.garment_id, Garment.deleted_at.is_(None)
        )
    )
    if garment is None:
        return {"background_removed": False, "reason": "garment_deleted"}
    if garment.background_removed_asset_id is not None:
        # Already done. The job's idempotency key makes a second enqueue
        # impossible; this covers a retry after a partial failure.
        return {
            "background_removed": True,
            "reason": "already_present",
            "asset_id": str(garment.background_removed_asset_id),
        }

    prompt = garment_noun_phrase(
        category=garment.effective_attributes.get("category") or garment.category,
        slot=garment.effective_attributes.get("slot"),
    )

    try:
        image = await store.read(asset)
        result = await segmenter.cutout(
            image=image,
            prompt=prompt,
            content_type=asset.content_type or CUTOUT_CONTENT_TYPE,
            background=background,
            user_id=payload.user_id,
            job_id=job.id,
        )
    except (SegmentationUnavailable, CapabilityUnavailable) as exc:
        # Capability missing, parser absent, or the mask selected no pixels.
        # None of these improve on a retry, and the original still works.
        logger.info(
            "background removal skipped; the original photograph stands",
            extra={"job_id": job_ref, "asset_id": asset_ref, "code": exc.code},
        )
        return {"background_removed": False, "reason": exc.code}

    cutout = result.image
    if cutout is None:
        # Documented outcome, not an error: the concept was not found. A white
        # garment on a white background returns exactly this.
        logger.info(
            "background removal found no subject; the original photograph stands",
            extra={"job_id": job_ref, "asset_id": asset_ref, "prompt": prompt},
        )
        return {
            "background_removed": False,
            "reason": result.reason or "no_subject_found",
        }

    key = cutout_storage_key(asset)
    try:
        await store.write(key, cutout, content_type=CUTOUT_CONTENT_TYPE)
    except CapabilityUnavailable as exc:
        logger.info(
            "cut-out could not be stored; the original photograph stands",
            extra={"job_id": job_ref, "asset_id": asset_ref, "code": exc.code},
        )
        return {"background_removed": False, "reason": exc.code}

    width, height = _png_size(cutout)

    # The guard once more, in the transaction that writes.
    try:
        await guard_write(
            session,
            payload.asset_id,
            version=payload.asset_version,
            user_id=payload.user_id,
        )
        derived = MediaAsset(
            user_id=asset.user_id,
            kind=asset.kind,
            status="ready",
            content_type=CUTOUT_CONTENT_TYPE,
            max_bytes=len(cutout),
            byte_size=len(cutout),
            storage_key=key,
            width=width,
            height=height,
            version=1,
            # Private by default, like every asset. A cut-out of a private
            # photograph is not less private than the photograph.
            publication_consent=False,
        )
        session.add(derived)
        await session.flush()
        updated = await session.execute(
            sa.update(Garment)
            .where(Garment.id == payload.garment_id, Garment.deleted_at.is_(None))
            .values(background_removed_asset_id=derived.id)
        )
        if not updated.rowcount:
            await session.rollback()
            return {"background_removed": False, "reason": "garment_deleted"}
        await session.commit()
    except AssetGone:
        await session.rollback()
        raise

    return {
        "background_removed": True,
        "asset_id": str(derived.id),
        "prompt": prompt,
        "objects": len(result.records),
        "cached": result.cached,
        "cost_micro_minor": result.cost_micro_minor,
    }


def _png_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return image.width, image.height
    except Exception:  # noqa: BLE001 - dimensions are metadata, not the artifact
        return None, None


# --------------------------------------------------------------------------- #
# handler registry
# --------------------------------------------------------------------------- #
def categorise_handlers(
    *,
    classifier: GarmentClassifier,
    segmenter: SegmentationProvider,
    store: MediaStore | None = None,
) -> dict[str, Any]:
    """The two handlers, bound to their collaborators.

    Dependencies are injected rather than constructed: a worker deployable wires
    the real provider and store once at start-up, and the test suite wires
    doubles, so no test needs a credential or a network stack.
    """
    media_store = store or UnavailableMediaStore()

    async def _categorise(session: AsyncSession, job: Job) -> dict[str, Any]:
        return await categorise(session, job, classifier=classifier, store=media_store)

    async def _remove_background(session: AsyncSession, job: Job) -> dict[str, Any]:
        return await remove_background(
            session, job, segmenter=segmenter, store=media_store
        )

    return {
        CATEGORISE_JOB_KIND: _categorise,
        BACKGROUND_REMOVAL_JOB_KIND: _remove_background,
    }


__all__ = [
    "CATEGORISATION_MAX_TOKENS",
    "CATEGORISATION_MODEL",
    "CATEGORISATION_PROMPT_VERSION",
    "CATEGORISATION_PURPOSE",
    "CATEGORISATION_RESPONSE_FORMAT",
    "CATEGORISATION_SCHEMA",
    "CATEGORISATION_SYSTEM",
    "CATEGORISATION_TEMPERATURE",
    "CATEGORISATION_USER_TEXT",
    "GarmentClassifier",
    "InMemoryMediaStore",
    "MediaJobPayload",
    "MediaStore",
    "MetaGarmentClassifier",
    "UnavailableMediaStore",
    "categorise",
    "categorise_handlers",
    "cutout_storage_key",
    "read_payload",
    "remove_background",
]
