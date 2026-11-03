"""Discover, built from user posts.

The properties worth pinning are the ones that decide whether the board
tells the truth.

**A fit is grouped by what its author tagged**, not by a guess. An
untagged fit sits in no group rather than being forced into one.

**Trending is a count of people**, so one enthusiast cannot manufacture
it, and a group below the floor is not reported as moving.

**Personalisation reorders, never hides.** A feed that filtered by
stated taste would stop being a way to discover anything.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import feed as domain
from app.models.posts import Post, PostSave
from app.models.profile import PostReaction, PostTag
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def _fit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    caption: str,
    tags: list[str],
    days_ago: int = 1,
) -> Post:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    post = Post(
        user_id=user_id,
        caption=caption,
        state="published",
        screen_mode="seed",
        published_at=when,
    )
    db.add(post)
    await db.flush()
    for tag in tags:
        db.add(PostTag(post_id=post.id, tag=tag, created_at=when))
    await db.commit()
    await db.refresh(post)
    return post


def test_hashtags_normalise_and_group() -> None:
    assert domain.tags_in("Commute fit #StreetWear #Y2K") == ["streetwear", "y2k"]
    # `#` is optional, case and punctuation do not make a new tag.
    assert domain.normalise_tag("#Street-Wear!") == "streetwear"
    assert domain.normalise_tag("###") is None
    # Synonyms land in one group; three strings, one idea.
    assert domain.categorise(["gym"]) == ["workout"]
    assert domain.categorise(["activewear"]) == ["workout"]
    # A tag nobody mapped leaves the fit ungrouped rather than guessed at.
    assert domain.categorise(["ootd"]) == []


async def test_the_board_is_user_posts_grouped_by_their_own_tags(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    street = await _fit(db, user_id=author, caption="#streetwear", tags=["streetwear"])
    gym = await _fit(db, user_id=author, caption="#gym", tags=["gym"])
    plain = await _fit(db, user_id=author, caption="no tags here", tags=[])

    everything = await domain.board(db, user_id=reader)
    assert {e.post.id for e in everything} == {street.id, gym.id, plain.id}

    by_id = {e.post.id: e for e in everything}
    assert by_id[street.id].groups == ["streetwear"]
    assert by_id[gym.id].groups == ["workout"]
    assert by_id[plain.id].groups == [], "an untagged fit is not forced into a group"

    only_street = await domain.board(db, user_id=reader, group="streetwear")
    assert [e.post.id for e in only_street] == [street.id]


async def test_engagement_and_freshness_rank_the_board(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    old_loved = await _fit(
        db, user_id=author, caption="#denim", tags=["denim"], days_ago=30
    )
    await _fit(
        db, user_id=author, caption="#denim", tags=["denim"], days_ago=0
    )

    for _ in range(6):
        fan = await make_user(db)
        db.add(PostReaction(user_id=fan, post_id=old_loved.id, kind="love"))
    await db.commit()

    ranked = await domain.board(db, user_id=reader)
    assert ranked[0].post.id == old_loved.id, (
        "six reactions should outrank being a day newer"
    )
    assert ranked[0].reactions == 6


async def test_taste_reorders_the_board_but_never_shortens_it(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    street = await _fit(db, user_id=author, caption="#streetwear", tags=["streetwear"])
    office = await _fit(db, user_id=author, caption="#office", tags=["office"])

    plain = await domain.board(db, user_id=reader)
    liked = await domain.board(db, user_id=reader, liked_groups={"office"})

    assert {e.post.id for e in plain} == {e.post.id for e in liked}, (
        "personalisation must not hide anything"
    )
    assert liked[0].post.id == office.id
    assert street.id in {e.post.id for e in liked}


async def test_trending_counts_people_not_presses(db: AsyncSession) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    fit = await _fit(db, user_id=author, caption="#vintage", tags=["vintage"])

    # One very keen person: a reaction and a save is still one person.
    keen = await make_user(db)
    db.add(PostReaction(user_id=keen, post_id=fit.id, kind="fire"))
    db.add(PostSave(user_id=keen, post_id=fit.id))
    await db.commit()

    found = {g.group: g for g in await domain.groups(db, user_id=reader)}
    assert found["vintage"].people == 1
    assert not found["vintage"].trending

    for _ in range(domain.MIN_TRENDING_PEOPLE):
        fan = await make_user(db)
        db.add(PostReaction(user_id=fan, post_id=fit.id, kind="love"))
    await db.commit()

    found = {g.group: g for g in await domain.groups(db, user_id=reader)}
    assert found["vintage"].people == domain.MIN_TRENDING_PEOPLE + 1
    assert found["vintage"].trending


async def test_a_blocked_author_is_absent_from_the_board(
    db: AsyncSession,
) -> None:
    from app.domain.moderation import block

    author = await make_user(db)
    reader = await make_user(db)
    await _fit(db, user_id=author, caption="#denim", tags=["denim"])
    assert await domain.board(db, user_id=reader)

    await block(db, blocker_id=reader, blocked_id=author)
    assert await domain.board(db, user_id=reader) == []


async def test_only_published_fits_inside_the_window_appear(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    await _fit(
        db, user_id=author, caption="#denim", tags=["denim"],
        days_ago=domain.WINDOW_DAYS + 5,
    )
    held = Post(user_id=author, caption="#denim", state="held", screen_mode="model")
    db.add(held)
    await db.commit()

    assert await domain.board(db, user_id=reader) == []


async def test_taste_cannot_push_other_fits_off_a_full_board(
    db: AsyncSession,
) -> None:
    """The cut to `MAX_ITEMS` happens before taste is applied.

    With fewer posts than the cap this is trivially true, which is why
    it went unnoticed: ranking and cutting in one pass let stated taste
    shove other people's fits off the end of a *full* board, which is
    filtering by taste wearing a different hat. So this fills the board
    past the cap and asserts the set is identical either way.
    """
    author = await make_user(db)
    reader = await make_user(db)
    for index in range(domain.MAX_ITEMS + 15):
        group = "office" if index % 2 else "streetwear"
        await _fit(
            db, user_id=author, caption=f"#{group}", tags=[group],
            days_ago=index % 40,
        )

    plain = await domain.board(db, user_id=reader)
    office = await domain.board(db, user_id=reader, liked_groups={"office"})
    street = await domain.board(db, user_id=reader, liked_groups={"streetwear"})

    assert len(plain) == domain.MAX_ITEMS
    assert {e.post.id for e in plain} == {e.post.id for e in office}
    assert {e.post.id for e in office} == {e.post.id for e in street}
    assert office[0].groups == ["office"]
    assert street[0].groups == ["streetwear"]


async def test_deleting_an_account_takes_its_fits_off_the_board(
    db: AsyncSession,
) -> None:
    """Account deletion has to reach discovery, not just the account.

    The post rows are untouched when somebody leaves, and `published`
    is a fact about the post rather than about whether its author is
    still here — so without a join to `users` their fits stayed on the
    board indefinitely.
    """
    import sqlalchemy as sa

    from app.models.user import User

    author = await make_user(db)
    reader = await make_user(db)
    await _fit(db, user_id=author, caption="#denim", tags=["denim"])
    assert len(await domain.board(db, user_id=reader)) == 1

    leaving = await db.get(User, author)
    leaving.deleted_at = sa.func.now()
    await db.commit()

    assert await domain.board(db, user_id=reader) == []
    assert await domain.groups(db, user_id=reader) == []


async def test_your_pins_are_other_peoples_posts(db: AsyncSession) -> None:
    """The library keeps fits, not catalogue entries.

    Not windowed, because a pin is a deliberate act and expiring one on
    a timer would be throwing away somebody's library. Blocks still
    apply: keeping a fit and later blocking its author hides it without
    deleting the keep.
    """
    import sqlalchemy as sa

    from app.domain.moderation import block

    author = await make_user(db)
    reader = await make_user(db)
    kept = await _fit(db, user_id=author, caption="#denim", tags=["denim"])
    await _fit(db, user_id=author, caption="#office", tags=["office"])
    # Old enough that the board would have dropped it.
    stale = await _fit(
        db, user_id=author, caption="#vintage", tags=["vintage"],
        days_ago=domain.WINDOW_DAYS + 10,
    )

    db.add(PostSave(user_id=reader, post_id=kept.id))
    db.add(PostSave(user_id=reader, post_id=stale.id))
    await db.commit()

    pins = await domain.saved(db, user_id=reader)
    assert {e.post.id for e in pins} == {kept.id, stale.id}
    assert all(e.saved_by_me for e in pins)
    assert stale.id not in {e.post.id for e in await domain.board(db, user_id=reader)}

    await block(db, blocker_id=reader, blocked_id=author)
    assert await domain.saved(db, user_id=reader) == []

    # The keeps themselves are untouched: blocking hides, it does not delete.
    remaining = await db.scalar(
        sa.select(sa.func.count()).select_from(PostSave).where(
            PostSave.user_id == reader
        )
    )
    assert remaining == 2


async def test_one_fit_carries_its_author_and_what_is_like_it(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    subject = await _fit(db, user_id=author, caption="#streetwear", tags=["streetwear"])
    near = await _fit(db, user_id=author, caption="#skater", tags=["skater"])
    far = await _fit(db, user_id=author, caption="#office", tags=["office"])

    found = await domain.one(db, user_id=reader, post_id=subject.id)
    assert found is not None and found.groups == ["streetwear"]

    more = await domain.more_like(db, user_id=reader, post_id=subject.id)
    ids = [e.post.id for e in more]
    assert subject.id not in ids, "a fit is not more of itself"
    # `skater` and `streetwear` are one group, so the near one leads.
    assert near.id in ids
    assert ids.index(near.id) < (ids.index(far.id) if far.id in ids else len(ids))


async def test_a_fit_you_cannot_see_is_the_same_404_as_one_that_never_was(
    db: AsyncSession,
) -> None:
    import uuid as _uuid

    from app.domain.moderation import block

    author = await make_user(db)
    reader = await make_user(db)
    fit = await _fit(db, user_id=author, caption="#denim", tags=["denim"])
    assert await domain.one(db, user_id=reader, post_id=fit.id) is not None

    await block(db, blocker_id=reader, blocked_id=author)
    assert await domain.one(db, user_id=reader, post_id=fit.id) is None
    assert await domain.one(db, user_id=reader, post_id=_uuid.uuid4()) is None


async def test_more_like_falls_back_rather_than_showing_an_empty_shelf(
    db: AsyncSession,
) -> None:
    """An untagged fit still gets somewhere to go next."""
    author = await make_user(db)
    reader = await make_user(db)
    plain = await _fit(db, user_id=author, caption="no tags", tags=[])
    await _fit(db, user_id=author, caption="#denim", tags=["denim"])

    more = await domain.more_like(db, user_id=reader, post_id=plain.id)
    assert more, "an ungrouped fit falls back to the board"
    assert plain.id not in {e.post.id for e in more}


async def test_a_feed_item_carries_its_covers_shape(db: AsyncSession) -> None:
    """So a tile is laid out once rather than corrected on decode.

    The board guessed one ratio for everything and re-flowed as each
    photograph arrived, which is the jump people read as the app
    glitching. The shape is already recorded at upload.
    """
    from app.routers.feed import _ratio

    assert _ratio((736, 1308)) == round(736 / 1308, 4)
    # Unknown, zero, or missing: the client measures on load, as it
    # used to for every tile.
    assert _ratio(None) is None
    assert _ratio((None, 1308)) is None
    assert _ratio((736, 0)) is None


# --------------------------------------------------------------------------- #
# whose fit this is
# --------------------------------------------------------------------------- #
async def test_an_author_opening_their_own_fit_is_told_so(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-own-fit-1")
    me = (await client.post("/v1/auth/session", headers=headers)).json()
    mine = await _fit(db, user_id=uuid.UUID(me["user_id"]), caption="", tags=["office"])

    body = (await client.get(f"/v1/feed/{mine.id}", headers=headers)).json()
    assert body["mine"] is True
    # The menu has to draw the switch the way it is actually set.
    assert body["visibility"] == "public"


async def test_somebody_elses_fit_says_nothing_about_visibility(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """A stranger cannot see a private fit at all, so there is nothing
    to tell them - and `visibility` is the author's own call."""
    headers = auth(sub="kc-own-fit-2")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    theirs = await _fit(db, user_id=author, caption="", tags=["office"])

    body = (await client.get(f"/v1/feed/{theirs.id}", headers=headers)).json()
    assert body["mine"] is False
    assert body["visibility"] is None


