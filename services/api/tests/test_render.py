"""Rendering a garment the photograph will not give up.

The feature exists for one case: a garment that is plainly present and plainly
not extractable, because something overlaps it. Cutting it out then yields a
fragment — a shirt with a bag-shaped hole — and the wardrobe shows nonsense.

Three properties carry this module, and each is a way the feature could do
harm rather than good:

* a render is **only** reached when the cut-out would be unusable, so a real
  garment is never quietly replaced by a drawing of one like it;
* a render is **labelled** as one, so nothing downstream can treat a drawing
  as evidence of what somebody owns;
* a render that fails **falls back** to the cut-out, because a fallback that
  can take the whole job down with it is not a fallback.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.garment import Garment
from app.models.media_asset import MediaAsset
from app.providers.base import GeneratedImage
from app.providers.segmentation import CUTOUT_BACKGROUND
from app.workers.outfit import (
    DEFAULT_VISIBILITY,
    DETECT_OUTFIT_JOB_KIND,
    VISIBILITY_LABELS,
    DetectedGarment,
    OutfitDetection,
    detect_outfit,
)
from app.workers.render import (
    RENDER_MEDIA_KIND,
    MetaGarmentRenderer,
    render_prompt,
)
from tests.test_garment_media import (
    StubSegmenter,
    enqueued_job,
    make_asset,
    make_garment,
    make_user,
    result,
    solid_png,
)


# --------------------------------------------------------------------------- #
# the prompt
# --------------------------------------------------------------------------- #
def test_the_prompt_describes_only_what_was_observed() -> None:
    """A render must not invent what nobody saw.

    The classifier reports a closed set of appearance labels. A prompt that
    added a brand, a size, or a fibre would be asserting something about the
    user's garment that no part of this system ever established.
    """
    prompt = render_prompt(
        "button-up shirt",
        result(colour="white", pattern="plain", apparent_material="linen"),
    )

    assert "button-up shirt" in prompt
    assert "white" in prompt
    assert "linen" in prompt
    # Appearance, never a composition claim.
    assert "look like linen" in prompt
    # Nothing is asserted that was not observed. The only mentions of brands
    # and logos are the instructions forbidding them.
    assert "no logo" in prompt and "no brand mark" in prompt
    for unobserved in ("cotton", "polyester", "medium", "large"):
        assert unobserved not in prompt.lower()


def test_the_prompt_asks_for_a_tile_that_matches_the_rest_of_the_grid() -> None:
    """A render sits beside real cut-outs, so it has to look like one."""
    prompt = render_prompt("wool coat", result(colour="black"))

    # Same ground as a cut-out, or the grid reads as two sources of picture.
    assert CUTOUT_BACKGROUND in prompt
    # A wardrobe is a grid of garments, not of people wearing them.
    for excluded in ("No person", "no model", "no mannequin"):
        assert excluded in prompt
    assert "contact shadow" in prompt


def test_an_unknown_attribute_is_left_out_rather_than_described() -> None:
    """'unknown' is the classifier declining to answer, not an adjective."""
    prompt = render_prompt(
        "trousers", result(colour="unknown", pattern="unknown", apparent_material="unknown")
    )

    assert "unknown" not in prompt
    assert "trousers" in prompt


def test_a_plain_pattern_is_not_announced() -> None:
    """Saying 'plain-patterned' of a plain garment reads as a defect."""
    assert "plain-patterned" not in render_prompt("tee", result(pattern="plain"))


# --------------------------------------------------------------------------- #
# the adapter contract
# --------------------------------------------------------------------------- #
def test_the_decoder_reads_the_shape_the_endpoint_actually_returns() -> None:
    """Verified live: base64 in ``data[i].b64_json``, ``url`` always null.

    Pinned because the client is OpenAI-shaped and invites the assumption that
    a URL is available and that the bytes are PNG. Neither is true here.
    """
    import base64

    from app.providers.meta import _decode_images

    payload = {
        "output_format": "webp",
        "data": [
            {"b64_json": base64.b64encode(b"first").decode(), "url": None},
            {"b64_json": base64.b64encode(b"second").decode(), "url": None},
        ],
    }
    images = _decode_images(payload)

    assert [image.data for image in images] == [b"first", b"second"]
    assert {image.content_type for image in images} == {"image/webp"}


def test_an_undecodable_entry_does_not_discard_the_others() -> None:
    """The call is already paid for; salvage what came back."""
    import base64

    from app.providers.meta import _decode_images

    payload = {
        "output_format": "webp",
        "data": [{"b64_json": None}, {"b64_json": base64.b64encode(b"ok").decode()}],
    }
    assert [image.data for image in _decode_images(payload)] == [b"ok"]


async def test_a_provider_that_returns_no_image_is_reported_not_retried() -> None:
    """Charged and given nothing. A second identical call would be billed too."""
    from app.errors import CapabilityUnavailable
    from app.providers.base import AIResponse, TokenUsage

    class Empty:
        async def generate_image(self, request: Any, **kwargs: Any) -> AIResponse:
            return AIResponse(
                provider="stub", model="stub-image", usage=TokenUsage(), images=1
            )

    with pytest.raises(CapabilityUnavailable):
        await MetaGarmentRenderer(Empty()).render(
            noun_phrase="shirt", classification=result()
        )


# --------------------------------------------------------------------------- #
# when a render is reached at all
# --------------------------------------------------------------------------- #
def test_visibility_decides_and_the_forgiving_value_is_the_default() -> None:
    assert VISIBILITY_LABELS == ("clear", "partly_hidden", "mostly_hidden")
    # Defaulting to 'clear' keeps the real cut-out and spends nothing when the
    # model declines to judge.
    assert DEFAULT_VISIBILITY == "clear"
    assert not DetectedGarment(
        noun_phrase="shirt", classification=result(), confidence=0.9
    ).needs_render


@pytest.mark.parametrize(
    ("visibility", "expected"),
    [("clear", False), ("partly_hidden", False), ("mostly_hidden", True)],
)
def test_only_a_mostly_hidden_garment_is_worth_drawing(
    visibility: str, expected: bool
) -> None:
    """Partly hidden still cuts out into something that reads as the garment."""
    piece = DetectedGarment(
        noun_phrase="shirt",
        classification=result(),
        confidence=0.9,
        visibility=visibility,
    )
    assert piece.needs_render is expected


class StubRenderer:
    def __init__(self, *, image: bytes | None = None, error: Exception | None = None):
        self.image = image
        self.error = error
        self.calls = 0

    async def render(self, **kwargs: Any) -> GeneratedImage:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return GeneratedImage(data=self.image or b"", content_type="image/webp")


class StubDetector:
    def __init__(self, *garments: DetectedGarment) -> None:
        self.garments = garments

    async def detect(self, **kwargs: Any) -> OutfitDetection:
        return OutfitDetection(worn=True, garments=self.garments)


async def _run(
    db: AsyncSession,
    *,
    garments: tuple[DetectedGarment, ...],
    renderer: Any,
    segmenter: Any,
) -> dict[str, Any]:
    from tests.test_garment_media import InMemoryMediaStore

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()
    job = await enqueued_job(
        db, garment=garment, asset=asset, user_id=user_id, kind=DETECT_OUTFIT_JOB_KIND
    )
    return await detect_outfit(
        db,
        job,
        detector=StubDetector(*garments),
        segmenter=segmenter,
        store=store,
        renderer=renderer,
    )


def _piece(visibility: str, name: str = "shirt") -> DetectedGarment:
    return DetectedGarment(
        noun_phrase=name,
        classification=result(),
        confidence=0.9,
        visibility=visibility,
    )


async def test_a_hidden_garment_is_drawn_and_stored_as_a_render(
    db: AsyncSession,
) -> None:
    renderer = StubRenderer(image=b"RIFFdrawn")
    segmenter = StubSegmenter(image=solid_png())

    outcome = await _run(
        db,
        garments=(_piece("mostly_hidden"), _piece("clear", "trousers")),
        renderer=renderer,
        segmenter=segmenter,
    )

    assert outcome["rendered"] == 1
    assert renderer.calls == 1
    # The visible garment still went through segmentation; the hidden one
    # never did, because its cut-out would have been paid for and discarded.
    assert segmenter.calls == 1

    kinds = {
        asset.kind
        for asset in (await db.execute(__import__("sqlalchemy").select(MediaAsset)))
        .scalars()
        .all()
    }
    assert RENDER_MEDIA_KIND in kinds, "a drawing was stored as if it were a photograph"


async def test_a_visible_garment_keeps_its_real_cut_out(db: AsyncSession) -> None:
    """The user's own garment beats a good drawing of one like it."""
    renderer = StubRenderer(image=b"RIFFdrawn")

    outcome = await _run(
        db,
        garments=(_piece("clear"), _piece("partly_hidden", "coat")),
        renderer=renderer,
        segmenter=StubSegmenter(image=solid_png()),
    )

    assert outcome["rendered"] == 0
    assert renderer.calls == 0


