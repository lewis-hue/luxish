"""Where this account can be reached.

Two routes and nothing else. Everything about *what* gets sent is
decided by the notification switches, which already have their own
endpoint - a device saying "here I am" must never also be a way to
change what somebody agreed to hear about.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.deps import AuthDep, SessionDep
from app.domain import push as domain
from app.models.push import PUSH_PLATFORMS

router = APIRouter(prefix="/push", tags=["push"])


class DeviceIn(BaseModel):
    """A phone announcing itself."""

    token: str = Field(min_length=8, max_length=255)
    #: `expo` unless a later build talks to a gateway directly.
    platform: str = Field(default="expo")
    #: The phone's own IANA zone, so a notification is not delivered at
    #: three in the morning. Optional: an unknown zone sends at once
    #: rather than waiting for a clock nobody knows.
    timezone: str | None = Field(default=None, max_length=64)


class DeviceOut(BaseModel):
    token: str
    platform: str
    timezone: str | None = None


@router.put("/devices", response_model=DeviceOut)
async def register(payload: DeviceIn, db: SessionDep, ctx: AuthDep) -> DeviceOut:
    """Register this phone, or refresh what is known about it.

    Idempotent, and safe to call on every launch: the same token is
    the same device, so the row is updated rather than duplicated.
    Calling it also un-revokes, which is what signing back in means.

    409 when the token is live under another account. A real client
    never sees it: a token comes from Expo on this handset, and a
    handset changing hands goes through a sign-out that frees the row
    first. Presenting one somebody else is currently reachable on is
    either a stale sign-out or an attempt to silence them, and neither
    is answered by moving the row.
    """
    platform = payload.platform if payload.platform in PUSH_PLATFORMS else "expo"
    try:
        device = await domain.register_device(
            db,
            user_id=ctx.user_id,
            token=payload.token,
            platform=platform,
            timezone=payload.timezone,
        )
    except domain.DeviceClaimed:
        # Said without detail. The caller already holds the token, so
        # this confirms nothing they did not have - but there is no
        # reason to name the account it belongs to either.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That device is registered to another account.",
        ) from None
    return DeviceOut(
        token=device.token, platform=device.platform, timezone=device.timezone
    )


@router.delete("/devices/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def forget(token: str, db: SessionDep, ctx: AuthDep) -> Response:
    """Stop sending to this phone. 204 whether or not it was known.

    Called on sign-out. 204 either way because forgetting something
    already forgotten is work that is done, and a different answer
    would tell the caller whether a token exists - or whose it is.

    Scoped to the caller: only your own device can be forgotten. A
    token is opaque, but that is secrecy rather than authorization,
    and one that leaked would otherwise let its holder silence
    somebody else's notifications.
    """
    await domain.forget_device(db, token=token, user_id=ctx.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
