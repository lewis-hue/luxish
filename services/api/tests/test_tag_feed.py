"""A hashtag page: everything under one tag.

The board narrows a recent slice in Python, which is right for a board
and wrong for a tag. A tag page has to filter in the query and drop the
recency window, or `#linen` returns three fits when a hundred carry it.

**Visibility applies exactly as it does everywhere.** A blocked person's
fits are not under a tag, a withdrawn fit is not under a tag, and the
count a search screen shows is counted over what this reader can reach -
otherwise it promises a page longer than the one they get.

**A tag page is not reordered by stated taste.** Somebody who tapped a
tag has already said what they want.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import feed as domain
from tests.test_feed import _fit
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def test_a_tag_page_reaches_past_the_boards_recency_window(
    db: AsyncSession,
) -> None:
    """The whole reason this is its own query.

    `WINDOW_DAYS` keeps the board alive. Applied to a tag it would make
    a tag with a hundred fits under it look nearly empty.
    """
    author = await make_user(db)
    old = await _fit(
        db,
        user_id=author,
        caption="",
        tags=["linen"],
        days_ago=domain.WINDOW_DAYS + 60,
    )
    recent = await _fit(db, user_id=author, caption="", tags=["linen"], days_ago=1)

    found = await domain.by_tag(db, user_id=author, tag="linen")
    assert {e.post.id for e in found} == {old.id, recent.id}

    # And the board, correctly, does not show the old one.
    board = await domain.board(db, user_id=author)
    assert old.id not in {e.post.id for e in board}


async def test_a_tag_page_is_not_limited_to_the_boards_slice(
    db: AsyncSession,
) -> None:
    """Narrowing a fetched page would return almost nothing for a tag
    that most posts do not carry."""
    author = await make_user(db)
    # Plenty of untagged noise, then one tagged fit at the far end.
    for index in range(domain.MAX_ITEMS * 2 + 10):
        await _fit(db, user_id=author, caption="", tags=["streetwear"], days_ago=1)
    needle = await _fit(db, user_id=author, caption="", tags=["linen"], days_ago=20)

    found = await domain.by_tag(db, user_id=author, tag="linen")
    assert [e.post.id for e in found] == [needle.id]


async def test_the_tag_is_normalised_the_way_it_is_stored(
    db: AsyncSession,
) -> None:
    """`#Linen`, `linen` and ` LINEN ` are one tag or they are three
    pages nobody can find."""
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["linen"])

    for spelling in ("linen", "#linen", "Linen", "  LINEN  ", "#LiNeN"):
        found = await domain.by_tag(db, user_id=author, tag=spelling)
        assert [e.post.id for e in found] == [post.id], spelling


async def test_a_tag_nobody_used_is_an_empty_page_not_an_error(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    assert await domain.by_tag(db, user_id=me, tag="nobodyusedthis") == []


async def test_a_meaningless_tag_is_empty_rather_than_a_crash(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    for junk in ("", "   ", "#", "##", "-"):
        assert await domain.by_tag(db, user_id=me, tag=junk) == []


async def test_a_blocked_authors_fits_are_not_under_a_tag(
    db: AsyncSession,
) -> None:
    from app.models.moderation import Block

    me = await make_user(db)
    author = await make_user(db)
    hidden = await _fit(db, user_id=author, caption="", tags=["linen"])
    db.add(Block(blocker_id=me, blocked_id=author))
    await db.commit()

    found = await domain.by_tag(db, user_id=me, tag="linen")
    assert hidden.id not in {e.post.id for e in found}


async def test_a_withdrawn_fit_is_not_under_a_tag(db: AsyncSession) -> None:
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["linen"])
    post.state = "pending_review"
    await db.commit()

    assert await domain.by_tag(db, user_id=me, tag="linen") == []


async def test_a_deleted_accounts_fits_are_not_under_a_tag(
    db: AsyncSession,
) -> None:
    import sqlalchemy as sa

    from app.models.user import User

    me = await make_user(db)
    author = await make_user(db)
    await _fit(db, user_id=author, caption="", tags=["linen"])
    gone = await db.get(User, author)
    gone.deleted_at = sa.func.now()
    await db.commit()

    assert await domain.by_tag(db, user_id=me, tag="linen") == []


async def test_related_tags_are_the_ones_that_appear_alongside(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    await _fit(db, user_id=author, caption="", tags=["linen", "summer", "minimal"])
    await _fit(db, user_id=author, caption="", tags=["linen", "summer"])
    await _fit(db, user_id=author, caption="", tags=["denim"])

    related = await domain.related_tags(db, user_id=author, tag="linen")
    # Shared most often first, and never the tag being looked at.
    assert related[0] == "summer"
    assert "minimal" in related
    assert "linen" not in related
    assert "denim" not in related


async def test_popular_tags_count_only_what_this_reader_can_see(
    db: AsyncSession,
) -> None:
    """A count over hidden fits promises a page longer than the one the
    reader will get."""
    from app.models.moderation import Block

    me = await make_user(db)
    visible = await make_user(db)
    blocked = await make_user(db)

    await _fit(db, user_id=visible, caption="", tags=["linen"])
    for _ in range(5):
        await _fit(db, user_id=blocked, caption="", tags=["linen"])
    db.add(Block(blocker_id=me, blocked_id=blocked))
    await db.commit()

    counts = dict(await domain.popular_tags(db, user_id=me))
    assert counts["linen"] == 1


# --------------------------------------------------------------------------- #
# the routes
# --------------------------------------------------------------------------- #
async def test_the_tags_route_is_not_shadowed_by_the_post_route(
    client: Any, auth: Any
) -> None:
    """`/v1/feed/tags` sits in front of `/v1/feed/{post_id}`, which is
    typed as a UUID. Declared the other way round, the literal word
    `tags` would be rejected as a malformed id."""
    headers = auth(sub="kc-tagfeed-1")
    await client.post("/v1/auth/session", headers=headers)

    r = await client.get("/v1/feed/tags", headers=headers)
    assert r.status_code == 200, r.text
    assert "items" in r.json()


async def test_the_tag_page_returns_its_fits_and_related_tags(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-tagfeed-2")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["linen", "summer"])

    r = await client.get("/v1/feed/tags/linen", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tag"] == "linen"
    assert [item["id"] for item in body["items"]] == [str(post.id)]
    assert "summer" in body["related"]


async def test_the_tag_page_accepts_a_hash_in_the_path(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """A client passing the tag as written should not get an empty page."""
    headers = auth(sub="kc-tagfeed-3")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    await _fit(db, user_id=author, caption="", tags=["linen"])

    r = await client.get("/v1/feed/tags/%23linen", headers=headers)
    assert r.json()["tag"] == "linen"
    assert len(r.json()["items"]) == 1


async def test_more_like_puts_the_closest_outfit_first(db: AsyncSession) -> None:
    """"More like this" has to mean the outfit, not the department.

    A group says "streetwear", which is a quarter of the board. The
    hashtags say what the fit actually is, so the one sharing three of
    them has to come above the one sharing one.
    """
    author = await make_user(db)
    reader = await make_user(db)
    seed = await _fit(
        db,
        user_id=author,
        caption="",
        tags=["streetwear", "cargos", "grey", "loafers"],
        days_ago=1,
    )
    # Posted oldest-first so the board's own ranking would put the
    # weakest match on top if shared tags were not counted.
    close = await _fit(
        db,
        user_id=author,
        caption="",
        tags=["streetwear", "cargos", "loafers"],
        days_ago=3,
    )
    distant = await _fit(
        db, user_id=author, caption="", tags=["streetwear"], days_ago=2
    )

    found = await domain.more_like(db, user_id=reader, post_id=seed.id)
    assert [entry.post.id for entry in found][:2] == [close.id, distant.id]


async def test_more_like_still_answers_for_a_fit_with_a_rare_tag(
    db: AsyncSession,
) -> None:
    """An empty shelf at the end of a photograph is where scrolling stops."""
    author = await make_user(db)
    reader = await make_user(db)
    seed = await _fit(db, user_id=author, caption="", tags=["veryrarething"])
    other = await _fit(db, user_id=author, caption="", tags=["linen"])

    found = await domain.more_like(db, user_id=reader, post_id=seed.id)
    assert [entry.post.id for entry in found] == [other.id]


# ------------------------------------------------------------------ #
# ideas: what this reader keeps reaching for
# ------------------------------------------------------------------ #
async def test_ideas_rank_by_what_you_kept(db: AsyncSession) -> None:
    """The shelf is built from saves, not from stated taste.

    Somebody who keeps saving one thing should see it offered back.
    `explore` ranks its first row by what people *said*; this ranks by
    what they did, and the two are allowed to disagree.
    """
    from app.models.posts import PostSave

    reader = await make_user(db)
    author = await make_user(db)

    # Four fits under one tag, all kept, against one under another.
    for index in range(4):
        kept = await _fit(
            db, user_id=author, caption=f"a {index}", tags=["tailoring"]
        )
        db.add(PostSave(user_id=reader, post_id=kept.id))
    ignored = await _fit(db, user_id=author, caption="b", tags=["gorpcore"])
    assert ignored is not None
    await db.commit()

    found = await domain.ideas(db, user_id=reader, limit=6)
    keys = [door.key for door in found]
    assert keys, "a reader with saves should get a shelf"
    assert keys[0] == "tailoring"


async def test_ideas_fall_back_rather_than_coming_back_empty(
    db: AsyncSession,
) -> None:
    """A new account has kept nothing, and a heading over an empty
    shelf reads as broken."""
    reader = await make_user(db)
    author = await make_user(db)
    for index in range(3):
        await _fit(db, user_id=author, caption=f"c {index}", tags=["denim"])

    found = await domain.ideas(db, user_id=reader, limit=6)
    assert [door.key for door in found] == ["denim"]


async def test_ideas_never_offer_a_door_onto_nothing(
    db: AsyncSession,
) -> None:
    """Every tile has to open on fits this reader can actually see."""
    reader = await make_user(db)
    author = await make_user(db)
    await _fit(db, user_id=author, caption="d", tags=["evening"])

    for door in await domain.ideas(db, user_id=reader, limit=6):
        assert door.posts > 0


async def test_ideas_are_capped(db: AsyncSession) -> None:
    reader = await make_user(db)
    author = await make_user(db)
    for tag in ("one", "two", "three", "four", "five", "six", "seven"):
        await _fit(db, user_id=author, caption=tag, tags=[tag])

    assert len(await domain.ideas(db, user_id=reader, limit=3)) <= 3
