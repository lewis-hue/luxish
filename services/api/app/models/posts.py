"""Fits: the first user-authored thing a stranger can see.

**Nothing publishes optimistically.** A post is born ``pending_review``,
and only the screening job moves it to ``published`` — or to ``held``,
which is also where it lands when screening is unavailable, because the
roadmap's rule is that a failure holds the post. ``removed`` is a
moderator's verdict; the author's own deletion is the usual tombstone.

**What a stranger can read is bounded by construction.** The caption is
the only free text, it is capped, and it is screened before anyone else
sees it. Tagged garments expose their taxonomy facts (category, colour),
never the owner-written name. Products come from the curated catalogue.
The look reference is a taxonomy id. So the review surface is exactly:
one caption and the photographs.

``screen_mode`` records *how* a post got its verdict (`model`, `seed`,
`unavailable`), because a feed where fixtures are indistinguishable from
screened content would break the capability-label rule one table down
from where anyone would look for it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

POST_STATES: tuple[str, ...] = ("pending_review", "published", "held", "removed")

post_state_enum = named_enum("post_state", *POST_STATES)

#: Who the author meant this for.
#:
#: **Separate from `state`, deliberately.** `state` is the screen's
#: verdict and belongs to us; this is the author's own decision and
#: belongs to them. Folding one into the other would mean taking a fit
#: private looked identical to having it held, and a moderator's
#: action could silently undo somebody's choice.
POST_VISIBILITIES: tuple[str, ...] = ("public", "private")

post_visibility_enum = named_enum("post_visibility", *POST_VISIBILITIES)

#: The most photographs one fit can carry, and the most tagged items.
MAX_POST_MEDIA = 4
MAX_POST_ITEMS = 6
MAX_CAPTION = 300


class Post(Base, TimestampMixin):
    __tablename__ = "posts"
    __table_args__ = (
        sa.Index("ix_posts_user_id_state", "user_id", "state"),
        sa.Index("ix_posts_published_at", "published_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    caption: Mapped[str | None] = mapped_column(sa.String(MAX_CAPTION), nullable=True)
    #: From the taste occasions vocabulary, validated on the way in.
    occasion: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    #: A collection id from the app's taxonomy, or nothing.
    state: Mapped[str] = mapped_column(
        post_state_enum,
        nullable=False,
        default="pending_review",
        server_default="pending_review",
    )
    #: The author's own call on who this is for. `public` by default,
    #: because posting a fit is already the act of showing it to
    #: people - a fit that arrived private would be a draft, and this
    #: app has no drafts.
    visibility: Mapped[str] = mapped_column(
        post_visibility_enum,
        nullable=False,
        default="public",
        server_default="public",
    )
    screen_mode: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    #: Why a post was held, in words shown to its author and nobody else.
    screen_note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, index=True
    )


class PostMedia(Base):
    __tablename__ = "post_media"

    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )


class PostItem(Base):
    """One tagged item: the poster's own garment, or a catalogue product.

    Both references are ``SET NULL`` on delete, so a purged garment leaves
    a visible gap in the tag row rather than silently shrinking a post
    somebody published. A row with both sides null renders as "an item
    that is gone", which is the truth.
    """

    __tablename__ = "post_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    post_id: Mapped[uuid.UUID] = uuid_fk("posts.id")
    garment_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("garments.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("shop_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )


class PostSave(Base):
    """Somebody kept a fit.

    The pair is the primary key, like a follow and a block: keeping a fit
    twice is the same state, so the database says so rather than the
    caller remembering to check. An index on the post serves the count,
    which is the direction every card reads it in.

    A save is an *action*, which is why it can ship where a comment
    cannot: there is no text to moderate.
    """

    __tablename__ = "post_saves"
    __table_args__ = (sa.Index("ix_post_saves_post", "post_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )

class PostHide(Base):
    """Somebody does not want to see this fit again.

    The pair is the primary key, like a save and a follow: hiding
    twice is the same state, so the database enforces it rather than
    every caller remembering to.

    Far smaller than a block, deliberately. Not wanting one photograph
    on your board is not the same as not wanting its author anywhere,
    and offering only the larger tool makes people reach for it.
    """

    __tablename__ = "post_hides"
    __table_args__ = (sa.Index("ix_post_hides_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )


def shown_to_strangers() -> sa.ColumnElement[bool]:
    """The rows anybody other than the author may be shown.

    **One predicate, used everywhere, because the alternative lost.**
    `state == "published"` and `deleted_at IS NULL` were written out
    by hand at twelve call sites across discover, search, boards,
    member profiles, the following feed and notifications. Adding a
    third condition to twelve places is how one of them gets missed -
    and the first draft of this change did miss one, which put a fit
    that had just been taken private straight back into its author's
    followers' feed.

    The author's own view does not use this - `posts.mine` is the one
    query that is meant to see everything, which is the whole point of
    there being a private setting at all. Two more opt out and say so
    where they are: opening a single fit, and reading its photograph.
    Both let the author through to their own private fit, because one
    the profile still lists has to be openable by the person who
    posted it.
    """
    return sa.and_(
        Post.state == "published",
        Post.deleted_at.is_(None),
        Post.visibility == "public",
    )
