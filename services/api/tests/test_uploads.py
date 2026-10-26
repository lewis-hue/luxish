"""Task 5 — upload authorisation.

A short-lived authorisation with byte and content-type caps, declared *before*
any bytes move. The caps are enforced server-side at authorisation time so an
oversized or unsupported upload is refused without touching storage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from app.models.media_asset import MediaAsset


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return uuid.UUID(r.json()["user_id"])


async def test_authorize_returns_a_short_lived_capped_authorisation(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    user_id = await _sign_in(client, auth(sub="kc-u1"))

    r = await client.post(
        "/v1/uploads/authorize",
        headers=auth(sub="kc-u1"),
        json={"kind": "garment_photo", "content_type": "image/jpeg", "content_length": 1_000_000},
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["upload_url"]
    assert body["asset_id"]
    assert body["max_bytes"] >= 1_000_000
    expires_at = datetime.fromisoformat(body["expires_at"])
    delta = (expires_at - datetime.now(UTC)).total_seconds()
    assert 0 < delta <= 3600, "an upload authorisation must be short-lived"

    asset = await db.get(MediaAsset, uuid.UUID(body["asset_id"]))
    assert asset is not None
    assert asset.user_id == user_id
    assert asset.status == "pending_upload"
    assert asset.content_type == "image/jpeg"
    assert asset.max_bytes == body["max_bytes"]


async def test_declared_length_over_the_cap_is_refused(
    client: httpx.AsyncClient, auth: Any
) -> None:
    await _sign_in(client, auth(sub="kc-u2"))
    r = await client.post(
        "/v1/uploads/authorize",
        headers=auth(sub="kc-u2"),
        json={
            "kind": "garment_photo",
            "content_type": "image/jpeg",
            "content_length": 500 * 1024 * 1024,
        },
    )
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"
    assert r.json()["detail"]["max_bytes"] > 0


async def test_unsupported_content_type_is_refused(
    client: httpx.AsyncClient, auth: Any
) -> None:
    await _sign_in(client, auth(sub="kc-u3"))
    r = await client.post(
        "/v1/uploads/authorize",
        headers=auth(sub="kc-u3"),
        json={
            "kind": "garment_photo",
            "content_type": "application/x-msdownload",
            "content_length": 1024,
        },
    )
    assert r.status_code == 415
    assert r.json()["code"] == "unsupported_media_type"
    assert "image/jpeg" in r.json()["detail"]["allowed"]


async def test_no_asset_row_is_created_for_a_refused_authorisation(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    from sqlalchemy import func, select

    await _sign_in(client, auth(sub="kc-u4"))
    await client.post(
        "/v1/uploads/authorize",
        headers=auth(sub="kc-u4"),
        json={"kind": "garment_photo", "content_type": "text/html", "content_length": 10},
    )
    assert (await db.scalar(select(func.count()).select_from(MediaAsset))) == 0


async def test_a_zero_or_negative_length_is_rejected(
    client: httpx.AsyncClient, auth: Any
) -> None:
    await _sign_in(client, auth(sub="kc-u5"))
    r = await client.post(
        "/v1/uploads/authorize",
        headers=auth(sub="kc-u5"),
        json={"kind": "garment_photo", "content_type": "image/jpeg", "content_length": 0},
    )
    assert r.status_code == 422


async def test_upload_authorisation_requires_authentication(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/v1/uploads/authorize",
        json={"kind": "garment_photo", "content_type": "image/jpeg", "content_length": 10},
    )
    assert r.status_code == 401


async def test_the_simulated_storage_backend_is_labelled_as_such(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """A fixture must never read as a live integration."""
    await _sign_in(client, auth(sub="kc-u6"))
    r = await client.post(
        "/v1/uploads/authorize",
        headers=auth(sub="kc-u6"),
        json={"kind": "garment_photo", "content_type": "image/png", "content_length": 2048},
    )
    assert r.json()["storage_mode"] == "simulated"


async def test_gcs_signing_is_declared_unavailable_rather_than_faked(
    client: httpx.AsyncClient, auth: Any
) -> None:
    import pytest

    from app.domain.uploads import GcsSignedUrlAuthorizer
    from app.errors import CapabilityUnavailable

    with pytest.raises(CapabilityUnavailable):
        GcsSignedUrlAuthorizer(bucket="atelier-test").authorize(
            asset_id=uuid.uuid4(), content_type="image/jpeg", max_bytes=1024, ttl_seconds=900
        )
