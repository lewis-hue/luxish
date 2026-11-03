"""The bipartite graph, and the random walk over it.

**Two pins are related because a person put them on the same board.**
That is the whole idea: the signal is not that
two photographs look alike, it is that somebody who was curating a
collection decided these two belonged in it. A model guessing at
similarity has no access to that judgement; a walk over the graph of
boards is reading it directly.

The graph is bipartite - pins on one side, boards on the other - and
the walk alternates:

    person -> their pins -> boards holding those pins -> other pins

**The multi-hit booster is the part that matters.** A naive walk
returns whatever is on the biggest board, because a board with two
hundred pins absorbs the walk. The answer here is to
count visits *per starting pin* and combine them as

    score(p) = ( sum over q of sqrt(visits_q(p)) ) ** 2

A pin reached ten times from one starting point scores 10. A pin
reached once from each of ten starting points scores 100. That is the
correct preference: the second pin is related to the person's taste as
a whole, the first is related to one thing they saved.

**What this is not.** A production deployment would hold
billions of edges in RAM across a cluster. This is a pure function
over an adjacency dict that an application process builds and caches.
The algorithm is the same shape and the asymptotics are the same; the
scale is four orders of magnitude apart, and pretending otherwise
would be the kind of claim this repository does not make about
itself. See `app/domain/discovery/README.md` for which pieces of
Pixie (Eksombatchai et al. 2018) this matches and which it does not.
"""

from __future__ import annotations

import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

#: How many steps a single walk takes before giving up.
#:
#: Each step is two hops (pin to board, board to pin). A few thousand
#: steps over a graph this size visits a good fraction of what is
#: reachable; the early stop below usually ends it sooner.
MAX_STEPS = 4000

#: Stop once this many distinct pins have been seen at least
#: `ENOUGH_VISITS` times.
#:
#: This is early stopping and it is what makes the walk cost
#: roughly the same whatever the graph's size: the walk ends when the
#: answer has settled, not when a step budget runs out.
ENOUGH_PINS = 300
ENOUGH_VISITS = 4

#: How far a single excursion travels before restarting from a query
#: pin. Short walks stay close to what somebody already likes; long
#: ones wander into the rest of the graph.
#:
#: Two is deliberate. One hop is "other pins on the same board", which
#: is barely a recommendation. Three starts returning the general
#: population, because this graph's boards overlap heavily.
HOPS = 2


@dataclass(frozen=True)
class Graph:
    """Who holds what. Both directions, because the walk alternates.

    Built by `load` and cached: this is the in-RAM copy that makes a
    walk cost microseconds rather than a query per hop. A query per
    hop is the implementation that looks correct and is unusable -
    three hundred round trips to answer one feed request.
    """

    #: board id -> the pins on it
    pins_on: dict[uuid.UUID, tuple[uuid.UUID, ...]]
    #: pin id -> the boards holding it
    boards_with: dict[uuid.UUID, tuple[uuid.UUID, ...]]

    def __bool__(self) -> bool:
        return bool(self.pins_on)

    @property
    def size(self) -> tuple[int, int]:
        """(boards, pins). For logging and for the tests."""
        return len(self.pins_on), len(self.boards_with)


@dataclass
class Visits:
    """What the walk saw, per starting pin.

    Kept per query pin rather than summed, because the booster below
    cannot be computed from a total - it needs to know how the visits
    were spread across starting points.
    """

    by_query: dict[uuid.UUID, dict[uuid.UUID, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    steps: int = 0

    def saw(self, query: uuid.UUID, pin: uuid.UUID) -> None:
        self.by_query[query][pin] += 1

    def boosted(self) -> dict[uuid.UUID, float]:
        """The multi-hit booster: breadth of reach beats depth.

        `(sum of sqrt(visits)) ** 2` rather than a plain sum. Ten
        visits from one starting pin score 10; one visit from each of
        ten score 100.
        """
        roots: dict[uuid.UUID, float] = defaultdict(float)
        for counts in self.by_query.values():
            for pin, seen in counts.items():
                roots[pin] += math.sqrt(seen)
        return {pin: total * total for pin, total in roots.items()}


def walk(
    graph: Graph,
    *,
    queries: list[uuid.UUID],
    weights: dict[uuid.UUID, float] | None = None,
    rng: random.Random | None = None,
    max_steps: int = MAX_STEPS,
) -> dict[uuid.UUID, float]:
    """Random-walk the graph from `queries`. Returns pin -> score.

    `weights` biases how often each query pin is chosen as a starting
    point - a fit somebody saved yesterday should launch more walks
    than one they reacted to a month ago. Unweighted, every query pin
    is equally likely.

    Deterministic given an `rng`, which is what makes it testable: a
    recommender nobody can reproduce is one nobody can debug.
    """
    chance = rng or random.Random()
    live = [q for q in queries if q in graph.boards_with]
    if not graph or not live:
        return {}

    # Chosen proportionally. `random.choices` wants a parallel list of
    # weights, and a missing or non-positive weight falls back to 1 so
    # one bad number cannot silence a query pin entirely.
    bias = [max(0.01, (weights or {}).get(q, 1.0)) for q in live]

    seen = Visits()
    settled = 0
    for _ in range(max_steps):
        seen.steps += 1
        start = chance.choices(live, weights=bias, k=1)[0]

        at = start
        for _ in range(HOPS):
            boards = graph.boards_with.get(at)
            if not boards:
                break
            board = chance.choice(boards)
            pins = graph.pins_on.get(board)
            if not pins:
                break
            at = chance.choice(pins)
            if at == start:
                # A walk that lands back on its own starting pin has
                # learnt nothing; counting it would reward pins that
                # sit on many boards with themselves.
                continue
            before = seen.by_query[start][at]
            seen.saw(start, at)
            if before + 1 == ENOUGH_VISITS:
                settled += 1

        if settled >= ENOUGH_PINS:
            break

    scores = seen.boosted()
    # The starting pins are not recommendations. Somebody already
    # saved them; showing them back is the most common way a
    # recommender looks broken.
    for q in queries:
        scores.pop(q, None)
    return scores


def neighbours(graph: Graph, pin: uuid.UUID, *, limit: int = 40) -> list[uuid.UUID]:
    """Pins sharing a board with this one, commonest first.

    The cheap, exact version of the walk, for "more like this" on a
    single pin where there is one starting point and no taste profile
    to weight by. Counting co-occurrence directly is both faster and
    more accurate than sampling it.
    """
    together: dict[uuid.UUID, int] = defaultdict(int)
    for board in graph.boards_with.get(pin, ()):
        for other in graph.pins_on.get(board, ()):
            if other != pin:
                together[other] += 1
    ranked = sorted(together.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [pin_id for pin_id, _ in ranked[:limit]]


__all__ = [
    "ENOUGH_PINS",
    "ENOUGH_VISITS",
    "HOPS",
    "MAX_STEPS",
    "Graph",
    "Visits",
    "neighbours",
    "walk",
]
