"""Wardrobe folder shapes."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

#: Mirrors `domain.collections.MAX_NAME`, so a client can validate the same
#: rule the server will.
MAX_NAME = 120

#: One bulk selection. Generous, because "select all" on a large wardrobe
#: is a normal thing to do.
MAX_MEMBERS = 500


class CollectionIn(BaseModel):
    name: str = Field(max_length=MAX_NAME)
    description: str | None = Field(default=None, max_length=500)


class CollectionRenameIn(BaseModel):
    name: str = Field(max_length=MAX_NAME)


class CollectionMembersIn(BaseModel):
    garment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MEMBERS)


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    #: What is in it now, excluding anything since deleted.
    garment_ids: list[uuid.UUID] = Field(default_factory=list)


class CollectionsOut(BaseModel):
    items: list[CollectionOut] = Field(default_factory=list)
