"""moodboards: named collections, and what is pinned to them

Revision ID: 0017_moodboards
Revises: 0016_outfit_plans
Create Date: 2026-10-29

Distinct from ``saved_looks`` on purpose. Saving is "I like this"; pinning is
"this belongs with these others". One is a verdict on a single look, the other
an argument about several, and collapsing them means either that liking
something files it somewhere or that a board is only a filtered view of likes.

``position`` is a column because a board is a composition — the arrangement is
part of what somebody made — and ``unpin`` compacts it, so removing the middle
pin cannot leave a hole that a later append collides with.

``look_id`` is a string, not a foreign key, for the reason every other look
reference in this schema is not: looks are bundled content, and one retired in
a later release should drop out of a board rather than break the read.

Nothing here stores an image, and nothing here may. When boards gain the
ability to hold somebody's own photograph it goes through the media pipeline
that already owns ownership and consent, not a URL column added here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_moodboards"
down_revision = "0016_outfit_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moodboards",
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
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
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
        # Two boards with the same name are two boards nobody can tell apart.
        sa.UniqueConstraint("user_id", "name", name="uq_moodboards_user_name"),
    )
    op.create_index("ix_moodboards_user", "moodboards", ["user_id"])

    op.create_table(
        "moodboard_pins",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "moodboard_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("moodboards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("look_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
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
            "moodboard_id", "look_id", name="uq_moodboard_pins_board_look"
        ),
    )
    op.create_index(
        "ix_moodboard_pins_board_position",
        "moodboard_pins",
        ["moodboard_id", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_moodboard_pins_board_position", table_name="moodboard_pins")
    op.drop_table("moodboard_pins")
    op.drop_index("ix_moodboards_user", table_name="moodboards")
    op.drop_table("moodboards")
