"""The catalogue shot a wardrobe garment gets when it is added.

**Why a cut-out was not enough.** A garment arrives as a phone
photograph - on a bed, half in shadow, at an angle. Background removal
is segmentation, so the best it can return is that same crumpled
garment with the room taken away, and on a dark garment it returns a
blob: a black sock against a dim duvet has no edge to find. The
wardrobe was showing exactly that.

The packshot is an edit of the owner's own photograph that re-stages
it the way a shop photographs stock. Three properties carry this
module, and each is a way it could do harm instead of good:

* it is **their garment**, an edit of their picture, so it is never
  badged as a render - the badge means "a drawing of one like yours";
* it **supersedes the cut-out and never the photograph**, so the
  evidence of what they own is still there afterwards;
* every failure **leaves the wardrobe as it was**, because a picture
  that did not improve must not be able to remove the one that worked.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CapabilityUnavailable
from app.models.media_asset import MediaAsset
from app.providers.base import GeneratedImage
from app.workers.garment_studio import Treatment
from app.workers.packshot import (
    PACKSHOT_JOB_KIND,
    PACKSHOT_MEDIA_KIND,
    make_packshot,
    packshot_storage_key,
)

from tests.test_garment_media import (
    InMemoryMediaStore,
    enqueued_job,
    make_asset,
    make_garment,
    make_user,
    reload,
    solid_png,
)

pytestmark = pytest.mark.anyio


class Studio:
    """A studio that returns one picture and records what it was asked."""

    def __init__(
        self, *, image: bytes = b"packshot-bytes", content_type: str = "image/webp"
    ) -> None:
        self.image = image
        self.content_type = content_type
        self.calls: list[Treatment] = []

        self.prompts: list[str | None] = []
        self.photos: list[bytes] = []

    async def shoot(
        self,
        *,
        photo: bytes,
        treatment: Treatment,
        prompt: str | None = None,
        **_: Any,
    ) -> GeneratedImage:
        self.calls.append(treatment)
        self.prompts.append(prompt)
        self.photos.append(photo)
        return GeneratedImage(data=self.image, content_type=self.content_type)


class Refuses:
    async def shoot(self, **_: Any) -> GeneratedImage:
        raise CapabilityUnavailable(
            "no edit here", detail={"capability": "image_edit"}
        )


class ReturnsNothing:
    async def shoot(self, **_: Any) -> GeneratedImage:
        return GeneratedImage(data=b"", content_type="image/webp")


async def _ready(db: AsyncSession) -> tuple[Any, Any, Any, InMemoryMediaStore]:
    """A user with one garment, its photograph, and a queued packshot."""
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)
    store = InMemoryMediaStore()
    store.objects[asset.storage_key or str(asset.id)] = solid_png()
    job = await enqueued_job(
        db, garment=garment, asset=asset, user_id=user_id, kind=PACKSHOT_JOB_KIND
    )
    return garment, asset, job, store


# --------------------------------------------------------------------------- #
# the happy path
# --------------------------------------------------------------------------- #
async def test_the_shot_becomes_the_garments_picture(db: AsyncSession) -> None:
    garment, _asset, job, store = await _ready(db)
    studio = Studio()

    out = await make_packshot(db, job, studio=studio, store=store)
    await db.commit()

    assert out["packshot"] is True
    after = await reload(db, garment.id)
    assert after.background_removed_asset_id is not None
    shot = await db.get(MediaAsset, after.background_removed_asset_id)
    assert shot is not None and shot.kind == PACKSHOT_MEDIA_KIND


async def test_it_runs_the_packshot_treatment_and_not_another(
    db: AsyncSession,
) -> None:
    """**The Studio tab and the wardrobe must not drift apart.**

    "On a model" and "In a scene" are also edits of the same
    photograph, and either would quietly fill a wardrobe with
    pictures of strangers.
    """
    _garment, _asset, job, store = await _ready(db)
    studio = Studio()

    await make_packshot(db, job, studio=studio, store=store)

    assert [t.id for t in studio.calls] == ["packshot"]


async def test_the_photograph_is_kept(db: AsyncSession) -> None:
    """It is the evidence the shot was derived from."""
    garment, asset, job, store = await _ready(db)

    await make_packshot(db, job, studio=Studio(), store=store)
    await db.commit()

    after = await reload(db, garment.id)
    assert after.media_asset_id == asset.id


async def test_it_is_not_badged_as_a_render(db: AsyncSession) -> None:
    """**The badge is a claim about provenance.**

    `image_is_rendered` means "this is a drawing of a garment like
    yours, because yours could not be cut out". A packshot is an edit
    of their own photograph, so saying so would be a lie in the
    direction that matters: it would tell somebody the picture is not
    evidence of what they own, when it is.
    """
    garment, _asset, job, store = await _ready(db)

    await make_packshot(db, job, studio=Studio(), store=store)
    await db.commit()

    assert (await reload(db, garment.id)).image_is_rendered is False


async def test_the_bytes_are_stored_under_the_type_they_actually_are(
    db: AsyncSession,
) -> None:
    """**Not assumed to be PNG.**

    The vendor's image endpoint returns WEBP where an OpenAI-shaped
    client makes PNG the natural guess, and bytes stored under the
    wrong type render on some clients and silently fail on others.
    """
    garment, _asset, job, store = await _ready(db)

    await make_packshot(
        db, job, studio=Studio(content_type="image/webp"), store=store
    )
    await db.commit()

    after = await reload(db, garment.id)
    shot = await db.get(MediaAsset, after.background_removed_asset_id)
    assert shot is not None
    assert shot.content_type == "image/webp"
    assert (shot.storage_key or "").endswith(".webp")


def test_the_key_follows_the_bytes() -> None:
    asset = MediaAsset(
        user_id=uuid.uuid4(), kind="outfit_photo", status="ready", version=3
    )
    asset.id = uuid.uuid4()
    assert packshot_storage_key(asset, content_type="image/png").endswith("/v3.png")
    assert packshot_storage_key(asset, content_type="image/webp").endswith("/v3.webp")


# --------------------------------------------------------------------------- #
# the wardrobe is never made worse
# --------------------------------------------------------------------------- #
async def test_a_studio_that_cannot_run_leaves_the_cut_out_alone(
    db: AsyncSession,
) -> None:
    """The reason this runs last in the pipeline."""
    garment, _asset, job, store = await _ready(db)
    cutout = await make_asset(db, user_id=garment.user_id)
    garment.background_removed_asset_id = cutout.id
    await db.commit()

    out = await make_packshot(db, job, studio=Refuses(), store=store)
    await db.commit()

    assert out["packshot"] is False
    assert (await reload(db, garment.id)).background_removed_asset_id == cutout.id


async def test_a_shot_with_no_image_changes_nothing(db: AsyncSession) -> None:
    """Never a silent fallback to the source: handing back the input as
    though it were the result is the one failure a person cannot see."""
    garment, _asset, job, store = await _ready(db)

    out = await make_packshot(db, job, studio=ReturnsNothing(), store=store)
    await db.commit()

    assert out["packshot"] is False
    assert (await reload(db, garment.id)).background_removed_asset_id is None


async def test_a_deleted_garment_is_not_shot(db: AsyncSession) -> None:
    """A paid call for a picture nobody will ever see."""
    from datetime import UTC, datetime

    garment, _asset, job, store = await _ready(db)
    garment.deleted_at = datetime.now(UTC)
    await db.commit()

    studio = Studio()
    out = await make_packshot(db, job, studio=studio, store=store)

    assert out == {"packshot": False, "reason": "garment_deleted"}
    assert studio.calls == []


# --------------------------------------------------------------------------- #
# not twice
# --------------------------------------------------------------------------- #
async def test_a_garment_already_shot_is_not_shot_again(db: AsyncSession) -> None:
    """Each run is a paid edit. A retry after a partial failure must
    not buy a second one."""
    garment, _asset, job, store = await _ready(db)
    await make_packshot(db, job, studio=Studio(), store=store)
    await db.commit()

    second = Studio()
    out = await make_packshot(db, job, studio=second, store=store)

    assert out["reason"] == "already_present"
    assert second.calls == []


async def test_a_plain_cut_out_does_not_count_as_already_shot(
    db: AsyncSession,
) -> None:
    """**Checked on the asset's kind, not on the field being set.**

    The cut-out lands in the same field, and a cut-out is precisely
    what this exists to improve on - so reading the field alone would
    make the feature skip every garment it was written for.
    """
    garment, _asset, job, store = await _ready(db)
    # A real cut-out inherits the photograph's kind, which is exactly
    # why the field alone cannot distinguish the two.
    cutout = await make_asset(db, user_id=garment.user_id)
    assert cutout.kind == "garment_photo"
    garment.background_removed_asset_id = cutout.id
    await db.commit()

    studio = Studio()
    out = await make_packshot(db, job, studio=studio, store=store)
    await db.commit()

    assert out["packshot"] is True
    assert len(studio.calls) == 1
    assert (await reload(db, garment.id)).background_removed_asset_id != cutout.id


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #
def test_the_packshot_is_a_paid_call_and_sits_on_the_paid_queue() -> None:
    """On `default` it would wait behind the sweeper."""
    from app.queue.celery_app import QUEUE_AI, QUEUE_BY_PREFIX

    assert QUEUE_BY_PREFIX["garment.packshot"] == QUEUE_AI


async def test_adding_a_garment_queues_one(db: AsyncSession) -> None:
    """**The whole point: it happens on upload, not on request.**

    "Add a piece" and "From photos" are the two ways a garment enters
    a wardrobe, and both land here.
    """
    import sqlalchemy as sa

    from app.domain.garment_media import enqueue_media_pipeline
    from app.models.job import Job

    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(db, user_id=user_id, asset=asset)

    queued = await enqueue_media_pipeline(db, garment=garment, user_id=user_id)
    await db.commit()

    assert PACKSHOT_JOB_KIND in queued
    job = await db.scalar(sa.select(Job).where(Job.kind == PACKSHOT_JOB_KIND))
    assert job is not None
    # Held back, so detection and categorisation settle what this
    # photograph actually is before a shot is hung off it.
    assert job.available_at is not None and job.available_at > job.created_at


# --------------------------------------------------------------------------- #
# Which picture it is made from
#
# **Reported, and it was my own doing.** A photograph of somebody
# wearing six things is split into six garments, and each one's
# `media_asset_id` points at its own cut-out - the documented
# workaround for the one-garment-per-upload index. The first version
# of this worker read that field for its source, so it re-staged a
# pixelated, part-occluded silhouette and produced a speckled stone
# blob where a pair of headphones should have been. Garbage in,
# faithfully rendered.
#
# The photograph is the only thing that still knows what the garment
# looks like. The cut-out has already thrown that away.
# --------------------------------------------------------------------------- #
async def test_a_named_piece_is_isolated_from_the_whole_photograph(
    db: AsyncSession,
) -> None:
    garment, asset, job, store = await _ready(db)
    job.payload = {**(job.payload or {}), "subject": "white neck headphones"}
    await db.commit()
    studio = Studio()

    await make_packshot(db, job, studio=studio, store=store)

    [prompt] = studio.prompts
    assert prompt is not None, "the treatment's own wording packshots everything"
    assert "white neck headphones" in prompt
    assert "no person" in prompt and "no other clothing" in prompt
    # And it is told not to improve on what it can see, because the
    # point is this garment rather than a nicer one.
    assert "do not invent detail" in prompt.lower()


async def test_a_single_garment_upload_runs_the_plain_treatment(
    db: AsyncSession,
) -> None:
    """Nothing to disambiguate: there is one garment in the frame."""
    _garment, _asset, job, store = await _ready(db)
    studio = Studio()

    await make_packshot(db, job, studio=studio, store=store)

    assert studio.prompts == [None]


async def test_the_bytes_edited_are_the_source_assets(db: AsyncSession) -> None:
    """Pinned because the whole defect was reading the wrong asset."""
    _garment, asset, job, store = await _ready(db)
    studio = Studio()

    await make_packshot(db, job, studio=studio, store=store)

    assert studio.photos == [store.objects[asset.storage_key or str(asset.id)]]


# --------------------------------------------------------------------------- #
# A pair is one thing
#
# **Reported: one packshot per shoe.** Asked for "white chunky
# sneakers" the model returned a single sneaker, and the wardrobe
# then showed one shoe as the item somebody owns. Nobody owns one
# sneaker. Socks, gloves and earrings are the same shape of mistake:
# one wardrobe item, two objects, and the model does not assume it.
#
# Pinned across all three prompts because they were written at
# different times for different callers and the next person editing
# one of them will not know about the other two.
# --------------------------------------------------------------------------- #
def test_every_packshot_prompt_keeps_a_pair_together() -> None:
    from app.workers.garment_studio import treatment_by_id
    from app.workers.packshot import ISOLATE
    from app.workers.piece_packshot import PIECE_PROMPT

    wardrobe = treatment_by_id("packshot")
    assert wardrobe is not None

    for name, said in (
        ("isolate-from-photo", ISOLATE.format(subject="white sneakers")),
        ("from-words", PIECE_PROMPT.format(phrase="white sneakers")),
        ("studio-treatment", wardrobe.prompt),
    ):
        lowered = said.lower()
        assert "pair" in lowered, name
        assert "side by side" in lowered, name
