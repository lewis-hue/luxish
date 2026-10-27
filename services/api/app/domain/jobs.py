"""Durable jobs, deletion, and the write guard.

Three things live here:

1. **A queue with exactly-once claiming.** ``claim_job`` uses
   ``SELECT … FOR UPDATE SKIP LOCKED`` on PostgreSQL so two workers never take
   the same row and never block on each other. The same three calls
   (``enqueue`` / ``claim_job`` / ``complete_job``) are what a Cloud Tasks
   adapter will implement.

2. **A bounded retry.** A job that exceeds ``max_attempts`` goes to
   ``dead_letter``. There is no path that retries forever.

3. **``guard_write``** — the single chokepoint every worker calls immediately
   before persisting. It re-checks ownership, tombstone, publication consent
   and asset version *in the same transaction as the write*, and on PostgreSQL
   it takes a row lock so a concurrent delete serialises behind it rather than
   racing it (ADR-012).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.job import JOB_STATES, Job
from app.models.media_asset import MediaAsset, MediaDerivative
from app.models.tombstone import Tombstone

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 5
#: Exponential backoff, capped. ASSUMED; revisit with measured failure data.
BACKOFF_BASE_SECONDS = 15
BACKOFF_CAP_SECONDS = 15 * 60


class AssetGone(ApiError):
    """The asset cannot be written to: deleted, re-versioned, or not yours.

    Deliberately one exception with a ``reason`` rather than four: a caller must
    not be able to handle "deleted" and forget "not yours".
    """

    status_code = 409
    code = "asset_gone"
    default_message = "The asset is no longer available for writing."

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or f"asset unavailable: {reason}", detail={"reason": reason})


def _now() -> datetime:
    return datetime.now(UTC)


def _supports_row_locking(session: AsyncSession) -> bool:
    """SQLite has no ``FOR UPDATE``; PostgreSQL is the queue that ships."""
    return session.bind is None or session.bind.dialect.name == "postgresql"


# --------------------------------------------------------------------------- #
# queue
# --------------------------------------------------------------------------- #
#: Called after a job row commits, to wake a worker. Set by the queue layer at
#: import; a no-op otherwise.
#:
#: A hook rather than a direct import, for two reasons. This module must stay
#: free of Celery so the queue is replaceable and so the test suite needs no
#: broker. And the call must happen *after* the commit: a message sent inside
#: the transaction can reach a worker before the row is visible, and the worker
#: would then find nothing and decline.
_dispatcher: Callable[[uuid.UUID, str], object] | None = None


def set_dispatcher(dispatcher: Callable[[uuid.UUID, str], object] | None) -> None:
    """Register the function that wakes a worker. Pass None to unregister."""
    global _dispatcher
    _dispatcher = dispatcher


def _notify(job: Job) -> None:
    """Wake a worker for ``job``. Never raises.

    A failure here is latency, not loss: the job is already committed and the
    sweeper will find it. So a broker outage must not fail the user's request.
    """
    if _dispatcher is None:
        return
    try:
        _dispatcher(job.id, job.kind)
    except Exception:  # noqa: BLE001 - the sweeper is the fallback
        logger.warning(
            "job dispatch failed; the sweeper will pick it up",
            extra={"job_id": str(job.id), "kind": job.kind},
            exc_info=True,
        )


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    available_at: datetime | None = None,
    notify: bool = True,
) -> Job:
    """Enqueue one job. With a key, enqueuing twice yields the same job.

    The uniqueness is enforced by the database, so two concurrent enqueues
    resolve to one job even when neither saw the other's row.
    """
    if idempotency_key:
        existing = await session.scalar(
            sa.select(Job).where(Job.idempotency_key == idempotency_key)
        )
        if existing is not None:
            # Already enqueued. Do not dispatch again: the first enqueue did,
            # and the sweeper covers the case where that dispatch was lost.
            return existing

    job = Job(
        kind=kind,
        payload=dict(payload),
        state="queued",
        attempts=0,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
        progress=0.0,
        available_at=available_at or _now(),
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if not idempotency_key:
            raise
        existing = await session.scalar(
            sa.select(Job).where(Job.idempotency_key == idempotency_key)
        )
        if existing is None:  # pragma: no cover - the constraint fired for another reason
            raise
        return existing
    await session.refresh(job)
    if notify:
        _notify(job)
    return job


def claim_statement(
    *,
    kinds: list[str] | None = None,
    now: datetime | None = None,
    limit: int = 1,
    locking: bool = True,
) -> sa.Select[tuple[Job]]:
    """The claim query, as a statement, so its SQL can be asserted in a test.

    ``locking`` is false only for SQLite, which has no row locking to ask for.
    """
    moment = now or _now()
    query = (
        sa.select(Job)
        .where(Job.state == "queued", Job.available_at <= moment)
        .order_by(Job.available_at.asc(), Job.created_at.asc())
        .limit(limit)
    )
    if kinds:
        query = query.where(Job.kind.in_(kinds))
    return query.with_for_update(skip_locked=True) if locking else query


async def claim_job(
    session: AsyncSession,
    *,
    kinds: list[str] | None = None,
    worker: str | None = None,
    now: datetime | None = None,
) -> Job | None:
    """Claim the next ready job, or return None.

    SQLite has no ``SKIP LOCKED``; there the lock clause is dropped and the
    single-writer model makes the claim safe anyway. Postgres is the queue that
    ships.
    """
    moment = now or _now()
    job = await session.scalar(
        claim_statement(kinds=kinds, now=moment, locking=_supports_row_locking(session))
    )
    if job is None:
        return None

    job.state = "running"
    job.attempts += 1
    job.locked_at = moment
    job.locked_by = worker
    await session.commit()
    await session.refresh(job)
    return job


#: How long a claimed job may hold its lease before the sweeper assumes the
#: worker died and returns the job to the queue.
#:
#: ASSUMED, and the most dangerous number in this module. It must exceed the
#: runtime of the slowest job, because the reclaim cannot distinguish "the
#: worker died" from "the worker is still working" — it sees only a stale
#: timestamp. Set it too low and a healthy long-running job is re-dispatched
#: *while it is still running*. The AI and media jobs are minutes, so this is
#: generous on purpose; lower it only alongside measured runtimes.
DEFAULT_LEASE_SECONDS = 30 * 60


async def claim_job_by_id(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker: str | None = None,
    now: datetime | None = None,
) -> Job | None:
    """Claim one *named* job, or return None if it is not claimable.

    This is the claim a push dispatcher needs: a broker message names a job,
    and the worker must either take that exact job or decline. Returning None
    rather than raising is the whole point — it is the normal, expected outcome
    of a duplicate delivery, and it is what makes duplicate delivery harmless.

    Implemented as a single conditional UPDATE rather than a locking SELECT
    followed by a write. Both are atomic, but the UPDATE needs no transaction
    to abandon when the job turns out to be unclaimable: a ``rollback`` on the
    decline path would expire every other object in the caller's session, which
    is a surprising thing for a function that did nothing to do.

    Of two workers handed the same message, the ``state = 'queued'`` predicate
    means exactly one row matches and the other sees no row and declines. No
    deduplication at the broker is required, which matters because the broker
    cannot provide any.
    """
    moment = now or _now()
    claimed = await session.scalar(
        sa.update(Job)
        .where(
            Job.id == job_id,
            Job.state == "queued",
            Job.available_at <= moment,
        )
        .values(
            state="running",
            attempts=Job.attempts + 1,
            locked_at=moment,
            locked_by=worker,
        )
        .returning(Job)
        .execution_options(synchronize_session=False)
    )
    if claimed is None:
        return None
    await session.commit()
    await session.refresh(claimed)
    return claimed


async def reclaim_stalled_jobs(
    session: AsyncSession,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    limit: int = 100,
    now: datetime | None = None,
) -> list[Job]:
    """Return jobs whose worker died mid-run to the queue.

    Without this a job that was claimed and then lost — SIGKILL, a pod
    evicted, a Cloud Run instance replaced during a deploy — stays ``running``
    forever. Nothing retries it and nothing reports it: the user watches a
    spinner and the queue looks healthy. This is the single most common way a
    queue silently stops being a queue.

    Reclaiming costs an attempt rather than resetting the counter, so a job
    that kills its worker every time walks to ``dead_letter`` instead of
    looping. That bound is deliberate: it is the backstop Redis does not have.
    """
    moment = now or _now()
    cutoff = moment - timedelta(seconds=lease_seconds)

    query = (
        sa.select(Job)
        .where(
            Job.state == "running",
            Job.locked_at.is_not(None),
            Job.locked_at < cutoff,
        )
        .order_by(Job.locked_at.asc())
        .limit(limit)
    )
    if _supports_row_locking(session):
        query = query.with_for_update(skip_locked=True)

    stalled = list((await session.scalars(query)).all())
    for job in stalled:
        if job.attempts >= job.max_attempts:
            job.state = "dead_letter"
            job.finished_at = moment
            job.last_error = (
                f"lease expired after {lease_seconds}s with no completion, "
                f"and attempts ({job.attempts}) reached max_attempts"
            )
        else:
            job.state = "queued"
            job.locked_at = None
            job.locked_by = None
            job.available_at = moment
            job.last_error = f"lease expired after {lease_seconds}s; requeued"
    if stalled:
        await session.commit()
    return stalled


async def ready_job_ids(
    session: AsyncSession,
    *,
    kinds: list[str] | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> list[uuid.UUID]:
    """Ids of jobs that are ready to run and that nobody is running.

    The polling publisher's read. It claims nothing and locks nothing: it only
    reports what the queue believes is outstanding, so that a dispatcher can
    push those ids at the broker. Safe to run concurrently with workers, and
    safe to dispatch an id twice — ``claim_job_by_id`` resolves that.
    """
    moment = now or _now()
    query = (
        sa.select(Job.id)
        .where(Job.state == "queued", Job.available_at <= moment)
        .order_by(Job.available_at.asc(), Job.created_at.asc())
        .limit(limit)
    )
    if kinds:
        query = query.where(Job.kind.in_(kinds))
    return list((await session.scalars(query)).all())


async def update_progress(session: AsyncSession, job: Job, progress: float) -> None:
    if not 0.0 <= progress <= 1.0:
        raise ValueError(f"progress must be within [0, 1], got {progress!r}")
    job.progress = progress
    await session.commit()


async def complete_job(
    session: AsyncSession, job: Job, *, result: dict[str, Any] | None = None
) -> None:
    job.state = "succeeded"
    job.progress = 1.0
    job.result = result
    job.last_error = None
    job.finished_at = _now()
    job.locked_at = None
    job.locked_by = None
    await session.commit()


def backoff_seconds(attempts: int) -> int:
    return min(BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)), BACKOFF_CAP_SECONDS)


async def fail_job(session: AsyncSession, job: Job, error: str) -> None:
    """Record a failure: requeue with backoff, or dead-letter at the limit."""
    job.last_error = error[:4000]
    job.locked_at = None
    job.locked_by = None
    if job.attempts >= job.max_attempts:
        job.state = "dead_letter"
        job.finished_at = _now()
    else:
        job.state = "queued"
        job.available_at = _now() + timedelta(seconds=backoff_seconds(job.attempts))
    await session.commit()


# --------------------------------------------------------------------------- #
# the write guard
# --------------------------------------------------------------------------- #
def guard_statement(asset_id: uuid.UUID, *, locking: bool = True) -> sa.Select[tuple[MediaAsset]]:
    """Select-for-update of one asset, so a concurrent delete must wait."""
    query = sa.select(MediaAsset).where(MediaAsset.id == asset_id)
    return query.with_for_update() if locking else query


async def guard_write(
    session: AsyncSession,
    asset_id: uuid.UUID,
    version: int | None = None,
    *,
    user_id: uuid.UUID | None = None,
    require_publication_consent: bool = False,
) -> MediaAsset:
    """Re-check every precondition for writing to ``asset_id``.

    Call this inside the transaction that performs the write, immediately before
    it. Checking at job start is not sufficient: a delete can land in between,
    which is the whole point of ADR-012.
    """
    statement = guard_statement(asset_id, locking=_supports_row_locking(session))

    # Tombstone first: it is the record that outlives the asset, so it is the
    # only check that still works once the row itself is gone.
    tombstone = await session.scalar(
        sa.select(Tombstone.id).where(Tombstone.asset_id == asset_id)
    )
    if tombstone is not None:
        raise AssetGone("tombstoned")

    asset = await session.scalar(statement)
    if asset is None:
        raise AssetGone("missing")
    if asset.deleted_at is not None:
        raise AssetGone("tombstoned")
    if user_id is not None and asset.user_id != user_id:
        raise AssetGone("not_owner")
    if version is not None and asset.version != version:
        raise AssetGone("version_changed")
    if require_publication_consent and not asset.publication_consent:
        raise AssetGone("no_publication_consent")
    return asset


# --------------------------------------------------------------------------- #
# deletion
# --------------------------------------------------------------------------- #
async def delete_asset(
    session: AsyncSession,
    asset_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    reason: str = "user_request",
) -> Tombstone:
    """Delete an asset: write the tombstone, then remove what it produced.

    Idempotent, and valid for an id we have no row for — the tombstone is still
    written, so a later write is still refused.
    """
    asset = await session.scalar(sa.select(MediaAsset).where(MediaAsset.id == asset_id))
    if asset is not None and user_id is not None and asset.user_id != user_id:
        # Same answer as "no such asset": do not confirm the id exists.
        raise AssetGone("not_owner")

    tombstone = await session.scalar(
        sa.select(Tombstone).where(Tombstone.asset_id == asset_id)
    )
    if tombstone is None:
        tombstone = Tombstone(
            asset_id=asset_id,
            user_id=asset.user_id if asset else user_id,
            asset_version=asset.version if asset else None,
            deleted_at=_now(),
            reason=reason,
            storage_key=asset.storage_key if asset else None,
        )
        session.add(tombstone)

    await session.execute(sa.delete(MediaDerivative).where(MediaDerivative.asset_id == asset_id))
    if asset is not None and asset.deleted_at is None:
        asset.deleted_at = _now()
        asset.status = "failed" if asset.status == "pending_upload" else asset.status
    await session.commit()
    await session.refresh(tombstone)
    return tombstone


# --------------------------------------------------------------------------- #
# small read helpers (used by workers and by tests)
# --------------------------------------------------------------------------- #
async def tombstone_exists(session: AsyncSession, asset_id: uuid.UUID) -> bool:
    found = await session.scalar(sa.select(Tombstone.id).where(Tombstone.asset_id == asset_id))
    return found is not None


async def count_derivatives(session: AsyncSession, asset_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(MediaDerivative)
            .where(MediaDerivative.asset_id == asset_id)
        )
    ) or 0


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "JOB_STATES",
    "AssetGone",
    "backoff_seconds",
    "claim_job",
    "claim_job_by_id",
    "claim_statement",
    "complete_job",
    "count_derivatives",
    "delete_asset",
    "enqueue",
    "set_dispatcher",
    "fail_job",
    "guard_statement",
    "guard_write",
    "ready_job_ids",
    "reclaim_stalled_jobs",
    "tombstone_exists",
    "update_progress",
]
