"""user cohorts: group people by wardrobe so inspiration is generated once

Revision ID: 0014_user_cohorts
Revises: 0013_saved_looks
Create Date: 2026-10-29

Generating fresh inspiration per user per week is a per-user model bill that
grows linearly with sign-ups. Serving one generated set to everybody with a
similar wardrobe makes the bill grow with the number of distinct *kinds* of
wardrobe instead.

A derived cache, rebuilt on a schedule. Nothing here is authoritative and
dropping the whole table costs one recomputation.

The three signature parts are columns rather than only a composed string,
because counting a cohort means asking "how many share two of these three",
and doing that against a composed key needs prefix matching that silently
stops working when the dropped part is in the middle.

Nothing in this table identifies a garment. Category counts and a stated
dress code only, which is what makes sharing generated content across a
cohort safe by construction rather than by care.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_user_cohorts"
down_revision = "0013_saved_looks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_cohorts",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cohort_key", sa.String(200), nullable=False),
        sa.Column("owns_key", sa.String(120), nullable=False),
        sa.Column("dress_code", sa.String(32), nullable=False),
        sa.Column("size_band", sa.String(16), nullable=False),
        sa.Column(
            "signature",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
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
        # One row per person: current state, not a history.
        sa.UniqueConstraint("user_id", name="uq_user_cohorts_user"),
    )
    op.create_index("ix_user_cohorts_key", "user_cohorts", ["cohort_key"])
    op.create_index(
        "ix_user_cohorts_parts",
        "user_cohorts",
        ["owns_key", "size_band", "dress_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_cohorts_parts", table_name="user_cohorts")
    op.drop_index("ix_user_cohorts_key", table_name="user_cohorts")
    op.drop_table("user_cohorts")
