"""The studio: what other people do with the fits you publish.

**Derived, like the inbox, and for the same reason.** Every number here is
a count over tables that already record what happened — saves, reactions,
follows — so the studio cannot disagree with the history it is counting
and there is no second copy to drift. The window is a parameter rather
than a stored report.

**Audience-led, not money-led.** The hero is saves: a save is somebody
planning to wear the thing, which is the one signal a fashion product can
stand behind. Earnings have no row here until money is real.

**Your own taps are not your audience.** Every count excludes the owner,
the same rule the inbox applies: being told that you yourself looked at
something is not reach.

**It measures what you published, not what you kept.** It used to count
taps against the catalogue looks somebody had saved, which made the
numbers a report on other people's clothes. A creator screen is about
your own work, and a published fit is the only thing here that is.

Per-fit counts carry no extra disclosure: the save and reaction totals on
a fit are already on its card for anybody who opens it, so the studio
shows its owner nothing a stranger could not already read — it only
gathers it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow import Follow
from app.models.posts import Post, PostSave
from app.models.profile import PostReaction

#: The windows the range control offers. ``None`` is all time; its chart
#: still draws the last 28 days, because an all-time daily series is an
#: unreadable smear and the totals above it carry the history.
WINDOWS: dict[str, int | None] = {"7d": 7, "28d": 28, "all": None}

#: How many bars the chart draws for the unbounded window.
SERIES_FALLBACK_DAYS = 28


class UnknownWindow(Exception):
    """A window key off the list. The route turns this into a 422."""


@dataclass(frozen=True, slots=True)
class TopFit:
    post_id: uuid.UUID
    #: Distinct people, not events: forty taps by one person is one person.
    people: int
    saves: int


@dataclass(frozen=True, slots=True)
class StudioOverview:
    window: str
    #: Fits this person has published. The body of work the numbers are
    #: about, so the screen can say "across your 11 fits".
    fits: int
    #: Saves by other people, on those fits, in the window. The hero.
    saves: int
    #: Distinct other people who touched any of those fits in the window.
    reach: int
    followers: int
    followers_gained: int
    #: One count per day, oldest first. Saves and reactions by others on
    #: published fits; length is the window (or the fallback for all time).
    series: tuple[int, ...]
    top_fits: tuple[TopFit, ...]


async def overview(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    window: str,
    now: datetime | None = None,
) -> StudioOverview:
    if window not in WINDOWS:
        raise UnknownWindow(window)
    moment = now or datetime.now(UTC)
    days = WINDOWS[window]
    series_days = days or SERIES_FALLBACK_DAYS
    cutoff = None if days is None else moment - timedelta(days=days)

    mine = list(
        await db.scalars(
            sa.select(Post.id).where(
                Post.user_id == user_id,
                Post.state == "published",
                Post.deleted_at.is_(None),
            )
        )
    )

    followers = int(
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(Follow)
            .where(Follow.followee_id == user_id)
        )
        or 0
    )
    gained_where = [Follow.followee_id == user_id]
    if cutoff is not None:
        gained_where.append(Follow.created_at >= cutoff)
    followers_gained = int(
        await db.scalar(
            sa.select(sa.func.count()).select_from(Follow).where(*gained_where)
        )
        or 0
    )

    if not mine:
        return StudioOverview(
            window=window,
            fits=0,
            saves=0,
            reach=0,
            followers=followers,
            followers_gained=followers_gained,
            series=tuple(0 for _ in range(series_days)),
            top_fits=(),
        )

    def others(model: type) -> list:
        """This fit, somebody else, inside the window."""
        where = [model.post_id.in_(mine), model.user_id != user_id]
        if cutoff is not None:
            where.append(model.created_at >= cutoff)
        return where

    saves = int(
        await db.scalar(
            sa.select(sa.func.count()).select_from(PostSave).where(*others(PostSave))
        )
        or 0
    )

    # Distinct *people*, over both kinds at once: somebody who saved a fit
    # and reacted to it is one person reached, and counting the two
    # separately and adding them would say two.
    touched = sa.union(
        sa.select(PostSave.user_id).where(*others(PostSave)),
        sa.select(PostReaction.user_id).where(*others(PostReaction)),
    ).subquery()
    reach = int(
        await db.scalar(
            sa.select(sa.func.count(sa.distinct(touched.c.user_id))).select_from(touched)
        )
        or 0
    )

    # The chart's days, bucketed in SQL and filled with zeroes in Python:
    # a day nobody touched anything is a real day and the bar chart needs
    # its slot, not a gap that shifts every bar after it.
    series_cutoff = moment - timedelta(days=series_days)

    def since(model: type) -> list:
        return [
            model.post_id.in_(mine),
            model.user_id != user_id,
            model.created_at >= series_cutoff,
        ]

    events = sa.union_all(
        sa.select(PostSave.created_at.label("at")).where(*since(PostSave)),
        sa.select(PostReaction.created_at.label("at")).where(*since(PostReaction)),
    ).subquery()
    rows = (
        await db.execute(
            sa.select(
                sa.func.date(events.c.at).label("day"), sa.func.count().label("count")
            )
            .select_from(events)
            .group_by(sa.func.date(events.c.at))
        )
    ).all()
    by_day = {str(row.day): int(row.count) for row in rows}
    series = tuple(
        by_day.get((moment - timedelta(days=offset)).date().isoformat(), 0)
        for offset in range(series_days - 1, -1, -1)
    )

    # Ranked by saves, which is the hero number, then by how many people
    # it reached. A fit nobody saved can still be the one most people
    # reacted to, so reactions are counted into `people` and a fit with
    # only reactions is still eligible.
    #
    # Two queries merged here rather than one grouped union: a save and a
    # reaction by the same person is one person reached but only one save,
    # and a single GROUP BY cannot report both without double-counting.
    saves_per_fit = {
        row.post_id: int(row.saves or 0)
        for row in (
            await db.execute(
                sa.select(
                    PostSave.post_id, sa.func.count().label("saves")
                )
                .where(*others(PostSave))
                .group_by(PostSave.post_id)
            )
        ).all()
    }
    reached = sa.union(
        sa.select(
            PostSave.post_id.label("post_id"), PostSave.user_id.label("user_id")
        ).where(*others(PostSave)),
        sa.select(
            PostReaction.post_id.label("post_id"),
            PostReaction.user_id.label("user_id"),
        ).where(*others(PostReaction)),
    ).subquery()
    people_per_fit = {
        row.post_id: int(row.people or 0)
        for row in (
            await db.execute(
                sa.select(
                    reached.c.post_id,
                    sa.func.count(sa.distinct(reached.c.user_id)).label("people"),
                )
                .select_from(reached)
                .group_by(reached.c.post_id)
            )
        ).all()
    }
    top = sorted(
        people_per_fit,
        key=lambda post_id: (
            -saves_per_fit.get(post_id, 0),
            -people_per_fit[post_id],
            str(post_id),
        ),
    )[:5]

    return StudioOverview(
        window=window,
        fits=len(mine),
        saves=saves,
        reach=reach,
        followers=followers,
        followers_gained=followers_gained,
        series=series,
        top_fits=tuple(
            TopFit(
                post_id=post_id,
                people=people_per_fit[post_id],
                saves=saves_per_fit.get(post_id, 0),
            )
            for post_id in top
        ),
    )


__all__ = [
    "SERIES_FALLBACK_DAYS",
    "StudioOverview",
    "TopFit",
    "UnknownWindow",
    "WINDOWS",
    "overview",
]
