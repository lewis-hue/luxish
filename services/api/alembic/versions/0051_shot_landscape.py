"""a studio shot can be asked for wide

Revision ID: 0051_shot_landscape
Revises: 0050_fit_pieces
Create Date: 2026-11-02

**The exception to the app being upright everywhere.**

Every picture this app draws sits in one upright shell, and the two
treatments that photograph garments lying flat - packshot and cutout
- are forced into it, because a flat-lay comes back wide and was
otherwise the only card in the feed on its side.

That is right for the feed and wrong as an absolute. The studio is
the tool half of this product: somebody making a banner, a header or
a wide catalogue image has a reason to want the frame they asked
for, and forcing it upright makes the tool unable to produce the
thing they came for. So the rule is the default and this is the
opt-out, stated per shot because it is a property of the picture
being made rather than a setting on the account.

Nothing is lost by allowing it. A landscape picture posted to the
feed is stood upright by `post.shape` on its way in, so choosing
wide here cannot put a sideways card on anybody's board - it just
means the file somebody downloads is the shape they asked for.

Not null with a default of false: every shot that already exists was
made under the upright rule, and a null would make "nobody asked"
indistinguishable from "asked for upright".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_shot_landscape"
down_revision = "0050_fit_pieces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "garment_shots",
        sa.Column(
            "landscape",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("garment_shots", "landscape")
