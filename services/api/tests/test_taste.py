"""Stated taste, and the four ways a preference screen stops meaning anything.

It becomes a wall somebody cannot get past; it cannot tell "declined" from
"not asked"; it offers answers the server rejects; or it makes a choice
impossible to take back. Three of those are silent.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.domain.taste import AESTHETICS, DEFAULT_LENS_ORDER, MAX_CHOICES, OCCASIONS


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def test_declining_is_a_real_answer(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """An empty body is somebody skipping, and that is distinguishable.

    "Asked and declined" and "never asked" are different states: one is a
    question still to put, the other an answer already given. A client that
    cannot tell them apart will either nag somebody who said no or never ask
    somebody who was never asked.
    """
    headers = auth(sub="kc-taste-1")
    await _sign_in(client, headers)

    before = await client.get("/v1/taste", headers=headers)
    assert before.json()["answered"] is False

    declined = await client.put("/v1/taste", json={}, headers=headers)
    assert declined.status_code == 200, declined.text
    assert declined.json()["answered"] is False

    # Still false, and that is correct — but the preference row now exists,
    # which is what a client checks to know the question was put.
    after = await client.get("/v1/taste", headers=headers)
    assert after.json()["answered"] is False


async def test_an_answer_is_recorded_and_read_back(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-taste-2")
    await _sign_in(client, headers)

    r = await client.put(
        "/v1/taste",
        json={
            "aesthetics": ["quiet-luxury", "minimalist"],
            "occasions": ["office", "evening"],
            "dress_code": "business",
            "goal": "more_from_what_i_own",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["answered"] is True

    back = (await client.get("/v1/taste", headers=headers)).json()
    assert back["aesthetics"] == ["quiet-luxury", "minimalist"]
    assert back["dress_code"] == "business"


async def test_deselecting_takes_it_back(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Re-answering overwrites rather than merging.

    Merge would make a choice impossible to withdraw — the same asymmetry
    consent deliberately avoids, and just as invisible: the aesthetic simply
    stays on the profile forever and the shelf never stops showing it.
    """
    headers = auth(sub="kc-taste-3")
    await _sign_in(client, headers)

    await client.put(
        "/v1/taste", json={"aesthetics": ["y2k", "gorpcore"]}, headers=headers
    )
    await client.put("/v1/taste", json={"aesthetics": ["y2k"]}, headers=headers)

    back = (await client.get("/v1/taste", headers=headers)).json()
    assert back["aesthetics"] == ["y2k"]


async def test_the_goal_decides_which_shelf_leads(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """The smallest useful thing a stated taste does, and it needs no model."""
    headers = auth(sub="kc-taste-4")
    await _sign_in(client, headers)

    r = await client.put(
        "/v1/taste", json={"goal": "more_from_what_i_own"}, headers=headers
    )
    assert r.json()["lens_order"][0] == "formula"

    r = await client.put("/v1/taste", json={"goal": "find_my_look"}, headers=headers)
    assert r.json()["lens_order"][0] == "aesthetic"

    # Every lens still appears. Leading one must not drop the others, or
    # answering a question would remove two thirds of Discover.
    assert sorted(r.json()["lens_order"]) == sorted(DEFAULT_LENS_ORDER)


async def test_nothing_said_gets_the_default_order(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-taste-5")
    await _sign_in(client, headers)
    back = (await client.get("/v1/taste", headers=headers)).json()
    assert back["lens_order"] == list(DEFAULT_LENS_ORDER)


async def test_an_answer_the_app_cannot_render_is_refused(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """A stored id matching no collection is an answer that silently does nothing."""
    headers = auth(sub="kc-taste-6")
    await _sign_in(client, headers)

    r = await client.put(
        "/v1/taste", json={"aesthetics": ["cottagecore"]}, headers=headers
    )
    assert r.status_code == 422, r.text


async def test_picking_everything_is_refused(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Somebody who picks every aesthetic has expressed no preference.

    Stored, it would make their shelf identical to the default while looking
    personalised — the worst of both, because nobody would think to check it.
    """
    headers = auth(sub="kc-taste-7")
    await _sign_in(client, headers)

    r = await client.put(
        "/v1/taste", json={"aesthetics": list(AESTHETICS)}, headers=headers
    )
    assert r.status_code == 422, r.text

    at_the_cap = await client.put(
        "/v1/taste",
        json={"aesthetics": list(AESTHETICS[:MAX_CHOICES])},
        headers=headers,
    )
    assert at_the_cap.status_code == 200, at_the_cap.text


async def test_the_same_answer_twice_is_refused(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-taste-8")
    await _sign_in(client, headers)
    r = await client.put(
        "/v1/taste", json={"occasions": ["office", "office"]}, headers=headers
    )
    assert r.status_code == 422, r.text


async def test_the_options_a_client_renders_are_the_ones_the_server_accepts(
    client: httpx.AsyncClient,
) -> None:
    """Served rather than hardcoded, and this is why.

    An aesthetic offered by the app but unknown to the server is an answer
    rejected after somebody taps it. One known to the server but not offered
    is a question nobody can answer. Both drift silently the moment the two
    lists live in two places.
    """
    r = await client.get("/v1/taste/options")
    assert r.status_code == 200, r.text
    options = r.json()
    assert options["aesthetics"] == list(AESTHETICS)
    assert options["occasions"] == list(OCCASIONS)
    assert options["max_choices"] == MAX_CHOICES


async def test_a_profile_belongs_to_exactly_one_person(
    client: httpx.AsyncClient, auth: Any
) -> None:
    mine = auth(sub="kc-taste-9")
    theirs = auth(sub="kc-taste-10")
    await _sign_in(client, mine)
    await _sign_in(client, theirs)

    await client.put("/v1/taste", json={"aesthetics": ["heritage"]}, headers=mine)
    assert (await client.get("/v1/taste", headers=theirs)).json()["aesthetics"] == []
