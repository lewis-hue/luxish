"""users: a photograph of their own

Revision ID: 0019_profile_photo
Revises: 0018_avatar_renders
Create Date: 2026-10-30

The profile screen has shown a picture since the avatar landed, and that
picture is the *drawn* figure — generated from appearance somebody answered
questions about. It is a good default and it is not a photograph of them.

This is the photograph. It is a media asset like any other, so it goes
through the same upload authorisation, the same storage mode and the same
delivery endpoint as a garment shot; nothing here is a second pipeline.

``ondelete="SET NULL"`` rather than CASCADE, deliberately: losing the media
row must blank the picture, never delete the account.

A nullable column rather than a separate table. One user has at most one
profile photo, it is replaced rather than versioned, and a join table for a
single optional foreign key is a row count nobody reads.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_profile_photo"
down_revision = "0018_avatar_renders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode so this works on SQLite, which cannot ALTER a table to add a
    # foreign key in place. The dev stack runs on SQLite and production on
    # Postgres; a migration that only applies to one of them is a migration
    # that gets discovered at the wrong time.
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("profile_photo_media_asset_id", sa.Uuid(as_uuid=True), nullable=True)
        )
        batch.create_foreign_key(
            "fk_users_profile_photo_media_asset",
            "media_assets",
            ["profile_photo_media_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_profile_photo_media_asset", type_="foreignkey")
        batch.drop_column("profile_photo_media_asset_id")
