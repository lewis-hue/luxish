"""Fan-out, batching, quiet hours, throttling and delivery.

The pipeline is five decisions and each one can fail quietly: a
notification sent to somebody who muted it, twenty notifications where
one was meant, a banner at three in the morning, a flood the gateway
refuses, or a row that can never be delivered and is retried for ever.
Each has a test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import push as domain
from app.domain.notification_prefs import write_prefs
from app.models.push import DeviceToken, PushOutbox
from app.workers.push import send_due
from tests.test_garment_media import make_user

#: Mid-afternoon in London, so nothing is held for quiet hours unless
#: a test asks for it.
AFTERNOON = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)


async def _device(
    db: AsyncSession, user_id: uuid.UUID, *, zone: str | None = "Europe/London"
) -> DeviceToken:
    return await domain.register_device(
        db, user_id=user_id, token=f"ExponentPushToken[{uuid.uuid4().hex}]", timezone=zone
    )


async def _queued(db: AsyncSession, user_id: uuid.UUID) -> list[PushOutbox]:
    rows = await db.scalars(
        sa.select(PushOutbox).where(
            PushOutbox.user_id == user_id, PushOutbox.state == "queued"
        )
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# devices
# --------------------------------------------------------------------------- #
async def test_the_same_phone_is_one_row_however_often_it_says_hello(
    db: AsyncSession,
) -> None:
    """Registering on every launch must not grow the table."""
    me = await make_user(db)
    token = "ExponentPushToken[abc123def456]"
    for _ in range(3):
        await domain.register_device(db, user_id=me, token=token, timezone="UTC")

    rows = await db.scalars(sa.select(DeviceToken).where(DeviceToken.user_id == me))
    assert len(list(rows)) == 1


async def test_a_handset_that_changes_hands_changes_owner(
    db: AsyncSession,
) -> None:
    """Otherwise a stale row delivers one person's notifications to a
    phone somebody else now uses.

    Through the sign-out, which is how a handset actually changes
    hands: it revokes the row, and a revoked row is free."""
    first = await make_user(db)
    second = await make_user(db)
    token = "ExponentPushToken[shared999]"

    await domain.register_device(db, user_id=first, token=token)
    await domain.forget_device(db, token=token, user_id=first)
    await domain.register_device(db, user_id=second, token=token)

    found = await db.get(DeviceToken, token)
    assert found is not None
    assert found.user_id == second
    assert len(await domain.devices_for(db, user_ids=[first])) == 0


async def test_you_cannot_take_a_phone_somebody_is_still_reachable_on(
    db: AsyncSession,
) -> None:
    """The token is the only thing offered in support of the claim,
    and a token is secret rather than authorizing."""
    mine = await make_user(db)
    theirs = await make_user(db)
    token = "ExponentPushToken[notyours]"

    await domain.register_device(db, user_id=mine, token=token)
    with pytest.raises(domain.DeviceClaimed):
        await domain.register_device(db, user_id=theirs, token=token)

    found = await db.get(DeviceToken, token)
    assert found is not None
    assert found.user_id == mine
    assert len(await domain.devices_for(db, user_ids=[mine])) == 1


async def test_claiming_a_phone_is_not_a_way_round_forgetting_it(
    db: AsyncSession,
) -> None:
    """The whole point of the ownership check on `forget_device`: it
    would be worth nothing if the token could be moved first."""
    mine = await make_user(db)
    theirs = await make_user(db)
    token = "ExponentPushToken[sneaky1]"

    await domain.register_device(db, user_id=mine, token=token)
    with pytest.raises(domain.DeviceClaimed):
        await domain.register_device(db, user_id=theirs, token=token)
    assert await domain.forget_device(db, token=token, user_id=theirs) is False

    # Still reachable, which is the thing being defended.
    assert len(await domain.devices_for(db, user_ids=[mine])) == 1


async def test_a_handset_nobody_has_used_in_months_can_be_claimed(
    db: AsyncSession,
) -> None:
    """The fallback for a sign-out that never arrived - an app
    deleted, a phone wiped. Otherwise that row holds the token for
    ever and the next person to sign in gets nothing."""
    first = await make_user(db)
    second = await make_user(db)
    token = "ExponentPushToken[abandon1]"

    await domain.register_device(db, user_id=first, token=token)
    stale = await db.get(DeviceToken, token)
    assert stale is not None
    stale.last_seen_at = datetime.now(UTC) - domain.STALE - timedelta(days=1)
    await db.commit()

    await domain.register_device(db, user_id=second, token=token)
    found = await db.get(DeviceToken, token)
    assert found is not None
    assert found.user_id == second


async def test_refreshing_your_own_phone_is_never_a_claim(
    db: AsyncSession,
) -> None:
    """Called on every launch, so it must not start failing."""
    me = await make_user(db)
    token = "ExponentPushToken[mineown1]"

    await domain.register_device(db, user_id=me, token=token)
    for _ in range(3):
        await domain.register_device(db, user_id=me, token=token, timezone="UTC")

    assert len(await domain.devices_for(db, user_ids=[me])) == 1


async def test_signing_out_and_back_in_is_one_row(db: AsyncSession) -> None:
    me = await make_user(db)
    token = "ExponentPushToken[returns1]"
    await domain.register_device(db, user_id=me, token=token)
    assert await domain.forget_device(db, token=token, user_id=me) is True
    # Forgetting twice is work already done, not an error.
    assert await domain.forget_device(db, token=token, user_id=me) is False
    assert await domain.devices_for(db, user_ids=[me]) == {}

    await domain.register_device(db, user_id=me, token=token)
    assert len(await domain.devices_for(db, user_ids=[me])) == 1


async def test_you_cannot_forget_somebody_elses_phone(
    db: AsyncSession,
) -> None:
    """A token is opaque, but that is secrecy rather than
    authorization.

    One that leaked - through a log, a client bug, a handset passed
    around - would otherwise let whoever holds it silence another
    account's notifications entirely.
    """
    mine = await make_user(db)
    theirs = await make_user(db)
    token = "ExponentPushToken[nottheirs]"
    await domain.register_device(db, user_id=mine, token=token)

    assert await domain.forget_device(db, token=token, user_id=theirs) is False
    # Still reachable, because nothing happened.
    assert len(await domain.devices_for(db, user_ids=[mine])) == 1


# --------------------------------------------------------------------------- #
# fanning out
# --------------------------------------------------------------------------- #
async def test_a_fan_out_reaches_everybody_once(db: AsyncSession) -> None:
    crowd = [await make_user(db) for _ in range(5)]
    for who in crowd:
        await _device(db, who)

    written = await domain.fan_out(
        db,
        kind="fit_reactions",
        # The same person twice, as a retried job would send.
        audience=[*crowd, crowd[0]],
        title="Your fit",
        body="Somebody kept it",
        now=AFTERNOON,
    )
    assert written == 5


async def test_a_muted_kind_is_never_queued(db: AsyncSession) -> None:
    """The switch is the whole point: a muted kind must not reach the
    outbox, let alone a phone."""
    me = await make_user(db)
    await _device(db, me)
    await write_prefs(db, user_id=me, changes={"fit_reactions": False})

    written = await domain.fan_out(
        db,
        kind="fit_reactions",
        audience=[me],
        title="Your fit",
        body="Somebody kept it",
        now=AFTERNOON,
    )
    assert written == 0
    assert await _queued(db, me) == []


async def test_another_kind_still_gets_through(db: AsyncSession) -> None:
    """Muting one thing must not mute everything."""
    me = await make_user(db)
    await _device(db, me)
    await write_prefs(db, user_id=me, changes={"fit_reactions": False})

    written = await domain.fan_out(
        db,
        kind="stylist_ready",
        audience=[me],
        title="Your outfit is ready",
        body="The stylist finished",
        now=AFTERNOON,
    )
    assert written == 1


# --------------------------------------------------------------------------- #
# batching
# --------------------------------------------------------------------------- #
async def test_twenty_likes_are_one_notification(db: AsyncSession) -> None:
    """"Ada and 19 others", not twenty banners."""
    me = await make_user(db)
    await _device(db, me)

    for _ in range(20):
        await domain.fan_out(
            db,
            kind="fit_reactions",
            audience=[me],
            subject="post-42",
            title="Your fit",
            body="Somebody kept it",
            now=AFTERNOON,
        )

    owed = await _queued(db, me)
    assert len(owed) == 1
    assert owed[0].people == 20


async def test_two_different_fits_are_two_notifications(
    db: AsyncSession,
) -> None:
    """Batching is per subject. Collapsing across them would tell
    somebody about one fit and silently drop the other."""
    me = await make_user(db)
    await _device(db, me)

    for subject in ("post-1", "post-2"):
        await domain.fan_out(
            db,
            kind="fit_reactions",
            audience=[me],
            subject=subject,
            title="Your fit",
            body="Somebody kept it",
            now=AFTERNOON,
        )

    assert len(await _queued(db, me)) == 2


async def test_a_message_about_nothing_in_particular_never_batches(
    db: AsyncSession,
) -> None:
    """With no subject there is nothing to batch on, and collapsing by
    kind alone would swallow unrelated messages."""
    me = await make_user(db)
    await _device(db, me)

    for _ in range(3):
        await domain.fan_out(
            db,
            kind="wardrobe_sorted",
            audience=[me],
            title="Wardrobe sorted",
            body="Your photographs are filed",
            now=AFTERNOON,
        )

    assert len(await _queued(db, me)) == 3


# --------------------------------------------------------------------------- #
# quiet hours
# --------------------------------------------------------------------------- #
def test_the_small_hours_wait_for_the_morning() -> None:
    three_am = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
    when = domain.civil_time(three_am, "Europe/London")
    assert when > three_am
    assert when.astimezone(domain.ZoneInfo("Europe/London")).hour == 8


def test_the_middle_of_the_day_goes_at_once() -> None:
    assert domain.civil_time(AFTERNOON, "Europe/London") == AFTERNOON


def test_late_evening_waits_for_tomorrow() -> None:
    late = datetime(2026, 11, 1, 23, 30, tzinfo=UTC)
    when = domain.civil_time(late, "Europe/London")
    assert when.astimezone(domain.ZoneInfo("Europe/London")).day == 2


def test_the_hold_follows_the_device_not_the_server() -> None:
    """Three in the afternoon in London is the middle of the night in
    Auckland, and the person in Auckland is the one being woken."""
    london = domain.civil_time(AFTERNOON, "Europe/London")
    auckland = domain.civil_time(AFTERNOON, "Pacific/Auckland")
    assert london == AFTERNOON
    assert auckland > AFTERNOON


def test_an_unknown_clock_sends_rather_than_waiting_for_ever() -> None:
    """A device that never reported a zone must still hear things."""
    for zone in (None, "", "Mars/Olympus"):
        assert domain.civil_time(AFTERNOON, zone) == AFTERNOON


# --------------------------------------------------------------------------- #
# throttling
# --------------------------------------------------------------------------- #
async def test_the_sender_takes_a_bounded_number(db: AsyncSession) -> None:
    """A flood is what a gateway blocks and what crashes the servers
    behind it when everybody opens the app at once."""
    crowd = [await make_user(db) for _ in range(8)]
    for who in crowd:
        await _device(db, who)
    await domain.fan_out(
        db,
        kind="wardrobe_sorted",
        audience=crowd,
        title="Wardrobe sorted",
        body="Your photographs are filed",
        now=AFTERNOON,
    )

    assert len(await domain.due(db, limit=3, now=AFTERNOON)) == 3


async def test_what_is_not_yet_due_is_not_handed_over(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    await _device(db, me, zone="Pacific/Auckland")
    await domain.fan_out(
        db,
        kind="wardrobe_sorted",
        audience=[me],
        title="Wardrobe sorted",
        body="Your photographs are filed",
        now=AFTERNOON,
    )

    # Held for Auckland's morning, so nothing is due now.
    assert await domain.due(db, now=AFTERNOON) == []
    later = AFTERNOON + timedelta(days=1)
    assert len(await domain.due(db, now=later)) == 1


# --------------------------------------------------------------------------- #
# delivery
# --------------------------------------------------------------------------- #
async def test_a_delivered_message_is_marked_sent(db: AsyncSession) -> None:
    me = await make_user(db)
    await _device(db, me)
    await domain.fan_out(
        db,
        kind="wardrobe_sorted",
        audience=[me],
        title="Wardrobe sorted",
        body="Your photographs are filed",
        now=AFTERNOON,
    )

    taken: list[list[dict[str, Any]]] = []

    async def gateway(messages: list[dict[str, Any]]) -> bool:
        taken.append(messages)
        return True

    outcome = await send_due(db, deliver=gateway, now=AFTERNOON)
    assert outcome["sent"] == 1
    assert await _queued(db, me) == []
    assert taken[0][0]["to"].startswith("ExponentPushToken[")


async def test_the_tally_is_written_into_the_sentence(
    db: AsyncSession,
) -> None:
    """The count is still rising while the row waits, so the sentence
    is built at send time rather than at fan-out."""
    me = await make_user(db)
    await _device(db, me)
    for _ in range(4):
        await domain.fan_out(
            db,
            kind="fit_reactions",
            audience=[me],
            subject="post-7",
            title="Your fit",
            body="Somebody kept it",
            now=AFTERNOON,
        )

    seen: list[dict[str, Any]] = []

    async def gateway(messages: list[dict[str, Any]]) -> bool:
        seen.extend(messages)
        return True

    await send_due(db, deliver=gateway, now=AFTERNOON)
    assert seen[0]["body"] == "Somebody kept it and 3 others"


async def test_a_refused_gateway_leaves_the_message_queued(
    db: AsyncSession,
) -> None:
    """A blip must delay a notification, never lose it."""
    me = await make_user(db)
    await _device(db, me)
    await domain.fan_out(
        db,
        kind="wardrobe_sorted",
        audience=[me],
        title="Wardrobe sorted",
        body="Your photographs are filed",
        now=AFTERNOON,
    )

    async def refuses(messages: list[dict[str, Any]]) -> bool:
        return False

    outcome = await send_due(db, deliver=refuses, now=AFTERNOON)
    assert outcome["outcome"] == "deferred"
    assert len(await _queued(db, me)) == 1


async def test_a_message_nobody_can_receive_is_given_up_on(
    db: AsyncSession,
) -> None:
    """Somebody who never granted the permission would otherwise
    accumulate a queue that can never drain."""
    me = await make_user(db)
    await domain.fan_out(
        db,
        kind="wardrobe_sorted",
        audience=[me],
        title="Wardrobe sorted",
        body="Your photographs are filed",
        now=AFTERNOON,
    )

    async def gateway(messages: list[dict[str, Any]]) -> bool:  # pragma: no cover
        raise AssertionError("nothing should be sent")

    outcome = await send_due(db, deliver=gateway, now=AFTERNOON)
    assert outcome["dropped"] == 1
    assert await _queued(db, me) == []


async def test_a_message_that_keeps_failing_is_eventually_given_up_on(
    db: AsyncSession,
) -> None:
    """One undeliverable row must not block the queue behind it."""
    from app.workers.push import MAX_ATTEMPTS

    me = await make_user(db)
    await _device(db, me)
    await domain.fan_out(
        db,
        kind="wardrobe_sorted",
        audience=[me],
        title="Wardrobe sorted",
        body="Your photographs are filed",
        now=AFTERNOON,
    )

    async def refuses(messages: list[dict[str, Any]]) -> bool:
        return False

    for _ in range(MAX_ATTEMPTS):
        await send_due(db, deliver=refuses, now=AFTERNOON)

    assert await _queued(db, me) == []


async def test_one_person_two_phones_hears_on_both(db: AsyncSession) -> None:
    me = await make_user(db)
    await _device(db, me)
    await _device(db, me)
    await domain.fan_out(
        db,
        kind="wardrobe_sorted",
        audience=[me],
        title="Wardrobe sorted",
        body="Your photographs are filed",
        now=AFTERNOON,
    )

    seen: list[dict[str, Any]] = []

    async def gateway(messages: list[dict[str, Any]]) -> bool:
        seen.extend(messages)
        return True

    await send_due(db, deliver=gateway, now=AFTERNOON)
    assert len({m["to"] for m in seen}) == 2


async def test_the_deep_link_rides_along(db: AsyncSession) -> None:
    """Tapping it has to land on the thing it is about, and the app
    reads this rather than guessing from the words."""
    me = await make_user(db)
    await _device(db, me)
    await domain.fan_out(
        db,
        kind="fit_reactions",
        audience=[me],
        title="Your fit",
        body="Somebody kept it",
        deep_link="/fit/abc",
        now=AFTERNOON,
    )

    seen: list[dict[str, Any]] = []

    async def gateway(messages: list[dict[str, Any]]) -> bool:
        seen.extend(messages)
        return True

    await send_due(db, deliver=gateway, now=AFTERNOON)
    assert seen[0]["data"]["deep_link"] == "/fit/abc"


async def test_nothing_due_is_not_an_error(db: AsyncSession) -> None:
    async def gateway(messages: list[dict[str, Any]]) -> bool:  # pragma: no cover
        raise AssertionError("nothing should be sent")

    assert (await send_due(db, deliver=gateway, now=AFTERNOON))["sent"] == 0


# --------------------------------------------------------------------------- #
# the routes
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_the_routes_register_and_forget(
    client: Any, auth: Any
) -> None:
    headers = auth(sub="kc-push-1")
    assert (await client.post("/v1/auth/session", headers=headers)).status_code == 200

    token = "ExponentPushToken[route12345]"
    put = await client.put(
        "/v1/push/devices",
        json={"token": token, "platform": "expo", "timezone": "Africa/Nairobi"},
        headers=headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["timezone"] == "Africa/Nairobi"

    # Somebody else holding the token cannot silence this phone, and
    # is told nothing either way.
    stranger = auth(sub="kc-push-2")
    assert (await client.post("/v1/auth/session", headers=stranger)).status_code == 200
    theirs = await client.delete(f"/v1/push/devices/{token}", headers=stranger)
    assert theirs.status_code == 204

    gone = await client.delete(f"/v1/push/devices/{token}", headers=headers)
    assert gone.status_code == 204
    # Forgetting what is already forgotten says the same thing.
    again = await client.delete(f"/v1/push/devices/{token}", headers=headers)
    assert again.status_code == 204


@pytest.mark.asyncio
async def test_the_route_refuses_a_phone_somebody_else_is_on(
    client: Any, auth: Any
) -> None:
    """409, and the row does not move. A real client never sees this:
    the token comes from Expo on this handset, and changing hands goes
    through a sign-out that frees the row first."""
    headers = auth(sub="kc-push-3")
    assert (await client.post("/v1/auth/session", headers=headers)).status_code == 200

    token = "ExponentPushToken[route99999]"
    mine = await client.put(
        "/v1/push/devices", json={"token": token}, headers=headers
    )
    assert mine.status_code == 200, mine.text

    stranger = auth(sub="kc-push-4")
    assert (await client.post("/v1/auth/session", headers=stranger)).status_code == 200
    taken = await client.put(
        "/v1/push/devices", json={"token": token}, headers=stranger
    )
    assert taken.status_code == 409, taken.text

    # And the owner is still the owner, so the delete check still bites.
    assert (
        await client.delete(f"/v1/push/devices/{token}", headers=stranger)
    ).status_code == 204
    still = await client.put(
        "/v1/push/devices", json={"token": token}, headers=headers
    )
    assert still.status_code == 200, still.text


@pytest.mark.asyncio
async def test_registering_a_device_needs_an_account(client: Any) -> None:
    r = await client.put(
        "/v1/push/devices", json={"token": "ExponentPushToken[nobody12]"}
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# what actually queues one
# --------------------------------------------------------------------------- #


async def _outbox(db: AsyncSession, user_id: uuid.UUID) -> list[PushOutbox]:
    rows = await db.scalars(
        sa.select(PushOutbox).where(PushOutbox.user_id == user_id)
    )
    return list(rows)


async def _published_fit(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """An author and a fit of theirs that anybody may keep."""
    from app.models.posts import Post

    author = await make_user(db)
    post = Post(
        user_id=author,
        caption="Linen in town",
        state="published",
        visibility="public",
        published_at=datetime.now(UTC),
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return author, post.id


async def test_keeping_a_fit_tells_its_author(db: AsyncSession) -> None:
    """The pipeline was built, tested and wired to nothing. This is the
    wire."""
    from app.domain.posts import set_saved

    author, post_id = await _published_fit(db)
    keeper = await make_user(db)
    await _device(db, author)

    await set_saved(db, user_id=keeper, post_id=post_id, saved=True)

    queued = await _outbox(db, author)
    assert [row.kind for row in queued] == ["fit_saved"]
    assert queued[0].deep_link == f"/fit/{post_id}"


async def test_keeping_your_own_fit_tells_nobody(db: AsyncSession) -> None:
    from app.domain.posts import set_saved

    author, post_id = await _published_fit(db)
    await _device(db, author)

    await set_saved(db, user_id=author, post_id=post_id, saved=True)
    assert await _outbox(db, author) == []


async def test_following_somebody_tells_them(db: AsyncSession) -> None:
    from app.domain.community import follow

    followee = await make_user(db)
    follower = await make_user(db)
    await _device(db, followee)

    await follow(db, follower_id=follower, followee_id=followee)

    queued = await _outbox(db, followee)
    assert [row.kind for row in queued] == ["new_follower"]
    assert queued[0].deep_link == f"/member/{follower}"


async def test_following_twice_is_one_notification(db: AsyncSession) -> None:
    """The idempotent return means a double tap cannot send twice."""
    from app.domain.community import follow

    followee = await make_user(db)
    follower = await make_user(db)
    await _device(db, followee)

    await follow(db, follower_id=follower, followee_id=followee)
    await follow(db, follower_id=follower, followee_id=followee)

    assert len(await _outbox(db, followee)) == 1


async def test_a_message_tells_the_person_it_was_sent_to(
    db: AsyncSession,
) -> None:
    from app.domain.messages import send

    sender = await make_user(db)
    recipient = await make_user(db)
    await _device(db, recipient)

    await send(db, sender_id=sender, to_id=recipient, body="Is this still up?")

    queued = await _outbox(db, recipient)
    assert [row.kind for row in queued] == ["message"]
    assert queued[0].body == "Is this still up?"
    assert await _outbox(db, sender) == []


async def test_a_muted_thread_sends_nothing(db: AsyncSession) -> None:
    """Muting this conversation is a choice about this person, and it
    beats the general switch."""
    from app.domain.messages import send, set_notifies

    sender = await make_user(db)
    recipient = await make_user(db)
    await _device(db, recipient)

    await send(db, sender_id=sender, to_id=recipient, body="First")
    await set_notifies(db, viewer_id=recipient, other_id=sender, notifies=False)

    await send(db, sender_id=sender, to_id=recipient, body="Second")

    bodies = [row.body for row in await _outbox(db, recipient)]
    assert bodies == ["First"], "the muted one must not be queued"


# --------------------------------------------------------------------------- #
# the drain, which is the only thing that sends anything
# --------------------------------------------------------------------------- #
async def test_every_notified_event_reaches_the_gateway(db: AsyncSession) -> None:
    """The whole path, from the thing that happened to the socket.

    This is the test that was missing. Each of the four events had its
    own test proving it *queues* a row, `send_due` had its own proving
    it drains one, and nothing checked that anybody ran the drain - so
    all of them passed while the outbox filled and no phone rang.
    """
    from app.domain.community import follow
    from app.domain.messages import send

    follower = await make_user(db)
    followee = await make_user(db)
    await _device(db, followee)

    sender = await make_user(db)
    await send(db, sender_id=sender, to_id=followee, body="Still got the coat?")
    await follow(db, follower_id=follower, followee_id=followee)

    taken: list[dict[str, Any]] = []

    async def deliver(messages: list[dict[str, Any]]) -> bool:
        taken.extend(messages)
        return True

    # Past every `send_after` these could have been given, including
    # one pushed out of quiet hours, so this asserts about the path
    # rather than about what time the suite happens to run at.
    outcome = await send_due(
        db, deliver=deliver, now=datetime.now(UTC) + timedelta(days=2)
    )

    assert outcome["outcome"] == "sent"
    assert outcome["sent"] == 2
    # Both left, and each carries somewhere to go.
    kinds = {m["data"]["kind"] for m in taken}
    assert kinds == {"message", "new_follower"}
    for message in taken:
        assert message["data"]["deep_link"].startswith("/")
        assert "(" not in message["data"]["deep_link"], (
            "a route group never appears in a URL, so a tap on this goes nowhere"
        )


async def test_the_drain_is_scheduled_rather_than_left_to_the_operator() -> None:
    """Nothing else in this service opens a socket to the gateway.

    `push_handlers` was written, exported, and registered nowhere, and
    no beat entry ran the drain. Every notification in the app was
    queued correctly and delivered to nobody, which from the writing
    side is indistinguishable from working.
    """
    from app.queue.celery_app import QUEUE_DEFAULT, celery_app

    entry = next(
        (
            e
            for e in celery_app.conf.beat_schedule.values()
            if e.get("task") == "luxish.deliver_push"
        ),
        None,
    )
    assert entry is not None, "nothing drains the push outbox"
    # Not `maintenance`: recomputing cohorts runs for minutes on that
    # queue and a message banner must not wait behind it.
    assert entry["options"]["queue"] == QUEUE_DEFAULT
    # This interval *is* the latency of every notification in the app.
    assert 0 < entry["schedule"] <= 300


def test_the_drain_is_also_servable_as_a_job() -> None:
    from app.workers.push import PUSH_SEND_JOB_KIND
    from app.workers.runner import all_handlers

    assert PUSH_SEND_JOB_KIND in all_handlers()


# --------------------------------------------------------------------------- #
# what the gateway says about each message, not just about the request
# --------------------------------------------------------------------------- #
#: A real refusal, copied from what exp.host actually answered when
#: this pipeline was probed with a token that cannot exist. The status
#: code was 200.
DEVICE_GONE = {
    "status": "error",
    "message": (
        '"ExponentPushToken[0]" is not a registered push notification '
        "recipient or it is associated with a project that does not exist."
    ),
    "details": {"error": "DeviceNotRegistered"},
}
TOOK_IT = {"status": "ok", "id": "ticket-1"}


async def _one_queued(db: AsyncSession, user_id: uuid.UUID) -> PushOutbox:
    await domain.notify(
        db,
        user_id=user_id,
        kind="new_follower",
        title="You have a new follower",
        body="Somebody started following you.",
        deep_link="/member/abc",
    )
    rows = await _queued(db, user_id)
    assert len(rows) == 1
    return rows[0]


async def test_a_dead_token_is_not_a_delivery(db: AsyncSession) -> None:
    """HTTP 200 with an error in the ticket is a failure.

    The gateway answers 200 for a request it accepted and puts the
    outcome of each message in its own ticket. Reading the status code
    alone marked these sent, so somebody who had uninstalled the app
    absorbed every notification they were ever sent and the outbox
    recorded each one as delivered.
    """
    me = await make_user(db)
    device = await _device(db, me)
    row = await _one_queued(db, me)

    async def gateway(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [DEVICE_GONE for _ in messages]

    outcome = await send_due(
        db, deliver=gateway, now=datetime.now(UTC) + timedelta(days=2)
    )

    assert outcome["sent"] == 0, "nothing was delivered"
    await db.refresh(row)
    assert row.state == "dropped"

    # And the token is revoked, or the next drain addresses it again
    # and every notification after this one goes the same way.
    assert outcome["revoked"] == 1
    await db.refresh(device)
    assert device.revoked_at is not None


async def test_a_token_the_gateway_took_is_still_a_delivery(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    device = await _device(db, me)
    row = await _one_queued(db, me)

    async def gateway(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [TOOK_IT for _ in messages]

    outcome = await send_due(
        db, deliver=gateway, now=datetime.now(UTC) + timedelta(days=2)
    )

    assert outcome["sent"] == 1
    assert outcome["revoked"] == 0
    await db.refresh(row)
    assert row.state == "sent"
    await db.refresh(device)
    assert device.revoked_at is None, "a working phone must not be revoked"


async def test_one_phone_of_two_is_enough(db: AsyncSession) -> None:
    """A notice delivered to either handset is delivered.

    Somebody with an old phone they no longer use must still be told
    on the one they do.
    """
    me = await make_user(db)
    old = await _device(db, me)
    new = await _device(db, me)
    row = await _one_queued(db, me)

    async def gateway(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            DEVICE_GONE if m["to"] == old.token else TOOK_IT for m in messages
        ]

    outcome = await send_due(
        db, deliver=gateway, now=datetime.now(UTC) + timedelta(days=2)
    )

    assert outcome["sent"] == 1
    await db.refresh(row)
    assert row.state == "sent"
    # The dead one still goes, so it is not addressed again.
    await db.refresh(old)
    await db.refresh(new)
    assert old.revoked_at is not None
    assert new.revoked_at is None


async def test_a_refusal_worth_retrying_leaves_the_row_queued(
    db: AsyncSession,
) -> None:
    """Not every error is a dead token.

    A rate limit is the gateway asking for the same message later,
    which is the opposite of a token to revoke.
    """
    me = await make_user(db)
    device = await _device(db, me)
    row = await _one_queued(db, me)

    async def gateway(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"status": "error", "details": {"error": "MessageRateExceeded"}}
            for _ in messages
        ]

    outcome = await send_due(
        db, deliver=gateway, now=datetime.now(UTC) + timedelta(days=2)
    )

    assert outcome["sent"] == 0
    await db.refresh(row)
    assert row.state == "queued", "this one is worth asking again"
    assert row.attempts == 1
    await db.refresh(device)
    assert device.revoked_at is None, "the phone is fine; the gateway is busy"


async def test_a_request_that_never_landed_is_deferred_not_dropped(
    db: AsyncSession,
) -> None:
    """None means the request itself failed.

    Nothing in the slice has an outcome, so nothing may be resolved
    either way - and in particular no token may be revoked on the
    strength of a network error.
    """
    me = await make_user(db)
    device = await _device(db, me)
    row = await _one_queued(db, me)

    async def unreachable(messages: list[dict[str, Any]]) -> None:
        return None

    outcome = await send_due(
        db, deliver=unreachable, now=datetime.now(UTC) + timedelta(days=2)
    )

    assert outcome["outcome"] == "deferred"
    assert outcome["revoked"] == 0
    await db.refresh(row)
    assert row.state == "queued"
    await db.refresh(device)
    assert device.revoked_at is None


async def test_an_accepted_slice_with_no_tickets_counts_as_sent(
    db: AsyncSession,
) -> None:
    """An empty ticket list must not read as failure.

    `_deliver` answers `[]` when the gateway took the request and said
    nothing this understands. The first version of the caller tested
    the answer for truthiness, which made `[]` indistinguishable from
    a refusal and would have retried a message the gateway had
    already accepted.
    """
    me = await make_user(db)
    await _device(db, me)
    row = await _one_queued(db, me)

    async def quiet(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []

    outcome = await send_due(
        db, deliver=quiet, now=datetime.now(UTC) + timedelta(days=2)
    )

    assert outcome["sent"] == 1
    await db.refresh(row)
    assert row.state == "sent"
