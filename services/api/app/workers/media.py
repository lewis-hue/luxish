"""Media worker.

Derivative *computation* (resize, mask, preview) is not implemented in Phase A
— ``sam-3.1`` segmentation and thumbnailing arrive with Task 7 and the media
pipeline. What is implemented, and what this module exists for, is the
**persistence** step: the only way derivative rows reach the database.

``persist`` opens with :func:`app.domain.jobs.guard_write` and writes inside the
same transaction, so a delete that lands mid-job causes ``AssetGone`` and
leaves nothing behind (ADR-012).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import AssetGone, guard_write
from app.models.job import Job
from app.models.media_asset import DERIVATIVE_KINDS, MediaDerivative

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DerivativeSpec:
    """One rendition a worker has produced and wants to record."""

    kind: str
    storage_key: str
    content_type: str
    byte_size: int | None = None
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in DERIVATIVE_KINDS:
            raise ValueError(f"unknown derivative kind {self.kind!r}")


def asset_id_of(job: Job) -> uuid.UUID:
    raw = (job.payload or {}).get("asset_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no asset_id")
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


async def persist(
    session: AsyncSession,
    job: Job,
    *,
    derivatives: list[DerivativeSpec],
    asset_version: int | None = None,
    user_id: uuid.UUID | None = None,
) -> list[MediaDerivative]:
    """Record derivatives for the job's asset, or refuse and write nothing.

    The guard and the insert share one transaction. On refusal the transaction
    is rolled back, so a partially-written batch cannot survive.
    """
    asset_id = asset_id_of(job)
    # Read what the log line needs *before* any rollback: a rollback expires
    # every instance, and touching an expired attribute afterwards would issue
    # IO from a non-async context.
    job_ref, asset_ref = str(job.id), str(asset_id)
    try:
        asset = await guard_write(
            session,
            asset_id,
            version=asset_version,
            user_id=user_id,
        )
        rows = [
            MediaDerivative(
                asset_id=asset.id,
                kind=spec.kind,
                storage_key=spec.storage_key,
                content_type=spec.content_type,
                byte_size=spec.byte_size,
                width=spec.width,
                height=spec.height,
                source_version=asset.version,
            )
            for spec in derivatives
        ]
        session.add_all(rows)
        await session.flush()
        await session.commit()
    except AssetGone as exc:
        await session.rollback()
        logger.info(
            "discarded derivative write for a gone asset",
            extra={"job_id": job_ref, "asset_id": asset_ref, "reason": exc.reason},
        )
        raise
    return rows
