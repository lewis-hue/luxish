"""Fits, and the gate that stands between "mine" and "everyone's".

The invariants: nothing publishes without a screen's yes; the gate being
broken is a no; a held post's photographs stay private; and what crosses
to strangers is the enumerated set, never the owner's free text on a
garment.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import sqlalchemy as sa

from app.domain.posts import SCREEN_JOB_KIND
from app.models.job import Job
from app.workers.screen import screen_post


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


class _Screener:
    """A fake with a verdict per surface, so tests choose the failure."""

    def __init__(self, *, text_ok: bool = True, image_ok: bool = True) -> None:
        self.text_ok = text_ok
        self.image_ok = image_ok
        self.texts: list[str] = []
        self.images = 0

    async def screen_text(self, text: str, *, user_id: uuid.UUID) -> tuple[bool, str]:
        self.texts.append(text)
        return self.text_ok, "" if self.text_ok else "Contains contact details."

    async def screen_image(
        self, data: bytes, content_type: str, *, user_id: uuid.UUID
    ) -> tuple[bool, str]:
        self.images += 1
        return self.image_ok, "" if self.image_ok else "Not clothing."


class _Store:
    async def read(self, asset: Any) -> bytes:
        return b"bytes"


async def _run_screen(engine: Any, post_id: str, screener: Any) -> None:
    from app.db.session import session_factory

    maker = session_factory(engine)
    async with maker() as db:
        await screen_post(
            db, post_id=uuid.UUID(post_id), screener=screener, store=_Store()
        )


async def _follow(client: httpx.AsyncClient, follower: dict, followee_id: str) -> None:
    r = await client.put(f"/v1/community/follows/{followee_id}", headers=follower)
    assert r.status_code == 204, r.text


async def _photo(engine: Any, user_id: str) -> str:
    """An uploaded photograph belonging to one person.

    Written straight in rather than uploaded: the upload path has its
    own tests, and what these need is an asset id the composer will
    accept as the author's own.
    """
    from app.db.session import session_factory
    from app.models.media_asset import MediaAsset

    maker = session_factory(engine)
    async with maker() as db:
        asset = MediaAsset(
            user_id=uuid.UUID(user_id),
            kind="outfit_photo",
            status="uploaded",
            content_type="image/webp",
            max_bytes=1_000_000,
            storage_key=f"originals/{uuid.uuid4().hex}.webp",
        )
        db.add(asset)
        await db.commit()
        return str(asset.id)


async def _compose(
    client: httpx.AsyncClient, engine: Any, headers: dict, **body: Any
) -> httpx.Response:
    """Publish a fit, with the photograph a fit needs.

    The author's id comes from signing in again, which is idempotent -
    so a call site does not have to have captured it.
    """
    user_id = await _sign_in(client, headers)
    asset = await _photo(engine, user_id)
    return await client.post(
        "/v1/posts", json={"media_asset_ids": [asset], **body}, headers=headers
    )


async def test_a_fit_is_live_the_moment_it_is_posted(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Published first, screened after.

    Fits used to wait for the screen, which meant somebody pressed
    publish and nothing appeared. The screen still runs and can take
    one down; what changed is which side of it the post sits on.
    """
    author = auth(sub="kc-post-1")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-post-1-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)

    r = await _compose(client, engine, author, caption="Trail layers for town")
    assert r.status_code == 201, r.text
    post_id = r.json()["id"]
    assert r.json()["state"] == "published"

    # In somebody else's feed already, with no screen having run.
    feed = (await client.get("/v1/posts/feed", headers=fan)).json()["items"]
    assert [item["id"] for item in feed] == [post_id]
    assert feed[0]["caption"] == "Trail layers for town"
    assert feed[0]["author_name"]

    # And the screen, when it runs, leaves a clean fit alone.
    await _run_screen(engine, post_id, _Screener())
    feed = (await client.get("/v1/posts/feed", headers=fan)).json()["items"]
    assert [item["id"] for item in feed] == [post_id]


async def test_the_screen_can_withdraw_a_fit_after_it_is_live(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """The other half of publishing first.

    Without this the screen is decoration: a fit that should not have
    gone out would stay out.
    """
    author = auth(sub="kc-post-withdraw")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-post-withdraw-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)

    r = await _compose(
        client, engine, author, caption="Something the screen dislikes"
    )
    post_id = r.json()["id"]
    assert (await client.get("/v1/posts/feed", headers=fan)).json()["items"]

    await _run_screen(engine, post_id, _Screener(text_ok=False))

    assert (await client.get("/v1/posts/feed", headers=fan)).json()["items"] == []


