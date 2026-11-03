"""The pipeline against a real database.

**The first four tests are the ones that matter.** Four retrieval
sources is four chances to forget a visibility rule, and the thing
being forgotten is somebody's private fit in a stranger's grid. The
design answer is that sources do not filter at all - they return bare
ids and `_visible` re-reads every one through the same predicates the
old feed used. These tests are what hold that design in place: each
one makes a pin reachable by a source and then asserts it does not
come out.

The rest cover the behaviour the staging exists for: a refresh that
returns something new, a mix that is actually mixed, and a cold
account that still gets a grid.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.discovery import store as graph_store
from app.domain.discovery.pipeline import discover
from app.domain.discovery.seen import InMemorySeen
from app.models.moodboard import Moodboard, MoodboardPin
from app.models.posts import Post, PostSave
from app.models.profile import Profile
from tests.test_garment_media import make_user

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh_graph():
    """The graph is cached in-process; a test must not see another's."""
    graph_store.forget()
    yield
    graph_store.forget()


async def post_by(
    db: AsyncSession, author: uuid.UUID, *, caption: str = "a fit", when=None
) -> Post:
    row = Post(
        user_id=author,
        caption=caption,
        state="published",
        screen_mode="seed",
        published_at=when or (NOW - timedelta(days=1)),
    )
    db.add(row)
    await db.flush()
    return row


async def board_with(
    db: AsyncSession, owner: uuid.UUID, posts: list[Post]
) -> Moodboard:
    board = Moodboard(user_id=owner, name="a board")
    db.add(board)
    await db.flush()
    for position, post in enumerate(posts):
        db.add(
            MoodboardPin(moodboard_id=board.id, post_id=post.id, position=position)
        )
    return board


async def saves(db: AsyncSession, who: uuid.UUID, post: Post) -> None:
    db.add(PostSave(user_id=who, post_id=post.id, created_at=NOW - timedelta(hours=2)))


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
async def test_a_private_account_never_reaches_a_strangers_grid(
    db: AsyncSession,
) -> None:
    """**Reachable by the walk, and still must not appear.**

    The pin is on a board beside something this person saved, so the
    graph walk will absolutely return it. The gate is the only thing
    standing between that and a private fit in a stranger's feed.
    """
    me = await make_user(db)
    shy = await make_user(db)
    neighbour = await make_user(db)

    db.add(Profile(user_id=shy, handle="shy", private=True))
    mine = await post_by(db, neighbour, caption="public")
    theirs = await post_by(db, shy, caption="private")
    await board_with(db, neighbour, [mine, theirs])
    await saves(db, me, mine)
    await db.commit()

    grid = await discover(
        db, user_id=me, size=20, rng=random.Random(1), now=NOW, record=False
    )
    assert theirs.id not in {g.post_id for g in grid}


async def test_a_blocked_person_is_absent_from_every_source(
    db: AsyncSession,
) -> None:
    """Blocking closes the thread; it has to close the feed too."""
    from app.domain.moderation import block

    me = await make_user(db)
    rude = await make_user(db)
    other = await make_user(db)

    ok = await post_by(db, other)
    bad = await post_by(db, rude)
    await board_with(db, other, [ok, bad])
    await saves(db, me, ok)
    await db.commit()

    await block(db, blocker_id=me, blocked_id=rude)
    await db.commit()

    grid = await discover(
        db, user_id=me, size=20, rng=random.Random(1), now=NOW, record=False
    )
    assert bad.id not in {g.post_id for g in grid}


async def test_a_fit_i_hid_does_not_come_back(db: AsyncSession) -> None:
    """"Do not show me this again" has to survive a new retrieval path."""
    from app.domain.feed import hide

    me = await make_user(db)
    other = await make_user(db)
    keep = await post_by(db, other)
    hated = await post_by(db, other)
    await board_with(db, other, [keep, hated])
    await saves(db, me, keep)
    await db.commit()

    await hide(db, user_id=me, post_id=hated.id)
    await db.commit()

    grid = await discover(
        db, user_id=me, size=20, rng=random.Random(1), now=NOW, record=False
    )
    assert hated.id not in {g.post_id for g in grid}


