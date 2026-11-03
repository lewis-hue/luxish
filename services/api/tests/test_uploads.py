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

#: A real JPEG start-of-image marker, so the bytes under test look like
#: the thing the endpoint actually serves.
JPEG_MAGIC = bytes.fromhex("ffd8ff")





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

        GcsSignedUrlAuthorizer(bucket="luxish-test").authorize(

            asset_id=uuid.uuid4(), content_type="image/jpeg", max_bytes=1024, ttl_seconds=900

        )





# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# reading media back
# --------------------------------------------------------------------------- #
# A garment the server derived has no photograph on the device, so with no way
# to read one back, background removal and outfit detection both succeed and
# stay invisible. These pin the rules that make such an endpoint safe to have.


async def _stored_asset(
    client: httpx.AsyncClient, headers: dict[str, str], body: bytes
) -> uuid.UUID:
    """Authorise an upload and PUT ``body`` through the real receiver."""
    authorized = await client.post(
        "/v1/uploads/authorize",
        headers=headers,
        json={
            "kind": "garment_photo",
            "content_type": "image/jpeg",
            "content_length": len(body),
        },
    )
    assert authorized.status_code == 201, authorized.text
    asset_id = authorized.json()["asset_id"]
    put = await client.put(
        f"/v1/uploads/local/{asset_id}",
        headers={**headers, "Content-Type": "image/jpeg"},
        content=body,
    )
    assert put.status_code == 204, put.text
    return uuid.UUID(asset_id)


async def test_an_owner_reads_back_exactly_what_was_stored(
    local_media_client: httpx.AsyncClient, auth: Any
) -> None:
    await _sign_in(local_media_client, auth(sub="kc-read-1"))
    body = JPEG_MAGIC + b"garment bytes" * 16

    asset_id = await _stored_asset(local_media_client, auth(sub="kc-read-1"), body)

    read = await local_media_client.get(
        f"/v1/uploads/local/{asset_id}", headers=auth(sub="kc-read-1")
    )
    assert read.status_code == 200, read.text
    assert read.content == body
    assert read.headers["content-type"].startswith("image/jpeg")
    # An asset's bytes never change in place; a new version is a new id.
    assert "immutable" in read.headers.get("cache-control", "")


async def test_another_users_media_is_not_found_rather_than_forbidden(
    local_media_client: httpx.AsyncClient, auth: Any
) -> None:
    """403 would confirm the id exists, which is the thing worth hiding."""
    await _sign_in(local_media_client, auth(sub="kc-read-owner"))
    await _sign_in(local_media_client, auth(sub="kc-read-other"))
    asset_id = await _stored_asset(
        local_media_client, auth(sub="kc-read-owner"), JPEG_MAGIC + b"mine"
    )

    read = await local_media_client.get(
        f"/v1/uploads/local/{asset_id}", headers=auth(sub="kc-read-other")
    )
    assert read.status_code == 404


async def test_reading_media_requires_authentication(
    local_media_client: httpx.AsyncClient, auth: Any
) -> None:
    await _sign_in(local_media_client, auth(sub="kc-read-anon"))
    asset_id = await _stored_asset(
        local_media_client, auth(sub="kc-read-anon"), JPEG_MAGIC + b"x"
    )

    assert (await local_media_client.get(f"/v1/uploads/local/{asset_id}")).status_code == 401


async def test_a_deleted_asset_cannot_be_read_back_through_a_kept_url(
    local_media_client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """Deletion has to hold against a URL someone already has.

    The bytes may well still be on disk, since removing them is a separate
    concern, so the check that matters is the one on the row rather than on
    the filesystem.
    """
    user_id = await _sign_in(local_media_client, auth(sub="kc-read-deleted"))
    asset_id = await _stored_asset(
        local_media_client, auth(sub="kc-read-deleted"), JPEG_MAGIC + b"gone"
    )

    from app.domain.jobs import delete_asset

    await delete_asset(db, asset_id, user_id=user_id, reason="user_request")

    read = await local_media_client.get(
        f"/v1/uploads/local/{asset_id}", headers=auth(sub="kc-read-deleted")
    )
    assert read.status_code == 404


async def test_an_asset_with_no_bytes_yet_is_not_found(
    local_media_client: httpx.AsyncClient, auth: Any
) -> None:
    """Authorised but never uploaded. There is nothing to serve."""
    await _sign_in(local_media_client, auth(sub="kc-read-pending"))
    authorized = await local_media_client.post(
        "/v1/uploads/authorize",
        headers=auth(sub="kc-read-pending"),
        json={
            "kind": "garment_photo",
            "content_type": "image/jpeg",
            "content_length": 10,
        },
    )
    asset_id = authorized.json()["asset_id"]

    read = await local_media_client.get(
        f"/v1/uploads/local/{asset_id}", headers=auth(sub="kc-read-pending")
    )
    assert read.status_code == 404


async def test_an_asset_whose_bytes_vanished_is_not_found_rather_than_a_500(
    local_media_client: httpx.AsyncClient, local_media_root: Any, auth: Any
) -> None:
    """The row says uploaded and the object is gone.

    Distinct from "never uploaded", which is caught on the row before storage
    is touched. This path reaches the store, and the store reports a missing
    object as a capability failure rather than the builtin — so catching
    `FileNotFoundError` caught nothing and this returned 503, which also told
    anybody probing their own ids which rows exist.
    """
    await _sign_in(local_media_client, auth(sub="kc-read-vanished"))
    asset_id = await _stored_asset(
        local_media_client, auth(sub="kc-read-vanished"), JPEG_MAGIC + b"gone"
    )

    # Remove the object behind the row's back, the way a pruned disk would.
    removed = 0
    for candidate in local_media_root.iterdir():
        candidate.unlink()
        removed += 1
    assert removed > 0, "nothing was stored, so this proves nothing"

    read = await local_media_client.get(
        f"/v1/uploads/local/{asset_id}", headers=auth(sub="kc-read-vanished")
    )
    assert read.status_code == 404, f"expected 404, got {read.status_code}"
    assert read.json()["code"] == "upload_rejected"
