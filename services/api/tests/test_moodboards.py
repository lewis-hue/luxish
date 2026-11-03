"""Moodboards, and the ways a collection feature quietly corrupts itself.

Two boards nobody can tell apart. A board that accumulates the same pin.
An arrangement with a hole in it that the next pin collides with. Or a
partial reorder that silently deletes everything it did not mention. All
four look like working code.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.moodboards import MAX_PINS


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def _board(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> str:
    r = await client.post("/v1/moodboards", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _fits(db: Any, count: int) -> list[str]:
    """`count` published fits by one other person, as pinnable ids.

    A board holds fits now. These tests used to pin strings from the
    curated catalogue, which needed no author and no row - which is
    also why they went on passing after the catalogue was gone.
    """
    from tests.test_feed import _fit
    from tests.test_garment_media import make_user

    author = await make_user(db)
    made = [
        await _fit(db, user_id=author, caption=f"fit {index}", tags=["office"])
        for index in range(count)
    ]
    return [str(post.id) for post in made]


async def test_a_board_is_made_named_and_read_back(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-board-1")
    await _sign_in(client, headers)

    board = await _board(client, headers, "Lisbon trip")
    listing = await client.get("/v1/moodboards", headers=headers)
    assert [item["name"] for item in listing.json()["items"]] == ["Lisbon trip"]
    assert listing.json()["items"][0]["id"] == board


async def test_two_boards_cannot_share_a_name(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Otherwise the one somebody pins to is whichever the query returned first."""
    headers = auth(sub="kc-board-2")
    await _sign_in(client, headers)

    await _board(client, headers, "summer")
    clash = await client.post("/v1/moodboards", json={"name": "summer"}, headers=headers)
    assert clash.status_code == 409, clash.text


async def test_a_board_needs_a_name(client: httpx.AsyncClient, auth: Any) -> None:
    headers = auth(sub="kc-board-3")
    await _sign_in(client, headers)
    r = await client.post("/v1/moodboards", json={"name": "   "}, headers=headers)
    assert r.status_code == 422, r.text


