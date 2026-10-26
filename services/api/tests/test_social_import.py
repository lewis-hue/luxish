"""Task 10 — social link references (ADR-009).

A pasted link is stored as a reference with attribution. We do **not** download,
store, or run perception over platform-hosted media, and the capability record
says so in six independent booleans rather than implying a capability we do not
have. The honest alternative — user-supplied media — is named in the response.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.social_import import (
    CAPABILITIES,
    PlatformCapability,
    canonicalise,
    classify_platform,
)
from app.models.external_reference import ExternalReference

API_ROOT = Path(__file__).resolve().parents[1]


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return uuid.UUID(r.json()["user_id"])


# --------------------------------------------------------------------------- #
# the honest capability report
# --------------------------------------------------------------------------- #
async def test_instagram_link_reports_no_analysis_and_offers_alternative(
    client: httpx.AsyncClient, auth: Any
) -> None:
    await _sign_in(client, auth(sub="kc-s1"))

    r = await client.post(
        "/v1/social/references",
        headers=auth(sub="kc-s1"),
        json={"url": "https://www.instagram.com/p/ABC123/"},
    )

    assert r.status_code == 201, r.text
    body = r.json()
    cap = body["capability"]
    assert cap["can_embed"] is True
    assert cap["can_analyse"] is False  # criterion 8
    assert body["alternative"] == "user_supplied_media"
    assert body["platform"] == "instagram"
    assert body["reference_id"]


def test_the_capability_record_has_six_independent_booleans() -> None:
    fields = PlatformCapability.model_fields
    assert set(fields) == {
        "can_embed",
        "can_read_metadata",
        "can_access_media",
        "can_analyse",
        "can_store",
        "authorised_now",
    }
    assert all(field.annotation is bool for field in fields.values())


@pytest.mark.parametrize("platform", sorted(CAPABILITIES))
def test_no_platform_claims_media_access_or_analysis(platform: str) -> None:
    """ADR-009: a public URL is not permission to fetch and analyse the media."""
    cap = CAPABILITIES[platform]
    assert cap.can_access_media is False
    assert cap.can_analyse is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.instagram.com/p/ABC123/", "instagram"),
        ("https://instagram.com/reel/XYZ/", "instagram"),
        ("https://www.tiktok.com/@user/video/123", "tiktok"),
        ("https://vm.tiktok.com/ABC/", "tiktok"),
        ("https://www.pinterest.com/pin/12345/", "pinterest"),
        ("https://pin.it/abc", "pinterest"),
        ("https://example.com/a-blog-post", "other"),
    ],
)
def test_platform_classification(url: str, expected: str) -> None:
    assert classify_platform(url) == expected


def test_canonicalisation_strips_tracking_parameters() -> None:
    canonical = canonicalise(
        "https://www.instagram.com/p/ABC123/?igshid=abc&utm_source=x&hl=en"
    )
    assert canonical == "https://www.instagram.com/p/ABC123/"


def test_canonicalisation_keeps_a_meaningful_query() -> None:
    assert canonicalise("https://example.com/search?q=linen") == (
        "https://example.com/search?q=linen"
    )


# --------------------------------------------------------------------------- #
# persistence and attribution
# --------------------------------------------------------------------------- #
async def test_the_reference_records_url_platform_author_and_timestamp(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await _sign_in(client, auth(sub="kc-s2"))
    r = await client.post(
        "/v1/social/references",
        headers=auth(sub="kc-s2"),
        json={"url": "https://www.tiktok.com/@stylist/video/999?utm_source=share"},
    )
    assert r.status_code == 201

    reference = await db.get(ExternalReference, uuid.UUID(r.json()["reference_id"]))
    assert reference is not None
    assert reference.user_id == user_id
    assert reference.platform == "tiktok"
    assert reference.canonical_url == "https://www.tiktok.com/@stylist/video/999"
    assert reference.author_handle == "stylist"
    assert reference.observed_at is not None
    assert reference.media_downloaded is False


async def test_pasting_the_same_link_twice_yields_one_reference(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    await _sign_in(client, auth(sub="kc-s3"))
    payload = {"url": "https://www.instagram.com/p/SAME/"}
    first = await client.post("/v1/social/references", headers=auth(sub="kc-s3"), json=payload)
    second = await client.post("/v1/social/references", headers=auth(sub="kc-s3"), json=payload)

    assert first.json()["reference_id"] == second.json()["reference_id"]
    assert (await db.scalar(sa.select(sa.func.count()).select_from(ExternalReference))) == 1


async def test_two_users_pasting_the_same_link_keep_separate_references(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    await _sign_in(client, auth(sub="kc-s4a"))
    await _sign_in(client, auth(sub="kc-s4b"))
    payload = {"url": "https://www.pinterest.com/pin/777/"}
    a = await client.post("/v1/social/references", headers=auth(sub="kc-s4a"), json=payload)
    b = await client.post("/v1/social/references", headers=auth(sub="kc-s4b"), json=payload)
    assert a.json()["reference_id"] != b.json()["reference_id"]


async def test_a_reference_is_private_to_its_owner(
    client: httpx.AsyncClient, auth: Any
) -> None:
    await _sign_in(client, auth(sub="kc-s5a"))
    await _sign_in(client, auth(sub="kc-s5b"))
    created = await client.post(
        "/v1/social/references",
        headers=auth(sub="kc-s5a"),
        json={"url": "https://www.instagram.com/p/PRIV/"},
    )
    reference_id = created.json()["reference_id"]

    stranger = await client.get(
        f"/v1/social/references/{reference_id}", headers=auth(sub="kc-s5b")
    )
    assert stranger.status_code == 404  # 404, not 403


async def test_an_unsafe_url_is_refused(client: httpx.AsyncClient, auth: Any) -> None:
    await _sign_in(client, auth(sub="kc-s6"))
    for url in ("http://169.254.169.254/", "file:///etc/passwd", "http://127.0.0.1/"):
        r = await client.post(
            "/v1/social/references", headers=auth(sub="kc-s6"), json={"url": url}
        )
        assert r.status_code in (400, 422), url


async def test_social_references_require_authentication(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/v1/social/references", json={"url": "https://www.instagram.com/p/A/"}
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# ADR-009, enforced structurally
# --------------------------------------------------------------------------- #
async def test_storing_a_reference_performs_no_network_request(
    client: httpx.AsyncClient, auth: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A link is stored on its own evidence. Nothing is fetched."""
    from app.security import urlfetch

    async def explode(*args: Any, **kwargs: Any):
        raise AssertionError("social import must not fetch anything")

    monkeypatch.setattr(urlfetch, "safe_fetch", explode)
    await _sign_in(client, auth(sub="kc-s7"))
    r = await client.post(
        "/v1/social/references",
        headers=auth(sub="kc-s7"),
        json={"url": "https://www.instagram.com/p/NOFETCH/"},
    )
    assert r.status_code == 201


def test_no_module_downloads_platform_hosted_media() -> None:
    """A grep is a blunt instrument, but this is a bright line (ADR-009)."""
    forbidden = (
        "cdninstagram",
        "scontent.cdninstagram",
        "graph.instagram.com",
        "oembed",
        "tiktokcdn",
        "pinimg.com",
        "ytimg.com",
        "yt-dlp",
        "youtube_dl",
        "instaloader",
    )
    offenders: list[str] = []
    for path in (API_ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == [], offenders
