"""who the clothes are cut for, as a lean on retrieval

Revision ID: 0054_vision_presentation
Revises: 0053_post_vision
Create Date: 2026-11-03

**The reported failure.** Opening a menswear fit and being offered a
rail of dresses. That is not a weak recommendation, it is the wrong
answer to the question the tap asked, and the app had no way to do
better: `post_tags` carried `menswear` on 61 pins and `womenswear` on
none at all, so there was nothing to lean on.

So the vision reading gains an axis. It sits beside `subject` rather
than inside `facets`, for two reasons. `facets` are folded into
`vector`, and putting presentation there would let a strong colour
match quietly cancel it. And the two do different jobs: a facet nudges
a cosine, while this has to steer retrieval on its own.

**It is a lean, not a gate.** `GOES_UNDER` is a gate - a sofa may
never sit under a dress, full stop. This is softer on purpose:
somebody looking at menswear is mostly after more menswear and is not
served by a filter that hides an androgynous piece that would suit
them. `subject.leans_together` adds 0.18 for agreement and half that
when one side is androgynous, which a clearly better visual match can
still outweigh.

**It describes the garments, never the person.** "Masculine" means cut
and styled as menswear. Nothing here infers anybody's gender, and
`unspecified` is both the default and the honest answer for most pins:
a flat-lay of a scarf has no presentation.

Every row written before this column exists holds `unspecified`, which
scores zero rather than counting as a mismatch - not knowing is not a
reason to push something down. `scripts/backfill_post_vision.py` fills
them in when it is next run.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0054_vision_presentation"
down_revision = "0053_post_vision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "post_vision",
        sa.Column(
            "presentation",
            sa.String(length=16),
            nullable=False,
            server_default="unspecified",
        ),
    )


def downgrade() -> None:
    op.drop_column("post_vision", "presentation")
