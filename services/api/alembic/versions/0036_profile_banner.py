"""A banner across the top of a profile.

The picture somebody puts at the top of their page is shown to everybody
who opens it, which makes it exactly as public as a caption and screened
the same way: held until the image screen agrees, and an unavailable
screen holds rather than publishes.

Its own media kind so a banner is never mistaken for a garment
photograph, a fit, or a picture of the person. It is decoration, and
nothing that reads clothes or faces should pick it up.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_profile_banner"
down_revision = "0035_report_guidelines"
branch_labels = None
depends_on = None

MEDIA = (
    "garment_photo",
    "outfit_photo",
    "inspiration",
    "avatar",
    "avatar_source",
    "garment_render",
    "garment_studio",
)
NEW_MEDIA = "profile_banner"


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

    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("banner_asset_id", sa.Uuid(), nullable=True))
        # The same three states a bio moves through, and for the same
        # reason: the owner sees what they chose, everybody else sees it
        # once the screen agrees.
        batch.add_column(
            sa.Column(
                "banner_state",
                sa.String(20),
                nullable=False,
                server_default="published",
            )
        )
        batch.add_column(sa.Column("banner_note", sa.String(300), nullable=True))
        # SET NULL rather than CASCADE: deleting the picture must not
        # delete the profile that was showing it.
        batch.create_foreign_key(
            "fk_profiles_banner_asset",
            "media_assets",
            ["banner_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_constraint("fk_profiles_banner_asset", type_="foreignkey")
        batch.drop_column("banner_note")
        batch.drop_column("banner_state")
        batch.drop_column("banner_asset_id")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text("DELETE FROM media_assets WHERE kind = 'profile_banner'")
        )
        return

    op.execute(sa.text("DELETE FROM media_assets WHERE kind = 'profile_banner'"))
    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*MEDIA, NEW_MEDIA, name="media_kind"),
            type_=sa.Enum(*MEDIA, name="media_kind"),
            existing_nullable=False,
        )
