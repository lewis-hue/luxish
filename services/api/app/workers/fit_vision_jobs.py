"""The handler that reads a posted fit, off the request path.

Standalone from the try-on path on purpose. A try-on reads the fit it is
about to wear, inside the render job, because the drawing cannot start
without it. This job exists for the other reason to read a fit: so that
Discover has captions and tags for photographs nobody has tried on yet -
a seeded world, a backfill after a prompt change, or a post whose author
published it without saying what it was.

**A fit with no readable photograph is finished, not failed.** There is
nothing to retry: the post has no picture, or its picture is gone. Failing
would put the job back on the queue to find the same absence.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import fit_descriptions
from app.models.job import Job


def _asset_id(job: Job) -> uuid.UUID | None:
    """The picture named when the job was written, if one was."""
    raw = (job.payload or {}).get("asset_id")
    if not raw:
        return None
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


def _post_id(job: Job) -> uuid.UUID:
    raw = (job.payload or {}).get("post_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no post_id")
    return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))


async def describe_fit_job(
    session: AsyncSession,
    job: Job,
    *,
    reader: object,
    store: object,
    segmenter: object | None = None,
) -> dict | None:
    """Read one fit and store what its clothes are."""
    post_id = _post_id(job)

    already = await fit_descriptions.get(session, post_id=post_id)
    if already is not None:
        # A re-dispatched job must not pay for a second reading. Re-reading
        # on purpose is a delete-then-describe, not a retry.
        return {"post_id": str(post_id), "state": "described", "repeat": True}

    try:
        row = await fit_descriptions.describe_now(
            session,
            post_id=post_id,
            reader=reader,
            objects=store,
            # Named when the job was written, so a cover reshaped
            # since is not what gets read.
            asset_id=_asset_id(job),
        )
    except fit_descriptions.NoPhotograph:
        return {"post_id": str(post_id), "state": "no_photograph"}

    # And the garments themselves, cut out of the photograph.
    #
    # Here rather than in the try-on, because it is the same answer
    # for everybody: the first person to open a fit pays for the
    # reading and the cutting, and the hundredth pays nothing.
    #
    # Never allowed to fail the description. The sentence is the
    # result and the cut-outs are an improvement on it, so a
    # segmenter that is down costs the pictures and leaves the fit
    # described, captioned and tryable the way it was before.
    cut = 0
    if segmenter is not None:
        from app.workers.fit_pieces import cut_pieces

        try:
            cut = await cut_pieces(
                session,
                post_id=post_id,
                segmenter=segmenter,
                store=store,
                job_id=job.id,
            )
        except Exception:  # noqa: BLE001 - see above
            logging.getLogger(__name__).exception(
                "could not cut the pieces", extra={"post": str(post_id)}
            )

    return {
        "post_id": str(post_id),
        "state": "described",
        "pieces": len(row.pieces or []),
        "cut": cut,
    }


__all__ = ["describe_fit_job"]
