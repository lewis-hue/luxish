"""The durable record of a usage reservation.

Redis holds the *live* rolling counters, because a per-minute limiter has to be
cheap and shared. This table holds the audit trail of what was reserved and
what it turned out to cost, which Redis must not be trusted with: Redis is a
cache and may be flushed, and a reconciliation that runs twice must not bill
twice.

``key`` is unique, so reconciling the same reservation after a retry is a no-op
by schema rather than by caller diligence — the same property Task 6's
``jobs.idempotency_key`` has, for the same reason.

Every amount is an integer (ADR-011). ``*_micro_minor`` is millionths of a
currency minor unit, which is the resolution per-million-token pricing needs
without ever reaching for a float.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, utcnow, uuid_pk

USAGE_RESERVATION_STATES: tuple[str, ...] = (
    #: Taken before the call. Counts against the team's window.
    "reserved",
    #: Settled against the provider's reported usage.
    "reconciled",
    #: The call never happened, or failed before producing usage.
    "released",
)

usage_reservation_state_enum = named_enum(
    "usage_reservation_state", *USAGE_RESERVATION_STATES
)


class UsageReservation(Base, TimestampMixin):
    __tablename__ = "usage_reservations"
    __table_args__ = (
        sa.UniqueConstraint("key", name="uq_usage_reservations_key"),
        sa.Index("ix_usage_reservations_team_id_created_at", "team_id", "created_at"),
        sa.CheckConstraint("estimated_tokens >= 0", name="estimated_tokens_non_negative"),
        sa.CheckConstraint(
            "actual_tokens IS NULL OR actual_tokens >= 0", name="actual_tokens_non_negative"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: The Redis reservation id. Unique, so settling twice cannot double count.
    key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Limits are per team, so reservations are held per team (ADR-007).
    team_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    provider: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    model: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    state: Mapped[str] = mapped_column(
        usage_reservation_state_enum,
        nullable=False,
        default="reserved",
        server_default="reserved",
    )

    estimated_tokens: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    estimated_micro_minor: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, default=0, server_default=sa.text("0")
    )
    actual_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    actual_micro_minor: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, default="USD", server_default="USD"
    )

    reserved_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, server_default=sa.func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    @property
    def is_settled(self) -> bool:
        return self.state != "reserved"

    @property
    def variance_tokens(self) -> int | None:
        """How wrong the estimate was. Feeds the Task 15 capacity worksheet."""
        if self.actual_tokens is None:
            return None
        return self.actual_tokens - self.estimated_tokens
