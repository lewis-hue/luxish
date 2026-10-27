"""regional: versioned, provenanced style profiles

Revision ID: 0006_regional
Revises: 0004_ai
Create Date: 2026-10-26

Task 9. Two schema properties carry the invariants rather than leaving them to
application diligence:

* ``source_provenance`` and ``reviewer`` are NOT NULL **and** CHECK-constrained
  non-empty, so an unattributed profile cannot exist even if a validator were
  bypassed.
* The unique constraint is ``(geography_key, source_slug, version)`` — *not*
  ``(geography, occasion)``. Two reviewed sources may cover the same place and
  occasion with different advice, and both are kept; ``supersedes_id`` chains
  versions and ``retired_at`` retires one without deleting it.

There is no column for ethnicity, religion, income, or personal taste, and no
coordinate column: a place reaches this table as a *name* only.

Numbering follows the plan (Task 9 = 0006). Task 7's ``0004_ai`` has landed, so
this revision now follows it and ``0007_external`` follows this one: the chain
reads 0003 → 0004 → 0006 → 0007 with a single head. Task 8's ``0005_stylist``
is inserted between 0004 and 0006 when it lands.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_regional"
down_revision: str | None = "0004_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)

GRANULARITIES = ("city", "region", "country")


def _granularity() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*GRANULARITIES, name="regional_granularity", create_type=False)
    return sa.Enum(*GRANULARITIES, name="regional_granularity")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*GRANULARITIES, name="regional_granularity").create(bind, checkfirst=True)

    op.create_table(
        "regional_style_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("geography", sa.String(length=160), nullable=False),
        sa.Column("geography_key", sa.String(length=160), nullable=False),
        sa.Column("country_key", sa.String(length=80), nullable=True),
        sa.Column("granularity", _granularity(), nullable=False),
        sa.Column("aliases", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("occasions", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("seasonality", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("styling_examples", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("variants", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("source_slug", sa.String(length=80), nullable=False),
        sa.Column("source_provenance", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("retired_at", TS, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["regional_style_profiles.id"],
            name="fk_regional_style_profiles_supersedes_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_regional_style_profiles"),
        sa.UniqueConstraint(
            "geography_key",
            "source_slug",
            "version",
            name="uq_regional_style_profiles_geography_key_source_slug_version",
        ),
        sa.CheckConstraint(
            "length(trim(source_provenance)) > 0",
            name="ck_regional_style_profiles_provenance_present",
        ),
        sa.CheckConstraint(
            "length(trim(reviewer)) > 0",
            name="ck_regional_style_profiles_reviewer_present",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_regional_style_profiles_confidence_range",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_regional_style_profiles_version_positive",
        ),
    )
    op.create_index(
        "ix_regional_style_profiles_geography_key",
        "regional_style_profiles",
        ["geography_key"],
    )
    op.create_index(
        "ix_regional_style_profiles_country_key",
        "regional_style_profiles",
        ["country_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_regional_style_profiles_country_key", table_name="regional_style_profiles"
    )
    op.drop_index(
        "ix_regional_style_profiles_geography_key", table_name="regional_style_profiles"
    )
    op.drop_table("regional_style_profiles")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="regional_granularity").drop(bind, checkfirst=True)
