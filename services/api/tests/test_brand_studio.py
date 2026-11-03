"""Brand visuals: several frames of one product, asked for once.

The properties worth pinning are the ones a brand would be misled by if
they were wrong.

**The product survives.** Every frame edits the brand's own photograph and
the clause protecting it goes last in the prompt, after the brief, because
an edit follows its final instruction most closely.

**A reference contributes words, not pixels.** The model takes one image,
so a fit from Discover cannot be composited in. The API returns the note
it did contribute, rather than letting a brand assume more happened.

**Video is blocked, and says so.** No model reachable here emits video.

**A cast is asked for.** Nothing reads appearance off a garment or a
prompt, and an unrecognised value is dropped rather than echoed into one.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import brand_studio as domain
from app.domain import fit_descriptions
from app.workers import brand_studio as prompts
from tests.test_feed import _fit
from tests.test_fit_descriptions import DESCRIBED
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


# --------------------------------------------------------------------------- #
# the prompts
# --------------------------------------------------------------------------- #
def test_the_clause_protecting_the_product_goes_last() -> None:
    """There is no mask on the edit endpoint, so the wording is the only
    thing keeping the garment the garment - and an edit follows its final
    instruction most closely. A brief that ended the prompt could undo
    it."""
    built = prompts.compose(
        scene=prompts.SCENES[0],
        brief="change the colour to red and restyle it completely",
    )
    assert built.endswith(prompts.KEEP_THE_GARMENT)
    assert built.index("brand's direction") < built.index(prompts.KEEP_THE_GARMENT)


def test_a_brief_is_labelled_as_the_brands_words() -> None:
    built = prompts.compose(scene=prompts.SCENES[0], brief="cold and blue")
    assert "The brand's direction for this frame: cold and blue" in built


def test_a_brief_is_bounded() -> None:
    """Long enough for a real direction, short enough that it cannot bury
    the clause after it."""
    built = prompts.compose(scene=prompts.SCENES[0], brief="x" * 5000)
    assert "x" * prompts.MAX_BRIEF in built
    assert "x" * (prompts.MAX_BRIEF + 1) not in built


def test_a_cast_only_speaks_in_words_it_was_given() -> None:
    """A prompt is not a place to echo client input."""
    cast = prompts.Cast.from_choices(
        {"age": "20s", "skin": "deep", "hair": "<script>", "build": "enormous"}
    )
    assert cast.age == "20s"
    assert cast.skin == "deep"
    assert cast.hair is None
    assert cast.build is None
    sentence = cast.sentence()
    assert "script" not in sentence
    assert "enormous" not in sentence


def test_an_empty_cast_says_nothing_rather_than_guessing() -> None:
    """Unspecified means the edit decides. Nothing is inferred."""
    assert prompts.Cast.from_choices({}).sentence() == ""
    assert prompts.Cast.from_choices(None).sentence() == ""


def test_a_cast_is_ignored_on_a_frame_with_nobody_in_it() -> None:
    flat = next(scene for scene in prompts.SCENES if not scene.wears)
    built = prompts.compose(
        scene=flat, cast=prompts.Cast.from_choices({"age": "20s"})
    )
    assert "in their 20s" not in built


def test_a_style_note_is_offered_as_a_spirit_not_a_copy() -> None:
    built = prompts.compose(
        scene=prompts.SCENES[0], style_note="washed daylight, oversized layers"
    )
    assert "in the spirit of this reference" in built


def test_every_ready_made_set_names_frames_that_exist() -> None:
    for kind in prompts.STORY_KINDS:
        assert kind.scenes
        for scene in kind.scenes:
            assert prompts.scene_by_id(scene) is not None, (kind.id, scene)


def test_the_reader_prompt_forbids_describing_the_person() -> None:
    """The note rides into an image prompt, so a description of somebody's
    face would be a way to generate the likeness of a person who posted an
    outfit for a different purpose."""
    said = prompts.STYLE_NOTE_INSTRUCTION.lower()
    assert "do not describe the person" in said
    for part in ("face", "body", "skin", "hair", "age"):
        assert part in said


# --------------------------------------------------------------------------- #
# starting a story
# --------------------------------------------------------------------------- #
async def _product(db: AsyncSession, user_id: uuid.UUID):
    """A garment with a photograph behind it."""
    from tests.test_garment_media import make_asset, make_garment

    asset = await make_asset(db, user_id=user_id)
    return await make_garment(db, user_id=user_id, asset=asset)


async def test_a_launch_queues_one_frame_per_scene_in_order(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    garment = await _product(db, me)

    story, frames = await domain.start(
        db, user_id=me, kind="launch", garment_id=garment.id, brief="linen, summer"
    )
    expected = prompts.story_kind_by_id("launch").scenes
    assert [f.treatment for f in frames] == list(expected)
    assert [f.position for f in frames] == list(range(len(expected)))
    assert all(f.state == "queued" for f in frames)
    assert all(f.story_id == story.id for f in frames)
    # Each frame carries the exact wording it will run.
    assert all(f.prompt and "linen, summer" in f.prompt for f in frames)


async def test_every_frame_edits_the_same_photograph(db: AsyncSession) -> None:
    """Resolved once, so a second check is not a second chance to be wrong."""
    me = await make_user(db)
    garment = await _product(db, me)
    _, frames = await domain.start(db, user_id=me, kind="campaign", garment_id=garment.id)
    assert len({f.source_asset_id for f in frames}) == 1


async def test_naming_scenes_overrides_the_ready_made_set(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    garment = await _product(db, me)
    story, frames = await domain.start(
        db, user_id=me, kind="launch", scenes=["detail"], garment_id=garment.id
    )
    assert [f.treatment for f in frames] == ["detail"]
    assert story.kind == "launch"


async def test_an_unknown_scene_is_refused_rather_than_skipped(
    db: AsyncSession,
) -> None:
    """Silently dropping it would give a brand fewer frames than they
    asked for with nothing saying why."""
    me = await make_user(db)
    garment = await _product(db, me)
    with pytest.raises(domain.NoSuchScene):
        await domain.start(
            db, user_id=me, scenes=["moon_landing"], garment_id=garment.id
        )


async def test_somebody_elses_garment_is_refused(db: AsyncSession) -> None:
    from app.domain import garment_studio as studio

    me = await make_user(db)
    them = await make_user(db)
    theirs = await _product(db, them)
    with pytest.raises(studio.NotYourGarment):
        await domain.start(db, user_id=me, kind="launch", garment_id=theirs.id)


async def test_a_reference_fit_contributes_words_and_is_recorded(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    author = await make_user(db)
    garment = await _product(db, me)
    post = await _fit(db, user_id=author, caption="", tags=["minimal"])
    await fit_descriptions.store(db, post_id=post.id, described=DESCRIBED)

    story, frames = await domain.start(
        db,
        user_id=me,
        kind="campaign",
        garment_id=garment.id,
        reference_post_id=post.id,
    )
    assert story.reference_post_id == post.id
    assert story.style_note == DESCRIBED.outfit
    assert all("in the spirit of this reference" in f.prompt for f in frames)


async def test_a_blocked_authors_fit_contributes_nothing(
    db: AsyncSession,
) -> None:
    """The story still starts - a reference is optional - but nothing of
    that person's photograph reaches the prompt."""
    from app.models.moderation import Block

    me = await make_user(db)
    author = await make_user(db)
    garment = await _product(db, me)
    post = await _fit(db, user_id=author, caption="", tags=["minimal"])
    await fit_descriptions.store(db, post_id=post.id, described=DESCRIBED)
    db.add(Block(blocker_id=me, blocked_id=author))
    await db.commit()

    story, frames = await domain.start(
        db,
        user_id=me,
        kind="campaign",
        garment_id=garment.id,
        reference_post_id=post.id,
    )
    assert story.style_note is None
    assert all("in the spirit of this reference" not in f.prompt for f in frames)


