"""cohort inspirations: one generated set serving everybody like you

Revision ID: 0015_cohort_inspirations
Revises: 0014_user_cohorts
Create Date: 2026-10-29

One row per cohort per window, so the model bill grows with the number of
distinct kinds of wardrobe rather than with the number of users.

**There is no user_id column, and there must never be one.** A row that
belonged to a person could carry their wardrobe to the next person in the
group; the reliable prevention is for the row to have no idea who it is for.
What it knows is a cohort key, which holds garment-category counts and a
stated dress code and nothing else.

A validity *window* rather than a timestamp: a set generated early for the
next window must not become current when it is written, and the previous one
has to stay readable until its replacement is valid so nobody meets an empty
shelf mid-regeneration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_cohort_inspirations"
down_revision = "0014_user_cohorts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cohort_inspirations",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("cohort_key", sa.String(200), nullable=False),
        sa.Column(
            "collections",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("rationale", sa.String(300), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
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
        # Regenerating a window replaces it rather than stacking, so a
        # retried task cannot double the spend.
        sa.UniqueConstraint(
            "cohort_key", "valid_from", name="uq_cohort_inspirations_key_from"
        ),
    )
    op.create_index(
        "ix_cohort_inspirations_lookup",
        "cohort_inspirations",
        ["cohort_key", "valid_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_cohort_inspirations_lookup", table_name="cohort_inspirations")
    op.drop_table("cohort_inspirations")
