"""Durable jobs.

All model work is queued, never awaited in a request handler (ADR-013 — Cloud
Run request timeouts make the alternative a liability). This table *is* the
local queue: claiming is ``SELECT … FOR UPDATE SKIP LOCKED``, which is why
``state``, ``available_at`` and ``locked_at`` are columns rather than
in-process state.

``idempotency_key`` is unique at the schema level. Retrying an enqueue after a
network failure is the normal case, so one job per key is a database property
rather than a matter of caller diligence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, named_enum, uuid_pk

JOB_STATES: tuple[str, ...] = ("queued", "running", "succeeded", "failed", "dead_letter")
#: States from which a job will never be handed to a worker again.
TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "dead_letter"})

job_state_enum = named_enum("job_state", *JOB_STATES)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        # The claim query's access path: ready work of a given kind, oldest first.
        sa.Index("ix_jobs_state_kind_available_at", "state", "kind", "available_at"),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="progress_range"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(
        job_state_enum, nullable=False, default="queued", server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=5, server_default=sa.text("5")
    )
    #: Null means "enqueued without a key"; the unique constraint ignores nulls.
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    progress: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.0, server_default=sa.text("0")
    )
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
