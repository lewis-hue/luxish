"""What a pin is actually about, when its author's hashtags are wrong.

**The failure this exists for, exactly as it happened.** A
photograph of a boucle bed was posted with the caption "Wedding
guest, not upstaging anybody" and the tags `#occasion #party
#weddingguest`. Every relatedness signal in the app read those tags,
so opening the couch offered a shelf of women's eveningwear. Nothing
was broken: the feed faithfully obeyed a label that lied.

Author tags cannot be ground truth. They are a claim by one person,
typed once, never checked - and they are wrong by accident far more
often than by malice: a folder dragged into the wrong place, a
template caption reused, a hashtag that meant something else.

**The crowd files things by what they are.** Somebody saving a couch
puts it on a board of rooms, whatever its caption says, because they
are looking at the picture rather than reading the hashtags. So the
boards a pin lands on are an independent opinion about its subject,
and where that opinion contradicts the author, the boards win. This is the
board-derived annotation idea: a pin's real topics come from
where people put it.

**It cannot run before anybody has saved anything.** A pin with no
board placements has no second opinion, so its author's tags stand
unchallenged - which is correct, not a gap. The protection arrives
with the evidence, and `confidence` says how much evidence there is
so a caller can tell "agreed" from "nobody has looked yet".
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass

from app.domain.discovery.graph import Graph

#: How many board-neighbours are needed before consensus means
#: anything.
#:
#: Under this the sample is too small to overrule a person about
#: their own photograph - two neighbours agreeing is a coincidence,
#: not a verdict.
ENOUGH_NEIGHBOURS = 5

#: A tag held by fewer than this share of a pin's board-neighbours,
#: when there were plenty of neighbours to ask, is treated as
#: contradicted.
#:
#: A fifth is deliberately forgiving. A fit genuinely tagged
#: `#weddingguest` sitting on general "going out" boards will still
#: clear it; only a tag that essentially nothing around it shares
#: gets marked down, which is the couch case - zero of its
#: neighbours are wedding outfits.
AGREEMENT_FLOOR = 0.2

#: What a contradicted tag is worth instead of 1.0.
#:
#: Not zero. The author may be right and the crowd early or wrong,
#: and silently deleting somebody's own label is a worse failure than
#: ranking it low. It stops the tag dominating; it does not erase it.
DOUBTED_WEIGHT = 0.15


@dataclass(frozen=True)
class Reading:
    """What this pin seems to be about, and how sure that is."""

    #: Tag to weight. Author tags, each scaled by whether the boards
    #: this pin sits on agree.
    weights: dict[str, float]
    #: Tags the boards suggest that the author did not write.
    suggested: tuple[str, ...]
    #: How many board-neighbours the reading is based on.
    neighbours: int

    @property
    def confident(self) -> bool:
        return self.neighbours >= ENOUGH_NEIGHBOURS

    def doubted(self) -> tuple[str, ...]:
        """Author tags the boards contradict."""
        return tuple(
            tag for tag, weight in self.weights.items() if weight < 1.0
        )


def read(
    graph: Graph,
    *,
    post_id: uuid.UUID,
    author_tags: list[str],
    tags_by_post: dict[uuid.UUID, list[str]],
    limit: int = 60,
) -> Reading:
    """Weigh this pin's tags against what sits beside it on boards.

    Pure, and takes the tag table as a dict rather than reading it,
    so the whole behaviour is testable without a database and the
    caller can load the tags once for a whole page of pins.
    """
    beside: Counter[str] = Counter()
    seen_neighbours = 0
    for board in graph.boards_with.get(post_id, ()):
        for other in graph.pins_on.get(board, ()):
            if other == post_id:
                continue
            seen_neighbours += 1
            beside.update(tags_by_post.get(other, ()))
            if seen_neighbours >= limit:
                break
        if seen_neighbours >= limit:
            break

    if seen_neighbours < ENOUGH_NEIGHBOURS:
        # Not enough evidence to contradict anybody. Author's tags
        # stand at full weight, and `confident` says why.
        return Reading(
            weights={tag: 1.0 for tag in author_tags},
            suggested=(),
            neighbours=seen_neighbours,
        )

    weights: dict[str, float] = {}
    for tag in author_tags:
        share = beside.get(tag, 0) / seen_neighbours
        weights[tag] = 1.0 if share >= AGREEMENT_FLOOR else DOUBTED_WEIGHT

    # What the neighbourhood says this is, that the author did not.
    # Offered rather than applied: these are a retrieval hint, not a
    # relabelling of somebody's post.
    author = set(author_tags)
    suggested = tuple(
        tag
        for tag, count in beside.most_common(6)
        if tag not in author and count / seen_neighbours >= AGREEMENT_FLOOR * 2
    )
    return Reading(
        weights=weights, suggested=suggested, neighbours=seen_neighbours
    )


def overlap(
    first: Reading, mine: list[str], theirs: list[str]
) -> float:
    """How alike two pins are by tag, with doubted tags discounted.

    `first` is the reading for the pin being viewed. A tag its boards
    contradict contributes almost nothing, so a couch mislabelled
    `#weddingguest` no longer scores against every wedding outfit in
    the app.
    """
    shared = set(mine) & set(theirs)
    return sum(first.weights.get(tag, 1.0) for tag in shared)


__all__ = [
    "AGREEMENT_FLOOR",
    "DOUBTED_WEIGHT",
    "ENOUGH_NEIGHBOURS",
    "Reading",
    "overlap",
    "read",
]
