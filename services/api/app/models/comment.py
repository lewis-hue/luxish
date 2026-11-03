"""Comments on a published fit.

**Free text in front of strangers, so it is screened like one.** A save is
an action and ships without review because there is nothing to moderate; a
comment is the opposite case and goes through the same fail-closed path a
caption and a bio already use. The author always sees what they wrote;
everyone else sees it only once the screen agrees. A screen that is
unavailable holds, never publishes.

**Seeded comments carry `screen_mode = "seed"`.** The same marker posts
use. A demo world is this repository's own fixture and paying for a
screening call per line of it buys nothing; a comment somebody actually
types is a different thing and is screened.

**Tombstoned, never erased.** Deleting a comment hides it and keeps the
row, like every other user-owned record here, so a thread does not silently
rewrite itself and a moderation record survives the delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

#: The longest a comment may be.
#:
#: Short on purpose. This is a remark under a photograph, not a post of its
#: own, and a field that invites an essay gets essays.
MAX_COMMENT = 500

COMMENT_STATES: tuple[str, ...] = (
    "pending_review",
    "published",
    "held",
)

comment_state_enum = named_enum("post_comment_state", *COMMENT_STATES)


class PostComment(Base, TimestampMixin):
    __tablename__ = "post_comments"
    __table_args__ = (
        # "This fit's comments, oldest first", which is the only order a
        # conversation reads in.
        sa.Index("ix_post_comments_post_created", "post_id", "created_at"),
        # "Everything this person wrote", for their own account page and
        # for removing it all when they leave.
        sa.Index("ix_post_comments_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    post_id: Mapped[uuid.UUID] = uuid_fk("posts.id")
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: What they wrote. Stored as typed; never rewritten by this service.
    body: Mapped[str] = mapped_column(sa.String(MAX_COMMENT), nullable=False)
    state: Mapped[str] = mapped_column(
        comment_state_enum,
        nullable=False,
        default="pending_review",
        server_default="pending_review",
    )
    #: How it was screened: the model, or `seed` for a fixture.
    screen_mode: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    #: Why it was held, in words shown to its author and nobody else.
    screen_note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    #: Set when a comment answers another. One level only: a thread that
    #: nests arbitrarily is a thread nobody can read on a phone, and the
    #: depth limit is enforced in the domain rather than hoped for.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("post_comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, index=True
    )


class CommentLike(Base):
    """Somebody liked a comment.

    The pair is the primary key, like a save and a follow: liking twice
    is the same state, so the database says so rather than every caller
    remembering to check. An index on the comment serves the count,
    which is the direction a thread reads it in.

    A like is an *action*, which is why it can ship where a reply
    cannot: there is no text to screen.
    """

    __tablename__ = "comment_likes"
    __table_args__ = (sa.Index("ix_comment_likes_comment", "comment_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    comment_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("post_comments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )


__all__ = ["COMMENT_STATES", "MAX_COMMENT", "CommentLike", "PostComment"]
