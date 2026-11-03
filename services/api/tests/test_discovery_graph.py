"""The random walk, the booster, and the blend.

All three are pure functions over data structures, which is the whole
reason they were written that way: a recommender whose behaviour can
only be observed by looking at a phone is one nobody can change
safely. Every test here fixes the seed, so a failure is reproducible
rather than "it looked wrong once".
"""

from __future__ import annotations

import random
import uuid

from app.domain.discovery.blend import (
    MOST_IN_A_ROW,
    SHARES,
    Candidate,
    blend,
    quotas,
)
from app.domain.discovery.graph import Graph, neighbours, walk


def ids(n: int) -> list[uuid.UUID]:
    """Stable ids, so a failure names the same pin every run."""
    return [uuid.UUID(int=i, version=4) for i in range(1, n + 1)]


def graph_of(boards: dict[int, list[int]]) -> Graph:
    """A graph from {board number: [pin numbers]}."""
    everything = ids(64)
    pins_on = {
        everything[b]: tuple(everything[p] for p in pins)
        for b, pins in boards.items()
    }
    holding: dict[uuid.UUID, list[uuid.UUID]] = {}
    for board, pins in pins_on.items():
        for pin in pins:
            holding.setdefault(pin, []).append(board)
    return Graph(
        pins_on=pins_on,
        boards_with={p: tuple(b) for p, b in holding.items()},
    )


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #
def test_a_walk_finds_what_shares_a_board() -> None:
    """The one claim the whole thing rests on.

    Two pins are related because somebody put them on the same board.
    """
    everything = ids(64)
    g = graph_of({10: [1, 2, 3], 11: [4, 5, 6]})

    found = walk(g, queries=[everything[1]], rng=random.Random(7))

    assert everything[2] in found and everything[3] in found
    # Nothing from the board this person has no connection to.
    assert everything[4] not in found
    assert everything[5] not in found


def test_a_starting_pin_is_never_recommended_back() -> None:
    """The commonest way a recommender looks broken.

    Somebody already saved it. Showing it back as a discovery says
    the system has not noticed what they did.
    """
    everything = ids(64)
    g = graph_of({10: [1, 2, 3]})
    found = walk(g, queries=[everything[1]], rng=random.Random(7))
    assert everything[1] not in found


def test_breadth_of_reach_beats_depth() -> None:
    """**The multi-hit booster, which is the point of the booster.**

    One pin sits on a board with each of three things this person
    likes. Another sits, three times over, with only the first. The
    first pin is related to this person's taste; the second is
    related to one thing they saved. Summing visits would rank them
    equally or backwards; `(sum of sqrt)**2` ranks them correctly.
    """
    everything = ids(64)
    # 20 shares a board with each of 1, 2 and 3 (broad).
    # 21 shares three boards with 1 only (deep).
    g = graph_of(
        {
            10: [1, 20],
            11: [2, 20],
            12: [3, 20],
            13: [1, 21],
            14: [1, 21],
            15: [1, 21],
        }
    )
    found = walk(
        g,
        queries=[everything[1], everything[2], everything[3]],
        rng=random.Random(11),
    )
    assert found[everything[20]] > found[everything[21]], (
        "a pin reached from three different starting points must beat "
        "one reached repeatedly from a single starting point"
    )


def test_the_walk_is_reproducible() -> None:
    """A feed nobody can reproduce is a feed nobody can debug."""
    everything = ids(64)
    g = graph_of({10: [1, 2, 3], 11: [2, 4, 5], 12: [3, 5, 6]})
    once = walk(g, queries=[everything[1]], rng=random.Random(3))
    twice = walk(g, queries=[everything[1]], rng=random.Random(3))
    assert once == twice


def test_weights_steer_where_the_walk_starts() -> None:
    """A fit saved yesterday should pull harder than one from a month ago."""
    everything = ids(64)
    g = graph_of({10: [1, 20, 21, 22], 11: [2, 30, 31, 32]})
    found = walk(
        g,
        queries=[everything[1], everything[2]],
        weights={everything[1]: 50.0, everything[2]: 0.5},
        rng=random.Random(5),
    )
    from_one = sum(found.get(everything[i], 0) for i in (20, 21, 22))
    from_two = sum(found.get(everything[i], 0) for i in (30, 31, 32))
    assert from_one > from_two


def test_an_empty_graph_returns_nothing_rather_than_raising() -> None:
    """A new deployment has no boards. The feed still has to load."""
    empty = Graph(pins_on={}, boards_with={})
    assert walk(empty, queries=ids(3), rng=random.Random(1)) == {}


def test_a_query_pin_nobody_boarded_returns_nothing() -> None:
    """Posting something does not put it in the graph; boarding it does."""
    everything = ids(64)
    g = graph_of({10: [1, 2]})
    assert walk(g, queries=[everything[40]], rng=random.Random(1)) == {}


