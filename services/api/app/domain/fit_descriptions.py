"""Storing what a posted fit is wearing, and putting it on somebody.

**Both model calls happen on a worker, in one job.** Reading a photograph
costs a call and so does drawing an avatar, so tapping "Try it on" writes a
render row and answers at once, exactly as every other paid call in this
service does (ADR-005, ADR-013). The reading and the drawing then run
together on the render job rather than as two queued jobs: two would need
the reading to land before the drawing, and nothing orders them.

A standalone describe job exists as well, for reading fits nobody has tried
on yet - a seeded world, or a backfill after a prompt change.

**A description is read once and reused.** Two people trying the same fit
pay for the reading once between them, and a fit that has been described
makes "Try it on" a single image call.

**The gate is `feed.one`.** A fit must be visible to the person asking
before it is read, described, or worn. Blocks, withdrawals and deletions
all answer alike, so a refusal confirms nothing - the same doctrine the
board and the detail route already use.

**The author's caption is never overwritten.** The generated caption lives
on the description row and is offered where the author wrote nothing. Their
words stay their words.
"""

from __future__ import annotations

import uuid
from typing import Any
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import avatar_renders, feed
from app.domain.jobs import enqueue
from app.models.avatar_render import AvatarRender
from app.models.fit_description import FitDescriptionRow
from app.models.media_asset import MediaAsset
from app.models.posts import Post, PostMedia
from app.models.profile import PostTag
from app.workers.fit_vision import FitDescription, Piece

#: Routed to the AI queue by prefix, like every other paid call.
DESCRIBE_JOB_KIND = "post.describe"


class FitNotVisible(Exception):
    """No such fit, as far as this reader is concerned."""


class NoPhotograph(Exception):
    """The fit has no readable photograph to describe."""


async def get(
    db: AsyncSession, *, post_id: uuid.UUID
) -> FitDescriptionRow | None:
    return await db.get(FitDescriptionRow, post_id)


async def for_posts(
    db: AsyncSession, post_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, FitDescriptionRow]:
    """Descriptions for a board of fits, in one query.

    The board renders a caption per tile, so fetching these one at a time
    would be a query per tile.
    """
    if not post_ids:
        return {}
    rows = await db.scalars(
        sa.select(FitDescriptionRow).where(
            FitDescriptionRow.post_id.in_(list(post_ids))
        )
    )
    return {row.post_id: row for row in rows}


def shown_caption(post: Post, described: FitDescriptionRow | None) -> str | None:
    """What a card shows under a fit.

    The author's words first, always. The generated one only fills a gap -
    a caption that names the clothes is better than no caption, and worse
    than the one the person actually wrote.
    """
    written = (post.caption or "").strip()
    if written:
        return written
    return (described.caption or "").strip() or None if described else None


async def photograph(
    db: AsyncSession, *, post_id: uuid.UUID
) -> MediaAsset | None:
    """The first readable picture on a fit.

    First rather than best: a post is an ordered set of pictures and the
    one its author put first is the one they led with.
    """
    return await db.scalar(
        sa.select(MediaAsset)
        .join(PostMedia, PostMedia.media_asset_id == MediaAsset.id)
        .where(
            PostMedia.post_id == post_id,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status.in_(("uploaded", "ready")),
        )
        .order_by(PostMedia.position.asc())
    )


async def store(
    db: AsyncSession, *, post_id: uuid.UUID, described: FitDescription
) -> FitDescriptionRow:
    """Write a description, replacing whatever was there.

    Also writes the tags, because a tag is how Discover groups a fit and a
    description that did not reach the grouping would have improved nothing
    anybody can see. Tags the author wrote are left alone: this adds, and
    the unique constraint on (post, tag) means adding one twice adds it
    once.
    """
    row = await db.get(FitDescriptionRow, post_id)
    if row is None:
        row = FitDescriptionRow(post_id=post_id)
        db.add(row)
    row.outfit = described.outfit
    row.caption = described.caption or None
    row.pieces = [
        {"name": p.name, "colour": p.colour, "category": p.category}
        for p in described.pieces
    ]
    row.model = described.model
    row.prompt_version = described.prompt_version

    if described.tags:
        existing = set(
            (
                await db.scalars(
                    sa.select(PostTag.tag).where(PostTag.post_id == post_id)
                )
            ).all()
        )
        for tag in described.tags:
            if tag not in existing:
                db.add(PostTag(post_id=post_id, tag=tag))
                existing.add(tag)

    await db.commit()
    await db.refresh(row)
    return row


