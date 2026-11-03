"""Upload authorisation and, in local development, upload receipt."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Request, Response, status

from app.deps import AuthDep, SessionDep, SettingsDep
from app.domain.uploads import authorize_upload, build_authorizer
from app.errors import ApiError, CapabilityUnavailable
from app.models.media_asset import MediaAsset
from app.schemas.uploads import UploadAuthorizeRequest, UploadAuthorizeResponse
from app.storage.local import build_local_store

router = APIRouter(prefix="/uploads", tags=["uploads"])


class UploadRejected(ApiError):
    status_code = 400
    code = "upload_rejected"
    default_message = "The upload could not be accepted."


@router.post(
    "/authorize",
    response_model=UploadAuthorizeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def authorize(
    payload: UploadAuthorizeRequest,
    request: Request,
    db: SessionDep,
    ctx: AuthDep,
    settings: SettingsDep,
) -> UploadAuthorizeResponse:
    """Authorise one upload: short-lived, capped, and owner-bound."""
    # **The local receiver's address is taken from this request, not from
    # configuration.** `public_base_url` defaulted to 127.0.0.1, so a phone
    # on the LAN was told to PUT its photograph to its own loopback: the
    # authorisation returned 201, the upload died on the device, and the
    # server log showed nothing at all — which is exactly how it was found.
    # The one base URL every client can provably reach is the one it just
    # used to ask, so for the local backend that is the one handed back.
    # Deployed storage modes ignore this: a signed GCS URL names the bucket.
    request_base = str(request.base_url).rstrip("/")
    authorization = await authorize_upload(
        db,
        user_id=ctx.user_id,
        kind=payload.kind,
        content_type=payload.content_type,
        content_length=payload.content_length,
        allowed_content_types=settings.upload_allowed_content_types,
        max_bytes=settings.upload_max_bytes,
        ttl_seconds=settings.upload_authorization_ttl_seconds,
        authorizer=build_authorizer(
            mode=settings.upload_storage_mode,
            bucket=settings.gcs_bucket,
            public_base_url=request_base or settings.public_base_url,
        ),
    )
    return UploadAuthorizeResponse(
        asset_id=authorization.asset_id,
        upload_url=authorization.upload_url,
        expires_at=authorization.expires_at,
        max_bytes=authorization.max_bytes,
        storage_mode=authorization.storage_mode,
        required_headers=authorization.required_headers,
    )


@router.get(
    "/local/{asset_id}",
    include_in_schema=False,
    response_class=Response,
)
async def serve_local_media(
    asset_id: uuid.UUID,
    db: SessionDep,
    ctx: AuthDep,
    settings: SettingsDep,
) -> Response:
    """Serve the bytes of one asset the caller owns. **Local development only.**

    Hidden from the OpenAPI document for the same reason the receiver is: in a
    deployment the client fetches a signed URL straight from object storage and
    this service never carries the bytes. It exists so that local development
    can show a cut-out at all, because without it a garment the server derived
    has no image a phone can fetch.

    Ownership is checked against the requesting user, and an asset belonging to
    someone else is a 404 rather than a 403: a 403 would confirm the id exists.
    A deleted asset is a 404 too, whatever is still on disk, so a tombstoned
    photograph cannot be read back through a URL someone kept.
    """
    asset = await db.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.deleted_at.is_(None),
        )
    )
    if asset is None or asset.storage_key is None or asset.status not in {
        "uploaded",
        "ready",
    }:
        raise UploadRejected("No such media.", status_code=404)

    # Somebody else's photograph is readable only while a fit that is
    # published *right now* carries it.
    #
    # This asked `publication_consent is True` once, which is a flag set
    # on publish and never cleared: deleting the fit, a moderator
    # removing it, or blocking its author all left the bytes fetchable
    # forever by anyone who had seen the asset id in a feed payload. The
    # live check cannot drift because there is no flag to forget. Still a
    # 404 rather than a 403, so the refusal confirms nothing.
    if asset.user_id != ctx.user_id:
        from app.domain.messages import attachment_is_in_a_thread_with
        from app.domain.posts import (
            media_is_published_to,
            piece_is_published_to,
        )

        # Two ways somebody else's picture is yours to see: a fit that
        # is published right now carries it, or it was sent to you in a
        # message. Both are asked per request rather than flagged on
        # the asset, so neither can drift when the fit comes down or
        # the thread is blocked away.
        allowed = (
            await media_is_published_to(
                db, viewer_id=ctx.user_id, asset_id=asset_id
            )
            # A garment cut out of a published fit, so the stylised
            # figure can wear the real thing. Asked the same way and
            # of the same row, so it stops being readable at exactly
            # the moment the fit does.
            or await piece_is_published_to(
                db, viewer_id=ctx.user_id, asset_id=asset_id
            )
            or await attachment_is_in_a_thread_with(
                db, viewer_id=ctx.user_id, asset_id=asset_id
            )
        )
        if not allowed:
            raise UploadRejected("No such media.", status_code=404)

    store = build_local_store(
        environment=settings.environment, root=settings.local_media_root
    )
    try:
        body = await store.read(asset)
    except CapabilityUnavailable:
        # The row says the bytes exist and they do not. Reported as missing
        # rather than as a server error: there is nothing to retry, and a 503
        # would also distinguish "row exists, object gone" from "no such
        # asset" to anybody probing their own ids.
        #
        # `CapabilityUnavailable`, not `FileNotFoundError`: the store reports a
        # missing object as a capability failure, so catching the builtin
        # caught nothing and this returned 503.
        raise UploadRejected("No such media.", status_code=404) from None

    return Response(
        content=body,
        media_type=asset.content_type,
        headers={
            # Immutable: an asset's bytes never change in place. A new version
            # is a new asset id, so a cached copy can never go stale.
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Length": str(len(body)),
        },
    )


@router.put(
    "/local/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def receive_local_upload(
    asset_id: uuid.UUID,
    request: Request,
    db: SessionDep,
    ctx: AuthDep,
    settings: SettingsDep,
) -> Response:
    """Receive the bytes for one authorised asset. **Local development only.**

    Hidden from the OpenAPI document (`include_in_schema=False`) because it is
    not part of the product's contract: in a deployment the client PUTs
    straight to object storage with a signed URL and this service never sees
    the bytes at all. Publishing it would invite a client to depend on it.

    Everything the signed-URL path enforces in the storage layer is enforced
    here instead, because the two must accept exactly the same uploads or
    local development stops predicting production:

    * the asset must belong to the caller, so an id from someone else's
      wardrobe is a 404 rather than a 403, which would confirm it exists;
    * the authorisation must not have expired;
    * the asset must still be awaiting its upload, so a second PUT cannot
      silently replace a photograph that has already been categorised;
    * the body must not exceed the cap the authorisation issued.
    """
    store = build_local_store(
        environment=settings.environment, root=settings.local_media_root
    )

    asset = await db.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == asset_id, MediaAsset.user_id == ctx.user_id
        )
    )
    if asset is None:
        raise UploadRejected("No such upload authorisation.", status_code=404)

    now = datetime.now(UTC)
    if asset.upload_authorized_until and asset.upload_authorized_until < now:
        raise UploadRejected("This upload authorisation has expired.")
    if asset.status != "pending_upload":
        raise UploadRejected(
            f"This asset is already {asset.status}.",
            detail={"status": asset.status},
        )

    body = await request.body()
    if not body:
        raise UploadRejected("The upload body was empty.")
    if len(body) > asset.max_bytes:
        raise UploadRejected(
            "The upload exceeds the size this authorisation allows.",
            detail={"max_bytes": asset.max_bytes, "received": len(body)},
        )

    key = f"users/{ctx.user_id}/media/{asset.id}"
    await store.write(key, body, content_type=asset.content_type)

    asset.storage_key = key
    asset.byte_size = len(body)
    # Recorded so a later read can prove it got back what it stored, which is
    # the one guarantee a filesystem gives less readily than object storage.
    asset.checksum_sha256 = hashlib.sha256(body).hexdigest()
    asset.status = "uploaded"
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
