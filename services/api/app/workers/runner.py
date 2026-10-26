"""Worker runner.

One deployable per queue class (ADR-003): the runner is given the kinds it
handles and a handler per kind, and does nothing else. A handler that raises
is a failure, which means backoff or dead-letter — never an infinite retry, and
never a silent swallow.

A handler raising :class:`~app.domain.jobs.AssetGone` is *not* a failure: the
work was correctly discarded because the asset was deleted, so the job
completes rather than retrying against something that no longer exists.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.jobs import AssetGone, claim_job, complete_job, fail_job
from app.models.job import Job

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, Job], Awaitable[dict | None]]


async def run_one(
    session: AsyncSession, *, handlers: dict[str, Handler], worker: str | None = None
) -> Job | None:
    """Claim and run at most one job. Returns the job, or None if idle."""
    job = await claim_job(session, kinds=list(handlers), worker=worker)
    if job is None:
        return None

    handler = handlers[job.kind]
    try:
        result = await handler(session, job)
    except AssetGone as exc:
        await complete_job(session, job, result={"discarded": exc.reason})
        logger.info(
            "job discarded by the write guard",
            extra={"job_id": str(job.id), "kind": job.kind, "reason": exc.reason},
        )
    except Exception as exc:  # noqa: BLE001 - the queue records every failure
        await fail_job(session, job, f"{type(exc).__name__}: {exc}")
        logger.warning(
            "job failed",
            extra={"job_id": str(job.id), "kind": job.kind, "state": job.state},
        )
    else:
        await complete_job(session, job, result=result)
    return job


async def run_forever(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    handlers: dict[str, Handler],
    worker: str | None = None,
    idle_sleep_seconds: float = 1.0,
    stop: asyncio.Event | None = None,
) -> None:
    """Poll for work until ``stop`` is set.

    One session per job so a failed job cannot poison the next one's
    transaction.
    """
    while not (stop and stop.is_set()):
        async with session_maker() as session:
            job = await run_one(session, handlers=handlers, worker=worker)
        if job is None:
            await asyncio.sleep(idle_sleep_seconds)


def media_handlers() -> dict[str, Handler]:
    """The media queue's handlers.

    ``media.derive`` has no computation step in Phase A — see
    ``app/workers/media.py``. It is registered so the queue, the guard and the
    dead-letter path are exercisable end to end.
    """
    from app.workers import media

    async def derive(session: AsyncSession, job: Job) -> dict | None:
        rows = await media.persist(session, job, derivatives=[])
        return {"derivatives": len(rows)}

    return {"media.derive": derive}


def all_handlers(kinds: Sequence[str] | None = None) -> dict[str, Handler]:
    handlers = media_handlers()
    if kinds is None:
        return handlers
    return {kind: handlers[kind] for kind in kinds if kind in handlers}
