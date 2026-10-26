"""Social link reference routes (ADR-009).

Storing a reference performs no outbound request. There is no endpoint here
that fetches platform media, because there is no code anywhere that does.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import social_import
from app.schemas.social import ReferenceCreate, ReferenceResponse

router = APIRouter(prefix="/social", tags=["social"])


@router.post(
    "/references", response_model=ReferenceResponse, status_code=status.HTTP_201_CREATED
)
async def create_reference(
    payload: ReferenceCreate, db: SessionDep, ctx: AuthDep
) -> ReferenceResponse:
    """Store a pasted link with attribution, and report what we can do with it."""
    reference, capability, alternative = await social_import.store_reference(
        db, user_id=ctx.user_id, url=payload.url, note=payload.note
    )
    return ReferenceResponse(
        reference_id=reference.id,
        platform=reference.platform,
        canonical_url=reference.canonical_url,
        author_handle=reference.author_handle,
        observed_at=reference.observed_at,
        capability=capability,
        alternative=alternative,
        media_downloaded=reference.media_downloaded,
    )


@router.get("/references/{reference_id}", response_model=ReferenceResponse)
async def read_reference(
    reference_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> ReferenceResponse:
    reference = await social_import.get_reference(
        db, user_id=ctx.user_id, reference_id=reference_id
    )
    capability = social_import.CAPABILITIES[reference.platform]
    return ReferenceResponse(
        reference_id=reference.id,
        platform=reference.platform,
        canonical_url=reference.canonical_url,
        author_handle=reference.author_handle,
        observed_at=reference.observed_at,
        capability=capability,
        alternative=social_import.alternative_for(capability),
        media_downloaded=reference.media_downloaded,
    )
