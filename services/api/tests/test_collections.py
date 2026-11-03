"""Wardrobe folders.

Four properties are worth pinning.

**Deleting a folder must not delete clothes.** It is a statement about the
grouping; somebody tidying their folders cannot be allowed to lose a coat.

**A garment belongs to several folders.** Work and Travel overlap by
design, and a model that forced a choice would be wrong about wardrobes.

**Names are unique per person**, so two folders called "Work" cannot exist
to be confused — and a rename onto an existing name is refused rather than
silently merging them.

**A stranger's garment cannot be filed.** An id from a client is a claim.
"""

from __future__ import annotations


import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import collections as domain
from app.models.garment import Garment
from tests.test_garment_media import make_asset, make_garment, make_user

pytestmark = pytest.mark.anyio


async def test_a_folder_holds_garments_and_a_garment_sits_in_several(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    blazer = await make_garment(db, user_id=user_id, asset=await make_asset(db, user_id=user_id))
    boots = await make_garment(db, user_id=user_id, asset=await make_asset(db, user_id=user_id))

    work = await domain.create(db, user_id=user_id, name="Work")
    travel = await domain.create(db, user_id=user_id, name="Travel")

    await domain.set_members(
        db, user_id=user_id, collection_id=work.id,
        garment_ids=[blazer.id, boots.id], present=True,
    )
    travel_now = await domain.set_members(
        db, user_id=user_id, collection_id=travel.id,
        garment_ids=[blazer.id], present=True,
    )

    assert set(travel_now.garment_ids) == {blazer.id}
    listing = {c.name: set(c.garment_ids) for c in await domain.listing(db, user_id=user_id)}
    assert listing == {"Work": {blazer.id, boots.id}, "Travel": {blazer.id}}

    # Adding twice is the same state, not a duplicate.
    again = await domain.set_members(
        db, user_id=user_id, collection_id=work.id,
        garment_ids=[blazer.id], present=True,
    )
    assert sorted(again.garment_ids) == sorted([blazer.id, boots.id])

    # Removing from one leaves the other alone.
    await domain.set_members(
        db, user_id=user_id, collection_id=work.id,
        garment_ids=[blazer.id], present=False,
    )
    listing = {c.name: set(c.garment_ids) for c in await domain.listing(db, user_id=user_id)}
    assert listing == {"Work": {boots.id}, "Travel": {blazer.id}}


async def test_deleting_a_folder_keeps_the_clothes(db: AsyncSession) -> None:
    user_id = await make_user(db)
    coat = await make_garment(db, user_id=user_id, asset=await make_asset(db, user_id=user_id))
    folder = await domain.create(db, user_id=user_id, name="Winter")
    await domain.set_members(
        db, user_id=user_id, collection_id=folder.id, garment_ids=[coat.id], present=True
    )

    assert await domain.remove(db, user_id=user_id, collection_id=folder.id)
    assert await domain.listing(db, user_id=user_id) == []

    still_there = await db.scalar(sa.select(Garment).where(Garment.id == coat.id))
    assert still_there is not None and still_there.deleted_at is None

    # And a second delete is not an error anybody has to handle.
    assert not await domain.remove(db, user_id=user_id, collection_id=folder.id)


async def test_names_are_the_users_and_unique_to_them(db: AsyncSession) -> None:
    user_id = await make_user(db)
    await domain.create(db, user_id=user_id, name="Work")

    with pytest.raises(domain.NameTaken):
        await domain.create(db, user_id=user_id, name="Work")
    # Whitespace is not a different name.
    with pytest.raises(domain.NameTaken):
        await domain.create(db, user_id=user_id, name="  Work  ")

    for bad in ("", "   ", "x" * (domain.MAX_NAME + 1)):
        with pytest.raises(domain.BadName):
            await domain.create(db, user_id=user_id, name=bad)

    # Somebody else may use the same name: uniqueness is per person.
    other = await make_user(db)
    assert (await domain.create(db, user_id=other, name="Work")).name == "Work"


async def test_renaming_onto_an_existing_name_is_refused(db: AsyncSession) -> None:
    user_id = await make_user(db)
    work = await domain.create(db, user_id=user_id, name="Work")
    await domain.create(db, user_id=user_id, name="Travel")

    with pytest.raises(domain.NameTaken):
        await domain.rename(db, user_id=user_id, collection_id=work.id, name="Travel")

    renamed = await domain.rename(
        db, user_id=user_id, collection_id=work.id, name="Office days"
    )
    assert renamed.name == "Office days"
    # Renaming to its own name is a no-op, not a clash with itself.
    assert (
        await domain.rename(
            db, user_id=user_id, collection_id=work.id, name="Office days"
        )
    ).name == "Office days"


async def test_a_strangers_folder_and_a_strangers_garment_are_both_refused(
    db: AsyncSession,
) -> None:
    owner = await make_user(db)
    folder = await domain.create(db, user_id=owner, name="Work")
    theirs = await make_garment(db, user_id=owner, asset=await make_asset(db, user_id=owner))

    stranger = await make_user(db)
    with pytest.raises(domain.NotYours):
        await domain.rename(
            db, user_id=stranger, collection_id=folder.id, name="Mine now"
        )
    with pytest.raises(domain.NotYours):
        await domain.set_members(
            db, user_id=stranger, collection_id=folder.id,
            garment_ids=[theirs.id], present=True,
        )
    assert not await domain.remove(db, user_id=stranger, collection_id=folder.id)

    # And the owner cannot file somebody else's garment into their own folder.
    mine = await domain.create(db, user_id=stranger, name="Stranger folder")
    filed = await domain.set_members(
        db, user_id=stranger, collection_id=mine.id,
        garment_ids=[theirs.id], present=True,
    )
    assert filed.garment_ids == [], "another person's garment must not be filed"


async def test_a_deleted_garment_leaves_the_folder_it_was_in(
    db: AsyncSession,
) -> None:
    """Membership rows outlive the garment, so the folder has to join."""
    user_id = await make_user(db)
    coat = await make_garment(db, user_id=user_id, asset=await make_asset(db, user_id=user_id))
    folder = await domain.create(db, user_id=user_id, name="Winter")
    await domain.set_members(
        db, user_id=user_id, collection_id=folder.id, garment_ids=[coat.id], present=True
    )

    coat.deleted_at = sa.func.now()
    await db.commit()

    listed = await domain.listing(db, user_id=user_id)
    assert listed[0].garment_ids == []


async def test_the_folder_limit_is_enforced(db: AsyncSession) -> None:
    user_id = await make_user(db)
    for index in range(domain.MAX_COLLECTIONS):
        await domain.create(db, user_id=user_id, name=f"Folder {index}")
    with pytest.raises(domain.TooMany):
        await domain.create(db, user_id=user_id, name="One too many")
