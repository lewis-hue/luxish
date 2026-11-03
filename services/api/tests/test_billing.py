"""Subscriptions, and the three lies this slice refuses to tell.

A fixture reading as revenue; a cancellation clawing back paid time; and a
meter counting something other than what actually happened. Each is a test
here rather than a review comment.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.domain.billing import PLAN_ALLOWANCES


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def test_everyone_starts_on_the_free_plan_with_a_real_meter(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-bill-1")
    await _sign_in(client, headers)

    r = await client.get("/v1/billing/entitlements", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "free"
    assert body["state"] == "free"
    assert body["store"] is None
    assert body["allowance"] == PLAN_ALLOWANCES["free"]
    assert body["used"] == 0
    assert body["remaining"] == PLAN_ALLOWANCES["free"]
    assert body["simulated"] is False


async def test_a_simulated_subscription_says_it_is_simulated(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """The one non-negotiable: a fixture must never read as a live store."""
    headers = auth(sub="kc-bill-2")
    await _sign_in(client, headers)

    r = await client.post(
        "/v1/billing/simulated/subscribe", json={"plan": "plus"}, headers=headers
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan"] == "plus"
    assert body["state"] == "active"
    assert body["store"] == "simulated"
    assert body["simulated"] is True
    assert body["allowance"] == PLAN_ALLOWANCES["plus"]
    assert body["period_end"] is not None


async def test_subscribing_twice_does_not_stack(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-bill-3")
    await _sign_in(client, headers)

    first = await client.post(
        "/v1/billing/simulated/subscribe", json={}, headers=headers
    )
    second = await client.post(
        "/v1/billing/simulated/subscribe", json={}, headers=headers
    )
    assert second.status_code == 201
    assert second.json()["period_end"] == first.json()["period_end"]


async def test_cancelling_keeps_the_paid_period(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Cancel means "do not renew", never "lose what was paid for"."""
    headers = auth(sub="kc-bill-4")
    await _sign_in(client, headers)
    subscribed = await client.post(
        "/v1/billing/simulated/subscribe", json={}, headers=headers
    )

    r = await client.post(
        "/v1/billing/auto-renew", json={"auto_renew": False}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "plus"
    assert body["state"] == "ending"
    assert body["auto_renew"] is False
    # The period end did not move: the time already granted stays granted.
    assert body["period_end"] == subscribed.json()["period_end"]

    resumed = await client.post(
        "/v1/billing/auto-renew", json={"auto_renew": True}, headers=headers
    )
    assert resumed.json()["state"] == "active"


async def test_cancelling_the_free_plan_is_a_no_op(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-bill-5")
    await _sign_in(client, headers)
    r = await client.post(
        "/v1/billing/auto-renew", json={"auto_renew": False}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["plan"] == "free"


async def test_the_meter_counts_what_actually_happened(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Used is a count over the run history, not a stored counter."""
    headers = auth(sub="kc-bill-6")
    await _sign_in(client, headers)

    before = (await client.get("/v1/billing/entitlements", headers=headers)).json()
    assert before["used"] == 0

    r = await client.post(
        "/v1/stylist/runs", json={"text": "Something for a long day"}, headers=headers
    )
    assert r.status_code in (200, 201, 202), r.text

    after = (await client.get("/v1/billing/entitlements", headers=headers)).json()
    assert after["used"] == 1
    assert after["remaining"] == after["allowance"] - 1


async def test_entitlements_belong_to_exactly_one_person(
    client: httpx.AsyncClient, auth: Any
) -> None:
    one = auth(sub="kc-bill-7")
    await _sign_in(client, one)
    other = auth(sub="kc-bill-7-other")
    await _sign_in(client, other)

    await client.post("/v1/billing/simulated/subscribe", json={}, headers=one)

    r = await client.get("/v1/billing/entitlements", headers=other)
    assert r.json()["plan"] == "free"
