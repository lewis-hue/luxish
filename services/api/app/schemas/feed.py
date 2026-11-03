"""Discover board shapes."""

from __future__ import annotations

from typing import Literal

import uuid

from app.models.comment import MAX_COMMENT
from datetime import datetime

from app.schemas.posts import PostItemOut
from pydantic import BaseModel, ConfigDict, Field


class FeedItemOut(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    #: First name only, same doctrine as everywhere identity crosses.
    author_name: str
    #: The author's own words, or - where they wrote none - the
    #: description read off the photograph. Never a replacement: a caption
    #: somebody typed is always theirs.
    caption: str | None = None
    #: True when `caption` came from the photograph rather than the author,
    #: so a client can present it as a description rather than as a quote.
    caption_is_described: bool = False
    occasion: str | None = None
    media_asset_ids: list[uuid.UUID] = Field(default_factory=list)
    #: The first photograph's width over its height.
    #:
    #: Sent so a tile can be laid out before the bytes arrive. Without
    #: it a board guesses one ratio and re-flows as each picture
    #: decodes, which is the jump people read as the app glitching.
    #: Null for assets uploaded before dimensions were recorded; a
    #: client measures those on load, as it used to for all of them.
    cover_ratio: float | None = None
    #: What the author tagged it, normalised.
    tags: list[str] = Field(default_factory=list)
    #: Which of the app's groups those tags put it in. Possibly none.
    groups: list[str] = Field(default_factory=list)
    reactions: int = 0
    saves: int = 0
    #: Published comments this reader can see. Counted over what they
    #: can reach, so the number does not promise a longer thread than
    #: the one they will get.
    comments: int = 0
    #: This reader's own reaction, so the control shows its real state.
    my_reaction: str | None = None
    saved_by_me: bool = False
    published_at: datetime | None = None


class FeedOut(BaseModel):
    group: str
    items: list[FeedItemOut] = Field(default_factory=list)


class GroupOut(BaseModel):
    group: str
    posts: int
    #: Distinct people who reacted or saved in this group.
    people: int
    #: True once `people` clears the floor. Below it a group is real but
    #: not reported as moving, because a leaderboard of two lies.
    trending: bool


class GroupsOut(BaseModel):
    #: The floor, said out loud so a client can explain an empty row.
    min_people: int
    items: list[GroupOut] = Field(default_factory=list)


class FitAuthorOut(BaseModel):
    user_id: uuid.UUID
    #: First name only, same doctrine as everywhere identity crosses.
    name: str
    handle: str | None = None
    #: The approved bio, or nothing. One in review does not cross.
    bio: str | None = None
    followed: bool = False
    #: Their own site, when they published one. Built from the stored
    #: platform and handle, never from a string somebody typed, so a
    #: Visit button can only ever go where it says it does.
    website: str | None = None


class CommentOut(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    #: First name only, same doctrine as everywhere identity crosses.
    author_name: str
    body: str
    #: `published`, or - for your own only - `pending_review` or `held`.
    #: Somebody's own comment is shown to them in whatever state it is,
    #: because one that vanished on submission reads as a bug and
    #: invites a second attempt.
    state: str
    #: Why it was held, in words shown to its author and nobody else.
    note: str | None = None
    #: Set when this answers another comment. One level only.
    parent_id: uuid.UUID | None = None
    #: True when this reader wrote it, which decides what they may do.
    mine: bool = False
    created_at: datetime | None = None
    #: How many people liked it. Shown beside the heart from one up.
    likes: int = 0
    #: Whether this reader is one of them, so the heart opens filled.
    liked_by_me: bool = False


class CommentLikeOut(BaseModel):
    """The tally after a like or an un-like, so the row can settle."""

    likes: int
    liked_by_me: bool


class CommentsOut(BaseModel):
    items: list[CommentOut] = Field(default_factory=list)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_COMMENT)
    #: The comment being answered. A reply to a reply is attached to the
    #: top-level parent rather than refused.
    parent_id: uuid.UUID | None = None


class VisualSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A picture you uploaded, as `outfit_photo` or `inspiration`.
    #: Re-validated against your account and those kinds.
    media_asset_id: uuid.UUID


class VisualSearchOut(BaseModel):
    """Where a search by picture got to.

    `queued` and `running` mean keep polling. Reading a photograph
    takes five to nine seconds, which is the real cost of the thing;
    the state says so rather than leaving a spinner to imply it is
    nearly done.
    """

    job_id: uuid.UUID
    state: str
    #: Tags read out of the picture, best first. Empty until it lands.
    tags: list[str] = Field(default_factory=list)
    #: What the reader thought the outfit was, so the answer can
    #: explain itself rather than only jumping somewhere.
    outfit: str = ""
    error: str | None = None


class DoorOut(BaseModel):
    """One category tile on the search screen."""

    #: `tag` today. `group` is reserved for this app's own groupings,
    #: which are a different destination.
    kind: str = "tag"
    key: str
    label: str
    #: How many fits are behind it, for this reader.
    posts: int = 0
    #: A real photograph somebody posted, not generated cover art.
    cover_asset_id: uuid.UUID | None = None


class IdeasOut(BaseModel):
    """A shelf of tags this reader keeps reaching for.

    The same tile as `explore`'s, ranked differently: by what they
    saved and reacted to rather than by what they said they liked.
    """

    items: list[DoorOut] = Field(default_factory=list)


class ExploreOut(BaseModel):
    """What to look at, in two rows.

    `for_you` comes from stated taste; `popular` from what is busy for
    this reader. A new account with nothing stated gets the busiest
    tags in the first row rather than an empty one.
    """

    for_you: list[DoorOut] = Field(default_factory=list)
    popular: list[DoorOut] = Field(default_factory=list)


class TagOut(BaseModel):
    tag: str
    #: How many published fits carry it that this reader can see. Counted
    #: over what they can actually reach, so the number does not promise
    #: a page longer than the one they will get.
    posts: int = 0


class TagsOut(BaseModel):
    items: list[TagOut] = Field(default_factory=list)


class TagFeedOut(BaseModel):
    """One hashtag, and everything under it."""

    tag: str
    items: list[FeedItemOut] = Field(default_factory=list)
    #: Tags that appear alongside this one, most shared first. Somewhere
    #: to go when a tag turns out to be broader than what was wanted.
    related: list[str] = Field(default_factory=list)


class TryOnFitOut(BaseModel):
    """A try-on that was asked for, and where it got to.

    The render is polled on the avatar routes, which already own render
    state; this only hands back the id to poll and what was asked for.
    """

    render_id: uuid.UUID
    state: str
    #: The outfit sentence the picture will be drawn from. Null on the
    #: first try of a fit nobody has read yet: the worker reads it.
    outfit: str | None = None


class FitPieceOut(BaseModel):
    """One garment from a fit, cut out of the photograph it was worn in."""

    #: The cut-out itself. Readable exactly while its fit is.
    media_asset_id: uuid.UUID
    #: Where it sits in the outfit, matching the described order.
    position: int
    #: Taxonomy facts only, the same rule as everywhere identity or
    #: free text would otherwise cross.
    name: str | None = None
    colour: str | None = None
    category: str | None = None


class FitDetailOut(BaseModel):
    fit: FeedItemOut
    author: FitAuthorOut
    #: Where this fit lives, for sharing.
    #:
    #: A picture shared without it is a picture nobody can trace back to
    #: the person who posted it, which is the thing attribution is for.
    #: Returned by the server rather than built by a client so the scheme
    #: is decided in one place.
    link: str = ""
    #: What to look at next, from the groups this fit is in.
    more: list[FeedItemOut] = Field(default_factory=list)
    #: The garments in this fit, each cut out of the photograph.
    #:
    #: **The clothes themselves, not a description of them.** A
    #: try-on used to pay an image model to redraw the outfit from a
    #: sentence, which produced something *like* it. These are the
    #: real things, so the stylised figure can wear them without
    #: anything being reconstructed.
    #:
    #: Empty until the fit has been read, and empty for one nothing
    #: could be cut from. A client offers the photoreal render in
    #: that case, which is what it did for everything before.
    pieces: list[FitPieceOut] = Field(default_factory=list)
    #: Whether the reader is the person who posted this.
    #:
    #: **Answered here rather than inferred by the client.** The app
    #: used to decide by looking for the fit in `/v1/posts/mine`,
    #: which returns the thirty newest - so an author's thirty-first
    #: fit silently lost the two controls that are theirs alone, with
    #: nothing to say why. Ownership is not a function of how recently
    #: something was posted, and the server is the only thing that
    #: knows it without a cap.
    mine: bool = False
    #: What this look is made of, for "Shop the look".
    #:
    #: **Sent here and not on a board tile.** The button that needs
    #: them is on this page, and a tile would pay a query per card to
    #: carry something nothing on a board reads. Without them the
    #: button had nothing to point at and fell through to generic
    #: recommendations under a label promising this look.
    #:
    #: Empty is the honest answer and the common one today: nothing
    #: has been tagged onto a fit yet. A client reads the emptiness
    #: and says so rather than offering a shelf that is not there.
    items: list[PostItemOut] = Field(default_factory=list)
    #: The author's own call on who this fit is for.
    #:
    #: Null for everybody else, and that is the point: a stranger
    #: never sees a private fit at all, so there is nothing to tell
    #: them. Sent to the author because the menu has to render the
    #: switch the way it is actually set.
    visibility: Literal["public", "private"] | None = None