async def test_a_failed_render_falls_back_to_the_cut_out(db: AsyncSession) -> None:
    """A fallback that can fail the job is not a fallback.

    A fragment of the real garment is worth more than nothing, and the garment
    is recorded either way.
    """
    segmenter = StubSegmenter(image=solid_png())

    outcome = await _run(
        db,
        garments=(_piece("mostly_hidden"), _piece("clear", "trousers")),
        renderer=StubRenderer(error=RuntimeError("quota")),
        segmenter=segmenter,
    )

    assert outcome["rendered"] == 0
    assert outcome["garments"] == 2
    # Two cut-outs: the fallback for the hidden one, and the visible one.
    assert segmenter.calls == 2, "the cut-out was not attempted after the render failed"


async def test_no_renderer_configured_is_simply_the_old_behaviour(
    db: AsyncSession,
) -> None:
    segmenter = StubSegmenter(image=solid_png())

    outcome = await _run(
        db,
        garments=(_piece("mostly_hidden"), _piece("clear", "trousers")),
        renderer=None,
        segmenter=segmenter,
    )

    assert outcome["rendered"] == 0
    assert segmenter.calls == 2


# --------------------------------------------------------------------------- #
# not paying twice for the same answer
# --------------------------------------------------------------------------- #
# Outfit detection classifies every garment it finds, including when the
# photograph turns out to hold exactly one. Discarding that and letting the
# categorise job ask again cost a second model call and the seconds somebody
# spends watching a spinner for it.


