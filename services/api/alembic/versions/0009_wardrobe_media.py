"""wardrobe media: favourites, cut-out asset, categorisation confidence

Revision ID: 0009_wardrobe_media
Revises: 0008_stylist
Create Date: 2026-10-27

Task 11 — the wardrobe media pipeline. Three columns on ``garments`` and two
indexes, each carrying one invariant into the schema:

* ``is_favourite`` is **user-stated truth**, in the same class as
  ``confirmed_attributes``. It is a column rather than a confirmed attribute
  because the stylist weights favourites on every retrieval, and that wants an
  indexed predicate rather than a JSON probe —
  ``ix_garments_user_id_is_favourite`` is that index.

* ``background_removed_asset_id`` points at the cut-out, which is a **new**
  ``media_assets`` row. §5 requires a usable original to survive when optional
  processing fails, so the cut-out never replaces anything: ``media_asset_id``
  keeps pointing at the photograph the user took. ``ON DELETE SET NULL``, so
  purging a cut-out can never cascade into the garment that referenced it.

* ``categorisation_confidence`` is deliberately separate from the existing
  ``inference_confidence``. That one is the run's overall confidence; this one is
  the confidence in the *category label*, which is what decides whether the
  ``category`` column is auto-filled or the user is asked. A CHECK constraint
  bounds it to [0, 1], matching the constraint already on
  ``inference_confidence``.

* ``uq_garments_user_id_media_asset_id`` is a **partial** unique index: one
  garment per uploaded asset per owner, exempting NULL assets and soft-deleted
  rows so a user can re-photograph a garment they deleted. This is what makes
  the bulk-create endpoint's per-item idempotency a schema property rather than
  a matter of caller diligence — the same reasoning as ``jobs.idempotency_key``.

No table is added, so this revision is a pure ``ALTER``. The foreign key and the
CHECK go through ``batch_alter_table`` because SQLite cannot ``ALTER`` either
one in; on PostgreSQL — the database that ships — batch mode issues plain
``ALTER TABLE`` statements and nothing is rebuilt.

**One SQLite-only cosmetic effect, recorded so it is not mistaken for a bug.**
Batch mode rebuilds the table on SQLite from reflection, and the metadata
naming convention is re-applied to the constraints it reflects, so the
pre-existing CHECK comes back named
``ck_garments_ck_garments_inference_confidence_range``. The constraint and its
semantics are intact; only the name on the unit-suite rehearsal database gains a
duplicated prefix. PostgreSQL is unaffected because no rebuild happens there.

**Chain note.** ``down_revision`` is ``0008_stylist`` (Task 8). If that revision
is not yet present this file will not resolve and
``tests/test_migrations.py::EXPECTED_ORDER`` needs both ``0008_stylist`` and
``0009_wardrobe_media`` appended; see the task report.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_wardrobe_media"
down_revision: str | None = "0008_stylist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FAVOURITE_INDEX = "ix_garments_user_id_is_favourite"
ASSET_UNIQUE_INDEX = "uq_garments_user_id_media_asset_id"
#: Short, because the metadata naming convention (``ck_%(table_name)s_%(constraint_name)s``)
#: supplies the prefix. Passing the prefixed name produces
#: ``ck_garments_ck_garments_…``.
CONFIDENCE_CHECK = "categorisation_confidence_range"
CUTOUT_FK = "fk_garments_background_removed_asset_id_media_assets"

#: Exempts NULL assets and soft-deleted rows. Identical text on both dialects,
#: which keeps the SQLite unit suite a faithful rehearsal of the Postgres one.
PARTIAL_WHERE = "media_asset_id IS NOT NULL AND deleted_at IS NULL"


def upgrade() -> None:
    op.add_column(
        "garments",
        sa.Column(
            "is_favourite",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "garments",
        sa.Column("background_removed_asset_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "garments", sa.Column("categorisation_confidence", sa.Float(), nullable=True)
    )

    # SQLite cannot ALTER in a foreign key or a CHECK, so both go through a
    # batch operation, which rebuilds the table there and is a plain ALTER on
    # PostgreSQL.
    with op.batch_alter_table("garments") as batch:
        batch.create_foreign_key(
            CUTOUT_FK,
            "media_assets",
            ["background_removed_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            CONFIDENCE_CHECK,
            "categorisation_confidence IS NULL OR "
            "(categorisation_confidence >= 0 AND categorisation_confidence <= 1)",
        )

    op.create_index(FAVOURITE_INDEX, "garments", ["user_id", "is_favourite"])
    op.create_index(
        ASSET_UNIQUE_INDEX,
        "garments",
        ["user_id", "media_asset_id"],
        unique=True,
        postgresql_where=sa.text(PARTIAL_WHERE),
        sqlite_where=sa.text(PARTIAL_WHERE),
    )


def downgrade() -> None:
    op.drop_index(ASSET_UNIQUE_INDEX, table_name="garments")
    op.drop_index(FAVOURITE_INDEX, table_name="garments")

    with op.batch_alter_table("garments") as batch:
        batch.drop_constraint(CONFIDENCE_CHECK, type_="check")
        batch.drop_constraint(CUTOUT_FK, type_="foreignkey")

    op.drop_column("garments", "categorisation_confidence")
    op.drop_column("garments", "background_removed_asset_id")
    op.drop_column("garments", "is_favourite")
