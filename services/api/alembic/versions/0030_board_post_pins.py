"""Boards can hold somebody's post, not only a curated look.

A pin was always a curated look's string id, which made a board unable to
hold the thing people most want to collect: a fit another person posted.
`look_id` becomes nullable and `post_id` joins it, with a constraint that
exactly one is set — a pin points at one thing, and a row with both or
neither is a bug that should fail at write time rather than at render time.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_board_post_pins"
down_revision = "0029_profiles_tags_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("moodboard_pins") as batch:
        batch.alter_column("look_id", existing_type=sa.String(64), nullable=True)
        batch.add_column(sa.Column("post_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_moodboard_pins_post",
            "posts",
            ["post_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_moodboard_pins_board_post", ["moodboard_id", "post_id"]
        )
        batch.create_check_constraint(
            "ck_moodboard_pins_one_subject",
            "(look_id IS NULL) <> (post_id IS NULL)",
        )
    op.create_index(
        "ix_moodboard_pins_post", "moodboard_pins", ["post_id"], unique=False
    )


def downgrade() -> None:
    # Pins that point at a post have no representation in the old shape, so
    # they go rather than being rewritten into something false.
    op.execute(sa.text("DELETE FROM moodboard_pins WHERE post_id IS NOT NULL"))
    op.drop_index("ix_moodboard_pins_post", table_name="moodboard_pins")
    with op.batch_alter_table("moodboard_pins") as batch:
        batch.drop_constraint("ck_moodboard_pins_one_subject", type_="check")
        batch.drop_constraint("uq_moodboard_pins_board_post", type_="unique")
        batch.drop_constraint("fk_moodboard_pins_post", type_="foreignkey")
        batch.drop_column("post_id")
        batch.alter_column("look_id", existing_type=sa.String(64), nullable=False)
