"""The two Celery tasks.

There are only two, and that is the design rather than an early stage. Celery
carries no domain logic here: it wakes a worker and names a job id. Everything
that decides what happens lives in :mod:`app.domain.jobs` and the handlers,
which is what keeps the queue replaceable and lets the whole pipeline be tested
without a broker.

``run_job`` runs one job by id. ``sweep`` is the re-drive authority: it returns
abandoned jobs to the queue and re-dispatches anything Redis dropped. Cloud
Scheduler drives ``sweep`` on a timer rather than ``celery beat``, because beat
requires exactly one scheduler process and keeps its state in a local file,
neither of which survives a platform that replaces instances freely.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.queue import bridge
from app.queue.celery_app import QUEUE_MAINTENANCE, celery_app, queue_for

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def dispatch(job_id: UUID, kind: str, *, countdown: float | None = None) -> str | None:
    """Ask a worker to pick up a job that is already committed in Postgres.

    Call this **after** the enqueue transaction commits, never inside it. A
    message sent inside the transaction can arrive before the commit lands, and
    the worker then finds no row and declines. Failing to send at all is the
    safe direction: the sweeper finds the job on its next pass, so a broker
    outage costs latency rather than work. That is why this swallows broker
    errors instead of raising into the request path.
    """
    try:
        result = run_job.apply_async(
            args=[str(job_id)], queue=queue_for(kind), countdown=countdown
        )
    except Exception:
        # Deliberately broad: every broker failure mode has the same correct
        # response, which is to let the sweeper handle it.
        logger.warning(
            "could not dispatch job; the sweeper will pick it up",
            extra={"job_id": str(job_id), "kind": kind},
            exc_info=True,
        )
        return None
    return result.id


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #
@celery_app.task(
    name="luxish.run_job",
    bind=True,
    # No Celery-level retry. Retries, backoff and the attempt ceiling are
    # Postgres's job (`fail_job` sets available_at and max_attempts bounds the
    # total). A second retry mechanism here would multiply attempts against
    # that ceiling and make the attempt count meaningless.
    max_retries=0,
    acks_late=True,
)
def run_job(self: Any, job_id: str) -> dict[str, Any]:
    """Claim and run one job.

    Returns a small dict for the task event stream. A job that is not
    claimable is reported as ``skipped`` rather than raised: that is the
    expected outcome of a duplicate delivery or of the sweeper racing a live
    worker, and treating it as an error would make the dashboards useless.
    """
    return bridge.run(_run_job(UUID(job_id), worker=self.request.hostname))


async def _run_job(job_id: UUID, *, worker: str | None) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.domain.jobs import AssetGone, claim_job_by_id, complete_job, fail_job
    from app.workers.runner import all_handlers

    handlers = all_handlers()

    async with session_scope() as session:
        job = await claim_job_by_id(session, job_id, worker=worker)
        if job is None:
            return {"job_id": str(job_id), "outcome": "skipped"}

        kind = job.kind
        handler = handlers.get(kind)
        if handler is None:
            # Enqueued for a kind this deployable cannot run. Fail it so it is
            # visible, rather than leaving it to time out silently.
            await fail_job(session, job, f"no handler registered for kind {kind!r}")
            return {"job_id": str(job_id), "outcome": "unhandled", "kind": kind}

        try:
            result = await handler(session, job)
        except AssetGone as exc:
            # Not a failure: the work was correctly discarded because the asset
            # was deleted while the job was queued.
            await complete_job(session, job, result={"discarded": exc.reason})
            return {"job_id": str(job_id), "outcome": "discarded", "kind": kind}
        except Exception as exc:  # noqa: BLE001 - every failure is recorded
            await fail_job(session, job, f"{type(exc).__name__}: {exc}")
            logger.warning(
                "job failed",
                extra={"job_id": str(job_id), "kind": kind, "state": job.state},
            )
            return {
                "job_id": str(job_id),
                "outcome": "failed",
                "kind": kind,
                "state": job.state,
            }

        await complete_job(session, job, result=result)
        return {"job_id": str(job_id), "outcome": "succeeded", "kind": kind}


@celery_app.task(name="luxish.sweep", queue=QUEUE_MAINTENANCE, acks_late=True)
def sweep(limit: int = 100) -> dict[str, int]:
    """Re-drive the queue from Postgres. The durability guarantee lives here.

    Two passes, in this order:

    1. **Reclaim.** Jobs whose lease expired go back to ``queued``, or to
       ``dead_letter`` once attempts are spent. Without this a job claimed by a
       worker that then died stays ``running`` forever: nothing retries it,
       nothing reports it, and the queue looks healthy while the user watches a
       spinner.
    2. **Dispatch.** Every ready job gets a message. This is the pass that
       makes a lost Redis message a non-event, and it is why the broker's
       durability is not load-bearing.

    Safe to run concurrently with itself and with workers. Dispatching a job
    twice is resolved by the claim; reclaiming costs an attempt, which is what
    bounds a poison job.
    """
    return bridge.run(_sweep(limit=limit))


async def _sweep(*, limit: int) -> dict[str, int]:
    from app.db.session import session_scope
    from app.domain.jobs import ready_job_ids, reclaim_stalled_jobs
    from app.models.job import Job
    from app.config import get_settings

    cfg = get_settings()

    async with session_scope() as session:
        stalled = await reclaim_stalled_jobs(
            session, lease_seconds=cfg.job_lease_seconds, limit=limit
        )
        requeued = sum(1 for job in stalled if job.state == "queued")
        dead = sum(1 for job in stalled if job.state == "dead_letter")

        ready = await ready_job_ids(session, limit=limit)
        kinds: dict[UUID, str] = {}
        if ready:
            import sqlalchemy as sa

            rows = await session.execute(
                sa.select(Job.id, Job.kind).where(Job.id.in_(ready))
            )
            kinds = dict(rows.all())

    dispatched = sum(
        1
        for job_id in ready
        if dispatch(job_id, kinds.get(job_id, "")) is not None
    )

    if requeued or dead:
        logger.info(
            "sweep reclaimed stalled jobs",
            extra={"requeued": requeued, "dead_lettered": dead},
        )

    return {
        "requeued": requeued,
        "dead_lettered": dead,
        "ready": len(ready),
        "dispatched": dispatched,
    }


__all__ = ["dispatch", "run_job", "sweep"]
