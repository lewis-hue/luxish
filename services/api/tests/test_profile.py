"""The taste profile, and the rule about which signal leads.

Three signals that disagree — what somebody said, what they own, what they
tap. The failure this guards is not a crash: it is a shelf that looks
personalised and is about somebody else, which nobody reports because it is
indistinguishable from a bad recommendation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.profile import (
    CAPSULE_CEILING,
    GENERAL_SCORE,
    OWNS_THRESHOLD,
    aesthetic_focus,
    build_profile,
    formula_focus,
)
from app.domain.taste import Taste, write_taste
from app.models.garment import Garment
from app.models.posts import Post, PostSave
from app.models.profile import PostReaction, PostTag
from app.models.user import User


async def _user(db: AsyncSession, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _own(db: AsyncSession, user: User, category: str, count: int) -> None:
    for index in range(count):
        db.add(Garment(user_id=user.id, name=f"{category}-{index}", category=category))
    await db.commit()


async def _tap(
    db: AsyncSession,
    user: User,
    aesthetic: str,
    *,
    kind: str = "save",
    days_ago: float = 0,
) -> None:
    """Somebody keeps or reacts to a fit tagged with one aesthetic.

    A fit per tap rather than one shared fit: keeping is a pair primary
    key, so five taps on one post are one row and "five people like
    festival" would silently become one.
    """
    when = datetime.now(UTC) - timedelta(days=days_ago)
    author = User(email=f"author-{uuid.uuid4().hex[:8]}@example.com")
    db.add(author)
    await db.flush()
    post = Post(user_id=author.id, state="published", caption=f"#{aesthetic}")
    db.add(post)
    await db.flush()
    db.add(PostTag(post_id=post.id, tag=aesthetic, created_at=when))
    if kind == "reaction":
        db.add(
            PostReaction(
                user_id=user.id, post_id=post.id, kind="love", created_at=when
            )
        )
    else:
        db.add(PostSave(user_id=user.id, post_id=post.id, created_at=when))
    await db.commit()


async def test_owned_leads_how_to_wear_what_you_own(db: AsyncSession) -> None:
    """The shelf is about their clothes, so their clothes decide it.

    Somebody with three pairs of jeans and no blazer must get denim before
    tailoring. Suggesting tailoring to a wardrobe with no tailoring in it is
    a shelf about a different person, and it looks exactly as personalised as
    a right answer.
    """
    user = await _user(db, "denim@example.com")
    await _own(db, user, "jeans", 3)
    await _own(db, user, "tshirt", 4)
    await _own(db, user, "shoes", 3)
    await _own(db, user, "knitwear", 3)
    await _own(db, user, "jacket", 3)

    focus = formula_focus(await build_profile(db, user_id=user.id))
    assert focus[0] in ("denim", "layering")
    assert "tailoring" not in focus[:2]


async def test_aspiration_does_not_override_the_wardrobe(db: AsyncSession) -> None:
    """Tapping festival looks does not put festival clothes in your wardrobe.

    The disagreement case, stated plainly: a workwear wardrobe and festival
    taps are two different true things, and "how to wear what you own" must
    answer the first.
    """
    user = await _user(db, "workwear@example.com")
    await _own(db, user, "blazer", 3)
    await _own(db, user, "trousers", 4)
    await _own(db, user, "shirt", 5)
    await _own(db, user, "shoes", 3)
    await _own(db, user, "coat", 2)
    for _ in range(5):
        await _tap(db, user, "festival")

    profile = await build_profile(db, user_id=user.id)
    # Big enough that concentration is the interesting fact rather than size.
    assert profile.wardrobe_size > CAPSULE_CEILING
    focus = formula_focus(profile)
    assert focus[0] in ("tailoring", "layering")
    # ...and the aspiration is not lost, it is just on the other shelf.
    assert aesthetic_focus(profile)[0] == "festival"


async def test_a_small_wardrobe_is_a_capsule_problem(db: AsyncSession) -> None:
    """Whatever else is in it. Saying so beats ranking its two jackets."""
    user = await _user(db, "small@example.com")
    await _own(db, user, "jeans", 2)
    await _own(db, user, "tshirt", 2)
    profile = await build_profile(db, user_id=user.id)
    assert profile.wardrobe_size <= CAPSULE_CEILING
    # Four pieces: how to get outfits out of few clothes is the useful answer,
    # and ranking its two pairs of jeans is not.
    assert formula_focus(profile)[0] == "capsule"


async def test_depth_beats_a_cheap_perfect_match(db: AsyncSession) -> None:
    """`denim` rests on one category and `layering` on four.

    Scored as a fraction, one pair of jeans is a *perfect* denim match and
    outranks a wardrobe full of knitwear, jackets and shirts — a shelf chosen
    because its rule was short, not because it fit. Counting met categories
    ranks by how much of somebody's wardrobe a shelf is actually about.
    """
    user = await _user(db, "layered@example.com")
    await _own(db, user, "jeans", 2)
    await _own(db, user, "knitwear", 3)
    await _own(db, user, "jacket", 3)
    await _own(db, user, "coat", 2)
    await _own(db, user, "shirt", 4)

    profile = await build_profile(db, user_id=user.id)
    assert profile.wardrobe_size > CAPSULE_CEILING
    focus = formula_focus(profile)
    assert focus[0] == "layering"
    assert focus.index("layering") < focus.index("denim")


async def test_the_collections_that_fit_anybody_never_outrank_a_real_match(
    db: AsyncSession,
) -> None:
    """`colour` and `capsule` apply to everybody, so they must rank below
    anything the wardrobe actually evidences — but still appear, rather than
    leaving a shelf of one."""
    assert GENERAL_SCORE < 1

    user = await _user(db, "real@example.com")
    await _own(db, user, "jeans", 4)
    await _own(db, user, "knitwear", 3)
    await _own(db, user, "jacket", 3)
    await _own(db, user, "coat", 3)
    await _own(db, user, "shirt", 3)

    focus = formula_focus(await build_profile(db, user_id=user.id), limit=7)
    assert focus[0] == "layering"
    assert "colour" in focus


async def test_one_of_something_is_not_a_pattern(db: AsyncSession) -> None:
    """A single pair of jeans is not a denim wardrobe.

    Building a denim shelf off one item is the kind of personalisation that
    reads as a guess, which costs more trust than showing the general shelf.
    """
    user = await _user(db, "single@example.com")
    await _own(db, user, "jeans", OWNS_THRESHOLD - 1)
    profile = await build_profile(db, user_id=user.id)
    assert profile.has("jeans") is False


async def test_an_empty_wardrobe_still_gets_a_shelf(db: AsyncSession) -> None:
    """A shelf that disappears is worse than a general shelf, honestly labelled.

    Somebody who has not photographed anything yet is the most common case on
    day one, and an empty Discover is the worst possible first impression.
    """
    user = await _user(db, "empty@example.com")
    profile = await build_profile(db, user_id=user.id)
    assert profile.wardrobe_size == 0
    assert len(formula_focus(profile)) > 0


async def test_stated_taste_seeds_the_look_before_any_taps(db: AsyncSession) -> None:
    """Day one, which is the only day there is nothing else to go on."""
    user = await _user(db, "stated@example.com")
    await write_taste(
        db,
        user_id=user.id,
        taste=Taste(aesthetics=("quiet-luxury", "minimalist")),
    )
    focus = aesthetic_focus(await build_profile(db, user_id=user.id))
    assert focus[:2] == ("quiet-luxury", "minimalist")


async def test_an_answer_survives_once_taps_exist(db: AsyncSession) -> None:
    """Answering the question must not look like it did nothing.

    Taps move the ranking, but a stated answer nobody has tapped yet is still
    something somebody told us, and dropping it entirely is the version of
    this that makes the sign-up questions feel pointless.
    """
    user = await _user(db, "both@example.com")
    await write_taste(db, user_id=user.id, taste=Taste(aesthetics=("heritage",)))
    for _ in range(6):
        await _tap(db, user, "streetwear")

    focus = aesthetic_focus(await build_profile(db, user_id=user.id))
    assert "heritage" in focus
    assert "streetwear" in focus


async def test_recent_taps_outrank_old_ones(db: AsyncSession) -> None:
    """Same decay as trending, so the two screens cannot disagree about taps."""
    user = await _user(db, "decay@example.com")
    await _tap(db, user, "y2k", days_ago=13)
    await _tap(db, user, "gorpcore", days_ago=0)

    profile = await build_profile(db, user_id=user.id)
    assert profile.reaches_for["gorpcore"] > profile.reaches_for["y2k"]


async def test_gaps_are_slots_you_cannot_build_from(db: AsyncSession) -> None:
    user = await _user(db, "gaps@example.com")
    await _own(db, user, "tshirt", 4)
    await _own(db, user, "jeans", 3)

    profile = await build_profile(db, user_id=user.id)
    assert "tops" not in profile.gaps
    assert "bottoms" not in profile.gaps
    assert "shoes" in profile.gaps
    assert "outerwear" in profile.gaps


async def test_a_deleted_garment_stops_counting(db: AsyncSession) -> None:
    """A profile built on clothes somebody no longer has recommends outfits
    they cannot make."""
    user = await _user(db, "deleted@example.com")
    await _own(db, user, "jeans", 3)
    profile = await build_profile(db, user_id=user.id)
    assert profile.owns["jeans"] == 3

    garments = (
        await db.scalars(sa.select(Garment).where(Garment.user_id == user.id))
    ).all()
    for garment in garments:
        garment.deleted_at = datetime.now(UTC)
    await db.commit()

    assert (await build_profile(db, user_id=user.id)).wardrobe_size == 0


async def test_a_profile_sees_only_its_own_wardrobe(db: AsyncSession) -> None:
    mine = await _user(db, "mine@example.com")
    theirs = await _user(db, "theirs@example.com")
    await _own(db, theirs, "jeans", 5)
    await _tap(db, theirs, "streetwear")

    profile = await build_profile(db, user_id=mine.id)
    assert profile.wardrobe_size == 0
    assert profile.reaches_for == {}
