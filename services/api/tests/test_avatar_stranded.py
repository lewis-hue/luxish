"""A render that says it is being drawn, and is not.

**Found on a real account, four days after the fact.** One row sat in
`queued` from a run where the worker never picked it up. Nothing
cleaned it up, and because both of the questions the app asks about
renders are "is anything working?", that single row did two things at
once: the avatar screen showed its progress card over a finished
picture for ever and polled every three seconds to be told the same
thing, and every later request for a base render was answered with the
dead row instead of drawing a new one - so the button did nothing.

Both are the same bug and both are fixed by the same rule: after ten
minutes, a render that still claims to be working has been abandoned.
Ten rather than one, because a slow worker or a queue being drained
after a restart must not have live work declared dead out from under
it; a base render measures at 27 seconds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import avatar_renders
from app.models.avatar_render import AvatarRender

from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def _render(
    db: AsyncSession, *, user_id: uuid.UUID, state: str, age: timedelta
) -> AvatarRender:
    row = AvatarRender(
        user_id=user_id,
        kind="base",
        state=state,
        pieces=[],
        created_at=datetime.now(UTC) - age,
    )
    db.add(row)
    await db.flush()
    return row


# --------------------------------------------------------------------------- #
# Recognising one
# --------------------------------------------------------------------------- #
async def test_a_render_stuck_for_days_is_abandoned(db: AsyncSession) -> None:
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="queued", age=timedelta(days=4))
    assert avatar_renders.abandoned(row)


async def test_a_render_from_a_moment_ago_is_not(db: AsyncSession) -> None:
    """The window has to be generous, or live work gets killed."""
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="running", age=timedelta(seconds=40))
    assert not avatar_renders.abandoned(row)


async def test_a_finished_render_is_never_abandoned(db: AsyncSession) -> None:
    """However old it is. `ready` is an answer, not a wait."""
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="ready", age=timedelta(days=90))
    assert not avatar_renders.abandoned(row)


# --------------------------------------------------------------------------- #
# Clearing it
# --------------------------------------------------------------------------- #
async def test_the_sweep_fails_it_and_says_why(db: AsyncSession) -> None:
    user_id = await make_user(db)
    row = await _render(db, user_id=user_id, state="queued", age=timedelta(hours=3))
    await db.commit()

    assert await avatar_renders.sweep_abandoned(db, user_id=user_id) == 1
    await db.commit()
    await db.refresh(row)

    assert row.state == "failed"
    # The client shows this line, so it has to read as an account of
    # what happened and what to do, not as a generic failure.
    assert row.error and "again" in row.error.lower()


async def test_the_sweep_leaves_live_work_alone(db: AsyncSession) -> None:
    user_id = await make_user(db)
    fresh = await _render(db, user_id=user_id, state="running", age=timedelta(minutes=1))
    await db.commit()

    assert await avatar_renders.sweep_abandoned(db, user_id=user_id) == 0
    await db.refresh(fresh)
    assert fresh.state == "running"


async def test_the_sweep_is_one_persons_only(db: AsyncSession) -> None:
    """A shared sweep would be a cross-account write on a read."""
    mine = await make_user(db)
    theirs = await make_user(db)
    stuck = await _render(db, user_id=theirs, state="queued", age=timedelta(days=1))
    await db.commit()

    assert await avatar_renders.sweep_abandoned(db, user_id=mine) == 0
    await db.refresh(stuck)
    assert stuck.state == "queued"


async def test_sweeping_twice_changes_nothing_the_second_time(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    await _render(db, user_id=user_id, state="queued", age=timedelta(days=1))
    await db.commit()

    assert await avatar_renders.sweep_abandoned(db, user_id=user_id) == 1
    await db.commit()
    assert await avatar_renders.sweep_abandoned(db, user_id=user_id) == 0


# --------------------------------------------------------------------------- #
# The two things it was breaking
# --------------------------------------------------------------------------- #
async def test_the_list_stops_reporting_work_that_is_not_happening(
    db: AsyncSession,
) -> None:
    """**Why the progress card never left the screen.**

    The client's "is anything being drawn" is a scan of this list for a
    queued or running row. One stranded row makes that true for ever.
    """
    user_id = await make_user(db)
    await _render(db, user_id=user_id, state="queued", age=timedelta(days=4))
    await db.commit()

    listed = await avatar_renders.recent(db, user_id=user_id)

    assert [row.state for row in listed] == ["failed"]


async def test_a_stranded_render_does_not_block_the_next_one(
    db: AsyncSession,
) -> None:
    """**Why the button appeared to do nothing.**

    `in_flight` exists so asking twice while a picture is drawing is
    asking once - one paid call, not two. Matching a four-day-old
    corpse turns that saving into a refusal to ever draw again.
    """
    user_id = await make_user(db)
    await _render(db, user_id=user_id, state="queued", age=timedelta(days=4))
    await db.commit()

    assert await avatar_renders.in_flight(db, user_id=user_id, kind="base") is None


async def test_work_actually_in_flight_still_blocks_a_second_call(
    db: AsyncSession,
) -> None:
    """The saving the rule above must not cost."""
    user_id = await make_user(db)
    live = await _render(
        db, user_id=user_id, state="running", age=timedelta(seconds=20)
    )
    await db.commit()

    found = await avatar_renders.in_flight(db, user_id=user_id, kind="base")
    assert found is not None and found.id == live.id


async def test_the_sweep_does_not_touch_rows_it_did_not_fail(
    db: AsyncSession,
) -> None:
    """A ready render keeps its picture; the sweep only writes state."""
    user_id = await make_user(db)
    done = await _render(db, user_id=user_id, state="ready", age=timedelta(days=5))
    await db.commit()

    await avatar_renders.sweep_abandoned(db, user_id=user_id)
    await db.commit()

    kept = await db.scalar(
        sa.select(AvatarRender).where(AvatarRender.id == done.id)
    )
    assert kept is not None and kept.state == "ready" and kept.error is None


# --------------------------------------------------------------------------- #
# What a reader is told when it fails
#
# The avatar screen printed the stored failure verbatim: "Error
# code: 400 - The response was filtered due to the prompt triggering
# our content management policy", in a red box under a picture of a
# hoodie and jeans. Three things wrong with it, in the order they
# matter: it is not actionable, it is not a fact about the person or
# their outfit, and "content management policy" reads as an
# accusation about what they asked for.
#
# The detail is not discarded - it stays on the row and in the run
# ledger, which is where somebody debugging this looks. What crosses
# the wire is a sentence this app wrote.
# --------------------------------------------------------------------------- #
def test_the_vendors_words_never_cross_the_wire() -> None:
    said = avatar_renders.public_reason(
        "Error code: 400 - The response was filtered due to the prompt "
        "triggering our content management policy"
    )
    assert said is not None
    for leak in ("error code", "400", "content management", "policy", "prompt"):
        assert leak not in said.lower(), leak
    # And it says what to do, which the original never did.
    assert "try again" in said.lower()


def test_a_render_that_did_not_fail_says_nothing() -> None:
    assert avatar_renders.public_reason(None) is None
    assert avatar_renders.public_reason("") is None


def test_a_reason_earns_its_own_line_only_when_the_action_differs() -> None:
    """Busy is worth saying because waiting is the right response;
    an unrecognised failure gets the general line rather than a
    guess dressed up as a diagnosis."""
    busy = avatar_renders.public_reason("HTTP 429 rate limit exceeded")
    assert busy is not None and "busy" in busy.lower()
    assert avatar_renders.public_reason("some unmapped vendor string") == (
        avatar_renders.UNLUCKY
    )


def test_the_stored_reason_is_still_there_for_whoever_is_debugging(
    db: AsyncSession,
) -> None:
    """The point of the split: the client loses the detail, the row
    keeps it."""
    row = AvatarRender(
        user_id=uuid.uuid4(),
        kind="base",
        state="failed",
        pieces=[],
        error="Error code: 400 - content management policy",
    )
    assert "400" in (row.error or "")
    assert "400" not in (avatar_renders.public_reason(row.error) or "")
