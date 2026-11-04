"""media kind: garment_packshot - the catalogue shot a wardrobe piece gets

Revision ID: 0055_packshot_media_kind
Revises: 0054_vision_presentation
Create Date: 2026-11-04

**The reported failure.** A wardrobe of black blobs. A garment is
added as a phone photograph - on a bed, half in shadow, at an angle -
and the only thing standing between that and the tile was background
removal, which is segmentation: it finds the garment's pixels and
drops the rest. On a dark garment against a dark surface there is no
edge to find, so a pair of black socks cut out as a silhouette, and a
white tee photographed on a sofa stayed a white tee on a sofa.

So the intake pipeline gains a last step: an **edit of the owner's own
photograph** that re-stages the garment the way a shop photographs
stock - laid flat, squared to the camera, evenly lit on a plain
ground. The weave, the print, the colour and the wear survive, because
they are in the source pixels.

**Why that needs a new member rather than reusing one.** The result
lands in ``background_removed_asset_id``, which is also where the
plain cut-out lands, so the only way to tell "already shot" from "has
a cut-out we are here to improve on" is the asset's kind. It cannot
borrow ``garment_studio`` either: those are shots somebody asked for
on the Studio screen and may delete, and deleting one must not take
the wardrobe's picture with it. And it must not borrow
``garment_render``, which means "a drawing of a garment like yours" -
a packshot is the opposite claim, and the badge the client shows for
a render would be a lie about provenance.

**Reversible, but only while it is safe to be.** PostgreSQL has no
``ALTER TYPE ... DROP VALUE``, so the downgrade rebuilds the type
without the new member - sound only while nothing is stored as one.
It counts first and refuses rather than stranding or silently
re-kinding real rows. This follows ``0010_garment_render``, which
established the pattern and the reasoning; see it for the note on
``ALTER TYPE`` inside a transaction (safe from PostgreSQL 12, and the
floor here is 16 per ADR-013).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0055_packshot_media_kind"
down_revision = "0054_vision_presentation"
branch_labels = None
depends_on = None

#: The value added to the ``media_kind`` enum.
PACKSHOT_KIND = "garment_packshot"

#: The members of ``media_kind`` before this revision.
PRIOR_KINDS = (
    "garment_photo",
    "outfit_photo",
    "inspiration",
    "avatar",
    "avatar_source",
    "profile_banner",
    "garment_render",
    "garment_studio",
    "message_media",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"ALTER TYPE media_kind ADD VALUE IF NOT EXISTS '{PACKSHOT_KIND}'"
            )
        )
        return

    # SQLite renders a named enum as VARCHAR plus a CHECK constraint and has
    # no ALTER for either, so the table is rebuilt with the wider set.
    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(),
            type_=sa.Enum(*PRIOR_KINDS, PACKSHOT_KIND, name="media_kind"),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    stranded = bind.execute(
        sa.text("SELECT count(*) FROM media_assets WHERE kind = :kind"),
        {"kind": PACKSHOT_KIND},
    ).scalar_one()
    if stranded:
        raise RuntimeError(
            f"{stranded} media asset(s) are stored as {PACKSHOT_KIND!r}. "
            "Reversing this migration would have to invent another kind for "
            "them or delete them, and neither is a decision a downgrade "
            "should make silently. Remove or re-kind those rows first."
        )

    if bind.dialect.name == "postgresql":
        used_by = bind.execute(
            sa.text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE udt_name = 'media_kind'"
            )
        ).scalar_one()
        if used_by != 1:
            raise RuntimeError(
                f"media_kind is used by {used_by} columns, not 1. The rebuild "
                "below would miss the others; widen it deliberately rather "
                "than letting it run against an assumption that has changed."
            )
        members = ", ".join(f"'{kind}'" for kind in PRIOR_KINDS)
        op.execute(sa.text("ALTER TYPE media_kind RENAME TO media_kind_superseded"))
        op.execute(sa.text(f"CREATE TYPE media_kind AS ENUM ({members})"))
        op.execute(
            sa.text(
                "ALTER TABLE media_assets ALTER COLUMN kind TYPE media_kind "
                "USING kind::text::media_kind"
            )
        )
        op.execute(sa.text("DROP TYPE media_kind_superseded"))
        return

    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(),
            type_=sa.Enum(*PRIOR_KINDS, name="media_kind"),
            existing_nullable=False,
        )
