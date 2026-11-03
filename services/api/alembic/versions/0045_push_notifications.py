"""device tokens and the push outbox

Revision ID: 0045_push_notifications
Revises: 0044_comment_likes
Create Date: 2026-11-01

Two tables, because they answer two different questions: where an
account can be reached right now, and what somebody is owed and when.

`device_tokens` is keyed by the token itself rather than a surrogate.
A push token addresses one installation, so the same token arriving
again is the same device - usually the same person signing back in,
sometimes a different one on a shared handset - and the row is
updated rather than duplicated. Without that key, a stale row would go
on delivering one person's notifications to a phone somebody else now
uses.

`push_outbox` is addressed to a person, not a device: which phones
they have is resolved at send time, so a message queued before a new
phone was registered still reaches it. Its two indexes are its two
queries - "what is due" for the sender, and "is this person already
owed one of these about this thing" for the batching that turns
twenty likes into one notification.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_push_notifications"
down_revision = "0044_comment_likes"
branch_labels = None
depends_on = None

PLATFORMS = ("expo", "apns", "fcm")
STATES = ("queued", "sent", "dropped")


def _enum(name: str, values: tuple[str, ...], bind) -> sa.types.TypeEngine:
    """The enum, created up front on Postgres and inline on SQLite.

    `create_type=False` for the same reason every other revision here
    does it: `create_table` would otherwise emit a second CREATE TYPE
    for a type that already exists, which fails and leaves the
    revision half-applied.
    """
    if bind.dialect.name == "postgresql":
        sa.Enum(*values, name=name).create(bind, checkfirst=True)
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    bind = op.get_bind()
    platform = _enum("push_platform", PLATFORMS, bind)
    state = _enum("push_outbox_state", STATES, bind)

    op.create_table(
        "device_tokens",
        sa.Column("token", sa.String(255), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", platform, nullable=False, server_default="expo"),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_device_tokens_user", "device_tokens", ["user_id"])

    op.create_table(
        "push_outbox",
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
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("subject", sa.String(64), nullable=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.String(300), nullable=False),
        sa.Column("deep_link", sa.String(200), nullable=True),
        sa.Column("people", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "send_after",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("state", state, nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_push_outbox_due", "push_outbox", ["state", "send_after"]
    )
    op.create_index(
        "ix_push_outbox_batch",
        "push_outbox",
        ["user_id", "kind", "subject", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_push_outbox_batch", table_name="push_outbox")
    op.drop_index("ix_push_outbox_due", table_name="push_outbox")
    op.drop_table("push_outbox")
    op.drop_index("ix_device_tokens_user", table_name="device_tokens")
    op.drop_table("device_tokens")
    bind = op.get_bind()
    sa.Enum(name="push_outbox_state").drop(bind, checkfirst=True)
    sa.Enum(name="push_platform").drop(bind, checkfirst=True)
