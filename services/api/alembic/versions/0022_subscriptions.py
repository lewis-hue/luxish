"""billing: subscriptions, from the one store this build honestly has

Revision ID: 0022_subscriptions
Revises: 0021_community_sharing
Create Date: 2026-10-30

The paywall, the manage screen and the stylist allowance meter all need a
subscription to read, and real billing is blocked on Apple and Google store
accounts this project does not hold (ADR-011). This table records where each
subscription came from in a ``store`` column whose only writable value today
is ``simulated`` — so the screens ship now, against rows that can never be
mistaken for revenue, and the real stores join the enum when their
credentials exist rather than rewriting history.

No money columns, deliberately. A simulated subscription moves no money;
when store billing lands, amounts arrive on an append-only ledger as
``(amount_minor, currency)`` per ADR-011.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_subscriptions"
down_revision = "0021_community_sharing"
branch_labels = None
depends_on = None

PLANS = ("plus",)
STATES = ("active", "expired")
STORES = ("simulated", "app_store", "play_billing")


def upgrade() -> None:
    # Created explicitly, then referenced with `create_type=False`, for the
    # same half-applied-revision reason 0018 records at length.
    bind = op.get_bind()
    plan: sa.types.TypeEngine
    state: sa.types.TypeEngine
    store: sa.types.TypeEngine
    if bind.dialect.name == "postgresql":
        plan = postgresql.ENUM(*PLANS, name="subscription_plan", create_type=False)
        state = postgresql.ENUM(*STATES, name="subscription_state", create_type=False)
        store = postgresql.ENUM(*STORES, name="subscription_store", create_type=False)
        sa.Enum(*PLANS, name="subscription_plan").create(bind, checkfirst=True)
        sa.Enum(*STATES, name="subscription_state").create(bind, checkfirst=True)
        sa.Enum(*STORES, name="subscription_store").create(bind, checkfirst=True)
    else:
        plan = sa.Enum(*PLANS, name="subscription_plan")
        state = sa.Enum(*STATES, name="subscription_state")
        store = sa.Enum(*STORES, name="subscription_store")

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", plan, nullable=False),
        sa.Column("state", state, nullable=False, server_default="active"),
        sa.Column("store", store, nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # "This person's live subscription" is the only read that matters.
    op.create_index(
        "ix_subscriptions_user_id_state", "subscriptions", ["user_id", "state"]
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id_state", table_name="subscriptions")
    op.drop_table("subscriptions")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="subscription_store").drop(bind, checkfirst=True)
        sa.Enum(name="subscription_state").drop(bind, checkfirst=True)
        sa.Enum(name="subscription_plan").drop(bind, checkfirst=True)
