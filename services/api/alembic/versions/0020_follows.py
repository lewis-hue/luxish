"""community: a follow graph

Revision ID: 0020_follows
Revises: 0019_profile_photo
Create Date: 2026-10-30

The Community tab has shown trending looks and nothing else, because every
other thing a social tab normally does is user-generated content and this
codebase has no moderation pipeline. A follow graph is the exception: it
carries no text, no images and nothing a person authored. It is two user ids
and a timestamp.

What it unlocks is a feed built entirely from *curated* looks — "three people
you follow saved this" — where every noun on screen came from the app's own
taxonomy rather than from a stranger. That is shippable today. Posting,
comments and messages are not, and this migration deliberately adds nothing
that would make them look closer than they are.

The primary key is the pair. A follow is a fact about two people that is
either true or not; a surrogate id would permit the same pair twice and make
"am I following them" a count rather than a lookup.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_follows"
down_revision = "0019_profile_photo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "follows",
        sa.Column(
            "follower_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "followee_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Enforced in the database as well as the domain. Following yourself
        # is not a harmless oddity: it puts your own saves in your own feed,
        # which makes the feed look populated when nobody is actually there.
        sa.CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
    )
    # "Who follows this person" — the direction the follower *count* is read
    # in. The primary key already serves "who does this person follow".
    op.create_index("ix_follows_followee", "follows", ["followee_id"])


def downgrade() -> None:
    op.drop_index("ix_follows_followee", table_name="follows")
    op.drop_table("follows")
