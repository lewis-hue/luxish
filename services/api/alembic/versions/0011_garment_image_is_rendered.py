"""garments.image_is_rendered — say so when the picture is a drawing

Revision ID: 0011_garment_image_is_rendered
Revises: 0010_garment_render
Create Date: 2026-10-28

``media_assets.kind`` already distinguishes a render from a photograph, and
that is the authority. This column is a denormalisation of it onto the garment,
and it exists because of where the fact has to be *read*: the wardrobe grid
shows many garments at once and must badge the rendered ones, so without this
every list response needs a join, or the client needs a second request per
tile to learn what it is looking at.

The alternative considered was a join in ``GarmentRepository``. Rejected: it
changes the repository's return type from ``Garment`` to a row tuple
everywhere, for one boolean, and the places that would then have to care about
it are mostly places that do not.

``server_default='false'`` rather than nullable. Every garment that already
exists shows a photograph or a cut-out of one — none of them were drawn — so
there is no unknown state to represent, and a nullable boolean would invite a
caller to treat "not known" as "not rendered" without saying so.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_garment_image_is_rendered"
down_revision = "0010_garment_render"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "garments",
        sa.Column(
            "image_is_rendered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("garments", "image_is_rendered")
