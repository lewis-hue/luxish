"""studio: shots taken of a garment

Revision ID: 0028_garment_shots
Revises: 0027_post_saves
Create Date: 2026-10-31

One row per result. The treatment is a plain string rather than an enum
because the set of treatments is prompt wording, which changes far more
often than a schema should — and a row naming a treatment that has since
been reworded is still a true record of what was run.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

SHOT_STATES = ("queued", "running", "ready", "failed")

MEDIA_KINDS_BEFORE = (
    "garment_photo",
    "outfit_photo",
    "inspiration",
    "avatar",
    "garment_render",
)
MEDIA_KINDS_AFTER = (*MEDIA_KINDS_BEFORE, "garment_studio")

revision = "0028_garment_shots"
down_revision = "0027_post_saves"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The studio writes its results under their own media kind, so nothing
    # downstream can mistake a derivative for the photograph the owner took.
    # PostgreSQL grows an enum in place; SQLite stores it as a CHECK on a
    # VARCHAR, which `batch_alter_table` rewrites.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE media_kind ADD VALUE IF NOT EXISTS 'garment_studio'")
    else:
        with op.batch_alter_table("media_assets") as batch:
            batch.alter_column(
                "kind",
                existing_type=sa.Enum(*MEDIA_KINDS_BEFORE, name="media_kind", native_enum=False),
                type_=sa.Enum(*MEDIA_KINDS_AFTER, name="media_kind", native_enum=False),
                existing_nullable=False,
            )

    op.create_table(
        "garment_shots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        # Denormalised from the garment, so ownership can be checked and a
        # discard authorised without a join.
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The photograph being edited: the source of truth, because the
        # stylist can shoot a picture straight off somebody's phone and
        # that picture has no wardrobe row behind it.
        sa.Column(
            "source_asset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Optional provenance, set when the shot came from a wardrobe item.
        sa.Column(
            "garment_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("garments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("treatment", sa.String(32), nullable=False),
        sa.Column(
            "state",
            sa.Enum(*SHOT_STATES, name="garment_shot_state", native_enum=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "job_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Null until the edit comes back.
        sa.Column(
            "media_asset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
    # "Every shot of this garment, newest first", which is the only way
    # anything reads this table.
    op.create_index(
        "ix_garment_shots_garment_id_created_at",
        "garment_shots",
        ["garment_id", "created_at"],
    )
    op.create_index(
        "ix_garment_shots_user_id_created_at", "garment_shots", ["user_id", "created_at"]
    )
    op.create_index("ix_garment_shots_deleted_at", "garment_shots", ["deleted_at"])


def downgrade() -> None:
    # The enum is left wide. Narrowing it would fail on any row already
    # written as `garment_studio`, and a downgrade that can only run on an
    # unused database is not a downgrade.
    op.drop_index("ix_garment_shots_deleted_at", table_name="garment_shots")
    op.drop_index("ix_garment_shots_user_id_created_at", table_name="garment_shots")
    op.drop_index("ix_garment_shots_garment_id_created_at", table_name="garment_shots")
    op.drop_table("garment_shots")