def test_neighbours_counts_rather_than_samples() -> None:
    """For a single pin there is an exact answer, so sampling is wrong.

    Used by "more like this", where there is one starting point and
    no taste profile to weight by.
    """
    everything = ids(64)
    g = graph_of({10: [1, 2, 3], 11: [1, 2], 12: [1, 3]})
    near = neighbours(g, everything[1])
    # 2 and 3 each share two boards with 1; both are present and the
    # order is deterministic.
    assert set(near) == {everything[2], everything[3]}
    assert near == neighbours(g, everything[1])


# --------------------------------------------------------------------------- #
# Quotas and blending
# --------------------------------------------------------------------------- #
def test_quotas_sum_to_the_page() -> None:
    """Rounding each share alone loses a slot and the page comes up short."""
    for size in range(1, 60):
        assert sum(quotas(size).values()) == size


def test_every_source_gets_a_share_of_a_full_page() -> None:
    got = quotas(20)
    assert all(got[name] > 0 for name in SHARES), got


def test_blending_mixes_the_top_of_the_grid() -> None:
    """**Filling source by source is a ranked list with extra steps.**

    If every graph result sits above every trending one, reserving a
    trending quota has achieved nothing: the trending pins are all
    below the fold.
    """
    everything = ids(64)
    pool = [
        Candidate(everything[i], "graph", score=100 - i, author_id=everything[i])
        for i in range(1, 20)
    ] + [
        Candidate(everything[i], "trending", score=1.0, author_id=everything[i])
        for i in range(20, 40)
    ]
    grid = blend(pool, size=12, rng=random.Random(2))
    top = [c.source for c in grid[:6]]
    assert "trending" in top, top


def test_one_author_never_runs_down_the_page() -> None:
    """Nine photographs by the same person is well-ranked and broken."""
    everything = ids(64)
    hog = everything[50]
    pool = [
        Candidate(everything[i], "graph", score=100 - i, author_id=hog)
        for i in range(1, 15)
    ] + [
        Candidate(everything[i], "graph", score=1.0, author_id=everything[i])
        for i in range(15, 30)
    ]
    grid = blend(pool, size=12, rng=random.Random(2))

    run = best = 0
    for candidate in grid:
        run = run + 1 if candidate.author_id == hog else 0
        best = max(best, run)
    assert best <= MOST_IN_A_ROW, f"{best} in a row by one author"


def test_a_source_with_nothing_gives_its_slots_away() -> None:
    """A quota is a target, not a hole in the page."""
    everything = ids(64)
    pool = [
        Candidate(everything[i], "graph", score=float(i), author_id=everything[i])
        for i in range(1, 30)
    ]
    grid = blend(pool, size=15, rng=random.Random(4))
    assert len(grid) == 15
    assert {c.source for c in grid} == {"graph"}


def test_nothing_appears_twice() -> None:
    """The same pin can be retrieved by several sources at once."""
    everything = ids(64)
    shared = everything[5]
    pool = [
        Candidate(shared, "graph", score=10.0, author_id=everything[1]),
        Candidate(shared, "trending", score=9.0, author_id=everything[1]),
        Candidate(shared, "fresh", score=1.0, author_id=everything[1]),
    ] + [
        Candidate(everything[i], "graph", score=1.0, author_id=everything[i])
        for i in range(10, 25)
    ]
    grid = blend(pool, size=10, rng=random.Random(6))
    assert len(grid) == len({c.post_id for c in grid})


def test_exploration_is_random_rather_than_the_best_of_the_unseen() -> None:
    """**Ranking the exploration slice defeats it.**

    Picking the highest-scoring barely-seen pins reintroduces exactly
    the bias the slice exists to escape - the pins with a head start
    win again, and genuinely cold content never gets an impression.
    """
    everything = ids(64)
    pool = [
        Candidate(everything[i], "fresh", score=float(i), author_id=everything[i])
        for i in range(1, 40)
    ]
    first = [c.post_id for c in blend(pool, size=8, rng=random.Random(1))]
    second = [c.post_id for c in blend(pool, size=8, rng=random.Random(99))]
    assert first != second, "the fresh slice is not being shuffled"


def test_blending_is_reproducible() -> None:
    everything = ids(64)
    pool = [
        Candidate(everything[i], "graph" if i % 2 else "trending",
                  score=float(i), author_id=everything[i])
        for i in range(1, 30)
    ]
    once = [c.post_id for c in blend(pool, size=12, rng=random.Random(8))]
    twice = [c.post_id for c in blend(pool, size=12, rng=random.Random(8))]
    assert once == twice


def test_an_empty_pool_is_an_empty_grid() -> None:
    assert blend([], size=10, rng=random.Random(1)) == []
