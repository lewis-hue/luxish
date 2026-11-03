"""media kind: garment_render — a picture of a garment that is not a photograph

Revision ID: 0010_garment_render
Revises: 0009_wardrobe_media
Create Date: 2026-10-28

A garment can be visible in a photograph and still be impossible to cut out of
it. Something overlaps it, so the mask comes back as a fragment: a shirt with a
tote-shaped hole in it, trousers sliced in half by a desk. The honest options
are to show that fragment, to show nothing, or to render what the garment looks
like from what was read off it. We render.

That makes the stored picture a different *kind* of thing from everything else
in ``media_assets``, and the schema has to say so. A render is not evidence. It
must never be mistaken for the user's own photograph — not by a person looking
at their wardrobe, not by a future feature that treats stored media as proof of
what someone owns, and not by anyone reading the table directly. ``media_kind``
is a native enum on PostgreSQL, so a new member is a migration rather than a
convention someone can forget.

**Reversible, but only while it is safe to be.** PostgreSQL has no
``ALTER TYPE ... DROP VALUE``, so the downgrade rebuilds the type without the
new member. That is only sound while nothing is stored as ``garment_render``,
so it counts first and refuses if any row would be stranded. Reversing a
migration should never be the thing that silently destroys data, and a
downgrade that quietly rewrote real rows to some other kind would be exactly
that. Exactly one column uses this type, which is what makes the rebuild
tractable; the check below asserts that rather than assuming it.

Note on transactions: ``ALTER TYPE ... ADD VALUE`` could not run inside a
transaction block before PostgreSQL 12. The floor here is 16 (ADR-013), so it
runs inline, and ``IF NOT EXISTS`` makes re-running it harmless.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_garment_render"
down_revision = "0009_wardrobe_media"
branch_labels = None
depends_on = None

#: The value added to the ``media_kind`` enum.
RENDER_KIND = "garment_render"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(f"ALTER TYPE media_kind ADD VALUE IF NOT EXISTS '{RENDER_KIND}'")
        )
        return

    # SQLite renders a named enum as VARCHAR plus a CHECK constraint, and has
    # no ALTER for either. The test suite runs here and only needs the value to
    # be accepted; batch_alter_table rebuilds the table with the wider set.
    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(),
            type_=sa.Enum(
                "garment_photo",
                "outfit_photo",
                "inspiration",
                "avatar",
                RENDER_KIND,
                name="media_kind",
            ),
            existing_nullable=False,
        )


#: The members of ``media_kind`` before this revision.
PRIOR_KINDS = ("garment_photo", "outfit_photo", "inspiration", "avatar")


def downgrade() -> None:
    bind = op.get_bind()

    stranded = bind.execute(
        sa.text("SELECT count(*) FROM media_assets WHERE kind = :kind"),
        {"kind": RENDER_KIND},
    ).scalar_one()
    if stranded:
        raise RuntimeError(
            f"{stranded} media asset(s) are stored as {RENDER_KIND!r}. "
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
