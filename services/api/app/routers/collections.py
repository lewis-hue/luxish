"""Wardrobe folders: create, rename, delete, and what is in them.

Thin, like the others. The only thing worth saying here is what a delete
means: removing a folder removes the grouping and **never the clothes**.
Somebody tidying their folders must not lose a coat.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import collections as domain
from app.errors import ApiError
from app.schemas.collections import (
    CollectionIn,
    CollectionMembersIn,
    CollectionOut,
    CollectionsOut,
    CollectionRenameIn,
)

router = APIRouter(prefix="/wardrobe/collections", tags=["collections"])


def _view(found: domain.CollectionView) -> CollectionOut:
    return CollectionOut(
        id=found.id,
        name=found.name,
        description=found.description,
        garment_ids=found.garment_ids,
    )


def _bad_name() -> ApiError:
    return ApiError(
        f"Give the folder a name, up to {domain.MAX_NAME} characters.",
        status_code=422,
        code="bad_name",
    )


def _taken() -> ApiError:
    return ApiError(
        "You already have a folder with that name.",
        status_code=409,
        code="name_taken",
    )


def _missing() -> ApiError:
    return ApiError(
        "No such folder.",
        status_code=status.HTTP_404_NOT_FOUND,
        code="not_found",
    )


@router.get("", response_model=CollectionsOut)
async def listing(db: SessionDep, ctx: AuthDep) -> CollectionsOut:
    """Every folder, with what is in each."""
    return CollectionsOut(
        items=[_view(found) for found in await domain.listing(db, user_id=ctx.user_id)]
    )


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
async def create(payload: CollectionIn, db: SessionDep, ctx: AuthDep) -> CollectionOut:
    try:
        return _view(
            await domain.create(
                db,
                user_id=ctx.user_id,
                name=payload.name,
                description=payload.description,
            )
        )
    except domain.BadName:
        raise _bad_name() from None
    except domain.NameTaken:
        raise _taken() from None
    except domain.TooMany:
        raise ApiError(
            f"That is {domain.MAX_COLLECTIONS} folders, which is the limit.",
            status_code=422,
            code="too_many",
        ) from None


@router.patch("/{collection_id}", response_model=CollectionOut)
async def rename(
    collection_id: uuid.UUID,
    payload: CollectionRenameIn,
    db: SessionDep,
    ctx: AuthDep,
) -> CollectionOut:
    """Change a folder's name. The clothes in it do not move."""
    try:
        return _view(
            await domain.rename(
                db,
                user_id=ctx.user_id,
                collection_id=collection_id,
                name=payload.name,
            )
        )
    except domain.NotYours:
        raise _missing() from None
    except domain.BadName:
        raise _bad_name() from None
    except domain.NameTaken:
        raise _taken() from None


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(collection_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Delete the folder. **The garments in it stay in the wardrobe.**"""
    if not await domain.remove(db, user_id=ctx.user_id, collection_id=collection_id):
        raise _missing()


@router.put("/{collection_id}/garments", response_model=CollectionOut)
async def add_members(
    collection_id: uuid.UUID,
    payload: CollectionMembersIn,
    db: SessionDep,
    ctx: AuthDep,
) -> CollectionOut:
    """Put garments in the folder. Idempotent."""
    try:
        return _view(
            await domain.set_members(
                db,
                user_id=ctx.user_id,
                collection_id=collection_id,
                garment_ids=list(payload.garment_ids),
                present=True,
            )
        )
    except domain.NotYours:
        raise _missing() from None


@router.delete("/{collection_id}/garments", response_model=CollectionOut)
async def remove_members(
    collection_id: uuid.UUID,
    payload: CollectionMembersIn,
    db: SessionDep,
    ctx: AuthDep,
) -> CollectionOut:
    """Take garments out of the folder. They stay in the wardrobe."""
    try:
        return _view(
            await domain.set_members(
                db,
                user_id=ctx.user_id,
                collection_id=collection_id,
                garment_ids=list(payload.garment_ids),
                present=False,
            )
        )
    except domain.NotYours:
        raise _missing() from None
