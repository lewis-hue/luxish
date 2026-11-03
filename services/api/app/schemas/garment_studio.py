"""Studio shapes. What a treatment is, and what a shot of one looks like."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.workers.brand_studio import MAX_BRIEF


class TreatmentOut(BaseModel):
    """One shot the studio can take, described before it is paid for."""

    id: str
    label: str
    #: What comes back, in the owner's terms. Not a quality claim.
    description: str


class TreatmentsOut(BaseModel):
    items: list[TreatmentOut] = Field(default_factory=list)
    #: Said plainly rather than implied by the absence of an option: the
    #: model behind this takes one source image, so a shot is always built
    #: around the garment alone. Choosing which mannequin wears it would
    #: need two images in one call and is not possible here.
    note: str


class ShotOut(BaseModel):
    id: uuid.UUID
    #: The photograph that was edited. Always present.
    source_asset_id: uuid.UUID
    #: Set only when the shot came from a wardrobe item.
    garment_id: uuid.UUID | None = None
    treatment: str
    state: Literal["queued", "running", "ready", "failed"]
    #: Null until the edit comes back, and on a failure.
    media_asset_id: uuid.UUID | None = None
    #: Why it failed, for the owner. Null in every other state.
    error: str | None = None
    #: The direction this was asked for with, in the owner's own words.
    #: Sent back so a shot can be shown with the sentence that produced
    #: it rather than with the treatment's name alone.
    brief: str | None = None
    created_at: datetime


class ShotsOut(BaseModel):
    items: list[ShotOut] = Field(default_factory=list)


class ShotRequestIn(BaseModel):
    treatment: str


class ShotFromAssetIn(BaseModel):
    """Shoot a photograph directly, with no wardrobe item behind it.

    This is the stylist's path: somebody hands it a picture from their
    camera roll and asks for a packshot, and that picture never becomes a
    garment. `garment_id` is accepted so the wardrobe can use the same
    endpoint and keep the provenance.
    """

    treatment: str
    media_asset_id: uuid.UUID | None = None
    garment_id: uuid.UUID | None = None
    #: Ask for a wide frame instead of the app's upright one.
    #:
    #: Only the two flat-lay treatments are forced upright, so this
    #: changes nothing for the rest. Safe to allow: a landscape
    #: picture posted to the feed is stood upright on its way in.
    landscape: bool = False
    #: Optional direction in the person's own words - "on a rooftop at
    #: dusk". Trimmed and capped server-side; it is placed after the
    #: treatment's wording and before the clause protecting the
    #: garment, never last, because an edit follows its final
    #: instruction most closely.
    brief: str | None = Field(default=None, max_length=MAX_BRIEF)


class SplitStartedOut(BaseModel):
    """A split has been queued. How many pictures is not known yet.

    Deciding what a photograph contains is a model call, so it happens
    on a worker and never in a handler (ADR-013) - which means the
    count cannot be in this reply. The shots appear in the studio's
    own list as the worker creates them, which is where somebody is
    already looking while they wait.
    """

    job_id: uuid.UUID
