"""gifts: an append-only credit ledger

Revision ID: 0024_gift_ledger
Revises: 0023_moderation
Create Date: 2026-10-30

ADR-011's ledger discipline, applied to gift credits: every movement is a
row, a balance is a sum, amounts are integers, and the two legs of a gift
share a ``transfer_id`` so they are auditable as one event. The only entry
point for credits in this build is ``simulated_topup``, which says so in
the row forever; store purchase kinds join the enum when their credentials
exist.

No message column: a gift that carries text is user-generated content
needing the moderation pipeline, so a gift carries a number and nothing
else.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_gift_ledger"
down_revision = "0023_moderation"
branch_labels = None
depends_on = None

ACCOUNTS = ("gift_credits",)
KINDS = ("simulated_topup", "gift_sent", "gift_received")


def upgrade() -> None:
    bind = op.get_bind()
    account: sa.types.TypeEngine
    kind: sa.types.TypeEngine
    if bind.dialect.name == "postgresql":
        account = postgresql.ENUM(*ACCOUNTS, name="credit_account", create_type=False)
        kind = postgresql.ENUM(*KINDS, name="credit_kind", create_type=False)
        sa.Enum(*ACCOUNTS, name="credit_account").create(bind, checkfirst=True)
        sa.Enum(*KINDS, name="credit_kind").create(bind, checkfirst=True)
    else:
        account = sa.Enum(*ACCOUNTS, name="credit_account")
        kind = sa.Enum(*KINDS, name="credit_kind")

    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account", account, nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("kind", kind, nullable=False),
        sa.Column(
            "counterparty_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("transfer_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_credit_ledger_user_account",
        "credit_ledger_entries",
        ["user_id", "account"],
    )
    op.create_index(
        "ix_credit_ledger_entries_user_id", "credit_ledger_entries", ["user_id"]
    )
    op.create_index(
        "ix_credit_ledger_entries_transfer_id",
        "credit_ledger_entries",
        ["transfer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_credit_ledger_entries_transfer_id", table_name="credit_ledger_entries"
    )
    op.drop_index(
        "ix_credit_ledger_entries_user_id", table_name="credit_ledger_entries"
    )
    op.drop_index("ix_credit_ledger_user_account", table_name="credit_ledger_entries")
    op.drop_table("credit_ledger_entries")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="credit_kind").drop(bind, checkfirst=True)
        sa.Enum(name="credit_account").drop(bind, checkfirst=True)
