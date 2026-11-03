""""How to wear what you own", generated per cohort and refreshed twice a week.

Three properties, and each is the answer to a way this feature goes wrong.

**Generated per cohort, so the bill does not grow with sign-ups.** One set
serves everybody whose wardrobe is the same kind of wardrobe. See
:mod:`app.domain.cohort` for how a group is formed and why it has a floor.

**Conditioned on the cohort key alone.** Never on a member's garments, never
on their name, never on anything one of them wrote. The key is category
counts and a stated dress code, so there is nothing in the input that could
carry one person's wardrobe into something another person reads. This is the
rule that makes sharing acceptable at all, and it is checked by a test rather
than left to the next person's care.

**A set that is not ready yet falls back to the general shelf, labelled.** A
spinner twice a week is not a refresh strategy, and showing the general
ordering while calling it "yours" is the dishonesty this is most tempted
into. :class:`Inspiration` carries `personalised`, and a caller that ignores
it is making a claim the data does not support.

Nothing here calls a model yet. The selection is from the bundled collection
taxonomy, ranked by what a cohort owns, which is already useful and costs
nothing; the structure — cohort key in, validity window, one row serving many
— is what a generated set would slot into unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cohort import (
    LADDER,
    MIN_COHORT_SIZE,
    Signature,
    key_at,
    resolve,
)
from app.domain.profile import FORMULA_EVIDENCE, build_profile, formula_focus
from app.models.cohort_inspiration import CohortInspiration
from app.models.user_cohort import UserCohort

#: How long a generated set stays current.
#:
#: Three and a half days, so two sets cover a week and the shelf somebody
#: opens on Thursday is not the one they saw on Monday. The schedule in
#: `queue/celery_app.py` runs on Monday and Thursday to match; if either
#: changes the other has to, or there will be days with no current set.
WINDOW = timedelta(days=3, hours=12)

#: How many collections a set carries.
#:
#: Six: enough that a shelf scrolls, few enough that it is a selection rather
#: than the whole taxonomy reordered.
SET_SIZE = 6


@dataclass(frozen=True, slots=True)
class Inspiration:
    """What to show, and an honest account of where it came from."""

    collections: tuple[str, ...]
    #: Why this set. Shown, so the shelf explains itself rather than looking
    #: like a reshuffle.
    rationale: str
    #: False when this is the general ordering rather than one made for a
    #: group this person is actually in. A caller that ignores this is
    #: claiming something the data does not support.
    personalised: bool
    #: How many people the set was made for, so the claim can show its basis.
    cohort_size: int
    valid_until: datetime | None = None


#: The ordering shown when nothing better is available.
#:
#: The bundled taxonomy as authored. Returned rather than an empty shelf: a
#: section that disappears while a schedule catches up is worse than a general
#: one that says it is general.
GENERAL = tuple(FORMULA_EVIDENCE)


def _rationale(collections: tuple[str, ...], members: int) -> str:
    lead = collections[0] if collections else "your wardrobe"
    return f"Built for {members} people with wardrobes like yours, starting with {lead}."


async def current(
    session: AsyncSession, *, cohort_key: str, now: datetime
) -> CohortInspiration | None:
    """The set valid for this cohort right now, if one has been made."""
    return await session.scalar(
        sa.select(CohortInspiration)
        .where(
            CohortInspiration.cohort_key == cohort_key,
            CohortInspiration.valid_from <= now,
            CohortInspiration.valid_until > now,
        )
        .order_by(CohortInspiration.valid_from.desc())
    )


async def for_user(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> Inspiration:
    """What to put on this person's "how to wear what you own" shelf.

    Falls through honestly: a current cohort set if there is one, otherwise
    the general ordering marked as general. Never an empty shelf, and never
    the general ordering presented as somebody's own.
    """
    moment = now or datetime.now(UTC)
    cohort = await resolve(session, user_id=user_id)

    set_ = await current(session, cohort_key=cohort.key, now=moment)
    if set_ is not None and set_.collections and not cohort.general:
        return Inspiration(
            collections=tuple(set_.collections),
            rationale=set_.rationale or _rationale(tuple(set_.collections), cohort.members),
            personalised=True,
            cohort_size=cohort.members,
            valid_until=set_.valid_until,
        )

    # Nothing generated for this cohort yet, or the cohort is everybody. Rank
    # from this person's own wardrobe, which costs three queries and is still
    # better than the authored order — but say plainly that it is not a set
    # made for a group.
    profile = await build_profile(session, user_id=user_id, now=moment)
    ranked = formula_focus(profile, limit=SET_SIZE)
    return Inspiration(
        collections=ranked or GENERAL[:SET_SIZE],
        rationale=(
            "From the pieces you have photographed."
            if profile.wardrobe_size
            else "A general selection, until you photograph some clothes."
        ),
        personalised=False,
        cohort_size=cohort.members,
    )


async def generate_for_cohort(
    session: AsyncSession,
    *,
    cohort_key: str,
    owns: tuple[str, ...],
    members: int,
    now: datetime | None = None,
) -> CohortInspiration:
    """Write this window's set for one cohort key.

    **Conditioned on the key alone.** `owns` is the shared part of a cohort's
    signature — which collections that *kind* of wardrobe has — and `members`
    is a count. No member's garments, names or ids reach this function, so
    there is nothing here that could carry one person's wardrobe into
    something another person reads.
    """
    moment = now or datetime.now(UTC)

    # What this kind of wardrobe owns leads; the rest of the taxonomy follows
    # in its authored order, so a set is a reordering rather than a
    # truncation and no collection is ever unreachable to anybody.
    collections = (*owns, *(name for name in GENERAL if name not in owns))[:SET_SIZE]

    existing = await session.scalar(
        sa.select(CohortInspiration).where(
            CohortInspiration.cohort_key == cohort_key,
            CohortInspiration.valid_from == moment,
        )
    )
    if existing is None:
        existing = CohortInspiration(
            cohort_key=cohort_key,
            collections=list(collections),
            rationale=_rationale(collections, members),
            valid_from=moment,
            valid_until=moment + WINDOW,
        )
        session.add(existing)
    else:
        existing.collections = list(collections)
        existing.rationale = _rationale(collections, members)
        existing.valid_until = moment + WINDOW
    await session.commit()
    await session.refresh(existing)
    return existing


async def refresh_all(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Generate this window's set for every group that is actually a group.

    **Walks the whole widening ladder, not just the most specific rung.** A
    cohort of two people whose widened group has five is served by the
    widened set; generating only for exact keys would mean widening changed
    nothing but the number `resolve` reports, and everybody in a small exact
    group would fall through to the general shelf despite a real group
    existing one rung up.

    Groups under the floor are skipped rather than generated for: a set made
    for one person is the per-user bill this mechanism exists to avoid, and
    it would be labelled as a group's while being nobody's but theirs.

    The bottom rung — everybody — is deliberately not generated. A set for
    `everyone` is the general shelf, and `for_user` already serves that
    honestly from the viewer's own wardrobe rather than pretending a group
    made it.
    """
    moment = now or datetime.now(UTC)
    made = 0

    for level, parts in enumerate(LADDER):
        if not parts:
            continue  # everybody: the general shelf, not a generated set

        columns = []
        if "owns" in parts:
            columns.append(UserCohort.owns_key)
        if "dress_code" in parts:
            columns.append(UserCohort.dress_code)
        if "size" in parts:
            columns.append(UserCohort.size_band)

        rows = (
            await session.execute(
                sa.select(*columns, sa.func.count())
                .group_by(*columns)
                .having(sa.func.count() >= MIN_COHORT_SIZE)
            )
        ).all()

        for row in rows:
            *values, count = row
            signature = Signature(
                owns=tuple(values[0].split("+")) if values[0] != "any" else (),
                dress_code=values[1] if "dress_code" in parts else "unspecified",
                size=values[-1] if "size" in parts else "none",
            )
            await generate_for_cohort(
                session,
                cohort_key=key_at(signature, level),
                owns=signature.owns,
                members=int(count),
                now=moment,
            )
            made += 1

    return made


__all__ = [
    "GENERAL",
    "SET_SIZE",
    "WINDOW",
    "Inspiration",
    "current",
    "for_user",
    "generate_for_cohort",
    "refresh_all",
]
