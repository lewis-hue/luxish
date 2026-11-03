"""Reading a fit, and wearing one.

The properties worth pinning are the ones that decide whether "Try it on"
under somebody else's photograph does what it says.

**The author's caption is never replaced.** A generated one fills a gap and
nothing more.

**A description reaches the grouping.** Tags read off the photograph are
written as tags, because a caption that improved nothing anybody browses
would have improved nothing.

**Try-on is gated, and it is real.** A fit this reader cannot see cannot be
worn, and the render it produces is a row on the same pipeline that dresses
the avatar in a curated look.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import fit_descriptions as domain
from app.models.profile import PostTag
from app.workers.fit_vision import FitDescription, Piece, parse_description
from tests.test_feed import _fit
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


DESCRIBED = FitDescription(
    pieces=(
        Piece(name="linen shirt", colour="cream", category="top"),
        Piece(name="wide trousers", colour="black", category="bottom"),
    ),
    outfit="A cream linen shirt tucked into wide black trousers.",
    caption="Cream linen shirt, wide black trousers",
    tags=("linen", "minimal", "tailoring"),
    model="muse-spark-1.3",
)


def test_the_reader_never_has_a_field_for_the_person() -> None:
    """The schema is the guarantee, not only the prompt wording.

    The output rides into an image prompt, so a field describing somebody's
    face would be a way to generate the likeness of a person who posted an
    outfit.
    """
    from app.workers.fit_vision import FIT_VISION_SCHEMA

    properties = set(FIT_VISION_SCHEMA["properties"])
    assert properties == {"pieces", "outfit", "caption", "tags"}
    for banned in ("person", "model", "body", "skin", "hair", "age", "gender"):
        assert banned not in properties


def test_tags_are_normalised_and_deduplicated() -> None:
    """A tag is a join key, so a nearly-right one makes a group of one."""
    read = parse_description(
        {
            "pieces": [],
            "outfit": "A coat.",
            "caption": "A coat",
            "tags": ["#Linen", "linen", "Wide-Leg", "a", "", "MINIMAL"],
        }
    )
    assert read.tags == ("linen", "wideleg", "minimal")


def test_a_description_with_no_outfit_sentence_is_not_usable() -> None:
    """Everything downstream needs it, so a row without it is a trap."""
    assert not parse_description(
        {"pieces": [], "outfit": "   ", "caption": "x", "tags": []}
    ).usable
    assert parse_description(
        {"pieces": [], "outfit": "A coat.", "caption": "", "tags": []}
    ).usable


async def test_the_authors_caption_wins_and_the_description_fills_a_gap(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    theirs = await _fit(db, user_id=author, caption="saturday", tags=[])
    silent = await _fit(db, user_id=author, caption="", tags=[])

    await domain.store(db, post_id=theirs.id, described=DESCRIBED)
    await domain.store(db, post_id=silent.id, described=DESCRIBED)

    assert domain.shown_caption(theirs, await domain.get(db, post_id=theirs.id)) == (
        "saturday"
    )
    assert domain.shown_caption(silent, await domain.get(db, post_id=silent.id)) == (
        "Cream linen shirt, wide black trousers"
    )


async def test_a_description_writes_tags_so_discover_can_group_it(
    db: AsyncSession,
) -> None:
    """Otherwise the reading improved nothing anybody can browse."""
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["streetwear"])

    await domain.store(db, post_id=post.id, described=DESCRIBED)

    tags = set(
        (
            await db.scalars(sa.select(PostTag.tag).where(PostTag.post_id == post.id))
        ).all()
    )
    # The author's own tag survives; the read ones are added beside it.
    assert tags == {"streetwear", "linen", "minimal", "tailoring"}


async def test_storing_twice_replaces_rather_than_accumulates(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=[])

    await domain.store(db, post_id=post.id, described=DESCRIBED)
    await domain.store(
        db,
        post_id=post.id,
        described=FitDescription(
            outfit="A grey coat over jeans.", caption="Grey coat", tags=("denim",)
        ),
    )

    row = await domain.get(db, post_id=post.id)
    assert row is not None
    assert row.outfit == "A grey coat over jeans."
    # The old tags stay - they describe the photograph, which has not
    # changed - and the new one joins them.
    tags = set(
        (
            await db.scalars(sa.select(PostTag.tag).where(PostTag.post_id == post.id))
        ).all()
    )
    assert "denim" in tags and "linen" in tags


async def test_trying_on_a_fit_queues_a_render_carrying_its_source(
    db: AsyncSession,
) -> None:
    """The render has to know which fit it came from.

    Without it the worker cannot read the photograph, and a second try-on
    of a different fit would be deduplicated into the first.
    """
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    await domain.store(db, post_id=post.id, described=DESCRIBED)

    render = await domain.try_on(db, user_id=me, post_id=post.id)
    assert render.kind == "try_on"
    assert render.state == "queued"
    assert render.source_post_id == post.id
    assert render.outfit == DESCRIBED.outfit
    assert [p["name"] for p in render.pieces] == ["linen shirt", "wide trousers"]


async def test_a_fit_with_no_description_still_queues_and_carries_no_outfit(
    db: AsyncSession,
) -> None:
    """The worker reads it. The row must not pretend to know yet."""
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    render = await domain.try_on(db, user_id=me, post_id=post.id)
    assert render.source_post_id == post.id
    assert not render.outfit


async def test_trying_on_two_fits_does_not_collapse_into_one_render(
    db: AsyncSession,
) -> None:
    """Dedupe used to key on the look alone, so the second tap returned
    the first picture - a fit nobody asked for."""
    me = await make_user(db)
    author = await make_user(db)
    first = await _fit(db, user_id=author, caption="", tags=["office"])
    second = await _fit(db, user_id=author, caption="", tags=["denim"])

    a = await domain.try_on(db, user_id=me, post_id=first.id)
    b = await domain.try_on(db, user_id=me, post_id=second.id)
    assert a.id != b.id
    assert b.source_post_id == second.id

    # The same fit twice while one is still drawing is one render, though.
    again = await domain.try_on(db, user_id=me, post_id=first.id)
    assert again.id == a.id


async def test_a_blocked_authors_fit_cannot_be_tried_on(db: AsyncSession) -> None:
    """An id from before the block must not reach a billed call."""
    from app.models.moderation import Block

    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    db.add(Block(blocker_id=me, blocked_id=author))
    await db.commit()

    with pytest.raises(domain.FitNotVisible):
        await domain.try_on(db, user_id=me, post_id=post.id)


async def test_a_fit_that_never_existed_refuses_the_same_way(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    with pytest.raises(domain.FitNotVisible):
        await domain.try_on(db, user_id=me, post_id=uuid.uuid4())


async def test_the_try_on_route_answers_202_with_a_render_to_poll(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-tryon-fit-1")
    signed = await client.post("/v1/auth/session", headers=headers)
    assert signed.status_code == 200

    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    await domain.store(db, post_id=post.id, described=DESCRIBED)

    r = await client.post(f"/v1/feed/{post.id}/try-on", headers=headers)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["state"] == "queued"
    assert body["outfit"] == DESCRIBED.outfit

    # And it is pollable on the avatar routes, which own render state.
    polled = await client.get(
        f"/v1/avatar/renders/{body['render_id']}", headers=headers
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["kind"] == "try_on"


async def test_the_board_shows_a_described_caption_only_where_none_was_written(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-tryon-fit-2")
    await client.post("/v1/auth/session", headers=headers)

    author = await make_user(db)
    silent = await _fit(db, user_id=author, caption="", tags=["office"])
    spoken = await _fit(db, user_id=author, caption="saturday", tags=["office"])
    await domain.store(db, post_id=silent.id, described=DESCRIBED)
    await domain.store(db, post_id=spoken.id, described=DESCRIBED)

    board = await client.get("/v1/feed", headers=headers)
    by_id = {item["id"]: item for item in board.json()["items"]}

    assert by_id[str(silent.id)]["caption"] == DESCRIBED.caption
    assert by_id[str(silent.id)]["caption_is_described"] is True
    assert by_id[str(spoken.id)]["caption"] == "saturday"
    assert by_id[str(spoken.id)]["caption_is_described"] is False
