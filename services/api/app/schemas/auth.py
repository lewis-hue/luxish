"""Auth request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str | None = None
    email_verified: bool = False
    session_id: uuid.UUID | None = None
    expires_at: datetime


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str | None = None
    email_verified: bool = False
    display_name: str | None = None


class IdentityLinkConfirmRequest(BaseModel):
    link_challenge_id: uuid.UUID = Field(
        description="From the 409 identity_link_required response."
    )


class IdentityLinkConfirmResponse(BaseModel):
    identity_id: uuid.UUID
    provider: str
    user_id: uuid.UUID