async def test_my_own_fits_are_not_discoveries(db: AsyncSession) -> None:
    """Being shown your own photograph is the feed failing to notice you."""
    me = await make_user(db)
    other = await make_user(db)
    mine = await post_by(db, me)
    theirs = await post_by(db, other)
    await board_with(db, other, [mine, theirs])
    await saves(db, me, theirs)
    await db.commit()

    grid = await discover(
        db, user_id=me, size=20, rng=random.Random(1), now=NOW, record=False
    )
    assert mine.id not in {g.post_id for g in grid}


async def test_a_deleted_fit_is_gone_from_the_graph_too(
    db: AsyncSession,
) -> None:
    """The board row survives the post. The gate is what catches it."""
    me = await make_user(db)
    other = await make_user(db)
    anchor = await post_by(db, other)
    doomed = await post_by(db, other)
    await board_with(db, other, [anchor, doomed])
    await saves(db, me, anchor)
    await db.commit()

    doomed.deleted_at = NOW - timedelta(minutes=5)
    await db.commit()

    grid = await discover(
        db, user_id=me, size=20, rng=random.Random(1), now=NOW, record=False
    )
    assert doomed.id not in {g.post_id for g in grid}


# --------------------------------------------------------------------------- #
# What the staging is for
# --------------------------------------------------------------------------- #
async def test_the_walk_finds_what_boards_put_together(
    db: AsyncSession,
) -> None:
    """The claim the graph source rests on, end to end."""
    me = await make_user(db)
    curator = await make_user(db)
    liked = await post_by(db, curator, caption="liked")
    beside = await post_by(db, curator, caption="beside it")
    await board_with(db, curator, [liked, beside])
    await saves(db, me, liked)
    await db.commit()

    grid = await discover(
        db, user_id=me, size=20, rng=random.Random(2), now=NOW, record=False
    )
    found = {g.post_id: g.source for g in grid}
    assert beside.id in found


async def test_a_refresh_returns_something_else(db: AsyncSession) -> None:
    """**What pull-to-refresh is for.**

    Without the seen-filter a refresh re-runs the same ranking over
    the same corpus and hands back the same grid, and the gesture
    that means "show me something else" shows the same thing.
    """
    me = await make_user(db)
    curator = await make_user(db)
    everything = [await post_by(db, curator, caption=f"fit {i}") for i in range(24)]
    await board_with(db, curator, everything)
    await saves(db, me, everything[0])
    await db.commit()

    memory = InMemorySeen()
    first = await discover(
        db, user_id=me, size=8, seen_store=memory, rng=random.Random(3), now=NOW
    )
    second = await discover(
        db, user_id=me, size=8, seen_store=memory, rng=random.Random(3), now=NOW
    )

    assert first, "the first grid is empty, so this proves nothing"
    overlap = {g.post_id for g in first} & {g.post_id for g in second}
    assert not overlap, f"{len(overlap)} pins repeated after a refresh"


async def test_an_account_with_no_history_still_gets_a_grid(
    db: AsyncSession,
) -> None:
    """**The cold start, which the graph alone cannot serve.**

    Somebody who signed up a minute ago has no saves, so no query
    pins, so no walk. A pipeline that only knew how to walk would
    hand them an empty screen on their first ever load.
    """
    me = await make_user(db)
    other = await make_user(db)
    for i in range(12):
        await post_by(db, other, caption=f"fit {i}")
    await db.commit()

    grid = await discover(
        db, user_id=me, size=10, rng=random.Random(4), now=NOW, record=False
    )
    assert grid, "a new account got nothing"
    assert {g.source for g in grid} <= {"fresh", "trending", "affinity", "graph"}


