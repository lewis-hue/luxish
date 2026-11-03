"""Candidate retrieval, heavy scoring, blending. In that order.

    [everything published]
            |
            v
    [ retrieval ]  graph walk . affinity . trending . fresh
            |        a few thousand, from four sources
            v
    [ visibility ]  one gate, applied once, to all of them
            |
            v
    [ seen filter ]  what this person was already shown
            |
            v
    [ scoring ]     one function over every candidate
            |
            v
    [ blending ]    quotas, diversity, exploration
            |
            v
        [ grid ]

**Why stages at all.** `feed.board` is one query that selects
everything published in a fortnight and sorts it in Python. That is
correct and it cannot do any of the things being asked for here: it
has no way to reserve room for something trending, no way to let an
unseen pin in ahead of a popular one, and no notion of why a pin was
chosen - so nothing downstream can reason about the mix. Splitting
retrieval from scoring is what makes "20% of this grid is trending" a
sentence the code can express.

**One visibility gate, applied once, to every source.** This is the
part worth being careful about. Four retrieval paths each doing their
own filtering is four chances to forget one, and the thing being
forgotten is somebody's private fit appearing in a stranger's feed.
So the sources return bare ids and are *not trusted*: `_visible`
re-reads every id through the same predicates `feed.board` uses, and
anything that does not come back is dropped. A source cannot leak
something by failing to filter, because a source does not filter.

**Where this matches the published designs this follows and where it does
not** is written down in `README.md` beside this file, because a
system that claims the architecture of something far larger should
say plainly which parts it actually has.
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.discovery import trending as trending_source
from app.domain.discovery.blend import Candidate, blend
from app.domain.discovery.graph import walk
from app.domain.discovery.seen import SeenStore, unseen
from app.domain.discovery.store import cached_graph

logger = logging.getLogger(__name__)

#: How many candidates each source may contribute before scoring.
#:
#: The funnel's first narrowing. Generous, because scoring is cheap
#: here and a source that returns too few cannot be rescued later.
PER_SOURCE = 400

#: How far back a signal still says something about present taste.
TASTE_DAYS = 60

#: A pin with fewer than this many signals counts as unproven, and is
#: eligible for the exploration slice.
#:
#: Three, matching the trending floor: below it there is not enough
#: evidence to say a pin is good or bad, which is precisely the
#: condition exploration exists to resolve.
UNPROVEN_BELOW = 3

#: How recently a pin must have been posted to count as fresh.
FRESH_DAYS = 21

#: Below this share of a full grid, the seen-filter is relaxed.
#:
#: **An empty Discover tab is the worst thing this pipeline can
#: produce**, and the seen-filter is the only stage that can cause
#: one: it subtracts and never adds, so a person who has been shown
#: everything gets nothing. That is not hypothetical - it happened on
#: the dev stack within an afternoon, because the corpus is four
#: hundred pins and a few refreshes exhaust it.
#:
#: Repetition is the correct trade against emptiness. A grid of pins
#: somebody saw yesterday is a worse grid; a blank screen is a broken
#: app.
ENOUGH_OF_A_GRID = 0.5


@dataclass(frozen=True)
class Explained:
    """A pin and why it is here. The `source` is what makes the mix
    inspectable - without it, nobody can answer "why am I seeing
    this", including us."""

    post_id: uuid.UUID
    source: str
    score: float


async def _query_pins(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime
) -> tuple[list[uuid.UUID], dict[uuid.UUID, float]]:
    """What this person has shown interest in, and how strongly.

    Saves outrank reactions and recent outranks old, which is the
    same ordering `app.domain.ranking` already states. The weights
    bias where the walk starts, so a fit somebody filed yesterday
    pulls harder than one they tapped a month ago.
    """
    from app.domain.ranking import WEIGHTS, decay
    from app.models.posts import PostSave
    from app.models.profile import PostReaction

    since = now - timedelta(days=TASTE_DAYS)
    weights: dict[uuid.UUID, float] = {}
    for model, key in ((PostSave, "save"), (PostReaction, "reaction")):
        rows = (
            await db.execute(
                sa.select(model.post_id, model.created_at).where(
                    model.user_id == user_id, model.created_at >= since
                )
            )
        ).all()
        for post_id, at in rows:
            moment = at if at.tzinfo else at.replace(tzinfo=UTC)
            weights[post_id] = weights.get(post_id, 0.0) + WEIGHTS[key] * decay(
                moment, now
            )
    return list(weights), weights


