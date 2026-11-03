"""What a plan entitles somebody to, and the simulated store that grants it.

**Capability labels, per the house rule.** The subscription record and the
entitlement read are ``implemented``. The purchase path is ``simulated``: it
exists so every screen above it can be built and tested end to end, it
refuses to run anywhere except a development environment, and everything it
writes is marked ``store="simulated"``. Apple and Google billing are
``blocked`` on store accounts (ADR-011); enforcement of the stylist
allowance is ``planned`` and deliberately not here, so turning a meter on
cannot silently turn a working feature off.

**The allowance is derived, not stored.** How many stylist runs this month
is a count over :class:`StylistRun`, the table that already records every
run, against the plan's monthly grant. A stored counter would be a second
copy of the truth that a retried request could double-spend; a count cannot
disagree with the history it is counting. The window is the calendar month,
which is the one period a person can hold in their head.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, CapabilityUnavailable
from app.models.billing import PLAN_IDS, Subscription
from app.models.stylist import StylistRun

#: What each plan grants, per calendar month. The free tier is a real plan
#: rather than an absence, so the meter can always say what it is counting
#: against. Numbers are product decisions; the shape is the contract.
PLAN_ALLOWANCES: dict[str, int] = {
    "free": 12,
    "plus": 60,
}

#: How long one simulated billing period runs. Thirty days, renewed lazily:
#: nothing schedules a job for a store that moves no money.
PERIOD = timedelta(days=30)


class NoSuchPlan(ApiError):
    status_code = 422
    code = "no_such_plan"
    default_message = "That is not a plan this service offers."


@dataclass(frozen=True, slots=True)
class Entitlements:
    """Everything the paywall, the manage screen and the meter need."""

    plan: str
    #: ``free`` | ``active`` | ``ending`` — ending is active with renewal
    #: switched off, which is its own state on every manage screen that has
    #: ever been designed, because "expires on" and "renews on" are
    #: different sentences.
    state: str
    store: str | None
    #: When the current period rolls over, or None on the free plan.
    period_end: datetime | None
    auto_renew: bool
    allowance: int
    used: int
    remaining: int
    resets_at: datetime
    #: True whenever the subscription came from the simulated store, so no
    #: client can render a fixture as a live billing relationship.
    simulated: bool


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(now: datetime) -> datetime:
    if now.month == 12:
        return now.replace(
            year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    return now.replace(
        month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
    )


async def _subscription(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime
) -> Subscription | None:
    """The user's live subscription, with lazy expiry and renewal.

    The simulated store has no webhooks, so period rollover happens on
    read: an auto-renewing subscription whose period lapsed is rolled
    forward, and a non-renewing one past its period is marked expired.
    Both are committed immediately so two readers agree.
    """
    row = await db.scalar(
        sa.select(Subscription).where(
            Subscription.user_id == user_id, Subscription.state == "active"
        )
    )
    if row is None:
        return None

    changed = False
    end = row.current_period_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= now:
        if row.auto_renew:
            while end <= now:
                end = end + PERIOD
            row.current_period_start = end - PERIOD
            row.current_period_end = end
            changed = True
        else:
            row.state = "expired"
            changed = True
    if changed:
        await db.commit()
    return row if row.state == "active" else None


async def entitlements(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> Entitlements:
    moment = now or datetime.now(UTC)
    sub = await _subscription(db, user_id=user_id, now=moment)

    plan = sub.plan if sub is not None else "free"
    allowance = PLAN_ALLOWANCES[plan]

    used = (
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(StylistRun)
            .where(
                StylistRun.user_id == user_id,
                StylistRun.created_at >= _month_start(moment),
            )
        )
        or 0
    )

    if sub is None:
        state = "free"
    elif sub.auto_renew:
        state = "active"
    else:
        state = "ending"

    period_end = None
    if sub is not None:
        period_end = sub.current_period_end
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=UTC)

    return Entitlements(
        plan=plan,
        state=state,
        store=sub.store if sub is not None else None,
        period_end=period_end,
        auto_renew=sub.auto_renew if sub is not None else False,
        allowance=allowance,
        used=int(used),
        remaining=max(0, allowance - int(used)),
        resets_at=_next_month(moment),
        simulated=sub is not None and sub.store == "simulated",
    )


async def subscribe_simulated(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    plan: str,
    environment: str,
    now: datetime | None = None,
) -> Entitlements:
    """Grant a subscription from the simulated store.

    **Development environments only, enforced here rather than documented.**
    In staging or production this refuses loudly: a simulated grant beside
    real customers would be indistinguishable from revenue in every query
    that forgot to filter on ``store``.

    Idempotent: subscribing while already subscribed returns the standing
    subscription rather than stacking a second one.
    """
    if environment not in ("local", "test"):
        raise CapabilityUnavailable(
            "The simulated store only exists in development builds. "
            "Real billing is blocked on store accounts (ADR-011)."
        )
    if plan not in PLAN_IDS:
        raise NoSuchPlan(f"{plan!r} is not a plan.", detail={"allowed": list(PLAN_IDS)})

    moment = now or datetime.now(UTC)
    existing = await _subscription(db, user_id=user_id, now=moment)
    if existing is None:
        db.add(
            Subscription(
                user_id=user_id,
                plan=plan,
                state="active",
                store="simulated",
                current_period_start=moment,
                current_period_end=moment + PERIOD,
                auto_renew=True,
            )
        )
        await db.commit()
    elif not existing.auto_renew:
        # Subscribing again while ending is the resume gesture.
        existing.auto_renew = True
        existing.canceled_at = None
        await db.commit()

    return await entitlements(db, user_id=user_id, now=moment)


async def set_auto_renew(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    auto_renew: bool,
    now: datetime | None = None,
) -> Entitlements:
    """Cancel or resume. Access always runs to the end of the paid period.

    Cancelling never claws anything back: the state becomes ``ending`` and
    the period plays out, which is what both stores do and what every
    subscriber expects. Resuming before the period lapses restores
    ``active`` with nothing lost. A free user asking to cancel is a no-op
    rather than an error: the state they want is the state they have.
    """
    moment = now or datetime.now(UTC)
    sub = await _subscription(db, user_id=user_id, now=moment)
    if sub is not None and sub.auto_renew != auto_renew:
        sub.auto_renew = auto_renew
        sub.canceled_at = None if auto_renew else moment
        await db.commit()
    return await entitlements(db, user_id=user_id, now=moment)


__all__ = [
    "PERIOD",
    "PLAN_ALLOWANCES",
    "Entitlements",
    "NoSuchPlan",
    "entitlements",
    "set_auto_renew",
    "subscribe_simulated",
]
