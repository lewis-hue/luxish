"""Upload authorisation contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: What a client may declare on an upload.
#:
#: ``profile_banner`` is the picture across the top of somebody's page.
#: Decoration, shown to everybody who opens the profile, and screened
#: like a caption for that reason.
#:
#: ``avatar_source`` is a photograph of the person themselves, uploaded so
#: an avatar can be built that looks like them. It is a separate kind from
#: ``avatar`` - one is what they sent, the other is what was drawn - and
#: separate from every garment kind, so a picture of a person is never
#: read as evidence of what they own.
#:
#: ``garment_render`` and ``garment_studio`` are deliberately absent: both
#: are written by this service from something a user already uploaded, and
#: a client declaring one would be claiming a derivative is an original.
MediaKind = Literal[
    "garment_photo",
    "outfit_photo",
    "inspiration",
    "avatar",
    "avatar_source",
    "profile_banner",
    #: A picture attached to a message. Private to the two people in
    #: that thread, and never read for clothes.
    "message_media",
]


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
