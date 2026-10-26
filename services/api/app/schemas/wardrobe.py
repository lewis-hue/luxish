"""Wardrobe request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.garment import AVAILABILITY_VALUES

Availability = Literal["available", "laundry", "unavailable", "archived"]
assert set(AVAILABILITY_VALUES) == set(Availability.__args__)  # schema mirrors the column


class GarmentCreate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    category: str | None = Field(default=None, max_length=64)
    media_asset_id: uuid.UUID | None = None
    confirmed_attributes: dict[str, Any] = Field(default_factory=dict)
    availability: Availability = "available"


class GarmentPatch(BaseModel):
    """A correction. Attributes merge per key; an explicit null clears a key."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160)
    category: str | None = Field(default=None, max_length=64)
    availability: Availability | None = None
    confirmed_attributes: dict[str, Any] | None = None


class GarmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    category: str | None
    availability: Availability
    media_asset_id: uuid.UUID | None
    confirmed_attributes: dict[str, Any]
    inferred_attributes: dict[str, Any]
    inference_confidence: float | None
    inference_version: str | None
    #: Inferred values with every confirmed key applied on top.
    effective_attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class GarmentPage(BaseModel):
    items: list[GarmentOut]
    next_cursor: str | None = None
