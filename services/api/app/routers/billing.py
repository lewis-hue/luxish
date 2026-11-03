"""Subscription routes.

Reads are plain. The one write that creates a subscription lives under a
path that says what it is: ``/simulated/subscribe`` exists so the paywall,
the manage screen and the allowance meter can be built and tested before
any store credential does, and it refuses to run outside a development
environment. When Apple and Google billing arrive they get their own
verification endpoints; this one keeps its name forever, so nothing about
its history is ever ambiguous in a log.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep, SettingsDep
from app.domain import billing
from app.schemas.billing import AutoRenewIn, EntitlementsOut, SimulatedSubscribeIn

router = APIRouter(prefix="/billing", tags=["billing"])


def _out(ent: billing.Entitlements) -> EntitlementsOut:
    return EntitlementsOut(
        plan=ent.plan,  # type: ignore[arg-type]
        state=ent.state,  # type: ignore[arg-type]
        store=ent.store,  # type: ignore[arg-type]
        period_end=ent.period_end,
        auto_renew=ent.auto_renew,
        allowance=ent.allowance,
        used=ent.used,
        remaining=ent.remaining,
        resets_at=ent.resets_at,
        simulated=ent.simulated,
    )


@router.get("/entitlements", response_model=EntitlementsOut)
async def read_entitlements(db: SessionDep, ctx: AuthDep) -> EntitlementsOut:
    """The plan, its state, and where the monthly allowance stands.

    Always answers: the free tier is a real plan, so a person who never
    paid still gets a meter that counts against something rather than a
    404 pretending billing does not exist.
    """
    return _out(await billing.entitlements(db, user_id=ctx.user_id))


@router.post(
    "/simulated/subscribe",
    response_model=EntitlementsOut,
    status_code=status.HTTP_201_CREATED,
)
async def simulated_subscribe(
    payload: SimulatedSubscribeIn, db: SessionDep, ctx: AuthDep, settings: SettingsDep
) -> EntitlementsOut:
    """Grant a subscription from the simulated store. Development only.

    Idempotent, and the resulting row carries ``store="simulated"`` so it
    can never be mistaken for revenue.
    """
    return _out(
        await billing.subscribe_simulated(
            db,
            user_id=ctx.user_id,
            plan=payload.plan,
            environment=settings.environment,
        )
    )


@router.post("/auto-renew", response_model=EntitlementsOut)
async def set_auto_renew(
    payload: AutoRenewIn, db: SessionDep, ctx: AuthDep
) -> EntitlementsOut:
    """Cancel or resume. Access always runs to the end of the paid period."""
    return _out(
        await billing.set_auto_renew(
            db, user_id=ctx.user_id, auto_renew=payload.auto_renew
        )
    )
