"""The search screen's categories, built from real fits.

A grid of generated cover art describing user content is a catalogue
pretending to be a community. The properties worth pinning are the ones
that keep it the community's own photographs, and the ones that stop a
tile promising a page it cannot fill.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import feed as domain
from tests.test_feed import _fit
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def _with_photo(db: AsyncSession, *, user_id, tags: list[str]):
    """A published fit that actually has a picture on it."""
    from app.models.posts import PostMedia
    from tests.test_garment_media import make_asset

    post = await _fit(db, user_id=user_id, caption="", tags=tags)
    asset = await make_asset(db, user_id=user_id)
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    await db.commit()
    return post, asset


async def test_a_tile_wears_a_real_photograph(db: AsyncSession) -> None:
    me = await make_user(db)
    author = await make_user(db)
    _, asset = await _with_photo(db, user_id=author, tags=["linen"])

    doors = await domain.doors(db, user_id=me, tags=["linen"])
    assert len(doors) == 1
    assert doors[0].key == "linen"
    assert doors[0].label == "Linen"
    assert doors[0].cover_asset_id == asset.id


async def test_a_tag_with_nothing_behind_it_is_not_shown(
    db: AsyncSession,
) -> None:
    """A door onto an empty room is worse than no door."""
    me = await make_user(db)
    assert await domain.doors(db, user_id=me, tags=["nobodyusedthis"]) == []


async def test_a_blocked_authors_fit_never_becomes_the_cover(
    db: AsyncSession,
) -> None:
    from app.models.moderation import Block

    me = await make_user(db)
    blocked = await make_user(db)
    visible = await make_user(db)
    await _with_photo(db, user_id=blocked, tags=["linen"])
    _, mine = await _with_photo(db, user_id=visible, tags=["linen"])
    db.add(Block(blocker_id=me, blocked_id=blocked))
    await db.commit()

    doors = await domain.doors(db, user_id=me, tags=["linen"])
    assert doors[0].cover_asset_id == mine.id
    assert doors[0].posts == 1


async def test_the_count_matches_what_the_page_will_hold(
    db: AsyncSession,
) -> None:
    """A tile saying 5 and a page showing 1 is the tile lying."""
    me = await make_user(db)
    author = await make_user(db)
    for _ in range(3):
        await _with_photo(db, user_id=author, tags=["denim"])

    doors = await domain.doors(db, user_id=me, tags=["denim"])
    page = await domain.by_tag(db, user_id=me, tag="denim")
    assert doors[0].posts == len(page)


async def test_for_you_comes_from_stated_taste(db: AsyncSession) -> None:
    me = await make_user(db)
    author = await make_user(db)
    await _with_photo(db, user_id=author, tags=["streetwear"])
    await _with_photo(db, user_id=author, tags=["office"])

    for_you, popular = await domain.explore(
        db, user_id=me, liked_groups={"streetwear"}
    )
    assert "streetwear" in {door.key for door in for_you}
    # And never twice across the two rows: two rows showing the same
    # tag is one row of information.
    assert not ({d.key for d in for_you} & {d.key for d in popular})


async def test_a_new_account_gets_a_full_first_row(db: AsyncSession) -> None:
    """An empty "for you" above a full "popular" reads as broken."""
    me = await make_user(db)
    author = await make_user(db)
    for tag in ("linen", "denim", "office"):
        await _with_photo(db, user_id=author, tags=[tag])

    for_you, _ = await domain.explore(db, user_id=me, liked_groups=set())
    assert for_you


async def test_the_route_is_not_shadowed_by_the_post_route(
    client: Any, auth: Any
) -> None:
    """`/v1/feed/explore` sits in front of `/v1/feed/{post_id}`, which
    is typed as a UUID and would reject the word with a 422."""
    headers = auth(sub="kc-explore-1")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.get("/v1/feed/explore", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "for_you" in body and "popular" in body


async def test_the_route_returns_tiles_with_covers(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-explore-2")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    _, asset = await _with_photo(db, user_id=author, tags=["linen"])

    r = await client.get("/v1/feed/explore", headers=headers)
    tiles = r.json()["for_you"] + r.json()["popular"]
    linen = next(t for t in tiles if t["key"] == "linen")
    assert linen["cover_asset_id"] == str(asset.id)
    assert linen["label"] == "Linen"
    assert linen["posts"] >= 1
