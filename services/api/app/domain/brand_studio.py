"""Making a set of brand visuals from one product photograph.

**A story is several frames of the same product, asked for once.** That is
the whole difference from the garment studio, and it is the thing a small
label actually needs: not one picture, but the four a drop takes.

**The frames are `garment_shots`.** Each one is an edit of a photograph the
brand owns, which is exactly what a studio shot already is. Reusing the row
means a frame inherits the ownership check, the billing, the storage path
and the tombstone, and cannot drift out of step with them. What a story
adds is a brief, a cast, an optional reference, and an order.

**A reference fit is read into words, never used as a second image.** The
vendor's edit endpoint takes one image (verified; see
`MetaProvider.edit_image`), so a fit from Discover cannot be composited
with a product. What it can do is describe the light, the palette and the
styling, and that description rides into the prompt. The API returns the
note so a brand can see exactly how much of the reference reached the
picture, rather than being left to assume it was copied.

**Nothing describes the person in the reference.** The description comes
from `fit_vision`, whose schema has no field for it and whose prompt
forbids it by name. A reference is for its light and its styling.

**Video is blocked.** Every model reachable here takes video in and none
emits it. `capabilities()` says so, with the reason, so a client renders
the truth instead of a button that cannot work.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import feed, fit_descriptions
from app.domain import garment_studio as studio
from app.domain.jobs import enqueue
from app.models.brand_story import BrandStory
from app.models.garment_studio import GarmentShot
from app.workers.brand_studio import (
    MAX_STYLE_NOTE,
    Cast,
    clean_brief,
    compose,
    scene_by_id,
    story_kind_by_id,
)

#: Shares the studio's job kind, because a frame *is* a studio shot: one
#: handler, one retry policy, one place a stuck picture is traced to.
FRAME_JOB_KIND = studio.SHOT_JOB_KIND

#: The most frames one story may hold. Each is a billed image call, so a
#: story is a handful of pictures rather than an open-ended batch.
MAX_FRAMES = 6

MAX_TITLE = 120


class NoSuchStoryKind(Exception):
    """Not one of the ready-made sets."""


class NoSuchScene(Exception):
    """Not one of the frames a story can contain."""


class StoryNotFound(Exception):
    """No such story, as far as this caller is concerned."""


async def style_note_from_fit(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID
) -> str | None:
    """The styling in a published fit, in words, if it may be read.

    Gated through the feed: a fit whose author is blocked either way, or
    which has been withdrawn, is not a reference. Returns nothing rather
    than raising when the fit has simply never been described - a story
    without a reference is a story, and refusing to start one because a
    description has not been computed yet would be the wrong trade.
    """
    if await feed.one(db, user_id=user_id, post_id=post_id) is None:
        return None
    described = await fit_descriptions.get(db, post_id=post_id)
    if described is None:
        # Queue the reading so the *next* story off this reference has it.
        await fit_descriptions.request_description(db, post_id=post_id)
        return None
    return (described.outfit or "")[:MAX_STYLE_NOTE] or None


async def start(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str = "launch",
    scenes: Sequence[str] | None = None,
    title: str | None = None,
    brief: str | None = None,
    cast: dict[str, str] | None = None,
    garment_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    reference_post_id: uuid.UUID | None = None,
) -> tuple[BrandStory, list[GarmentShot]]:
    """Record a story and queue a frame per scene. Returns at once.

    `scenes` overrides the ready-made set, which is how a request for one
    particular frame is expressed without a second code path.

    The source photograph is resolved and ownership-checked once, here,
    rather than per frame: every frame edits the same picture, and a
    second check would be a second chance to get it wrong.
    """
    chosen = story_kind_by_id(kind)
    if chosen is None and scenes is None:
        raise NoSuchStoryKind(kind)

    wanted = tuple(scenes) if scenes else (chosen.scenes if chosen else ())
    resolved = []
    for scene_id in wanted[:MAX_FRAMES]:
        scene = scene_by_id(scene_id)
        if scene is None:
            raise NoSuchScene(scene_id)
        resolved.append(scene)
    if not resolved:
        raise NoSuchScene("a story needs at least one frame")

    # Raises NotYourGarment / NoPhotograph, which the caller maps to 404.
    source, from_garment = await studio.resolve_source(
        db, user_id=user_id, garment_id=garment_id, asset_id=asset_id
    )

    note = None
    if reference_post_id is not None:
        note = await style_note_from_fit(
            db, user_id=user_id, post_id=reference_post_id
        )

    picked = Cast.from_choices(cast)
    story = BrandStory(
        user_id=user_id,
        kind=kind if chosen is not None else "custom",
        title=(title or "").strip()[:MAX_TITLE] or None,
        brief=clean_brief(brief) or None,
        cast={k: v for k, v in picked.__dict__.items() if v},
        # Stored even when the note came back empty: it records that this
        # story was asked for with that reference in mind.
        reference_post_id=reference_post_id,
        style_note=note,
        state="working",
    )
    db.add(story)
    await db.flush()

    frames: list[GarmentShot] = []
    for position, scene in enumerate(resolved):
        frame = GarmentShot(
            user_id=user_id,
            source_asset_id=source.id,
            garment_id=from_garment,
            treatment=scene.id,
            # The exact wording this frame runs, stored so the picture can
            # be explained and repeated. The studio's own shots leave this
            # null and run their treatment's fixed prompt.
            prompt=compose(
                scene=scene, brief=story.brief, cast=picked, style_note=note
            ),
            story_id=story.id,
            position=position,
            state="queued",
        )
        db.add(frame)
        frames.append(frame)
    await db.flush()

    for frame in frames:
        job = await enqueue(
            db,
            FRAME_JOB_KIND,
            {"shot_id": str(frame.id), "user_id": str(user_id)},
            idempotency_key=f"{FRAME_JOB_KIND}:{frame.id}",
        )
        frame.job_id = job.id

    await db.commit()
    await db.refresh(story)
    for frame in frames:
        await db.refresh(frame)
    return story, frames


async def get(
    db: AsyncSession, *, user_id: uuid.UUID, story_id: uuid.UUID
) -> BrandStory | None:
    return await db.scalar(
        sa.select(BrandStory).where(
            BrandStory.id == story_id,
            BrandStory.user_id == user_id,
            BrandStory.deleted_at.is_(None),
        )
    )


async def frames(
    db: AsyncSession, *, story_id: uuid.UUID
) -> list[GarmentShot]:
    """The frames of a story, in the order they were asked for."""
    rows = await db.scalars(
        sa.select(GarmentShot)
        .where(GarmentShot.story_id == story_id, GarmentShot.deleted_at.is_(None))
        .order_by(GarmentShot.position.asc())
    )
    return list(rows)


async def recent(
    db: AsyncSession, *, user_id: uuid.UUID, limit: int = 20
) -> list[BrandStory]:
    rows = await db.scalars(
        sa.select(BrandStory)
        .where(BrandStory.user_id == user_id, BrandStory.deleted_at.is_(None))
        .order_by(BrandStory.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def settle(story: BrandStory, frames: Sequence[GarmentShot]) -> str:
    """What state a story is in, from its frames.

    Three outcomes rather than two: a set where three of four frames came
    back is useful and must not read as a failure, so it is `partial` and
    says which frame is missing.
    """
    if not frames:
        return "failed"
    states = [frame.state for frame in frames]
    if all(state == "ready" for state in states):
        return "ready"
    if any(state in ("queued", "running") for state in states):
        return "working"
    return "partial" if any(state == "ready" for state in states) else "failed"


async def refresh_state(
    db: AsyncSession, *, story: BrandStory
) -> BrandStory:
    """Recompute a story's state from its frames and store it."""
    found = await frames(db, story_id=story.id)
    settled = settle(story, found)
    if story.state != settled:
        story.state = settled
        await db.commit()
        await db.refresh(story)
    return story


async def discard(
    db: AsyncSession, *, user_id: uuid.UUID, story_id: uuid.UUID
) -> bool:
    """Throw a story and its frames away. Tombstoned, like everything here."""
    story = await get(db, user_id=user_id, story_id=story_id)
    if story is None:
        return False
    story.deleted_at = sa.func.now()
    for frame in await frames(db, story_id=story.id):
        await studio.discard(db, user_id=user_id, shot_id=frame.id)
    await db.commit()
    return True


__all__ = [
    "FRAME_JOB_KIND",
    "MAX_FRAMES",
    "NoSuchScene",
    "NoSuchStoryKind",
    "StoryNotFound",
    "discard",
    "frames",
    "get",
    "recent",
    "refresh_state",
    "settle",
    "start",
    "style_note_from_fit",
]
