"""The studio, and the two ways a creator dashboard learns to lie.

It counts the owner's own taps as an audience, or it reports a different
window than the one on the control. Both are tests here.

**It measures what the owner published.** It used to measure other
people's activity on the catalogue looks the owner had *saved*, which
made the dashboard a report on somebody else's clothes. The fits below
are the owner's own, which is the only thing a creator screen can
honestly be about.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.posts import Post, PostSave
from app.models.profile import PostReaction


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return uuid.UUID(r.json()["user_id"])


async def _publish(engine: Any, author: uuid.UUID, caption: str) -> uuid.UUID:
    """A published fit, written straight in.

    Through the database rather than the composer: publishing over HTTP
    needs an upload, a screen and a consent, none of which this file is
    about.
    """
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        post = Post(user_id=author, state="published", caption=caption)
        session.add(post)
        await session.commit()
        return post.id


async def _keep(
    engine: Any,
    *,
    post_id: uuid.UUID,
    user_id: uuid.UUID,
    when: datetime | None = None,
) -> None:
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(
            PostSave(
                user_id=user_id,
                post_id=post_id,
                created_at=when or datetime.now(UTC),
            )
        )
        await session.commit()


async def _react(
    engine: Any,
    *,
    post_id: uuid.UUID,
    user_id: uuid.UUID,
    when: datetime | None = None,
) -> None:
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(
            PostReaction(
                user_id=user_id,
                post_id=post_id,
                kind="love",
                created_at=when or datetime.now(UTC),
            )
        )
        await session.commit()


async def test_an_empty_shelf_gets_zeroes_not_an_error(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-studio-1")
    await _sign_in(client, headers)

    r = await client.get("/v1/studio/overview", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fits"] == 0
    assert body["saves"] == 0
    assert body["reach"] == 0
    assert body["series"] == [0] * 28


async def test_the_studio_counts_other_people_and_never_the_owner(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    me = auth(sub="kc-studio-2")
    my_id = await _sign_in(client, me)
    fit = await _publish(engine, my_id, "#gorpcore")

    # My own keep and my own reaction on my own fit: not reach, not saves.
    await _keep(engine, post_id=fit, user_id=my_id)
    await _react(engine, post_id=fit, user_id=my_id)

    for n in range(2):
        other = auth(sub=f"kc-studio-2-other-{n}")
        other_id = await _sign_in(client, other)
        await _keep(engine, post_id=fit, user_id=other_id)

    body = (await client.get("/v1/studio/overview", headers=me)).json()
    assert body["fits"] == 1
    assert body["saves"] == 2
    assert body["reach"] == 2
    assert sum(body["series"]) == 2
    assert body["top_fits"] == [{"post_id": str(fit), "people": 2, "saves": 2}]


async def test_one_person_who_both_keeps_and_reacts_is_one_person_reached(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Reach is people, not events.

    Counting saves and reactions separately and adding them would say
    two, which is the easiest way for this screen to overstate an
    audience.
    """
    me = auth(sub="kc-studio-5")
    my_id = await _sign_in(client, me)
    fit = await _publish(engine, my_id, "#tailoring")

    fan = auth(sub="kc-studio-5-fan")
    fan_id = await _sign_in(client, fan)
    await _keep(engine, post_id=fit, user_id=fan_id)
    await _react(engine, post_id=fit, user_id=fan_id)

    body = (await client.get("/v1/studio/overview", headers=me)).json()
    assert body["reach"] == 1
    assert body["saves"] == 1
    # The chart counts events, which is two: the reach number is the one
    # making a claim about how many people there are.
    assert sum(body["series"]) == 2
    assert body["top_fits"] == [{"post_id": str(fit), "people": 1, "saves": 1}]


async def test_a_fit_nobody_saved_still_shows_the_people_it_reached(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """Otherwise the fit most people reacted to is invisible here."""
    me = auth(sub="kc-studio-6")
    my_id = await _sign_in(client, me)
    fit = await _publish(engine, my_id, "#y2k")

    fan = auth(sub="kc-studio-6-fan")
    fan_id = await _sign_in(client, fan)
    await _react(engine, post_id=fit, user_id=fan_id)

    body = (await client.get("/v1/studio/overview", headers=me)).json()
    assert body["saves"] == 0
    assert body["reach"] == 1
    assert body["top_fits"] == [{"post_id": str(fit), "people": 1, "saves": 0}]


async def test_somebody_elses_fit_is_not_in_your_studio(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """The numbers are about your own work, not what you have kept."""
    me = auth(sub="kc-studio-7")
    my_id = await _sign_in(client, me)
    them = auth(sub="kc-studio-7-them")
    their_id = await _sign_in(client, them)

    theirs = await _publish(engine, their_id, "#mob-wife")
    # I keep it, and a crowd keeps it with me. None of that is mine.
    await _keep(engine, post_id=theirs, user_id=my_id)
    for n in range(3):
        fan = auth(sub=f"kc-studio-7-fan-{n}")
        fan_id = await _sign_in(client, fan)
        await _keep(engine, post_id=theirs, user_id=fan_id)

    body = (await client.get("/v1/studio/overview", headers=me)).json()
    assert body["fits"] == 0
    assert body["saves"] == 0
    assert body["reach"] == 0
    assert body["top_fits"] == []


async def test_the_window_actually_windows(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    me = auth(sub="kc-studio-3")
    my_id = await _sign_in(client, me)
    fit = await _publish(engine, my_id, "#heritage")

    fresh = auth(sub="kc-studio-3-fresh")
    fresh_id = await _sign_in(client, fresh)
    await _keep(engine, post_id=fit, user_id=fresh_id)

    stale = auth(sub="kc-studio-3-stale")
    stale_id = await _sign_in(client, stale)
    await _keep(
        engine,
        post_id=fit,
        user_id=stale_id,
        when=datetime.now(UTC) - timedelta(days=10),
    )

    week = (await client.get("/v1/studio/overview?window=7d", headers=me)).json()
    month = (await client.get("/v1/studio/overview?window=28d", headers=me)).json()
    assert week["saves"] == 1
    assert month["saves"] == 2
    assert len(week["series"]) == 7
    assert len(month["series"]) == 28

    r = await client.get("/v1/studio/overview?window=fortnight", headers=me)
    assert r.status_code == 422
    assert r.json()["code"] == "unknown_window"


async def test_followers_gained_is_windowed_and_total_is_not(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-studio-4")
    my_id = await _sign_in(client, me)
    fan = auth(sub="kc-studio-4-fan")
    await _sign_in(client, fan)
    assert (
        await client.put(f"/v1/community/follows/{my_id}", headers=fan)
    ).status_code == 204

    body = (await client.get("/v1/studio/overview?window=7d", headers=me)).json()
    assert body["followers"] == 1
    assert body["followers_gained"] == 1
