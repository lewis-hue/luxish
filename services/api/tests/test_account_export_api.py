"""The export routes, over HTTP.

The domain tests own the rules - what goes in, what never does, who
may read it. These own the wiring, and one of them is the only test
that exercises the thing an attacker would actually try: asking for
somebody else's export by id over the wire.

A refusal is the same 404 as a missing thing throughout, so it
confirms nothing. The object behind one of these ids is a person's
whole account, which is why that matters more here than anywhere else
in the service.
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


async def test_asking_for_one_and_watching_it(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """202 with a row to watch, then the same row on a GET.

    The shape every slow thing in this service uses: gathering reads
    every picture somebody owns out of object storage, so it cannot
    happen inside a request.
    """
    mine = auth(sub="kc-export-1")
    await _sign_in(client, mine)

    # Nothing yet.
    empty = await client.get("/v1/account/export", headers=mine)
    assert empty.status_code == 200, empty.text
    assert empty.json() is None

    asked = await client.post("/v1/account/export", headers=mine)
    assert asked.status_code == 202, asked.text
    body = asked.json()
    assert body["state"] == "gathering"
    assert body["byte_size"] is None

    seen = await client.get("/v1/account/export", headers=mine)
    assert seen.status_code == 200, seen.text
    assert seen.json()["id"] == body["id"]


async def test_asking_twice_hands_back_the_same_one(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """An impatient finger must not bill every picture read twice."""
    mine = auth(sub="kc-export-2")
    await _sign_in(client, mine)

    first = await client.post("/v1/account/export", headers=mine)
    second = await client.post("/v1/account/export", headers=mine)
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


async def test_somebody_elses_export_is_a_404(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """**The attack, over the wire.**

    404 and not 403: a 403 confirms the id exists, and what sits
    behind this one is a person's whole account - their wardrobe,
    their conversations and every picture they own.
    """
    mine = auth(sub="kc-export-3")
    theirs = auth(sub="kc-export-4")
    await _sign_in(client, mine)
    await _sign_in(client, theirs)

    asked = await client.post("/v1/account/export", headers=mine)
    export_id = asked.json()["id"]

    stolen = await client.get(
        f"/v1/account/export/{export_id}/file", headers=theirs
    )
    assert stolen.status_code == 404, stolen.text
    assert stolen.json()["code"] == "not_found"


async def test_an_unfinished_export_is_not_downloadable(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Same 404. There is no file yet, and saying which is saying too much."""
    mine = auth(sub="kc-export-5")
    await _sign_in(client, mine)

    asked = await client.post("/v1/account/export", headers=mine)
    early = await client.get(
        f"/v1/account/export/{asked.json()['id']}/file", headers=mine
    )
    assert early.status_code == 404, early.text


async def test_an_id_that_does_not_exist_is_the_same_404(
    client: httpx.AsyncClient, auth: Any
) -> None:
    mine = auth(sub="kc-export-6")
    await _sign_in(client, mine)
    missing = await client.get(
        "/v1/account/export/00000000-0000-4000-8000-000000000000/file",
        headers=mine,
    )
    assert missing.status_code == 404, missing.text


async def test_none_of_it_is_reachable_without_signing_in(
    client: httpx.AsyncClient,
) -> None:
    """Three routes, three refusals.

    Listed one by one rather than trusting the dependency: this is the
    router where an unauthenticated path would serve a stranger's
    account.
    """
    for method, path in (
        ("POST", "/v1/account/export"),
        ("GET", "/v1/account/export"),
        (
            "GET",
            "/v1/account/export/00000000-0000-4000-8000-000000000000/file",
        ),
    ):
        r = await client.request(method, path)
        assert r.status_code in {401, 403}, f"{method} {path} -> {r.status_code}"


async def test_a_finished_export_downloads_as_a_zip(
    client: httpx.AsyncClient, auth: Any, db: Any
) -> None:
    """End to end: ask, build, download, open it.

    The one test that proves the whole path, including that the bytes
    the route serves are the bytes the worker wrote.
    """
    import io
    import json
    import uuid
    import zipfile

    from app.config import get_settings
    from app.models.account_export import AccountExport
    from app.workers.runner import build_media_store
    from app.workers.account_export import build_export

    mine = auth(sub="kc-export-7")
    user_id = await _sign_in(client, mine)

    asked = await client.post("/v1/account/export", headers=mine)
    export_id = uuid.UUID(asked.json()["id"])

    # Built through the same store the route reads through. Not
    # `build_local_store`: that refuses outside local development, and
    # the route calling it was a real defect this test found.
    store = build_media_store(get_settings())

    class Job:
        id = uuid.uuid4()
        payload = {"export_id": str(export_id)}

    row = await db.get(AccountExport, export_id)
    assert row is not None, "the POST did not persist a row"
    outcome = await build_export(db, Job(), store=store)
    assert outcome["state"] == "ready", outcome

    got = await client.get(
        f"/v1/account/export/{export_id}/file", headers=mine
    )
    assert got.status_code == 200, got.text
    assert got.headers["content-type"] == "application/zip"
    # Never cached: a copy in a proxy outlives the deadline on the row.
    assert "no-store" in got.headers["cache-control"]
    assert "attachment" in got.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(got.content)) as archive:
        manifest = json.loads(archive.read("my-data.json"))
    assert manifest["export_version"] == 1
    # The account block is present and dated. Not asserting on the
    # email: the test identity signs in through a token that carries
    # none, so a non-null email here would be a fact about the
    # fixture rather than about the export.
    assert "account" in manifest
    assert manifest["account"]["joined_at"]
    # Every section the screen promises is a key, even when empty, so
    # somebody opening the file can tell "nothing here" from
    # "forgotten".
    for section in ("wardrobe", "fits", "comments", "boards", "plans",
                    "conversations", "what_you_agreed_to", "pictures"):
        assert section in manifest, f"{section} is missing from the export"
        assert isinstance(manifest[section], list)
    # It says what it refused to include, in the file itself.
    assert "push_tokens" in manifest["not_included"]
    assert str(user_id)  # the sign-in produced one, used above
