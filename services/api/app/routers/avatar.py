"""Avatar routes.

Thin, like the others. Three things here are worth saying out loud.

**Drawing happens on a worker, not in the request.** A generate measured at
27 seconds and a try-on at 15 to 21; both used to be awaited here. Every
other paid model call in this service goes through a durable job (ADR-005,
ADR-013) and the avatar was the exception. These handlers now write a row,
queue a job and answer 202; the client polls the render.

**Appearance is asked for, not worked out.** Every other prompt in this
service forbids reading identity off clothing, and a feature that inferred
somebody's presentation from their wardrobe would quietly contradict all of
them. It is a stated preference, editable, with "did not say" available on
every field.

**A try-on costs money, so it is explicit.** Nothing here runs on a schedule
or in the background off the back of a browse: an image edit is a billed call,
and the person asks for it by tapping.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.deps import AuthDep, SessionDep
from app.domain import avatar as domain
from app.domain import avatar_renders as renders
from app.domain import likeness
from app.errors import ApiError
from app.schemas.avatar import (
    AppearanceIn,
    AppearanceOut,
    AvatarOut,
    LikenessIn,
    LikenessPhotoOut,
    LikenessPhotosOut,
    PieceOut,
    RenderOut,
    RendersResponse,
    TryOnIn,
)
from app.workers.avatar import Appearance

router = APIRouter(prefix="/avatar", tags=["avatar"])


class RenderNotFound(ApiError):
    status_code = 404
    code = "render_not_found"
    default_message = "That picture does not exist."


def _out(appearance: Appearance) -> AppearanceOut:
    return AppearanceOut(**appearance.as_stored())


@router.get("", response_model=AvatarOut)
async def read_avatar(db: SessionDep, ctx: AuthDep) -> AvatarOut:
    """The avatar, and what it was drawn from."""
    asset = await domain.current_avatar(db, user_id=ctx.user_id)
    appearance = await domain.read_appearance(db, user_id=ctx.user_id)
    return AvatarOut(
        asset_id=str(asset.id) if asset else None, appearance=_out(appearance)
    )


@router.put("/appearance", response_model=AppearanceOut)
async def set_appearance(
    payload: AppearanceIn, db: SessionDep, ctx: AuthDep
) -> AppearanceOut:
    """Record how somebody says they look.

    Does not redraw the avatar. Changing a detail and regenerating are two
    decisions, and a billed call should not happen as a side effect of
    answering a question.
    """
    stated = await domain.write_appearance(
        db, user_id=ctx.user_id, appearance=Appearance(**payload.model_dump())
    )
    return _out(stated)


def _render_out(render: object) -> RenderOut:
    raw = getattr(render, "pieces", None) or []
    return RenderOut(
        id=str(getattr(render, "id")),
        kind=getattr(render, "kind"),
        state=getattr(render, "state"),
        asset_id=(
            str(getattr(render, "media_asset_id"))
            if getattr(render, "media_asset_id", None)
            else None
        ),
        outfit=getattr(render, "outfit", None),
        pieces=[
            PieceOut(
                name=str(piece.get("name", "")),
                colour=piece.get("colour"),
                category=piece.get("category"),
            )
            for piece in raw
            if isinstance(piece, dict) and piece.get("name")
        ],
        error=getattr(render, "error", None),
    )


@router.post("", response_model=RenderOut, status_code=status.HTTP_202_ACCEPTED)
async def create_avatar(db: SessionDep, ctx: AuthDep) -> RenderOut:
    """Ask for the avatar to be drawn. Returns at once; poll the render.

    **202, not 201.** Drawing measured at 27 seconds, which is a connection
    held open for half a minute and a request timeout waiting to happen. The
    work is a durable job like every other paid model call in this service
    (ADR-005, ADR-013); this handler writes a row and queues it.

    Asking again while one is already drawing returns the same render rather
    than paying for a second picture nobody will look at.
    """
    render = await renders.request(db, user_id=ctx.user_id, kind="base")
    return _render_out(render)


@router.post("/try-on", response_model=RenderOut, status_code=status.HTTP_202_ACCEPTED)
async def try_on(payload: TryOnIn, db: SessionDep, ctx: AuthDep) -> RenderOut:
    """Ask for an outfit to be put on the avatar. Returns at once.

    An image edit rather than a fresh drawing, which is what keeps it the
    same person in the same pose against the same wall; a new figure each
    time would make comparing two outfits meaningless.

    The pieces travel with the request and are stored as asked for, so the
    finished picture can be labelled and each garment searched without a
    second model call.
    """
    render = await renders.request(
        db,
        user_id=ctx.user_id,
        kind="try_on",
        outfit=payload.outfit,
        pieces=[piece.model_dump() for piece in payload.pieces],
    )
    return _render_out(render)


@router.post(
    "/from-photo",
    response_model=RenderOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def from_photo(
    payload: LikenessIn, db: SessionDep, ctx: AuthDep
) -> RenderOut:
    """Build an avatar that looks like you, from a photograph of you.

    An edit of your own photograph rather than a figure drawn to a
    description, which is the only way the result actually resembles
    anybody. Your words ride along as a note; nothing is read *out* of
    the picture, and no attribute of your stated appearance is ever
    written from an image.

    **403 until you have agreed to it.** `likeness` is its own consent:
    a photograph of your face going to a model is a different question
    from letting the stylist read your wardrobe, and one answer must not
    stand in for the other.

    404 for a photograph that is not yours or not an `avatar_source`
    upload, which are the same answer on purpose.
    """
    try:
        render = await likeness.request(
            db,
            user_id=ctx.user_id,
            asset_id=uuid.UUID(payload.media_asset_id),
            note=payload.note,
        )
    except ValueError:
        raise ApiError(
            "No such photograph.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    except likeness.NeedsLikenessConsent:
        raise ApiError(
            "Building an avatar from your photograph needs your agreement "
            "first. Nothing is sent until you give it, and you can "
            "withdraw it at any time.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="likeness_consent_required",
        ) from None
    except likeness.NoSuchPhotograph:
        raise ApiError(
            "No such photograph.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return _render_out(render)


@router.get("/photos", response_model=LikenessPhotosOut)
async def read_photos(db: SessionDep, ctx: AuthDep) -> LikenessPhotosOut:
    """Photographs of yourself you have uploaded.

    Listed so they can be removed. A feature that takes a picture of
    somebody's face and offers no way to find it again is not one they
    can withdraw from in practice.
    """
    found = await likeness.photographs(db, user_id=ctx.user_id)
    return LikenessPhotosOut(
        items=[
            LikenessPhotoOut(
                asset_id=str(asset.id),
                content_type=asset.content_type,
                created_at=asset.created_at,
            )
            for asset in found
        ]
    )


@router.delete("/photos/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_photo(
    asset_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> Response:
    """Remove a photograph of yourself. 204 either way.

    Avatars already drawn from it are kept: the link is `SET NULL`, and
    somebody deleting the source is asking for the photograph to go, not
    for a picture they liked to be destroyed.
    """
    await likeness.forget(db, user_id=ctx.user_id, asset_id=asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/renders", response_model=RendersResponse)
async def read_renders(db: SessionDep, ctx: AuthDep) -> RendersResponse:
    """Everything this person has asked for, newest first."""
    items = await renders.recent(db, user_id=ctx.user_id)
    return RendersResponse(items=[_render_out(render) for render in items])


@router.get("/renders/{render_id}", response_model=RenderOut)
async def read_render(
    render_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> RenderOut:
    """One render, for polling.

    404 for somebody else's, rather than 403: distinguishing them would
    confirm the id exists.
    """
    render = await renders.get(db, user_id=ctx.user_id, render_id=render_id)
    if render is None:
        raise RenderNotFound()
    return _render_out(render)
