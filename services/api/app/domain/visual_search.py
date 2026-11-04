"""Searching by picture.

A camera in a search field means one thing everywhere it appears: find
me things like this. On this screen it used to photograph a garment
into the wardrobe, which is useful and is not what the icon promises.

**It reads the clothes, then searches the words.** There is no image
index here and building one would be a different project; what exists
is a reader that names the garments in a photograph, and tags that
people actually used. Reading the picture into words and searching
those is the honest version, and it is also explicable: the answer
comes back saying what it thought it saw.

**It is a job, because it is a model call** (ADR-013). The handler
writes a row and answers at once; the client polls. A visual search
takes five to nine seconds, which is slow for a search and is the real
cost of reading a photograph - saying so beats pretending otherwise
with a spinner that never explains itself.

**The picture must be the caller's own upload.** An asset id in a
request is a claim, re-validated against its owner and its kind. The
repository rule holds: analysis runs on user-supplied media only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import enqueue
from app.models.job import Job
from app.models.media_asset import MediaAsset

#: Routed to the AI queue by prefix, like every other paid call.
VISUAL_SEARCH_JOB_KIND = "search.visual"

#: What a picture may be uploaded as for this. An outfit photograph or
#: one of the person: both are things somebody might point a camera at
#: and ask "what is this". Never a garment photograph, which belongs to
#: the wardrobe's own pipeline and would have the cut-out and
#: categorisation jobs already running over it.
SEARCHABLE_KINDS: tuple[str, ...] = ("outfit_photo", "inspiration")


class NoSuchPhotograph(Exception):
    """Not this caller's, or not a kind that can be searched."""


@dataclass(frozen=True)
class VisualSearch:
    """Where a search got to, and what it found."""

    job_id: uuid.UUID
    state: str
    #: Tags read out of the picture, best first. Empty until it lands.
    tags: tuple[str, ...] = ()
    #: What the reader thought the outfit was, so the answer can
    #: explain itself rather than just jumping somewhere.
    outfit: str = ""
    #: The garments it named. Carried because the matcher reads the
    #: nouns to decide what kind of thing was photographed, and a
    #: tag is a word about the whole picture rather than a piece.
    pieces: tuple[str, ...] = ()
    error: str | None = None


async def owned_photograph(
    db: AsyncSession, *, user_id: uuid.UUID, asset_id: uuid.UUID
) -> MediaAsset:
    asset = await db.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.user_id == user_id,
            MediaAsset.kind.in_(SEARCHABLE_KINDS),
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status.in_(("uploaded", "ready")),
        )
    )
    if asset is None or not asset.storage_key:
        raise NoSuchPhotograph()
    return asset


async def start(
    db: AsyncSession, *, user_id: uuid.UUID, asset_id: uuid.UUID
) -> VisualSearch:
    """Queue a reading of this picture. Returns at once."""
    asset = await owned_photograph(db, user_id=user_id, asset_id=asset_id)
    job = await enqueue(
        db,
        VISUAL_SEARCH_JOB_KIND,
        {"asset_id": str(asset.id), "user_id": str(user_id)},
        # Keyed on the picture, so tapping search twice on the same one
        # reads it once.
        idempotency_key=f"{VISUAL_SEARCH_JOB_KIND}:{asset.id}",
    )
    await db.commit()
    return VisualSearch(job_id=job.id, state=job.state)


async def read(
    db: AsyncSession, *, user_id: uuid.UUID, job_id: uuid.UUID
) -> VisualSearch | None:
    """Where a search got to.

    Returns nothing for a job that is not this caller's, which is the
    same answer as one that never existed: a job id is guessable and a
    different answer would confirm somebody else's search exists.
    """
    job = await db.get(Job, job_id)
    if job is None or job.kind != VISUAL_SEARCH_JOB_KIND:
        return None
    if str((job.payload or {}).get("user_id")) != str(user_id):
        return None

    result = job.result or {}
    return VisualSearch(
        job_id=job.id,
        state=job.state,
        tags=tuple(result.get("tags") or ()),
        outfit=str(result.get("outfit") or ""),
        pieces=tuple(result.get("pieces") or ()),
        error=job.last_error,
    )


__all__ = [
    "SEARCHABLE_KINDS",
    "VISUAL_SEARCH_JOB_KIND",
    "NoSuchPhotograph",
    "VisualSearch",
    "owned_photograph",
    "read",
    "start",
]
