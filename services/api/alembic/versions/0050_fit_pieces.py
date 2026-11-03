"""each garment in a posted fit, cut out and kept

Revision ID: 0050_fit_pieces
Revises: 0049_plan_reference_post
Create Date: 2026-11-02

**What this is for.** Trying a fit on reads the photograph, writes a
sentence describing the clothes, and pays an image model to draw
somebody wearing that sentence. The result looks *like* the outfit;
it is not the outfit, because the model is reconstructing from a
description. A logo moves, a pattern becomes a different pattern.

What people mean by "try it on" is the clothes in the picture. So
each garment is cut out of the photograph it is actually in, and the
free stylised figure wears the cut-outs directly - nothing is
redrawn, so nothing drifts. The paid photoreal render stays where it
is, as the thing somebody asks for when they want it.

**A table rather than ids in the description's JSON, and that is the
whole reason this revision exists.** The `pieces` column is already
free-form JSON and an asset id would have fitted in it. But media
readability in this service is decided by a live join - the gate
asks "does a post that is published *right now* carry this asset",
precisely so there is no flag anywhere to forget to clear. An id
that only exists inside a JSON blob cannot be joined, so the gate
would have had to scan JSON or, far more likely, the pieces would
have been let through on a flag of their own. An id nobody can join
is an id nobody checks.

Cascades on the post, because a piece is meaningless without the fit
it was cut from, and on the asset, because the row describes bytes
that no longer exist once the asset is gone.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050_fit_pieces"
down_revision = "0049_plan_reference_post"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_description_pieces",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_asset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        #: Where it sits in the outfit, matching the described order.
        sa.Column("position", sa.Integer(), nullable=False),
        #: Taxonomy facts, copied from the description so a client can
        #: label a cut-out without reading the JSON beside it.
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("colour", sa.String(60), nullable=True),
        sa.Column("category", sa.String(60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # One row per piece per post, so a re-run replaces rather than
        # doubles.
        sa.UniqueConstraint(
            "post_id", "position", name="uq_post_description_pieces_post_position"
        ),
    )
    # The read is "the pieces of this fit", in order.
    op.create_index(
        "ix_post_description_pieces_post",
        "post_description_pieces",
        ["post_id", "position"],
    )
    # And the gate's read is "which fit is this asset a piece of".
    op.create_index(
        "ix_post_description_pieces_asset",
        "post_description_pieces",
        ["media_asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_post_description_pieces_asset", "post_description_pieces"
    )
    op.drop_index("ix_post_description_pieces_post", "post_description_pieces")
    op.drop_table("post_description_pieces")
