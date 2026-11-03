"""Comments on a published fit.

A save shipped without review because there is nothing in it to moderate.
A comment is the opposite case - free text in front of people who did not
choose to receive it - so it arrives with the same fail-closed screen a
caption and a bio already use, and with its own state column to hold it
until the screen agrees.

Tombstoned rather than deleted, like every other user-owned row here, so
a thread does not silently rewrite itself and the record of what was
written survives its removal.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_post_comments"
down_revision = "0033_likeness_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "post_id",
            sa.Uuid(),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "pending_review",
                "published",
                "held",
                name="post_comment_state",
            ),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("screen_mode", sa.String(32), nullable=True),
        sa.Column("screen_note", sa.String(300), nullable=True),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            sa.ForeignKey("post_comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index(
        "ix_post_comments_post_created",
        "post_comments",
        ["post_id", "created_at"],
    )
    op.create_index("ix_post_comments_user", "post_comments", ["user_id"])
    op.create_index(
        "ix_post_comments_deleted_at", "post_comments", ["deleted_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_post_comments_deleted_at", table_name="post_comments")
    op.drop_index("ix_post_comments_user", table_name="post_comments")
    op.drop_index("ix_post_comments_post_created", table_name="post_comments")
    op.drop_table("post_comments")
    sa.Enum(name="post_comment_state").drop(op.get_bind(), checkfirst=True)
