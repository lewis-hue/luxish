"""A picture attached to a direct message.

Its own media kind rather than reusing one: a kind is a boundary in
this schema, not a label. Nothing that scans for clothes may pick up
a photograph somebody sent to one person, and an id in a request is
re-validated against both its owner and its kind.

`SET NULL` on the asset: deleting the photograph must not delete the
message that was sent with it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_message_media"
down_revision = "0039_direct_messages"
branch_labels = None
depends_on = None

MEDIA = (
    "garment_photo",
    "outfit_photo",
    "inspiration",
    "avatar",
    "avatar_source",
    "profile_banner",
    "garment_render",
    "garment_studio",
)
NEW_MEDIA = "message_media"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TYPE media_kind ADD VALUE IF NOT EXISTS '{NEW_MEDIA}'")
    else:
        with op.batch_alter_table("media_assets") as batch:
            batch.alter_column(
                "kind",
                existing_type=sa.Enum(*MEDIA, name="media_kind"),
                type_=sa.Enum(*MEDIA, NEW_MEDIA, name="media_kind"),
                existing_nullable=False,
            )

    with op.batch_alter_table("direct_messages") as batch:
        batch.add_column(sa.Column("media_asset_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_direct_messages_media_asset",
            "media_assets",
            ["media_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("direct_messages") as batch:
        batch.drop_constraint("fk_direct_messages_media_asset", type_="foreignkey")
        batch.drop_column("media_asset_id")

    op.execute(sa.text("DELETE FROM media_assets WHERE kind = 'message_media'"))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return
    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*MEDIA, NEW_MEDIA, name="media_kind"),
            type_=sa.Enum(*MEDIA, name="media_kind"),
            existing_nullable=False,
        )
