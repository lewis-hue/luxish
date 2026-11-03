"""a copy of everything somebody put in, on request

Revision ID: 0052_account_exports
Revises: 0051_shot_landscape
Create Date: 2026-11-03

Settings has carried a dead "Export my data" row since the account
section was built. It was Phase C in the roadmap and a disabled row on
the screen, which is the worst of both: a person looking for the
control finds it, taps it, and nothing happens.

**The table exists because an artifact has to be addressed.** The
`jobs` row says whether the work ran. This says what there is to
download, whose it is, and when it stops being downloadable - and the
last of those is the reason it is a column rather than a convention.
An export is the most sensitive object this system writes: one file
holding a wardrobe, a set of conversations and every picture somebody
owns. A link that works forever makes one leaked URL a permanent
breach, so the deadline rides on the row and the route refuses past it
whatever is still on disk.

`pictures_included` and `pictures_omitted` are not statistics. An
archive is capped, because a wardrobe of two hundred photographs is
not a phone download, and a cap that is not reported reads as a
complete copy of somebody's account when it is not one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052_account_exports"
down_revision = "0051_shot_landscape"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_exports",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            # The export goes when the account goes. It is a copy of
            # exactly the data being deleted, so leaving it readable
            # would make deletion a half-measure.
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(as_uuid=True),
            # Not CASCADE: losing the job record must not delete a
            # finished archive somebody is about to download.
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "state",
            sa.String(16),
            nullable=False,
            server_default="gathering",
        ),
        sa.Column("storage_key", sa.String(512), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column(
            "pictures_included",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "pictures_omitted",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("failure", sa.String(200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
    # Every read of this table is "the latest export for this person",
    # so the index is the one that answers it.
    op.create_index(
        "ix_account_exports_user_created",
        "account_exports",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_exports_user_created", table_name="account_exports")
    op.drop_table("account_exports")
