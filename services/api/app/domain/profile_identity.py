"""Who somebody is, as they have chosen to present it.

Distinct from `app.domain.profile`, which is the *style* profile — what the
stylist has inferred about how a person dresses. This file is the two things
a person sets about themselves by hand: the name shown in the app and the
photograph shown beside it.

Nothing here touches the email or the verified flag. Those arrive in every
token from the identity provider, so a local write would be overwritten at
the next sign-in and is better refused than silently lost.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media_asset import MediaAsset
from app.models.user import User


class ProfilePhotoNotFound(Exception):
    """The asset does not exist, or does not belong to this user.

    One exception for both, deliberately: telling a caller that an id exists
    but is somebody else's confirms the existence of another person's media,
    which is the thing the ownership check is there to prevent.
    """


async def set_profile(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    display_name: str | None = None,
    photo_asset_id: uuid.UUID | None = None,
    fields: set[str],
) -> User:
    """Apply the fields the caller actually sent.

    `fields` is the set of names present in the request, which is what makes
    this three-valued: absent leaves a column alone, a value sets it, and an
    explicit null clears it. Without it there is no way to say "remove my
    photograph" that is distinguishable from "do not touch my photograph".
    """
    user = await db.get(User, user_id)
    if user is None:  # pragma: no cover - an authenticated user exists
        raise ProfilePhotoNotFound

    if "display_name" in fields:
        # Trimmed, and an empty string is a clear rather than a name made of
        # spaces. Somebody wiping the field means "use my email again".
        cleaned = (display_name or "").strip()
        user.display_name = cleaned or None

    if "profile_photo_asset_id" in fields:
        if photo_asset_id is None:
            user.profile_photo_media_asset_id = None
        else:
            # **Re-validated against this user's own media**, on the same rule
            # the wardrobe applies to garment ids a model returns: an id that
            # arrives from a client is a claim, not a fact. Without this check
            # anybody could set any other user's photograph as their own by
            # guessing a uuid.
            owned = await db.scalar(
                sa.select(MediaAsset.id).where(
                    MediaAsset.id == photo_asset_id,
                    MediaAsset.user_id == user_id,
                )
            )
            if owned is None:
                raise ProfilePhotoNotFound
            user.profile_photo_media_asset_id = photo_asset_id

    # Committed, not merely flushed. Nothing in this app commits on the way
    # out of a request, so a flush alone is rolled back when the session
    # closes: the endpoint returns 200 with the new values and the next read
    # shows the old ones. Every other domain module here commits for the same
    # reason.
    await db.commit()
    return user
