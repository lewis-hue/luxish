"""The name and photograph somebody sets about themselves.

The interesting half of this endpoint is not the happy path. It is that a
media asset id arriving from a client is a *claim* about ownership, and that
the three-valued body has to tell "leave it alone" apart from "clear it" —
both of which fail silently and plausibly if they are wrong.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.models.media_asset import MediaAsset


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    response = await client.post("/v1/auth/session", headers=headers)
    assert response.status_code == 200
    return uuid.UUID(response.json()["user_id"])


async def _media_for(engine: Any, user_id: uuid.UUID) -> uuid.UUID:
    """A media row owned by `user_id`, created directly.

    Going through the upload endpoints would test those instead; what this
    file needs is simply a row with a known owner.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        asset = MediaAsset(
            user_id=user_id,
            kind="garment_photo",
            content_type="image/webp",
            max_bytes=1_000_000,
            storage_key=f"k/{uuid.uuid4()}",
        )
        session.add(asset)
        await session.commit()
        return asset.id


@pytest.mark.asyncio
async def test_a_display_name_can_be_set_and_cleared(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-name", email="someone@example.com")
    await _sign_in(client, headers)

    set_it = await client.patch(
        "/v1/auth/me", headers=headers, json={"display_name": "  Ada Lovelace  "}
    )
    assert set_it.status_code == 200
    # Trimmed on the way in, so a name is not stored with the whitespace
    # somebody's keyboard added.
    assert set_it.json()["display_name"] == "Ada Lovelace"

    # Read back rather than trusting the write's own response. The endpoint
    # returned the right body while persisting nothing at all until this was
    # checked: the domain flushed without committing, and the session rolled
    # back on the way out.
    assert (await client.get("/v1/auth/me", headers=headers)).json()[
        "display_name"
    ] == "Ada Lovelace"

    cleared = await client.patch("/v1/auth/me", headers=headers, json={"display_name": ""})
    assert cleared.status_code == 200
    # Empty means "use my email again", not a name made of nothing.
    assert cleared.json()["display_name"] is None
    assert (await client.get("/v1/auth/me", headers=headers)).json()[
        "display_name"
    ] is None


@pytest.mark.asyncio
async def test_omitting_a_field_leaves_it_alone(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    headers = auth(sub="kc-partial", email="partial@example.com")
    user_id = await _sign_in(client, headers)
    asset_id = await _media_for(engine, user_id)

    await client.patch(
        "/v1/auth/me",
        headers=headers,
        json={"display_name": "Grace", "profile_photo_asset_id": str(asset_id)},
    )
    # Editing only the name must not blank the photograph. This is the whole
    # reason the body is three-valued rather than a full replacement.
    only_name = await client.patch(
        "/v1/auth/me", headers=headers, json={"display_name": "Grace Hopper"}
    )
    assert only_name.status_code == 200
    assert only_name.json()["display_name"] == "Grace Hopper"
    assert only_name.json()["profile_photo_asset_id"] == str(asset_id)


@pytest.mark.asyncio
async def test_an_explicit_null_removes_the_photograph(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    headers = auth(sub="kc-remove", email="remove@example.com")
    user_id = await _sign_in(client, headers)
    asset_id = await _media_for(engine, user_id)

    await client.patch(
        "/v1/auth/me", headers=headers, json={"profile_photo_asset_id": str(asset_id)}
    )
    # Prove it was actually set first, or the removal below passes whether or
    # not anything ever happened.
    assert (await client.get("/v1/auth/me", headers=headers)).json()[
        "profile_photo_asset_id"
    ] == str(asset_id)

    removed = await client.patch(
        "/v1/auth/me", headers=headers, json={"profile_photo_asset_id": None}
    )
    assert removed.status_code == 200
    assert removed.json()["profile_photo_asset_id"] is None
    assert (await client.get("/v1/auth/me", headers=headers)).json()[
        "profile_photo_asset_id"
    ] is None


@pytest.mark.asyncio
async def test_a_photograph_belonging_to_somebody_else_is_refused(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    owner = auth(sub="kc-owner-photo", email="owner@example.com")
    owner_id = await _sign_in(client, owner)
    asset_id = await _media_for(engine, owner_id)

    intruder = auth(sub="kc-intruder", email="intruder@example.com")
    await _sign_in(client, intruder)

    stolen = await client.patch(
        "/v1/auth/me", headers=intruder, json={"profile_photo_asset_id": str(asset_id)}
    )
    # 404, not 403: telling the caller the id exists but belongs to somebody
    # else confirms the existence of another person's media, which is exactly
    # what the ownership check is for.
    assert stolen.status_code == 404
    assert stolen.json()["code"] == "media_not_found"


@pytest.mark.asyncio
async def test_an_unknown_photograph_is_refused(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-unknown-photo", email="unknown@example.com")
    await _sign_in(client, headers)
    response = await client.patch(
        "/v1/auth/me",
        headers=headers,
        json={"profile_photo_asset_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_email_cannot_be_written_through_this_endpoint(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-email-write", email="real@example.com")
    await _sign_in(client, headers)
    response = await client.patch(
        "/v1/auth/me", headers=headers, json={"email": "spoofed@example.com"}
    )
    # Rejected outright rather than ignored. The email comes from the token on
    # every sign-in, so accepting it would let a client write a claim that is
    # silently overwritten minutes later — the worst of both.
    assert response.status_code == 422
