"""The planner, and the four ways a calendar quietly lies.

It moves a plan by a timezone. It stacks duplicates when somebody taps twice.
It loses the note that said what the day was for. Or it reads "not answered
yet" as "no", so every future plan looks rejected. None of the four raises
anything.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import planner
from app.domain.planner import MAX_RANGE_DAYS
from app.models.garment import Garment
from tests.test_garment_media import make_user


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def _wardrobe(
    db: AsyncSession, user_id: str, *names: str
) -> list[str]:
    """Clothes this person owns, as the ids a plan refers to."""
    out: list[str] = []
    for name in names:
        garment = Garment(
            user_id=uuid.UUID(user_id),
            name=name,
            confirmed_attributes={},
            inferred_attributes={},
        )
        db.add(garment)
        await db.commit()
        await db.refresh(garment)
        out.append(str(garment.id))
    return out


THURSDAY = date(2026, 11, 5)


async def test_planning_the_same_day_twice_plans_it_once(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """`PUT` states what a day holds, so a double tap is one plan."""
    headers = auth(sub="kc-plan-1")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    for _ in range(3):
        r = await client.put(
            f"/v1/planner/{THURSDAY}", json={"garment_ids": [wardrobe[1]]}, headers=headers
        )
        assert r.status_code == 200, r.text

    listing = await client.get(
        "/v1/planner", params={"start": str(THURSDAY), "end": str(THURSDAY)},
        headers=headers,
    )
    assert len(listing.json()["items"]) == 1


async def test_a_plan_stays_on_its_day(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A date, never a timestamp.

    A plan made in Nairobi for Thursday must still be Thursday after landing
    in London. Stored as an instant it moves by a timezone, and the person
    finds out by being dressed for the wrong day.
    """
    headers = auth(sub="kc-plan-2")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    await client.put(
        f"/v1/planner/{THURSDAY}", json={"garment_ids": [wardrobe[0]]}, headers=headers
    )
    item = (
        await client.get(
            "/v1/planner",
            params={"start": str(THURSDAY), "end": str(THURSDAY)},
            headers=headers,
        )
    ).json()["items"][0]
    # Exactly the day asked for, with no time component to drift.
    assert item["planned_for"] == str(THURSDAY)