async def _visible(
    db: AsyncSession, *, user_id: uuid.UUID, ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[uuid.UUID, datetime]]:
    """The subset this person may see, with author and publish time.

    **The one gate.** Every retrieval source funnels through here, so
    a source cannot leak a private fit by forgetting to filter: it
    never filters, and anything it names that does not survive this
    read is simply absent from the result.

    The clauses are `feed`'s own, imported rather than restated. A
    second copy of a visibility rule is a second thing to keep in
    step with the first, and the cost of them drifting is the kind of
    bug nobody notices until it is in somebody's screenshot.
    """
    if not ids:
        return {}
    from app.domain.feed import visible_author
    from app.models.posts import Post, shown_to_strangers
    from app.models.user import User

    rows = (
        await db.execute(
            sa.select(Post.id, Post.user_id, Post.published_at, Post.created_at)
            .join(User, User.id == Post.user_id)
            .where(
                Post.id.in_(ids),
                shown_to_strangers(),
                visible_author(user_id),
                User.deleted_at.is_(None),
            )
        )
    ).all()
    return {
        post_id: (author_id, published or created)
        for post_id, author_id, published, created in rows
    }


async def _affinity(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime, limit: int
) -> dict[uuid.UUID, float]:
    """Pins carrying tags this person keeps engaging with.

    The fallback that covers what the walk cannot: somebody with no
    boards and two saves has no graph neighbourhood, and would
    otherwise get a feed made entirely of trending and random.
    """
    from app.models.posts import Post, PostSave
    from app.models.profile import PostTag

    since = now - timedelta(days=TASTE_DAYS)
    liked = (
        await db.execute(
            sa.select(PostTag.tag, sa.func.count())
            .join(PostSave, PostSave.post_id == PostTag.post_id)
            .where(PostSave.user_id == user_id, PostSave.created_at >= since)
            .group_by(PostTag.tag)
            .order_by(sa.func.count().desc())
            .limit(12)
        )
    ).all()
    if not liked:
        return {}
    strength = {tag: float(count) for tag, count in liked}

    rows = (
        await db.execute(
            sa.select(PostTag.post_id, PostTag.tag)
            .join(Post, Post.id == PostTag.post_id)
            .where(
                PostTag.tag.in_(list(strength)),
                Post.user_id != user_id,
                Post.deleted_at.is_(None),
                Post.state == "published",
            )
            .limit(limit * 4)
        )
    ).all()
    out: dict[uuid.UUID, float] = {}
    for post_id, tag in rows:
        out[post_id] = out.get(post_id, 0.0) + strength.get(tag, 0.0)
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:limit])