async def test_a_flagged_caption_holds_the_fit_with_its_reason(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    author = auth(sub="kc-post-2")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-post-2-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)

    r = await _compose(client, engine, author, caption="Call me on 0712")
    post_id = r.json()["id"]
    await _run_screen(engine, post_id, _Screener(text_ok=False))

    assert (await client.get("/v1/posts/feed", headers=fan)).json()["items"] == []
    mine = (await client.get("/v1/posts/mine", headers=author)).json()["items"]
    assert mine[0]["state"] == "held"
    assert "caption" in mine[0]["screen_note"]
    assert mine[0]["screen_mode"] == "model"


async def test_a_broken_gate_is_a_no_not_a_yes(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """No screener holds the post. The one thing the gate never does is
    guess "probably fine"."""
    author = auth(sub="kc-post-3")
    await _sign_in(client, author)
    r = await _compose(client, engine, author)
    post_id = r.json()["id"]

    await _run_screen(engine, post_id, None)

    mine = (await client.get("/v1/posts/mine", headers=author)).json()["items"]
    assert mine[0]["state"] == "held"
    assert mine[0]["screen_mode"] == "unavailable"


async def test_the_screen_job_is_enqueued_with_the_post(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    author = auth(sub="kc-post-4")
    await _sign_in(client, author)
    r = await _compose(client, engine, author)
    post_id = r.json()["id"]

    from app.db.session import session_factory

    maker = session_factory(engine)
    async with maker() as db:
        job = await db.scalar(
            sa.select(Job).where(Job.idempotency_key == f"post-screen:{post_id}")
        )
        assert job is not None
        assert job.kind == SCREEN_JOB_KIND


async def test_a_strangers_garment_cannot_be_tagged(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """The house non-negotiable, applied to posts."""
    author = auth(sub="kc-post-5")
    await _sign_in(client, author)
    other = auth(sub="kc-post-5-other")
    await _sign_in(client, other)

    r = await _compose(client, engine, author, garment_ids=[str(uuid.uuid4())])
    assert r.status_code == 404


async def test_an_empty_fit_is_refused(client: httpx.AsyncClient, auth: Any) -> None:
    author = auth(sub="kc-post-6")
    await _sign_in(client, author)
    r = await client.post("/v1/posts", json={"caption": "words alone"}, headers=author)
    assert r.status_code == 422
    assert r.json()["code"] == "bad_post"


async def test_blocking_the_author_clears_their_fits_from_the_feed(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    author = auth(sub="kc-post-7")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-post-7-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)

    r = await _compose(client, engine, author)
    await _run_screen(engine, r.json()["id"], _Screener())
    assert len((await client.get("/v1/posts/feed", headers=fan)).json()["items"]) == 1

    await client.put(f"/v1/community/blocks/{author_id}", headers=fan)
    assert (await client.get("/v1/posts/feed", headers=fan)).json()["items"] == []


async def test_deleting_a_fit_removes_it_everywhere(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    author = auth(sub="kc-post-8")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-post-8-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)

    r = await _compose(client, engine, author)
    post_id = r.json()["id"]
    await _run_screen(engine, post_id, _Screener())

    assert (await client.delete(f"/v1/posts/{post_id}", headers=author)).status_code == 204
    assert (await client.get("/v1/posts/feed", headers=fan)).json()["items"] == []
    # And not somebody else's to delete.
    r2 = await _compose(client, engine, author)
    stranger_delete = await client.delete(
        f"/v1/posts/{r2.json()['id']}", headers=fan
    )
    assert stranger_delete.status_code == 404


async def test_a_post_can_be_reported(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    author = auth(sub="kc-post-9")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-post-9-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)
    r = await _compose(client, engine, author)
    post_id = r.json()["id"]
    await _run_screen(engine, post_id, _Screener())

    report = await client.post(
        "/v1/community/reports",
        json={"subject_kind": "post", "post_id": post_id, "reason": "inappropriate"},
        headers=fan,
    )
    assert report.status_code == 201, report.text


async def _published_fit_with_media(
    client: httpx.AsyncClient, engine: Any, author: dict, image: bytes
) -> tuple[str, str]:
    """Publish a fit carrying one real photograph. Returns (post, asset)."""
    authorize = await client.post(
        "/v1/uploads/authorize",
        json={
            "kind": "outfit_photo",
            "content_type": "image/jpeg",
            "content_length": len(image),
        },
        headers=author,
    )
    assert authorize.status_code == 201, authorize.text
    asset_id = authorize.json()["asset_id"]
    put = await client.put(
        f"/v1/uploads/local/{asset_id}", content=image, headers=author
    )
    assert put.status_code == 204, put.text

    created = await client.post(
        "/v1/posts",
        json={"media_asset_ids": [asset_id]},
        headers=author,
    )
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]
    await _run_screen(engine, post_id, _Screener())
    return post_id, asset_id


async def test_deleting_a_fit_un_publishes_its_photograph(
    local_media_client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """The one a sticky consent flag got wrong.

    A follower holds the asset id from the feed payload. Once the author
    deletes the fit the bytes must stop being readable, or "delete" was a
    lie about everyone who had already scrolled past it.
    """
    author = auth(sub="kc-post-media-1")
    author_id = await _sign_in(local_media_client, author)
    fan = auth(sub="kc-post-media-1-fan")
    await _sign_in(local_media_client, fan)
    await _follow(local_media_client, fan, author_id)

    post_id, asset_id = await _published_fit_with_media(
        local_media_client, engine, author, b"jpeg-bytes"
    )

    live = await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    assert live.status_code == 200, live.text

    assert (
        await local_media_client.delete(f"/v1/posts/{post_id}", headers=author)
    ).status_code == 204

    gone = await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    assert gone.status_code == 404
    # The author keeps their own photograph either way.
    assert (
        await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=author)
    ).status_code == 200


async def test_a_block_hides_the_photograph_too(
    local_media_client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Blocking must reach the bytes, not only the feed rows."""
    author = auth(sub="kc-post-media-2")
    author_id = await _sign_in(local_media_client, author)
    fan = auth(sub="kc-post-media-2-fan")
    await _sign_in(local_media_client, fan)
    await _follow(local_media_client, fan, author_id)

    _post_id, asset_id = await _published_fit_with_media(
        local_media_client, engine, author, b"jpeg-bytes-two"
    )
    assert (
        await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    ).status_code == 200

    await local_media_client.put(f"/v1/community/blocks/{author_id}", headers=fan)
    assert (
        await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    ).status_code == 404


async def test_a_withdrawn_fits_photograph_stops_being_readable(
    local_media_client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Publishing first is only safe if withdrawal is real.

    A fit is live the instant it is posted, so its photograph has to
    load. What has to hold is the other direction: when the screen
    takes a fit down, the picture goes with it.
    """
    author = auth(sub="kc-post-media-3")
    author_id = await _sign_in(local_media_client, author)
    fan = auth(sub="kc-post-media-3-fan")
    await _sign_in(local_media_client, fan)
    await _follow(local_media_client, fan, author_id)

    image = b"jpeg-bytes-three"
    authorize = await local_media_client.post(
        "/v1/uploads/authorize",
        json={
            "kind": "outfit_photo",
            "content_type": "image/jpeg",
            "content_length": len(image),
        },
        headers=author,
    )
    asset_id = authorize.json()["asset_id"]
    await local_media_client.put(f"/v1/uploads/local/{asset_id}", content=image, headers=author)
    created = await local_media_client.post(
        "/v1/posts",
        json={"media_asset_ids": [asset_id]},
        headers=author,
    )
    post_id = created.json()["id"]

    # Live, so readable: the fit is published the moment it is posted
    # and a photograph nobody can load is a fit nobody can see.
    assert (
        await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    ).status_code == 200

    # Withdrawn by the screen: not readable any more. This is the half
    # that still matters - publishing first is only safe if taking
    # something down actually takes its pictures with it.
    await _run_screen(engine, post_id, _Screener(image_ok=False))
    assert (
        await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    ).status_code == 404


async def test_keeping_a_fit_counts_once_however_many_taps(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    author = auth(sub="kc-post-save-1")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-post-save-1-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)

    r = await _compose(client, engine, author)
    post_id = r.json()["id"]
    await _run_screen(engine, post_id, _Screener())

    first = await client.put(f"/v1/posts/{post_id}/save", headers=fan)
    assert first.status_code == 200, first.text
    assert first.json() == {"saves": 1, "saved_by_me": True}
    # A double tap is the same state, not a second save.
    again = await client.put(f"/v1/posts/{post_id}/save", headers=fan)
    assert again.json() == {"saves": 1, "saved_by_me": True}

    feed = (await client.get("/v1/posts/feed", headers=fan)).json()["items"]
    assert [(f["saves"], f["saved_by_me"]) for f in feed] == [(1, True)]

    # The author sees the count but is not one of the savers.
    mine = (await client.get("/v1/posts/mine", headers=author)).json()["items"]
    assert (mine[0]["saves"], mine[0]["saved_by_me"]) == (1, False)

    gone = await client.delete(f"/v1/posts/{post_id}/save", headers=fan)
    assert gone.json() == {"saves": 0, "saved_by_me": False}


async def test_a_fit_nobody_can_see_cannot_be_kept(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Blocked and never-existed are the same 404.

    A save that worked on a fit this person cannot see would confirm it
    exists, which is the leak every refusal in this router is shaped to
    avoid. Withdrawal is the same refusal and has its own test:
    `test_a_withdrawn_fits_photograph_stops_being_readable`.
    """
    author = auth(sub="kc-post-save-2")
    author_id = await _sign_in(client, author)
    stranger = auth(sub="kc-post-save-2-stranger")
    await _sign_in(client, stranger)

    r = await _compose(client, engine, author)
    post_id = r.json()["id"]
    # Live at once, so keepable at once.
    assert (
        await client.put(f"/v1/posts/{post_id}/save", headers=stranger)
    ).status_code == 200

    await client.put(f"/v1/community/blocks/{author_id}", headers=stranger)
    blocked = await client.put(f"/v1/posts/{post_id}/save", headers=stranger)
    assert blocked.status_code == 404
    assert (
        await client.put(f"/v1/posts/{uuid.uuid4()}/save", headers=stranger)
    ).status_code == 404


async def _name_yourself(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> None:
    r = await client.patch("/v1/auth/me", headers=headers, json={"display_name": name})
    assert r.status_code == 200, r.text


async def test_publishing_a_fit_is_what_makes_you_findable(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Search is not a directory of everyone who signed up.

    The pool is people who put an outfit in front of strangers, and it is
    reversible: taking the last fit down takes the account back out.
    """
    seeker = auth(sub="kc-find-seeker")
    await _sign_in(client, seeker)

    quiet = auth(sub="kc-find-quiet")
    await _sign_in(client, quiet)
    await _name_yourself(client, quiet, "Marguerite Quiet")

    poster = auth(sub="kc-find-poster")
    await _sign_in(client, poster)
    await _name_yourself(client, poster, "Marguerite Poster")

    # Both are findable the moment they have names: publishing is no
    # longer the gate, because an app that cannot answer "is my friend
    # on here yet" fails the first thing anybody does with a new
    # account.
    found = (await client.get("/v1/community/people?q=Marguerite", headers=seeker)).json()
    assert len(found["items"]) == 2
    assert all(item["fits"] == 0 for item in found["items"])

    r = await _compose(client, engine, poster)
    post_id = r.json()["id"]
    await _run_screen(engine, post_id, _Screener())

    # Publishing ranks rather than gates: the one with a fit sorts
    # first, and the one without is still there.
    found = (await client.get("/v1/community/people?q=Marguerite", headers=seeker)).json()
    assert len(found["items"]) == 2
    assert found["items"][0]["fits"] == 1
    assert found["items"][1]["fits"] == 0
    assert found["items"][0]["followed"] is False

    # Following from the search result is the same follow as anywhere else.
    person_id = found["items"][0]["user_id"]
    assert (
        await client.put(f"/v1/community/follows/{person_id}", headers=seeker)
    ).status_code == 204
    again = (await client.get("/v1/community/people?q=Marguerite", headers=seeker)).json()
    assert again["items"][0]["followed"] is True
    assert again["items"][0]["follower_count"] == 1

    # Taking the fit down drops them back to zero fits; it no longer
    # removes them from search, because their name is what put them
    # there.
    assert (await client.delete(f"/v1/posts/{post_id}", headers=poster)).status_code == 204
    after = (
        await client.get("/v1/community/people?q=Marguerite", headers=seeker)
    ).json()
    assert len(after["items"]) == 2
    assert all(item["fits"] == 0 for item in after["items"])


async def test_search_never_surfaces_somebody_either_of_you_blocked(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    seeker = auth(sub="kc-find-blocker")
    seeker_id = await _sign_in(client, seeker)
    poster = auth(sub="kc-find-blocked")
    await _sign_in(client, poster)
    await _name_yourself(client, poster, "Cassiopeia Blocked")

    r = await _compose(client, engine, poster)
    await _run_screen(engine, r.json()["id"], _Screener())
    assert (
        await client.get("/v1/community/people?q=Cassiopeia", headers=seeker)
    ).json()["items"] != []

    # A block the *other* way hides them just the same.
    await client.put(f"/v1/community/blocks/{seeker_id}", headers=poster)
    assert (
        await client.get("/v1/community/people?q=Cassiopeia", headers=seeker)
    ).json()["items"] == []


async def test_one_letter_is_not_a_search(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """A single character would match most of the table and is refused."""
    seeker = auth(sub="kc-find-short")
    await _sign_in(client, seeker)
    poster = auth(sub="kc-find-short-poster")
    await _sign_in(client, poster)
    await _name_yourself(client, poster, "Anastasia Short")
    r = await _compose(client, engine, poster)
    await _run_screen(engine, r.json()["id"], _Screener())

    for query in ("", "A", "  "):
        body = (await client.get(f"/v1/community/people?q={query}", headers=seeker)).json()
        assert body["items"] == [], query
    assert (
        await client.get("/v1/community/people?q=An", headers=seeker)
    ).json()["items"] != []


# --------------------------------------------------------------------------- #
# the author's own switch
# --------------------------------------------------------------------------- #


async def test_a_private_fit_leaves_everybody_elses_feed(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """The whole point of the switch, and the thing it must never fail
    to do."""
    author = auth(sub="kc-vis-1")
    author_id = await _sign_in(client, author)
    fan = auth(sub="kc-vis-1-fan")
    await _sign_in(client, fan)
    await _follow(client, fan, author_id)

    post_id = (await _compose(client, engine, author, caption="Linen in town")).json()[
        "id"
    ]
    feed = (await client.get("/v1/posts/feed", headers=fan)).json()["items"]
    assert [item["id"] for item in feed] == [post_id]

    r = await client.put(
        f"/v1/posts/{post_id}/visibility",
        json={"visibility": "private"},
        headers=author,
    )
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "private"

    feed = (await client.get("/v1/posts/feed", headers=fan)).json()["items"]
    assert feed == []


async def test_a_private_fit_is_still_the_authors_own(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Private is not deleted. It has to still be there, and still say
    which way the switch is set, or there is no way to put it back."""
    author = auth(sub="kc-vis-2")
    await _sign_in(client, author)
    post_id = (await _compose(client, engine, author, caption="Just for me")).json()[
        "id"
    ]

    await client.put(
        f"/v1/posts/{post_id}/visibility",
        json={"visibility": "private"},
        headers=author,
    )
    mine = (await client.get("/v1/posts/mine", headers=author)).json()["items"]
    assert [item["id"] for item in mine] == [post_id]
    assert mine[0]["visibility"] == "private"

    # And back again.
    await client.put(
        f"/v1/posts/{post_id}/visibility",
        json={"visibility": "public"},
        headers=author,
    )
    mine = (await client.get("/v1/posts/mine", headers=author)).json()["items"]
    assert mine[0]["visibility"] == "public"


async def test_only_the_author_can_flip_the_switch(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """404 rather than 403, the same answer as for a fit that does not
    exist - otherwise this reports whether an id is somebody's post."""
    author = auth(sub="kc-vis-3")
    await _sign_in(client, author)
    stranger = auth(sub="kc-vis-3-other")
    await _sign_in(client, stranger)

    post_id = (await _compose(client, engine, author, caption="Mine")).json()["id"]
    r = await client.put(
        f"/v1/posts/{post_id}/visibility",
        json={"visibility": "private"},
        headers=stranger,
    )
    assert r.status_code == 404

    mine = (await client.get("/v1/posts/mine", headers=author)).json()["items"]
    assert mine[0]["visibility"] == "public"


async def test_taking_a_fit_private_takes_its_photograph_with_it(
    local_media_client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """The leak one layer below the one you can see: the feed declines
    to show the fit and the bytes come down anyway, to anybody who
    noted the asset id from a feed payload while it was public."""
    author = auth(sub="kc-vis-4")
    author_id = await _sign_in(local_media_client, author)
    fan = auth(sub="kc-vis-4-fan")
    await _sign_in(local_media_client, fan)
    await _follow(local_media_client, fan, author_id)

    post_id, asset_id = await _published_fit_with_media(
        local_media_client, engine, author, b"jpeg-bytes"
    )
    live = await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    assert live.status_code == 200, live.text

    assert (
        await local_media_client.put(
            f"/v1/posts/{post_id}/visibility",
            json={"visibility": "private"},
            headers=author,
        )
    ).status_code == 200

    gone = await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=fan)
    assert gone.status_code == 404
    # The author keeps their own, or the switch would read as a
    # deletion on their own profile.
    assert (
        await local_media_client.get(f"/v1/uploads/local/{asset_id}", headers=author)
    ).status_code == 200


async def test_the_screen_and_the_switch_do_not_overwrite_each_other(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Two different columns, because they are two different
    decisions: ours about whether it may be shown, theirs about
    whether it should be."""
    author = auth(sub="kc-vis-5")
    await _sign_in(client, author)
    post_id = (await _compose(client, engine, author, caption="Quiet one")).json()["id"]

    await client.put(
        f"/v1/posts/{post_id}/visibility",
        json={"visibility": "private"},
        headers=author,
    )
    await _run_screen(engine, post_id, _Screener())

    mine = (await client.get("/v1/posts/mine", headers=author)).json()["items"]
    assert mine[0]["state"] == "published"
    assert mine[0]["visibility"] == "private"


async def test_a_visibility_nobody_recognises_is_refused(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    author = auth(sub="kc-vis-6")
    await _sign_in(client, author)
    post_id = (await _compose(client, engine, author, caption="Hmm")).json()["id"]
    r = await client.put(
        f"/v1/posts/{post_id}/visibility",
        json={"visibility": "unlisted"},
        headers=author,
    )
    assert r.status_code == 422


async def test_somebody_who_has_named_themselves_is_findable(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """The first thing anybody does with a new account is look for a
    friend. Requiring a published fit first made that impossible."""
    seeker = auth(sub="kc-find-new-seeker")
    await _sign_in(client, seeker)

    fresh = auth(sub="kc-find-new-fresh")
    await _sign_in(client, fresh)
    await _name_yourself(client, fresh, "Ottoline Fresh")

    body = (
        await client.get("/v1/community/people?q=Ottoline", headers=seeker)
    ).json()
    assert [item["name"] for item in body["items"]] == ["Ottoline"]
    assert body["items"][0]["fits"] == 0


async def test_an_account_with_no_name_is_not_findable(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """A fresh sign-up stays out of search until its owner has decided
    to be somebody here. It is also not addressable by name when it
    has none."""
    seeker = auth(sub="kc-find-noname-seeker")
    await _sign_in(client, seeker)
    nameless = auth(sub="kc-find-noname")
    await _sign_in(client, nameless)

    for query in ("kc", "find", "noname"):
        body = (
            await client.get(f"/v1/community/people?q={query}", headers=seeker)
        ).json()
        assert body["items"] == [], query


async def test_private_takes_somebody_back_out_of_search(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """One switch, one meaning. `private` already says "my own things
    are not for strangers", and being listed by name to strangers is
    the same question."""
    seeker = auth(sub="kc-find-priv-seeker")
    await _sign_in(client, seeker)

    shy = auth(sub="kc-find-priv")
    await _sign_in(client, shy)
    await _name_yourself(client, shy, "Perpetua Shy")

    body = (
        await client.get("/v1/community/people?q=Perpetua", headers=seeker)
    ).json()
    assert [item["name"] for item in body["items"]] == ["Perpetua"]

    assert (
        await client.patch(
            "/v1/profiles/me", json={"private": True}, headers=shy
        )
    ).status_code == 200

    gone = (
        await client.get("/v1/community/people?q=Perpetua", headers=seeker)
    ).json()
    assert gone["items"] == [], "private means not listed to strangers"
