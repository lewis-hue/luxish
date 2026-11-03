"""An avatar built from a photograph somebody uploaded of themselves.

Three vocabularies grow, and each boundary is deliberate.

``consent_kind`` gains ``likeness``. Sending a photograph of your face to a
model is a different question from "may the stylist read my wardrobe", and
one grant must not stand in for the other.

``media_kind`` gains ``avatar_source``: the uploaded photograph, kept apart
from every kind that means a garment so nothing downstream reads a picture
of a person as evidence of what they own.

``avatar_render_kind`` gains ``from_photo``, so a likeness is
distinguishable from a figure invented to a description.

``avatar_renders`` gains ``source_asset_id``, which is what makes the
photograph removable: deleting it has to find the renders drawn from it.
``SET NULL`` rather than ``CASCADE`` - removing the source photograph must
not silently destroy the pictures somebody kept.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_likeness_avatar"
down_revision = "0032_stylist_subject_and_intent"
branch_labels = None
depends_on = None

CONSENTS = (
    "publication",
    "ai_processing",
    "location_precise",
    "location_coarse",
    "analytics",
    "community_sharing",
)
NEW_CONSENT = "likeness"

MEDIA = (
    "garment_photo",
    "outfit_photo",
    "inspiration",
    "avatar",
    "garment_render",
    "garment_studio",
)
NEW_MEDIA = "avatar_source"

RENDERS = ("base", "try_on")
NEW_RENDER = "from_photo"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 12+ allows this inline; `IF NOT EXISTS` makes a re-run harmless.
        op.execute(
            f"ALTER TYPE consent_kind ADD VALUE IF NOT EXISTS '{NEW_CONSENT}'"
        )
        op.execute(f"ALTER TYPE media_kind ADD VALUE IF NOT EXISTS '{NEW_MEDIA}'")
        op.execute(
            "ALTER TYPE avatar_render_kind ADD VALUE IF NOT EXISTS "
            f"'{NEW_RENDER}'"
        )
    else:
        # SQLite: each enum is a CHECK constraint, so the column is
        # rewritten with the wider set.
        with op.batch_alter_table("consents") as batch:
            batch.alter_column(
                "kind",
                existing_type=sa.Enum(*CONSENTS, name="consent_kind"),
                type_=sa.Enum(*CONSENTS, NEW_CONSENT, name="consent_kind"),
                existing_nullable=False,
            )
        with op.batch_alter_table("media_assets") as batch:
            batch.alter_column(
                "kind",
                existing_type=sa.Enum(*MEDIA, name="media_kind"),
                type_=sa.Enum(*MEDIA, NEW_MEDIA, name="media_kind"),
                existing_nullable=False,
            )
        with op.batch_alter_table("avatar_renders") as batch:
            batch.alter_column(
                "kind",
                existing_type=sa.Enum(*RENDERS, name="avatar_render_kind"),
                type_=sa.Enum(*RENDERS, NEW_RENDER, name="avatar_render_kind"),
                existing_nullable=False,
            )

    with op.batch_alter_table("avatar_renders") as batch:
        batch.add_column(sa.Column("source_asset_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("note", sa.String(400), nullable=True))
        batch.create_foreign_key(
            "fk_avatar_renders_source_asset",
            "media_assets",
            ["source_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("avatar_renders") as batch:
        batch.drop_constraint("fk_avatar_renders_source_asset", type_="foreignkey")
        batch.drop_column("note")
        batch.drop_column("source_asset_id")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL cannot drop a value from an enum. Rows carrying the
        # new values go, so the type is at least consistent with the
        # narrower set that the application will enforce again.
        op.execute(sa.text("DELETE FROM consents WHERE kind = 'likeness'"))
        op.execute(
            sa.text("DELETE FROM avatar_renders WHERE kind = 'from_photo'")
        )
        op.execute(sa.text("DELETE FROM media_assets WHERE kind = 'avatar_source'"))
        return

    op.execute(sa.text("DELETE FROM consents WHERE kind = 'likeness'"))
    op.execute(sa.text("DELETE FROM avatar_renders WHERE kind = 'from_photo'"))
    op.execute(sa.text("DELETE FROM media_assets WHERE kind = 'avatar_source'"))
    with op.batch_alter_table("consents") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*CONSENTS, NEW_CONSENT, name="consent_kind"),
            type_=sa.Enum(*CONSENTS, name="consent_kind"),
            existing_nullable=False,
        )
    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*MEDIA, NEW_MEDIA, name="media_kind"),
            type_=sa.Enum(*MEDIA, name="media_kind"),
            existing_nullable=False,
        )
    with op.batch_alter_table("avatar_renders") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*RENDERS, NEW_RENDER, name="avatar_render_kind"),
            type_=sa.Enum(*RENDERS, name="avatar_render_kind"),
            existing_nullable=False,
        )
