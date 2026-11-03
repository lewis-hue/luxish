"""Moodboard request and response shapes."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.domain.moodboards import MAX_NAME, MAX_NOTE, MAX_PINS


class BoardFitOut(BaseModel):
    """One pinned fit: what to show, and what to open."""

    post_id: uuid.UUID
    #: Null when the fit has no readable photograph.
    cover_asset_id: uuid.UUID | None = None


class BoardOut(BaseModel):
    id: str
    name: str
    note: str | None = None
    #: What is on it, in the order it was arranged. Returned with the board
    #: rather than behind a second request: a board with no pictures is not a
    #: board, so fetching them separately renders empty rectangles first.
    post_ids: list[str] = Field(default_factory=list)
    #: `(post_id, cover_asset_id)` for each pinned fit, in pin order.
    #:
    #: Pairs rather than ids: a tile needs the asset to render and the
    #: post to open. Without this the board screen had post pins it
    #: could not draw.
    posts: list[BoardFitOut] = Field(default_factory=list)
    #: Everything on the board in one ordered list. The same ids as
    #: `post_ids`; this is the name the reorder endpoint takes them under.
    refs: list[str] = Field(default_factory=list)


class BoardsResponse(BaseModel):
    items: list[BoardOut]


class BoardIn(BaseModel):
    """Create or edit. On a `PATCH`, omitting a field leaves it alone."""

    name: str | None = Field(default=None, max_length=MAX_NAME)
    note: str | None = Field(default=None, max_length=MAX_NOTE)


class ReorderIn(BaseModel):
    #: The arrangement, as the `refs` a board came back with. Anything on
    #: the board but missing here keeps its relative order after everything
    #: named, rather than being dropped.
    refs: list[str] = Field(max_length=MAX_PINS)


class PinsResponse(BaseModel):
    refs: list[str]
