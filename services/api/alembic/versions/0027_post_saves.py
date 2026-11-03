"""community: keeping a fit

Revision ID: 0027_post_saves
Revises: 0026_posts
Create Date: 2026-10-31

The count a fit carries on its picture. A save is an action rather than
text, which is why it ships now while comments wait for the moderation
console: there is nothing here to read.

The pair is the primary key, like `follows` and `blocks`, so keeping a
fit twice is the same state by schema rather than by caller diligence.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_post_saves"
down_revision = "0026_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_saves",
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # "How many kept this", which is the direction every card reads it in.
    op.create_index("ix_post_saves_post", "post_saves", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_post_saves_post", table_name="post_saves")
    op.drop_table("post_saves")
