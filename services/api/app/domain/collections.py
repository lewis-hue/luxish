"""Folders in the wardrobe: a name, and the garments under it.

**A garment can be in several.** "Work" and "Travel" overlap by design —
the same navy blazer is in both — so membership is a join table rather
than a column on the garment. The alternative, one folder per garment,
would force a choice nobody's wardrobe actually makes.

**Every id is re-validated against the caller's own rows** before it is
joined to anything. An id from a client is a claim; adding a stranger's
garment to your folder would be a way to read their wardrobe through
your own screen.

**Names are the user's, and unique per person.** The database enforces
that, so two folders called "Work" cannot exist to be confused. A rename
onto an existing name is refused with a reason rather than silently
merging two folders.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.garment import Collection, CollectionGarment, Garment

#: Long enough for "Weekend away, October" and short enough to render in a
#: chip. Matches the column.
MAX_NAME = 120

#: Enough that somebody can organise, few enough that the folder row stays
#: scannable. A wardrobe with forty folders has no folders.
MAX_COLLECTIONS = 40


class NameTaken(Exception):
    """Another folder of this person's already has that name."""


class BadName(Exception):
    """Empty, or longer than the column."""


class TooMany(Exception):
    """At the folder limit."""


class NotYours(Exception):
    """No such folder for this user."""


@dataclass(frozen=True)
class CollectionView:
    id: uuid.UUID
    name: str
    description: str | None
    garment_ids: list[uuid.UUID]


def clean_name(raw: str) -> str:
    cleaned = " ".join(raw.split())
    if not cleaned or len(cleaned) > MAX_NAME:
        raise BadName()
    return cleaned


async def _owned(
    session: AsyncSession, *, user_id: uuid.UUID, collection_id: uuid.UUID
) -> Collection:
    found = await session.scalar(
        sa.select(Collection).where(
            Collection.id == collection_id,
            Collection.user_id == user_id,
            Collection.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotYours()
    return found


async def _members(
    session: AsyncSession, collection_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Garment ids per folder, excluding anything since deleted.

    Joined to `garments` rather than read straight off the join table: a
    deleted garment leaves its membership row behind, and a folder that
    counted it would disagree with the grid it is filtering.
    """
    if not collection_ids:
        return {}
    rows = (
        await session.execute(
            sa.select(CollectionGarment.collection_id, CollectionGarment.garment_id)
            .join(Garment, Garment.id == CollectionGarment.garment_id)
            .where(
                CollectionGarment.collection_id.in_(collection_ids),
                Garment.deleted_at.is_(None),
            )
        )
    ).all()
    out: dict[uuid.UUID, list[uuid.UUID]] = {cid: [] for cid in collection_ids}
    for collection_id, garment_id in rows:
        out[collection_id].append(garment_id)
    return out


async def listing(session: AsyncSession, *, user_id: uuid.UUID) -> list[CollectionView]:
    """Every folder, oldest first, each with what is in it."""
    found = list(
        await session.scalars(
            sa.select(Collection)
            .where(Collection.user_id == user_id, Collection.deleted_at.is_(None))
            .order_by(Collection.created_at)
        )
    )
    members = await _members(session, [c.id for c in found])
    return [
        CollectionView(
            id=c.id,
            name=c.name,
            description=c.description,
            garment_ids=members.get(c.id, []),
        )
        for c in found
    ]


async def create(
    session: AsyncSession, *, user_id: uuid.UUID, name: str, description: str | None = None
) -> CollectionView:
    cleaned = clean_name(name)
    count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Collection)
        .where(Collection.user_id == user_id, Collection.deleted_at.is_(None))
    )
    if (count or 0) >= MAX_COLLECTIONS:
        raise TooMany()
    clash = await session.scalar(
        sa.select(Collection.id).where(
            Collection.user_id == user_id,
            Collection.name == cleaned,
            Collection.deleted_at.is_(None),
        )
    )
    if clash is not None:
        raise NameTaken()

    collection = Collection(user_id=user_id, name=cleaned, description=description)
    session.add(collection)
    await session.commit()
    await session.refresh(collection)
    return CollectionView(
        id=collection.id, name=collection.name, description=collection.description, garment_ids=[]
    )


async def rename(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    collection_id: uuid.UUID,
    name: str,
) -> CollectionView:
    collection = await _owned(session, user_id=user_id, collection_id=collection_id)
    cleaned = clean_name(name)
    if cleaned != collection.name:
        clash = await session.scalar(
            sa.select(Collection.id).where(
                Collection.user_id == user_id,
                Collection.name == cleaned,
                Collection.id != collection_id,
                Collection.deleted_at.is_(None),
            )
        )
        if clash is not None:
            raise NameTaken()
        collection.name = cleaned
        await session.commit()
        await session.refresh(collection)
    members = await _members(session, [collection.id])
    return CollectionView(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        garment_ids=members.get(collection.id, []),
    )


async def remove(
    session: AsyncSession, *, user_id: uuid.UUID, collection_id: uuid.UUID
) -> bool:
    """Delete the folder. **The garments in it are untouched.**

    Deleting a folder is a statement about the grouping, not about the
    clothes — somebody tidying their folders must not lose a coat.
    """
    try:
        collection = await _owned(session, user_id=user_id, collection_id=collection_id)
    except NotYours:
        return False
    collection.deleted_at = sa.func.now()
    await session.execute(
        sa.delete(CollectionGarment).where(
            CollectionGarment.collection_id == collection_id
        )
    )
    await session.commit()
    return True


async def set_members(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    collection_id: uuid.UUID,
    garment_ids: list[uuid.UUID],
    present: bool,
) -> CollectionView:
    """Add or remove garments. Idempotent in both directions.

    Only the caller's own live garments are touched; anything else in the
    list is ignored rather than refused, because a stale id in a bulk
    selection is a normal race rather than an error worth failing on.
    """
    collection = await _owned(session, user_id=user_id, collection_id=collection_id)

    mine = set(
        await session.scalars(
            sa.select(Garment.id).where(
                Garment.id.in_(garment_ids),
                Garment.user_id == user_id,
                Garment.deleted_at.is_(None),
            )
        )
    ) if garment_ids else set()

    if mine:
        if present:
            existing = set(
                await session.scalars(
                    sa.select(CollectionGarment.garment_id).where(
                        CollectionGarment.collection_id == collection_id,
                        CollectionGarment.garment_id.in_(mine),
                    )
                )
            )
            for garment_id in mine - existing:
                session.add(
                    CollectionGarment(
                        collection_id=collection_id, garment_id=garment_id
                    )
                )
        else:
            await session.execute(
                sa.delete(CollectionGarment).where(
                    CollectionGarment.collection_id == collection_id,
                    CollectionGarment.garment_id.in_(mine),
                )
            )
        await session.commit()

    members = await _members(session, [collection.id])
    return CollectionView(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        garment_ids=members.get(collection.id, []),
    )


__all__ = [
    "MAX_COLLECTIONS",
    "MAX_NAME",
    "BadName",
    "CollectionView",
    "NameTaken",
    "NotYours",
    "TooMany",
    "clean_name",
    "create",
    "listing",
    "remove",
    "rename",
    "set_members",
]
