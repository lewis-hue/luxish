"""Wardrobe media routes: favourites and bulk operations.

Thin by design, like ``app/routers/wardrobe.py``: this module builds no queries
and holds no rules. It constructs nothing but request/response objects and
delegates to ``app.domain.garment_media``, which is what makes owner scoping
impossible to forget — a router that never builds a query cannot build an
unscoped one.

**Renaming is not here.** ``PATCH /v1/wardrobe/garments/{id}`` already records
corrections, including ``name``, and that is the right home for it: a rename is
a user correction, and corrections belong on one endpoint with one merge rule.
Adding a second way to set a name would be two code paths to keep agreeing about
which column wins.

**Paths avoid the existing router deliberately.** Favourites are listed at
``/wardrobe/favourites``, not ``/wardrobe/garments/favourites``, because the
latter is matched by ``/wardrobe/garments/{garment_id}`` and would resolve to a
UUID-parse failure depending on router registration order. Keeping the two
routers' path spaces disjoint means registration order cannot change behaviour.

**No model work happens in a request.** Bulk create enqueues durable
categorisation and background-removal jobs and returns; it never awaits a
provider (ADR-005, ADR-013).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from app.deps import AuthDep, SessionDep
from app.domain.garment_media import (
    BulkGarmentItem,
    BulkItemOutcome,
    bulk_create_garments,
    bulk_delete_garments,
    delete_garment,
    favourite_garment_ids,
    list_favourites,
    set_favourite,
)
from app.domain.wardrobe import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.schemas.garment_media import (
    BulkDeleteIn,
    BulkGarmentCreate,
    BulkItemOut,
    BulkResultOut,
    FavouriteIdsOut,
    FavouritePage,
    GarmentMediaOut,
)

router = APIRouter(prefix="/wardrobe", tags=["wardrobe"])

#: The ceiling the ids endpoint reads to. A wardrobe is hundreds of items
#: (ADR-004), so this is a generous bound rather than a page size — but it is a
#: bound, and ``truncated`` says so when it bites.
FAVOURITE_IDS_LIMIT = 500


def _result(items: list[BulkItemOut]) -> BulkResultOut:
    failed = sum(1 for item in items if item.status == "failed")
    return BulkResultOut(items=items, succeeded=len(items) - failed, failed=failed)


def _item_out(outcome: BulkItemOutcome) -> BulkItemOut:
    return BulkItemOut(
        index=outcome.index,
        media_asset_id=outcome.media_asset_id,
        status=outcome.status,  # type: ignore[arg-type]
        garment_id=outcome.garment_id,
        code=outcome.code,
        message=outcome.message,
        jobs=list(outcome.jobs),
    )


# --------------------------------------------------------------------------- #
# favourites
# --------------------------------------------------------------------------- #
@router.post("/garments/{garment_id}/favourite", response_model=GarmentMediaOut)
async def favourite(
    garment_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> GarmentMediaOut:
    """Mark a garment as a favourite. Idempotent.

    A favourite is a **stated** preference, not an inferred one, so it is stored
    as user truth and the stylist weights it rather than guessing at it.
    """
    garment = await set_favourite(
        db, user_id=ctx.user_id, garment_id=garment_id, favourite=True
    )
    return GarmentMediaOut.model_validate(garment)


@router.delete("/garments/{garment_id}/favourite", response_model=GarmentMediaOut)
async def unfavourite(
    garment_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> GarmentMediaOut:
    """Un-favourite a garment. Idempotent, and returns the garment either way."""
    garment = await set_favourite(
        db, user_id=ctx.user_id, garment_id=garment_id, favourite=False
    )
    return GarmentMediaOut.model_validate(garment)


@router.get("/favourites", response_model=FavouritePage)
async def read_favourites(
    db: SessionDep,
    ctx: AuthDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> FavouritePage:
    """This user's favourites, newest first. Same cursor idiom as the wardrobe."""
    page = await list_favourites(db, user_id=ctx.user_id, cursor=cursor, limit=limit)
    return FavouritePage(
        items=[GarmentMediaOut.model_validate(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/favourites/ids", response_model=FavouriteIdsOut)
async def read_favourite_ids(db: SessionDep, ctx: AuthDep) -> FavouriteIdsOut:
    """Just the ids — the cheap read the stylist's retrieval step wants."""
    ids, total = await favourite_garment_ids(
        db, user_id=ctx.user_id, limit=FAVOURITE_IDS_LIMIT
    )
    return FavouriteIdsOut(
        garment_ids=list(ids), total=total, truncated=len(ids) < total
    )


# --------------------------------------------------------------------------- #
# bulk
# --------------------------------------------------------------------------- #
@router.post("/garments/bulk", response_model=BulkResultOut)
async def bulk_create(
    payload: BulkGarmentCreate, db: SessionDep, ctx: AuthDep
) -> BulkResultOut:
    """Create many garments from already-authorised uploads.

    **200 even when some items fail.** A partial failure is reported per item,
    never as a status code: nineteen good photographs must not be discarded
    because the twentieth referenced an upload that is not this user's. Each
    item is independently durable and independently idempotent on its
    ``media_asset_id``.
    """
    outcomes = await bulk_create_garments(
        db,
        user_id=ctx.user_id,
        items=[
            BulkGarmentItem(
                media_asset_id=item.media_asset_id,
                name=item.name,
                category=item.category,
                availability=item.availability,
                is_favourite=item.is_favourite,
            )
            for item in payload.items
        ],
    )
    return _result([_item_out(outcome) for outcome in outcomes])


@router.post("/garments/bulk/delete", response_model=BulkResultOut)
async def bulk_delete(
    payload: BulkDeleteIn, db: SessionDep, ctx: AuthDep
) -> BulkResultOut:
    """Delete many garments, through the tombstone path (ADR-012).

    Each deletion writes a tombstone for the garment's media, so a
    categorisation or background-removal job already in flight is refused by
    ``guard_write`` instead of resurrecting a deleted photograph. Per-item
    status, for the same reason as the bulk create.
    """
    outcomes = await bulk_delete_garments(
        db, user_id=ctx.user_id, garment_ids=payload.garment_ids
    )
    return _result([_item_out(outcome) for outcome in outcomes])


@router.delete(
    "/garments/{garment_id}/media", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_with_media(
    garment_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> Response:
    """Delete a garment **and** tombstone its media.

    The plain ``DELETE /wardrobe/garments/{id}`` is a soft delete of the garment
    row only. That is enough to stop a late inference landing on the row, but it
    leaves no tombstone, so a worker holding the asset id has nothing denying its
    write. This is the full deletion ADR-012 describes and is what the mobile
    client should call; see this module's report note about delegating the
    original route here so there is only one answer.
    """
    await delete_garment(db, user_id=ctx.user_id, garment_id=garment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
