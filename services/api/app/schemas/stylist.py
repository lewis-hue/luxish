"""Stylist request/response contracts.

Two shapes here carry a rule rather than just a type.

:class:`PlaceIn` accepts a **name** and nothing else, with ``extra="forbid"``.
A client that sends ``{"lat": …, "lon": …}`` is rejected with a 422 instead of
having the coordinates quietly ignored, because "ignored" is one refactor away
from "stored". A coarse device fix must be reverse-geocoded to a name before it
reaches the API at all (``app.domain.regional``).

:class:`AttachmentIn` is the only way imported text enters a run, and it is
labelled with its source so the prompt layer can fence it as data
(``app.ai.untrusted``). There is no field through which a caption could be
marked trusted.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.schemas import OUTFIT_ROLES
from app.domain.stylist import MAX_ATTACHMENTS, MAX_REQUEST_TEXT
from app.models.stylist import (
    OUTFIT_FEEDBACK_KINDS,
    OUTFIT_ITEM_ROLES,
    STYLIST_RUN_STATES,
)

OutfitRole = Literal["top", "bottom", "dress", "outer", "shoes", "bag", "accessory"]
assert set(OUTFIT_ITEM_ROLES) == set(OutfitRole.__args__)  # mirrors the column
assert set(OUTFIT_ROLES) == set(OutfitRole.__args__)  # and the model's contract

RunState = Literal["queued", "running", "completed", "failed", "cancelled"]
assert set(STYLIST_RUN_STATES) == set(RunState.__args__)

FeedbackKind = Literal["would_wear", "wore", "dislike"]
assert set(OUTFIT_FEEDBACK_KINDS) == set(FeedbackKind.__args__)


class PlaceIn(BaseModel):
    """A place the user named. Never a coordinate.

    ``manual`` is accepted alongside ``name`` because that is the key the
    mobile client sends when the user typed a place after declining location
    permission; both mean the same thing and exactly one is required.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160)
    manual: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _one_name(self) -> PlaceIn:
        if not (self.name or self.manual):
            raise ValueError("a place needs a name")
        return self

    @property
    def value(self) -> str:
        return (self.name or self.manual or "").strip()


class AttachmentIn(BaseModel):
    """Imported text offered with a request. Treated as data, always."""

    model_config = ConfigDict(extra="forbid")

    #: What this is: ``instagram_caption``, ``retailer_page``, ``note``. The
    #: label is sanitised downstream so the content cannot control it.
    source: str = Field(default="imported", max_length=60)
    text: str = Field(max_length=8_000)
    origin_url: str | None = Field(default=None, max_length=2048)


class CapabilityOut(BaseModel):
    """One thing the assistant can be asked for, in its own words.

    Returned as data so a client can show examples of what to *say*. It is
    deliberately not a list of buttons: the capabilities live behind the
    sentence, which is what keeps the screen to one input box.
    """

    intent: str
    label: str
    description: str
    #: What has to be attached, if anything.
    needs: list[str] = Field(default_factory=list)


class AssistantOut(BaseModel):
    """What the assistant can do, and what it cannot."""

    items: list[CapabilityOut] = Field(default_factory=list)
    #: Moving pictures, labelled honestly. Every model this service can
    #: reach accepts video and none produces it, so this is `blocked`
    #: rather than `planned`, with the reason.
    video: str = "blocked"
    video_reason: str = ""


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=MAX_REQUEST_TEXT)
    occasion: str | None = Field(default=None, max_length=64)
    #: A name, or an object carrying one. Coordinates are refused, not ignored.
    place: PlaceIn | str | None = None
    date: datetime.date | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)
    conversation_id: uuid.UUID | None = None

    # What the request is *about*. The assistant is one input box rather
    # than a grid of capability tiles, so what can be asked for depends on
    # which kind of picture is in hand. Every id is re-validated against
    # the asker on the worker: naming one is a claim, not an entitlement.
    #: A piece out of your own wardrobe.
    garment_id: uuid.UUID | None = None
    #: A photograph you uploaded, wardrobe row or not.
    media_asset_id: uuid.UUID | None = None
    #: A fit somebody else published: to try on, or to take styling from.
    post_id: uuid.UUID | None = None

    @property
    def place_name(self) -> str | None:
        if self.place is None:
            return None
        if isinstance(self.place, str):
            return self.place.strip()[:160] or None
        return self.place.value or None

    @model_validator(mode="after")
    def _something_to_style(self) -> RunCreate:
        if not (self.text or self.occasion or self.attachments):
            raise ValueError("a run needs at least text, an occasion, or an attachment")
        return self


