"""Clearing a conversation, for one person.

A watermark rather than a delete: the other half of a thread is the
other person's, and clearing yours cannot reach into theirs. Reads
for that member start after this moment; anything sent afterwards
arrives normally, because clearing is not a way to stop hearing from
somebody - blocking is.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_clear_thread"
down_revision = "0040_message_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("direct_thread_members") as batch:
        batch.add_column(
            sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("direct_thread_members") as batch:
        batch.drop_column("cleared_at")
