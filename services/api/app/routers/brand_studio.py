"""Brand story routes: make a set of visuals from one product.

Thin, like the other studio router, and for the same reasons.

**A story is requested, not awaited.** Each frame is an image edit of 15
to 30 billed seconds, so `POST` answers 202 with queued frames and the
client polls (ADR-005, ADR-013).

**Every id is re-validated against the caller.** A garment or an asset
that is not theirs is a 404, never a 403, and a reference fit goes through
the same visibility gate Discover uses.

**The capability endpoint says what is not possible.** Video is blocked
and the reason is returned with it, because a client that had to guess
would render a button that cannot work.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import brand_studio as domain
from app.domain import garment_studio as studio
from app.errors import ApiError
from app.models.brand_story import BrandStory
from app.models.garment_studio import GarmentShot
from app.schemas.brand_studio import (
    FrameOut,
    SceneOut,
    StoriesOut,
    StoryCreate,
    StoryKindOut,
    StoryOut,
    StudioCapabilitiesOut,
)
from app.workers.brand_studio import (
    CAST_OPTIONS,
    SCENES,
    STORY_KINDS,
    VIDEO_REASON,
    VIDEO_STATUS,
)

router = APIRouter(prefix="/studio", tags=["brand-studio"])

#: Returned with the capabilities because it decides what is possible,
#: and a client that did not know it would promise the wrong thing.
SOURCE_NOTE = (
    "Every frame is built from your product's own photograph, so its "
    "colour, print and texture are the real ones. The model takes a "
    "single source image: a fit you pick as a reference contributes its "
    "light, palette and styling as a written note, and its photograph is "
    "never combined with yours."
)


def _frame(shot: GarmentShot) -> FrameOut:
    return FrameOut(
        id=shot.id,
        scene=shot.treatment,
        position=shot.position or 0,
        state=shot.state,
        media_asset_id=shot.media_asset_id,
        error=shot.error,
    )


def _story(story: BrandStory, frames: list[GarmentShot]) -> StoryOut:
    return StoryOut(
        id=story.id,
        kind=story.kind,
        title=story.title,
        brief=story.brief,
        cast=dict(story.cast or {}),
        state=story.state,
        reference_post_id=story.reference_post_id,
        style_note=story.style_note,
        frames=[_frame(frame) for frame in frames],
        created_at=story.created_at,
    )


@router.get("/capabilities", response_model=StudioCapabilitiesOut)
async def capabilities() -> StudioCapabilitiesOut:
    """What the studio can do. Static, and the same for everybody."""
    return StudioCapabilitiesOut(
        scenes=[
            SceneOut(
                id=scene.id,
                label=scene.label,
                description=scene.description,
                use=scene.use,
                aspect=scene.aspect,
                wears=scene.wears,
            )
            for scene in SCENES
        ],
        kinds=[
            StoryKindOut(
                id=kind.id,
                label=kind.label,
                description=kind.description,
                scenes=list(kind.scenes),
            )
            for kind in STORY_KINDS
        ],
        cast_options={key: list(values) for key, values in CAST_OPTIONS.items()},
        video=VIDEO_STATUS,
        video_reason=VIDEO_REASON,
        source_note=SOURCE_NOTE,
    )


@router.post(
    "/stories", response_model=StoryOut, status_code=status.HTTP_202_ACCEPTED
)
async def create_story(
    payload: StoryCreate, db: SessionDep, ctx: AuthDep
) -> StoryOut:
    """Start a set of frames from one product. Answers at once."""
    if payload.garment_id is None and payload.media_asset_id is None:
        raise ApiError(
            "Name the product to shoot: a garment of yours, or a photograph.",
            status_code=422,
            code="no_source",
        )
    try:
        story, frames = await domain.start(
            db,
            user_id=ctx.user_id,
            kind=payload.kind,
            scenes=payload.scenes,
            title=payload.title,
            brief=payload.brief,
            cast=payload.cast,
            garment_id=payload.garment_id,
            asset_id=payload.media_asset_id,
            reference_post_id=payload.reference_post_id,
        )
    except domain.NoSuchStoryKind:
        raise ApiError(
            "No such set. Try one of: "
            + ", ".join(kind.id for kind in STORY_KINDS)
            + ".",
            status_code=422,
            code="bad_story_kind",
        ) from None
    except domain.NoSuchScene:
        raise ApiError(
            "No such frame. Try one of: "
            + ", ".join(scene.id for scene in SCENES)
            + ".",
            status_code=422,
            code="bad_scene",
        ) from None
    except (studio.NotYourGarment, studio.NoPhotograph):
        # The same answer for "not yours" and "has no photograph": a
        # different one would confirm that somebody else's id exists.
        raise ApiError(
            "No such product.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return _story(story, frames)


@router.get("/stories", response_model=StoriesOut)
async def read_stories(db: SessionDep, ctx: AuthDep) -> StoriesOut:
    """Your stories, newest first, each with its frames."""
    stories = await domain.recent(db, user_id=ctx.user_id)
    out = []
    for story in stories:
        frames = await domain.frames(db, story_id=story.id)
        out.append(_story(story, frames))
    return StoriesOut(items=out)


@router.get("/stories/{story_id}", response_model=StoryOut)
async def read_story(
    story_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> StoryOut:
    """One story, for polling while its frames are being made."""
    story = await domain.get(db, user_id=ctx.user_id, story_id=story_id)
    if story is None:
        raise ApiError(
            "No such story.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    # Recomputed on read rather than written by each frame as it lands:
    # four workers racing to update one row is four chances to settle it
    # wrong, and the frames are the truth either way.
    story = await domain.refresh_state(db, story=story)
    return _story(story, await domain.frames(db, story_id=story.id))


@router.delete("/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_story(
    story_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> None:
    """Throw a story and its frames away. Only yours, and only once."""
    if not await domain.discard(db, user_id=ctx.user_id, story_id=story_id):
        raise ApiError(
            "No such story.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
