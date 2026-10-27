"""Upload authorisation and, in local development, upload receipt."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Request, Response, status

from app.deps import AuthDep, SessionDep, SettingsDep
from app.domain.uploads import authorize_upload, build_authorizer
from app.errors import ApiError
from app.models.media_asset import MediaAsset
from app.schemas.uploads import UploadAuthorizeRequest, UploadAuthorizeResponse
from app.storage.local import build_local_store

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "/authorize",
    response_model=UploadAuthorizeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def authorize(
    payload: UploadAuthorizeRequest,
    db: SessionDep,
    ctx: AuthDep,
    settings: SettingsDep,
) -> UploadAuthorizeResponse:
    """Authorise one upload: short-lived, capped, and owner-bound."""
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
            public_base_url=settings.public_base_url,
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


class UploadRejected(ApiError):
    status_code = 400
    code = "upload_rejected"
    default_message = "The upload could not be accepted."


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
