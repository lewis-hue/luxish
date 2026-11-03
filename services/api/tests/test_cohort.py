"""Taste cohorts, and the one property that must hold whatever else changes.

A cohort exists so generated inspiration can be made once and shown to
several people. That is only acceptable if a cohort cannot carry one person's
wardrobe to another, so the first test here is the privacy one and it checks
the *construction* of the key rather than the care of its callers.

The second failure this guards is quieter: a cohort of one. Generating "for
their cohort" when the cohort is them is generating for them while implying
otherwise, and it costs exactly as much as the per-user bill cohorts exist to
avoid.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cohort import (
    EVERYONE,
    LADDER,
    MIN_COHORT_SIZE,
    assign,
    cohort_key,
    recompute_all,
    resolve,
    signature_of,
    size_band,
)
from app.domain.profile import build_profile
from app.domain.taste import Taste, write_taste
from app.models.garment import Garment
from app.models.user import User
from app.models.user_cohort import UserCohort


async def _user(db: AsyncSession, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _own(db: AsyncSession, user: User, category: str, count: int) -> None:
    for index in range(count):
        db.add(
            Garment(
                user_id=user.id,
                name=f"{user.email} {category} {index}",
                category=category,
            )
        )
    await db.commit()


async def _wardrobe(db: AsyncSession, email: str, dress_code: str = "business") -> User:
    """A mid-sized tailoring-and-layering wardrobe. Same shape every time."""
    user = await _user(db, email)
    await _own(db, user, "blazer", 3)
    await _own(db, user, "trousers", 4)
    await _own(db, user, "shirt", 5)
    await _own(db, user, "knitwear", 3)
    await _own(db, user, "coat", 2)
    await write_taste(db, user_id=user.id, taste=Taste(dress_code=dress_code))
    return user


async def test_a_key_contains_nothing_that_identifies_anybody(
    db: AsyncSession,
) -> None:
    """The property the whole feature rests on, checked on the key itself.

    A cohort is safe to share generated content across only if there is
    nothing in it that could carry one person's wardrobe to another. Checking
    the construction rather than the callers is the point: a downstream
    feature cannot leak a wardrobe through something that never held one.
    """
    user = await _wardrobe(db, "private@example.com")
    await _own(db, user, "jeans", 2)
    row = await assign(db, user_id=user.id)

    garments = (
        await db.scalars(sa.select(Garment).where(Garment.user_id == user.id))
    ).all()

    haystack = f"{row.cohort_key} {row.owns_key} {row.signature}".lower()
    # No garment id, no garment name, no user id, no email.
    for garment in garments:
        assert str(garment.id) not in haystack
        assert (garment.name or "").lower() not in haystack
    assert str(user.id) not in haystack
    assert "private@example.com" not in haystack

    # And what it *does* contain is category-level vocabulary.
    assert set(row.signature) == {"owns", "dress_code", "size"}


async def test_the_same_wardrobe_always_lands_in_the_same_group(
    db: AsyncSession,
) -> None:
    """Deterministic, so a generated set stays valid between recomputations.

    A clustering algorithm would relabel people as the population shifts,
    which would silently invalidate every set generated for the old labels.
    """
    first = await _wardrobe(db, "same-1@example.com")
    second = await _wardrobe(db, "same-2@example.com")

    key_one = (await assign(db, user_id=first.id)).cohort_key
    key_two = (await assign(db, user_id=second.id)).cohort_key
    assert key_one == key_two

    # And recomputing does not move it.
    assert (await assign(db, user_id=first.id)).cohort_key == key_one


async def test_a_new_signup_does_not_relabel_everybody_else(
    db: AsyncSession,
) -> None:
    """Stability, which is the other half of being able to reuse a set."""
    established = await _wardrobe(db, "established@example.com")
    before = (await assign(db, user_id=established.id)).cohort_key

    newcomer = await _user(db, "newcomer@example.com")
    await _own(db, newcomer, "sweatshirt", 9)
    await assign(db, user_id=newcomer.id)

    after = (await assign(db, user_id=established.id)).cohort_key
    assert after == before


async def test_a_cohort_of_one_is_widened_rather_than_used(
    db: AsyncSession,
) -> None:
    """Generating "for their cohort" when it is them is the per-user bill back.

    It also misrepresents what the person is being shown, which is the part
    that matters more.
    """
    alone = await _user(db, "alone@example.com")
    await _own(db, alone, "jeans", 30)
    await _own(db, alone, "tshirt", 20)
    await assign(db, user_id=alone.id)

    cohort = await resolve(db, user_id=alone.id)
    assert cohort.members < MIN_COHORT_SIZE or cohort.widened
    # The ladder always terminates, so there is always an answer.
    assert cohort.key


async def test_enough_people_keeps_the_specific_key(db: AsyncSession) -> None:
    """At the floor, the precise cohort is used rather than a widened one."""
    users = [
        await _wardrobe(db, f"together-{index}@example.com")
        for index in range(MIN_COHORT_SIZE)
    ]
    for user in users:
        await assign(db, user_id=user.id)

    cohort = await resolve(db, user_id=users[0].id)
    assert cohort.widened is False
    assert cohort.level == 0
    assert cohort.members >= MIN_COHORT_SIZE


async def test_widening_drops_the_dress_code_first(db: AsyncSession) -> None:
    """The part somebody may simply never have answered.

    Three identical wardrobes with three different stated dress codes are one
    group for every purpose this feature has; splitting them three ways and
    then falling all the way back to "everyone" would be the worst of both.
    """
    users = [
        await _wardrobe(db, f"dress-{index}@example.com", dress_code=code)
        for index, code in enumerate(("business", "smart_casual", "formal"))
    ]
    for user in users:
        await assign(db, user_id=user.id)

    cohort = await resolve(db, user_id=users[0].id)
    assert cohort.widened is True
    assert cohort.level == 1
    assert cohort.members >= MIN_COHORT_SIZE
    # Still a real group, not the everybody fallback.
    assert cohort.general is False


async def test_the_ladder_always_terminates(db: AsyncSession) -> None:
    """Somebody unlike everyone else still gets a cohort: the general one."""
    odd = await _user(db, "odd@example.com")
    await _own(db, odd, "accessory", 60)
    await assign(db, user_id=odd.id)

    cohort = await resolve(db, user_id=odd.id)
    assert cohort.key
    if cohort.general:
        assert cohort.key == EVERYONE


async def test_the_general_cohort_is_marked_as_general(db: AsyncSession) -> None:
    """Content for `everyone` is a general shelf and must be labelled as one.

    Presenting it as somebody's own is the dishonesty this flag exists to
    make impossible to do by accident.
    """
    assert LADDER[-1] == ()
    lonely = await _user(db, "lonely@example.com")
    await assign(db, user_id=lonely.id)
    cohort = await resolve(db, user_id=lonely.id)
    assert cohort.general is (cohort.level == len(LADDER) - 1)


async def test_recompute_covers_everybody(db: AsyncSession) -> None:
    for index in range(4):
        user = await _user(db, f"bulk-{index}@example.com")
        await _own(db, user, "jeans", 3)

    computed = await recompute_all(db)
    assert computed >= 4
    rows = int(
        await db.scalar(sa.select(sa.func.count()).select_from(UserCohort)) or 0
    )
    assert rows == computed


async def test_size_bands_are_where_the_advice_changes(db: AsyncSession) -> None:
    assert size_band(0) == "none"
    assert size_band(1) == "small"
    assert size_band(12) == "small"
    assert size_band(13) == "medium"
    assert size_band(40) == "medium"
    assert size_band(41) == "large"


async def test_a_key_is_order_independent(db: AsyncSession) -> None:
    """The same wardrobe must not produce two keys depending on query order."""
    user = await _wardrobe(db, "ordered@example.com")
    signature = signature_of(await build_profile(db, user_id=user.id))
    assert list(signature.owns) == sorted(signature.owns)
    assert cohort_key(signature) == cohort_key(signature)
