"""Task 7 — the owned-garment guard (Review Focus item 1, ADR-010).

A garment id that came back from a model is an *assertion*, not a fact. This
module tests the one chokepoint that turns it into a fact, and the four ways it
must refuse:

1. the id belongs to another user,
2. the id does not exist at all,
3. the garment is archived,
4. the garment is marked ``laundry`` or ``unavailable``.

The failure mode this prevents is the worst kind: a run that looks successful
while rendering a stranger's clothes. So the guard refuses with a structured
error and never degrades into a plausible-looking outfit.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.wardrobe_guard import (
    MAX_VALIDATED_IDS,
    UnownedGarment,
    validate_owned_ids,
)
from app.models.garment import Garment
from app.models.user import User


async def make_user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_garment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    availability: str = "available",
    deleted: bool = False,
) -> Garment:
    from datetime import UTC, datetime

    garment = Garment(
        user_id=user_id,
        name="navy blazer",
        category="outerwear",
        availability=availability,
        confirmed_attributes={},
        inferred_attributes={},
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(garment)
    await db.commit()
    await db.refresh(garment)
    return garment


# --------------------------------------------------------------------------- #
# the plan's named tests
# --------------------------------------------------------------------------- #
async def test_model_returned_id_from_another_user_is_rejected(db: AsyncSession) -> None:
    a, b = await make_user(db), await make_user(db)
    gb = await make_garment(db, user_id=b.id)

    with pytest.raises(UnownedGarment):
        await validate_owned_ids(db, a.id, [gb.id])


async def test_unavailable_garment_is_rejected(db: AsyncSession) -> None:
    user = await make_user(db)
    g = await make_garment(db, user_id=user.id, availability="laundry")

    with pytest.raises(UnownedGarment):
        await validate_owned_ids(db, g.user_id, [g.id])


# --------------------------------------------------------------------------- #
# the remaining refusals
# --------------------------------------------------------------------------- #
async def test_a_nonexistent_id_is_rejected(db: AsyncSession) -> None:
    user = await make_user(db)
    with pytest.raises(UnownedGarment) as exc:
        await validate_owned_ids(db, user.id, [uuid.uuid4()])
    assert exc.value.reason == "unknown"


@pytest.mark.parametrize("availability", ["laundry", "unavailable", "archived"])
async def test_every_non_styleable_availability_is_rejected(
    db: AsyncSession, availability: str
) -> None:
    user = await make_user(db)
    g = await make_garment(db, user_id=user.id, availability=availability)
    with pytest.raises(UnownedGarment) as exc:
        await validate_owned_ids(db, user.id, [g.id])
    assert exc.value.reason == "not_styleable"


async def test_a_soft_deleted_garment_is_rejected(db: AsyncSession) -> None:
    user = await make_user(db)
    g = await make_garment(db, user_id=user.id, deleted=True)
    with pytest.raises(UnownedGarment) as exc:
        await validate_owned_ids(db, user.id, [g.id])
    # A deleted row is reported as unknown, exactly like someone else's row:
    # the caller learns nothing about which it was.
    assert exc.value.reason == "unknown"


async def test_a_malformed_id_is_refused_not_crashed(db: AsyncSession) -> None:
    user = await make_user(db)
    with pytest.raises(UnownedGarment) as exc:
        await validate_owned_ids(db, user.id, ["not-a-uuid"])
    assert exc.value.reason == "malformed"


async def test_a_single_bad_id_fails_the_whole_batch(db: AsyncSession) -> None:
    """Partial success is the dangerous outcome: it renders an outfit missing a
    slot and looks like a styling decision rather than a failure."""
    a, b = await make_user(db), await make_user(db)
    mine = await make_garment(db, user_id=a.id)
    theirs = await make_garment(db, user_id=b.id)

    with pytest.raises(UnownedGarment):
        await validate_owned_ids(db, a.id, [mine.id, theirs.id])


async def test_an_absurd_number_of_ids_is_refused_before_the_query(
    db: AsyncSession,
) -> None:
    user = await make_user(db)
    ids = [uuid.uuid4() for _ in range(MAX_VALIDATED_IDS + 1)]
    with pytest.raises(UnownedGarment) as exc:
        await validate_owned_ids(db, user.id, ids)
    assert exc.value.reason == "too_many"


# --------------------------------------------------------------------------- #
# the happy path, and the shape of what it returns
# --------------------------------------------------------------------------- #
async def test_owned_available_ids_are_returned_in_request_order(db: AsyncSession) -> None:
    user = await make_user(db)
    first = await make_garment(db, user_id=user.id)
    second = await make_garment(db, user_id=user.id)
    third = await make_garment(db, user_id=user.id)

    got = await validate_owned_ids(db, user.id, [third.id, first.id, second.id])

    assert [g.id for g in got] == [third.id, first.id, second.id]
    assert all(isinstance(g, Garment) for g in got)


async def test_string_ids_are_accepted(db: AsyncSession) -> None:
    user = await make_user(db)
    g = await make_garment(db, user_id=user.id)
    got = await validate_owned_ids(db, user.id, [str(g.id)])
    assert [x.id for x in got] == [g.id]


async def test_a_repeated_id_is_returned_once(db: AsyncSession) -> None:
    user = await make_user(db)
    g = await make_garment(db, user_id=user.id)
    got = await validate_owned_ids(db, user.id, [g.id, g.id])
    assert [x.id for x in got] == [g.id]


async def test_an_empty_list_is_an_empty_result_not_an_error(db: AsyncSession) -> None:
    user = await make_user(db)
    assert await validate_owned_ids(db, user.id, []) == []


# --------------------------------------------------------------------------- #
# the error contract
# --------------------------------------------------------------------------- #
async def test_the_error_is_structured_and_does_not_confirm_foreign_ownership(
    db: AsyncSession,
) -> None:
    a, b = await make_user(db), await make_user(db)
    gb = await make_garment(db, user_id=b.id)

    with pytest.raises(UnownedGarment) as exc:
        await validate_owned_ids(db, a.id, [gb.id])

    payload = exc.value.to_payload()
    assert payload["code"] == "unowned_garment"
    assert payload["detail"]["garment_ids"] == [str(gb.id)]
    # "not_owned" is kept off the wire: telling the caller that an id exists but
    # is someone else's is itself a disclosure.
    assert "not_owned" not in str(payload)
    assert exc.value.status_code == 409


def test_the_guard_lives_in_exactly_one_module() -> None:
    """ADR-010 makes this a single chokepoint. Two copies is one copy too many."""
    import pathlib

    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    definitions = [
        path
        for path in app_root.rglob("*.py")
        if "def validate_owned_ids" in path.read_text(encoding="utf-8")
    ]
    assert [p.name for p in definitions] == ["wardrobe_guard.py"]
