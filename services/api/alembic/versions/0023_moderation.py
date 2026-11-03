"""moderation: blocks and reports, before any composer ships

Revision ID: 0023_moderation
Revises: 0022_subscriptions
Create Date: 2026-10-30

Both store policies make these preconditions for user-generated content:
Apple 1.2 requires blocking and reporting, Google Play's UGC policy requires
both in-app. The community tab already shows other people (first names and
curated looks), so the controls land now, ahead of anything that lets a
person publish a word.

Blocks mirror follows: the pair is the primary key, a check stops self-
blocking, and an index serves the "who blocked this person" direction that
every cross-user read filters on. Reports are rows a human reads later;
``subject_user_id`` is SET NULL so purging a reported account does not erase
the record that it was reported.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_moderation"
down_revision = "0022_subscriptions"
branch_labels = None
depends_on = None

SUBJECTS = ("account", "look")
REASONS = ("impersonation", "inappropriate", "spam", "other")
STATES = ("open", "resolved")


def upgrade() -> None:
    op.create_table(
        "blocks",
        sa.Column(
            "blocker_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "blocked_id",
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
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_blocks_not_self"),
    )
    op.create_index("ix_blocks_blocked", "blocks", ["blocked_id"])

    # Enums created explicitly then referenced with `create_type=False`, for
    # the half-applied-revision reason 0018 records at length.
    bind = op.get_bind()
    subject: sa.types.TypeEngine
    reason: sa.types.TypeEngine
    state: sa.types.TypeEngine
    if bind.dialect.name == "postgresql":
        subject = postgresql.ENUM(*SUBJECTS, name="report_subject", create_type=False)
        reason = postgresql.ENUM(*REASONS, name="report_reason", create_type=False)
        state = postgresql.ENUM(*STATES, name="report_state", create_type=False)
        sa.Enum(*SUBJECTS, name="report_subject").create(bind, checkfirst=True)
        sa.Enum(*REASONS, name="report_reason").create(bind, checkfirst=True)
        sa.Enum(*STATES, name="report_state").create(bind, checkfirst=True)
    else:
        subject = sa.Enum(*SUBJECTS, name="report_subject")
        reason = sa.Enum(*REASONS, name="report_reason")
        state = sa.Enum(*STATES, name="report_state")

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "reporter_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_kind", subject, nullable=False),
        sa.Column(
            "subject_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_ref", sa.String(64), nullable=True),
        sa.Column("reason", reason, nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("state", state, nullable=False, server_default="open"),
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
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])
    op.create_index("ix_reports_subject_user_id", "reports", ["subject_user_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_subject_user_id", table_name="reports")
    op.drop_index("ix_reports_reporter_id", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_blocks_blocked", table_name="blocks")
    op.drop_table("blocks")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="report_state").drop(bind, checkfirst=True)
        sa.Enum(name="report_reason").drop(bind, checkfirst=True)
        sa.Enum(name="report_subject").drop(bind, checkfirst=True)
