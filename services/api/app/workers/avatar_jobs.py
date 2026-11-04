"""The handlers that actually draw an avatar, off the request path.

Two kinds, and they are different operations for the reason
:mod:`app.workers.avatar` already records: generating is text-to-image because
there is no source photograph, and dressing is image-to-image because the
whole point is the same person in the same pose wearing something else.

What is new here is only *where* they run. Both were being awaited inside a
request handler at 15 to 27 seconds a call. Now they are jobs, which buys the
three things a job always buys: the request returns at once, a process that
dies mid-call leaves a row that can be retried, and the work is attributable
to a job id when somebody asks why a picture never arrived.

**A failure is recorded, not swallowed.** `CapabilityUnavailable` from a
missing store, a refusal from the model, a bad content type — each one ends as
a `failed` render carrying the reason. The alternative is a render that stays
`running` forever, which a screen cannot distinguish from a slow one.

**A try-on from somebody else's fit reads the photograph here.** Tapping
"Try it on" under a fit on Discover carries a post id and, the first time
anybody tries that fit, no outfit sentence. Reading the clothes out of the
photograph is a model call, so it happens on this worker and not in the
handler — and it happens in the *same* job as the drawing, because two jobs
would need the reading to land before the drawing and nothing orders them.
The description is stored, so the second person to try that fit skips
straight to the drawing.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import avatar as avatar_domain
from app.domain import avatar_renders as renders
from app.errors import CapabilityUnavailable
from app.models.job import Job
from app.workers.avatar import AvatarRenderer


def _render_id(job: Job) -> uuid.UUID:
    raw = (job.payload or {}).get("render_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no render_id")
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


async def _run(
    session: AsyncSession,
    job: Job,
    *,
    renderer: AvatarRenderer,
    store: object,
    draw,
) -> dict | None:
    """Shared shape: claim the render, draw, record what happened.

    The two handlers differ only in `draw`, so the state machine lives once.
    Duplicating it would be the place the two drift: one of them would learn
    to record a failure and the other would not.
    """
    render = await session.get(renders.AvatarRender, _render_id(job))
    if render is None:
        # The render was deleted between enqueue and run. Nothing to do, and
        # not a failure: returning None lets the job finish cleanly rather
        # than retrying work whose record is gone.
        return None

    if render.state == "ready":
        # Already done. A re-dispatched job must not pay for a second
        # picture, which is the whole reason the state is on the row.
        return {"render_id": str(render.id), "state": "ready", "repeat": True}

    if renders.was_cancelled(render):
        # Stopped before a worker reached it, which is the common case:
        # the queue is where a render waits, so that is where somebody
        # changing their mind catches it. Returning before `draw` is the
        # point - this is the branch that does not spend the money.
        return {"render_id": str(render.id), "state": "cancelled", "drawn": False}

    await renders.mark_running(session, render=render)
    try:
        asset = await draw(session, render, renderer=renderer, store=store)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a state
        await renders.mark_failed(session, render=render, reason=str(exc))
        # Re-raised so the job records the failure too, and so a transient
        # one is retried by the normal attempt machinery. The render already
        # says what went wrong either way.
        raise

    # **Asked again, now that drawing is over.** The cancel arrived while
    # the model was working, in a different request and a different
    # session, so the copy of the row in this one is half a minute stale.
    # Without the refresh `mark_ready` writes over it and the avatar
    # becomes the picture they told us to stop drawing - the worst of the
    # outcomes, because they watched it happen anyway.
    await session.refresh(render)
    if renders.was_cancelled(render):
        # The row keeps the cancellation. The asset is left where it is
        # rather than deleted: it is a real drawing, the media store
        # already has it, and the tombstoned-deletion path (ADR-012) is
        # what removes media, not an opportunistic unlink in a worker.
        return {
            "render_id": str(render.id),
            "asset_id": str(asset.id),
            "state": "cancelled",
            "drawn": True,
        }

    await renders.mark_ready(session, render=render, media_asset_id=asset.id)
    return {"render_id": str(render.id), "asset_id": str(asset.id), "state": "ready"}


async def generate_avatar_job(
    session: AsyncSession,
    job: Job,
    *,
    renderer: AvatarRenderer,
    store: object,
) -> dict | None:
    """Draw the base figure from what somebody said about how they look."""

    async def draw(session, render, *, renderer, store):
        return await avatar_domain.generate_avatar(
            session, user_id=render.user_id, renderer=renderer, store=store
        )

    return await _run(session, job, renderer=renderer, store=store, draw=draw)


async def try_on_job(
    session: AsyncSession,
    job: Job,
    *,
    renderer: AvatarRenderer,
    store: object,
    reader: object | None = None,
) -> dict | None:
    """Put the requested outfit on the existing avatar.

    `reader` describes a photograph when the render came from a published
    fit that nobody has read yet. Optional so the garment and curated-look
    paths, which already carry their outfit in words, need nothing new.
    """

    async def draw(session, render, *, renderer, store):
        outfit = (render.outfit or "").strip()

        if not outfit and render.source_post_id is not None:
            if reader is None:
                raise CapabilityUnavailable(
                    "This fit has not been read yet and no reader is configured to read it.",
                    detail={"capability": "fit_description"},
                )
            from app.domain import fit_descriptions

            described = await fit_descriptions.describe_now(
                session,
                post_id=render.source_post_id,
                reader=reader,
                objects=store,
            )
            # Stored on the render too, so the finished picture can say
            # what it is wearing without reaching back to the post - which
            # may be withdrawn by the time anybody looks.
            outfit = described.outfit
            render.outfit = outfit[:500]
            render.pieces = list(described.pieces or [])
            await session.commit()

        if not outfit:
            raise CapabilityUnavailable(
                "There is nothing to put on: this render carries no outfit.",
                detail={"capability": "try_on"},
            )

        return await avatar_domain.try_on(
            session,
            user_id=render.user_id,
            outfit=outfit,
            renderer=renderer,
            store=store,
        )

    return await _run(session, job, renderer=renderer, store=store, draw=draw)


async def likeness_job(
    session: AsyncSession,
    job: Job,
    *,
    renderer: AvatarRenderer,
    store: object,
) -> dict | None:
    """Draw an avatar from a photograph the person uploaded of themselves.

    Consent and ownership are both re-checked inside `likeness.draw`
    rather than trusted from the request that queued this. A consent is a
    live answer: somebody may have withdrawn it in the half minute
    between asking and this running, and this is the last moment before
    their face goes to a model.
    """

    async def draw(session, render, *, renderer, store):
        from app.domain import likeness

        return await likeness.draw(session, render=render, renderer=renderer, store=store)

    return await _run(session, job, renderer=renderer, store=store, draw=draw)


__all__ = ["generate_avatar_job", "likeness_job", "try_on_job"]
