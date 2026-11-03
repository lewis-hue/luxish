"""Fit shapes. What crosses to strangers is exactly these fields."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PostCreateIn(BaseModel):
    caption: str | None = Field(default=None, max_length=300)
    occasion: str | None = None
    media_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    garment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=6)
    product_ids: list[uuid.UUID] = Field(default_factory=list, max_length=6)


class PostItemOut(BaseModel):
    kind: Literal["garment", "product", "gone"]
    #: Taxonomy facts for a garment; the owner-written name never travels.
    category_id: str | None = None
    colour: str | None = None
    #: The product card, for catalogue items.
    title: str | None = None
    brand: str | None = None
    retailer: str | None = None
    price_minor: int | None = None
    currency: str | None = None
    source_url: str | None = None


class PostOut(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    #: First name only, same doctrine as everywhere identity crosses.
    author_name: str
    caption: str | None = None
    occasion: str | None = None
    media_asset_ids: list[uuid.UUID] = Field(default_factory=list)
    items: list[PostItemOut] = Field(default_factory=list)
    published_at: datetime | None = None
    #: How many people kept this fit. Counted, never stored.
    saves: int = 0
    #: Whether the reader is one of them, so the control renders its real
    #: state rather than guessing from a local cache.
    saved_by_me: bool = False


class PostMineOut(PostOut):
    """The author's own view carries the state and the held note."""

    state: Literal["pending_review", "published", "held", "removed"]
    #: The author's own call on who this is for, which is theirs and
    #: separate from `state`. Only ever sent to the author: a stranger
    #: never sees a private fit at all, so there is nothing to say.
    visibility: Literal["public", "private"] = "public"
    #: The cover's width over its height, so the profile's masonry can
    #: lay a tile out before its bytes arrive. Sent for the same reason
    #: the board gets it: without it every tile opens at a guessed
    #: shape and the column re-flows as the photographs land.
    cover_ratio: float | None = None
    #: How the verdict was reached: `model`, `seed`, or `unavailable`.
    screen_mode: str | None = None
    screen_note: str | None = None
    created_at: datetime


class PostFeedOut(BaseModel):
    items: list[PostOut] = Field(default_factory=list)


class PostMineListOut(BaseModel):
    items: list[PostMineOut] = Field(default_factory=list)


class PostCreatedOut(BaseModel):
    id: uuid.UUID
    #: `published` for an ordinary fit, which is live at once.
    #: `pending_review` remains possible for a path that still holds.
    state: Literal["published", "pending_review"]
    #: Said in the response, not just the UI, so a client never has to
    #: invent the sentence that explains what just happened.
    note: str


class PostVisibilityIn(BaseModel):
    """Show this fit to people, or stop."""

    visibility: Literal["public", "private"]


class PostVisibilityOut(BaseModel):
    id: uuid.UUID
    visibility: Literal["public", "private"]


class PostSaveOut(BaseModel):
    saves: int
    saved_by_me: bool


class PostReactIn(BaseModel):
    #: One of `app.models.profile.REACTIONS`, or null to take it back.
    kind: str | None = None


class PostReactionsOut(BaseModel):
    #: Count per reaction kind. Kinds nobody picked are absent.
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    #: What this reader picked, so the control shows its real state.
    mine: str | None = None
