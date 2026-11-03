"""Public identity: the handle, the bio, and the links off this app.

**A handle is not a display name.** The display name is whatever somebody
types; the handle is the stable, unique, lowercase thing other people
address them by and that a URL could one day contain. Keeping them apart
means changing how your name is spelled does not break anybody's link to
you.

**The bio is free text that strangers read, so it is screened.** Same
doctrine as a post caption: it is held until the screen approves it, and
an unavailable screen holds rather than publishes. The difference is
what happens meanwhile — a held bio simply does not show, where a held
post does not exist for anybody else at all.

**Links off the app are handles, not URLs.** Somebody pasting a URL can
paste any URL, which is an open redirect dressed as a profile field.
Storing `tiktok` + `iillegalsaac` and building the address ourselves
means the only place a link can point is the platform it claims to be.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_pk

#: Lowercase, digits, underscore and dot; 3 to 30. The shape every
#: platform this app links to already uses, so a handle somebody picks
#: here is one they can plausibly hold elsewhere.
HANDLE_PATTERN = re.compile(r"^[a-z0-9._]{3,30}$")

MAX_BIO = 300

#: Platforms whose address we can build from a handle. Adding one is a
#: deliberate act: each entry is a promise about where the link goes.
SOCIAL_PLATFORMS: dict[str, str] = {
    "tiktok": "https://www.tiktok.com/@{handle}",
    "instagram": "https://www.instagram.com/{handle}",
    "youtube": "https://www.youtube.com/@{handle}",
    "pinterest": "https://www.pinterest.com/{handle}",
    "x": "https://x.com/{handle}",
    #: Somebody's own site. The "handle" is a bare domain, and
    #: `clean_links` already refuses anything containing `/?#&: ` - so
    #: this can address a host and never a path, which is what keeps a
    #: profile field from becoming an open redirect.
    "website": "https://{handle}",
}

#: Same states a post moves through, for the same reason.
BIO_STATES: tuple[str, ...] = ("pending_review", "published", "held")

bio_state_enum = named_enum("bio_state", *BIO_STATES)


class Profile(Base, TimestampMixin):
    """One row per account, created the first time anything is set.

    Separate from `users` rather than more columns on it: this is the
    *public* half of an identity, every field here crosses to strangers,
    and keeping it apart makes that boundary something you can see in the
    schema rather than something you have to remember.
    """

    __tablename__ = "profiles"
    __table_args__ = (
        # Case-insensitive uniqueness is enforced by storing lowercase and
        # validating the shape, which is simpler than a functional index
        # and works identically on both engines.
        sa.UniqueConstraint("handle", name="uq_profiles_handle"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Null until chosen. A profile without one is reachable by id and
    #: simply has no `@name` to show.
    handle: Mapped[str | None] = mapped_column(sa.String(30), nullable=True)

    bio: Mapped[str | None] = mapped_column(sa.String(MAX_BIO), nullable=True)
    #: The bio as last approved. Shown to other people; `bio` is what the
    #: owner last typed. They differ exactly while something is in review,
    #: which is what stops an edit from publishing before it is screened.
    bio_public: Mapped[str | None] = mapped_column(sa.String(MAX_BIO), nullable=True)
    bio_state: Mapped[str] = mapped_column(
        bio_state_enum,
        nullable=False,
        default="published",
        server_default="published",
    )
    bio_note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)

    #: `{platform: handle}`, restricted to :data:`SOCIAL_PLATFORMS`. The
    #: address is built at render time, never stored, so a link can only
    #: ever point at the platform it names.
    #: The picture across the top of the page.
    #:
    #: Held until the image screen agrees, exactly like a bio: it is
    #: shown to everybody who opens the profile, so an unscreened one is
    #: unscreened content in front of strangers. SET NULL on delete, so
    #: removing the picture does not remove the profile.
    banner_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    banner_state: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, default="published", server_default="published"
    )
    #: Why it was held, in words shown to its owner and nobody else.
    banner_note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)

    links: Mapped[dict] = mapped_column(
        sa.JSON, nullable=False, default=dict, server_default="{}"
    )

    #: Nobody but the owner sees their fits, or who they are connected to.
    #:
    #: Public is the default, because publishing a fit is an affirmative
    #: act and the whole app is built on it. This is for people who want
    #: the app without the audience. The *counts* stay visible either
    #: way: a count is not a list, and hiding it would say only that
    #: there is something here to hide.
    private: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


#: The reactions a post can carry. Closed, and emoji rather than words:
#: a fixed set needs no moderation queue, which is the whole reason this
#: can ship while comments cannot.
REACTIONS: tuple[str, ...] = ("love", "fire", "stunning", "want", "clapping")

#: What each one renders as. Here rather than in the app so the set
#: cannot drift between the two.
REACTION_EMOJI: dict[str, str] = {
    "love": "❤️",
    "fire": "🔥",
    "stunning": "😍",
    "want": "🙌",
    "clapping": "👏",
}

reaction_enum = named_enum("post_reaction", *REACTIONS)


class PostReaction(Base):
    """One person's reaction to one fit.

    **One reaction per person per post**, not one of each: the pair is
    the primary key and the kind is a column, so reacting again replaces
    rather than accumulates. A tally where one enthusiast can press five
    buttons is not a measure of anything.
    """

    __tablename__ = "post_reactions"
    __table_args__ = (sa.Index("ix_post_reactions_post", "post_id"),)

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
    kind: Mapped[str] = mapped_column(reaction_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )


#: A hashtag, normalised. Lowercase, no `#`, letters and digits only —
#: so `#StreetWear`, `#streetwear` and `#STREETWEAR` are one tag.
TAG_PATTERN = re.compile(r"[^a-z0-9]+")
MAX_TAG = 40
MAX_TAGS_PER_POST = 10


class PostTag(Base):
    """A hashtag on a fit, which is how Discover learns what it is.

    Stored as its own rows rather than parsed out of the caption on every
    read: this is the join Discover groups by, and re-deriving it per
    query would make the feed's cost a function of how much people write.
    """

    __tablename__ = "post_tags"
    __table_args__ = (
        # "Every post with this tag, newest first" is the only direction
        # the feed reads it in.
        sa.Index("ix_post_tags_tag_created", "tag", "created_at"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag: Mapped[str] = mapped_column(sa.String(MAX_TAG), primary_key=True)
    #: Denormalised from the post so the feed can order without a join.
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )
