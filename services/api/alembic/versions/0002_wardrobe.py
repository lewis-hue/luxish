"""wardrobe: media assets, derivatives, garments, collections

Revision ID: 0002_wardrobe
Revises: 0001_core
Create Date: 2026-10-26

Task 5. ``garments.confirmed_attributes`` and ``garments.inferred_attributes``
are separate JSONB columns on purpose: there is no column a worker could use to
overwrite a user's correction. ``media_derivatives`` is created here with the
rest of the media schema; Task 6's worker is its only writer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_wardrobe"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)

MEDIA_KINDS = ("garment_photo", "outfit_photo", "inspiration", "avatar")
MEDIA_STATUSES = ("pending_upload", "uploaded", "processing", "ready", "failed")
DERIVATIVE_KINDS = ("thumbnail", "display", "mask", "preview")
AVAILABILITY = ("available", "laundry", "unavailable", "archived")

ENUMS = {
    "media_kind": MEDIA_KINDS,
    "media_asset_status": MEDIA_STATUSES,
    "media_derivative_kind": DERIVATIVE_KINDS,
    "garment_availability": AVAILABILITY,
}


def _enum(name: str) -> sa.types.TypeEngine:
    values = ENUMS[name]
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def _create_enums() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)


def _drop_enums() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)


def upgrade() -> None:
    _create_enums()

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", _enum("media_kind"), nullable=False),
        sa.Column(
            "status",
            _enum("media_asset_status"),
            server_default="pending_upload",
            nullable=False,
        ),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("max_bytes", sa.BigInteger(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "publication_consent", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("upload_authorized_until", TS, nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_media_assets_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
    )
    op.create_index("ix_media_assets_user_id", "media_assets", ["user_id"])
    op.create_index("ix_media_assets_deleted_at", "media_assets", ["deleted_at"])

    op.create_table(
        "media_derivatives",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", _enum("media_derivative_kind"), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["media_assets.id"],
            name="fk_media_derivatives_asset_id_media_assets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_derivatives"),
        sa.UniqueConstraint(
            "asset_id",
            "kind",
            "source_version",
            name="uq_media_derivatives_asset_id_kind_source_version",
        ),
    )
    op.create_index("ix_media_derivatives_asset_id", "media_derivatives", ["asset_id"])

    op.create_table(
        "garments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column(
            "availability", _enum("garment_availability"), server_default="available", nullable=False
        ),
        sa.Column("confirmed_attributes", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("inferred_attributes", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("inference_confidence", sa.Float(), nullable=True),
        sa.Column("inference_version", sa.String(length=64), nullable=True),
        sa.Column("inferred_at", TS, nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "inference_confidence IS NULL OR "
            "(inference_confidence >= 0 AND inference_confidence <= 1)",
            name="ck_garments_inference_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_garments_media_asset_id_media_assets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_garments_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_garments"),
    )
    op.create_index("ix_garments_media_asset_id", "garments", ["media_asset_id"])
    op.create_index("ix_garments_deleted_at", "garments", ["deleted_at"])
    # Every wardrobe read is owner-scoped, so every index leads with user_id.
    op.create_index("ix_garments_user_id_created_at", "garments", ["user_id", "created_at"])
    op.create_index("ix_garments_user_id_category", "garments", ["user_id", "category"])
    op.create_index("ix_garments_user_id_availability", "garments", ["user_id", "availability"])

    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_collections_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_collections"),
        sa.UniqueConstraint("user_id", "name", name="uq_collections_user_id_name"),
    )
    op.create_index("ix_collections_user_id", "collections", ["user_id"])

    op.create_table(
        "collection_garments",
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("garment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name="fk_collection_garments_collection_id_collections",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["garment_id"],
            ["garments.id"],
            name="fk_collection_garments_garment_id_garments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("collection_id", "garment_id", name="pk_collection_garments"),
    )


def downgrade() -> None:
    op.drop_table("collection_garments")
    op.drop_index("ix_collections_user_id", table_name="collections")
    op.drop_table("collections")
    op.drop_index("ix_garments_user_id_availability", table_name="garments")
    op.drop_index("ix_garments_user_id_category", table_name="garments")
    op.drop_index("ix_garments_user_id_created_at", table_name="garments")
    op.drop_index("ix_garments_deleted_at", table_name="garments")
    op.drop_index("ix_garments_media_asset_id", table_name="garments")
    op.drop_table("garments")
    op.drop_index("ix_media_derivatives_asset_id", table_name="media_derivatives")
    op.drop_table("media_derivatives")
    op.drop_index("ix_media_assets_deleted_at", table_name="media_assets")
    op.drop_index("ix_media_assets_user_id", table_name="media_assets")
    op.drop_table("media_assets")
    _drop_enums()
