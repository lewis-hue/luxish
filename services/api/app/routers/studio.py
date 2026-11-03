"""The studio route: one read, windowed.

A single overview endpoint rather than one route per card, because every
card answers the same question over the same window and a screen stitched
from five requests is five chances to show two windows at once.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import AuthDep, SessionDep
from app.domain import studio
from app.errors import ApiError
from app.schemas.studio import StudioOverviewOut, TopFitOut

router = APIRouter(prefix="/studio", tags=["studio"])


@router.get("/overview", response_model=StudioOverviewOut)
async def overview(
    db: SessionDep,
    ctx: AuthDep,
    window: str = Query(default="28d"),
) -> StudioOverviewOut:
    """What other people did with the fits you published, in one window.

    Every number excludes the owner's own activity. A fresh account gets
    zeroes over its empty shelf, which is the honest answer rather than a
    404 pretending the studio does not exist yet.
    """
    try:
        data = await studio.overview(db, user_id=ctx.user_id, window=window)
    except studio.UnknownWindow:
        raise ApiError(
            f"{window!r} is not a window. Use one of {sorted(studio.WINDOWS)}.",
            status_code=422,
            code="unknown_window",
        ) from None
    return StudioOverviewOut(
        window=data.window,
        fits=data.fits,
        saves=data.saves,
        reach=data.reach,
        followers=data.followers,
        followers_gained=data.followers_gained,
        series=list(data.series),
        top_fits=[
            TopFitOut(post_id=item.post_id, people=item.people, saves=item.saves)
            for item in data.top_fits
        ],
    )
