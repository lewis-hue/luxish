"""Taste profile routes.

One endpoint, read-only. The profile is derived from three things that are
already stored — stated answers, garments, interactions — so there is nothing
to write here and nothing that can drift out of step with them.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthDep, SessionDep
from app.domain import inspiration as inspiration_domain
from app.domain import profile as domain
from app.schemas.profile import InspirationOut, ProfileOut

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/taste", response_model=ProfileOut)
async def read_taste_profile(db: SessionDep, ctx: AuthDep) -> ProfileOut:
    """Which collections to lead each shelf with, for this person.

    Three queries and no model call, which is what makes it safe to ask for
    on every Discover open.
    """
    built = await domain.build_profile(db, user_id=ctx.user_id)
    return ProfileOut(
        formula=list(domain.formula_focus(built)),
        aesthetics=list(domain.aesthetic_focus(built)),
        wardrobe_size=built.wardrobe_size,
        gaps=list(built.gaps),
        answered=built.stated.answered,
    )


@router.get("/inspiration", response_model=InspirationOut)
async def read_inspiration(db: SessionDep, ctx: AuthDep) -> InspirationOut:
    """What to put on "how to wear what you own" for this person.

    A set generated for their cohort when one is current; otherwise a ranking
    from their own wardrobe, honestly marked as not being a group's. Never an
    empty shelf, and never the general order presented as theirs.
    """
    result = await inspiration_domain.for_user(db, user_id=ctx.user_id)
    return InspirationOut(
        collections=list(result.collections),
        rationale=result.rationale,
        personalised=result.personalised,
        cohort_size=result.cohort_size,
    )
