"""Upload authorisation contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MediaKind = Literal["garment_photo", "outfit_photo", "inspiration", "avatar"]


class UploadAuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MediaKind = "garment_photo"
    content_type: str = Field(max_length=127)
    #: What the client intends to send. Checked against the cap before any
    #: storage is touched; the backend enforces the same ceiling again.
    content_length: int = Field(gt=0, le=10 * 1024 * 1024 * 1024)


class UploadAuthorizeResponse(BaseModel):
    asset_id: uuid.UUID
    upload_url: str
    expires_at: datetime
    max_bytes: int
    #: "simulated" until a signing credential exists — never presented as live.
    storage_mode: str
    required_headers: dict[str, str] = Field(default_factory=dict)
