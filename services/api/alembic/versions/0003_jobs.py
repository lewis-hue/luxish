"""jobs: the durable queue and deletion tombstones

Revision ID: 0003_jobs
Revises: 0002_wardrobe
Create Date: 2026-10-26

Task 6. ``jobs.idempotency_key`` is unique so a retried enqueue is one job by
schema rather than by diligence, and ``tombstones.asset_id`` carries **no
foreign key** to ``media_assets`` — a tombstone has to outlive the row it
describes (ADR-012).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_jobs"
down_revision: str | None = "0002_wardrobe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)

JOB_STATES = ("queued", "running", "succeeded", "failed", "dead_letter")


def _job_state() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*JOB_STATES, name="job_state", create_type=False)
    return sa.Enum(*JOB_STATES, name="job_state")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*JOB_STATES, name="job_state").create(bind, checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("state", _job_state(), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("progress", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", TS, nullable=False),
        sa.Column("locked_at", TS, nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_jobs_progress_range"),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    # The claim query's access path: ready work of a given kind, oldest first.
    op.create_index(
        "ix_jobs_state_kind_available_at", "jobs", ["state", "kind", "available_at"]
    )

    op.create_table(
        "tombstones",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        # Deliberately not a foreign key: it must survive the asset row.
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("asset_version", sa.Integer(), nullable=True),
        sa.Column("deleted_at", TS, nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("purged_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tombstones"),
        sa.UniqueConstraint("asset_id", name="uq_tombstones_asset_id"),
    )


def downgrade() -> None:
    op.drop_table("tombstones")
    op.drop_index("ix_jobs_state_kind_available_at", table_name="jobs")
    op.drop_table("jobs")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="job_state").drop(bind, checkfirst=True)
