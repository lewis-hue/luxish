"""piece_packshots - a garment drawn from its words, once, for everybody

Revision ID: 0056_piece_packshots
Revises: 0055_packshot_media_kind
Create Date: 2026-11-04

**The reported failure.** "How would baggy skater shorts with white
sneakers and a white t-shirt look on me?" answered: you do not own
those, here is where to buy them - and showed nothing. Every other
reply in that thread carries a figure wearing the look, composed on
the device from the pieces' own cut-outs. A cut-out only exists for a
garment somebody has photographed, so the one reply where seeing it
would have helped most was the only reply with no picture.

So a named piece nobody owns gets a plain packshot drawn from its
words, which is the same shape the composite already lays over the
figure.

**Keyed on the phrase, not on a person, and that is the whole
design.** "white sneakers" is the same request whoever asks it. The
first person to need one pays for one generation; everybody after
them gets a row lookup. A per-user table would have turned a
one-time cost into a cost per person per question, which is exactly
the pattern this release has been removing - the photorealistic
stylist render went for the same reason.

The unique index on ``phrase`` is load-bearing rather than hygienic:
two people asking at the same moment must end up sharing one row and
one drawing, and the database is the only thing that can arbitrate
that.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0056_piece_packshots"
down_revision = "0055_packshot_media_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "piece_packshots",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("phrase", sa.String(120), nullable=False),
        sa.Column("slot", sa.String(32), nullable=True),
        sa.Column(
            "state", sa.String(16), nullable=False, server_default="queued"
        ),
        sa.Column(
            "media_asset_id",
            sa.Uuid(),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Unique rather than merely indexed: see the note above. This is
    # what makes two simultaneous askers share one drawing.
    op.create_index(
        "uq_piece_packshots_phrase", "piece_packshots", ["phrase"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_piece_packshots_phrase", table_name="piece_packshots")
    op.drop_table("piece_packshots")
