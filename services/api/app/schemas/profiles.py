"""Public identity shapes."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.models.profile import MAX_BIO


class LinkOut(BaseModel):
    platform: str
    handle: str
    #: Built from a table at render time, never stored. A link can only
    #: ever point at the platform it names.
    url: str


class ProfileIn(BaseModel):
    handle: str | None = Field(default=None, max_length=40)
    #: Sending `null` clears it. Omitting the field leaves it alone,
    #: which is why the router checks `model_fields_set`.
    bio: str | None = Field(default=None, max_length=MAX_BIO)
    #: `{platform: handle}`. Replaces the whole set.
    links: dict[str, str] | None = None
    #: A picture uploaded with kind `profile_banner`, to put across the
    #: top of the page. Sending `null` takes it down. Omitting the field
    #: leaves it alone, which is why the router checks
    #: `model_fields_set`. Held until the image screen agrees.
    banner_asset_id: uuid.UUID | None = None
    #: Keep your fits and your two follow lists to yourself. Omitting
    #: the field leaves it alone.
    private: bool | None = None


class MyProfileOut(BaseModel):
    user_id: uuid.UUID
    handle: str | None = None
    #: What you last typed, whatever its state.
    bio: str | None = None
    bio_state: Literal["pending_review", "published", "held"]
    #: Why it was held, in words shown to its author and nobody else.
    bio_note: str | None = None
    links: list[LinkOut] = Field(default_factory=list)
    #: Which platforms links may point at.
    platforms: list[str] = Field(default_factory=list)
    #: What you chose, whatever its state - you see your own choice at
    #: once, and strangers see it once the screen agrees.
    banner_asset_id: uuid.UUID | None = None
    banner_state: Literal["pending_review", "published", "held"] = "published"
    #: Why it was held, in words shown to its owner and nobody else.
    banner_note: str | None = None
    #: Whether strangers are shown your fits and who you follow.
    private: bool = False


class PublicProfileOut(BaseModel):
    user_id: uuid.UUID
    handle: str | None = None
    #: The approved bio, or nothing. A bio in review does not cross.
    bio: str | None = None
    links: list[LinkOut] = Field(default_factory=list)
    #: The approved banner, or nothing. One in review does not cross.
    banner_asset_id: uuid.UUID | None = None


class ReactionKindOut(BaseModel):
    kind: str
    emoji: str


class ReactionsCatalogueOut(BaseModel):
    items: list[ReactionKindOut] = Field(default_factory=list)