async def _looks_like(
    db: AsyncSession, *, user_id: uuid.UUID, queries: list[uuid.UUID], limit: int
) -> dict[uuid.UUID, float]:
    """Pins whose photographs resemble the ones this person keeps.

    **The signal that works on a pin nobody has touched.** The walk
    needs board placements and affinity needs tags; a photograph
    posted ten minutes ago with a careless caption has neither, and
    is exactly the pin that gets mis-recommended. This reads the
    picture instead.

    A scan over a few hundred unit vectors, not an index. At this
    corpus size that is microseconds of arithmetic, and ADR-004
    scopes pgvector to "where measured retrieval needs justify it" -
    the trigger is a scan that stops being fast enough, not a table
    that exists.
    """
    from app.domain.discovery import subject as subjects
    from app.models.post_vision import PostVisionRow

    if not queries:
        return {}

    liked = (
        await db.scalars(
            sa.select(PostVisionRow).where(PostVisionRow.post_id.in_(queries))
        )
    ).all()
    if not liked:
        return {}

    everything = (
        await db.scalars(sa.select(PostVisionRow).limit(limit * 6))
    ).all()
    candidates = {
        row.post_id: (row.subject, list(row.vector or []))
        for row in everything
        if row.post_id not in set(queries)
    }
    presents = {
        row.post_id: (row.presentation or "unspecified") for row in everything
    }

    # Scored against each thing they liked, keeping the best match
    # rather than the sum: a pin that strongly resembles one saved
    # photograph is a better recommendation than one that vaguely
    # resembles ten.
    #
    # **Plus a lean toward the same presentation.** Opening a menswear
    # fit and being shown a rail of dresses is not a weak answer, it is
    # the wrong one. A lean rather than a filter, so an androgynous
    # piece that genuinely suits still gets through and a clearly
    # better visual match still wins - see `subject.leans_together`,
    # which scores nothing when either side is `unspecified`, because
    # not knowing is not a reason to push something down.
    best: dict[uuid.UUID, float] = {}
    for seed in liked:
        seen_as = seed.presentation or "unspecified"
        for post_id, score in subjects.nearest(
            viewing_subject=seed.subject,
            viewing_vector=list(seed.vector or []),
            candidates={str(k): v for k, v in candidates.items()},
            limit=limit,
        ):
            key = uuid.UUID(post_id)
            leaned = score + subjects.leans_together(
                seen_as, presents.get(key, "unspecified")
            )
            if leaned > best.get(key, 0.0):
                best[key] = leaned
    return best


async def _unproven(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime, limit: int
) -> list[uuid.UUID]:
    """Recent pins almost nobody has touched. The exploration pool.

    **Posted recently and barely engaged with**, both. Without the
    recency clause this becomes a graveyard of everything the feed
    has ever declined to show, and exploration stops being about new
    content and becomes about resurfacing failures.
    """
    from app.models.posts import Post, PostSave
    from app.models.profile import PostReaction

    since = now - timedelta(days=FRESH_DAYS)
    reactions = (
        sa.select(PostReaction.post_id, sa.func.count().label("n"))
        .group_by(PostReaction.post_id)
        .subquery()
    )
    saves = (
        sa.select(PostSave.post_id, sa.func.count().label("n"))
        .group_by(PostSave.post_id)
        .subquery()
    )
    rows = (
        await db.execute(
            sa.select(Post.id)
            .outerjoin(reactions, reactions.c.post_id == Post.id)
            .outerjoin(saves, saves.c.post_id == Post.id)
            .where(
                Post.user_id != user_id,
                Post.deleted_at.is_(None),
                Post.state == "published",
                sa.func.coalesce(Post.published_at, Post.created_at) >= since,
                (
                    sa.func.coalesce(reactions.c.n, 0)
                    + sa.func.coalesce(saves.c.n, 0)
                )
                < UNPROVEN_BELOW,
            )
            .limit(limit)
        )
    ).all()
    return [row[0] for row in rows]


