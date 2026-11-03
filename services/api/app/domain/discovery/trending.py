"""What is moving, as opposed to what is big.

**Volume and velocity are different questions and this app only ever
asked the first one.** `feed.score` adds up reactions and saves, so
the fit at the top of Discover is the one that has accumulated the
most attention since it was posted - which is a leaderboard, not a
trend. A photograph from five weeks ago with four hundred saves beats
one from this morning with thirty, for ever, and nothing new can ever
reach the top because the metric rewards having been around.

Trending is the derivative: attention *now* against that pin's own
recent baseline.

    velocity = weighted signals in the last DAY
    baseline = weighted signals in the BASELINE window before it,
               per day
    lift     = velocity / (baseline + floor)

The floor matters more than it looks. Without it a pin going from
zero to three saves has infinite lift and wins outright, so the first
three taps on anything would make it the most trending thing on the
platform. With it, a pin needs real movement to clear pins that are
already busy.

**Weighted by the same constants as everywhere else.** `app.domain.
ranking` already decides what a save is worth against a reaction, and
a second opinion about that here would show up as two screens
disagreeing about the same taps - which is the exact failure that
module's docstring was written about.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ranking import WEIGHTS

#: The window that counts as "now".
DAY = timedelta(hours=24)

#: What "now" is measured against. A week, so a pin's own weekday
#: rhythm is averaged out rather than being read as a trend.
BASELINE = timedelta(days=7)

#: Added to the baseline so a pin coming off zero cannot divide by it.
#:
#: Set to roughly one save a day: a pin has to be moving faster than
#: that before lift says anything, which is what stops the first three
#: taps on a brand-new pin from making it the top of the platform.
BASELINE_FLOOR = 8.0

#: A pin needs this many distinct people in the window before it can
#: trend at all. Three, matching `ranking.MIN_DISTINCT_USERS`: the
#: smallest number that cannot be one person with a lot of enthusiasm.
MIN_PEOPLE = 3


@dataclass(frozen=True)
class Trend:
    post_id: uuid.UUID
    velocity: float
    baseline: float
    people: int

    @property
    def lift(self) -> float:
        return self.velocity / (self.baseline + BASELINE_FLOOR)


async def rising(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 200,
    scope_tag: str | None = None,
) -> list[Trend]:
    """Pins whose attention is accelerating, strongest lift first.

    `scope_tag` narrows to one vertical. Reserving trending
    slots per demographic rather than globally for the same reason:
    the single global list is whatever the largest population likes,
    so a smaller vertical never appears in it. With decor, accessories
    and beauty alongside clothes, a global-only trend list would be
    clothes every time.
    """
    from app.models.posts import Post, PostSave
    from app.models.profile import PostReaction, PostTag

    moment = now or datetime.now(UTC)
    recent_from = moment - DAY
    baseline_from = moment - DAY - BASELINE

    # One statement per signal, unioned, rather than a join across
    # both: a post with reactions and saves would otherwise multiply
    # the two together and report a velocity that never happened.
    parts = []
    for model, weight_key in ((PostReaction, "reaction"), (PostSave, "save")):
        parts.append(
            sa.select(
                model.post_id.label("post_id"),
                model.user_id.label("user_id"),
                model.created_at.label("at"),
                sa.literal(WEIGHTS[weight_key]).label("weight"),
            )
        )
    signals = sa.union_all(*parts).subquery()

    query = (
        sa.select(
            signals.c.post_id,
            sa.func.sum(
                sa.case((signals.c.at >= recent_from, signals.c.weight), else_=0.0)
            ).label("velocity"),
            sa.func.sum(
                sa.case(
                    (
                        sa.and_(
                            signals.c.at >= baseline_from,
                            signals.c.at < recent_from,
                        ),
                        signals.c.weight,
                    ),
                    else_=0.0,
                )
            ).label("earlier"),
            sa.func.count(sa.distinct(signals.c.user_id))
            .filter(signals.c.at >= recent_from)
            .label("people"),
        )
        .join(Post, Post.id == signals.c.post_id)
        .where(
            signals.c.at >= baseline_from,
            Post.deleted_at.is_(None),
            Post.state == "published",
        )
        .group_by(signals.c.post_id)
    )

    if scope_tag:
        query = query.where(
            sa.exists().where(
                sa.and_(
                    PostTag.post_id == signals.c.post_id,
                    PostTag.tag == scope_tag,
                )
            )
        )

    found: list[Trend] = []
    for post_id, velocity, earlier, people in (await db.execute(query)).all():
        if (people or 0) < MIN_PEOPLE:
            continue
        if not velocity:
            continue
        found.append(
            Trend(
                post_id=post_id,
                velocity=float(velocity),
                # Per day, so it is comparable with a one-day velocity.
                baseline=float(earlier or 0.0) / BASELINE.days,
                people=int(people or 0),
            )
        )

    found.sort(key=lambda t: (-t.lift, str(t.post_id)))
    return found[:limit]


__all__ = [
    "BASELINE",
    "BASELINE_FLOOR",
    "DAY",
    "MIN_PEOPLE",
    "Trend",
    "rising",
]
