"""saved looks: a collection that survives a reinstall

Revision ID: 0013_saved_looks
Revises: 0012_look_interactions
Create Date: 2026-10-29

Saved looks have lived in the device's key-value store since there was no
session to own them. There is one now, and the local-only version has a cost
that grows with use: a reinstall loses the whole collection, and a second
device starts empty.

Separate from ``look_interactions`` on purpose. An interaction is an event —
weighted, decaying, only ever read as an aggregate across people. A saved look
is state: kept or not kept, and un-keeping has to remove it rather than append
an opposite event. One table cannot be both without either counting un-saves
as enthusiasm or producing a collection nobody can remove from.

``saved_at`` is device time, not write time. The first sign-in after this
ships carries a whole local collection up in one request, and ordering by
write time would stack years of saves into one second.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_saved_looks"
down_revision = "0012_look_interactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_looks",
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
        sa.Column("look_id", sa.String(64), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
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
        # Keeping the same look twice is keeping it once. The migration from
        # local storage re-sends what it is unsure about, so without this an
        # interrupted run would duplicate the collection on the retry.
        sa.UniqueConstraint("user_id", "look_id", name="uq_saved_looks_user_look"),
    )
    op.create_index(
        "ix_saved_looks_user_saved_at", "saved_looks", ["user_id", "saved_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_saved_looks_user_saved_at", table_name="saved_looks")
    op.drop_table("saved_looks")