async def discover(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    size: int = 30,
    seen_store: SeenStore | None = None,
    rng: random.Random | None = None,
    now: datetime | None = None,
    record: bool = True,
) -> list[Explained]:
    """One grid for one person. The whole pipeline.

    `record` writes the result to the seen-filter so the next refresh
    returns something else. Off for a dry run, because an inspection
    that marks everything as shown changes what it was inspecting.
    """
    chance = rng or random.Random()
    moment = now or datetime.now(UTC)

    # ---- retrieval ------------------------------------------------ #
    queries, weights = await _query_pins(db, user_id=user_id, now=moment)

    graph = await cached_graph(db)
    from_graph = (
        walk(graph, queries=queries, weights=weights, rng=chance)
        if queries
        else {}
    )
    from_graph = dict(
        sorted(from_graph.items(), key=lambda kv: -kv[1])[:PER_SOURCE]
    )
    from_affinity = await _affinity(
        db, user_id=user_id, now=moment, limit=PER_SOURCE
    )
    from_similar = await _looks_like(
        db, user_id=user_id, queries=queries, limit=PER_SOURCE
    )
    rising = await trending_source.rising(db, now=moment, limit=PER_SOURCE)
    from_trending = {t.post_id: t.lift for t in rising}
    fresh = await _unproven(db, user_id=user_id, now=moment, limit=PER_SOURCE)

    # ---- one visibility gate, for all of them --------------------- #
    everything = (
        set(from_graph)
        | set(from_similar)
        | set(from_affinity)
        | set(from_trending)
        | set(fresh)
    )
    everything.discard(None)
    allowed = await _visible(db, user_id=user_id, ids=everything)

    # Their own fits are not discoveries, and the two "do not show me
    # this" controls are honoured here rather than per source.
    from app.domain.feed import hidden_posts
    from app.domain.moderation import hidden_either_way

    blocked = await hidden_either_way(db, user_id=user_id)
    skipped = await hidden_posts(db, user_id=user_id)

    def permitted(post_id: uuid.UUID) -> bool:
        seen_row = allowed.get(post_id)
        if seen_row is None:
            return False
        author, _ = seen_row
        return author != user_id and author not in blocked and post_id not in skipped

    # ---- the seen filter ------------------------------------------ #
    #
    # **Relaxed rather than obeyed when it would empty the grid.**
    # This stage only ever subtracts, so on a small corpus a few
    # refreshes exhaust it and the next request returns nothing at
    # all. The filter is a preference for novelty, not a correctness
    # rule, so when honouring it costs the whole page it gives way:
    # a repeated pin is a worse grid, an empty one is a broken app.
    #
    # Measured against what is *permitted*, not against what was
    # retrieved, because the visibility gate is a correctness rule
    # and never gives way.
    already = await seen_store.seen(user_id) if seen_store else set()
    allowed_count = sum(1 for post_id in allowed if permitted(post_id))
    if allowed_count and allowed_count - len(
        {p for p in already if permitted(p)}
    ) < size * ENOUGH_OF_A_GRID:
        logger.info(
            "relaxing the seen-filter: too little left to fill a grid",
            extra={"user": str(user_id), "permitted": allowed_count},
        )
        already = set()

    def survivors(ids: list[uuid.UUID]) -> list[uuid.UUID]:
        return [p for p in unseen(ids, already) if permitted(p)]

    # ---- scoring -------------------------------------------------- #
    # Retrieval scores are not comparable across sources - a walk
    # score is a visit count and a trend score is a ratio - so each
    # is normalised to its own best before anything is blended.
    # Without this the source with the largest raw numbers wins every
    # tie and the quotas are the only thing still doing any work.
    def normalise(scores: dict[uuid.UUID, float]) -> dict[uuid.UUID, float]:
        if not scores:
            return {}
        top = max(scores.values()) or 1.0
        return {k: v / top for k, v in scores.items()}

    pool: list[Candidate] = []
    for source, scored in (
        ("graph", normalise(from_graph)),
        ("similar", normalise(from_similar)),
        ("affinity", normalise(from_affinity)),
        ("trending", normalise(from_trending)),
    ):
        for post_id in survivors(list(scored)):
            author, _ = allowed[post_id]
            pool.append(
                Candidate(
                    post_id=post_id,
                    source=source,
                    score=scored[post_id],
                    author_id=author,
                )
            )
    for post_id in survivors(fresh):
        author, _ = allowed[post_id]
        pool.append(
            Candidate(post_id=post_id, source="fresh", score=0.0, author_id=author)
        )

    # ---- blending ------------------------------------------------- #
    grid = blend(pool, size=size, rng=chance)

    if record and seen_store is not None:
        await seen_store.note(user_id, [c.post_id for c in grid])

    logger.info(
        "built a discovery grid",
        extra={
            "user": str(user_id),
            "size": len(grid),
            "mix": {
                name: sum(1 for c in grid if c.source == name)
                for name in {c.source for c in grid}
            },
        },
    )
    return [Explained(c.post_id, c.source, c.score) for c in grid]


__all__ = [
    "FRESH_DAYS",
    "PER_SOURCE",
    "TASTE_DAYS",
    "UNPROVEN_BELOW",
    "Explained",
    "discover",
]
