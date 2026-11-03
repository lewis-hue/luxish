"""Wardrobe routes.

Thin by design: this module builds no queries. It constructs a
:class:`~app.domain.wardrobe.GarmentRepository` bound to the authenticated user
and delegates, which is what makes owner scoping impossible to forget.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from app.deps import AuthDep, SessionDep
from app.domain import garment_media
from app.domain.wardrobe import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, GarmentRepository
from app.schemas.wardrobe import GarmentCreate, GarmentOut, GarmentPage, GarmentPatch

router = APIRouter(prefix="/wardrobe", tags=["wardrobe"])


def _repo(db: SessionDep, ctx: AuthDep) -> GarmentRepository:
    return GarmentRepository(db, user_id=ctx.user_id)


@router.get("/garments", response_model=GarmentPage)
async def list_garments(
    db: SessionDep,
    ctx: AuthDep,
    cursor: str | None = Query(default=None),
    category: str | None = Query(default=None, max_length=64),
    availability: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> GarmentPage:
    page = await _repo(db, ctx).list(
        cursor=cursor, category=category, availability=availability, limit=limit
    )
    return GarmentPage(
        items=[GarmentOut.model_validate(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("/garments", response_model=GarmentOut, status_code=status.HTTP_201_CREATED)
async def create_garment(payload: GarmentCreate, db: SessionDep, ctx: AuthDep) -> GarmentOut:
    """Create one garment and start the work its photograph needs.

    The pipeline is queued here and not only in the bulk endpoint. Uploading a
    single photograph is the ordinary path through the app, and without this a
    garment created that way keeps a null category for ever: nothing
    categorises it, nothing cuts it out, and nothing looks at what is being
    worn in it. The client reads that as still-processing and shows a spinner
    with no end, which is what it did.

    ``enqueue_media_pipeline`` is a no-op for a garment with no photograph, and
    its idempotency keys are derived from the garment, so a retried request
    cannot queue the work, or the spend, twice.
    """
    garment = await _repo(db, ctx).create(
        name=payload.name,
        category=payload.category,
        media_asset_id=payload.media_asset_id,
        confirmed_attributes=payload.confirmed_attributes,
        availability=payload.availability,
    )
    await garment_media.enqueue_media_pipeline(
        db, garment=garment, user_id=ctx.user_id
    )
    return GarmentOut.model_validate(garment)


@router.get("/garments/{garment_id}", response_model=GarmentOut)
async def read_garment(garment_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> GarmentOut:
    return GarmentOut.model_validate(await _repo(db, ctx).require(garment_id))


@router.patch("/garments/{garment_id}", response_model=GarmentOut)
async def correct_garment(
    garment_id: uuid.UUID, payload: GarmentPatch, db: SessionDep, ctx: AuthDep
) -> GarmentOut:
    """Record a user correction. Confirmed attributes always win on read."""
    fields = payload.model_dump(exclude_unset=True)
    garment = await _repo(db, ctx).apply_correction(
        garment_id,
        confirmed_attributes=fields.get("confirmed_attributes"),
        name=fields.get("name"),
        category=fields.get("category"),
        availability=fields.get("availability"),
    )
    return GarmentOut.model_validate(garment)


@router.delete("/garments/{garment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_garment(garment_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> Response:
    """Delete a garment, its photograph and its cut-out.

    Delegates rather than calling ``soft_delete`` directly, so that deleting a
    garment always writes the media tombstones. Without them a categorisation
    or background-removal job already in flight would write its result back
    against an asset the user just deleted — the write guard consults the
    tombstone, not the garment row (ADR-012). There is one deletion path for
    exactly this reason.
    """
    await garment_media.delete_garment(db, user_id=ctx.user_id, garment_id=garment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
