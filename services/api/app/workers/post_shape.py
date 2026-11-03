"""Bringing a posted picture into the shape the app draws it in.

**Why a worker and not the upload handler.** In a deployment the
client PUTs straight to object storage with a signed URL and this
service never sees the bytes at all - the local upload route exists
only so development predicts production. So there is no request
during which the picture could be reshaped. A job that reads it back
out of storage is the only place the work can happen, and it is the
same place in both environments.

**It never replaces the original.** The shaped picture is a new
asset and the post's cover is repointed at it; the photograph the
author uploaded stays exactly as they uploaded it. That matters for
more than sentiment: the description is pinned to the original
precisely so a vision model is not handed a rotated photograph, and
the original has to still be there for that to mean anything.

**It is not a paid call.** Rotating and padding is arithmetic on
pixels, so this costs a read, a write and no model time. A fit whose
picture is already inside the shell is left alone entirely, which is
almost all of them.
"""

from __future__ import annotations

import uuid
from typing import Any

SHAPE_JOB_KIND = "post.shape"


async def shape_post_cover(
    session: Any, job: Any, *, store: Any
) -> dict[str, Any]:
    """Reshape one post's cover if it is outside the shell. Idempotent.

    Returns what happened, for the job record. Doing nothing is the
    common outcome and is reported as such rather than as a failure.
    """
    import hashlib
    import logging

    import sqlalchemy as sa

    from app.errors import CapabilityUnavailable
    from app.models.media_asset import MediaAsset
    from app.models.posts import PostMedia
    from app.workers.shell_fit import fit_to_shell, measure, needs_fitting

    logger = logging.getLogger(__name__)
    payload = job.payload or {}
    raw = payload.get("post_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no post_id")
    post_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))

    link = await session.scalar(
        sa.select(PostMedia).where(
            PostMedia.post_id == post_id, PostMedia.position == 0
        )
    )
    if link is None:
        return {"post_id": str(post_id), "state": "no_picture"}

    asset = await session.get(MediaAsset, link.media_asset_id)
    if asset is None or not asset.storage_key or asset.deleted_at is not None:
        return {"post_id": str(post_id), "state": "no_picture"}

    # Already upright and inside the bounds. The common case, and the
    # cheapest possible answer to it.
    if (
        asset.width
        and asset.height
        and not needs_fitting(asset.width, asset.height, portrait=True)
    ):
        return {"post_id": str(post_id), "state": "already_fits"}

    try:
        data = await store.read(asset)
    except CapabilityUnavailable as exc:
        return {"post_id": str(post_id), "state": "unreadable", "reason": exc.code}

    shaped = fit_to_shell(
        data, content_type=asset.content_type or "image/jpeg", portrait=True
    )
    if shaped is data:
        # `fit_to_shell` hands back the same object when there was
        # nothing to do, which also covers a picture it could not
        # read. Recording the size it reports stops this job looking
        # at the same bytes again on every re-dispatch.
        size = measure(data)
        if size and not asset.width:
            asset.width, asset.height = size
            await session.commit()
        return {"post_id": str(post_id), "state": "already_fits"}

    size = measure(shaped)
    key = f"posts/{post_id}/shaped/{uuid.uuid4().hex[:12]}"
    try:
        await store.write(
            key, shaped, content_type=asset.content_type or "image/jpeg"
        )
    except CapabilityUnavailable as exc:
        return {"post_id": str(post_id), "state": "unwritable", "reason": exc.code}

    derived = MediaAsset(
        user_id=asset.user_id,
        kind=asset.kind,
        status="ready",
        content_type=asset.content_type,
        width=size[0] if size else None,
        height=size[1] if size else None,
        max_bytes=len(shaped),
        byte_size=len(shaped),
        storage_key=key,
        checksum_sha256=hashlib.sha256(shaped).hexdigest(),
        version=1,
        # Inherited, not assumed: this is the same picture in a
        # different frame, so it carries exactly the consent the
        # original carried.
        publication_consent=asset.publication_consent,
    )
    session.add(derived)
    await session.flush()

    link.media_asset_id = derived.id
    await session.commit()

    logger.info(
        "reshaped a posted picture",
        extra={"post": str(post_id), "from": str(asset.id), "to": str(derived.id)},
    )
    return {
        "post_id": str(post_id),
        "state": "reshaped",
        "asset_id": str(derived.id),
    }


__all__ = ["SHAPE_JOB_KIND", "shape_post_cover"]
