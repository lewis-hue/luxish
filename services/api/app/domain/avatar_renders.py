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


async def recent(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 20
) -> Sequence[AvatarRender]:
    """This person's renders, newest first."""
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
    "AvatarRender",
    "GENERATE_JOB_KIND",
    "MAX_ERROR",
    "MAX_PIECES",
    "TRY_ON_JOB_KIND",
    "get",
    "in_flight",
    "latest",
    "mark_failed",
    "mark_ready",
    "mark_running",
    "recent",
    "request",
]