async def test_pinning_the_same_fit_twice_pins_it_once(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """A board that accumulates duplicates has to be de-duplicated forever."""
    headers = auth(sub="kc-board-4")
    await _sign_in(client, headers)
    (fit,) = await _fits(db, 1)
    board = await _board(client, headers, "work")

    for _ in range(3):
        r = await client.put(f"/v1/moodboards/{board}/posts/{fit}", headers=headers)
        assert r.status_code == 200, r.text
    assert r.json()["post_ids"] == [fit]


async def test_pins_keep_the_order_they_were_arranged_in(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """A board is a composition, so order is a column, not insertion luck."""
    headers = auth(sub="kc-board-5")
    await _sign_in(client, headers)
    first, second, third = await _fits(db, 3)
    board = await _board(client, headers, "autumn")

    for fit in (first, second, third):
        await client.put(f"/v1/moodboards/{board}/posts/{fit}", headers=headers)

    reordered = await client.put(
        f"/v1/moodboards/{board}/order",
        json={"refs": [third, first, second]},
        headers=headers,
    )
    assert reordered.json()["refs"] == [third, first, second]

    listing = await client.get("/v1/moodboards", headers=headers)
    assert listing.json()["items"][0]["post_ids"] == [third, first, second]


async def test_removing_the_middle_pin_closes_the_gap(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """The quiet one.

    Without compacting, position 1 is left empty and the next pin appended at
    `count` collides with an existing position. The order then depends on
    which row the database returns first, which only ever shows up on
    somebody else's machine.
    """
    headers = auth(sub="kc-board-6")
    await _sign_in(client, headers)
    a, b, c, d = await _fits(db, 4)
    board = await _board(client, headers, "gaps")

    for fit in (a, b, c):
        await client.put(f"/v1/moodboards/{board}/posts/{fit}", headers=headers)

    await client.delete(f"/v1/moodboards/{board}/posts/{b}", headers=headers)
    after = await client.put(f"/v1/moodboards/{board}/posts/{d}", headers=headers)

    # Appended to the end rather than colliding with what was already there.
    assert after.json()["post_ids"] == [a, c, d]


async def test_a_partial_reorder_keeps_what_it_did_not_mention(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """A short list means a client that knows about fewer pins than exist.

    Reading it as "delete the rest" is the worst available interpretation and
    loses work silently.
    """
    headers = auth(sub="kc-board-7")
    await _sign_in(client, headers)
    one, two, three = await _fits(db, 3)
    board = await _board(client, headers, "partial")

    for fit in (one, two, three):
        await client.put(f"/v1/moodboards/{board}/posts/{fit}", headers=headers)

    r = await client.put(
        f"/v1/moodboards/{board}/order",
        json={"refs": [three]},
        headers=headers,
    )
    assert r.json()["refs"][0] == three
    assert set(r.json()["refs"]) == {one, two, three}


async def test_unpinning_something_not_on_the_board_is_not_an_error(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-board-8")
    await _sign_in(client, headers)
    board = await _board(client, headers, "empty")
    r = await client.delete(
        f"/v1/moodboards/{board}/posts/{uuid.uuid4()}", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["post_ids"] == []


async def test_deleting_a_board_takes_its_pins_with_it(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    headers = auth(sub="kc-board-9")
    await _sign_in(client, headers)
    (fit,) = await _fits(db, 1)
    board = await _board(client, headers, "temporary")
    await client.put(f"/v1/moodboards/{board}/posts/{fit}", headers=headers)

    assert (
        await client.delete(f"/v1/moodboards/{board}", headers=headers)
    ).status_code == 204
    assert (await client.get("/v1/moodboards", headers=headers)).json()["items"] == []


async def test_a_board_belongs_to_exactly_one_person(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """Not-found rather than forbidden, so an id's existence is not confirmed."""
    mine = auth(sub="kc-board-10")
    theirs = auth(sub="kc-board-11")
    await _sign_in(client, mine)
    await _sign_in(client, theirs)

    board = await _board(client, mine, "private")
    (fit,) = await _fits(db, 1)

    assert (await client.get("/v1/moodboards", headers=theirs)).json()["items"] == []
    reach = await client.put(f"/v1/moodboards/{board}/posts/{fit}", headers=theirs)
    assert reach.status_code == 404, reach.text

    # And deleting cannot reach across either.
    await client.delete(f"/v1/moodboards/{board}", headers=theirs)
    assert len((await client.get("/v1/moodboards", headers=mine)).json()["items"]) == 1


async def test_a_board_is_bounded(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """Ten thousand pins is a corrupt client, not an enthusiastic user.

    The board is filled in one insert rather than two hundred requests.
    The ceiling is a count, so what is worth exercising over the API is
    the pin that reaches it and the one that does not fit.
    """
    from app.models.moodboard import MoodboardPin

    headers = auth(sub="kc-board-12")
    await _sign_in(client, headers)
    last, over_the_line = await _fits(db, 2)
    board = await _board(client, headers, "bounded")

    # MAX_PINS - 1 pins written straight in, so the next one over the API
    # is the one that fills the board.
    filler = await _fits(db, MAX_PINS - 1)
    for position, fit in enumerate(filler):
        db.add(
            MoodboardPin(
                moodboard_id=uuid.UUID(board),
                post_id=uuid.UUID(fit),
                position=position,
            )
        )
    await db.commit()

    fills = await client.put(f"/v1/moodboards/{board}/posts/{last}", headers=headers)
    assert fills.status_code == 200, fills.text
    assert len(fills.json()["post_ids"]) == MAX_PINS

    over = await client.put(
        f"/v1/moodboards/{board}/posts/{over_the_line}", headers=headers
    )
    assert over.status_code == 422, over.text


async def test_renaming_leaves_the_note_alone(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-board-13")
    await _sign_in(client, headers)
    r = await client.post(
        "/v1/moodboards",
        json={"name": "before", "note": "for the Lisbon trip"},
        headers=headers,
    )
    board = r.json()["id"]

    renamed = await client.patch(
        f"/v1/moodboards/{board}", json={"name": "after"}, headers=headers
    )
    assert renamed.json()["name"] == "after"
    assert renamed.json()["note"] == "for the Lisbon trip"


async def test_a_board_holds_a_fit_somebody_published(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """The thing people most want to collect is each other's outfits.

    Boards used to hold only curated looks, which made the `...` sheet on
    Discover offer a save that could not work.
    """
    from tests.test_feed import _fit
    from tests.test_garment_media import make_user

    headers = auth(sub="kc-board-post-1")
    await _sign_in(client, headers)
    author_id = await make_user(db)
    post = await _fit(db, user_id=author_id, caption="Commute fit", tags=["office"])
    board = await _board(client, headers, "People I like")

    pinned = await client.put(
        f"/v1/moodboards/{board}/posts/{post.id}", headers=headers
    )
    assert pinned.status_code == 200, pinned.text
    body = pinned.json()
    assert body["post_ids"] == [str(post.id)]
    assert body["refs"] == [str(post.id)]

    # Twice is once.
    again = await client.put(
        f"/v1/moodboards/{board}/posts/{post.id}", headers=headers
    )
    assert again.json()["post_ids"] == [str(post.id)]

    off = await client.delete(
        f"/v1/moodboards/{board}/posts/{post.id}", headers=headers
    )
    assert off.json()["post_ids"] == []


async def test_a_blocked_authors_fit_cannot_be_pinned(
    client: httpx.AsyncClient, db: Any, auth: Any
) -> None:
    """An id read out of a response from before the block must not work.

    404 rather than 403: withdrawn, blocked and never-existed answer alike,
    so the refusal confirms nothing about who posted what.
    """
    from app.models.moderation import Block
    from tests.test_feed import _fit
    from tests.test_garment_media import make_user

    headers = auth(sub="kc-board-post-2")
    me = await _sign_in(client, headers)
    author_id = await make_user(db)
    post = await _fit(db, user_id=author_id, caption="Hidden", tags=["office"])
    db.add(Block(blocker_id=uuid.UUID(me), blocked_id=author_id))
    await db.commit()

    board = await _board(client, headers, "Board")
    r = await client.put(f"/v1/moodboards/{board}/posts/{post.id}", headers=headers)
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "pin_subject_not_found"


async def test_a_board_sends_the_cover_for_each_fit_on_it(
    db: AsyncSession,
) -> None:
    """A tile needs the asset to render and the post to open.

    The board screen could draw curated looks and nothing else while
    the Save-to-board flow was already writing post pins, so pinning a
    fit put a row in the table that no screen could show.
    """
    from app.domain import moodboards as domain
    from app.models.posts import PostMedia
    from app.routers.moodboards import _out
    from tests.test_feed import _fit
    from tests.test_garment_media import make_asset, make_user

    owner = await make_user(db)
    author = await make_user(db)
    board = await domain.create_board(db, user_id=owner, name="Winter", note=None)
    post = await _fit(db, user_id=author, caption="", tags=["linen"])
    asset = await make_asset(db, user_id=author)
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    await db.commit()
    await domain.pin(db, user_id=owner, board_id=board.id, post_id=post.id)

    out = await _out(db, board)
    assert [p.post_id for p in out.posts] == [post.id]
    assert out.posts[0].cover_asset_id == asset.id