async def test_a_single_garment_is_sorted_by_the_detector_itself(
    db: AsyncSession,
) -> None:
    outcome = await _run(
        db,
        garments=(_piece("clear", "linen shirt"),),
        renderer=None,
        segmenter=StubSegmenter(image=solid_png()),
    )

    assert outcome["reason"] == "single_garment"
    assert outcome["sorted_from_detection"] is True


async def test_the_categorise_job_then_calls_nothing(db: AsyncSession) -> None:
    """The second opinion is the thing being removed, so it must not happen."""
    import sqlalchemy as sa

    from app.workers.categorise import CATEGORISE_JOB_KIND, categorise
    from tests.test_garment_media import InMemoryMediaStore, StubClassifier

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()

    # Stand in for what detection already wrote.
    await db.execute(
        sa.update(Garment)
        .where(Garment.id == garment.id)
        .values(inference_version="outfit.v1", category="shirt")
    )
    await db.commit()

    job = await enqueued_job(
        db, garment=garment, asset=asset, user_id=user_id, kind=CATEGORISE_JOB_KIND
    )
    classifier = StubClassifier()
    outcome = await categorise(db, job, classifier=classifier, store=store)

    assert outcome["reason"] == "already_categorised"
    assert classifier.calls == 0, "paid for a second opinion on the same photograph"


async def test_detection_never_overwrites_an_answer_that_got_there_first(
    db: AsyncSession,
) -> None:
    """Saving a call is not worth losing a better answer.

    `only_if_unset` is what makes the write a claim on an empty slot rather
    than an update, so an earlier run — or a user's own correction — stands.
    """
    import sqlalchemy as sa

    from app.domain.garment_media import record_categorisation
    from tests.test_garment_media import result as classification

    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)
    await db.execute(
        sa.update(Garment)
        .where(Garment.id == garment.id)
        .values(inference_version="earlier.v1", category="knitwear")
    )
    await db.commit()

    written = await record_categorisation(
        db,
        garment.id,
        classification(category="shirt"),
        inference_version="outfit.v1",
        only_if_unset=True,
    )
    await db.commit()

    assert written is False
    db.expunge_all()
    fresh = await db.get(Garment, garment.id)
    assert fresh is not None
    assert fresh.category == "knitwear"
    assert fresh.inference_version == "earlier.v1"


# --------------------------------------------------------------------------- #
# a packshot for each piece
# --------------------------------------------------------------------------- #
async def _shots(db: AsyncSession) -> list[Any]:
    """The Studio's own shots: pictures somebody asked it to make."""
    import sqlalchemy as sa

    from app.models.garment_studio import GarmentShot

    rows = await db.scalars(sa.select(GarmentShot))
    return list(rows)


