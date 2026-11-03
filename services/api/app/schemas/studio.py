"""Studio shapes."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class TopFitOut(BaseModel):
    post_id: uuid.UUID
    #: Distinct people who saved or reacted to it. Not events.
    people: int
    saves: int


class StudioOverviewOut(BaseModel):
    window: str
    #: Fits this person has published, which is what the rest is about.
    fits: int
    saves: int
    reach: int
    followers: int
    followers_gained: int
    #: One count per day, oldest first. The client draws these as bars and
    #: must not re-derive them.
    series: list[int] = Field(default_factory=list)
    top_fits: list[TopFitOut] = Field(default_factory=list)
