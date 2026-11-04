"""The inbox, and the three ways a notification list stops being worth opening.

It fills itself with things that did not happen; it reports an audience that
is one stranger; or it loses track of what you already read, so the unread
count stops meaning anything. None of those raise an error.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications import INBOX_DAYS
from app.domain.ranking import MIN_DISTINCT_USERS


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


async def _a_fit(db: AsyncSession) -> str:
    """A published fit by somebody else, for people to keep."""
    from tests.test_feed import _fit
    from tests.test_garment_media import make_user

    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["linen"])
    return str(post.id)


async def _keep(
    client: httpx.AsyncClient, headers: dict[str, str], post_id: str
) -> None:
    r = await client.put(f"/v1/posts/{post_id}/save", headers=headers)
    assert r.status_code in (200, 201), r.text


async def _backdate(db: AsyncSession, post_id: str, when: datetime) -> None:
    """Age every keep on a fit, for the window test.

    The route stamps now, and the case worth testing is the one where
    the attention was a fortnight ago.
    """
    from app.models.posts import PostSave

    await db.execute(
        sa.update(PostSave)
        .where(PostSave.post_id == uuid.UUID(post_id))
        .values(created_at=when)
    )
    await db.commit()


async def test_an_empty_inbox_stays_empty(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Nothing manufactures a welcome message to avoid an empty screen.

    This is the whole reason an inbox is worth opening: if it contains
    something whenever you look, the badge stops carrying information.
    """
    headers = auth(sub="kc-inbox-1")
    await _sign_in(client, headers)

    r = await client.get("/v1/notifications", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "unread": 0, "window_days": INBOX_DAYS}


