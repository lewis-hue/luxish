"""One row per model call.

This table answers three questions that are impossible to answer afterwards if
they are not recorded at the time: *which prompt version produced this*, *what
did it cost*, and *what happened*. Task 8's stylist loop reads the prompt
version off here when an output has to be explained or reproduced.

``provider`` and ``model`` are plain strings rather than enums on purpose: this
is an append-only audit row, and a model we stop offering must not make the
history of its calls unreadable.

Cost is stored twice, both integer (ADR-011 — no float money anywhere):

* ``cost_micro_minor`` is exact. Published prices are minor units per million
  tokens, so ``tokens x price`` is exactly millionths of a minor unit.
* ``cost_minor`` is that value rounded **up** to the currency's minor unit,
  which is what the ledger can actually post.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, named_enum, uuid_pk

AI_RUN_OUTCOMES: tuple[str, ...] = (
    "pending",
    "succeeded",
    #: The provider was called and failed.
    "failed",
    #: We refused before calling: unsupported modality, unowned garment id, an
    #: injected instruction. A refusal is not a failure and must not be retried
    #: as if it were.
    "refused",
    "rate_limited",
    "cancelled",
)

ai_run_outcome_enum = named_enum("ai_run_outcome", *AI_RUN_OUTCOMES)


class AIRun(Base, TimestampMixin):
    __tablename__ = "ai_runs"
    __table_args__ = (
        sa.Index("ix_ai_runs_user_id_created_at", "user_id", "created_at"),
        sa.Index("ix_ai_runs_team_id_created_at", "team_id", "created_at"),
        sa.Index("ix_ai_runs_provider_model", "provider", "model"),
        sa.CheckConstraint("input_tokens >= 0", name="input_tokens_non_negative"),
        sa.CheckConstraint("output_tokens >= 0", name="output_tokens_non_negative"),
        sa.CheckConstraint("cost_minor >= 0", name="cost_minor_non_negative"),
        sa.CheckConstraint("cost_micro_minor >= 0", name="cost_micro_minor_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Nullable: a system-initiated run (a backfill, an eval) has no owner, and
    #: a user deletion must not delete the financial record of their spend.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Meta's rate limits are per team, so spend is attributed per team too.
    team_id: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)

    provider: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    model: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    #: The ``VERSION`` constant of the prompt module that produced this call.
    prompt_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    purpose: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    #: The Redis reservation this run was billed against, for reconciliation.
    reservation_id: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    #: The request id the call was made under, to join a run to its HTTP log.
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    outcome: Mapped[str] = mapped_column(
        ai_run_outcome_enum, nullable=False, default="pending", server_default="pending"
    )

    input_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    output_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    cached_input_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    reasoning_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    images: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )

    cost_minor: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, default=0, server_default=sa.text("0")
    )
    cost_micro_minor: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, default=0, server_default=sa.text("0")
    )
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, default="USD", server_default="USD"
    )

    finish_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    response_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Tool names executed, token-level detail, anything a reviewer needs. Never
    #: the prompt or the output: those are user content with their own lifecycle.
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def is_settled(self) -> bool:
        return self.outcome != "pending"
