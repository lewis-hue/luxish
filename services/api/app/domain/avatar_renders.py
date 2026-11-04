"""Asking for an avatar picture, and finding out what happened to it.

The request handler's whole job here is to write a row and enqueue work. It
must not call the model: drawing an avatar measured at **27 seconds** and a
try-on at 15 to 21, which is a connection held open for half a minute, a Cloud
Run request timeout waiting to happen, and no record of the work at all if the
process dies mid-call. Every other model call in this service already goes
through a durable job (ADR-005, ADR-013); the avatar was the exception and it
was an oversight.

**The row exists before the work does.** That is the whole of the durability:
"this person asked for a picture" is recorded whether or not the worker, the
broker, or the model survives the next thirty seconds. A render that fails is
a row saying so rather than a request that timed out with nothing behind it.

**One render in flight per person per kind.** Asking twice while the first is
still drawing is asking once — the idempotency key sees to it — which matters
because each duplicate is a paid call for a picture nobody will look at.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import enqueue
from app.models.avatar_render import AvatarRender

#: Job kinds. Routed to the AI queue by prefix, like every other paid call.
GENERATE_JOB_KIND = "avatar.generate"
TRY_ON_JOB_KIND = "avatar.try_on"
LIKENESS_JOB_KIND = "avatar.from_photo"

#: The most pieces a render carries.
#:
#: Matches the outfit detector's own cap for the same reason it has one: more
#: than this in one picture is a misreading rather than an outfit.
MAX_PIECES = 8

#: How long an error message may be. Mirrors the column.
MAX_ERROR = 300


async def latest(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str | None = None
) -> AvatarRender | None:
    """The newest render, optionally of one kind."""
    query = sa.select(AvatarRender).where(AvatarRender.user_id == user_id)
    if kind is not None:
        query = query.where(AvatarRender.kind == kind)
    return await session.scalar(query.order_by(AvatarRender.created_at.desc()))


async def get(
    session: AsyncSession, *, user_id: uuid.UUID, render_id: uuid.UUID
) -> AvatarRender | None:
    """One render, if it belongs to this person."""
    return await session.scalar(
        sa.select(AvatarRender).where(
            AvatarRender.id == render_id, AvatarRender.user_id == user_id
        )
    )


#: What a reader is told when a drawing fails.
#:
#: **The vendor's words are not for them.** A failed render stored
#: "Error code: 400 - The response was filtered due to the prompt
#: triggering our content management policy", and the avatar screen
#: printed it. Three things wrong with that, in order of how much
#: they matter:
#:
#:   * it is not actionable. Nobody reading it knows what to do, and
#:     the one thing they *should* do - try again - was not offered;
#:   * it is not theirs. It describes our provider's moderation, our
#:     prompt and our status code, none of which is a fact about the
#:     person or about the outfit they tapped;
#:   * it reads as an accusation. "Content management policy" under a
#:     picture of a hoodie and jeans suggests they asked for
#:     something they did not ask for.
#:
#: The detail is not thrown away - it stays on the row and in the
#: run ledger, which is where somebody debugging this looks. What
#: crosses to the client is a sentence this app wrote.
UNLUCKY = "That one did not come out. Pull down to try again."

#: Matched against the stored reason, in order. First hit wins.
#:
#: Narrow on purpose: a reason only earns its own line when there is
#: something different for the reader to do about it.
_PLAINLY: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("content management", "content_filter", "content policy", "filtered"),
        # Deliberately not "your request was blocked". The filter
        # trips on the *garment description* - "bare feet with toe
        # rings" tripped it - and telling somebody their outfit was
        # rejected for policy reasons is both alarming and wrong.
        "This outfit could not be drawn. Pull down to try again.",
    ),
    (
        ("rate limit", "429", "too many requests"),
        "The studio is busy. Pull down to try again in a moment.",
    ),
    (
        ("timeout", "timed out"),
        "That took too long. Pull down to try again.",
    ),
    (
        ("quota", "insufficient", "credit", "billing"),
        "Drawing is unavailable right now. Try again later.",
    ),
)


def public_reason(error: str | None) -> str | None:
    """The sentence a reader gets for a stored failure.

    `None` in, `None` out: a render that did not fail has nothing to
    say. Anything else becomes one of the lines above, and never the
    stored text itself.
    """
    if not error:
        return None
    lowered = error.lower()
    for needles, said in _PLAINLY:
        if any(needle in lowered for needle in needles):
            return said
    return UNLUCKY


#: After this long, a render that still says it is being drawn is not.
#:
#: **A row that never finished is worse than a row that failed.** A
#: base render measured at 27 seconds and a try-on at 15 to 21, so
#: nothing legitimate is still working ten minutes later. What is left
#: at that point is a job whose worker died, whose broker dropped it,
#: or that was queued while the stack was down - and the row sits in
#: `queued` for ever.
#:
#: That row does two kinds of damage, both seen on a real account that
#: had one stranded from four days earlier:
#:
#:   * the screen reads "a picture is being drawn" and never stops, so
#:     the progress card sits over a finished avatar permanently and
#:     the client polls every three seconds for ever;
#:   * `in_flight` matches it, so the next request for that kind of
#:     picture is answered with the dead row instead of drawing - the
#:     feature appears to do nothing at all.
#:
#: Ten minutes rather than one: a worker that is merely slow, or a
#: queue being drained after a restart, must not have its work
#: declared dead out from under it.
ABANDONED_AFTER = timedelta(minutes=10)


def abandoned(render: AvatarRender, *, now: datetime | None = None) -> bool:
    """Whether this row says it is working but plainly is not."""
    if render.state not in ("queued", "running"):
        return False
    made = render.created_at
    if made is None:
        return False
    if made.tzinfo is None:
        made = made.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - made > ABANDONED_AFTER


async def sweep_abandoned(
    session: AsyncSession, *, user_id: uuid.UUID
) -> int:
    """Fail this person's stranded renders. Returns how many.

    **Healing on read, rather than only in a scheduled sweep.** The
    damage is to a screen somebody is looking at right now, and the
    account that has the problem is by definition the one asking. A
    periodic reaper would also work and would not fix the phone in
    somebody's hand this second.

    Idempotent, and narrow: only rows past the cutoff, only this
    person's, and the state it writes is `failed`, which every caller
    already handles.
    """
    cutoff = datetime.now(UTC) - ABANDONED_AFTER
    done = await session.execute(
        sa.update(AvatarRender)
        .where(
            AvatarRender.user_id == user_id,
            AvatarRender.state.in_(("queued", "running")),
            AvatarRender.created_at < cutoff,
        )
        .values(
            state="failed",
            # Said plainly. The client shows this, and "it was never
            # picked up" is a truer account than a generic failure.
            error="This one was never finished. Ask for it again.",
        )
    )
    return int(done.rowcount or 0)


async def recent(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 20
) -> Sequence[AvatarRender]:
    """This person's renders, newest first.

    Stranded rows are failed first, so the list never reports work
    that is not happening. See `sweep_abandoned`.
    """
    if await sweep_abandoned(session, user_id=user_id):
        await session.commit()
    result = await session.scalars(
        sa.select(AvatarRender)
        .where(AvatarRender.user_id == user_id)
        .order_by(AvatarRender.created_at.desc())
        .limit(limit)
    )
    return result.all()


async def in_flight(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    source_post_id: uuid.UUID | None = None,
    source_asset_id: uuid.UUID | None = None,
) -> AvatarRender | None:
    """A render of this kind and subject that has not finished.

    Used to answer "is one already drawing" without a second table: a paid
    call that nobody will wait for is the thing worth not making twice.

    **The subject is part of the match, and the query not the caller does
    it.** Matching only the newest in-flight render against the subject was
    a real defect: trying fit A, then fit B, then A again paid for a third
    picture, because A was no longer the newest. A base render has no
    subject, so it matches on kind alone.
    """
    query = sa.select(AvatarRender).where(
        AvatarRender.user_id == user_id,
        AvatarRender.kind == kind,
        AvatarRender.state.in_(("queued", "running")),
        # A stranded row is not work in flight. Without this the next
        # request for this kind of picture is answered with a job that
        # died days ago, and the button appears to do nothing.
        AvatarRender.created_at >= datetime.now(UTC) - ABANDONED_AFTER,
    )
    if kind != "base":
        query = query.where(
            AvatarRender.source_post_id.is_(source_post_id)
            if source_post_id is None
            else AvatarRender.source_post_id == source_post_id,
            AvatarRender.source_asset_id.is_(source_asset_id)
            if source_asset_id is None
            else AvatarRender.source_asset_id == source_asset_id,
        )
    return await session.scalar(query.order_by(AvatarRender.created_at.desc()))


async def request(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    outfit: str | None = None,
    pieces: list[dict[str, Any]] | None = None,
    source_post_id: uuid.UUID | None = None,
    source_asset_id: uuid.UUID | None = None,
    note: str | None = None,
) -> AvatarRender:
    """Record the request and queue the work. Returns immediately.

    Returns the render already in flight rather than starting a second one.
    Two pictures of the same thing is two paid calls and one of them is
    thrown away before anybody sees it.
    """
    # Trying on a second thing while the first is still drawing is two
    # different pictures, so the subject is part of the match.
    existing = await in_flight(
        session,
        user_id=user_id,
        kind=kind,
        source_post_id=source_post_id,
        source_asset_id=source_asset_id,
    )
    if existing is not None:
        return existing

    render = AvatarRender(
        user_id=user_id,
        kind=kind,
        state="queued",
        source_post_id=source_post_id,
        source_asset_id=source_asset_id,
        note=note,
        outfit=(outfit or None),
        # Written from what was asked for, never detected back out of the
        # finished picture: the garments are already known exactly.
        pieces=(pieces or [])[:MAX_PIECES],
    )
    session.add(render)
    await session.flush()

    job_kind = {
        "base": GENERATE_JOB_KIND,
        "from_photo": LIKENESS_JOB_KIND,
    }.get(kind, TRY_ON_JOB_KIND)
    job = await enqueue(
        session,
        job_kind,
        {"render_id": str(render.id), "user_id": str(user_id)},
        # Keyed on the render, so a retried request rides the same job rather
        # than paying for a second picture.
        idempotency_key=f"{job_kind}:{render.id}",
    )
    render.job_id = job.id
    await session.commit()
    await session.refresh(render)
    return render


async def mark_running(session: AsyncSession, *, render: AvatarRender) -> None:
    render.state = "running"
    await session.commit()


async def mark_ready(
    session: AsyncSession, *, render: AvatarRender, media_asset_id: uuid.UUID
) -> None:
    render.state = "ready"
    render.media_asset_id = media_asset_id
    render.error = None
    await session.commit()


async def mark_failed(
    session: AsyncSession, *, render: AvatarRender, reason: str
) -> None:
    """Record why, in the words the failure used.

    A failed render that says nothing is indistinguishable from one still
    drawing, and the screen has to tell somebody which.
    """
    render.state = "failed"
    render.error = reason.strip()[:MAX_ERROR] or "The picture could not be drawn."
    await session.commit()


__all__ = [
    "ABANDONED_AFTER",
    "AvatarRender",
    "GENERATE_JOB_KIND",
    "MAX_ERROR",
    "MAX_PIECES",
    "TRY_ON_JOB_KIND",
    "abandoned",
    "get",
    "in_flight",
    "latest",
    "mark_failed",
    "mark_ready",
    "mark_running",
    "public_reason",
    "recent",
    "request",
    "sweep_abandoned",
]