async def test_the_grid_is_mixed_rather_than_one_source(
    db: AsyncSession,
) -> None:
    """A quota nothing honours is a comment.

    Built with enough of each kind that every source has something to
    give, then asserted on the mix rather than on the order.
    """
    me = await make_user(db)
    curator = await make_user(db)
    boarded = [await post_by(db, curator, caption=f"boarded {i}") for i in range(14)]
    await board_with(db, curator, boarded)
    await saves(db, me, boarded[0])
    # Plus a pile nobody has touched, posted recently.
    for i in range(14):
        await post_by(db, curator, caption=f"cold {i}", when=NOW - timedelta(hours=3))
    await db.commit()

    grid = await discover(
        db, user_id=me, size=16, rng=random.Random(5), now=NOW, record=False
    )
    sources = {g.source for g in grid}
    assert len(sources) >= 2, f"one source filled the whole grid: {sources}"


async def test_it_is_reproducible(db: AsyncSession) -> None:
    """Same seed, same grid. Otherwise nobody can debug a bad feed."""
    me = await make_user(db)
    curator = await make_user(db)
    posts = [await post_by(db, curator, caption=f"fit {i}") for i in range(16)]
    await board_with(db, curator, posts)
    await saves(db, me, posts[0])
    await db.commit()

    once = await discover(
        db, user_id=me, size=10, rng=random.Random(9), now=NOW, record=False
    )
    twice = await discover(
        db, user_id=me, size=10, rng=random.Random(9), now=NOW, record=False
    )
    assert [g.post_id for g in once] == [g.post_id for g in twice]


async def test_every_pin_says_why_it_is_there(db: AsyncSession) -> None:
    """Without a source nobody can answer "why am I seeing this"."""
    me = await make_user(db)
    other = await make_user(db)
    for i in range(8):
        await post_by(db, other, caption=f"fit {i}")
    await db.commit()

    grid = await discover(
        db, user_id=me, size=6, rng=random.Random(6), now=NOW, record=False
    )
    assert all(g.source for g in grid)


async def test_the_seen_filter_never_empties_the_grid(
    db: AsyncSession,
) -> None:
    """**The bug this caught, on the dev stack, within an afternoon.**

    The seen-filter only subtracts. On a small corpus a few refreshes
    exhaust it and the next request returns nothing at all - an empty
    Discover tab, which is the worst thing this pipeline can produce.

    Repetition is the correct trade against emptiness: a grid of pins
    somebody saw yesterday is a worse grid, a blank screen is a
    broken app.
    """
    me = await make_user(db)
    other = await make_user(db)
    everything = [await post_by(db, other, caption=f"fit {i}") for i in range(10)]
    await board_with(db, other, everything)
    await saves(db, me, everything[0])
    await db.commit()

    memory = InMemorySeen()
    # Drain it: ask for more than exists, repeatedly.
    for _ in range(5):
        await discover(
            db, user_id=me, size=10, seen_store=memory,
            rng=random.Random(1), now=NOW,
        )

    after = await discover(
        db, user_id=me, size=10, seen_store=memory,
        rng=random.Random(1), now=NOW,
    )
    assert after, "the feed went empty once everything had been seen"


async def test_relaxing_the_filter_does_not_relax_the_gate(
    db: AsyncSession,
) -> None:
    """**The fallback must not become a hole in the visibility rules.**

    Novelty gives way under starvation; privacy does not. A private
    account's fit must stay absent even when relaxing the seen-filter
    is the only way to fill the page.
    """
    me = await make_user(db)
    shy = await make_user(db)
    other = await make_user(db)

    db.add(Profile(user_id=shy, handle="shy-too", private=True))
    mine = await post_by(db, other, caption="public")
    hidden = await post_by(db, shy, caption="private")
    await board_with(db, other, [mine, hidden])
    await saves(db, me, mine)
    await db.commit()

    memory = InMemorySeen()
    for _ in range(5):
        await discover(
            db, user_id=me, size=10, seen_store=memory,
            rng=random.Random(1), now=NOW,
        )

    after = await discover(
        db, user_id=me, size=10, seen_store=memory,
        rng=random.Random(1), now=NOW,
    )
    assert hidden.id not in {g.post_id for g in after}


