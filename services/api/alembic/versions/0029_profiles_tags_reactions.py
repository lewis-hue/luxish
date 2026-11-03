"""public identity, hashtags, and reactions

Revision ID: 0029_profiles_tags_reactions
Revises: 0028_garment_shots
Create Date: 2026-10-31

Three tables that together turn this from an app with a catalogue into
an app with a community:

* `profiles` — the handle, bio and off-app links a stranger sees. Split
  from `users` because every column here crosses to other people, and a
  boundary you can see in the schema is one nobody forgets.
* `post_tags` — the hashtags Discover groups by. Their own rows rather
  than a caption parsed per query, so the feed's cost does not scale
  with how much people write.
* `post_reactions` — one reaction per person per post, so a tally cannot
  be run up by one enthusiast pressing five buttons.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_profiles_tags_reactions"
down_revision = "0028_garment_shots"
branch_labels = None
depends_on = None

BIO_STATES = ("pending_review", "published", "held")
REACTIONS = ("love", "fire", "stunning", "want", "clapping")


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("handle", sa.String(30), nullable=True),
        sa.Column("bio", sa.String(300), nullable=True),
        # What other people see. Differs from `bio` exactly while an edit
        # is in review, which is what stops it publishing unscreened.
        sa.Column("bio_public", sa.String(300), nullable=True),
        sa.Column(
            "bio_state",
            sa.Enum(*BIO_STATES, name="bio_state", native_enum=False),
            nullable=False,
            server_default="published",
        ),
        sa.Column("bio_note", sa.String(300), nullable=True),
        sa.Column("links", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("handle", name="uq_profiles_handle"),
    )
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"])

    op.create_table(
        "post_tags",
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tag", sa.String(40), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # "Every post with this tag, newest first", the only direction the
    # feed reads it in.
    op.create_index("ix_post_tags_tag_created", "post_tags", ["tag", "created_at"])

    op.create_table(
        "post_reactions",
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "kind",
            sa.Enum(*REACTIONS, name="post_reaction", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_post_reactions_post", "post_reactions", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_post_reactions_post", table_name="post_reactions")
    op.drop_table("post_reactions")
    op.drop_index("ix_post_tags_tag_created", table_name="post_tags")
    op.drop_table("post_tags")
    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.drop_table("profiles")
