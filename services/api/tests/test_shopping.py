"""The curated shop, and the overclaims it is built to refuse.

§10's acceptance criteria as tests: resemblance can never yield
`confirmed_item`, an expired offer is labelled rather than dropped, and a
retailer badge cannot appear without a verification record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.models.shopping import Offer, Retailer, ShopProduct


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


@pytest.fixture
async def catalogue(engine: Any) -> dict[str, uuid.UUID]:
    """Three products at one retailer, one of them with a lapsed offer."""
    from app.db.session import session_factory

    maker = session_factory(engine)
    now = datetime.now(UTC)
    async with maker() as db:
        retailer = Retailer(slug="test-shop", name="Test Shop", homepage="https://example.com")
        db.add(retailer)
        await db.flush()

        def product(title: str, category: str, slot: str, colour: str | None, aes: list[str]) -> ShopProduct:
            row = ShopProduct(
                retailer_id=retailer.id,
                title=title,
                brand="Test",
                category_id=category,
                slot=slot,
                colour=colour,
                aesthetics=aes,
            )
            db.add(row)
            return row

        jacket = product("Leather jacket", "jacket", "outerwear", "black", ["downtown-romantic"])
        tee = product("Boxy tee", "tshirt", "tops", "charcoal", ["streetwear"])
        old = product("Old coat", "coat", "outerwear", "camel", ["quiet-luxury"])
        await db.flush()

        def offer(product_row: ShopProduct, *, expired: bool) -> Offer:
            return Offer(
                product_id=product_row.id,
                price_minor=499000,
                currency="KES",
                sizes=["M"],
                ships_to=["KE"],
                retrieved_at=now - (timedelta(days=40) if expired else timedelta()),
                expires_at=now + (timedelta(days=-10) if expired else timedelta(days=30)),
                source_url="https://example.com/search?q=x",
                evidence={"provider": "curated"},
            )

        db.add(offer(jacket, expired=False))
        db.add(offer(tee, expired=False))
        db.add(offer(old, expired=True))
        await db.commit()
        return {"jacket": jacket.id, "tee": tee.id, "old": old.id}


async def test_resemblance_never_claims_a_confirmed_item(
    client: httpx.AsyncClient, auth: Any, catalogue: dict[str, uuid.UUID]
) -> None:
    """§10 acceptance criterion 7, enforced where the label is made."""
    headers = auth(sub="kc-shop-1")
    await _sign_in(client, headers)

    r = await client.get(
        "/v1/shopping/search?category=jacket&colour=black", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "curated"
    assert len(body["items"]) >= 1
    for item in body["items"]:
        assert item["match_label"] == "similar_style"
        assert item["availability"] == "unverified"
        assert "matched" in item["evidence"]


async def test_an_expired_offer_is_labelled_not_dropped(
    client: httpx.AsyncClient, auth: Any, catalogue: dict[str, uuid.UUID]
) -> None:
    headers = auth(sub="kc-shop-2")
    await _sign_in(client, headers)

    r = await client.get("/v1/shopping/search?category=coat", headers=headers)
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["stale"] is True


async def test_the_badge_cannot_appear_without_verification(
    client: httpx.AsyncClient, auth: Any, catalogue: dict[str, uuid.UUID]
) -> None:
    headers = auth(sub="kc-shop-3")
    await _sign_in(client, headers)

    r = await client.get("/v1/shopping/search?category=jacket", headers=headers)
    for item in r.json()["items"]:
        assert item["retailer"]["verified"] is False


async def test_the_best_match_leads(
    client: httpx.AsyncClient, auth: Any, catalogue: dict[str, uuid.UUID]
) -> None:
    """Category plus colour beats category alone; an unrelated ask is empty."""
    headers = auth(sub="kc-shop-4")
    await _sign_in(client, headers)

    r = await client.get(
        "/v1/shopping/search?slot=outerwear&colour=black", headers=headers
    )
    items = r.json()["items"]
    assert items[0]["title"] == "Leather jacket"

    nothing = await client.get("/v1/shopping/search?category=swimwear", headers=headers)
    assert nothing.json()["items"] == []


async def test_recommendations_come_from_taste_not_thin_air(
    client: httpx.AsyncClient, auth: Any, catalogue: dict[str, uuid.UUID]
) -> None:
    """A fresh account gets no sections; a stated taste gets its own."""
    headers = auth(sub="kc-shop-5")
    await _sign_in(client, headers)

    empty = await client.get("/v1/shopping/recommendations", headers=headers)
    assert empty.json()["sections"] == []

    r = await client.put(
        "/v1/taste", json={"aesthetics": ["streetwear"]}, headers=headers
    )
    assert r.status_code in (200, 201), r.text

    full = (await client.get("/v1/shopping/recommendations", headers=headers)).json()
    keys = [section["key"] for section in full["sections"]]
    assert "taste" in keys
    taste_section = next(s for s in full["sections"] if s["key"] == "taste")
    assert any(item["title"] == "Boxy tee" for item in taste_section["items"])