async def test_changing_the_look_keeps_the_occasion(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """The note is usually what the day is *for*.

    "Dad's birthday" does not stop being true because somebody picked a
    different outfit for it, and silently dropping it is the sort of loss
    nobody notices until the day arrives.
    """
    headers = auth(sub="kc-plan-3")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    await client.put(
        f"/v1/planner/{THURSDAY}",
        json={"garment_ids": [wardrobe[0]], "note": "Dad's birthday"},
        headers=headers,
    )
    changed = await client.put(
        f"/v1/planner/{THURSDAY}", json={"garment_ids": [wardrobe[1]]}, headers=headers
    )
    assert changed.json()["note"] == "Dad's birthday"
    assert changed.json()["garment_ids"] == [wardrobe[1]]

    cleared = await client.put(
        f"/v1/planner/{THURSDAY}",
        json={"garment_ids": [wardrobe[1]], "note": ""},
        headers=headers,
    )
    assert cleared.json()["note"] is None


async def test_not_answered_is_not_no(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Null `worn` is "has not happened", not "declined".

    Collapsed to false, every plan in the future reads as one somebody
    rejected, and any count built on it is wrong in the same direction.
    """
    headers = auth(sub="kc-plan-4")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    planned = await client.put(
        f"/v1/planner/{THURSDAY}", json={"garment_ids": [wardrobe[0]]}, headers=headers
    )
    assert planned.json()["worn"] is None

    worn = await client.post(
        f"/v1/planner/{THURSDAY}/worn", json={"worn": True}, headers=headers
    )
    assert worn.json()["worn"] is True

    not_worn = await client.post(
        f"/v1/planner/{THURSDAY}/worn", json={"worn": False}, headers=headers
    )
    assert not_worn.json()["worn"] is False


async def test_reporting_worn_does_not_change_the_plan(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Separate endpoints because they are separate acts."""
    headers = auth(sub="kc-plan-5")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    await client.put(
        f"/v1/planner/{THURSDAY}",
        json={"garment_ids": [wardrobe[1]], "note": "hike"},
        headers=headers,
    )
    after = await client.post(
        f"/v1/planner/{THURSDAY}/worn", json={"worn": True}, headers=headers
    )
    assert after.json()["garment_ids"] == [wardrobe[1]]
    assert after.json()["note"] == "hike"


async def test_reporting_a_day_with_no_plan_is_a_404(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-plan-6")
    me = await _sign_in(client, headers)
    await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')
    r = await client.post(
        f"/v1/planner/{THURSDAY}/worn", json={"worn": True}, headers=headers
    )
    assert r.status_code == 404, r.text


async def test_a_range_includes_both_ends(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A week view asks Monday to Sunday and means it.

    Half-open, it silently drops Sunday — the day somebody is most likely to
    be planning for.
    """
    headers = auth(sub="kc-plan-7")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    monday = date(2026, 11, 2)
    sunday = monday + timedelta(days=6)
    for offset, which in ((0, 1), (6, 0)):
        await client.put(
            f"/v1/planner/{monday + timedelta(days=offset)}",
            json={"garment_ids": [wardrobe[which]]},
            headers=headers,
        )

    items = (
        await client.get(
            "/v1/planner",
            params={"start": str(monday), "end": str(sunday)},
            headers=headers,
        )
    ).json()["items"]
    assert [item["garment_ids"] for item in items] == [
        [wardrobe[1]],
        [wardrobe[0]],
    ]


async def test_plans_come_back_in_date_order(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-plan-8")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    for offset in (5, 1, 3):
        await client.put(
            f"/v1/planner/{THURSDAY + timedelta(days=offset)}",
            json={"garment_ids": [wardrobe[offset % 3]]},
            headers=headers,
        )

    items = (
        await client.get(
            "/v1/planner",
            params={"start": str(THURSDAY), "end": str(THURSDAY + timedelta(days=10))},
            headers=headers,
        )
    ).json()["items"]
    assert [item["planned_for"] for item in items] == sorted(
        item["planned_for"] for item in items
    )


async def test_an_unbounded_range_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A calendar that will scan a table on request is one somebody will."""
    headers = auth(sub="kc-plan-9")
    me = await _sign_in(client, headers)
    await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    r = await client.get(
        "/v1/planner",
        params={"start": "1900-01-01", "end": "2200-01-01"},
        headers=headers,
    )
    assert r.status_code == 422, r.text

    fine = await client.get(
        "/v1/planner",
        params={
            "start": str(THURSDAY),
            "end": str(THURSDAY + timedelta(days=MAX_RANGE_DAYS)),
        },
        headers=headers,
    )
    assert fine.status_code == 200, fine.text


async def test_clearing_a_day_is_idempotent(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-plan-10")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'navy blazer', 'white shirt', 'grey trousers')

    await client.put(
        f"/v1/planner/{THURSDAY}", json={"garment_ids": [wardrobe[2]]}, headers=headers
    )
    for _ in range(2):
        r = await client.delete(f"/v1/planner/{THURSDAY}", headers=headers)
        assert r.status_code == 204

    listing = await client.get(
        "/v1/planner",
        params={"start": str(THURSDAY), "end": str(THURSDAY)},
        headers=headers,
    )
    assert listing.json()["items"] == []


async def test_a_calendar_belongs_to_exactly_one_person(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    mine = auth(sub="kc-plan-11")
    theirs = auth(sub="kc-plan-12")
    me = await _sign_in(client, mine)
    await _sign_in(client, theirs)
    wardrobe = await _wardrobe(db, me, 'navy blazer')

    await client.put(
        f"/v1/planner/{THURSDAY}", json={"garment_ids": [wardrobe[0]]}, headers=mine
    )

    listing = await client.get(
        "/v1/planner",
        params={"start": str(THURSDAY), "end": str(THURSDAY)},
        headers=theirs,
    )
    assert listing.json()["items"] == []

    # And clearing by date cannot reach across accounts.
    await client.delete(f"/v1/planner/{THURSDAY}", headers=theirs)
    still_mine = await client.get(
        "/v1/planner",
        params={"start": str(THURSDAY), "end": str(THURSDAY)},
        headers=mine,
    )
    assert len(still_mine.json()["items"]) == 1


async def test_a_plan_can_only_hold_your_own_clothes(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """The house rule: an id in a request is re-validated against the
    wardrobe it claims to come from before anything is stored.

    Without it, a planner is a way to read whether a guessed garment id
    exists - and to fill a calendar with somebody else's clothes.
    """
    mine = auth(sub="kc-plan-13")
    theirs = auth(sub="kc-plan-14")
    me = await _sign_in(client, mine)
    them = await _sign_in(client, theirs)
    ours = await _wardrobe(db, me, 'navy blazer')
    yours = await _wardrobe(db, them, 'their coat')

    refused = await client.put(
        f"/v1/planner/{THURSDAY}",
        json={"garment_ids": [ours[0], yours[0]]},
        headers=mine,
    )
    assert refused.status_code == 404, refused.text

    # And nothing was written on the way to refusing.
    listing = await client.get(
        "/v1/planner",
        params={"start": str(THURSDAY), "end": str(THURSDAY)},
        headers=mine,
    )
    assert listing.json()["items"] == []


async def test_the_clothes_replace_rather_than_accumulate(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A `PUT` states what the day holds.

    Adding to it would mean a client had to know what was already
    planned before it could change anything, and a double tap would
    dress somebody twice.
    """
    headers = auth(sub="kc-plan-15")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'blazer', 'shirt', 'trousers')

    await client.put(
        f"/v1/planner/{THURSDAY}",
        json={"garment_ids": [wardrobe[0], wardrobe[1]]},
        headers=headers,
    )
    changed = await client.put(
        f"/v1/planner/{THURSDAY}",
        json={"garment_ids": [wardrobe[2]]},
        headers=headers,
    )
    assert changed.json()["garment_ids"] == [wardrobe[2]]


async def test_the_order_of_the_clothes_is_kept(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A plan is a composition, so the order it was put together in is
    the order it comes back in."""
    headers = auth(sub="kc-plan-16")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'blazer', 'shirt', 'trousers')
    backwards = list(reversed(wardrobe))

    planned = await client.put(
        f"/v1/planner/{THURSDAY}",
        json={"garment_ids": backwards},
        headers=headers,
    )
    assert planned.json()["garment_ids"] == backwards


async def test_removing_a_garment_takes_it_out_of_the_plans(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A plan naming clothes somebody no longer owns is worse than a
    shorter plan.

    Garments here are tombstoned rather than deleted, so the foreign
    key cascade never fires and the read is what has to notice.
    """
    import uuid as _uuid
    from datetime import UTC, datetime

    headers = auth(sub="kc-plan-17")
    me = await _sign_in(client, headers)
    wardrobe = await _wardrobe(db, me, 'blazer', 'shirt')
    await client.put(
        f"/v1/planner/{THURSDAY}", json={"garment_ids": wardrobe}, headers=headers
    )

    gone = await db.get(Garment, _uuid.UUID(wardrobe[0]))
    assert gone is not None
    gone.deleted_at = datetime.now(UTC)
    await db.commit()

    items = (
        await client.get(
            "/v1/planner",
            params={"start": str(THURSDAY), "end": str(THURSDAY)},
            headers=headers,
        )
    ).json()["items"]
    assert items[0]["garment_ids"] == [wardrobe[1]]


# --------------------------------------------------------------------------- #


async def _a_post(db: AsyncSession, *, user_id: uuid.UUID):
    """A published fit with a cover, which is all these tests need."""
    from app.models.media_asset import MediaAsset
    from app.models.posts import Post, PostMedia

    asset = MediaAsset(
        user_id=user_id,
        kind="outfit_photo",
        status="ready",
        content_type="image/jpeg",
        max_bytes=1,
        byte_size=1,
        version=1,
        publication_consent=True,
    )
    db.add(asset)
    await db.flush()

    post = Post(user_id=user_id, caption="", state="published", screen_mode="seed")
    db.add(post)
    await db.flush()
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    await db.commit()
    await db.refresh(post)
    return post

# the fit a day was planned from
# --------------------------------------------------------------------------- #
async def test_a_day_remembers_the_fit_it_was_planned_from(
    db: AsyncSession,
) -> None:
    """"Plan a day for it" starts on a pin, and a pin is not a garment.

    Without this the action arrived at an empty calendar with nothing
    identifying what "it" was.
    """

    user = await make_user(db)
    post = await _a_post(db, user_id=user)

    plan = await planner.plan_day(
        db,
        user_id=user,
        day=date(2026, 11, 10),
        garment_ids=[],
        reference_post_id=post.id,
    )
    assert plan.reference_post_id == post.id


async def test_changing_the_clothes_keeps_the_picture(db: AsyncSession) -> None:
    """Omitting it means "not talking about it", the rule the note follows.

    Re-saving a day's clothes must not quietly drop what it was
    planned from.
    """

    user = await make_user(db)
    post = await _a_post(db, user_id=user)
    day = date(2026, 11, 11)

    await planner.plan_day(
        db, user_id=user, day=day, garment_ids=[], reference_post_id=post.id
    )
    again = await planner.plan_day(db, user_id=user, day=day, garment_ids=[])
    assert again.reference_post_id == post.id


async def test_a_day_planned_from_the_wardrobe_references_nothing(
    db: AsyncSession,
) -> None:
    # The ordinary case, and always will be.

    user = await make_user(db)
    plan = await planner.plan_day(
        db, user_id=user, day=date(2026, 11, 12), garment_ids=[]
    )
    assert plan.reference_post_id is None


async def test_the_cover_is_looked_up_for_a_whole_range_at_once(
    db: AsyncSession,
) -> None:
    """A month view asking per day is thirty round trips for one screen."""

    user = await make_user(db)
    post = await _a_post(db, user_id=user)

    covers = await planner.covers_for(
        db, user_id=user, post_ids=[post.id, None, post.id]
    )
    assert set(covers) == {post.id}

    assert await planner.covers_for(db, user_id=user, post_ids=[None]) == {}
    assert await planner.covers_for(db, user_id=user, post_ids=[]) == {}


async def test_a_plan_cannot_name_a_fit_the_planner_cannot_see(
    db: AsyncSession,
) -> None:
    """The house rule: an id in a request is re-validated.

    `garment_ids` went through `_theirs`; `reference_post_id` arrived
    later and was written straight through, so a plan could name any
    post in the database - somebody else's private fit, a removed
    one, an id guessed outright.
    """
    from app.models.posts import Post

    mine = await make_user(db)
    stranger = await make_user(db)
    theirs = await _a_post(db, user_id=stranger)
    theirs.visibility = "private"
    await db.commit()

    plan = await planner.plan_day(
        db,
        user_id=mine,
        day=date(2026, 11, 20),
        garment_ids=[],
        reference_post_id=theirs.id,
    )
    assert plan.reference_post_id is None, "a private fit is not referenceable"

    removed = await _a_post(db, user_id=stranger)
    await db.execute(
        sa.update(Post).where(Post.id == removed.id).values(state="removed")
    )
    await db.commit()
    gone = await planner.plan_day(
        db,
        user_id=mine,
        day=date(2026, 11, 21),
        garment_ids=[],
        reference_post_id=removed.id,
    )
    assert gone.reference_post_id is None


async def test_an_author_may_reference_their_own_private_fit(
    db: AsyncSession,
) -> None:
    """The exception the predicate names.

    A fit their own profile still lists has to be usable by the
    person who posted it.
    """
    mine = await make_user(db)
    own = await _a_post(db, user_id=mine)
    own.visibility = "private"
    await db.commit()

    plan = await planner.plan_day(
        db,
        user_id=mine,
        day=date(2026, 11, 22),
        garment_ids=[],
        reference_post_id=own.id,
    )
    assert plan.reference_post_id == own.id


async def test_a_fit_taken_private_later_stops_handing_out_its_cover(
    db: AsyncSession,
) -> None:
    """Checked on read, not only on write.

    A reference stored while a fit was public would otherwise go on
    exposing its cover for ever.
    """
    mine = await make_user(db)
    author = await make_user(db)
    post = await _a_post(db, user_id=author)

    assert await planner.covers_for(db, user_id=mine, post_ids=[post.id])

    post.visibility = "private"
    await db.commit()
    assert await planner.covers_for(db, user_id=mine, post_ids=[post.id]) == {}
    # Still theirs to see.
    assert await planner.covers_for(db, user_id=author, post_ids=[post.id])
