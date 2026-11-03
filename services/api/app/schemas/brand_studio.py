"""Brand story request and response shapes."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.workers.brand_studio import MAX_BRIEF


class SceneOut(BaseModel):
    id: str
    label: str
    description: str
    #: What the frame is shaped for: ``feed``, ``story`` or ``catalogue``.
    use: str
    #: Asked for in words, not cropped to. Advisory.
    aspect: str
    #: True when a person appears, which is when a cast means anything.
    wears: bool


class StoryKindOut(BaseModel):
    id: str
    label: str
    description: str
    scenes: list[str] = Field(default_factory=list)


class StudioCapabilitiesOut(BaseModel):
    """What the brand studio can and cannot do, stated plainly."""

    scenes: list[SceneOut] = Field(default_factory=list)
    kinds: list[StoryKindOut] = Field(default_factory=list)
    #: The closed vocabularies a cast is chosen from. Asked, never
    #: inferred: nothing in this service reads appearance off a garment,
    #: a photograph or a prompt.
    cast_options: dict[str, list[str]] = Field(default_factory=dict)
    #: ``blocked``. No model reachable here emits video.
    video: str = "blocked"
    video_reason: str = ""
    #: Said because it decides what is possible: one source image means a
    #: reference fit contributes words, not pixels.
    source_note: str = ""


class StoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: One of the ready-made sets, or omit and name `scenes` instead.
    kind: str = Field(default="launch", max_length=32)
    #: Overrides the set, for one particular frame or a hand-picked list.
    scenes: list[str] | None = Field(default=None, max_length=6)
    title: str | None = Field(default=None, max_length=120)
    #: The brand's own direction, in their words.
    brief: str | None = Field(default=None, max_length=MAX_BRIEF)
    #: Who is wearing it, from the closed vocabularies above. Anything
    #: unrecognised is dropped rather than passed into a prompt.
    cast: dict[str, str] | None = None
    #: The product. One of these two.
    garment_id: uuid.UUID | None = None
    media_asset_id: uuid.UUID | None = None
    #: A fit from Discover to take the styling from. Its light, palette
    #: and layering reach the prompt as words; the photograph itself is
    #: never a second input, because the model takes one image.
    reference_post_id: uuid.UUID | None = None


class FrameOut(BaseModel):
    id: uuid.UUID
    scene: str
    position: int
    state: str
    media_asset_id: uuid.UUID | None = None
    error: str | None = None


class StoryOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str | None = None
    brief: str | None = None
    cast: dict[str, str] = Field(default_factory=dict)
    #: ``working``, ``ready``, ``partial`` or ``failed``. Partial is a real
    #: outcome: three frames of four is a usable set.
    state: str
    #: The reference fit, and the words actually taken from it. Both, so a
    #: brand can see how much of the reference reached the pictures.
    reference_post_id: uuid.UUID | None = None
    style_note: str | None = None
    frames: list[FrameOut] = Field(default_factory=list)
    created_at: datetime | None = None


class StoriesOut(BaseModel):
    items: list[StoryOut] = Field(default_factory=list)


__all__ = [
    "FrameOut",
    "SceneOut",
    "StoriesOut",
    "StoryCreate",
    "StoryKindOut",
    "StoryOut",
    "StudioCapabilitiesOut",
]
