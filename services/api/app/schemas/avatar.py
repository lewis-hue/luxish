"""Avatar request and response shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Presentation = Literal["feminine", "masculine", "androgynous", "unspecified"]
BodyType = Literal["slim", "average", "athletic", "curvy", "plus", "unspecified"]
Height = Literal["tall", "average", "short", "unspecified"]
AgeBand = Literal["20s", "30s", "40s", "50s", "60s_plus", "unspecified"]
SkinTone = Literal[
    "very_fair", "fair", "medium", "olive", "brown", "dark_brown", "deep", "unspecified"
]


class AppearanceIn(BaseModel):
    """What someone says about how they look.

    Every field optional and defaulting to unspecified. This is asked, never
    derived: nothing in this service may read presentation off a wardrobe, and
    an avatar with nothing stated is still drawn.
    """

    presentation: Presentation = "unspecified"
    body_type: BodyType = "unspecified"
    height: Height = "unspecified"
    age_band: AgeBand = "unspecified"
    skin_tone: SkinTone = "unspecified"


class AppearanceOut(AppearanceIn):
    pass


class VehicleIn(BaseModel):
    """Which figure to use. False means the mannequin."""

    on_my_avatar: bool


class AvatarOut(BaseModel):
    #: Null until one has been generated.
    asset_id: str | None = None
    #: What the avatar was drawn from, so a client can show it and offer to
    #: change it rather than making somebody guess why it looks as it does.
    appearance: AppearanceOut
    #: Whether this person has asked to be shown on a photorealistic
    #: likeness instead of the mannequin.
    #:
    #: **The mannequin is the default for everybody, new or old.**
    #: Having generated a likeness once is not the same as choosing to
    #: see it everywhere, and before this the mere existence of one
    #: took over the profile - with no way back short of deleting it.
    #: The client shows the mannequin unless this is true.
    on_my_avatar: bool = False


class PieceOut(BaseModel):
    """One garment in a picture, as it was asked for.

    Never detected back out of the finished image: when the avatar is dressed
    in an outfit the garments are already known, so re-reading them would pay a
    vision call to guess at something in hand.
    """

    name: str
    colour: str | None = None
    category: str | None = None


class PieceIn(PieceOut):
    pass


class TryOnIn(BaseModel):
    #: Plain words describing the outfit. The look's own pieces, or the
    #: garments from a wardrobe, rendered as a sentence by the caller.
    outfit: Annotated[str, Field(min_length=3, max_length=600)]
    #: Which curated look this came from, when it came from one.
    #: The garments, so the finished picture can be labelled and each piece
    #: searched for without a second model call.
    pieces: list[PieceIn] = Field(default_factory=list, max_length=8)


class LikenessIn(BaseModel):
    """Build an avatar from a photograph of yourself."""

    #: A photograph you uploaded with kind `avatar_source`. Re-validated
    #: against your account and that kind before anything is read: an id
    #: in a request is a claim.
    media_asset_id: str
    #: Anything you want to say about how it should look, in your own
    #: words. It cannot change who is in the picture - the instruction to
    #: keep the person comes before it and is repeated after it.
    note: str | None = Field(default=None, max_length=400)


class LikenessPhotoOut(BaseModel):
    """One photograph you uploaded of yourself, so you can remove it."""

    asset_id: str
    content_type: str | None = None
    created_at: datetime | None = None


class LikenessPhotosOut(BaseModel):
    items: list[LikenessPhotoOut] = Field(default_factory=list)
    #: Said plainly, because it is the thing somebody wants to know:
    #: removing a photograph does not delete avatars already drawn.
    note: str = (
        "Removing a photograph deletes the picture you uploaded. Avatars "
        "already drawn from it are kept, and you can delete those "
        "separately."
    )


class RenderOut(BaseModel):
    """A picture that was asked for, and where it got to.

    `state` is the whole point: drawing takes 15 to 27 seconds on a worker,
    so a client is told immediately what it asked for and polls this.
    """

    id: str
    #: `from_photo` is a likeness drawn from a photograph the person
    #: uploaded of themselves, as against `base`, which is a figure drawn
    #: from what they said about how they look.
    kind: Literal["base", "try_on", "from_photo"]
    state: Literal["queued", "running", "ready", "failed"]
    #: Null until the picture exists.
    asset_id: str | None = None
    outfit: str | None = None
    pieces: list[PieceOut] = Field(default_factory=list)
    #: Why it failed, in the words the failure used. Null unless `failed`.
    error: str | None = None


class RendersResponse(BaseModel):
    items: list[RenderOut]


__all__ = [
    "AppearanceIn",
    "LikenessIn",
    "LikenessPhotoOut",
    "LikenessPhotosOut",
    "AppearanceOut",
    "AvatarOut",
    "PieceIn",
    "PieceOut",
    "RenderOut",
    "RendersResponse",
    "TryOnIn",
]
