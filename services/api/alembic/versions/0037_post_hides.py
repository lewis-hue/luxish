"""Hiding one fit from one person's board.

"Show fewer like this" needs somewhere to remember the answer, and a
block is far too big a hammer: not wanting to see one photograph again
is not the same as not wanting to see its author ever.

The pair is the primary key, like a follow and a save: hiding twice is
the same state, so the database says so rather than every caller
remembering to check.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_post_hides"
down_revision = "0036_profile_banner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_hides",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "post_id",
            sa.Uuid(),
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
    # "What has this person hidden", which is the only direction the
    # board reads it in.
    op.create_index("ix_post_hides_user", "post_hides", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_post_hides_user", table_name="post_hides")
    op.drop_table("post_hides")