async def _packshot_jobs(db: AsyncSession) -> list[Any]:
    """The wardrobe packshots the fan-out queued, one per piece.

    **These used to be `GarmentShot` rows and the pictures were
    thrown away.** `garment_studio.request` makes a shot somebody
    asked for on the Studio screen, and nothing ever pointed the
    garment at the result: measured on a real account, nine ready
    packshots and zero garments showing one. The wardrobe kept its
    segmentation cut-out, which is the thing a packshot exists to
    replace. The fan-out now queues the wardrobe's own job, which
    repoints the garment when the picture lands.
    """
    import sqlalchemy as sa

    from app.models.job import Job
    from app.workers.packshot import PACKSHOT_JOB_KIND

    rows = await db.scalars(sa.select(Job).where(Job.kind == PACKSHOT_JOB_KIND))
    return list(rows)


async def test_each_piece_of_a_worn_outfit_gets_its_own_packshot(
    db: AsyncSession,
) -> None:
    """One wardrobe item, one picture of it.

    A cut-out from a worn photograph is shaped round a body, lit by
    whatever room the person was standing in, and often part-hidden by
    an arm. The wardrobe shows the garment, so each piece is restyled
    as a catalogue packshot of its own - not one grouped picture,
    which would be the same image under four different items.
    """
    outcome = await _run(
        db,
        garments=(
            _piece(DEFAULT_VISIBILITY, "lilac long sleeve tee"),
            _piece(DEFAULT_VISIBILITY, "patchwork cargo trousers"),
            _piece(DEFAULT_VISIBILITY, "tan suede trainers"),
        ),
        renderer=None,
        segmenter=StubSegmenter(image=solid_png()),
    )

    assert outcome["garments"] == 3
    assert outcome["packshots"] == 3

    shots = await _packshot_jobs(db)
    assert len(shots) == 3
    # Each against its own garment, or the wardrobe gets one picture
    # three times.
    assert len({shot.payload["garment_id"] for shot in shots}) == 3

    # **The original photograph, never the piece's cut-out.**
    #
    # A fan-out piece's `media_asset_id` points at its own cut-out,
    # and those cut-outs are exactly what a packshot exists to
    # improve on. The first version read that field and re-staged a
    # pixelated silhouette: a pair of headphones came back as a
    # speckled stone blob, faithfully rendered from rubbish.
    sources = {shot.payload["asset_id"] for shot in shots}
    assert len(sources) == 1, "one photograph, which is what they came from"

    # And each job says which garment to take out of it, because the
    # photograph holds all three.
    assert {shot.payload["subject"] for shot in shots} == {
        "lilac long sleeve tee",
        "patchwork cargo trousers",
        "tan suede trainers",
    }


async def test_a_piece_nothing_could_be_isolated_from_is_not_shot(
    db: AsyncSession,
) -> None:
    """There is no picture of it to restyle.

    Its source would be the whole photograph, so the packshot would
    be of the person wearing it - and it would be billed.
    """

    class RefusesToCut:
        async def cutout(self, **kwargs: Any) -> Any:
            from app.providers.segmentation import SegmentationUnavailable

            raise SegmentationUnavailable("no subject found")

    # Two pieces, so this is a worn outfit and takes the fan-out path
    # at all. One piece would fall through to the single-garment
    # branch, which never offered a packshot in the first place.
    outcome = await _run(
        db,
        garments=(_piece(DEFAULT_VISIBILITY, "shirt"), _piece(DEFAULT_VISIBILITY, "jeans")),
        renderer=None,
        segmenter=RefusesToCut(),
    )

    assert outcome["without_cutout"] == 2
    assert outcome["packshots"] == 0
    assert await _packshot_jobs(db) == []


