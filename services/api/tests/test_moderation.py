"""Blocks and reports, and the disclosures a block must never make.

The invariants here are the quiet ones: a block that leaks its own
existence, a severed follow that comes back to life, a member page that
answers differently for "gone" and "blocked you".

A block also clears the blocked person's fits out of the feed. That one
lives in `test_posts.py`, beside the feed it is about - it used to be
asserted here against a feed of saved catalogue looks, which no longer
exists.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def _grant_sharing(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    r = await client.put(
        "/v1/consents/community_sharing",
        json={"granted": True, "source": "test"},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text


async def test_blocking_severs_follows_both_ways(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-mod-1")
    my_id = await _sign_in(client, me)
    them = auth(sub="kc-mod-1-other")
    their_id = await _sign_in(client, them)

    assert (await client.put(f"/v1/community/follows/{their_id}", headers=me)).status_code == 204
    assert (await client.put(f"/v1/community/follows/{my_id}", headers=them)).status_code == 204

    r = await client.put(f"/v1/community/blocks/{their_id}", headers=me)
    assert r.status_code == 204, r.text

    mine = (await client.get("/v1/community/follows", headers=me)).json()
    theirs = (await client.get("/v1/community/follows", headers=them)).json()
    assert mine == {"following": 0, "followers": 0}
    assert theirs == {"following": 0, "followers": 0}


async def test_following_somebody_you_blocked_is_refused_out_loud(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-mod-3")
    await _sign_in(client, me)
    them = auth(sub="kc-mod-3-other")
    their_id = await _sign_in(client, them)

    await client.put(f"/v1/community/blocks/{their_id}", headers=me)
    r = await client.put(f"/v1/community/follows/{their_id}", headers=me)
    assert r.status_code == 400
    assert r.json()["code"] == "blocked_by_you"


async def test_a_block_is_never_announced_to_its_subject(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """The blocked person's requests keep succeeding; things just go quiet.

    An error anywhere on their path would be the announcement. The follow
    returns 204 and writes nothing; the member page answers 404 exactly as
    it would for an account that never existed.
    """
    me = auth(sub="kc-mod-4")
    my_id = await _sign_in(client, me)
    them = auth(sub="kc-mod-4-other")
    their_id = await _sign_in(client, them)

    await client.put(f"/v1/community/blocks/{their_id}", headers=me)

    quiet = await client.put(f"/v1/community/follows/{my_id}", headers=them)
    assert quiet.status_code == 204
    counts = (await client.get("/v1/community/follows", headers=them)).json()
    assert counts["following"] == 0

    page = await client.get(f"/v1/community/members/{my_id}", headers=them)
    missing = await client.get(
        "/v1/community/members/00000000-0000-0000-0000-000000000000", headers=them
    )
    assert page.status_code == missing.status_code == 404
    assert page.json()["code"] == missing.json()["code"]


async def test_unblocking_restores_sight_but_not_the_follow(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-mod-5")
    await _sign_in(client, me)
    them = auth(sub="kc-mod-5-other")
    their_id = await _sign_in(client, them)

    await client.put(f"/v1/community/follows/{their_id}", headers=me)
    await client.put(f"/v1/community/blocks/{their_id}", headers=me)
    await client.delete(f"/v1/community/blocks/{their_id}", headers=me)

    page = await client.get(f"/v1/community/members/{their_id}", headers=me)
    assert page.status_code == 200
    assert page.json()["blocked"] is False
    # The severed follow stayed severed: ending it was part of the block.
    assert page.json()["followed"] is False


async def test_the_member_page_shows_the_shelf_only_under_consent(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """The shelf is the fits they kept, and it is behind a consent.

    It used to be the curated looks they had saved. The catalogue is
    gone; the gate is the part that mattered, so it is asserted over
    what a shelf holds now.
    """
    from app.models.posts import PostSave
    from tests.test_feed import _fit
    from tests.test_garment_media import make_user

    me = auth(sub="kc-mod-6")
    await _sign_in(client, me)
    them = auth(sub="kc-mod-6-other")
    their_id = await _sign_in(client, them)

    author = await make_user(db)
    kept = await _fit(db, user_id=author, caption="Someone else's fit", tags=["linen"])
    db.add(PostSave(user_id=uuid.UUID(their_id), post_id=kept.id))
    await db.commit()

    closed = (await client.get(f"/v1/community/members/{their_id}", headers=me)).json()
    assert closed["shares"] is False
    assert closed["saved_posts"] == []

    await _grant_sharing(client, them)
    open_ = (await client.get(f"/v1/community/members/{their_id}", headers=me)).json()
    assert open_["shares"] is True
    assert [fit["post_id"] for fit in open_["saved_posts"]] == [str(kept.id)]


async def test_reports_are_recorded_and_say_nothing_else(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-mod-7")
    await _sign_in(client, me)
    them = auth(sub="kc-mod-7-other")
    their_id = await _sign_in(client, them)

    account = await client.post(
        "/v1/community/reports",
        json={
            "subject_kind": "account",
            "subject_user_id": their_id,
            "reason": "impersonation",
            "note": "Claims to be somebody they are not.",
        },
        headers=me,
    )
    assert account.status_code == 201, account.text
    assert set(account.json()) == {"report_id"}

    # Nothing is a look any more, so the API will not take one.
    look = await client.post(
        "/v1/community/reports",
        json={"subject_kind": "look", "look_id": "gorpcore", "reason": "other"},
        headers=me,
    )
    assert look.status_code == 422, look.text

    headless = await client.post(
        "/v1/community/reports",
        json={"subject_kind": "account", "reason": "spam"},
        headers=me,
    )
    assert headless.status_code == 422
    assert headless.json()["code"] == "bad_report"


async def test_the_blocked_list_belongs_to_the_blocker(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-mod-8")
    await _sign_in(client, me)
    them = auth(sub="kc-mod-8-other")
    their_id = await _sign_in(client, them)

    await client.put(f"/v1/community/blocks/{their_id}", headers=me)

    mine = (await client.get("/v1/community/blocks", headers=me)).json()
    assert [item["user_id"] for item in mine["items"]] == [their_id]
    theirs = (await client.get("/v1/community/blocks", headers=them)).json()
    assert theirs["items"] == []
