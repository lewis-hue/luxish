"""Regional style context routes.

Thin by design, like the other routers: all resolution lives in
:mod:`app.domain.regional`.

Two things about this endpoint are deliberate rather than incidental:

* **It does not require a device location.** `place` is an optional free-text name the
  user typed, and omitting it is a supported outcome rather than an error — a user who
  declines location permission still gets a usable response, just with coverage
  ``none``. That is acceptance criterion 5.
* **It returns weather nowhere.** Geographic style context, live weather and retailer
  inventory are three separate concerns (§7), and merging them into one response body
  is how they stop being separable.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Query

from app.deps import AuthDep, SessionDep
from app.domain import regional
from app.schemas.regional import RegionalContextResponse

router = APIRouter(prefix="/regional", tags=["regional"])


@router.get("/context", response_model=RegionalContextResponse)
async def read_regional_context(
    db: SessionDep,
    ctx: AuthDep,
    place: str | None = Query(
        default=None,
        max_length=160,
        description="A place name the user typed, e.g. 'Nairobi'. Omit it when the "
        "user has declined location — the response is still usable.",
    ),
    date: datetime.date | None = Query(
        default=None,
        description="Date being styled for. Defaults to today; a travel date changes "
        "the resolved season.",
    ),
    occasion: str | None = Query(default=None, max_length=64),
) -> RegionalContextResponse:
    context = await regional.regional_context(
        db,
        place=place,
        date=date,
        occasion=occasion,
        # No device-fix value exists in PLACE_SOURCES by design: a coarse device
        # location must be reverse-geocoded to a name before it reaches this layer,
        # so coordinates are never stored against style guidance.
        place_source="user_manual" if place else "declined",
    )
    return RegionalContextResponse.from_context(context)
