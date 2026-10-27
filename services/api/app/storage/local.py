"""Filesystem-backed media storage, for local development only.

The stub authorizer returns a URL that stores nothing and the GCS one refuses
for want of a signing credential, so until now no photograph could actually
reach the server. That made the whole media pipeline — categorisation,
background removal, the contact shadow — unreachable from the app despite
being implemented and tested. This is the missing backend.

**Local only, and enforced rather than documented.** :func:`build_local_store`
refuses outside the ``local`` environment. The reasons it must never run in a
deployment are concrete: it serves bytes from a local directory, so it does
not survive an instance being replaced; it has no CDN, no lifecycle rules and
no object versioning; and the receiving endpoint accepts a body the process
holds in memory, which is a denial-of-service surface that a signed upload
straight to object storage does not have.

The trade is deliberate. A developer gets the real end-to-end path — upload,
classify, segment, composite, read back — against the real database and the
real worker, and the only substituted part is where the bytes sit.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path

from app.errors import ApiError, CapabilityUnavailable
from app.models.media_asset import MediaAsset


class LocalStorageRefused(ApiError):
    """Local storage was requested outside local development."""

    status_code = 500
    code = "local_storage_refused"
    default_message = "Filesystem media storage is only available locally."


def _safe_name(key: str) -> str:
    """Flatten a storage key to a single filename.

    Keys come from our own code, not from a user, but a traversal bug here
    would write anywhere on disk, so the key is never used as a path. The
    hash keeps it collision-free and the suffix keeps it recognisable while
    debugging.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    tail = key.rsplit("/", 1)[-1][-40:]
    safe_tail = "".join(c if c.isalnum() or c in "._-" else "_" for c in tail)
    return f"{digest[:16]}__{safe_tail}"


class LocalFileAuthorizer:
    """Hands out a URL pointing at this service's own receiver.

    Unlike the stub it names a route that exists, so the client's PUT really
    stores something.
    """

    storage_mode = "local_file"

    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def authorize(
        self,
        *,
        asset_id: uuid.UUID,
        content_type: str,
        max_bytes: int,
        ttl_seconds: int,
    ) -> tuple[str, dict[str, str]]:
        return (
            f"{self.base_url}/v1/uploads/local/{asset_id}",
            {
                "Content-Type": content_type,
                "X-Upload-Max-Bytes": str(max_bytes),
            },
        )


class LocalMediaStore:
    """Reads originals and writes derivatives under one directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        return self.root / _safe_name(key)

    async def read(self, asset: MediaAsset) -> bytes:
        if not asset.storage_key:
            # Authorized but never uploaded. A capability error rather than a
            # crash, because both handlers treat it as "degrade" and the
            # garment keeps its original photograph.
            raise CapabilityUnavailable(
                "This asset has no stored object yet.",
                detail={"asset_id": str(asset.id), "reason": "not_uploaded"},
            )
        path = self.path_for(asset.storage_key)
        if not path.exists():
            raise CapabilityUnavailable(
                "The stored object is missing from local media storage.",
                detail={"asset_id": str(asset.id), "reason": "missing_object"},
            )
        # `to_thread` rather than an async file library: this is local-only
        # code and adding a dependency to the production image for it would be
        # the wrong trade.
        return await asyncio.to_thread(path.read_bytes)

    async def write(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self.path_for(key)
        # Write to a sibling then rename: a reader must never observe a
        # half-written cut-out, and on the same filesystem the rename is
        # atomic.
        staging = path.with_suffix(path.suffix + ".part")

        def _write() -> None:
            staging.write_bytes(data)
            staging.replace(path)

        await asyncio.to_thread(_write)


def build_local_store(*, environment: str, root: str) -> LocalMediaStore:
    """A local store, or a refusal outside local development."""
    if environment != "local":
        raise LocalStorageRefused(
            f"Filesystem media storage requested in environment {environment!r}. "
            "Configure object storage instead."
        )
    return LocalMediaStore(Path(root))


__all__ = [
    "LocalFileAuthorizer",
    "LocalMediaStore",
    "LocalStorageRefused",
    "build_local_store",
]
