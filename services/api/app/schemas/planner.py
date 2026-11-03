"""Planner request and response shapes."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.domain.planner import MAX_NOTE


class PlanOut(BaseModel):
    planned_for: date
    #: The clothes, in the order they were put together. Theirs: every
    #: id is re-validated against the wardrobe before it is stored.
    garment_ids: list[uuid.UUID] = Field(default_factory=list)
    note: str | None = None
    #: Null means not yet answered, which is not "no". A plan for next
    #: Tuesday has not been declined; it has not happened.
    worn: bool | None = None
    #: The fit this day was planned from, when it started on one.
    #: Null on most days: planning straight out of the wardrobe
    #: references nothing.
    reference_post_id: uuid.UUID | None = None
    #: That fit's cover, so a calendar can show the picture without a
    #: request per day.
    reference_asset_id: uuid.UUID | None = None


class PlannerResponse(BaseModel):
    items: list[PlanOut]
    #: Echoed back, so a client can tell a short answer from a short range.
    start: date
    end: date


class PlanIn(BaseModel):
    #: What to wear. Replaces whatever was planned for the day: the
    #: request describes the day, and a client that had to diff would
    #: have to know what was there before it could change anything.
    garment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    #: Omitting leaves a previous note alone; an empty string clears it.
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    worn: bool | None = None
    #: The fit this day is being planned from, if it started on one.
    #: Omitting leaves a previous reference alone, the same rule the
    #: note follows.
    reference_post_id: uuid.UUID | None = None


class WornIn(BaseModel):
    worn: bool
