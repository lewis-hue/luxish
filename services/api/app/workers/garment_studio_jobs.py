"""The handler that actually takes a studio shot, off the request path.

Same shape as :mod:`app.workers.avatar_jobs`, and for the same reasons: an
image edit is 15 to 30 seconds of billed work, so it runs as a job and the
request returns at once, a process that dies mid-call leaves a row that can
be retried, and the spend is attributable to a job id when somebody asks
why a picture never arrived.

**A failure is recorded, not swallowed.** A missing store, a refusal from
the model, a photograph that has since been deleted — each ends as a
`failed` shot carrying the reason. The alternative is a shot that stays
`running` forever, which a screen cannot tell apart from a slow one.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import garment_studio as domain
from app.models.garment_studio import GarmentShot
from app.models.job import Job
from app.workers.garment_studio import GarmentStudio


def _shot_id(job: Job) -> uuid.UUID:
    raw = (job.payload or {}).get("shot_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no shot_id")
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


async def take_shot_job(
    session: AsyncSession,
    job: Job,
    *,
    studio: GarmentStudio,
    store: object,
) -> dict | None:
    """Claim the shot, run the treatment, record what happened."""
    shot = await session.get(GarmentShot, _shot_id(job))
    if shot is None or shot.deleted_at is not None:
        # Discarded between enqueue and run. Nothing to do, and not a
        # failure: returning None lets the job finish cleanly rather than
        # retrying work whose record is gone.
        return None

    if shot.state == "ready":
        # Already done. A re-dispatched job must not pay for a second
        # picture, which is the whole reason the state is on the row.
        return {"shot_id": str(shot.id), "state": "ready", "repeat": True}

    await domain.mark_running(session, shot=shot)
    try:
        await domain.take(session, shot=shot, studio=studio, store=store)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a state
        await domain.mark_failed(session, shot=shot, error=str(exc))
        # Re-raised so the job records the failure too, and so a transient
        # one is retried by the normal attempt machinery. The shot already
        # says what went wrong either way.
        raise

    return {
        "shot_id": str(shot.id),
        "asset_id": str(shot.media_asset_id),
        "state": "ready",
    }


__all__ = ["take_shot_job"]
