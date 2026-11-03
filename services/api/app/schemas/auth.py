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
    #: The media asset holding their photograph, if they set one. The client
    #: fetches it from the usual delivery endpoint; there is no second route.
    profile_photo_asset_id: uuid.UUID | None = None


class UpdateMeRequest(BaseModel):
    """What somebody may change about their own profile.

    Both fields are three-valued and the distinction is the whole point of
    the shape: absent means "leave it alone", a value sets it, and `null`
    clears it. A two-valued field cannot express "remove my photograph"
    without a second endpoint to do the removing.

    Nothing here touches the email or the verified flag. Those come from the
    identity provider on every token, so accepting them would let a client
    write a claim the next sign-in silently overwrites.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(
        default=None,
        max_length=120,
        description="Shown in the app. Null clears it and falls back to the email.",
    )
    profile_photo_asset_id: uuid.UUID | None = Field(
        default=None,
        description="A media asset this user owns. Null removes the photograph.",
    )
    #: Which of the above were actually sent, since Pydantic cannot otherwise
    #: tell `display_name=None` from an omitted `display_name`.
    def fields_sent(self) -> set[str]:
        return set(self.model_fields_set)


class IdentityLinkConfirmRequest(BaseModel):
    link_challenge_id: uuid.UUID = Field(
        description="From the 409 identity_link_required response."
    )


class IdentityLinkConfirmResponse(BaseModel):
    identity_id: uuid.UUID
    provider: str
    user_id: uuid.UUID
