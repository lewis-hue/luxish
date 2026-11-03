"""A plan holds garments, not a catalogue entry.

Planning Thursday used to mean choosing a curated look - a catalogue
entry nobody owned, out of a generated set - so planning a week
produced a wardrobe of clothes the wearer did not have. A plan now
holds garments from their own wardrobe.

`look_id` becomes nullable rather than being dropped. The rows that
have one are somebody's plans, and removing the column would rewrite
their history to say they planned nothing. Nothing writes it any
more.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_plan_garments"
down_revision = "0041_clear_thread"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outfit_plan_items",
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("outfit_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # CASCADE: removing a garment takes it out of every day it was
        # planned for. A plan naming clothes somebody no longer owns is
        # worse than a shorter plan.
        sa.Column(
            "garment_id",
            sa.Uuid(),
            sa.ForeignKey("garments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("plan_id", "garment_id"),
    )
    op.create_index(
        "ix_outfit_plan_items_plan", "outfit_plan_items", ["plan_id", "position"]
    )

    with op.batch_alter_table("outfit_plans") as batch:
        batch.alter_column(
            "look_id", existing_type=sa.String(64), nullable=True
        )


def downgrade() -> None:
    # Plans written since the change have no look to put back, so the
    # column cannot be made required again without inventing one.
    op.execute(sa.text("DELETE FROM outfit_plans WHERE look_id IS NULL"))
    with op.batch_alter_table("outfit_plans") as batch:
        batch.alter_column(
            "look_id", existing_type=sa.String(64), nullable=False
        )
    op.drop_index("ix_outfit_plan_items_plan", table_name="outfit_plan_items")
    op.drop_table("outfit_plan_items")
