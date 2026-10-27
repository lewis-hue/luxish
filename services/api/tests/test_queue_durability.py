"""The durability claims in ADR-018, as tests.

ADR-018 says the broker may lose or duplicate a message without losing work.
That is a claim about behaviour, so it is asserted here rather than left as
prose. Each test names the failure it is standing in for:

* a duplicated delivery must not run the job twice;
* a lost delivery must not lose the job;
* a worker that dies mid-job must not strand it forever;
* a job that kills its worker every time must still stop eventually.

None of these needs Redis. That is the point of keeping PostgreSQL as the
record: the durability is testable without the component that is unreliable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import (
    DEFAULT_LEASE_SECONDS,
    claim_job_by_id,
    complete_job,
    enqueue,
    ready_job_ids,
    reclaim_stalled_jobs,
    set_dispatcher,
)
from app.models.job import Job


@pytest.fixture
async def session(engine) -> AsyncSession:  # type: ignore[no-untyped-def]
    from tests.conftest import session_factory

    maker = session_factory(engine)
    async with maker() as s:
        yield s


async def _job(session: AsyncSession, kind: str = "media.derive") -> Job:
    return await enqueue(session, kind, {"asset_id": str(uuid.uuid4())}, notify=False)


# --------------------------------------------------------------------------- #
# Duplicate delivery
# --------------------------------------------------------------------------- #
async def test_a_duplicated_delivery_runs_the_job_once(session: AsyncSession) -> None:
    """Redis can deliver the same message twice. That must cost nothing.

    This is what lets the broker be unreliable: idempotency is a property of
    the claim, not something the broker has to provide.
    """
    job = await _job(session)

    first = await claim_job_by_id(session, job.id, worker="w1")
    second = await claim_job_by_id(session, job.id, worker="w2")

    assert first is not None, "the first delivery must claim the job"
    assert second is None, "the second delivery must decline, not run it again"
    assert first.attempts == 1, "a duplicate must not consume a second attempt"
    assert first.locked_by == "w1"


async def test_a_completed_job_cannot_be_reclaimed(session: AsyncSession) -> None:
    # The sweeper dispatches anything that looks ready; a late message arriving
    # after completion must not re-run finished work.
    job = await _job(session)
    claimed = await claim_job_by_id(session, job.id, worker="w1")
    assert claimed is not None
    await complete_job(session, claimed, result={"ok": True})

    assert await claim_job_by_id(session, job.id, worker="w2") is None


async def test_claiming_an_unknown_id_declines_rather_than_raising(
    session: AsyncSession,
) -> None:
    # A message naming a job that was deleted must not crash a worker.
    assert await claim_job_by_id(session, uuid.uuid4(), worker="w1") is None


# --------------------------------------------------------------------------- #
# Lost delivery
# --------------------------------------------------------------------------- #
async def test_a_lost_delivery_leaves_the_job_findable(session: AsyncSession) -> None:
    """The job survives a broker that never delivered the message at all.

    ``notify=False`` *is* the lost message: the row committed and nothing was
    dispatched. The sweeper's read must still find it.
    """
    job = await _job(session)
    assert job.id in await ready_job_ids(session)


async def test_a_failed_dispatch_does_not_fail_the_enqueue(
    session: AsyncSession,
) -> None:
    """A broker outage must not surface as an error in the user's request.

    The job is already committed when dispatch runs, so a raise here would
    report failure for work that will in fact be done.
    """
    calls: list[tuple[uuid.UUID, str]] = []

    def exploding(job_id: uuid.UUID, kind: str) -> None:
        calls.append((job_id, kind))
        raise ConnectionError("redis is down")

    set_dispatcher(exploding)
    try:
        job = await enqueue(session, "media.derive", {"a": 1})
    finally:
        set_dispatcher(None)

    assert calls, "dispatch should have been attempted"
    assert job.state == "queued"
    assert job.id in await ready_job_ids(session)


async def test_an_idempotent_re_enqueue_does_not_dispatch_twice(
    session: AsyncSession,
) -> None:
    calls: list[uuid.UUID] = []
    set_dispatcher(lambda job_id, kind: calls.append(job_id))
    try:
        first = await enqueue(session, "media.derive", {"a": 1}, idempotency_key="k1")
        second = await enqueue(session, "media.derive", {"a": 1}, idempotency_key="k1")
    finally:
        set_dispatcher(None)

    assert first.id == second.id
    assert calls == [first.id], "the second enqueue must not re-dispatch"


# --------------------------------------------------------------------------- #
# The worker died mid-job
# --------------------------------------------------------------------------- #
async def test_a_stalled_job_returns_to_the_queue(session: AsyncSession) -> None:
    """The failure every queue has and few handle.

    A worker claims a job and is then SIGKILLed: evicted, out of memory, or
    replaced during a deploy. Without a reclaim the row sits in ``running``
    forever. Nothing retries it, nothing reports it, and the queue looks
    healthy while the user watches a spinner.
    """
    job = await _job(session)
    claimed = await claim_job_by_id(session, job.id, worker="dead-worker")
    assert claimed is not None

    # Backdate the lease to simulate a worker that stopped heartbeating.
    claimed.locked_at = datetime.now(UTC) - timedelta(seconds=DEFAULT_LEASE_SECONDS + 60)
    await session.commit()

    reclaimed = await reclaim_stalled_jobs(session, lease_seconds=DEFAULT_LEASE_SECONDS)

    assert [j.id for j in reclaimed] == [job.id]
    assert reclaimed[0].state == "queued"
    assert reclaimed[0].locked_by is None
    assert job.id in await ready_job_ids(session)


async def test_a_job_inside_its_lease_is_left_alone(session: AsyncSession) -> None:
    """The dangerous direction: never re-dispatch a job that is still running.

    The reclaim cannot tell "the worker died" from "the worker is still
    working" — it sees only a timestamp. So a job whose lease has not expired
    must be untouched, or a healthy long job gets a second execution.
    """
    job = await _job(session)
    claimed = await claim_job_by_id(session, job.id, worker="busy-worker")
    assert claimed is not None

    assert await reclaim_stalled_jobs(session, lease_seconds=DEFAULT_LEASE_SECONDS) == []

    refreshed = await session.get(Job, job.id)
    assert refreshed is not None
    assert refreshed.state == "running"
    assert refreshed.locked_by == "busy-worker"


async def test_a_running_job_is_not_offered_to_the_sweeper(
    session: AsyncSession,
) -> None:
    job = await _job(session)
    assert await claim_job_by_id(session, job.id, worker="w1") is not None
    assert job.id not in await ready_job_ids(session)


# --------------------------------------------------------------------------- #
# The poison job
# --------------------------------------------------------------------------- #
async def test_a_job_that_always_kills_its_worker_eventually_stops(
    session: AsyncSession,
) -> None:
    """The bound Redis has no equivalent of.

    Celery's own ``task_reject_on_worker_lost`` is documented as able to cause
    message loops, and on Redis a rejected message returns to the *head* of the
    queue, so a job that kills its worker is retried immediately and forever.
    Attempts are counted in PostgreSQL, so the loop terminates here.
    """
    job = await enqueue(
        session, "media.derive", {"poison": True}, max_attempts=3, notify=False
    )
    stale = DEFAULT_LEASE_SECONDS + 60

    for expected_attempt in (1, 2, 3):
        claimed = await claim_job_by_id(session, job.id, worker="doomed")
        assert claimed is not None, f"should be claimable on attempt {expected_attempt}"
        assert claimed.attempts == expected_attempt
        claimed.locked_at = datetime.now(UTC) - timedelta(seconds=stale)
        await session.commit()
        await reclaim_stalled_jobs(session, lease_seconds=DEFAULT_LEASE_SECONDS)

    final = await session.get(Job, job.id)
    assert final is not None
    assert final.state == "dead_letter", "the loop must terminate, not run forever"
    assert final.attempts == 3
    assert final.last_error is not None
    assert await claim_job_by_id(session, job.id, worker="w") is None


async def test_the_sweeper_reports_what_it_did(session: AsyncSession) -> None:
    # The counts drive alerting, so a silent sweep is as bad as no sweep.
    requeued = await _job(session)
    claimed = await claim_job_by_id(session, requeued.id, worker="dead")
    assert claimed is not None
    claimed.locked_at = datetime.now(UTC) - timedelta(seconds=DEFAULT_LEASE_SECONDS + 60)
    await session.commit()

    reclaimed = await reclaim_stalled_jobs(session, lease_seconds=DEFAULT_LEASE_SECONDS)
    assert len(reclaimed) == 1
    assert reclaimed[0].last_error is not None
    assert "lease expired" in reclaimed[0].last_error


async def test_ready_ids_can_be_filtered_by_kind(session: AsyncSession) -> None:
    # One deployable per queue class: a media worker must not be handed AI work.
    media = await _job(session, "media.derive")
    ai = await _job(session, "stylist.run")

    assert await ready_job_ids(session, kinds=["media.derive"]) == [media.id]
    assert await ready_job_ids(session, kinds=["stylist.run"]) == [ai.id]


async def test_a_job_scheduled_for_later_is_not_ready_yet(
    session: AsyncSession,
) -> None:
    later = datetime.now(UTC) + timedelta(hours=1)
    job = await enqueue(
        session, "media.derive", {"a": 1}, available_at=later, notify=False
    )

    assert job.id not in await ready_job_ids(session)
    assert await claim_job_by_id(session, job.id, worker="eager") is None


async def test_every_job_state_is_accounted_for(session: AsyncSession) -> None:
    # Guards against a new state being added without the sweeper learning it.
    from app.models.job import JOB_STATES

    assert set(JOB_STATES) == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "dead_letter",
    }


async def test_the_lease_is_longer_than_the_hard_task_limit() -> None:
    """The single most dangerous number in the configuration.

    If the lease is shorter than a task's hard time limit, a job that is still
    legitimately running has its lease expire and gets a second execution. The
    two numbers live in different modules, so nothing but this test connects
    them.
    """
    from app.config import get_settings

    cfg = get_settings()
    assert cfg.job_lease_seconds > cfg.celery_task_time_limit_seconds, (
        "job_lease_seconds must exceed celery_task_time_limit_seconds, or a "
        "healthy long-running job will be re-dispatched while it runs"
    )


async def test_the_visibility_timeout_cannot_redeliver_before_postgres_does() -> None:
    """Postgres must be the only re-drive authority (ADR-018).

    Two redelivery mechanisms racing is how one job becomes three. Redis is
    configured never to redeliver, which is only true while its visibility
    timeout exceeds the lease.
    """
    from app.config import get_settings

    cfg = get_settings()
    assert cfg.celery_visibility_timeout_seconds > cfg.job_lease_seconds
    assert cfg.celery_soft_shutdown_seconds < 10, (
        "Cloud Run allows 10s between SIGTERM and SIGKILL; a longer soft "
        "shutdown is never honoured"
    )


async def test_enqueue_still_records_the_job_when_nothing_is_listening(
    session: AsyncSession,
) -> None:
    # The default state in tests and in a broker-less deployment.
    set_dispatcher(None)
    job = await enqueue(session, "media.derive", {"a": 1})
    found = await session.scalar(sa.select(Job).where(Job.id == job.id))
    assert found is not None
    assert found.state == "queued"
