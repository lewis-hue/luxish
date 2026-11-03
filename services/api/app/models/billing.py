"""Subscriptions, in the only form this build can honestly hold them.

**The store is simulated and the row says so.** Real billing runs through
Apple In-App Purchase and Google Play Billing, both of which are blocked on
accounts this project does not hold (ADR-011, INTEGRATION-MATRIX). Rather
than faking a store client, the ``store`` column names where a subscription
actually came from, and the only value this build can write is
``simulated`` — so when the real stores arrive their rows are distinguishable
from every row created before them, and a test fixture can never be mistaken
for a paying customer.

**No money columns.** A simulated subscription moves no money, so there is
nothing to record; when store billing lands, amounts arrive on an append-only
ledger as ``(amount_minor, currency)`` per ADR-011, not as columns here.

One subscription row per user is enforced in the domain rather than by a
partial unique index, because the index would need per-dialect ``WHERE``
clauses and the domain check is the same three lines either way.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

#: The paid plan. One, deliberately: a second tier is a pricing decision,
#: not a schema concern, and adding an enum value is one migration.
PLAN_IDS: tuple[str, ...] = ("plus",)

#: ``expired`` is terminal. ``active`` covers both renewing and cancelled-
#: but-paid-up subscriptions; whether it renews is ``auto_renew``'s answer.
SUBSCRIPTION_STATES: tuple[str, ...] = ("active", "expired")

#: Where the subscription came from. The real stores join this tuple when
#: their credentials exist; nothing in this build may write them.
SUBSCRIPTION_STORES: tuple[str, ...] = ("simulated", "app_store", "play_billing")

plan_enum = named_enum("subscription_plan", *PLAN_IDS)
subscription_state_enum = named_enum("subscription_state", *SUBSCRIPTION_STATES)
subscription_store_enum = named_enum("subscription_store", *SUBSCRIPTION_STORES)


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        sa.Index("ix_subscriptions_user_id_state", "user_id", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    plan: Mapped[str] = mapped_column(plan_enum, nullable=False)
    state: Mapped[str] = mapped_column(
        subscription_state_enum, nullable=False, default="active", server_default="active"
    )
    store: Mapped[str] = mapped_column(subscription_store_enum, nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    auto_renew: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    #: When the person asked for it not to renew. Access continues to
    #: ``current_period_end``; this is the audit of the choice, not a gate.
    canceled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
