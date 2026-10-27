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
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.jobs import AssetGone, claim_job, complete_job, fail_job
from app.models.job import Job

if TYPE_CHECKING:  # pragma: no cover - imported for signatures only
    from app.providers.segmentation import SegmentationProvider
    from app.workers.categorise import GarmentClassifier, MediaStore

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, Job], Awaitable[dict | None]]


class UnknownJobKind(LookupError):
    """A deployable was configured for a queue no handler serves."""

    def __init__(self, unknown: Sequence[str], known: Sequence[str]) -> None:
        self.unknown = tuple(unknown)
        self.known = tuple(known)
        super().__init__(
            f"no handler for job kind(s) {', '.join(unknown)}; "
            f"this service handles {', '.join(known)}"
        )


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


def stylist_handlers() -> dict[str, Handler]:
    """The stylist queue's handler.

    ``execute_run`` builds its own provider registry per job, because
    ``AIRunRecorder`` needs the job's session to record accounting rows in the
    same transaction as the outfit it is accounting for.
    """
    from app.domain import stylist

    return {stylist.JOB_KIND: stylist.handle_job}


def wardrobe_media_handlers(
    *,
    classifier: GarmentClassifier | None = None,
    segmenter: SegmentationProvider | None = None,
    store: MediaStore | None = None,
) -> dict[str, Handler]:
    """Categorisation and background removal.

    Every collaborator is injectable so the test suite can wire doubles, and
    every default *refuses* rather than fakes: with no credential configured
    the jobs fail with a recorded reason and the garment keeps its original
    photograph. A worker deployable passes the real three.

    The segmentation provider is chosen by name from
    :data:`~app.providers.segmentation.SEGMENTATION_PROVIDERS` so a swap is a
    config change rather than an edit here.
    """
    from app.config import get_settings
    from app.providers.meta import MetaProvider
    from app.providers.segmentation import SEGMENTATION_PROVIDERS
    from app.workers.categorise import MetaGarmentClassifier, categorise_handlers

    if classifier is None or segmenter is None:
        cfg = get_settings()
        if classifier is None:
            classifier = MetaGarmentClassifier(MetaProvider())
        if segmenter is None:
            segmenter = SEGMENTATION_PROVIDERS[cfg.segmentation_provider]()

    return categorise_handlers(
        classifier=classifier, segmenter=segmenter, store=store
    )


def all_handlers(
    kinds: Sequence[str] | None = None,
    *,
    classifier: GarmentClassifier | None = None,
    segmenter: SegmentationProvider | None = None,
    store: MediaStore | None = None,
) -> dict[str, Handler]:
    """Every handler this service knows how to run.

    ``kinds`` selects a subset, which is how one deployable per queue class is
    achieved from a single image (ADR-003). An unknown kind is *not* silently
    dropped: a deployable asked to serve a queue nobody handles would poll
    forever and look healthy, so it raises instead.
    """
    handlers = {
        **media_handlers(),
        **stylist_handlers(),
        **wardrobe_media_handlers(
            classifier=classifier, segmenter=segmenter, store=store
        ),
    }
    if kinds is None:
        return handlers

    unknown = sorted(set(kinds) - set(handlers))
    if unknown:
        raise UnknownJobKind(unknown, sorted(handlers))
    return {kind: handlers[kind] for kind in kinds}
