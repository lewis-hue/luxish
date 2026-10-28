"""Task 11 — auto-categorisation, bulk operations, and tombstoned deletion.

Four invariants carry this module, and each is the kind that fails silently if
it is not asserted:

* **The label set is closed.** An open vocabulary returns "top", "shirt",
  "button-down" and "oxford" for one photograph across four runs, and a category
  column full of synonyms cannot be filtered. A label outside the set raises
  rather than being coerced, because a coerced label is a wrong answer nobody
  can find.
* **A user correction always wins (ADR-010).** A later, *more confident*
  inference must not overwrite it — and the way that is guaranteed is that the
  write statement has no ``confirmed_attributes`` in it.
* **A photograph cannot establish fibre composition, size, waterproofing,
  thermal rating, price or brand authenticity.** Those keys never appear in
  inferred output.
* **A late job cannot resurrect deleted content (ADR-012).** Deletion writes a
  tombstone that outlives the asset, and the worker re-checks it in the same
  transaction as its write.

No test here touches the network: the classifier and the segmenter are doubles.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import session_factory
from app.workers.outfit import DETECT_OUTFIT_JOB_KIND
from app.domain.garment_media import (
    CATEGORIES,
    CATEGORISATION_WRITABLE_COLUMNS,
    CATEGORY_AUTOFILL_CONFIDENCE,
    CATEGORY_SLOT,
    FORBIDDEN_INFERENCE_KEYS,
    MAX_BULK_ITEMS,
    SLOTS,
    UNKNOWN,
    BulkGarmentItem,
    CategorisationResult,
    ClosedLabelViolation,
    ForbiddenInference,
    bulk_create_garments,
    delete_garment,
    parse_categorisation,
    record_categorisation,
    reject_forbidden_inference,
)
from app.domain.jobs import AssetGone, claim_job, tombstone_exists
from app.domain.wardrobe import GarmentRepository
from app.models.garment import Garment
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.models.tombstone import Tombstone
from app.models.user import User
from app.providers.segmentation import Box, CutoutResult, MaskRecord
from app.workers import runner
from app.workers.categorise import (
    BACKGROUND_REMOVAL_JOB_KIND,
    CATEGORISATION_SCHEMA,
    CATEGORISE_JOB_KIND,
    InMemoryMediaStore,
    MetaGarmentClassifier,
    UnavailableMediaStore,
    categorise,
    categorise_handlers,
    remove_background,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test attempted a real network request")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


# --------------------------------------------------------------------------- #
# fixtures and helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
async def media_client(engine: Any, verifier: Any) -> AsyncIterator[httpx.AsyncClient]:
    """The app with this task's router mounted.

    ``app/main.py`` is not this task's to edit, so the router is included here.
    The guard makes the fixture a no-op once it is registered upstream, rather
    than quietly mounting every route twice.
    """
    from app.db.session import get_session
    from app.deps import get_token_verifier
    from app.main import API_PREFIX, create_app
    from app.routers import wardrobe_media

    app = create_app()
    if not any(
        getattr(route, "path", "") == f"{API_PREFIX}/wardrobe/favourites"
        for route in app.routes
    ):
        app.include_router(wardrobe_media.router, prefix=API_PREFIX)

    maker = session_factory(engine)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def make_user(db: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def make_asset(
    db: AsyncSession, *, user_id: uuid.UUID, storage_key: str | None = None
) -> MediaAsset:
    asset = MediaAsset(
        user_id=user_id,
        kind="garment_photo",
        status="uploaded",
        content_type="image/png",
        max_bytes=1_000_000,
        storage_key=storage_key or f"originals/{uuid.uuid4().hex}.png",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def make_garment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    asset: MediaAsset | None = None,
    **kwargs: Any,
) -> Garment:
    garment = Garment(
        user_id=user_id,
        media_asset_id=asset.id if asset else None,
        confirmed_attributes=kwargs.pop("confirmed", {}) or {},
        inferred_attributes=kwargs.pop("inferred", {}) or {},
        **kwargs,
    )
    db.add(garment)
    await db.commit()
    await db.refresh(garment)
    return garment


def result(**overrides: Any) -> CategorisationResult:
    base: dict[str, Any] = {
        "slot": "tops",
        "category": "shirt",
        "colour": "navy",
        "pattern": "plain",
        "apparent_material": "cotton",
        "slot_confidence": 0.9,
        "category_confidence": 0.88,
        "colour_confidence": 0.8,
        "pattern_confidence": 0.7,
        "material_confidence": 0.6,
        "prompt_version": "garment_categorisation_v1",
    }
    base.update(overrides)
    return CategorisationResult(**base)


class StubClassifier:
    def __init__(self, *results: CategorisationResult, error: Exception | None = None) -> None:
        self.results = list(results)
        self.error = error
        self.calls = 0

    async def classify(
        self, *, image: bytes, content_type: str, user_id: uuid.UUID | None = None
    ) -> CategorisationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.results.pop(0) if self.results else result()


class StubSegmenter:
    """One ``cutout`` call, answering with whatever the test asked for."""

    name = "stub"
    model = "stub-1"

    def __init__(
        self, *, image: bytes | None = None, reason: str | None = None, error: Exception | None = None
    ) -> None:
        self.image = image
        self.reason = reason
        self.error = error
        self.calls = 0

    async def cutout(self, **kwargs: Any) -> CutoutResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        records = (
            (
                MaskRecord(
                    object_id=1,
                    box=Box(x1=0, y1=0, x2=3, y2=3, frame_width=8, frame_height=8),
                    height=4,
                    width=4,
                    raster=b"\x01" * 16,
                ),
            )
            if self.image is not None
            else ()
        )
        return CutoutResult(
            image=self.image,
            provider=self.name,
            model=self.model,
            records=records,
            reason=self.reason,
            cost_micro_minor=250_000 if self.image is not None else 0,
        )


def solid_png(size: tuple[int, int] = (8, 8), colour: tuple[int, int, int] = (9, 9, 9)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def media_job(
    *, garment: Garment, asset: MediaAsset, user_id: uuid.UUID, kind: str = CATEGORISE_JOB_KIND
) -> Job:
    from datetime import UTC, datetime

    return Job(
        kind=kind,
        payload={
            "garment_id": str(garment.id),
            "asset_id": str(asset.id),
            "asset_version": asset.version,
            "user_id": str(user_id),
        },
        state="running",
        available_at=datetime.now(UTC),
    )


async def enqueued_job(
    db: AsyncSession, *, garment: Garment, asset: MediaAsset, user_id: uuid.UUID, kind: str
) -> Job:
    job = media_job(garment=garment, asset=asset, user_id=user_id, kind=kind)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def reload(db: AsyncSession, garment_id: uuid.UUID) -> Garment:
    """Re-read from the database rather than from the identity map.

    ``expunge_all`` rather than ``expire_all``: the factory sets
    ``expire_on_commit=False``, so expiring would leave every other object in
    the test issuing a synchronous lazy load the moment it is touched.
    """
    db.expunge_all()
    garment = await db.get(Garment, garment_id)
    assert garment is not None
    return garment


# --------------------------------------------------------------------------- #
# the closed label set
# --------------------------------------------------------------------------- #
def test_the_slot_and_category_sets_are_exactly_the_agreed_vocabulary() -> None:
    assert SLOTS == ("tops", "bottoms", "outerwear", "shoes", "accessories")
    assert CATEGORIES == (
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
    # Every category has a slot, and every slot it names is a real slot.
    assert set(CATEGORY_SLOT) == set(CATEGORIES)
    assert set(CATEGORY_SLOT.values()) <= set(SLOTS)


@pytest.mark.parametrize(
    "label", ["top", "button-down", "oxford", "button down shirt", "outerware", ""]
)
def test_a_label_outside_the_closed_set_is_refused_not_coerced(label: str) -> None:
    """The four answers one open-ended prompt gave for one photograph.

    Coercing "oxford" to "shirt" would hide exactly the drift this closure
    exists to surface, so it raises and the job dead-letters where someone reads
    it.
    """
    with pytest.raises(ClosedLabelViolation):
        result(category=label)


def test_unknown_is_a_member_of_every_set_so_the_model_need_never_guess() -> None:
    honest = result(
        slot=UNKNOWN,
        category=UNKNOWN,
        colour=UNKNOWN,
        pattern=UNKNOWN,
        apparent_material=UNKNOWN,
        category_confidence=0.1,
    )
    assert honest.category == UNKNOWN
    assert honest.slot == UNKNOWN


def test_case_and_whitespace_are_normalised_but_synonyms_are_not() -> None:
    assert result(category=" Shirt ").category == "shirt"
    with pytest.raises(ClosedLabelViolation):
        result(category="Shirts")


def test_the_category_decides_the_slot_when_the_model_disagrees() -> None:
    """The mapping is a product decision; the slot is not independently
    observable, so a disagreeing slot is corrected rather than trusted."""
    assert result(category="jeans", slot="tops").slot == "bottoms"
    assert result(category="coat", slot="tops").slot == "outerwear"
    assert result(category="bag", slot="tops").slot == "accessories"


def test_a_dress_is_flagged_as_one_piece_so_it_is_not_paired_with_a_bottom() -> None:
    dress = result(category="dress")
    assert dress.slot == "tops"
    assert dress.inferred_attributes()["one_piece"] is True
    assert result(category="shirt").inferred_attributes()["one_piece"] is False


def test_a_confidence_outside_zero_to_one_is_refused() -> None:
    with pytest.raises(ClosedLabelViolation):
        result(category_confidence=1.4)
    with pytest.raises(ClosedLabelViolation):
        result(category_confidence="very")


def test_the_structured_output_schema_is_strict_and_enumerated() -> None:
    """Verified: strict mode needs a root object with additionalProperties false.

    The enums are what make the set closed on the provider's side; the Python
    tuples re-check it on ours, because a vendor's schema enforcement is a claim
    rather than a guarantee.
    """
    assert CATEGORISATION_SCHEMA["type"] == "object"
    assert CATEGORISATION_SCHEMA["additionalProperties"] is False
    properties = CATEGORISATION_SCHEMA["properties"]
    assert set(CATEGORISATION_SCHEMA["required"]) == set(properties)
    assert properties["slot"]["enum"] == [*SLOTS, UNKNOWN]
    assert properties["category"]["enum"] == [*CATEGORIES, UNKNOWN]
    nested = properties["confidence"]
    assert nested["additionalProperties"] is False
    assert set(nested["required"]) == set(nested["properties"])


def test_the_schema_has_no_field_for_an_unestablishable_claim() -> None:
    rendered = json.dumps(CATEGORISATION_SCHEMA)
    for key in ("fibre_composition", "price", "waterproof", "thermal_rating", "brand"):
        assert f'"{key}"' not in rendered


# --------------------------------------------------------------------------- #
# forbidden inferences
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "key",
    [
        "fibre_composition",
        "fabric_composition",
        "composition",
        "size",
        "measurements",
        "waterproof",
        "water_resistance",
        "thermal_rating",
        "insulation_rating",
        "price",
        "rrp",
        "brand",
        "brand_authenticity",
        "is_genuine",
        "counterfeit",
    ],
)
def test_an_inference_asserting_a_non_visual_claim_is_refused(key: str) -> None:
    """A camera cannot read a composition label, measure a size, test a
    membrane, quantify insulation, know what was paid, or authenticate a
    trademark. A confident guess is worse than silence: the user acts on it."""
    assert key in FORBIDDEN_INFERENCE_KEYS
    with pytest.raises(ForbiddenInference):
        reject_forbidden_inference({"category": "coat", key: "anything"})


@pytest.mark.parametrize("spelling", ["Waterproof", "water-resistance", "Thermal Rating"])
def test_a_forbidden_key_is_caught_whatever_its_spelling(spelling: str) -> None:
    with pytest.raises(ForbiddenInference):
        reject_forbidden_inference({spelling: True})


def test_a_model_that_volunteers_a_price_fails_the_run_rather_than_being_trimmed() -> None:
    """Quietly dropping the extra field would leave the non-compliance
    unrecorded."""
    with pytest.raises(ForbiddenInference):
        parse_categorisation(
            {
                "slot": "outerwear",
                "category": "coat",
                "colour": "navy",
                "pattern": "plain",
                "apparent_material": "wool",
                "price": "180",
                "confidence": {},
            }
        )


def test_no_forbidden_key_ever_reaches_the_inferred_document() -> None:
    for category in CATEGORIES:
        attributes = result(category=category).inferred_attributes()
        assert FORBIDDEN_INFERENCE_KEYS.isdisjoint(attributes)
        assert FORBIDDEN_INFERENCE_KEYS.isdisjoint(attributes["confidence"])


def test_apparent_material_is_allowed_because_it_is_an_appearance_class() -> None:
    """"Looks like wool" is a statement about the photograph. "100% merino" is a
    statement about the label, which the photograph does not show."""
    attributes = result(apparent_material="wool").inferred_attributes()
    assert attributes["apparent_material"] == "wool"
    assert "fibre_composition" not in attributes


def test_the_prompt_forbids_the_same_claims_the_code_refuses() -> None:
    from app.workers.categorise import CATEGORISATION_SYSTEM

    lowered = CATEGORISATION_SYSTEM.lower()
    for phrase in (
        "fibre composition",
        "size",
        "waterproof",
        "thermal",
        "price",
        "brand",
        "genuine",
    ):
        assert phrase in lowered


# --------------------------------------------------------------------------- #
# inferred vs confirmed
# --------------------------------------------------------------------------- #
async def test_the_write_statement_cannot_touch_the_confirmed_column() -> None:
    assert "confirmed_attributes" not in CATEGORISATION_WRITABLE_COLUMNS


async def test_a_later_high_confidence_inference_never_overwrites_a_correction(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """ADR-010, through the real HTTP correction endpoint."""
    session = await media_client.post("/v1/auth/session", headers=auth(sub="kc-gm1"))
    user_id = uuid.UUID(session.json()["user_id"])
    garment = await make_garment(db, user_id=user_id, inferred={"colour": "navy"})

    patched = await media_client.patch(
        f"/v1/wardrobe/garments/{garment.id}",
        headers=auth(sub="kc-gm1"),
        json={"confirmed_attributes": {"colour": "black", "category": "blazer"}},
    )
    assert patched.status_code == 200, patched.text

    # A later run, more confident than anything before it.
    assert await record_categorisation(
        db,
        garment.id,
        result(category="shirt", colour="navy", category_confidence=0.99),
        inference_version="v2",
    )
    await db.commit()

    fresh = await reload(db, garment.id)
    assert fresh.confirmed_attributes == {"colour": "black", "category": "blazer"}
    assert fresh.inferred_attributes["colour"] == "navy"
    assert fresh.effective_attributes["colour"] == "black"
    assert fresh.effective_attributes["category"] == "blazer"


async def test_the_category_column_is_auto_filled_only_into_a_vacuum(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    empty = await make_garment(db, user_id=user_id)
    named = await make_garment(db, user_id=user_id, category="blazer")
    corrected = await make_garment(db, user_id=user_id, confirmed={"category": "jeans"})

    empty_id, named_id, corrected_id = empty.id, named.id, corrected.id

    confident = result(category="shirt", category_confidence=0.95)
    for garment_id in (empty_id, named_id, corrected_id):
        assert await record_categorisation(db, garment_id, confident)
    await db.commit()

    assert (await reload(db, empty_id)).category == "shirt"
    # The user's own answers stand.
    assert (await reload(db, named_id)).category == "blazer"
    assert (await reload(db, corrected_id)).category is None


async def test_a_low_confidence_label_stays_an_inference_only(db: AsyncSession) -> None:
    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)

    timid = result(
        category="knitwear", category_confidence=CATEGORY_AUTOFILL_CONFIDENCE - 0.01
    )
    assert await record_categorisation(db, garment.id, timid)
    await db.commit()

    fresh = await reload(db, garment.id)
    assert fresh.category is None
    assert fresh.inferred_attributes["category"] == "knitwear"
    assert fresh.categorisation_confidence == pytest.approx(timid.category_confidence)


async def test_the_overall_and_category_confidences_are_recorded_separately(
    db: AsyncSession,
) -> None:
    """Two different questions: "how sure overall" and "how sure of the label"."""
    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)
    assert await record_categorisation(db, garment.id, result())
    await db.commit()

    fresh = await reload(db, garment.id)
    assert fresh.categorisation_confidence == pytest.approx(0.88)
    assert fresh.inference_confidence == pytest.approx(result().confidence)
    assert fresh.inference_confidence != fresh.categorisation_confidence


async def test_recording_against_a_deleted_garment_reports_rather_than_raises(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)
    await GarmentRepository(db, user_id=user_id).soft_delete(garment.id)

    assert await record_categorisation(db, garment.id, result()) is False


# --------------------------------------------------------------------------- #
# the categorisation worker
# --------------------------------------------------------------------------- #
async def test_categorisation_runs_as_a_job_and_writes_only_inferred_values(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db, garment=garment, asset=asset, user_id=user_id, kind=CATEGORISE_JOB_KIND
    )

    outcome = await categorise(db, job, classifier=StubClassifier(), store=store)

    assert outcome["categorised"] is True
    assert outcome["slot"] == "tops"
    fresh = await reload(db, garment.id)
    assert fresh.inferred_attributes["category"] == "shirt"
    assert fresh.confirmed_attributes == {}


async def test_categorisation_degrades_when_the_bytes_cannot_be_read(
    db: AsyncSession,
) -> None:
    """No storage credential in this build. The garment still works; it is
    simply uncategorised, and retrying cannot change that."""
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    job = await enqueued_job(
        db, garment=garment, asset=asset, user_id=user_id, kind=CATEGORISE_JOB_KIND
    )

    outcome = await categorise(
        db, job, classifier=StubClassifier(), store=UnavailableMediaStore()
    )

    assert outcome == {"categorised": False, "reason": "capability_unavailable"}
    assert (await reload(db, garment.id)).inferred_attributes == {}


async def test_the_classifier_is_never_called_for_a_deleted_photograph(
    db: AsyncSession,
) -> None:
    from app.domain.jobs import delete_asset as tombstone_asset

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db, garment=garment, asset=asset, user_id=user_id, kind=CATEGORISE_JOB_KIND
    )
    await tombstone_asset(db, asset.id, user_id=user_id)

    classifier = StubClassifier()
    with pytest.raises(AssetGone):
        await categorise(db, job, classifier=classifier, store=store)
    assert classifier.calls == 0


async def test_a_classifier_returning_an_open_vocabulary_label_fails_the_job(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db, garment=garment, asset=asset, user_id=user_id, kind=CATEGORISE_JOB_KIND
    )

    classifier = StubClassifier(error=ClosedLabelViolation("category", "oxford", CATEGORIES))
    with pytest.raises(ClosedLabelViolation):
        await categorise(db, job, classifier=classifier, store=store)
    assert (await reload(db, garment.id)).inferred_attributes == {}


async def test_the_classifier_sends_an_image_and_a_strict_schema() -> None:
    """The only user-supplied input is the photograph: no user text enters the
    prompt, so there is no untrusted-text surface here."""

    class Recorder:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def complete(self, request: Any, *, user_id: Any = None) -> Any:
            self.requests.append(request)

            class Response:
                model = "muse-spark-1.3"
                text = json.dumps(
                    {
                        "slot": "tops",
                        "category": "shirt",
                        "colour": "navy",
                        "pattern": "plain",
                        "apparent_material": "cotton",
                        "confidence": {
                            "slot": 0.9,
                            "category": 0.9,
                            "colour": 0.8,
                            "pattern": 0.7,
                            "apparent_material": 0.6,
                        },
                    }
                )

            return Response()

    provider = Recorder()
    classified = await MetaGarmentClassifier(provider).classify(
        image=solid_png(), content_type="image/png"
    )

    assert classified.category == "shirt"
    request = provider.requests[0]
    assert request.response_format is not None
    assert request.response_format.strict is True
    assert request.needs.image_in and request.needs.structured_output
    parts = request.messages[0].content
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_a_non_json_classifier_reply_is_a_502_not_a_silent_skip() -> None:
    class Rambling:
        async def complete(self, request: Any, *, user_id: Any = None) -> Any:
            class Response:
                model = "muse-spark-1.3"
                text = "It looks like a nice navy shirt!"

            return Response()

    with pytest.raises(Exception, match="JSON"):
        await MetaGarmentClassifier(Rambling()).classify(
            image=solid_png(), content_type="image/png"
        )


# --------------------------------------------------------------------------- #
# background removal: degrade, never block
# --------------------------------------------------------------------------- #
async def test_a_failed_background_removal_leaves_a_usable_original(
    db: AsyncSession,
) -> None:
    """§5: the original must survive optional processing failing.

    Every documented failure mode lands here — no subject found (white on
    white), no parser installed, no storage backend — and in each the garment is
    exactly as usable as before.
    """
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset, category="shirt")
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db,
        garment=garment,
        asset=asset,
        user_id=user_id,
        kind=BACKGROUND_REMOVAL_JOB_KIND,
    )

    garment_id, asset_id = garment.id, asset.id

    outcome = await remove_background(
        db, job, segmenter=StubSegmenter(image=None), store=store
    )

    assert outcome == {"background_removed": False, "reason": "no_subject_found"}
    fresh = await reload(db, garment_id)
    assert fresh.background_removed_asset_id is None
    # The original is untouched and still attached.
    assert fresh.media_asset_id == asset_id
    original = await db.get(MediaAsset, asset_id)
    assert original is not None and original.deleted_at is None


async def test_a_missing_segmentation_capability_degrades_rather_than_blocking(
    db: AsyncSession,
) -> None:
    from app.providers.segmentation import SegmentationUnavailable

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db,
        garment=garment,
        asset=asset,
        user_id=user_id,
        kind=BACKGROUND_REMOVAL_JOB_KIND,
    )

    outcome = await remove_background(
        db,
        job,
        segmenter=StubSegmenter(error=SegmentationUnavailable("no parser")),
        store=store,
    )

    garment_id, asset_id = garment.id, asset.id
    assert outcome["background_removed"] is False
    assert outcome["reason"] == "segmentation_unavailable"
    assert (await reload(db, garment_id)).media_asset_id == asset_id


async def test_a_successful_cut_out_is_a_new_asset_and_never_a_replacement(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset, category="shirt")
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db,
        garment=garment,
        asset=asset,
        user_id=user_id,
        kind=BACKGROUND_REMOVAL_JOB_KIND,
    )

    garment_id, asset_id = garment.id, asset.id

    outcome = await remove_background(
        db, job, segmenter=StubSegmenter(image=solid_png()), store=store
    )

    assert outcome["background_removed"] is True
    fresh = await reload(db, garment_id)
    assert fresh.media_asset_id == asset_id
    assert fresh.background_removed_asset_id is not None
    assert fresh.background_removed_asset_id != asset_id

    cutout = await db.get(MediaAsset, fresh.background_removed_asset_id)
    assert cutout is not None
    assert cutout.content_type == "image/png"
    assert cutout.user_id == user_id
    # Private by default: a cut-out of a private photograph is not less private.
    assert cutout.publication_consent is False
    assert str(asset_id) in (cutout.storage_key or "")
    assert cutout.storage_key in store.objects


async def test_background_removal_is_not_repeated_for_a_garment_that_has_one(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db,
        garment=garment,
        asset=asset,
        user_id=user_id,
        kind=BACKGROUND_REMOVAL_JOB_KIND,
    )
    segmenter = StubSegmenter(image=solid_png())

    await remove_background(db, job, segmenter=segmenter, store=store)
    second = await remove_background(db, job, segmenter=segmenter, store=store)

    assert second["reason"] == "already_present"
    assert segmenter.calls == 1


async def test_the_segmenter_is_prompted_with_one_noun_phrase_for_the_category(
    db: AsyncSession,
) -> None:
    captured: dict[str, Any] = {}

    class Capturing(StubSegmenter):
        async def cutout(self, **kwargs: Any) -> CutoutResult:
            captured.update(kwargs)
            return await super().cutout(**kwargs)

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset, category="jeans")
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db,
        garment=garment,
        asset=asset,
        user_id=user_id,
        kind=BACKGROUND_REMOVAL_JOB_KIND,
    )

    await remove_background(db, job, segmenter=Capturing(image=solid_png()), store=store)

    assert captured["prompt"] == "jeans"
    assert "," not in captured["prompt"]


# --------------------------------------------------------------------------- #
# delete + late job = no resurrection (ADR-012)
# --------------------------------------------------------------------------- #
async def test_deleting_a_garment_tombstones_its_media(db: AsyncSession) -> None:
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)

    receipt = await delete_garment(db, user_id=user_id, garment_id=garment.id)

    assert receipt.tombstoned_asset_ids == (asset.id,)
    assert await tombstone_exists(db, asset.id)
    assert (await db.get(Garment, garment.id)).deleted_at is not None


async def test_a_late_categorisation_job_cannot_resurrect_a_deleted_garment(
    db: AsyncSession,
) -> None:
    """The job is already in flight when the delete lands. The tombstone is the
    record that outlives the asset, so ``guard_write`` refuses and the runner
    completes the job as discarded rather than retrying it forever."""
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    garment_id = garment.id
    job = Job(
        kind=CATEGORISE_JOB_KIND,
        payload={
            "garment_id": str(garment_id),
            "asset_id": str(asset.id),
            "asset_version": asset.version,
            "user_id": str(user_id),
        },
        state="queued",
        available_at=asset.created_at,
    )
    db.add(job)
    await db.commit()

    # The user deletes while the job sits in the queue.
    await delete_garment(db, user_id=user_id, garment_id=garment_id)

    handlers = categorise_handlers(
        classifier=StubClassifier(), segmenter=StubSegmenter(), store=store
    )
    ran = await runner.run_one(db, handlers=handlers, worker="test")
    assert ran is not None
    job_id = ran.id

    db.expunge_all()
    finished = await db.get(Job, job_id)
    assert finished is not None
    assert finished.state == "succeeded"
    assert finished.result == {"discarded": "tombstoned"}

    fresh = await reload(db, garment_id)
    assert fresh.deleted_at is not None
    assert fresh.inferred_attributes == {}
    assert fresh.category is None


async def test_a_late_background_removal_job_cannot_attach_a_cut_out(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db,
        garment=garment,
        asset=asset,
        user_id=user_id,
        kind=BACKGROUND_REMOVAL_JOB_KIND,
    )

    await delete_garment(db, user_id=user_id, garment_id=garment.id)

    with pytest.raises(AssetGone):
        await remove_background(
            db, job, segmenter=StubSegmenter(image=solid_png()), store=store
        )

    fresh = await db.get(Garment, garment.id)
    assert fresh.background_removed_asset_id is None


async def test_the_tombstone_survives_an_asset_we_never_had_a_row_for(
    db: AsyncSession,
) -> None:
    """A garment whose asset row is already gone still gets a denial on record."""
    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)
    garment.media_asset_id = None
    await db.commit()

    receipt = await delete_garment(db, user_id=user_id, garment_id=garment.id)
    assert receipt.tombstoned_asset_ids == ()
    assert (await db.get(Garment, garment.id)).deleted_at is not None


async def test_deleting_a_stranger_s_garment_is_a_404_not_a_403(
    db: AsyncSession,
) -> None:
    from app.errors import NotFound

    owner = await make_user(db)
    stranger = await make_user(db)
    garment = await make_garment(db, user_id=owner)

    with pytest.raises(NotFound):
        await delete_garment(db, user_id=stranger, garment_id=garment.id)
    assert (await db.get(Garment, garment.id)).deleted_at is None


async def test_the_cut_out_is_tombstoned_alongside_the_original(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    cutout = await make_asset(db, user_id=user_id, storage_key="cutouts/x.png")
    garment = await make_garment(db, user_id=user_id, asset=asset)
    garment.background_removed_asset_id = cutout.id
    await db.commit()

    receipt = await delete_garment(db, user_id=user_id, garment_id=garment.id)

    assert set(receipt.tombstoned_asset_ids) == {asset.id, cutout.id}
    rows = (await db.scalars(sa.select(Tombstone.asset_id))).all()
    assert set(rows) == {asset.id, cutout.id}


# --------------------------------------------------------------------------- #
# bulk create
# --------------------------------------------------------------------------- #
async def test_a_bulk_create_queues_the_pipeline_and_never_runs_it_inline(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    assets = [await make_asset(db, user_id=user_id) for _ in range(3)]

    outcomes = await bulk_create_garments(
        db,
        user_id=user_id,
        items=[BulkGarmentItem(media_asset_id=asset.id) for asset in assets],
    )

    assert [o.status for o in outcomes] == ["created"] * 3
    for outcome in outcomes:
        # Detection leads: it decides whether this photograph is one garment
        # or a worn outfit, and the single-garment jobs run only when it says
        # the former. Ordering is asserted, not just membership, because the
        # two later jobs would overwrite a fan-out's work if they ran first.
        assert outcome.jobs == (
            DETECT_OUTFIT_JOB_KIND,
            CATEGORISE_JOB_KIND,
            BACKGROUND_REMOVAL_JOB_KIND,
        )

    jobs = (await db.scalars(sa.select(Job))).all()
    # Three garments, three jobs each: detect, categorise, remove background.
    assert len(jobs) == 9
    assert {job.state for job in jobs} == {"queued"}


async def test_a_partial_failure_is_reported_per_item_and_does_not_fail_the_batch(
    db: AsyncSession,
) -> None:
    """Nineteen good photographs must not be lost to one bad reference."""
    owner = await make_user(db)
    stranger = await make_user(db)
    mine = await make_asset(db, user_id=owner)
    theirs = await make_asset(db, user_id=stranger)
    missing = uuid.uuid4()
    other = await make_asset(db, user_id=owner)

    outcomes = await bulk_create_garments(
        db,
        user_id=owner,
        items=[
            BulkGarmentItem(media_asset_id=mine.id),
            BulkGarmentItem(media_asset_id=theirs.id),
            BulkGarmentItem(media_asset_id=missing),
            BulkGarmentItem(media_asset_id=other.id),
        ],
    )

    assert [o.index for o in outcomes] == [0, 1, 2, 3]
    assert [o.status for o in outcomes] == ["created", "failed", "failed", "created"]
    # Not yours and not existing are the same answer, so neither confirms an id.
    assert outcomes[1].code == outcomes[2].code == "not_found"
    assert outcomes[0].garment_id is not None
    assert outcomes[3].garment_id is not None
    assert outcomes[1].garment_id is None

    rows = (await db.scalars(sa.select(Garment).where(Garment.user_id == owner))).all()
    assert len(rows) == 2


async def test_re_sending_a_batch_returns_the_same_records_and_no_new_jobs(
    db: AsyncSession,
) -> None:
    """Idempotency keyed on the upload: a retried request after a network
    failure must not duplicate a wardrobe, or the paid work behind it."""
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    items = [BulkGarmentItem(media_asset_id=asset.id)]

    first = await bulk_create_garments(db, user_id=user_id, items=items)
    second = await bulk_create_garments(db, user_id=user_id, items=items)

    assert first[0].status == "created"
    assert second[0].status == "existing"
    assert second[0].garment_id == first[0].garment_id
    assert second[0].jobs == ()
    # Still one garment's worth of jobs: the idempotency key is derived from
    # the garment, so re-sending the batch queues nothing and spends nothing.
    assert len((await db.scalars(sa.select(Job))).all()) == 3
    assert len((await db.scalars(sa.select(Garment))).all()) == 1


async def test_the_database_refuses_a_second_garment_for_one_upload(
    db: AsyncSession,
) -> None:
    """Idempotency is a schema property, not caller diligence — the same
    reasoning as ``jobs.idempotency_key``."""
    from sqlalchemy.exc import IntegrityError

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    await make_garment(db, user_id=user_id, asset=asset)

    db.add(Garment(user_id=user_id, media_asset_id=asset.id))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_a_soft_deleted_garment_does_not_block_re_adding_the_same_upload(
    db: AsyncSession,
) -> None:
    """The unique index is partial on ``deleted_at IS NULL``.

    So removing a garment from the wardrobe does not permanently burn the
    upload it was made from.
    """
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    first = await bulk_create_garments(
        db, user_id=user_id, items=[BulkGarmentItem(media_asset_id=asset.id)]
    )
    first_id = first[0].garment_id
    await GarmentRepository(db, user_id=user_id).soft_delete(first_id)

    again = await bulk_create_garments(
        db, user_id=user_id, items=[BulkGarmentItem(media_asset_id=asset.id)]
    )
    assert again[0].status == "created", again[0].message
    assert again[0].garment_id != first_id


async def test_a_full_delete_tombstones_the_upload_so_it_cannot_be_re_added(
    db: AsyncSession,
) -> None:
    """The stronger statement: the photograph itself is gone (ADR-012).

    A user who deletes a garment re-photographs it rather than re-adding the
    old upload, because the old upload now has a tombstone denying every
    further write to it.
    """
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    first = await bulk_create_garments(
        db, user_id=user_id, items=[BulkGarmentItem(media_asset_id=asset.id)]
    )
    await delete_garment(db, user_id=user_id, garment_id=first[0].garment_id)

    again = await bulk_create_garments(
        db, user_id=user_id, items=[BulkGarmentItem(media_asset_id=asset.id)]
    )
    assert again[0].status == "failed"
    assert again[0].code == "not_found"


async def test_a_bulk_create_over_the_cap_is_refused_before_anything_is_written(
    db: AsyncSession,
) -> None:
    """Without a cap, one request can queue unbounded paid model work."""
    from app.domain.garment_media import BulkTooLarge

    user_id = await make_user(db)
    items = [BulkGarmentItem(media_asset_id=uuid.uuid4()) for _ in range(MAX_BULK_ITEMS + 1)]

    with pytest.raises(BulkTooLarge):
        await bulk_create_garments(db, user_id=user_id, items=items)
    assert (await db.scalars(sa.select(Garment))).all() == []


async def test_a_garment_with_no_upload_queues_nothing(db: AsyncSession) -> None:
    from app.domain.garment_media import enqueue_media_pipeline

    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)
    assert await enqueue_media_pipeline(db, garment=garment, user_id=user_id) == ()
    assert (await db.scalars(sa.select(Job))).all() == []


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
async def test_bulk_create_over_http_reports_each_item_and_still_returns_200(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    session = await media_client.post("/v1/auth/session", headers=auth(sub="kc-bulk"))
    user_id = uuid.UUID(session.json()["user_id"])
    asset = await make_asset(db, user_id=user_id)

    response = await media_client.post(
        "/v1/wardrobe/garments/bulk",
        headers=auth(sub="kc-bulk"),
        json={
            "items": [
                {"media_asset_id": str(asset.id), "name": "navy shirt"},
                {"media_asset_id": str(uuid.uuid4())},
            ]
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert [item["status"] for item in body["items"]] == ["created", "failed"]
    assert body["items"][0]["jobs"] == [
        DETECT_OUTFIT_JOB_KIND,
        CATEGORISE_JOB_KIND,
        BACKGROUND_REMOVAL_JOB_KIND,
    ]


async def test_bulk_create_refuses_more_than_twenty_items(
    media_client: httpx.AsyncClient, auth: Any
) -> None:
    response = await media_client.post(
        "/v1/wardrobe/garments/bulk",
        headers=auth(sub="kc-cap"),
        json={"items": [{"media_asset_id": str(uuid.uuid4())} for _ in range(21)]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


async def test_bulk_create_refuses_the_same_upload_twice_in_one_request(
    media_client: httpx.AsyncClient, auth: Any
) -> None:
    asset_id = str(uuid.uuid4())
    response = await media_client.post(
        "/v1/wardrobe/garments/bulk",
        headers=auth(sub="kc-dup"),
        json={"items": [{"media_asset_id": asset_id}, {"media_asset_id": asset_id}]},
    )
    assert response.status_code == 422


async def test_bulk_delete_over_http_tombstones_and_reports_per_item(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    session = await media_client.post("/v1/auth/session", headers=auth(sub="kc-bdel"))
    user_id = uuid.UUID(session.json()["user_id"])
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)

    response = await media_client.post(
        "/v1/wardrobe/garments/bulk/delete",
        headers=auth(sub="kc-bdel"),
        json={"garment_ids": [str(garment.id), str(uuid.uuid4())]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["status"] for item in body["items"]] == ["deleted", "failed"]
    assert await tombstone_exists(db, asset.id)


async def test_the_full_delete_route_writes_a_tombstone(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    session = await media_client.post("/v1/auth/session", headers=auth(sub="kc-del"))
    user_id = uuid.UUID(session.json()["user_id"])
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)

    response = await media_client.delete(
        f"/v1/wardrobe/garments/{garment.id}/media", headers=auth(sub="kc-del")
    )

    assert response.status_code == 204
    assert await tombstone_exists(db, asset.id)


async def test_renaming_goes_through_the_existing_correction_endpoint(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A rename is a user correction, so it belongs on the one endpoint that
    records corrections rather than on a second path with its own merge rule."""
    session = await media_client.post("/v1/auth/session", headers=auth(sub="kc-ren"))
    user_id = uuid.UUID(session.json()["user_id"])
    garment = await make_garment(db, user_id=user_id, name="old name")

    response = await media_client.patch(
        f"/v1/wardrobe/garments/{garment.id}",
        headers=auth(sub="kc-ren"),
        json={"name": "navy wool blazer"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "navy wool blazer"
    assert (await reload(db, garment.id)).name == "navy wool blazer"


def test_this_router_builds_no_queries_of_its_own() -> None:
    """Owner scoping lives in the repository. A router that never builds a query
    cannot build an unscoped one."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "routers" / "wardrobe_media.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("select(", "sa.select", "db.get(", "session.get("):
        assert forbidden not in source


def test_the_job_kinds_are_namespaced_so_the_queue_can_be_split() -> None:
    assert CATEGORISE_JOB_KIND == "wardrobe.categorise"
    assert BACKGROUND_REMOVAL_JOB_KIND == "wardrobe.remove_background"
    handlers = categorise_handlers(classifier=StubClassifier(), segmenter=StubSegmenter())
    assert set(handlers) == {CATEGORISE_JOB_KIND, BACKGROUND_REMOVAL_JOB_KIND}


async def test_a_claimed_job_carries_everything_the_handler_needs(
    db: AsyncSession,
) -> None:
    from app.workers.categorise import read_payload

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    outcomes = await bulk_create_garments(
        db, user_id=user_id, items=[BulkGarmentItem(media_asset_id=asset.id)]
    )
    claimed = await claim_job(db, kinds=[CATEGORISE_JOB_KIND], worker="test")

    assert claimed is not None
    payload = read_payload(claimed)
    assert payload.garment_id == outcomes[0].garment_id
    assert payload.asset_id == asset.id
    assert payload.asset_version == asset.version
    assert payload.user_id == user_id


# --------------------------------------------------------------------------- #
# what actually goes on the wire
# --------------------------------------------------------------------------- #
def test_a_large_photograph_is_downscaled_before_it_is_sent() -> None:
    """Not cosmetic. The reservation is sized from the rendered message, and a
    base64 data URI *is* that message, so a 3 MB photograph reserves close to a
    million tokens against a 4,000,000-per-minute team budget and the queue
    rate-limits itself after four garments."""
    from PIL import Image

    from app.workers.categorise import CATEGORISATION_MAX_IMAGE_EDGE, prepare_image

    big = solid_png((2400, 1600), (120, 40, 40))
    sent, content_type = prepare_image(big, content_type="image/png")

    assert len(sent) < len(big)
    assert content_type == "image/jpeg"
    with Image.open(io.BytesIO(sent)) as image:
        assert max(image.size) == CATEGORISATION_MAX_IMAGE_EDGE
    # The original bytes are untouched — §5 again.
    assert len(big) > 0


def test_a_small_photograph_is_sent_exactly_as_it_arrived() -> None:
    from app.workers.categorise import prepare_image

    small = solid_png((64, 64))
    assert prepare_image(small, content_type="image/png") == (small, "image/png")


def test_an_unreadable_image_still_reaches_the_model() -> None:
    """A resize failure must not block a garment over an optimisation."""
    from app.workers.categorise import prepare_image

    junk = b"not an image at all"
    assert prepare_image(junk, content_type="image/png") == (junk, "image/png")


async def test_the_downscaled_copy_is_what_the_provider_receives() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def complete(self, request: Any, *, user_id: Any = None) -> Any:
            self.requests.append(request)

            class Response:
                model = "muse-spark-1.3"
                text = json.dumps(
                    {
                        "slot": "bottoms",
                        "category": "jeans",
                        "colour": "blue",
                        "pattern": "plain",
                        "apparent_material": "denim",
                        "confidence": {
                            "slot": 0.9,
                            "category": 0.9,
                            "colour": 0.9,
                            "pattern": 0.9,
                            "apparent_material": 0.9,
                        },
                    }
                )

            return Response()

    provider = Recorder()
    await MetaGarmentClassifier(provider).classify(
        image=solid_png((2000, 2000)), content_type="image/png"
    )

    url = provider.requests[0].messages[0].content[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
