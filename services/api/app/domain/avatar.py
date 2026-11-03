"""Storing an avatar, and putting outfits on it.

Thin over :mod:`app.workers.avatar`, which owns the vocabulary and the
prompts. What lives here is the part that touches the database: where the
stated appearance is kept, where the picture is kept, and the rule that an
avatar belongs to exactly one person.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.media_asset import MediaAsset
from app.models.preference import Preference
from app.workers.avatar import (
    APPEARANCE_KEY,
    AVATAR_MEDIA_KIND,
    Appearance,
    AvatarRenderer,
)


class NoAvatarYet(ApiError):
    status_code = 409
    code = "no_avatar"
    default_message = "Create your avatar before trying clothes on it."


async def read_appearance(session: AsyncSession, *, user_id: uuid.UUID) -> Appearance:
    """What this person said about how they look, or nothing at all."""
    stored = await session.scalar(
        sa.select(Preference.value).where(
            Preference.user_id == user_id, Preference.key == APPEARANCE_KEY
        )
    )
    return Appearance.from_stored(stored)


async def write_appearance(
    session: AsyncSession, *, user_id: uuid.UUID, appearance: Appearance
) -> Appearance:
    """Record it. Idempotent, and overwrites rather than accumulating.

    Stored as a preference because that is exactly what it is: a statement by
    the user, which the preference table's own rule says always wins over an
    inference. Nothing in this service may derive these values from someone's
    clothes, and keeping them here rather than on a model output is what makes
    that structural.
    """
    existing = await session.scalar(
        sa.select(Preference).where(
            Preference.user_id == user_id, Preference.key == APPEARANCE_KEY
        )
    )
    if existing is None:
        session.add(
            Preference(
                user_id=user_id, key=APPEARANCE_KEY, value=appearance.as_stored()
            )
        )
    else:
        existing.value = appearance.as_stored()
    await session.commit()
    return appearance


async def current_avatar(
    session: AsyncSession, *, user_id: uuid.UUID
) -> MediaAsset | None:
    """The newest avatar this person has, if any.

    Newest rather than only: regenerating leaves the old one in place so a
    half-finished write never takes somebody's avatar away, and a later sweep
    can retire what is no longer pointed at.
    """
    return await session.scalar(
        sa.select(MediaAsset)
        .where(
            MediaAsset.user_id == user_id,
            MediaAsset.kind == AVATAR_MEDIA_KIND,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status == "ready",
        )
        .order_by(MediaAsset.created_at.desc())
    )


async def store_avatar(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    data: bytes,
    content_type: str,
    store: Any,
) -> MediaAsset:
    """Write one avatar image and the row that points at it.

    Kind ``avatar``, never ``garment_photo``. It is a drawing of somebody who
    looks like the user, not a photograph of them, and nothing downstream
    should be able to mistake the two.
    """
    asset = MediaAsset(
        user_id=user_id,
        kind=AVATAR_MEDIA_KIND,
        status="processing",
        content_type=content_type,
        max_bytes=len(data),
        byte_size=len(data),
        version=1,
        publication_consent=False,
    )
    session.add(asset)
    await session.flush()

    key = f"users/{user_id}/avatar/{asset.id}"
    await store.write(key, data, content_type=content_type)

    asset.storage_key = key
    asset.checksum_sha256 = hashlib.sha256(data).hexdigest()
    asset.status = "ready"
    await session.commit()
    await session.refresh(asset)
    return asset


async def generate_avatar(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    renderer: AvatarRenderer,
    store: Any,
) -> MediaAsset:
    """Draw this person's avatar from what they told us, and keep it."""
    appearance = await read_appearance(session, user_id=user_id)
    drawn = await renderer.generate(appearance=appearance, user_id=user_id)
    return await store_avatar(
        session,
        user_id=user_id,
        data=drawn.data,
        content_type=drawn.content_type,
        store=store,
    )


async def try_on(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    outfit: str,
    renderer: AvatarRenderer,
    store: Any,
) -> MediaAsset:
    """Put an outfit on the avatar and keep the result as its own asset.

    Kept rather than returned and discarded, so the same outfit is not paid
    for twice when somebody scrolls back to it, and so a try-on can be shown
    beside the fit it came from.
    """
    # **A mannequin when they have no avatar of their own.**
    #
    # This used to refuse outright, and that refusal was the single
    # biggest hole in the feature: eight of the last eight try-ons
    # failed with "create your avatar first", which is a wall in
    # front of the thing somebody came to do. The figures were
    # already in the repository as bundled client assets and were
    # simply never reachable from here.
    from app.domain.mannequin import figure_to_dress

    found = await figure_to_dress(session, user_id=user_id, store=store)
    if found is None:
        raise NoAvatarYet()
    source, source_type = found

    dressed = await renderer.try_on(
        avatar=source,
        outfit=outfit,
        # What the figure actually is, not what the vendor defaults
        # to - and now that it may be a shipped mannequin rather
        # than a stored avatar, it comes back with the bytes.
        content_type=source_type,
        user_id=user_id,
    )
    return await store_avatar(
        session,
        user_id=user_id,
        data=dressed.data,
        content_type=dressed.content_type,
        store=store,
    )


__all__ = [
    "NoAvatarYet",
    "current_avatar",
    "generate_avatar",
    "read_appearance",
    "store_avatar",
    "try_on",
    "write_appearance",
]
