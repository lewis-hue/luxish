"""Messages between two people.

They were always gated on blocking and reporting shipping first, on the
reasoning that an app which lets strangers write to each other without
those is an app with no answer when somebody is harassed. Both now
exist, so this does.

The pair is stored sorted and made unique: without that, two people
opening each other at the same moment create two threads and each sees
half the conversation.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_direct_messages"
down_revision = "0038_private_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "direct_threads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "lower_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "upper_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("lower_id", "upper_id", name="uq_direct_threads_pair"),
    )
    op.create_index(
        "ix_direct_threads_lower_active",
        "direct_threads",
        ["lower_id", "last_message_at"],
    )
    op.create_index(
        "ix_direct_threads_upper_active",
        "direct_threads",
        ["upper_id", "last_message_at"],
    )

    op.create_table(
        "direct_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Uuid(),
            sa.ForeignKey("direct_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_direct_messages_thread_created",
        "direct_messages",
        ["thread_id", "created_at"],
    )

    op.create_table(
        "direct_thread_members",
        sa.Column(
            "thread_id",
            sa.Uuid(),
            sa.ForeignKey("direct_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "notifies", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "user_id"),
    )
    op.create_index(
        "ix_direct_thread_members_user", "direct_thread_members", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_direct_thread_members_user", table_name="direct_thread_members")
    op.drop_table("direct_thread_members")
    op.drop_index("ix_direct_messages_thread_created", table_name="direct_messages")
    op.drop_table("direct_messages")
    op.drop_index("ix_direct_threads_upper_active", table_name="direct_threads")
    op.drop_index("ix_direct_threads_lower_active", table_name="direct_threads")
    op.drop_table("direct_threads")
