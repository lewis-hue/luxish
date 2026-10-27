"""Task 6 — the durable queue.

A job survives the process that enqueued it, is claimed exactly once, and
cannot retry forever. The local queue is Postgres-backed
(``SELECT … FOR UPDATE SKIP LOCKED``); the Cloud Tasks adapter will implement
the same three calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import (
    JOB_STATES,
    claim_job,
    claim_statement,
    complete_job,
    enqueue,
    fail_job,
    update_progress,
)
from app.models.job import Job


async def test_the_same_idempotency_key_enqueued_twice_yields_one_job(
    db: AsyncSession,
) -> None:
    first = await enqueue(db, "media.derive", {"asset_id": "a"}, idempotency_key="k-1")
    second = await enqueue(db, "media.derive", {"asset_id": "a"}, idempotency_key="k-1")

    assert first.id == second.id
    assert (await db.scalar(sa.select(sa.func.count()).select_from(Job))) == 1


async def test_a_different_key_is_a_different_job(db: AsyncSession) -> None:
    await enqueue(db, "media.derive", {}, idempotency_key="k-a")
    await enqueue(db, "media.derive", {}, idempotency_key="k-b")
    assert (await db.scalar(sa.select(sa.func.count()).select_from(Job))) == 2


async def test_an_enqueue_without_a_key_is_always_a_new_job(db: AsyncSession) -> None:
    await enqueue(db, "media.derive", {})
    await enqueue(db, "media.derive", {})
    assert (await db.scalar(sa.select(sa.func.count()).select_from(Job))) == 2


async def test_claim_marks_the_job_running_and_counts_the_attempt(db: AsyncSession) -> None:
    job = await enqueue(db, "media.derive", {"asset_id": "a"}, idempotency_key="k-claim")

    claimed = await claim_job(db, kinds=["media.derive"], worker="worker-1")

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.state == "running"
    assert claimed.attempts == 1
    assert claimed.locked_at is not None
    assert claimed.locked_by == "worker-1"


async def test_a_claimed_job_is_not_claimed_again(db: AsyncSession) -> None:
    await enqueue(db, "media.derive", {}, idempotency_key="k-once")
    assert await claim_job(db, kinds=["media.derive"]) is not None
    assert await claim_job(db, kinds=["media.derive"]) is None


async def test_claim_respects_the_kind_filter(db: AsyncSession) -> None:
    await enqueue(db, "ai.style", {}, idempotency_key="k-ai")
    assert await claim_job(db, kinds=["media.derive"]) is None
    assert await claim_job(db, kinds=["ai.style"]) is not None


async def test_claim_ignores_a_job_scheduled_for_later(db: AsyncSession) -> None:
    await enqueue(
        db,
        "media.derive",
        {},
        idempotency_key="k-later",
        available_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert await claim_job(db, kinds=["media.derive"]) is None


async def test_complete_job_records_success_and_full_progress(db: AsyncSession) -> None:
    await enqueue(db, "media.derive", {}, idempotency_key="k-done")
    job = await claim_job(db, kinds=["media.derive"])
    assert job is not None

    await complete_job(db, job, result={"derivatives": 2})

    assert job.state == "succeeded"
    assert job.progress == pytest.approx(1.0)
    assert job.result == {"derivatives": 2}
    assert job.last_error is None


async def test_a_failure_below_the_limit_is_requeued_with_backoff(db: AsyncSession) -> None:
    await enqueue(db, "media.derive", {}, idempotency_key="k-retry", max_attempts=3)
    job = await claim_job(db, kinds=["media.derive"])
    assert job is not None

    await fail_job(db, job, "transient storage error")

    assert job.state == "queued"
    assert job.attempts == 1
    assert job.last_error == "transient storage error"
    assert job.available_at > datetime.now(UTC)


async def test_exceeding_max_attempts_lands_in_dead_letter_not_an_infinite_retry(
    db: AsyncSession,
) -> None:
    await enqueue(db, "media.derive", {}, idempotency_key="k-dead", max_attempts=2)

    for _ in range(2):
        job = await claim_job(db, kinds=["media.derive"], now=datetime.now(UTC) + timedelta(hours=1))
        assert job is not None
        await fail_job(db, job, "still broken")

    assert job.state == "dead_letter"
    assert job.attempts == 2
    # And it is never handed out again.
    assert await claim_job(db, kinds=["media.derive"], now=datetime.now(UTC) + timedelta(days=1)) is None


async def test_dead_letter_is_a_declared_state(db: AsyncSession) -> None:
    assert "dead_letter" in JOB_STATES


async def test_progress_is_bounded(db: AsyncSession) -> None:
    await enqueue(db, "media.derive", {}, idempotency_key="k-prog")
    job = await claim_job(db, kinds=["media.derive"])
    assert job is not None
    await update_progress(db, job, 0.5)
    assert job.progress == pytest.approx(0.5)
    with pytest.raises(ValueError):
        await update_progress(db, job, 1.5)


def test_the_claim_query_uses_skip_locked_on_postgres() -> None:
    """Two workers must never claim the same row, and must not block each other."""
    compiled = str(
        claim_statement(kinds=["media.derive"], now=datetime.now(UTC)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "FOR UPDATE" in compiled
    assert "SKIP LOCKED" in compiled


def test_idempotency_key_is_unique_in_the_schema() -> None:
    uniques = {
        tuple(sorted(c.columns.keys()))
        for c in Job.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    } | {tuple(sorted(i.columns.keys())) for i in Job.__table__.indexes if i.unique}
    assert ("idempotency_key",) in uniques


@pytest.mark.postgres
async def test_two_concurrent_claims_never_get_the_same_job() -> None:
    import os

    url = os.environ.get("LUXISH_TEST_PG_URL")
    if not url:
        pytest.skip("LUXISH_TEST_PG_URL is not set")

    from app.db.base import Base
    from app.db.session import build_engine, session_factory

    engine = build_engine(url.replace("+psycopg", "+asyncpg"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = session_factory(engine)
    try:
        async with maker() as setup:
            for index in range(4):
                await enqueue(setup, "media.derive", {}, idempotency_key=f"pg-{uuid.uuid4()}")

        async with maker() as a, maker() as b:
            first = await claim_job(a, kinds=["media.derive"], worker="a")
            second = await claim_job(b, kinds=["media.derive"], worker="b")
            assert first is not None and second is not None
            assert first.id != second.id
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