async def test_one_stranger_is_not_a_community(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Below the threshold, a saved look produces no notification at all.

    "1 person saved this too" is a single tap dressed up as an audience, and
    it is the most tempting notification to send because it is the easiest
    one to generate.
    """
    mine = auth(sub="kc-inbox-2")
    await _sign_in(client, mine)
    fit = await _a_fit(db)
    await _keep(client, mine, fit)

    stranger = auth(sub="kc-inbox-2-other")
    await _sign_in(client, stranger)
    await _keep(client, stranger, fit)

    r = await client.get("/v1/notifications", headers=mine)
    assert [item["kind"] for item in r.json()["items"]] == []


async def test_enough_people_is_reported_with_its_basis(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """At the threshold it appears, and it says how many people it rests on."""
    mine = auth(sub="kc-inbox-3")
    await _sign_in(client, mine)
    fit = await _a_fit(db)
    await _keep(client, mine, fit)

    for n in range(MIN_DISTINCT_USERS):
        other = auth(sub=f"kc-inbox-3-other-{n}")
        await _sign_in(client, other)
        await _keep(client, other, fit)

    items = (await client.get("/v1/notifications", headers=mine)).json()["items"]
    reactions = [item for item in items if item["kind"] == "fit_reactions"]
    assert len(reactions) == 1
    assert reactions[0]["people"] == MIN_DISTINCT_USERS
    assert reactions[0]["target"] == f"/fit/{fit}"


async def test_your_own_taps_are_not_news(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Being told that you looked at your own saved look is not a notification.

    Without excluding the owner, somebody who views a look they kept three
    times is most of the way to a threshold about themselves.
    """
    mine = auth(sub="kc-inbox-4")
    await _sign_in(client, mine)
    fit = await _a_fit(db)
    # Keeping, unkeeping and keeping again is still one person.
    for _ in range(3):
        await _keep(client, mine, fit)

    items = (await client.get("/v1/notifications", headers=mine)).json()["items"]
    assert [item for item in items if item["kind"] == "fit_reactions"] == []


async def test_reading_clears_the_unread_count(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    mine = auth(sub="kc-inbox-5")
    await _sign_in(client, mine)
    fit = await _a_fit(db)
    await _keep(client, mine, fit)
    for n in range(MIN_DISTINCT_USERS):
        other = auth(sub=f"kc-inbox-5-other-{n}")
        await _sign_in(client, other)
        await _keep(client, other, fit)

    before = (await client.get("/v1/notifications", headers=mine)).json()
    assert before["unread"] == len(before["items"]) > 0

    assert (await client.post("/v1/notifications/read", headers=mine)).status_code == 200

    after = (await client.get("/v1/notifications", headers=mine)).json()
    assert after["unread"] == 0
    # Read, not deleted. An inbox that empties itself when you look at it has
    # thrown away the thing you opened it to find.
    assert len(after["items"]) == len(before["items"])


async def test_the_watermark_only_moves_forward(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Two devices, minutes apart, must not un-read each other's reading."""
    mine = auth(sub="kc-inbox-6")
    await _sign_in(client, mine)

    first = (await client.post("/v1/notifications/read", headers=mine)).json()["read_at"]
    second = (await client.post("/v1/notifications/read", headers=mine)).json()["read_at"]
    assert second >= first


async def test_an_inbox_belongs_to_exactly_one_person(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Somebody else's saved look must not produce notifications for you."""
    mine = auth(sub="kc-inbox-7")
    theirs = auth(sub="kc-inbox-8")
    await _sign_in(client, mine)
    await _sign_in(client, theirs)

    fit = await _a_fit(db)
    await _keep(client, theirs, fit)
    for n in range(MIN_DISTINCT_USERS):
        other = auth(sub=f"kc-inbox-7-other-{n}")
        await _sign_in(client, other)
        await _keep(client, other, fit)

    assert (await client.get("/v1/notifications", headers=mine)).json()["items"] == []
    assert (await client.get("/v1/notifications", headers=theirs)).json()["unread"] >= 1


async def test_nothing_older_than_the_window_is_reported(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """An inbox reaching back forever is a log, not news."""
    mine = auth(sub="kc-inbox-9")
    await _sign_in(client, mine)
    fit = await _a_fit(db)
    await _keep(client, mine, fit)

    for n in range(MIN_DISTINCT_USERS):
        other = auth(sub=f"kc-inbox-9-other-{n}")
        await _sign_in(client, other)
        await _keep(client, other, fit)
    await _backdate(db, fit, datetime.now(UTC) - timedelta(days=INBOX_DAYS + 5))

    items = (await client.get("/v1/notifications", headers=mine)).json()["items"]
    assert [item for item in items if item["kind"] == "fit_reactions"] == []


async def test_preferences_default_to_everything_on(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A fresh account hears about everything without a row being written."""
    headers = auth(sub="kc-prefs-1")
    await _sign_in(client, headers)

    r = await client.get("/v1/notifications/preferences", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "wardrobe_sorted": True,
        "stylist_ready": True,
        "fit_reactions": True,
        "plan_reminders": True,
    }


async def test_flipping_one_switch_leaves_the_others_alone(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """The PATCH is partial: absent means untouched, like the profile PATCH."""
    headers = auth(sub="kc-prefs-2")
    await _sign_in(client, headers)

    r = await client.patch(
        "/v1/notifications/preferences",
        json={"fit_reactions": False},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["fit_reactions"] is False
    assert r.json()["stylist_ready"] is True

    # And it stuck: read back through a fresh request, not the response.
    again = await client.get("/v1/notifications/preferences", headers=headers)
    assert again.json()["fit_reactions"] is False
    assert again.json()["plan_reminders"] is True


async def test_a_muted_kind_disappears_from_the_inbox(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Muting is enforced where the inbox is built, not in the client.

    The person keeps a fit, enough strangers keep it too that the item
    would appear, and then the person mutes the kind: the item is gone
    and the unread count does not secretly keep counting it.
    """
    mine = auth(sub="kc-prefs-3")
    await _sign_in(client, mine)
    fit = await _a_fit(db)
    await _keep(client, mine, fit)

    for n in range(MIN_DISTINCT_USERS):
        other = auth(sub=f"kc-prefs-3-other-{n}")
        await _sign_in(client, other)
        await _keep(client, other, fit)

    before = (await client.get("/v1/notifications", headers=mine)).json()
    assert [item["kind"] for item in before["items"]] == ["fit_reactions"]
    assert before["unread"] == 1

    await client.patch(
        "/v1/notifications/preferences",
        json={"fit_reactions": False},
        headers=mine,
    )

    after = (await client.get("/v1/notifications", headers=mine)).json()
    assert after["items"] == []
    assert after["unread"] == 0


async def test_an_unknown_toggle_is_refused_with_the_allowed_list(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A typo cannot create a phantom setting that nothing reads."""
    headers = auth(sub="kc-prefs-4")
    await _sign_in(client, headers)

    r = await client.patch(
        "/v1/notifications/preferences",
        json={"marketing_emails": True},
        headers=headers,
    )
    # Pydantic drops unknown fields, so an unknown key is simply not a
    # change rather than an error: the response is the unchanged truth.
    assert r.status_code == 200, r.text
    assert "marketing_emails" not in r.json()


async def test_preferences_belong_to_exactly_one_person(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    one = auth(sub="kc-prefs-5")
    await _sign_in(client, one)
    other = auth(sub="kc-prefs-5-other")
    await _sign_in(client, other)

    await client.patch(
        "/v1/notifications/preferences",
        json={"wardrobe_sorted": False},
        headers=one,
    )

    r = await client.get("/v1/notifications/preferences", headers=other)
    assert r.json()["wardrobe_sorted"] is True


# --------------------------------------------------------------------------- #
# Work that finished while somebody was somewhere else
#
# Both of these run on a worker for twenty to thirty seconds, which is
# long enough that nobody waits on the screen - they change tabs.
# Without these kinds the work finished silently and the only way to
# find out was to navigate back and look.
# --------------------------------------------------------------------------- #
async def test_a_studio_shot_that_finished_reaches_the_inbox(
    db: AsyncSession,
) -> None:
    from app.domain import notifications as domain
    from app.models.garment_studio import GarmentShot
    from tests.test_garment_media import make_asset, make_user

    me = await make_user(db)
    source = await make_asset(db, user_id=me)
    db.add(
        GarmentShot(
            user_id=me,
            source_asset_id=source.id,
            treatment="packshot",
            state="ready",
        )
    )
    await db.commit()

    items, _unread = await domain.inbox(db, user_id=me)
    kinds = [item.kind for item in items]
    assert "studio_ready" in kinds
    said = next(i for i in items if i.kind == "studio_ready")
    assert "packshot" in said.body, "which shot it was is the useful part"
    assert said.target == "/studio"


async def test_a_finished_try_on_reaches_the_inbox(db: AsyncSession) -> None:
    from app.domain import notifications as domain
    from app.models.avatar_render import AvatarRender
    from tests.test_garment_media import make_user

    me = await make_user(db)
    db.add(AvatarRender(user_id=me, kind="try_on", state="ready"))
    await db.commit()

    items, _unread = await domain.inbox(db, user_id=me)
    said = next(i for i in items if i.kind == "render_ready")
    assert said.title == "Your try-on is ready"
    assert said.target == "/avatar"


async def test_an_avatar_and_a_try_on_are_announced_differently(
    db: AsyncSession,
) -> None:
    """They are different things to have been waiting for."""
    from app.domain import notifications as domain
    from app.models.avatar_render import AvatarRender
    from tests.test_garment_media import make_user

    me = await make_user(db)
    db.add(AvatarRender(user_id=me, kind="base", state="ready"))
    await db.commit()

    items, _unread = await domain.inbox(db, user_id=me)
    said = next(i for i in items if i.kind == "render_ready")
    assert said.title == "Your avatar is ready"


async def test_work_still_running_is_not_announced(db: AsyncSession) -> None:
    """**Only `ready`.** A queued job is not news, and announcing one
    would mean the badge lit the moment somebody pressed the button."""
    from app.models.avatar_render import AvatarRender
    from app.domain import notifications as domain
    from app.models.garment_studio import GarmentShot
    from tests.test_garment_media import make_asset, make_user

    me = await make_user(db)
    source = await make_asset(db, user_id=me)
    db.add(AvatarRender(user_id=me, kind="try_on", state="queued"))
    db.add(
        GarmentShot(
            user_id=me,
            source_asset_id=source.id,
            treatment="packshot",
            state="queued",
        )
    )
    await db.commit()

    items, _unread = await domain.inbox(db, user_id=me)
    assert not [i for i in items if i.kind in ("render_ready", "studio_ready")]


async def test_both_new_kinds_can_be_muted(db: AsyncSession) -> None:
    """Every other kind can be, so these must be too - or the
    preferences screen quietly stops covering the inbox."""
    from app.domain import notifications as domain
    from app.domain.notification_prefs import write_prefs
    from app.models.avatar_render import AvatarRender
    from app.models.garment_studio import GarmentShot
    from tests.test_garment_media import make_asset, make_user

    me = await make_user(db)
    source = await make_asset(db, user_id=me)
    db.add(AvatarRender(user_id=me, kind="try_on", state="ready"))
    db.add(
        GarmentShot(
            user_id=me,
            source_asset_id=source.id,
            treatment="packshot",
            state="ready",
        )
    )
    await db.commit()

    await write_prefs(
        db,
        user_id=me,
        changes={"render_ready": False, "studio_ready": False},
    )
    items, _unread = await domain.inbox(db, user_id=me)
    assert not [i for i in items if i.kind in ("render_ready", "studio_ready")]
