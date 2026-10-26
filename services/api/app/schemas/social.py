"""Social reference contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.social_import import PlatformCapability


class ReferenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    note: str | None = Field(default=None, max_length=1000)


class ReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reference_id: uuid.UUID
    platform: str
    canonical_url: str
    author_handle: str | None = None
    observed_at: datetime
    capability: PlatformCapability
    #: What the user can do instead when the platform cannot be analysed.
    alternative: str | None = None
    #: Stated explicitly so a client never has to infer it (ADR-009).
    media_downloaded: bool = False
