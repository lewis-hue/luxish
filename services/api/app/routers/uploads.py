"""Upload authorisation routes."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep, SettingsDep
from app.domain.uploads import authorize_upload, build_authorizer
from app.schemas.uploads import UploadAuthorizeRequest, UploadAuthorizeResponse

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
            mode=settings.upload_storage_mode, bucket=settings.gcs_bucket
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
