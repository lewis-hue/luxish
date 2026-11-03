"""Wardrobe media pipeline: closed taxonomy, favourites, bulk, tombstoned delete.

Four ideas carry this module.

**The label set is closed, and closure is enforced on the way in.** An
open-ended prompt returns "top", "shirt", "button-down" and "oxford" for one
photograph across four runs, which makes ``category`` useless for the
deterministic SQL retrieval ADR-004 commits us to. :data:`SLOTS` and
:data:`CATEGORIES` are therefore the whole vocabulary; ``"unknown"`` is a member
of both, and anything else is a :class:`ClosedLabelViolation` rather than a
value that quietly lands in a column.

**Inference and user truth never share a column (ADR-010).** Everything a model
produces goes to ``inferred_attributes`` with a confidence.
:func:`record_categorisation` emits exactly one UPDATE and that statement has no
``confirmed_attributes`` in it, so a later, more confident run has nothing to
overwrite. The ``category`` column is auto-filled *only* while it is NULL and
the user has confirmed no category of their own.

**Some attributes cannot be established from a photograph at all.** Fibre
composition, size, waterproofing, thermal rating, price and brand authenticity
are claims about a garment's provenance and construction, not about its
appearance. :data:`FORBIDDEN_INFERENCE_KEYS` is applied by
:func:`reject_forbidden_inference` before anything is written, so "the model
said so" can never become "the wardrobe says so".

**``is_favourite`` is user-stated truth.** It belongs to the same class of claim
as ``confirmed_attributes``: no worker and no model may write it. It is a
column rather than a confirmed attribute because the stylist weights it on every
retrieval and that is an indexed predicate, not a JSON probe.

Columns
-------
``is_favourite``, ``background_removed_asset_id`` and
``categorisation_confidence`` are added to ``garments`` by
:func:`extend_garment_model`, which runs on import. They are declared here
rather than in ``app/models/garment.py`` only because this module owns them for
now; the function is idempotent and skips any column that already exists, so
promoting the three declarations into the model file is a safe, no-op-for-us
change. Migration ``0009_wardrobe_media`` adds the same three columns and the
two indexes.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import mapped_column

from app.domain.jobs import delete_asset, enqueue
from app.domain.wardrobe import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    GarmentRepository,
    Page,
    decode_cursor,
    encode_cursor,
)
from app.errors import ApiError
from app.models.garment import Garment
from app.models.media_asset import MediaAsset

# --------------------------------------------------------------------------- #
# the closed vocabulary
# --------------------------------------------------------------------------- #
#: The only value that may stand in for "the model could not tell". Present in
#: every enum below so a model has an honest answer available and never has to
#: invent one.
UNKNOWN = "unknown"

#: The five wardrobe slots. Fixed by the product brief; not extensible by a
#: model, a prompt, or a request parameter.
SLOTS: tuple[str, ...] = ("tops", "bottoms", "outerwear", "shoes", "accessories")

#: The finer category. Closed, and deliberately small: every member is a word a
#: user would recognise on a filter chip.
CATEGORIES: tuple[str, ...] = (
    "shirt",
    "tshirt",
    "knitwear",
    "sweatshirt",
    "blouse",
    "dress",
    "trousers",
    "jeans",
    "skirt",
    "shorts",
    "blazer",
    "jacket",
    "coat",
    "shoes",
    "bag",
    "accessory",
)

SLOT_LABELS: tuple[str, ...] = (*SLOTS, UNKNOWN)
CATEGORY_LABELS: tuple[str, ...] = (*CATEGORIES, UNKNOWN)

#: Which slot each category belongs in. This is the authority: a model that
#: returns a category and a slot that disagree is corrected to the mapping,
#: because the mapping is a product decision and the slot is not independently
#: observable.
#:
#: ``dress`` maps to ``tops`` because the brief fixes the slot list at five and
#: a one-piece garment has no bottoms counterpart to pair with. The
#: ``one_piece`` flag in the inferred attributes is what tells the stylist not
#: to pair it with a bottom.
CATEGORY_SLOT: Mapping[str, str] = {
    "shirt": "tops",
    "tshirt": "tops",
    "knitwear": "tops",
    "sweatshirt": "tops",
    "blouse": "tops",
    "dress": "tops",
    "trousers": "bottoms",
    "jeans": "bottoms",
    "skirt": "bottoms",
    "shorts": "bottoms",
    "blazer": "outerwear",
    "jacket": "outerwear",
    "coat": "outerwear",
    "shoes": "shoes",
    "bag": "accessories",
    "accessory": "accessories",
}

#: Categories that occupy a top and a bottom at once.
ONE_PIECE_CATEGORIES: frozenset[str] = frozenset({"dress"})

#: Colour *families*, not names. "Ecru" and "ivory" are both ``white`` here:
#: the point is a filterable family, and a model asked for a free-text colour
#: name produces a thesaurus.
COLOUR_LABELS: tuple[str, ...] = (
    "black",
    "white",
    "grey",
    "beige",
    "brown",
    "navy",
    "blue",
    "green",
    "olive",
    "yellow",
    "orange",
    "red",
    "pink",
    "purple",
    "gold",
    "silver",
    "multicolour",
    UNKNOWN,
)

PATTERN_LABELS: tuple[str, ...] = (
    "plain",
    "striped",
    "checked",
    "floral",
    "polka_dot",
    "animal",
    "geometric",
    "abstract",
    "logo",
    "colourblock",
    UNKNOWN,
)

#: **Apparent** material: what the surface looks like in the photograph. This is
#: an appearance class and nothing more — it is not a fibre-composition claim,
#: which is why ``fibre_composition`` is a forbidden key below while
#: ``apparent_material`` is allowed.
MATERIAL_LABELS: tuple[str, ...] = (
    "cotton",
    "denim",
    "wool",
    "knit",
    "leather",
    "suede",
    "silk",
    "linen",
    "synthetic",
    "fleece",
    "lace",
    "velvet",
    UNKNOWN,
)

#: Keys a photograph cannot establish, so no inference may write them.
#:
#: Each is a claim about provenance or construction rather than appearance:
#: a camera cannot read a composition label, measure a size, test a membrane,
#: quantify insulation, know what was paid, or authenticate a trademark. A
#: confident-looking guess at any of these is worse than silence, because the
#: user will act on it — buying a coat for a winter it cannot handle, or
#: reselling a bag as genuine.
FORBIDDEN_INFERENCE_KEYS: frozenset[str] = frozenset(
    {
        # fibre composition
        "fibre_composition",
        "fiber_composition",
        "fabric_composition",
        "composition",
        "fibre",
        "fiber",
        "fibre_content",
        "fiber_content",
        # size
        "size",
        "exact_size",
        "size_label",
        "garment_size",
        "measurements",
        "fit_measurements",
        # weather / thermal performance
        "waterproof",
        "waterproofing",
        "water_resistance",
        "waterproof_rating",
        "thermal_rating",
        "warmth_rating",
        "insulation_rating",
        "temperature_rating",
        # money
        "price",
        "price_minor",
        "retail_price",
        "rrp",
        "msrp",
        "resale_value",
        # brand and authenticity
        "brand",
        "brand_authenticity",
        "authenticity",
        "authentic",
        "is_authentic",
        "is_genuine",
        "genuine",
        "counterfeit",
    }
)

#: Below this, the ``category`` column is left alone and the label stays an
#: inference only. ASSUMED; the number to tune once there is correction data.
CATEGORY_AUTOFILL_CONFIDENCE = 0.6

#: One request authorises one upload, and a bulk create takes at most this many.
#: A cap is required: without one, a single request can enqueue unbounded paid
#: model work. Twenty is a camera roll selection, not a wardrobe import.
MAX_BULK_ITEMS = 20

#: Durable job kinds. All model work is queued (ADR-013).
CATEGORISE_JOB_KIND = "wardrobe.categorise"
BACKGROUND_REMOVAL_JOB_KIND = "wardrobe.remove_background"

FAVOURITE_INDEX = "ix_garments_user_id_is_favourite"
#: One garment per uploaded asset, per owner. Idempotency as a schema property
#: rather than caller diligence — the same reasoning as ``jobs.idempotency_key``.
GARMENT_ASSET_UNIQUE_INDEX = "uq_garments_user_id_media_asset_id"
CATEGORISATION_CONFIDENCE_CHECK = "categorisation_confidence_range"


class ClosedLabelViolation(ApiError):
    """A label arrived that is not in the closed set.

    A 502: the request was fine, the *provider* broke its contract. Raising
    beats coercing — a silently coerced "oxford" to "shirt" is a wrong label
    nobody can find, while a raised violation is a dead-lettered job somebody
    reads.
    """

    status_code = 502
    code = "closed_label_violation"
    default_message = "The model returned a label outside the closed set."

    def __init__(self, field: str, value: Any, allowed: Sequence[str]) -> None:
        self.field = field
        self.value = value
        super().__init__(
            f"{field}={value!r} is not one of the {len(allowed)} permitted values",
            detail={"field": field, "value": str(value), "allowed": list(allowed)},
        )


class ForbiddenInference(ApiError):
    """An inference tried to assert something a photograph cannot establish."""

    status_code = 502
    code = "forbidden_inference"
    default_message = "The model asserted an attribute an image cannot establish."

    def __init__(self, keys: Sequence[str]) -> None:
        self.keys = tuple(sorted(keys))
        super().__init__(
            "these attributes cannot be inferred from an image: "
            + ", ".join(self.keys),
            detail={"keys": list(self.keys)},
        )


class BulkTooLarge(ApiError):
    status_code = 422
    code = "bulk_too_large"
    default_message = "Too many items in one bulk request."


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# the three columns
# --------------------------------------------------------------------------- #
def extend_garment_model() -> None:
    """Add this task's three columns and two indexes to ``garments``.

    Idempotent by design, and in both directions: it skips any column already
    present, so it is safe to call twice *and* safe once the declarations are
    promoted into ``app/models/garment.py``. Must run before
    ``Base.metadata.create_all``, which is why it is called at import time.
    """
    table = Garment.__table__

    if "is_favourite" not in table.c:
        # User-stated, like confirmed_attributes. Nothing automated writes it.
        Garment.is_favourite = mapped_column(
            "is_favourite",
            sa.Boolean,
            nullable=False,
            default=False,
            server_default=sa.false(),
        )

    if "background_removed_asset_id" not in table.c:
        # A *new* asset, never a replacement: §5 requires the original to
        # survive optional processing, so the cut-out gets its own row and
        # ``media_asset_id`` keeps pointing at the photograph the user took.
        # ON DELETE SET NULL, so purging the cut-out cannot cascade into the
        # garment.
        Garment.background_removed_asset_id = mapped_column(
            "background_removed_asset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        )

    if "categorisation_confidence" not in table.c:
        # Separate from ``inference_confidence``: that one is the run's overall
        # confidence, this one is the confidence in the *category label*, which
        # is what decides whether the column is auto-filled or the user is asked.
        Garment.categorisation_confidence = mapped_column(
            "categorisation_confidence", sa.Float, nullable=True
        )
        table.append_constraint(
            sa.CheckConstraint(
                "categorisation_confidence IS NULL OR "
                "(categorisation_confidence >= 0 AND categorisation_confidence <= 1)",
                name=CATEGORISATION_CONFIDENCE_CHECK,
            )
        )

    existing = {index.name for index in table.indexes}
    if FAVOURITE_INDEX not in existing:
        # The stylist reads "this user's favourites" on every run.
        sa.Index(FAVOURITE_INDEX, table.c.user_id, table.c.is_favourite)
    if GARMENT_ASSET_UNIQUE_INDEX not in existing:
        # Partial: NULL asset ids and soft-deleted rows are exempt, so a user
        # can re-photograph and re-add a garment they deleted.
        sa.Index(
            GARMENT_ASSET_UNIQUE_INDEX,
            table.c.user_id,
            table.c.media_asset_id,
            unique=True,
            postgresql_where=sa.text("media_asset_id IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=sa.text("media_asset_id IS NOT NULL AND deleted_at IS NULL"),
        )


extend_garment_model()


# --------------------------------------------------------------------------- #
# categorisation results
# --------------------------------------------------------------------------- #
def check_label(field: str, value: Any, allowed: Sequence[str]) -> str:
    """Normalise case and whitespace, then require membership. No synonyms.

    Trimming and lower-casing is the only leniency: ``" Tops"`` is the same
    answer as ``"tops"``. Mapping ``"button-down"`` onto ``"shirt"`` would
    *hide* the open-vocabulary drift this closure exists to surface, so an
    unrecognised label raises.
    """
    text = str(value).strip().lower()
    if text not in allowed:
        raise ClosedLabelViolation(field, value, allowed)
    return text


def check_confidence(field: str, value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ClosedLabelViolation(field, value, ("a number in [0, 1]",)) from exc
    if not 0.0 <= number <= 1.0:
        raise ClosedLabelViolation(field, value, ("a number in [0, 1]",))
    return number


def reject_forbidden_inference(attributes: Mapping[str, Any]) -> None:
    """Refuse an inference payload that asserts a non-visual claim.

    Checked against the normalised key name, so ``"Waterproof"`` and
    ``"water-resistance"`` are caught as readily as the canonical spellings.
    """
    offending = [
        key
        for key in attributes
        if str(key).strip().lower().replace("-", "_").replace(" ", "_")
        in FORBIDDEN_INFERENCE_KEYS
    ]
    if offending:
        raise ForbiddenInference(offending)


@dataclass(frozen=True, slots=True, kw_only=True)
class CategorisationResult:
    """One classification of one photograph, validated against the closed sets.

    Construction *is* the validation: there is no way to hold an out-of-set
    label in this type, so nothing downstream has to re-check.
    """

    slot: str
    category: str
    colour: str
    pattern: str
    apparent_material: str
    slot_confidence: float = 0.0
    category_confidence: float = 0.0
    colour_confidence: float = 0.0
    pattern_confidence: float = 0.0
    material_confidence: float = 0.0
    model: str | None = None
    prompt_version: str = "unversioned"

    def __post_init__(self) -> None:
        category = check_label("category", self.category, CATEGORY_LABELS)
        slot = check_label("slot", self.slot, SLOT_LABELS)
        # The mapping is the authority; a disagreeing slot is a model error we
        # can correct without losing information, unlike a bad category.
        if category != UNKNOWN:
            slot = CATEGORY_SLOT[category]
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "slot", slot)
        object.__setattr__(
            self, "colour", check_label("colour", self.colour, COLOUR_LABELS)
        )
        object.__setattr__(
            self, "pattern", check_label("pattern", self.pattern, PATTERN_LABELS)
        )
        object.__setattr__(
            self,
            "apparent_material",
            check_label("apparent_material", self.apparent_material, MATERIAL_LABELS),
        )
        for field_name in (
            "slot_confidence",
            "category_confidence",
            "colour_confidence",
            "pattern_confidence",
            "material_confidence",
        ):
            object.__setattr__(
                self, field_name, check_confidence(field_name, getattr(self, field_name))
            )

    @property
    def confidence(self) -> float:
        """The run's overall confidence: the mean of the five per-field values.

        A mean rather than a minimum, because one unreadable attribute (a colour
        under tungsten light) should not reduce the whole record's confidence to
        that of its worst field.
        """
        values = (
            self.slot_confidence,
            self.category_confidence,
            self.colour_confidence,
            self.pattern_confidence,
            self.material_confidence,
        )
        return round(sum(values) / len(values), 6)

    @property
    def is_one_piece(self) -> bool:
        return self.category in ONE_PIECE_CATEGORIES

    def inferred_attributes(self) -> dict[str, Any]:
        """The document written to ``Garment.inferred_attributes``.

        Flat values plus a ``confidence`` sub-map, because ``effective_attributes``
        merges per key: a flat ``colour`` is overridable by a user's confirmed
        ``colour``, which is the whole point.
        """
        attributes: dict[str, Any] = {
            "slot": self.slot,
            "category": self.category,
            "colour": self.colour,
            "pattern": self.pattern,
            "apparent_material": self.apparent_material,
            "one_piece": self.is_one_piece,
            "confidence": {
                "slot": self.slot_confidence,
                "category": self.category_confidence,
                "colour": self.colour_confidence,
                "pattern": self.pattern_confidence,
                "apparent_material": self.material_confidence,
            },
        }
        # Belt and braces: the dict above is written by hand and contains no
        # forbidden key, but asserting it means a future edit cannot add one.
        reject_forbidden_inference(attributes)
        return attributes


def parse_categorisation(
    payload: Mapping[str, Any], *, model: str | None = None, prompt_version: str = "unversioned"
) -> CategorisationResult:
    """Turn a model's structured output into a validated result.

    Forbidden keys are refused here rather than dropped: a model that answered a
    question we did not ask has not complied with the schema, and quietly
    discarding the extra field would leave that fact unrecorded.
    """
    reject_forbidden_inference(payload)
    confidences = payload.get("confidence")
    if not isinstance(confidences, Mapping):
        confidences = {}
    return CategorisationResult(
        slot=payload.get("slot", UNKNOWN),
        category=payload.get("category", UNKNOWN),
        colour=payload.get("colour", UNKNOWN),
        pattern=payload.get("pattern", UNKNOWN),
        apparent_material=payload.get("apparent_material", UNKNOWN),
        slot_confidence=confidences.get("slot", 0.0),
        category_confidence=confidences.get("category", 0.0),
        colour_confidence=confidences.get("colour", 0.0),
        pattern_confidence=confidences.get("pattern", 0.0),
        material_confidence=confidences.get("apparent_material", 0.0),
        model=model,
        prompt_version=prompt_version,
    )


# --------------------------------------------------------------------------- #
# writing an inference
# --------------------------------------------------------------------------- #
#: The only columns :func:`record_categorisation` is allowed to set.
#: ``confirmed_attributes`` is absent and a test asserts it stays absent.
CATEGORISATION_WRITABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "inferred_attributes",
        "inference_confidence",
        "inference_version",
        "inferred_at",
        "categorisation_confidence",
        "category",
    }
)


async def record_categorisation(
    session: AsyncSession,
    garment_id: uuid.UUID,
    result: CategorisationResult,
    *,
    inference_version: str | None = None,
    autofill_confidence: float = CATEGORY_AUTOFILL_CONFIDENCE,
    only_if_unset: bool = False,
) -> bool:
    """Write one categorisation. Never commits; the caller owns the transaction.

    Returns ``False`` when the garment is gone — a soft-deleted garment is not
    an error for a worker, it is the expected outcome of a delete that landed
    mid-job (ADR-012), and the caller completes the job rather than retrying.

    The statement cannot touch ``confirmed_attributes``: it is not in the
    ``values`` call and :data:`CATEGORISATION_WRITABLE_COLUMNS` is asserted
    against. So "a later high-confidence inference overwrote my correction" is
    not a bug that can be introduced here without deleting a line that exists to
    stop it.

    ``only_if_unset`` makes the write a claim on an empty slot rather than an
    update. Outfit detection uses it: it has already classified the garment it
    found, and writing that is worth doing *because* it saves a second model
    call — but never at the price of overwriting a better answer that arrived
    first. Reported as ``False`` when it declines, so the caller can tell the
    difference between "the garment is gone" and "it was already sorted".
    """
    garment = await session.scalar(
        sa.select(Garment).where(Garment.id == garment_id, Garment.deleted_at.is_(None))
    )
    if garment is None:
        return False
    if only_if_unset and garment.inference_version is not None:
        return False

    values: dict[str, Any] = {
        "inferred_attributes": result.inferred_attributes(),
        "inference_confidence": result.confidence,
        "inference_version": inference_version or result.prompt_version,
        "inferred_at": _now(),
        "categorisation_confidence": result.category_confidence,
    }

    # The column is auto-filled only into a vacuum: NULL today, and no confirmed
    # category of the user's own. Anything else is the user's answer and stands.
    confirmed = garment.confirmed_attributes or {}
    if (
        garment.category is None
        and "category" not in confirmed
        and result.category != UNKNOWN
        and result.category_confidence >= autofill_confidence
    ):
        values["category"] = result.category

    leaked = set(values) - CATEGORISATION_WRITABLE_COLUMNS
    if leaked:  # pragma: no cover - a programming error, not an input error
        raise RuntimeError(f"categorisation tried to write {sorted(leaked)}")

    await session.execute(
        sa.update(Garment)
        .where(Garment.id == garment_id, Garment.deleted_at.is_(None))
        .values(**values)
    )
    return True


# --------------------------------------------------------------------------- #
# favourites
# --------------------------------------------------------------------------- #
async def set_favourite(
    session: AsyncSession, *, user_id: uuid.UUID, garment_id: uuid.UUID, favourite: bool
) -> Garment:
    """Favourite or unfavourite one garment. Idempotent in both directions.

    Owner scoping comes from :class:`GarmentRepository`, so another user's id is
    a 404 — the same answer as an id that does not exist, because a 403 would
    confirm the id is real.
    """
    repo = GarmentRepository(session, user_id=user_id)
    garment = await repo.require(garment_id)
    garment.is_favourite = bool(favourite)
    await session.commit()
    await session.refresh(garment)
    return garment


async def list_favourites(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> Page:
    """One page of this user's favourites, newest first.

    Same keyset cursor as the main wardrobe listing, so a client has one
    pagination idiom rather than two.
    """
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    repo = GarmentRepository(session, user_id=user_id)
    query = repo.scoped_select().where(Garment.is_favourite.is_(True))
    if cursor:
        created_at, last_id = decode_cursor(cursor)
        query = query.where(
            sa.tuple_(Garment.created_at, Garment.id) < sa.tuple_(created_at, last_id)
        )
    query = query.order_by(Garment.created_at.desc(), Garment.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(query)).all())
    next_cursor = encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return Page(items=rows[:limit], next_cursor=next_cursor)


async def favourite_garment_ids(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 500
) -> tuple[tuple[uuid.UUID, ...], int]:
    """Just the ids, for the stylist's retrieval step.

    Favouriting is a *stated* preference, so it is weighted rather than
    inferred. This is the cheap read that lets the stylist do that without
    loading whole garments it may not use. Returns ``(ids, total)`` so a
    truncated read is detectable rather than silently partial.
    """
    repo = GarmentRepository(session, user_id=user_id)
    total = (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Garment)
            .where(
                Garment.user_id == user_id,
                Garment.deleted_at.is_(None),
                Garment.is_favourite.is_(True),
            )
        )
    ) or 0
    rows = (
        await session.scalars(
            repo.scoped_select()
            .where(Garment.is_favourite.is_(True))
            .order_by(Garment.created_at.desc(), Garment.id.desc())
            .limit(max(1, limit))
            .with_only_columns(Garment.id)
        )
    ).all()
    return tuple(rows), total  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# bulk create
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True, kw_only=True)
class BulkGarmentItem:
    """One garment in a bulk create, keyed on an authorised upload."""

    media_asset_id: uuid.UUID
    name: str | None = None
    category: str | None = None
    availability: str = "available"
    is_favourite: bool = False


@dataclass(slots=True, kw_only=True)
class BulkItemOutcome:
    """What happened to one item. Position is preserved, so a client can zip."""

    index: int
    media_asset_id: uuid.UUID
    #: ``created`` | ``existing`` | ``failed``
    status: str
    garment_id: uuid.UUID | None = None
    code: str | None = None
    message: str | None = None
    jobs: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in ("created", "existing")


async def bulk_create_garments(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    items: Sequence[BulkGarmentItem],
    enqueue_jobs: bool = True,
) -> list[BulkItemOutcome]:
    """Create up to :data:`MAX_BULK_ITEMS` garments, reporting each separately.

    **Partial failure does not fail the batch.** Each item is validated,
    inserted and committed on its own, so nineteen good photographs are not lost
    to one that referenced a stranger's upload. The price is twenty small
    transactions instead of one; for a capped batch of user-initiated work that
    is the right trade, and it is what makes each row durable the moment it
    succeeds.

    Re-submitting an asset is safe: the existing garment is returned with status
    ``existing`` and no second set of paid jobs is queued. The partial unique
    index on ``(user_id, media_asset_id)`` closes the race the lookup cannot, so
    two concurrent identical batches still produce one garment.
    """
    if len(items) > MAX_BULK_ITEMS:
        raise BulkTooLarge(
            f"At most {MAX_BULK_ITEMS} garments may be created in one request.",
            detail={"max_items": MAX_BULK_ITEMS, "received": len(items)},
        )

    repo = GarmentRepository(session, user_id=user_id)
    outcomes: list[BulkItemOutcome] = []

    for index, item in enumerate(items):
        outcome = BulkItemOutcome(
            index=index, media_asset_id=item.media_asset_id, status="failed"
        )
        outcomes.append(outcome)
        try:
            existing = await session.scalar(
                repo.scoped_select().where(Garment.media_asset_id == item.media_asset_id)
            )
            if existing is not None:
                outcome.status = "existing"
                outcome.garment_id = existing.id
                continue

            # Ownership of the upload, before anything is written.
            await repo.require_own_asset(item.media_asset_id)
            garment = Garment(
                user_id=user_id,
                name=item.name,
                category=item.category,
                media_asset_id=item.media_asset_id,
                confirmed_attributes={},
                inferred_attributes={},
                availability=item.availability,
                is_favourite=bool(item.is_favourite),
            )
            session.add(garment)
            await session.commit()
            await session.refresh(garment)
        except ApiError as exc:
            await session.rollback()
            outcome.code = exc.code
            outcome.message = exc.message
            continue
        except IntegrityError:
            # Lost the race against a concurrent identical batch. The other
            # writer's row is the answer.
            await session.rollback()
            duplicate = await session.scalar(
                repo.scoped_select().where(Garment.media_asset_id == item.media_asset_id)
            )
            if duplicate is None:  # pragma: no cover - the constraint fired elsewhere
                outcome.code = "conflict"
                outcome.message = "The garment could not be created."
                continue
            outcome.status = "existing"
            outcome.garment_id = duplicate.id
            continue

        outcome.status = "created"
        outcome.garment_id = garment.id
        if enqueue_jobs:
            outcome.jobs = await enqueue_media_pipeline(
                session, garment=garment, user_id=user_id
            )

    return outcomes


#: How long categorisation waits so detection can answer first.
#:
#: Raised from 12 on 2026-10-29. The 12 came from "detection completes in
#: roughly 7-9 seconds", which was two photographs. Fourteen real ones
#: (`scripts/measure_detection.py`) put the model call at **3.1 to 12.8
#: seconds** — the worst case already past the old handicap, and three of the
#: fourteen within 2.5s of it. Those are model latencies alone; the job also
#: downloads the image, segments and commits, so end-to-end overruns more
#: often than one in fourteen.
#:
#: Every overrun costs a paid call for an answer detection was about to
#: produce, which is the exact saving the handicap exists to make. Twenty
#: clears the measured worst case with room for the work around it.
#:
#: **The cost falls on the failure path, deliberately.** Categorisation is
#: still enqueued, so a garment whose detection dead-letters is sorted by it —
#: twenty seconds later instead of twelve. That path is rare and already
#: degraded; the common path is every upload. Setting this to 0 restores the
#: race and makes both calls on every upload, for a latency difference
#: measured under a second.
CATEGORISE_HANDICAP_SECONDS = 20


async def enqueue_media_pipeline(
    session: AsyncSession, *, garment: Garment, user_id: uuid.UUID
) -> tuple[str, ...]:
    """Queue categorisation and background removal for one garment.

    Both are durable jobs and neither runs in a request handler: they call a
    paid model and Cloud Run request timeouts make an inline call a liability
    (ADR-005, ADR-013). The idempotency key is derived from the garment, so a
    retried request cannot queue the work — or the spend — twice.
    """
    if garment.media_asset_id is None:
        return ()
    asset = await session.get(MediaAsset, garment.media_asset_id)
    payload = {
        "garment_id": str(garment.id),
        "asset_id": str(garment.media_asset_id),
        "asset_version": asset.version if asset else None,
        "user_id": str(user_id),
    }
    # Outfit detection runs first and decides which shape this upload is.
    #
    # Not a user-facing choice. Asking "is this one garment or an outfit?"
    # pushes a question onto the person that the model can answer from the
    # photograph, and gets it wrong whenever they tap without reading. The
    # detector reports `worn` and the number of garments it can see, and a
    # photograph that turns out to hold one garment falls through to the
    # single-garment path it would have taken anyway.
    from app.workers.outfit import DETECT_OUTFIT_JOB_KIND

    queued: list[str] = []
    for kind in (
        DETECT_OUTFIT_JOB_KIND,
        CATEGORISE_JOB_KIND,
        BACKGROUND_REMOVAL_JOB_KIND,
    ):
        await enqueue(
            session,
            kind,
            payload,
            idempotency_key=f"{kind}:{garment.id}",
            # Categorisation starts late, and the delay is the whole point.
            #
            # Detection already classifies a photograph that turns out to hold
            # one garment, and writes it. These two sit on different queues and
            # are dispatched together, so they race: categorisation made its
            # own paid call for an answer detection was about to produce, and
            # its write was then discarded as the later one.
            #
            # Holding it back lets detection land first, so categorisation
            # finds the garment already sorted and returns without calling
            # anything. It is still *enqueued*, which is what makes this safe:
            # if detection fails or dead-letters, this runs and does the work,
            # so the cost of the delay falls only on the path where something
            # already went wrong.
            available_at=(
                _now() + timedelta(seconds=CATEGORISE_HANDICAP_SECONDS)
                if kind == CATEGORISE_JOB_KIND
                else None
            ),
        )
        queued.append(kind)
    return tuple(queued)


# --------------------------------------------------------------------------- #
# deletion, through the tombstone path
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class DeletionReceipt:
    garment_id: uuid.UUID
    tombstoned_asset_ids: tuple[uuid.UUID, ...] = ()


async def delete_garment(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    garment_id: uuid.UUID,
    reason: str = "user_request",
) -> DeletionReceipt:
    """Delete a garment and tombstone its media (ADR-012).

    Soft-deleting the garment alone is not enough. A categorisation or
    background-removal job can already be in flight, and it will write through
    :func:`app.domain.jobs.guard_write`, which consults the **tombstone** — the
    record that outlives the asset row. Writing that tombstone here is what
    makes a late job discard its work instead of resurrecting a deleted
    photograph.

    The cut-out is tombstoned alongside the original: it is a derivative of
    deleted content and has no independent reason to exist.
    """
    repo = GarmentRepository(session, user_id=user_id)
    garment = await repo.require(garment_id)

    asset_ids = tuple(
        dict.fromkeys(
            asset_id
            for asset_id in (garment.media_asset_id, garment.background_removed_asset_id)
            if asset_id is not None
        )
    )

    garment.deleted_at = _now()
    await session.commit()

    for asset_id in asset_ids:
        await delete_asset(session, asset_id, user_id=user_id, reason=reason)

    return DeletionReceipt(garment_id=garment_id, tombstoned_asset_ids=asset_ids)


async def bulk_delete_garments(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    garment_ids: Sequence[uuid.UUID],
    reason: str = "user_request",
) -> list[BulkItemOutcome]:
    """Delete up to :data:`MAX_BULK_ITEMS` garments, reporting each separately.

    Same contract as the bulk create: one unknown id does not cost the caller
    the nineteen deletions that succeeded.
    """
    if len(garment_ids) > MAX_BULK_ITEMS:
        raise BulkTooLarge(
            f"At most {MAX_BULK_ITEMS} garments may be deleted in one request.",
            detail={"max_items": MAX_BULK_ITEMS, "received": len(garment_ids)},
        )

    outcomes: list[BulkItemOutcome] = []
    for index, garment_id in enumerate(garment_ids):
        try:
            receipt = await delete_garment(
                session, user_id=user_id, garment_id=garment_id, reason=reason
            )
        except ApiError as exc:
            await session.rollback()
            outcomes.append(
                BulkItemOutcome(
                    index=index,
                    media_asset_id=garment_id,
                    status="failed",
                    code=exc.code,
                    message=exc.message,
                )
            )
            continue
        outcomes.append(
            BulkItemOutcome(
                index=index,
                media_asset_id=garment_id,
                status="deleted",
                garment_id=receipt.garment_id,
            )
        )
    return outcomes


__all__ = [
    "BACKGROUND_REMOVAL_JOB_KIND",
    "CATEGORIES",
    "CATEGORISATION_CONFIDENCE_CHECK",
    "CATEGORISATION_WRITABLE_COLUMNS",
    "CATEGORISE_JOB_KIND",
    "CATEGORY_AUTOFILL_CONFIDENCE",
    "CATEGORY_LABELS",
    "CATEGORY_SLOT",
    "COLOUR_LABELS",
    "FAVOURITE_INDEX",
    "FORBIDDEN_INFERENCE_KEYS",
    "GARMENT_ASSET_UNIQUE_INDEX",
    "MATERIAL_LABELS",
    "MAX_BULK_ITEMS",
    "ONE_PIECE_CATEGORIES",
    "PATTERN_LABELS",
    "SLOTS",
    "SLOT_LABELS",
    "UNKNOWN",
    "BulkGarmentItem",
    "BulkItemOutcome",
    "BulkTooLarge",
    "CategorisationResult",
    "ClosedLabelViolation",
    "DeletionReceipt",
    "ForbiddenInference",
    "bulk_create_garments",
    "bulk_delete_garments",
    "check_confidence",
    "check_label",
    "delete_garment",
    "enqueue_media_pipeline",
    "extend_garment_model",
    "favourite_garment_ids",
    "list_favourites",
    "parse_categorisation",
    "record_categorisation",
    "reject_forbidden_inference",
    "set_favourite",
]