# --------------------------------------------------------------------------- #
# What the photographs are of
# --------------------------------------------------------------------------- #
async def _read_as(db: AsyncSession, post: Post, subject: str, facets):
    """Record what a pin's photograph is of, as the vision job would."""
    from app.domain.discovery.subject import Reading, vector_for
    from app.models.post_vision import PostVisionRow

    reading = Reading(subject=subject, facets=tuple(facets))
    db.add(
        PostVisionRow(
            post_id=post.id,
            subject=reading.subject,
            confidence=1.0,
            facets=list(reading.facets),
            vector=vector_for(reading),
            model="test",
            prompt_version="pv-1",
        )
    )


async def test_a_couch_is_not_offered_under_a_dress(db: AsyncSession) -> None:
    """**The reported failure, end to end.**

    The couch is on the same board as the dress and carries the same
    hashtags, so both the walk and the tag overlap return it. The
    only thing that keeps it off the shelf is what the photograph is
    of.
    """
    from app.domain.feed import more_like
    from app.models.profile import PostTag

    me = await make_user(db)
    author = await make_user(db)
    dress = await post_by(db, author, caption="wedding guest")
    couch = await post_by(db, author, caption="wedding guest, not upstaging")
    # Real outfits to choose instead. Without them the pool is
    # degenerate and the "do not leave a blank shelf" fallback fires,
    # which is correct behaviour in a world with two posts in it and
    # not the world this is about.
    others = []
    for i in range(6):
        other = await post_by(db, author, caption=f"another guest fit {i}")
        others.append(other)
    for post in (dress, couch, *others):
        for tag in ("weddingguest", "occasion", "party"):
            db.add(PostTag(post_id=post.id, tag=tag))
    await board_with(db, author, [dress, couch, *others])
    await saves(db, me, dress)

    await _read_as(db, dress, "outfit", ("neutral", "formal"))
    await _read_as(db, couch, "interior", ("neutral", "boucle", "cosy"))
    for other in others:
        await _read_as(db, other, "outfit", ("neutral", "formal"))
    await db.commit()

    shelf = await more_like(db, user_id=me, post_id=dress.id, limit=10)
    assert couch.id not in {entry.post.id for entry in shelf}, (
        "a couch is on the shelf under a dress, which is the whole bug"
    )


async def test_a_pin_nobody_has_read_is_not_excluded(
    db: AsyncSession,
) -> None:
    """**A backfill in progress must not empty the shelf.**

    The gate only ever removes pins it has a reading for. One with
    no reading falls through to the older signals, which is exactly
    the behaviour before any of this existed.
    """
    from app.domain.feed import more_like
    from app.models.profile import PostTag

    me = await make_user(db)
    author = await make_user(db)
    seed = await post_by(db, author, caption="a fit")
    unread = await post_by(db, author, caption="not read yet")
    for post in (seed, unread):
        db.add(PostTag(post_id=post.id, tag="streetwear"))
    await board_with(db, author, [seed, unread])
    await saves(db, me, seed)
    await _read_as(db, seed, "outfit", ("street",))
    await db.commit()

    shelf = await more_like(db, user_id=me, post_id=seed.id, limit=10)
    assert unread.id in {entry.post.id for entry in shelf}


async def test_the_gate_gives_way_rather_than_leaving_a_blank_shelf(
    db: AsyncSession,
) -> None:
    """An empty shelf is where somebody stops scrolling.

    A pin whose subject nothing else shares still gets something
    under it - ranked by the older signals, which is a weaker answer
    than a correct one and a better answer than none.
    """
    from app.domain.feed import more_like
    from app.models.profile import PostTag

    me = await make_user(db)
    author = await make_user(db)
    lonely = await post_by(db, author, caption="the only room here")
    for i in range(6):
        other = await post_by(db, author, caption=f"an outfit {i}")
        db.add(PostTag(post_id=other.id, tag="ootd"))
        await _read_as(db, other, "outfit", ("casual",))
    db.add(PostTag(post_id=lonely.id, tag="ootd"))
    await _read_as(db, lonely, "interior", ("wood",))
    await db.commit()

    shelf = await more_like(db, user_id=me, post_id=lonely.id, limit=6)
    assert shelf, "the shelf went blank rather than falling back"