class RunAccepted(BaseModel):
    """The 202 body. A run id to poll, and where it is."""

    run_id: uuid.UUID
    conversation_id: uuid.UUID
    state: RunState


class SwapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: OutfitRole


class OutfitItemOut(BaseModel):
    role: OutfitRole
    #: True for a garment the user owns; false for a shopping suggestion.
    owned: bool
    garment_id: uuid.UUID | None = None
    product_ref: str | None = None
    name: str | None = None
    category: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class OutfitOut(BaseModel):
    id: uuid.UUID
    items: list[OutfitItemOut]
    rationale: str | None = None
    occasion: str | None = None
    place: str | None = None
    styled_for: datetime.date | None = None
    missing_slots: list[str] = Field(default_factory=list)
    created_at: datetime.datetime | None = None


class ToolExecutionOut(BaseModel):
    """One dispatch attempt. ``ok=false`` means it was refused, not that it ran."""

    name: str
    ok: bool
    error_code: str | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    state: RunState
    progress: float
    outfit: OutfitOut | None = None
    explanation: str | None = None
    #: Why there is no outfit. Null when there is one.
    explanation_code: str | None = None
    prompt_version: str | None = None
    provider: str | None = None
    model: str | None = None
    tool_calls_used: int = 0
    tool_executions: list[ToolExecutionOut] = Field(default_factory=list)
    error_code: str | None = None
    swap_slot: OutfitRole | None = None
    parent_run_id: uuid.UUID | None = None
    #: The hard constraints Python applied, so the client can show them.
    excluded: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: FeedbackKind
    note: str | None = Field(default=None, max_length=500)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    outfit_id: uuid.UUID
    kind: FeedbackKind
    note: str | None = None


class OutfitPageOut(BaseModel):
    items: list[OutfitOut]
    next_cursor: str | None = None


__all__ = [
    "AttachmentIn",
    "FeedbackCreate",
    "FeedbackOut",
    "OutfitItemOut",
    "OutfitOut",
    "OutfitPageOut",
    "PlaceIn",
    "RunAccepted",
    "RunCreate",
    "RunOut",
    "SwapRequest",
    "ToolExecutionOut",
]


class AskTurn(BaseModel):
    """One thing already said, by one side."""

    #: `you` for the person, `stylist` for the assistant.
    who: str = Field(pattern="^(you|stylist)$")
    text: str = Field(min_length=1, max_length=2000)


class AskCreate(BaseModel):
    """A question about this person's own wardrobe.

    `post_id` is the pin they are looking at, when they came from
    one. It is what makes "match the fit above" answerable: the
    photograph goes to the model, not just the caption.
    """

    question: str = Field(min_length=1, max_length=500)
    post_id: uuid.UUID | None = None
    #: What has already been said in this conversation, oldest first.
    #:
    #: **Sent by the client rather than kept on the server**, which
    #: is the right trade for a conversation this short: it is a few
    #: turns about one wardrobe, it ends when the screen closes, and
    #: storing it would mean a table, a retention rule and an export
    #: entry for something nobody asked to keep.
    #:
    #: Capped so a client cannot grow the prompt without bound.
    history: list[AskTurn] = Field(default_factory=list, max_length=20)
