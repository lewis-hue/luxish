"""what a photograph is of, read off the photograph

Revision ID: 0053_post_vision
Revises: 0052_account_exports
Create Date: 2026-11-03

**The signal an author cannot write.**

A boucle bed was posted captioned "Wedding guest, not upstaging
anybody" and tagged `#occasion #party #weddingguest`. Every
relatedness signal in the app read those tags and obeyed them, so a
shelf of women's eveningwear appeared under a photograph of a couch.
Nothing was broken: the ranking was perfect on a label that lied.

Two signals already existed and neither was enough. Hashtags are a
claim typed once by one person. Board placement is the crowd's
opinion and is better, but it needs somebody to have saved the pin
first, so it cannot help a photograph posted five minutes ago - which
is exactly when a mislabelled pin does its damage.

This table holds the third: what the vision model sees when it looks
at the picture.

**Why a vocabulary rather than a dense embedding.** The vendor has no
embeddings model and no embeddings endpoint - re-verified against the
live API today, where `POST /v1/embeddings` is a 404 on every model in
the catalogue, which is what ADR-004 recorded in October. What it does
have is a vision model with structured output. So `subject` and
`facets` come from a closed list the model fills in, and `vector` is
built from them.

`subject` is the part that earns the table. It is a hard category, and
a hard category can gate - which a cosine cannot. A cream boucle sofa
and a cream knit dress are genuinely close in any visual space and
must still never sit under one another.

`model` and `prompt_version` are on the row so a better embedder -
CLIP, Vertex, whatever ADR-004's cost review eventually picks - can be
rolled in one post at a time rather than requiring a flag day.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0053_post_vision"
down_revision = "0052_account_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_vision",
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.Uuid(as_uuid=True),
            # SET NULL, not CASCADE: a reshaped cover replaces the
            # asset, and losing the reading with it would make every
            # rotated photograph un-rankable until it was read again.
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(24), nullable=False),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default="1.0"
        ),
        sa.Column("facets", sa.JSON(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(160), nullable=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Retrieval asks "every pin of this subject", so that is the index.
    op.create_index("ix_post_vision_subject", "post_vision", ["subject"])


def downgrade() -> None:
    op.drop_index("ix_post_vision_subject", table_name="post_vision")
    op.drop_table("post_vision")
