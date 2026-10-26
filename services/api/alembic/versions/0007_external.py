"""external: social link references with attribution

Revision ID: 0007_external
Revises: 0006_regional
Create Date: 2026-10-26

Task 10 (ADR-009). A reference is a canonical URL, a platform, an author handle
when the URL carries one, and when the user handed it to us. There is no column
for media bytes, because no code downloads platform-hosted media;
``media_downloaded`` is a queryable assertion of that.

Numbering follows the plan, so this revision stays last and each earlier task's
migration is inserted ahead of it as it lands: the chain currently reads
0003 → 0004_ai → 0006_regional → 0007_external, with 0005 (stylist) reserved
for Task 8.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_external"
down_revision: str | None = "0006_regional"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)

SOCIAL_PLATFORMS = ("instagram", "tiktok", "pinterest", "youtube", "other")


def _platform() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*SOCIAL_PLATFORMS, name="social_platform", create_type=False)
    return sa.Enum(*SOCIAL_PLATFORMS, name="social_platform")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*SOCIAL_PLATFORMS, name="social_platform").create(bind, checkfirst=True)

    op.create_table(
        "external_references",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("platform", _platform(), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("submitted_url", sa.String(length=2048), nullable=False),
        sa.Column("author_handle", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("observed_at", TS, nullable=False),
        sa.Column("capability_snapshot", JSONB, nullable=False),
        sa.Column(
            "media_downloaded", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_external_references_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_external_references"),
        sa.UniqueConstraint(
            "user_id", "canonical_url", name="uq_external_references_user_id_canonical_url"
        ),
    )
    op.create_index("ix_external_references_user_id", "external_references", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_external_references_user_id", table_name="external_references")
    op.drop_table("external_references")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="social_platform").drop(bind, checkfirst=True)
