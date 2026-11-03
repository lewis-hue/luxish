"""Loading the graph, and keeping it in memory.

**A query per hop is the implementation that looks right and is
unusable.** A two-hop walk taking four thousand steps would make
sixteen thousand round trips to answer one feed request. The standard
answer is to hold the whole graph in RAM and walk it there, and that
is the answer here too - load the edges once, cache them in the
process, walk the copy.

**The cache has a deadline rather than an invalidation.** Boards
change when somebody pins something, and threading an invalidation
through every write path is how a cache ends up stale in exactly one
code path nobody remembered. A deadline is wrong for at most its own
length and is wrong in the harmless direction: a pin saved a minute
ago is missing from one walk, not forever.

**Freshness is not this cache's job.** New pins reach the feed through
the trending and fresh retrieval sources, which read the database
directly. So a cold-started pin is discoverable immediately even
though the graph has not noticed it yet, which is the behaviour the
exploration slice exists to provide.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.discovery.graph import Graph

logger = logging.getLogger(__name__)

#: How long a loaded graph is used before it is rebuilt.
#:
#: Five minutes: long enough that a burst of feed requests shares one
#: load, short enough that somebody who makes a board sees it affect
#: their recommendations within a coffee.
GRAPH_TTL_SECONDS = 300.0

_cached: Graph | None = None
_loaded_at: float = 0.0


async def load(db: AsyncSession) -> Graph:
    """Every board-to-pin edge, both directions.

    One statement. The edges are the whole table, and a table scan of
    something this shape is cheaper than any clever incremental
    alternative until it stops being - at which point the honest fix
    is a separate service holding the graph, not a subtler query
    here.
    """
    from app.models.moodboard import MoodboardPin

    rows = (
        await db.execute(
            sa.select(MoodboardPin.moodboard_id, MoodboardPin.post_id)
        )
    ).all()

    on: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    holding: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for board_id, post_id in rows:
        on[board_id].append(post_id)
        holding[post_id].append(board_id)

    graph = Graph(
        pins_on={b: tuple(p) for b, p in on.items()},
        boards_with={p: tuple(b) for p, b in holding.items()},
    )
    logger.info(
        "loaded the pin graph",
        extra={"boards": graph.size[0], "pins": graph.size[1], "edges": len(rows)},
    )
    return graph


async def cached_graph(db: AsyncSession, *, now: float | None = None) -> Graph:
    """The graph, loaded at most once per `GRAPH_TTL_SECONDS`."""
    global _cached, _loaded_at
    moment = now if now is not None else time.monotonic()
    if _cached is not None and moment - _loaded_at < GRAPH_TTL_SECONDS:
        return _cached
    _cached = await load(db)
    _loaded_at = moment
    return _cached


def forget() -> None:
    """Drop the cached graph. For tests, and for a seeder that just ran."""
    global _cached, _loaded_at
    _cached = None
    _loaded_at = 0.0


__all__ = ["GRAPH_TTL_SECONDS", "cached_graph", "forget", "load"]
