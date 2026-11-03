"""Taste routes.

`PUT` rather than `POST`: this states what somebody's answers *are*, so
sending it twice is not two profiles and the client never has to know whether
a row already existed. Re-answering overwrites, because deselecting an
aesthetic has to be able to take it back.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthDep, SessionDep
from app.domain import taste as domain
from app.schemas.taste import TasteIn, TasteOptions, TasteOut

router = APIRouter(prefix="/taste", tags=["taste"])


def _out(taste: domain.Taste) -> TasteOut:
    return TasteOut(
        aesthetics=list(taste.aesthetics),
        occasions=list(taste.occasions),
        dress_code=taste.dress_code,
        goal=taste.goal,
        answered=taste.answered,
        lens_order=list(domain.lens_order(taste)),
    )


@router.get("/options", response_model=TasteOptions)
async def read_options() -> TasteOptions:
    """Every answer this service accepts.

    Unauthenticated on purpose: it is a vocabulary, not anybody's data, and
    the sign-up screen that needs it runs before there is a session.
    """
    return TasteOptions()


@router.get("", response_model=TasteOut)
async def read_taste(db: SessionDep, ctx: AuthDep) -> TasteOut:
    """What this person said, and what it implies for their shelves."""
    return _out(await domain.read_taste(db, user_id=ctx.user_id))


@router.put("", response_model=TasteOut)
async def set_taste(payload: TasteIn, db: SessionDep, ctx: AuthDep) -> TasteOut:
    """Record the answers. An empty body is a valid answer: declining."""
    taste = domain.Taste(
        aesthetics=tuple(payload.aesthetics),
        occasions=tuple(payload.occasions),
        dress_code=payload.dress_code,
        goal=payload.goal,
    )
    return _out(await domain.write_taste(db, user_id=ctx.user_id, taste=taste))
