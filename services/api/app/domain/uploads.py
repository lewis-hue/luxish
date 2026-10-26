"""Upload authorisation.

Caps are decided and recorded **before** any bytes move: the client declares a
content type and length, the server refuses anything outside policy, and the
authorisation it hands back is short-lived and carries the byte ceiling the
storage backend will enforce.

Two backends are declared. The GCS signed-URL backend is the real one and is
**not implemented in Phase A** — it raises rather than returning something that
looks like a working integration (see the labelling rule in the plan).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CapabilityUnavailable, PayloadTooLarge, UnsupportedMediaType
from app.models.media_asset import MEDIA_KINDS, MediaAsset


@dataclass(frozen=True, slots=True)
class UploadAuthorization:
    asset_id: uuid.UUID
    upload_url: str
    expires_at: datetime
    max_bytes: int
    storage_mode: str
    required_headers: dict[str, str]


class UploadAuthorizer(Protocol):
    """What a storage backend must provide to authorise one upload."""

    storage_mode: str

    def authorize(
        self, *, asset_id: uuid.UUID, content_type: str, max_bytes: int, ttl_seconds: int
    ) -> tuple[str, dict[str, str]]: ...


class StubUploadAuthorizer:
    """Local development backend. **Simulated** — stores nothing.

    Returned URLs point at this service's own (not yet implemented) local
    receiver, and the response labels itself ``simulated`` so no caller can
    mistake it for object storage.
    """

    storage_mode = "simulated"

    def __init__(self, base_url: str = "http://localhost:8000/_dev/uploads") -> None:
        self.base_url = base_url.rstrip("/")

    def authorize(
        self, *, asset_id: uuid.UUID, content_type: str, max_bytes: int, ttl_seconds: int
    ) -> tuple[str, dict[str, str]]:
        return (
            f"{self.base_url}/{asset_id}",
            {"Content-Type": content_type, "X-Upload-Max-Bytes": str(max_bytes)},
        )


class GcsSignedUrlAuthorizer:
    """GCS V4 signed resumable upload (ADR-013). PLANNED, not implemented.

    It needs a service-account signing credential this build does not hold, so
    it refuses loudly instead of returning a URL that cannot work.
    """

    storage_mode = "gcs_signed_url"

    def __init__(self, *, bucket: str) -> None:
        self.bucket = bucket

    def authorize(
        self, *, asset_id: uuid.UUID, content_type: str, max_bytes: int, ttl_seconds: int
    ) -> tuple[str, dict[str, str]]:
        raise CapabilityUnavailable(
            "GCS signed upload URLs are not implemented in this build "
            "(no signing credential configured)."
        )


def build_authorizer(*, mode: str, bucket: str) -> UploadAuthorizer:
    if mode == "gcs_signed_url":
        return GcsSignedUrlAuthorizer(bucket=bucket)
    return StubUploadAuthorizer()


async def authorize_upload(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    content_type: str,
    content_length: int,
    allowed_content_types: tuple[str, ...],
    max_bytes: int,
    ttl_seconds: int,
    authorizer: UploadAuthorizer,
) -> UploadAuthorization:
    """Validate the declaration, then record and authorise one upload.

    Refusals happen before any row is written, so a rejected request leaves no
    trace to clean up.
    """
    normalised = content_type.split(";", 1)[0].strip().lower()
    if normalised not in allowed_content_types:
        raise UnsupportedMediaType(
            f"{content_type!r} is not an accepted upload type.",
            detail={"allowed": list(allowed_content_types)},
        )
    if kind not in MEDIA_KINDS:
        raise UnsupportedMediaType(
            f"{kind!r} is not a known media kind.", detail={"allowed": list(MEDIA_KINDS)}
        )
    if content_length > max_bytes:
        raise PayloadTooLarge(
            "The declared upload is larger than the permitted size.",
            detail={"max_bytes": max_bytes, "declared": content_length},
        )

    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    asset = MediaAsset(
        user_id=user_id,
        kind=kind,
        status="pending_upload",
        content_type=normalised,
        max_bytes=max_bytes,
        upload_authorized_until=expires_at,
    )
    session.add(asset)
    await session.flush()

    upload_url, headers = authorizer.authorize(
        asset_id=asset.id,
        content_type=normalised,
        max_bytes=max_bytes,
        ttl_seconds=ttl_seconds,
    )
    await session.commit()
    return UploadAuthorization(
        asset_id=asset.id,
        upload_url=upload_url,
        expires_at=expires_at,
        max_bytes=max_bytes,
        storage_mode=authorizer.storage_mode,
        required_headers=headers,
    )
