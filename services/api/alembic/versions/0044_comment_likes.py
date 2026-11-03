"""liking a comment

Revision ID: 0044_comment_likes
Revises: 0043_drop_looks
Create Date: 2026-11-01

A heart beside Reply on every comment, which until now had nothing
behind it.

The pair is the primary key, the same shape `post_saves` uses: liking
twice is the same state, so the database enforces it rather than every
caller remembering to check. Both sides cascade - a deleted comment
takes its likes with it, and so does a deleted account - because a
like is a fact about a row that no longer exists once that row is
gone.

The index is on the comment, which is the direction a thread reads it
in: "how many liked this one", once per comment on the page.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_comment_likes"
down_revision = "0043_drop_looks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_likes",
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "comment_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("post_comments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_comment_likes_comment", "comment_likes", ["comment_id"])


def downgrade() -> None:
    op.drop_index("ix_comment_likes_comment", table_name="comment_likes")
    op.drop_table("comment_likes")