async def test_ownership_does_not_depend_on_how_recent_the_fit_is(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """The bug this replaced.

    The app decided whose a fit was by looking for it in
    `/v1/posts/mine`, which returns the thirty newest. An author's
    thirty-first fit therefore lost "Make it private" and "Delete this
    fit" - the two controls that are theirs alone - with nothing on
    screen to say why. Ownership is not a function of recency.
    """
    from app.domain.posts import FEED_LIMIT

    headers = auth(sub="kc-own-fit-3")
    me = (await client.post("/v1/auth/session", headers=headers)).json()
    mine = uuid.UUID(me["user_id"])

    oldest = await _fit(db, user_id=mine, caption="", tags=["office"], days_ago=400)
    for at in range(FEED_LIMIT + 2):
        await _fit(db, user_id=mine, caption="", tags=["office"], days_ago=at + 1)

    # Off the end of the capped list, by construction.
    listed = (await client.get("/v1/posts/mine", headers=headers)).json()["items"]
    assert len(listed) == FEED_LIMIT
    assert str(oldest.id) not in {item["id"] for item in listed}

    body = (await client.get(f"/v1/feed/{oldest.id}", headers=headers)).json()
    assert body["mine"] is True, "an older fit is no less the author's"
    assert body["visibility"] == "public"


async def test_a_fit_carries_what_it_is_made_of(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """"Shop the look" needs something to point at.

    The button was on the fit's page and the pieces were not, so it
    fell through to generic recommendations under a label promising
    this look.
    """
    headers = auth(sub="kc-pieces-1")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    body = (await client.get(f"/v1/feed/{post.id}", headers=headers)).json()
    # Empty is the honest answer today, and it has to be *present* so
    # a client can read the emptiness rather than guess.
    assert body["items"] == []


async def test_a_piece_tagged_onto_a_fit_reaches_its_page(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    from app.models.posts import PostItem
    from tests.test_garment_media import make_garment

    headers = auth(sub="kc-pieces-2")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    garment = await make_garment(db, user_id=author)
    db.add(PostItem(post_id=post.id, garment_id=garment.id, position=0))
    await db.commit()

    body = (await client.get(f"/v1/feed/{post.id}", headers=headers)).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["kind"] == "garment"
    # Taxonomy facts only. The free-text name an owner typed is not
    # screened, so it never travels to a stranger.
    assert "name" not in body["items"][0]
