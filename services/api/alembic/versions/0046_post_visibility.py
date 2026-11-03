"""an author can take their own fit off the board

Revision ID: 0046_post_visibility
Revises: 0045_push_notifications
Create Date: 2026-11-01

One column, and it is deliberately not `state`.

`state` is the screen's verdict and belongs to us: pending, published,
held, removed. `visibility` is the author's own decision about who a
fit is for. Folding the second into the first would mean taking a fit
private looked exactly like having it held - the same word in the same
column, with no way for the app to tell somebody which of the two had
happened to their photograph - and a later moderation write could
silently undo a choice that was never ours to make.

Everything already up is `public`, which is what it has been all
along: posting a fit in this app has always been the act of showing
it to people. The default stays `public` for the same reason - a fit
that arrived private would be a draft, and there are no drafts here.

The gate itself lives in one place, `app.models.posts.shown_to_strangers`,
rather than being written out beside every `state == "published"`. That
predicate was hand-copied at twelve call sites across discover, search,
boards, member profiles, the following feed and notifications before
this revision, and adding a third condition to twelve places is how one
gets missed - the first draft of this change did miss one, and a fit
that had just been taken private went straight back into its author's
followers' feed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_post_visibility"
down_revision = "0045_push_notifications"
branch_labels = None
depends_on = None

VISIBILITIES = ("public", "private")


def _enum(name: str, values: tuple[str, ...], bind) -> sa.types.TypeEngine:
    """The enum, created up front on Postgres and inline on SQLite.

    `create_type=False` for the same reason every other revision here
    does it: `add_column` would otherwise emit a second CREATE TYPE for
    a type that already exists, which fails and leaves the revision
    half-applied.
    """
    if bind.dialect.name == "postgresql":
        sa.Enum(*values, name=name).create(bind, checkfirst=True)
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    bind = op.get_bind()
    visibility = _enum("post_visibility", VISIBILITIES, bind)

    op.add_column(
        "posts",
        sa.Column(
            "visibility",
            visibility,
            nullable=False,
            server_default="public",
        ),
    )
    # "Everything of mine, newest first" is what the profile reads, and
    # "is this one still shown" is what every public query now asks on
    # top of the state it already filtered by.
    op.create_index(
        "ix_posts_visibility_state", "posts", ["visibility", "state"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_posts_visibility_state", table_name="posts")
    op.drop_column("posts", "visibility")
    if bind.dialect.name == "postgresql":
        sa.Enum(*VISIBILITIES, name="post_visibility").drop(bind, checkfirst=True)
