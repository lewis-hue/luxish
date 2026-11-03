"""Studio routes: shoot a garment you own, and read what came back.

Thin, like the others. Two things are worth saying out loud.

**A shot is requested, not awaited.** `POST` answers 202 with a queued row
and the client polls, because an image edit is 15 to 30 seconds of billed
work and every other paid call in this service already works that way
(ADR-005, ADR-013).

**Every id is re-validated against the caller's own wardrobe.** A garment
that is not yours is a 404, not a 403, so the refusal confirms nothing —
the same doctrine the posts router uses, for the same reason.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import garment_studio as domain
from app.errors import ApiError
from app.models.garment_studio import GarmentShot
from app.schemas.garment_studio import (
    ShotFromAssetIn,
    SplitStartedOut,
    ShotOut,
    ShotRequestIn,
    ShotsOut,
    TreatmentOut,
    TreatmentsOut,
)
from app.workers.garment_studio import TREATMENTS, treatment_by_id

router = APIRouter(prefix="/garments", tags=["garment-studio"])

#: Said on the treatments endpoint rather than only in a docstring, because
#: the client renders it: the limit is the vendor's, and a UI that quietly
#: omitted the option would leave people hunting for it.
#: Three lines of explanation became one.
#:
#: The long version said the same fact three ways and ran to a
#: paragraph under four buttons, which is the kind of text people stop
#: reading. What a reader has to know is that they cannot pick the
#: model; that the colours are real is what the pictures themselves
#: show.
ONE_IMAGE_NOTE = "You cannot choose the model. The edit invents one."


def _view(shot: GarmentShot) -> ShotOut:
    return ShotOut(
        id=shot.id,
        source_asset_id=shot.source_asset_id,
        garment_id=shot.garment_id,
        treatment=shot.treatment,
        state=shot.state,  # type: ignore[arg-type]
        media_asset_id=shot.media_asset_id,
        error=shot.error,
        brief=shot.brief,
        created_at=shot.created_at,
    )


@router.get("/studio/treatments", response_model=TreatmentsOut)
async def treatments() -> TreatmentsOut:
    """What the studio can do. Static, and the same for everybody."""
    return TreatmentsOut(
        items=[
            TreatmentOut(id=t.id, label=t.label, description=t.description)
            for t in TREATMENTS
        ],
        note=ONE_IMAGE_NOTE,
    )


@router.get("/{garment_id}/studio", response_model=ShotsOut)
async def shots(garment_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> ShotsOut:
    """Every shot of this garment, newest first, whatever state it is in."""
    try:
        found = await domain.shots_for(db, user_id=ctx.user_id, garment_id=garment_id)
    except domain.NotYourGarment:
        raise ApiError(
            "No such garment.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return ShotsOut(items=[_view(shot) for shot in found])


@router.post(
    "/{garment_id}/studio",
    response_model=ShotOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def shoot(
    garment_id: uuid.UUID, payload: ShotRequestIn, db: SessionDep, ctx: AuthDep
) -> ShotOut:
    """Ask for one treatment. Answers at once with a queued shot."""
    treatment = treatment_by_id(payload.treatment)
    if treatment is None:
        raise ApiError(
            f"No such treatment. Try one of: {', '.join(t.id for t in TREATMENTS)}.",
            status_code=422,
            code="bad_treatment",
        )
    try:
        shot = await domain.request(
            db, user_id=ctx.user_id, garment_id=garment_id, treatment=treatment
        )
    except domain.NotYourGarment:
        raise ApiError(
            "No such garment.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    except domain.NoPhotograph:
        raise ApiError(
            "This garment has no photograph to work from. Add one first.",
            status_code=422,
            code="no_photograph",
        ) from None
    return _view(shot)


@router.post(
    "/studio/shots/each",
    response_model=SplitStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def shoot_each(
    payload: ShotFromAssetIn, db: SessionDep, ctx: AuthDep
) -> SplitStartedOut:
    """One picture per garment in the photograph, instead of one of the lot.

    **The grouped shot is the default and this is the opt-in.** Handed
    a photograph of a shirt and trousers, the packshot treatment
    returns a single picture with both in it, which is what somebody
    making an image wants. This is the other case: the same
    photograph as two catalogue images, one per garment.

    Answers with a job rather than the pictures. How many there will
    be is however many garments a vision call finds, and that call
    belongs on a worker (ADR-013); the shots appear in the studio's
    list as they are made.
    """
    treatment = treatment_by_id(payload.treatment)
    if treatment is None:
        raise ApiError(
            f"No such treatment. Try one of: {', '.join(t.id for t in TREATMENTS)}.",
            status_code=422,
            code="bad_treatment",
        )
    if payload.media_asset_id is None and payload.garment_id is None:
        raise ApiError(
            "Name a photograph or a garment to shoot.",
            status_code=422,
            code="no_source",
        )
    try:
        job_id = await domain.request_each(
            db,
            user_id=ctx.user_id,
            treatment=treatment,
            garment_id=payload.garment_id,
            asset_id=payload.media_asset_id,
            brief=payload.brief,
            landscape=payload.landscape,
        )
    except domain.NotYourGarment:
        raise ApiError(
            "No such garment.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    except domain.NoPhotograph:
        raise ApiError(
            "No such photograph.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return SplitStartedOut(job_id=job_id)


@router.get("/studio/shots/{shot_id}", response_model=ShotOut)
async def shot(shot_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> ShotOut:
    """One shot, for polling while it is being taken."""
    found = await domain.get(db, user_id=ctx.user_id, shot_id=shot_id)
    if found is None:
        raise ApiError(
            "No such shot.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    return _view(found)


@router.delete("/studio/shots/{shot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard(shot_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Throw a shot away. Only yours, and only once."""
    if not await domain.discard(db, user_id=ctx.user_id, shot_id=shot_id):
        raise ApiError(
            "No such shot.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )


@router.get("/studio/shots", response_model=ShotsOut)
async def recent_shots(db: SessionDep, ctx: AuthDep) -> ShotsOut:
    """Everything you have shot, newest first.

    The stylist's view. Shots taken there are often of a photograph with
    no wardrobe row behind it, so there is no garment to group them under.
    """
    return ShotsOut(items=[_view(shot) for shot in await domain.recent(db, user_id=ctx.user_id)])


@router.post(
    "/studio/shots",
    response_model=ShotOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def shoot_asset(
    payload: ShotFromAssetIn, db: SessionDep, ctx: AuthDep
) -> ShotOut:
    """Shoot a photograph you own, wardrobe item or not.

    The path the stylist uses: it is handed an asset id, which may be a
    garment's photograph or one just uploaded from the camera roll.
    """
    treatment = treatment_by_id(payload.treatment)
    if treatment is None:
        raise ApiError(
            f"No such treatment. Try one of: {', '.join(t.id for t in TREATMENTS)}.",
            status_code=422,
            code="bad_treatment",
        )
    if payload.media_asset_id is None and payload.garment_id is None:
        raise ApiError(
            "Name a photograph or a garment to shoot.",
            status_code=422,
            code="no_source",
        )
    try:
        shot = await domain.request(
            db,
            user_id=ctx.user_id,
            treatment=treatment,
            garment_id=payload.garment_id,
            asset_id=payload.media_asset_id,
            brief=payload.brief,
            landscape=payload.landscape,
        )
    except domain.NotYourGarment:
        raise ApiError(
            "No such garment.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    except domain.NoPhotograph:
        # Same answer for "not yours" and "not usable": a different one
        # would confirm that somebody else's asset id exists.
        raise ApiError(
            "No such photograph.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return _view(shot)