async def test_a_studio_that_cannot_take_the_work_does_not_lose_the_wardrobe(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The garments are the result; a packshot is an improvement.

    So a studio that is down, out of quota or misconfigured costs the
    nicer picture and nothing else. Raising here would mean a failed
    detection and no wardrobe items at all, which is strictly worse
    than three pieces with their cut-outs.
    """

    async def refuse(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the queue is down")

    # Patched where the fan-out actually calls it. It used to go
    # through `garment_studio.request`; patching that now proves
    # nothing, because nothing on this path calls it.
    from app.domain import jobs as jobs_domain

    monkeypatch.setattr(jobs_domain, "enqueue", refuse)

    outcome = await _run(
        db,
        garments=(_piece(DEFAULT_VISIBILITY, "shirt"), _piece(DEFAULT_VISIBILITY, "jeans")),
        renderer=None,
        segmenter=StubSegmenter(image=solid_png()),
    )

    assert outcome["garments"] == 2, "the wardrobe still got its pieces"
    assert outcome["packshots"] == 0
    assert await _packshot_jobs(db) == []


# --------------------------------------------------------------------------- #
# the studio's split: a picture per garment, instead of one of the lot
# --------------------------------------------------------------------------- #
async def _split(
    db: AsyncSession,
    *,
    garments: tuple[DetectedGarment, ...],
    segmenter: Any,
    treatment: str = "packshot",
) -> dict[str, Any]:
    from app.domain.garment_studio import SPLIT_JOB_KIND
    from app.domain.jobs import enqueue
    from app.workers.outfit import split_shots
    from tests.test_garment_media import InMemoryMediaStore

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key] = solid_png()

    job = await enqueue(
        db,
        SPLIT_JOB_KIND,
        {
            "asset_id": str(asset.id),
            "asset_version": asset.version,
            "garment_id": None,
            "user_id": str(user_id),
            "treatment": treatment,
            "brief": None,
        },
        idempotency_key=f"{SPLIT_JOB_KIND}:{asset.id}:{treatment}",
    )
    await db.commit()
    return await split_shots(
        db, job, detector=StubDetector(*garments), segmenter=segmenter, store=store
    )


async def test_the_split_makes_one_picture_per_garment(db: AsyncSession) -> None:
    """The opt-in case: two garments wanted as two catalogue images.

    The grouped packshot remains the default - handed the same
    photograph without asking for a split, the studio returns one
    picture with both in it.
    """
    outcome = await _split(
        db,
        garments=(
            _piece(DEFAULT_VISIBILITY, "lilac long sleeve tee"),
            _piece(DEFAULT_VISIBILITY, "patchwork cargo trousers"),
        ),
        segmenter=StubSegmenter(image=solid_png()),
    )

    assert outcome["split"] is True
    assert outcome["shots"] == 2

    shots = await _shots(db)
    assert {shot.treatment for shot in shots} == {"packshot"}
    # Each shot off its own cut-out, or they are two renders of the
    # same picture.
    assert len({shot.source_asset_id for shot in shots}) == 2


async def test_the_split_never_fills_the_wardrobe(db: AsyncSession) -> None:
    """This is somebody making pictures, not cataloguing a cupboard.

    The intake split creates a garment per piece because that is what
    filling a wardrobe means. This path is often handed a camera roll
    photograph that is not theirs to own, so it writes cut-outs and
    shots and no garments at all.
    """
    import sqlalchemy as sa

    before = len((await db.scalars(sa.select(Garment))).all())
    await _split(
        db,
        garments=(_piece(DEFAULT_VISIBILITY, "tee"), _piece(DEFAULT_VISIBILITY, "jeans")),
        segmenter=StubSegmenter(image=solid_png()),
    )
    after = len((await db.scalars(sa.select(Garment))).all())
    assert after == before, "a studio split must not create wardrobe items"


async def test_one_garment_is_not_worth_splitting(db: AsyncSession) -> None:
    """Splitting a photograph of one garment is the ordinary request.

    Doing it the long way would pay for a segmentation first and
    arrive at the same picture.
    """
    outcome = await _split(
        db,
        garments=(_piece(DEFAULT_VISIBILITY, "tee"),),
        segmenter=StubSegmenter(image=solid_png()),
    )
    assert outcome["split"] is False
    assert outcome["reason"] == "single_garment"
    assert outcome["shots"] == 1
    assert len(await _shots(db)) == 1


async def test_a_piece_that_will_not_segment_costs_only_itself(
    db: AsyncSession,
) -> None:
    """Partial success is the normal outcome.

    A bag half behind a hip may not cut out cleanly while the shirt
    and the trousers do, and two packshots beats a failed job.
    """

    class CutsOnce:
        """Segments the first piece and refuses the rest."""

        def __init__(self) -> None:
            self.calls = 0

        async def cutout(self, **kwargs: Any) -> Any:
            from app.providers.segmentation import SegmentationUnavailable

            self.calls += 1
            if self.calls > 1:
                raise SegmentationUnavailable("no subject found")
            return await StubSegmenter(image=solid_png()).cutout(**kwargs)

    outcome = await _split(
        db,
        garments=(
            _piece(DEFAULT_VISIBILITY, "tee"),
            _piece(DEFAULT_VISIBILITY, "jeans"),
            _piece(DEFAULT_VISIBILITY, "bag"),
        ),
        segmenter=CutsOnce(),
    )

    assert outcome["shots"] == 1
    assert outcome["without_cutout"] == 2
    assert len(await _shots(db)) == 1
