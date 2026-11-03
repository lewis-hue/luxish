"""The personalised shelf, and the three claims it must not make falsely.

That a set was made for a group, when it was made for one person. That it is
theirs, when it is the general order. That it is current, when its window has
passed. None of the three raises anything; all three read as a working
feature.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cohort import MIN_COHORT_SIZE, recompute_all, resolve
from app.domain.inspiration import (
    SET_SIZE,
    WINDOW,
    for_user,
    generate_for_cohort,
    refresh_all,
)
from app.domain.taste import Taste, write_taste
from app.models.cohort_inspiration import CohortInspiration
from app.models.garment import Garment
from app.models.user import User


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
                name=f"{user.email} secret {category} {index}",
                category=category,
            )
        )
    await db.commit()


async def _tailored(db: AsyncSession, email: str) -> User:
    """The same shape of wardrobe every time, so these land in one cohort."""
    user = await _user(db, email)
    await _own(db, user, "blazer", 3)
    await _own(db, user, "trousers", 4)
    await _own(db, user, "shirt", 5)
    await _own(db, user, "knitwear", 3)
    await _own(db, user, "coat", 2)
    await write_taste(db, user_id=user.id, taste=Taste(dress_code="business"))
    return user


async def _cohort_of(db: AsyncSession, size: int, prefix: str) -> list[User]:
    users = [await _tailored(db, f"{prefix}-{n}@example.com") for n in range(size)]
    await recompute_all(db)
    return users


async def test_a_generated_set_carries_nobody_s_wardrobe(db: AsyncSession) -> None:
    """The property that makes sharing acceptable at all.

    A set is conditioned on the cohort key — category counts and a stated
    dress code — and never on a member's garments. Checked against the stored
    row rather than against the code that built it, because what is stored is
    what reaches other people.
    """
    users = await _cohort_of(db, MIN_COHORT_SIZE, "private")
    cohort = await resolve(db, user_id=users[0].id)
    made = await generate_for_cohort(
        db,
        cohort_key=cohort.key,
        owns=("tailoring", "layering"),
        members=cohort.members,
    )

    garments = (
        await db.scalars(sa.select(Garment).where(Garment.user_id == users[0].id))
    ).all()

    stored = f"{made.cohort_key} {made.collections} {made.rationale}".lower()
    for garment in garments:
        assert str(garment.id) not in stored
        assert "secret" not in stored
    for user in users:
        assert str(user.id) not in stored
        assert user.email.split("@")[0] not in stored


async def test_one_set_serves_the_whole_cohort(db: AsyncSession) -> None:
    """The cost argument, as a test.

    If each member got their own row, the bill would grow with sign-ups and
    the entire mechanism would be pointless while still looking like it
    worked.
    """
    users = await _cohort_of(db, MIN_COHORT_SIZE, "shared")
    assert await refresh_all(db) >= 1

    # One row *per cohort key*, not per user. More rows than one is expected
    # — the ladder also generates for the widened rungs — but never one per
    # member, which is the shape that would mean the bill still grows with
    # sign-ups.
    rows = int(
        await db.scalar(sa.select(sa.func.count()).select_from(CohortInspiration)) or 0
    )
    assert rows < len(users) + 1
    per_key = int(
        await db.scalar(
            sa.select(sa.func.count(sa.distinct(CohortInspiration.cohort_key)))
        )
        or 0
    )
    assert rows == per_key

    seen = set()
    for user in users:
        result = await for_user(db, user_id=user.id)
        assert result.personalised is True
        seen.add(result.collections)
    assert len(seen) == 1


async def test_a_widened_cohort_actually_receives_a_set(
    db: AsyncSession,
) -> None:
    """Generation walks the whole ladder, not only the most specific rung.

    Three identical wardrobes with three different stated dress codes split
    into three groups of one, and widen into one group of three. Generating
    only for exact keys would leave all three on the general shelf while a
    real group existed one rung up — widening would change nothing but the
    number `resolve` reports.
    """
    users = []
    for index, code in enumerate(("business", "smart_casual", "formal")):
        user = await _tailored(db, f"widened-{index}@example.com")
        await write_taste(db, user_id=user.id, taste=Taste(dress_code=code))
        users.append(user)
    await recompute_all(db)

    cohort = await resolve(db, user_id=users[0].id)
    assert cohort.widened is True
    assert cohort.general is False

    await refresh_all(db)
    for user in users:
        result = await for_user(db, user_id=user.id)
        assert result.personalised is True
        assert result.cohort_size >= MIN_COHORT_SIZE


async def test_a_cohort_under_the_floor_gets_no_generated_set(
    db: AsyncSession,
) -> None:
    """A set for one person is the per-user bill this exists to avoid.

    It would also be labelled as a group's while being nobody's but theirs,
    which is the worse half of the problem.
    """
    alone = await _user(db, "alone@example.com")
    await _own(db, alone, "accessory", 25)
    await recompute_all(db)

    await refresh_all(db)
    result = await for_user(db, user_id=alone.id)
    assert result.personalised is False
    # ...and they still get a shelf.
    assert result.collections


async def test_the_general_shelf_says_it_is_general(db: AsyncSession) -> None:
    """Showing the general order while calling it yours is the dishonesty
    this flag exists to make impossible by accident."""
    newcomer = await _user(db, "newcomer@example.com")
    result = await for_user(db, user_id=newcomer.id)
    assert result.personalised is False
    assert result.collections
    assert "general" in result.rationale.lower()


async def test_an_expired_set_is_not_served(db: AsyncSession) -> None:
    """A window, not a sort by recency.

    Without the range check the newest row is always current, so a shelf that
    was supposed to refresh twice a week silently never expires.
    """
    users = await _cohort_of(db, MIN_COHORT_SIZE, "expiring")
    long_ago = datetime.now(UTC) - WINDOW - timedelta(days=1)
    cohort = await resolve(db, user_id=users[0].id)
    await generate_for_cohort(
        db, cohort_key=cohort.key, owns=("tailoring",), members=3, now=long_ago
    )

    result = await for_user(db, user_id=users[0].id)
    assert result.personalised is False


async def test_a_set_generated_early_is_not_current_yet(
    db: AsyncSession,
) -> None:
    """The other half of the window. A set made for next week must wait."""
    users = await _cohort_of(db, MIN_COHORT_SIZE, "early")
    later = datetime.now(UTC) + timedelta(days=2)
    cohort = await resolve(db, user_id=users[0].id)
    await generate_for_cohort(
        db, cohort_key=cohort.key, owns=("tailoring",), members=3, now=later
    )

    result = await for_user(db, user_id=users[0].id)
    assert result.personalised is False


async def test_regenerating_a_window_replaces_rather_than_stacks(
    db: AsyncSession,
) -> None:
    """A retried task must not double the spend or the rows."""
    users = await _cohort_of(db, MIN_COHORT_SIZE, "retry")
    moment = datetime.now(UTC)
    cohort = await resolve(db, user_id=users[0].id)
    for _ in range(3):
        await generate_for_cohort(
            db, cohort_key=cohort.key, owns=("tailoring",), members=3, now=moment
        )

    rows = int(
        await db.scalar(sa.select(sa.func.count()).select_from(CohortInspiration)) or 0
    )
    assert rows == 1


async def test_a_set_is_a_reordering_not_a_truncation(db: AsyncSession) -> None:
    """What the cohort owns leads; the rest follows in authored order.

    A set that only contained what a wardrobe evidences would make most of
    the taxonomy unreachable for most people, which is a narrower product
    wearing personalisation as an excuse.
    """
    users = await _cohort_of(db, MIN_COHORT_SIZE, "ordering")
    cohort = await resolve(db, user_id=users[0].id)
    made = await generate_for_cohort(
        db, cohort_key=cohort.key, owns=("tailoring", "layering"), members=3
    )
    assert len(made.collections) == SET_SIZE
    assert len(set(made.collections)) == SET_SIZE


async def test_refresh_skips_every_group_under_the_floor(
    db: AsyncSession,
) -> None:
    """Nothing is generated for a key nobody is in, or that too few share."""
    for index in range(2):
        user = await _user(db, f"pair-{index}@example.com")
        await _own(db, user, "accessory", 20)
    await recompute_all(db)

    await refresh_all(db)
    keys = {
        row[0]
        for row in (await db.execute(sa.select(CohortInspiration.cohort_key))).all()
    }
    # Two people sharing a wardrobe shape is below the floor at every rung
    # that still mentions what they own, so nothing was made for them.
    assert not any("accessory" in key for key in keys)


async def test_a_shelf_is_never_empty(db: AsyncSession) -> None:
    """Whatever the state of the schedule, cohorts or wardrobe."""
    nobody = await _user(db, "bare@example.com")
    result = await for_user(db, user_id=nobody.id)
    assert len(result.collections) > 0
    assert result.rationale
