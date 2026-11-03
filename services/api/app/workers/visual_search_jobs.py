"""Reading a photograph somebody wants to search with.

The same reader the feed uses, pointed at an uploaded picture instead
of a published fit. Nothing is stored against the picture: a search is
a question, not a record, and the tags it produces live on the job
result for as long as the job does.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import visual_search
from app.models.job import Job


def _asset_id(job: Job) -> uuid.UUID:
    raw = (job.payload or {}).get("asset_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no asset_id")
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


async def visual_search_job(
    session: AsyncSession,
    job: Job,
    *,
    reader: object,
    store: object,
) -> dict | None:
    """Read one picture into tags."""
    user_id = uuid.UUID(str((job.payload or {}).get("user_id")))
    asset = await visual_search.owned_photograph(
        session, user_id=user_id, asset_id=_asset_id(job)
    )

    data = await store.read(asset)  # type: ignore[attr-defined]
    described = await reader.describe(  # type: ignore[attr-defined]
        image=data, content_type=asset.content_type or "image/jpeg"
    )
    return {
        "tags": list(described.tags),
        "outfit": described.outfit,
        # The pieces, so a client could show what it saw rather than
        # only where it decided to send somebody.
        "pieces": [p.name for p in described.pieces],
    }


__all__ = ["visual_search_job"]
