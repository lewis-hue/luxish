"""Planner routes.

`PUT` on a date, because a plan is a statement about a day rather than an
event: sending it twice plans the day once, and the client never has to know
whether a row already existed.
"""

from __future__ import annotations

import uuid

from datetime import date, timedelta

from fastapi import APIRouter, Query, Response, status

from app.deps import AuthDep, SessionDep
from app.domain import planner as domain
from app.errors import ApiError
from app.schemas.planner import PlanIn, PlanOut, PlannerResponse, WornIn

router = APIRouter(prefix="/planner", tags=["planner"])


class NothingPlanned(ApiError):
    status_code = 404
    code = "nothing_planned"
    default_message = "Nothing is planned for that day."


def _out(
    record: object, garments: list, covers: dict | None = None
) -> PlanOut:
    reference = getattr(record, "reference_post_id", None)
    return PlanOut(
        planned_for=getattr(record, "planned_for"),
        garment_ids=garments,
        note=getattr(record, "note", None),
        worn=getattr(record, "worn", None),
        reference_post_id=reference,
        # Looked up for the whole range at once by the caller, so a
        # month of plans is one query rather than thirty.
        reference_asset_id=(covers or {}).get(reference),
    )


async def _one(
    db: SessionDep, record: object, *, user_id: uuid.UUID
) -> PlanOut:
    """One plan, with its clothes. For the routes that return a single day.

    The viewer is passed rather than taken from the record: the cover
    lookup checks what *this person* may see, and reading the owner
    off the row would make the check answer itself.
    """
    found = await domain.garments_in(db, plan_ids=[getattr(record, "id")])
    covers = await domain.covers_for(
        db,
        user_id=user_id,
        post_ids=[getattr(record, "reference_post_id", None)],
    )
    return _out(record, found.get(getattr(record, "id"), []), covers)


@router.get("", response_model=PlannerResponse)
async def read_planner(
    db: SessionDep,
    ctx: AuthDep,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
) -> PlannerResponse:
    """Plans in a range, earliest first. Both ends inclusive.

    Defaults to the fortnight from today, which is what a week strip scrolls
    through without needing a second request.
    """
    first = start or date.today()
    last = end or (first + timedelta(days=13))
    records = await domain.plans_between(db, user_id=ctx.user_id, start=first, end=last)
    # One query for the whole range rather than one per day: a month
    # view asking per plan is thirty round trips to draw one screen.
    covers = await domain.covers_for(
        db,
        user_id=ctx.user_id,
        post_ids=[record.reference_post_id for record in records],
    )
    garments = await domain.garments_in(
        db, plan_ids=[record.id for record in records]
    )
    return PlannerResponse(
        items=[
            _out(record, garments.get(record.id, []), covers)
            for record in records
        ],
        start=first,
        end=last,
    )


@router.put("/{day}", response_model=PlanOut)
async def plan_day(day: date, payload: PlanIn, db: SessionDep, ctx: AuthDep) -> PlanOut:
    """Plan one day, or change what is planned for it."""
    record = await domain.plan_day(
        db,
        user_id=ctx.user_id,
        day=day,
        garment_ids=payload.garment_ids,
        note=payload.note,
        worn=payload.worn,
        reference_post_id=payload.reference_post_id,
    )
    return await _one(db, record, user_id=ctx.user_id)


@router.post("/{day}/worn", response_model=PlanOut)
async def set_worn(day: date, payload: WornIn, db: SessionDep, ctx: AuthDep) -> PlanOut:
    """Answer "did you wear it".

    Separate from `PUT` because it is a different act: one is planning, the
    other is reporting. Folded together, a client wanting to record a day as
    worn would have to resend the clothes, which is how a report accidentally
    becomes an edit.
    """
    record = await domain.mark_worn(db, user_id=ctx.user_id, day=day, worn=payload.worn)
    if record is None:
        raise NothingPlanned()
    return await _one(db, record, user_id=ctx.user_id)


@router.delete("/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def unplan_day(day: date, db: SessionDep, ctx: AuthDep) -> Response:
    """Clear one day.

    204 whether or not anything was there. Clearing an already-empty day is
    work that is done, and an error would make a retried delete look failed.
    """
    await domain.unplan_day(db, user_id=ctx.user_id, day=day)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
