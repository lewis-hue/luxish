"""Wardrobe media contracts: favourites, bulk operations, categorisation view.

The enums here are generated from the domain tuples rather than retyped, and
asserted equal, so a label added in one place cannot be missing from the API
schema — which is the failure mode that makes a "closed" set quietly open.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.garment_media import (
    CATEGORIES,
    MAX_BULK_ITEMS,
    SLOTS,
    UNKNOWN,
)
from app.schemas.wardrobe import Availability, GarmentOut

Slot = Literal["tops", "bottoms", "outerwear", "shoes", "accessories"]
assert set(SLOTS) == set(Slot.__args__)  # schema mirrors the closed set

Category = Literal[
    "shirt",
    "tshirt",
    "knitwear",
    "sweatshirt",
    "blouse",
    "dress",
    "trousers",
    "jeans",
    "skirt",
    "shorts",
    "blazer",
    "jacket",
    "coat",
    "shoes",
    "bag",
    "accessory",
]
assert set(CATEGORIES) == set(Category.__args__)  # schema mirrors the closed set

#: What a *response* may carry: the closed set plus the honest non-answer.
InferredSlot = Slot | Literal["unknown"]
InferredCategory = Category | Literal["unknown"]


class GarmentMediaOut(GarmentOut):
    """A garment, plus what this task added.

    Extends rather than replaces :class:`~app.schemas.wardrobe.GarmentOut` so
    there is one definition of a garment and one place to change it.
    """

    is_favourite: bool = False
    #: The cut-out. ``None`` is the normal state, not an error: background
    #: removal is optional processing and the original always works without it.
    background_removed_asset_id: uuid.UUID | None = None
    #: Confidence in the *category label* specifically, which is what a client
    #: uses to decide whether to ask the user to confirm it.
    categorisation_confidence: float | None = None


class FavouritePage(BaseModel):
    items: list[GarmentMediaOut]
    next_cursor: str | None = None


class FavouriteIdsOut(BaseModel):
    """Just the ids, for a client — or the stylist — that weights favourites.

    ``total`` is reported separately so a truncated read is visible rather than
    silently partial.
    """

    garment_ids: list[uuid.UUID]
    total: int
    truncated: bool = False


# --------------------------------------------------------------------------- #
# bulk create
# --------------------------------------------------------------------------- #
class BulkGarmentIn(BaseModel):
    """One garment, keyed on an upload this user was authorised for.

    ``media_asset_id`` is the idempotency key: one garment per uploaded asset
    per owner, enforced by a partial unique index, so re-sending a batch after a
    network failure returns the same records instead of duplicating a wardrobe.
    """

    model_config = ConfigDict(extra="forbid")

    media_asset_id: uuid.UUID
    name: str | None = Field(default=None, max_length=160)
    category: Category | None = None
    availability: Availability = "available"
    is_favourite: bool = False


class BulkGarmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BulkGarmentIn] = Field(min_length=1, max_length=MAX_BULK_ITEMS)

    @field_validator("items")
    @classmethod
    def _unique_assets(cls, items: list[BulkGarmentIn]) -> list[BulkGarmentIn]:
        """One asset may appear once per request.

        Rejected rather than de-duplicated: the same asset twice in one batch is
        a client bug, and silently collapsing it would make the per-item result
        array stop lining up with what was sent.
        """
        seen = {item.media_asset_id for item in items}
        if len(seen) != len(items):
            raise ValueError("media_asset_id must be unique within one request")
        return items


class BulkItemOut(BaseModel):
    """What happened to one item. Position-preserving, so a client can zip."""

    index: int
    media_asset_id: uuid.UUID
    #: ``created`` | ``existing`` | ``deleted`` | ``failed``
    status: Literal["created", "existing", "deleted", "failed"]
    garment_id: uuid.UUID | None = None
    #: Present only on ``failed``: the stable error code for this item alone.
    code: str | None = None
    message: str | None = None
    #: Durable jobs queued for this item. Model work is never run inline.
    jobs: list[str] = Field(default_factory=list)


class BulkResultOut(BaseModel):
    """A batch result. **Never** a 4xx for a partial failure.

    One bad item out of twenty must not discard the nineteen that worked, so the
    response is a 200 (or 207-shaped 200) carrying per-item status, and the
    counts are precomputed because every client needs them.
    """

    items: list[BulkItemOut]
    succeeded: int
    failed: int

    @property
    def partial(self) -> bool:
        return self.succeeded > 0 and self.failed > 0


class BulkDeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_ITEMS)


# --------------------------------------------------------------------------- #
# categorisation view
# --------------------------------------------------------------------------- #
class CategorisationOut(BaseModel):
    """The inference, as a client reads it.

    Everything here is a *model* claim. The user's own answers live in
    ``confirmed_attributes`` and override these on read (ADR-010), which is why
    this object is reported alongside ``effective_attributes`` rather than
    instead of it.
    """

    slot: InferredSlot = UNKNOWN
    category: InferredCategory = UNKNOWN
    colour: str = UNKNOWN
    pattern: str = UNKNOWN
    apparent_material: str = UNKNOWN
    one_piece: bool = False
    confidence: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def from_inferred(cls, inferred: dict[str, Any] | None) -> CategorisationOut | None:
        if not inferred or "category" not in inferred:
            return None
        return cls.model_validate(inferred)


__all__ = [
    "BulkDeleteIn",
    "BulkGarmentCreate",
    "BulkGarmentIn",
    "BulkItemOut",
    "BulkResultOut",
    "CategorisationOut",
    "Category",
    "FavouriteIdsOut",
    "FavouritePage",
    "GarmentMediaOut",
    "InferredCategory",
    "InferredSlot",
    "Slot",
]
