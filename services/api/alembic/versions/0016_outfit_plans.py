"""outfit plans: what you are wearing on Thursday

Revision ID: 0016_outfit_plans
Revises: 0015_cohort_inspirations
Create Date: 2026-10-29

The app answers "what should I wear" on every screen and had nowhere to
answer it for a specific day.

``planned_for`` is a DATE, not a timestamp. A plan made in Nairobi for
Thursday must still be Thursday after landing in London, and a timestamp
moves it by a timezone.

One plan per person per day. Somebody who changes for the evening has a real
case this does not cover; the constraint is what makes planning idempotent,
and relaxing it later is a smaller change than untangling the duplicates
somebody would accumulate by double-tapping.

``worn`` is nullable on purpose. Null is "not yet answered", which is not
"no" — a plan for next Tuesday has not been declined, it has not happened,
and collapsing those two makes every future plan look rejected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_outfit_plans"
down_revision = "0015_cohort_inspirations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outfit_plans",
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
        sa.Column("planned_for", sa.Date, nullable=False),
        sa.Column("look_id", sa.String(64), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("worn", sa.Boolean, nullable=True),
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
        sa.UniqueConstraint(
            "user_id", "planned_for", name="uq_outfit_plans_user_date"
        ),
    )
    op.create_index(
        "ix_outfit_plans_user_date", "outfit_plans", ["user_id", "planned_for"]
    )


def downgrade() -> None:
    op.drop_index("ix_outfit_plans_user_date", table_name="outfit_plans")
    op.drop_table("outfit_plans")
