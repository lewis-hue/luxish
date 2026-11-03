"""one person can take a message out of their own copy of a thread

Revision ID: 0048_message_hidden_for
Revises: 0047_shot_brief
Create Date: 2026-11-02

**Not the same act as unsending, and the difference is the point.**

`unsend` already exists and belongs to whoever wrote the message: it
tombstones the row, so it leaves both copies of the conversation.
That is right for taking back something you said, and it is the only
delete a sender should have - a button that removed a message from
somebody else's thread without being its author would let anybody
edit anybody's record of a conversation.

The other half was missing. A person who *received* something they
would rather not scroll past again had nothing: the whole thread
could be cleared (`direct_thread_members.cleared_at`) and one message
could not. Clearing a conversation to be rid of one line is a very
large hammer, and it takes everything else with it.

So this is per person and per message, and it is deliberately not
visible to anybody else. Hiding a message changes one reader's view
and nothing about what was said: the sender's copy is untouched, the
row is untouched, and a moderation report still finds it. The other
person is not told, because there is nothing for them to know -
somebody choosing not to look at something is not an event in their
conversation.

A composite primary key rather than a surrogate id: the pair *is*
the fact, and it makes hiding the same message twice a no-op rather
than two rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_message_hidden_for"
down_revision = "0047_shot_brief"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "direct_message_hidden",
        sa.Column(
            "message_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("direct_messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Reading a thread asks "which of these has this person hidden",
    # so the index leads with the person.
    op.create_index(
        "ix_direct_message_hidden_user_id",
        "direct_message_hidden",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_direct_message_hidden_user_id", "direct_message_hidden")
    op.drop_table("direct_message_hidden")
