"""Putting one grid together out of several sources.

**Ranking by score alone produces a worse feed than ranking plus
blending, and the reason is not subtle.** Whichever retrieval source
scores highest wins every slot, so a person with a rich board history
sees only graph results and never anything new, and a brand-new
account sees only trending because that is all it has. Both are a
feed that cannot change. Target ratios fix the proportion before
scores are allowed to argue about the order within it.

Three rules here, in the order they are applied:

1. **Quota.** Each source gets a share of the grid. A source with
   nothing to give hands its share back rather than leaving a gap.
2. **Diversity.** No run of pins by one author, and no run from one
   tag. A grid of nine photographs by the same person is technically
   well-ranked and reads as broken.
3. **Exploration.** A slice is given to pins with almost no
   engagement history, chosen at random. This is epsilon-greedy and
   it costs something real: those slots are, on average, worse than
   the ones they displace. They are what stops the feed being a
   closed loop where only things that have already been shown can
   ever be shown, which is how a recommender starves its own
   corpus.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

#: Where the grid comes from, as a share of its slots.
#:
#: A common published split is roughly 60/20/20 across personalised, trends
#: and ads. This app has no ads, so that slice is given to the graph
#: walk and to exploration instead. The numbers are a starting point
#: that a real deployment would move with experiments, not a
#: discovery - which is why they are one dict and not scattered.
SHARES: dict[str, float] = {
    # The random walk over boards: "people who curate what you curate
    # also kept these". The strongest signal here and the biggest
    # share.
    "graph": 0.35,
    # Pictures that look like the pictures somebody keeps, read off
    # the photographs rather than off anybody's hashtags. This is the
    # slot the embedding retriever fills in larger systems. It takes its share from the
    # walk rather than from exploration, because the two are
    # answering the same question - "more like this" - and the walk
    # cannot answer it at all for a pin nobody has boarded yet.
    "similar": 0.15,
    # Tag and taste matches. Weakest of the three, and last, because
    # it is the only one the person being ranked wrote themselves.
    "affinity": 0.15,
    # Accelerating now. Reserved rather than competed for, because
    # trending pins lose on absolute engagement to older ones and
    # would never appear otherwise.
    "trending": 0.20,
    # Barely-seen pins, chosen at random. The epsilon in
    # epsilon-greedy.
    "fresh": 0.15,
}

#: Longest run of pins by the same author before one is held back.
MOST_IN_A_ROW = 2

#: Longest run sharing a leading tag. Looser than the author rule:
#: somebody browsing decor should see a lot of decor, just not nine
#: identical bedrooms.
MOST_SAME_TAG = 3


@dataclass
class Candidate:
    post_id: uuid.UUID
    source: str
    score: float
    author_id: uuid.UUID | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


def quotas(size: int, shares: dict[str, float] | None = None) -> dict[str, int]:
    """How many slots each source gets in a grid of `size`.

    Largest remainder, so the parts sum to exactly `size`. Rounding
    each share independently loses or gains a slot and the page ends
    up one short, which looks like an off-by-one somewhere else.
    """
    weights = shares or SHARES
    if size <= 0:
        return {name: 0 for name in weights}
    exact = {name: size * share for name, share in weights.items()}
    whole = {name: int(value) for name, value in exact.items()}
    left = size - sum(whole.values())
    # Biggest fractional part first; name as the tie-break so the
    # allocation is deterministic.
    order = sorted(
        exact, key=lambda name: (-(exact[name] - whole[name]), name)
    )
    for name in order[:left]:
        whole[name] += 1
    return whole


def blend(
    candidates: Iterable[Candidate],
    *,
    size: int,
    shares: dict[str, float] | None = None,
    rng: random.Random | None = None,
) -> list[Candidate]:
    """One grid: quota per source, then diversity, then whatever fits.

    Deterministic given an `rng`. A feed nobody can reproduce is a
    feed nobody can debug, and "it looked wrong on my phone" is not a
    bug report anybody can act on without this.
    """
    chance = rng or random.Random()
    want = quotas(size, shares)

    pools: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        pools.setdefault(candidate.source, []).append(candidate)
    for name, pool in pools.items():
        if name == "fresh":
            # Exploration is random by definition. Ranking it by
            # score would pick the best of the barely-seen, which is
            # exactly the bias the slice exists to avoid.
            chance.shuffle(pool)
        else:
            pool.sort(key=lambda c: (-c.score, str(c.post_id)))

    taken: list[Candidate] = []
    used: set[uuid.UUID] = set()
    # Held back by the diversity rule rather than rejected; a run of
    # one author at the top should push them down the page, not
    # delete them.
    deferred: list[Candidate] = []

    def fits(candidate: Candidate) -> bool:
        if candidate.author_id is not None:
            recent = [c.author_id for c in taken[-MOST_IN_A_ROW:]]
            if len(recent) == MOST_IN_A_ROW and all(
                a == candidate.author_id for a in recent
            ):
                return False
        if candidate.tags:
            lead = candidate.tags[0]
            recent_tags = [c.tags[0] for c in taken[-MOST_SAME_TAG:] if c.tags]
            if len(recent_tags) == MOST_SAME_TAG and all(
                t == lead for t in recent_tags
            ):
                return False
        return True

    def take(candidate: Candidate) -> None:
        taken.append(candidate)
        used.add(candidate.post_id)

    def sweep(*, respect_quota: bool, respect_diversity: bool) -> None:
        """One round-robin pass over every source.

        Round-robin rather than source by source: filling in source
        order puts every graph result above every trending one, which
        is a ranked list with extra steps and makes the trending
        quota pointless because all of it lands below the fold.
        """
        moving = True
        while moving and len(taken) < size:
            moving = False
            for name in order:
                if len(taken) >= size:
                    return
                if respect_quota and want[name] <= 0:
                    continue
                pool = pools.get(name, [])
                while cursors[name] < len(pool):
                    candidate = pool[cursors[name]]
                    cursors[name] += 1
                    if candidate.post_id in used:
                        continue
                    if respect_diversity and not fits(candidate):
                        deferred.append(candidate)
                        continue
                    take(candidate)
                    want[name] -= 1
                    moving = True
                    break

    order = sorted(want, key=lambda name: (-want[name], name))
    cursors = dict.fromkeys(order, 0)

    # 1. Each source up to its quota.
    sweep(respect_quota=True, respect_diversity=True)

    # 2. A source that ran dry gives its slots to whoever still has
    #    something, so the page is never short. Still round-robin and
    #    still diverse: re-sorting everything by score here was a real
    #    defect, and it had two symptoms at once. It undid the
    #    shuffle on the exploration slice, so the "random" slots
    #    became the highest-scoring barely-seen pins - the exact bias
    #    the slice exists to escape. And it ignored the author rule,
    #    so one prolific account reappeared in a block at the bottom
    #    of every page.
    sweep(respect_quota=False, respect_diversity=True)

    # 3. Last resort: a short page is worse than an imperfect run, so
    #    the diversity rule is the thing that gives way, and only
    #    once there is genuinely nothing else to put there.
    if len(taken) < size:
        for candidate in deferred:
            if len(taken) >= size:
                break
            if candidate.post_id not in used:
                take(candidate)

    return taken[:size]


__all__ = [
    "MOST_IN_A_ROW",
    "MOST_SAME_TAG",
    "SHARES",
    "Candidate",
    "blend",
    "quotas",
]
