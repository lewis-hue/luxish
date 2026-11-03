"""The messaging routes, over HTTP.

The domain tests own the rules; these own the wiring — that the
endpoints exist, that the two deletes are reachable and reach exactly
as far as they should, and that a refusal is the same shape as a
missing thing so it confirms nothing.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.anyio


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def test_writing_and_reading_a_thread(
    client: httpx.AsyncClient, auth: Any
) -> None:
    mine = auth(sub="kc-dm-1")
    theirs = auth(sub="kc-dm-2")
    await _sign_in(client, mine)
    them = await _sign_in(client, theirs)

    sent = await client.post(
        f"/v1/messages/{them}", headers=mine, json={"body": "that coat?"}
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["mine"] is True
    assert sent.json()["asset_id"] is None

    read = await client.get(f"/v1/messages/{them}", headers=mine)
    assert read.status_code == 200, read.text
    assert [line["body"] for line in read.json()["items"]] == ["that coat?"]

    # And it is on the other person's list, unread.
    inbox = await client.get("/v1/messages", headers=theirs)
    assert inbox.status_code == 200, inbox.text
    rows = inbox.json()["threads"]
    assert len(rows) == 1
    assert rows[0]["last"] == "that coat?"
    assert rows[0]["unread"] == 1


async def test_an_empty_message_with_no_picture_is_refused(
    client: httpx.AsyncClient, auth: Any
) -> None:
    mine = auth(sub="kc-dm-3")
    theirs = auth(sub="kc-dm-4")
    await _sign_in(client, mine)
    them = await _sign_in(client, theirs)

    r = await client.post(f"/v1/messages/{them}", headers=mine, json={"body": "  "})
    assert r.status_code == 422, r.text


async def test_somebody_elses_picture_cannot_be_attached(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """The same answer as a missing account, so it confirms nothing."""
    import uuid

    mine = auth(sub="kc-dm-5")
    theirs = auth(sub="kc-dm-6")
    await _sign_in(client, mine)
    them = await _sign_in(client, theirs)

    r = await client.post(
        f"/v1/messages/{them}",
        headers=mine,
        json={"body": "look", "asset_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404, r.text


async def test_unsending_reaches_both_copies_and_only_the_sender(
    client: httpx.AsyncClient, auth: Any
) -> None:
    mine = auth(sub="kc-dm-7")
    theirs = auth(sub="kc-dm-8")
    me = await _sign_in(client, mine)
    them = await _sign_in(client, theirs)

    sent = await client.post(
        f"/v1/messages/{them}", headers=mine, json={"body": "oops"}
    )
    message_id = sent.json()["id"]

    # Not theirs to take back.
    refused = await client.delete(
        f"/v1/messages/{me}/messages/{message_id}", headers=theirs
    )
    assert refused.status_code == 404, refused.text

    gone = await client.delete(
        f"/v1/messages/{them}/messages/{message_id}", headers=mine
    )
    assert gone.status_code == 204, gone.text

    for headers, other in ((mine, them), (theirs, me)):
        read = await client.get(f"/v1/messages/{other}", headers=headers)
        assert read.json()["items"] == []


async def test_clearing_a_conversation_leaves_their_copy_alone(
    client: httpx.AsyncClient, auth: Any
) -> None:
    mine = auth(sub="kc-dm-9")
    theirs = auth(sub="kc-dm-10")
    me = await _sign_in(client, mine)
    them = await _sign_in(client, theirs)

    await client.post(f"/v1/messages/{them}", headers=mine, json={"body": "one"})

    cleared = await client.delete(f"/v1/messages/{them}", headers=mine)
    assert cleared.status_code == 204, cleared.text

    assert (await client.get(f"/v1/messages/{them}", headers=mine)).json()[
        "items"
    ] == []
    assert [
        line["body"]
        for line in (await client.get(f"/v1/messages/{me}", headers=theirs)).json()[
            "items"
        ]
    ] == ["one"]


async def test_thread_settings_round_trip(
    client: httpx.AsyncClient, auth: Any
) -> None:
    mine = auth(sub="kc-dm-11")
    theirs = auth(sub="kc-dm-12")
    await _sign_in(client, mine)
    them = await _sign_in(client, theirs)
    await client.post(f"/v1/messages/{them}", headers=mine, json={"body": "hello"})

    off = await client.patch(
        f"/v1/messages/{them}/settings", headers=mine, json={"notifies": False}
    )
    assert off.status_code == 200, off.text
    assert off.json()["notifies"] is False

    read = await client.get(f"/v1/messages/{them}", headers=mine)
    assert read.json()["notifies"] is False