# --------------------------------------------------------------------------- #
# how a story settles
# --------------------------------------------------------------------------- #
def test_a_partly_finished_set_is_partial_rather_than_failed() -> None:
    """Three frames of four is a usable set, and calling it a failure
    would throw away work a brand has paid for."""

    class Frame:
        def __init__(self, state: str) -> None:
            self.state = state

    settle = domain.settle
    assert settle(None, [Frame("ready"), Frame("ready")]) == "ready"
    assert settle(None, [Frame("ready"), Frame("queued")]) == "working"
    assert settle(None, [Frame("ready"), Frame("failed")]) == "partial"
    assert settle(None, [Frame("failed"), Frame("failed")]) == "failed"
    assert settle(None, []) == "failed"


# --------------------------------------------------------------------------- #
# the routes
# --------------------------------------------------------------------------- #
async def test_the_capability_route_is_honest_about_video_and_one_image(
    client: Any, auth: Any
) -> None:
    headers = auth(sub="kc-brand-can")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.get("/v1/studio/capabilities", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["video"] == "blocked"
    assert "never produce" in body["video_reason"] or "never" in body["video_reason"]
    assert "single source image" in body["source_note"]
    assert {s["id"] for s in body["scenes"]} == set(prompts.SCENE_IDS)
    assert set(body["cast_options"]) == set(prompts.CAST_OPTIONS)


async def test_a_story_with_no_product_is_refused(
    client: Any, auth: Any
) -> None:
    headers = auth(sub="kc-brand-nosource")
    await client.post("/v1/auth/session", headers=headers)
    r = await client.post("/v1/studio/stories", json={"kind": "launch"}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "no_source"


async def test_a_story_for_somebody_elses_product_is_404(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-brand-notmine")
    await client.post("/v1/auth/session", headers=headers)
    them = await make_user(db)
    theirs = await _product(db, them)

    r = await client.post(
        "/v1/studio/stories",
        json={"kind": "launch", "garment_id": str(theirs.id)},
        headers=headers,
    )
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"
