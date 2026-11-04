"""Stopping a picture that is being drawn, and asking again at once.

**Waiting was the only option.** A render that had been asked for could
not be called off. The progress card sat over the avatar, and because
one render is allowed in flight per kind, asking again returned the row
already going rather than starting over - so someone who had picked the
wrong garment watched it being drawn and then waited out
`ABANDONED_AFTER`, ten minutes, before the feature would respond at
all. That is also where the stale rows came from: the only way to be
rid of one was to leave it until the sweep took it.

Cancelling writes the row finished, which is what makes retrying free:
nothing is in flight afterwards, so asking again simply asks again.
There is no retry endpoint because there is nothing left to retry past.

The cases that matter, in the order they bite:

  * stopped while queued, which is the common one, must not draw;
  * stopped while the model is working must not overwrite the avatar
    with the picture they told us to stop;
  * somebody else's render is not theirs to stop;
  * a second tap is not an error.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import avatar_renders as renders
from app.models.avatar_render import AvatarRender

from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def _render(db: AsyncSession, *, user_id: uuid.UUID, state: str = "queued"):
    row = AvatarRender(user_id=user_id, kind="base", state=state, pieces=[])
    db.add(row)
    await db.flush()
    await db.commit()
    return row


async def test_cancelling_a_queued_render_finishes_it(db: AsyncSession) -> None:
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)

    stopped = await renders.cancel(db, user_id=user_id, render_id=row.id)

    assert stopped is not None
    assert stopped.state == "failed"
    assert stopped.error == renders.CANCELLED_NOTE
    assert renders.was_cancelled(stopped)


async def test_cancelling_a_running_render_finishes_it(db: AsyncSession) -> None:
    """The model is already working; the row still stops."""
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="running")

    stopped = await renders.cancel(db, user_id=user_id, render_id=row.id)

    assert stopped is not None
    assert renders.was_cancelled(stopped)


async def test_nothing_is_in_flight_once_a_render_is_cancelled(
    db: AsyncSession,
) -> None:
    """The point of cancelling: the next request draws instead of waiting.

    `in_flight` is what made retrying impossible. While it matched, a
    second request was answered with the same row, so the button did
    nothing until the ten-minute sweep.
    """
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)

    assert await renders.in_flight(db, user_id=user_id, kind="base") is not None

    await renders.cancel(db, user_id=user_id, render_id=row.id)

    assert await renders.in_flight(db, user_id=user_id, kind="base") is None


async def test_a_cancelled_render_is_not_counted_as_abandoned(
    db: AsyncSession,
) -> None:
    """It finished. The sweep has no business touching it again."""
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)
    await renders.cancel(db, user_id=user_id, render_id=row.id)
    await db.refresh(row)

    assert not renders.abandoned(row)
    assert await renders.sweep_abandoned(db, user_id=user_id) == 0


async def test_another_persons_render_cannot_be_cancelled(db: AsyncSession) -> None:
    """`None`, the same answer as a render that does not exist.

    Telling the two apart would confirm the id belongs to somebody.
    """
    owner_id = await make_user(db)
    stranger_id = await make_user(db)
    row = await _render(db, user_id=owner_id)

    assert await renders.cancel(db, user_id=stranger_id, render_id=row.id) is None

    await db.refresh(row)
    assert row.state == "queued", "a stranger changed somebody else's render"


async def test_cancelling_an_unknown_render_is_not_found(db: AsyncSession) -> None:
    user_id = await make_user(db)
    assert await renders.cancel(db, user_id=user_id, render_id=uuid.uuid4()) is None


async def test_cancelling_twice_is_not_an_error(db: AsyncSession) -> None:
    """A person double-tapping stop has not made a mistake.

    The screen and the database disagree for a few hundred
    milliseconds every time, so the second tap is expected traffic.
    """
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)

    first = await renders.cancel(db, user_id=user_id, render_id=row.id)
    second = await renders.cancel(db, user_id=user_id, render_id=row.id)

    assert first is not None and second is not None
    assert second.state == "failed"
    assert second.error == renders.CANCELLED_NOTE


async def test_cancelling_a_finished_render_leaves_the_picture_alone(
    db: AsyncSession,
) -> None:
    """Stop arriving after the picture landed must not undo it."""
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="ready")

    result = await renders.cancel(db, user_id=user_id, render_id=row.id)

    assert result is not None
    assert result.state == "ready", "a late cancel threw away a finished picture"
    assert not renders.was_cancelled(result)


async def test_a_real_failure_is_not_mistaken_for_a_cancellation(
    db: AsyncSession,
) -> None:
    """`was_cancelled` is what the worker trusts, so it has to be exact."""
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="running")
    await renders.mark_failed(db, render=row, reason="the model refused")

    assert not renders.was_cancelled(row)
    assert renders.public_reason(row.error) is not None


# --------------------------------------------------------------------------
# The worker side: what the handler does when the row says "stopped".
# --------------------------------------------------------------------------


class _Job:
    """Just the two fields `_run` reads.

    A persisted `Job` row would drag in `available_at` and the rest of
    the queue's schema, none of which this handler touches - and a test
    that fails on an unrelated NOT NULL constraint says nothing about
    cancelling.
    """

    def __init__(self, render_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.payload = {"render_id": str(render_id)}


async def test_the_worker_does_not_draw_a_render_that_was_cancelled(
    db: AsyncSession,
) -> None:
    """The branch that does not spend the money.

    Most cancels land while the render is queued, because queued is
    where it waits. Drawing anyway would pay for a picture nobody will
    ever see.
    """
    from app.workers import avatar_jobs

    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)
    await renders.cancel(db, user_id=user_id, render_id=row.id)

    drawn = False

    async def draw(session, render, *, renderer, store):
        nonlocal drawn
        drawn = True
        raise AssertionError("drew a render that had been cancelled")

    result = await avatar_jobs._run(db, _Job(row.id), renderer=None, store=None, draw=draw)

    assert drawn is False
    assert result == {
        "render_id": str(row.id),
        "state": "cancelled",
        "drawn": False,
    }


async def test_a_cancel_during_drawing_does_not_replace_the_avatar(
    db: AsyncSession,
) -> None:
    """The case worth the refresh.

    The stop arrives in another request while the model is working, so
    the worker's copy of the row is half a minute stale. Writing
    `ready` from that copy would make the avatar the very picture they
    asked us to abandon - and they would have watched it happen.
    """
    from app.workers import avatar_jobs

    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)

    class Asset:
        id = uuid.uuid4()

    async def draw(session, render, *, renderer, store):
        # Mid-draw, somebody taps stop. A different request, which for
        # the purposes of this test is simply a write and a commit.
        await renders.cancel(session, user_id=user_id, render_id=row.id)
        return Asset()

    result = await avatar_jobs._run(db, _Job(row.id), renderer=None, store=None, draw=draw)

    assert result is not None
    assert result["state"] == "cancelled"
    assert result["drawn"] is True

    await db.refresh(row)
    assert row.state == "failed", "the cancelled render was marked ready anyway"
    assert row.media_asset_id is None, "a cancelled render became the avatar"


async def test_a_render_nobody_cancelled_still_finishes(db: AsyncSession) -> None:
    """The refresh must not break the ordinary path."""
    from app.workers import avatar_jobs

    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)

    class Asset:
        id = uuid.uuid4()

    async def draw(session, render, *, renderer, store):
        return Asset()

    result = await avatar_jobs._run(db, _Job(row.id), renderer=None, store=None, draw=draw)

    assert result is not None
    assert result["state"] == "ready"
    await db.refresh(row)
    assert row.state == "ready"
    assert row.media_asset_id == Asset.id


# --------------------------------------------------------------------------
# Over HTTP, which is what the stop button on the progress card calls.
# --------------------------------------------------------------------------


async def test_the_endpoint_stops_a_render_and_frees_the_next_request(client, auth) -> None:
    """The whole loop as the screen performs it: ask, stop, ask again.

    The second `POST /v1/avatar` is the assertion that matters. Before
    cancelling existed it answered with the same render id for ten
    minutes, which is what made the feature look dead.
    """
    who = {"headers": auth(sub="kc-avatar-cancel-1")}
    await client.post("/v1/auth/session", **who)

    asked = await client.post("/v1/avatar", **who)
    assert asked.status_code == 202, asked.text
    first = asked.json()
    assert first["state"] in ("queued", "running")

    stopped = await client.post(f"/v1/avatar/renders/{first['id']}/cancel", **who)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["state"] == "failed"

    again = await client.post("/v1/avatar", **who)
    assert again.status_code == 202, again.text
    assert again.json()["id"] != first["id"], "asking again returned the render that was stopped"


async def test_the_endpoint_will_not_stop_somebody_elses_render(client, auth) -> None:
    """404, the same answer as an id that does not exist."""
    owner = {"headers": auth(sub="kc-avatar-cancel-2")}
    stranger = {"headers": auth(sub="kc-avatar-cancel-3")}
    await client.post("/v1/auth/session", **owner)
    await client.post("/v1/auth/session", **stranger)

    asked = await client.post("/v1/avatar", **owner)
    render_id = asked.json()["id"]

    refused = await client.post(f"/v1/avatar/renders/{render_id}/cancel", **stranger)
    assert refused.status_code == 404

    mine = await client.get(f"/v1/avatar/renders/{render_id}", **owner)
    assert mine.json()["state"] in ("queued", "running"), (
        "a stranger stopped somebody else's render"
    )


async def test_stopping_an_unknown_render_is_a_404(client, auth) -> None:
    who = {"headers": auth(sub="kc-avatar-cancel-4")}
    await client.post("/v1/auth/session", **who)
    missing = await client.post(f"/v1/avatar/renders/{uuid.uuid4()}/cancel", **who)
    assert missing.status_code == 404


async def test_the_reason_shown_for_a_stopped_render_is_the_cancellation(client, auth) -> None:
    """Not "that one did not come out": nothing went wrong.

    `public_reason` rewrites stored failures into something a reader
    can act on, and a cancellation must not be dressed up as bad luck
    when the person is the one who stopped it.
    """
    who = {"headers": auth(sub="kc-avatar-cancel-5")}
    await client.post("/v1/auth/session", **who)
    asked = await client.post("/v1/avatar", **who)

    stopped = await client.post(f"/v1/avatar/renders/{asked.json()['id']}/cancel", **who)
    body = stopped.json()

    shown = body.get("error_text") or body.get("error") or ""
    assert shown == renders.CANCELLED_NOTE, f"a cancellation was dressed up as a failure: {shown!r}"
    assert renders.UNLUCKY not in shown


async def test_a_stopped_render_is_flagged_as_stopped_not_merely_failed(client, auth) -> None:
    """The flag the screen needs, because both are `failed`.

    The avatar screen retries the newest failure when somebody pulls
    down, which is the gesture people reach for first. Without a way
    to tell a cancellation from a fault, that gesture bought the render
    again the moment anybody stopped one.

    A field rather than matching on the sentence: the copy belongs to
    the server and will be reworded, and a screen whose behaviour
    depends on its exact wording breaks silently when it is.
    """
    who = {"headers": auth(sub="kc-avatar-cancel-6")}
    await client.post("/v1/auth/session", **who)
    asked = await client.post("/v1/avatar", **who)

    stopped = await client.post(f"/v1/avatar/renders/{asked.json()['id']}/cancel", **who)
    body = stopped.json()

    assert body["state"] == "failed"
    assert body["stopped"] is True


async def test_a_render_that_actually_failed_is_not_flagged_as_stopped(
    db: AsyncSession,
) -> None:
    """Otherwise pull-to-refresh would stop retrying real failures."""
    from app.routers.avatar import _render_out

    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="running")
    await renders.mark_failed(db, render=row, reason="the model refused")

    out = _render_out(row)
    assert out.state == "failed"
    assert out.stopped is False


async def test_a_render_still_drawing_is_not_flagged_as_stopped(
    db: AsyncSession,
) -> None:
    from app.routers.avatar import _render_out

    user_id = await make_user(db)
    row = await _render(db, user_id=user_id)

    assert _render_out(row).stopped is False


def test_an_object_without_the_fields_is_not_treated_as_cancelled() -> None:
    """`_render_out` is typed on `object` and reads every field defensively.

    The safe answer for anything unrecognisable is "not cancelled":
    that keeps a picture. The other default throws one away.
    """

    class Bare:
        pass

    assert renders.was_cancelled(Bare()) is False