async def request_description(
    db: AsyncSession, *, post_id: uuid.UUID
) -> None:
    """Queue a reading of this fit, unless one is already queued.

    Keyed on the post, so twenty people opening the same fit in the same
    minute pay for one reading.
    """
    # **Pinned to the picture as it was uploaded.**
    #
    # The cover can be reshaped after a post is made - a landscape
    # one is turned upright - and a vision model reading a
    # photograph that has been rotated a quarter turn describes a
    # person lying down. Naming the asset here means the reading is
    # of what the author actually took, whatever the shell does to
    # it afterwards for display.
    asset = await photograph(db, post_id=post_id)
    await enqueue(
        db,
        DESCRIBE_JOB_KIND,
        {
            "post_id": str(post_id),
            "asset_id": str(asset.id) if asset is not None else None,
        },
        idempotency_key=f"{DESCRIBE_JOB_KIND}:{post_id}",
    )
    await db.commit()


async def describe_now(
    db: AsyncSession,
    *,
    post_id: uuid.UUID,
    reader: object,
    objects: object,
    asset_id: uuid.UUID | None = None,
) -> FitDescriptionRow:
    """Read the photograph and store the result. The worker's half.

    Never called from a request handler: it makes a model call, which
    belongs on a worker like every other paid call here. The object store
    is passed in rather than reached for, so a test can run this against
    bytes in memory.
    """
    # The one named when the job was written, when there is one:
    # the cover may have been reshaped since, and a reading of a
    # rotated photograph describes a person lying down.
    asset = (
        await db.get(MediaAsset, asset_id)
        if asset_id is not None
        else await photograph(db, post_id=post_id)
    ) or await photograph(db, post_id=post_id)
    if asset is None or not asset.storage_key:
        raise NoPhotograph()

    data = await objects.read(asset)  # type: ignore[attr-defined]
    described = await reader.describe(  # type: ignore[attr-defined]
        image=data, content_type=asset.content_type or "image/jpeg"
    )
    if not described.usable:
        raise NoPhotograph()
    return await store(db, post_id=post_id, described=described)


async def pieces_of(db: AsyncSession, *, post_id: uuid.UUID) -> list[Any]:
    """The cut-out garments of one fit, in the order they were described.

    Readability is not decided here. These rows only say what was
    cut; whether the bytes come down is asked per request by
    `posts.piece_is_published_to`, which runs the same live join the
    cover does. A caller handing these to somebody who may not see
    the fit would be handing over ids that fetch nothing.
    """
    from app.models.fit_description import FitPieceRow

    rows = await db.scalars(
        sa.select(FitPieceRow)
        .where(FitPieceRow.post_id == post_id)
        .order_by(FitPieceRow.position)
    )
    return list(rows)

async def try_on(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID
) -> AvatarRender:
    """Put the outfit in a published fit on this person's avatar.

    The whole path, and it is the real one: the fit is gated through
    `feed.one`, its outfit sentence comes from the stored description, and
    the picture is drawn by the same try-on worker that dresses the avatar
    in a curated look. Nothing here is a fixture.

    A fit nobody has read yet is read **by the render worker**, not by a
    second job queued alongside this one. Two jobs would need the reading
    to land before the drawing, and nothing orders them; one job that
    describes and then draws cannot get that wrong. The description it
    writes is stored, so the next person to try the same fit skips it.
    """
    visible = await feed.one(db, user_id=user_id, post_id=post_id)
    if visible is None:
        raise FitNotVisible()

    described = await get(db, post_id=post_id)
    return await avatar_renders.request(
        db,
        user_id=user_id,
        kind="try_on",
        # Empty when the fit has not been read. The worker fills it in and
        # fails loudly if it cannot, rather than drawing a person in
        # nothing and calling that a result.
        outfit=(described.outfit if described else None) or None,
        pieces=list(described.pieces) if described else [],
        source_post_id=post_id,
    )


def as_pieces(row: FitDescriptionRow | None) -> tuple[Piece, ...]:
    """The stored pieces, back in the worker's shape."""
    if row is None:
        return ()
    return tuple(
        Piece(
            name=str(item.get("name") or ""),
            colour=item.get("colour"),
            category=item.get("category"),
        )
        for item in (row.pieces or [])
        if item.get("name")
    )


__all__ = [
    "DESCRIBE_JOB_KIND",
    "FitNotVisible",
    "NoPhotograph",
    "as_pieces",
    "describe_now",
    "for_posts",
    "get",
    "photograph",
    "request_description",
    "shown_caption",
    "store",
    "try_on",
]
