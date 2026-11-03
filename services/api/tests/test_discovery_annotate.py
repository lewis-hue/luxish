"""Tags weighed against where people actually file a pin.

Written from a real failure. A photograph of a boucle bed was posted
captioned "Wedding guest, not upstaging anybody" and tagged
`#occasion #party #weddingguest`, and the app offered a shelf of
women's eveningwear underneath it. Nothing was broken - every
relatedness signal read those tags and obeyed them.

The rule these tests hold in place: an author's tag that essentially
nothing around the pin shares is discounted, and a pin nobody has
boarded yet keeps its author's tags at full weight, because there is
no second opinion to be had.
"""

from __future__ import annotations

import uuid

from app.domain.discovery.annotate import (
    AGREEMENT_FLOOR,
    DOUBTED_WEIGHT,
    ENOUGH_NEIGHBOURS,
    overlap,
    read,
)
from app.domain.discovery.graph import Graph


def ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i, version=4) for i in range(1, n + 1)]


EVERY = ids(80)


def graph_of(boards: dict[int, list[int]]) -> Graph:
    pins_on = {
        EVERY[b]: tuple(EVERY[p] for p in pins) for b, pins in boards.items()
    }
    holding: dict[uuid.UUID, list[uuid.UUID]] = {}
    for board, pins in pins_on.items():
        for pin in pins:
            holding.setdefault(pin, []).append(board)
    return Graph(
        pins_on=pins_on, boards_with={p: tuple(b) for p, b in holding.items()}
    )


def test_a_tag_nothing_around_it_shares_is_doubted() -> None:
    """**The couch.**

    Pin 1 is a bed, tagged `weddingguest` by its author, sitting on a
    board of rooms. Eight neighbours, none of them wedding outfits.
    """
    g = graph_of({50: [1, 2, 3, 4, 5, 6, 7, 8, 9]})
    tags = {EVERY[i]: ["interiors", "bedroom"] for i in range(2, 10)}

    got = read(
        g,
        post_id=EVERY[1],
        author_tags=["weddingguest", "party"],
        tags_by_post=tags,
    )

    assert got.confident
    assert got.weights["weddingguest"] == DOUBTED_WEIGHT
    assert got.weights["party"] == DOUBTED_WEIGHT
    assert set(got.doubted()) == {"weddingguest", "party"}


def test_the_boards_offer_what_the_author_left_out() -> None:
    """The neighbourhood's own opinion, as a retrieval hint.

    Offered rather than applied: this does not relabel somebody's
    post, it gives retrieval somewhere better to look.
    """
    g = graph_of({50: [1, 2, 3, 4, 5, 6, 7, 8, 9]})
    tags = {EVERY[i]: ["interiors", "bedroom"] for i in range(2, 10)}

    got = read(
        g, post_id=EVERY[1], author_tags=["weddingguest"], tags_by_post=tags
    )
    assert "interiors" in got.suggested
    assert "bedroom" in got.suggested
    # It never suggests back what the author already wrote.
    assert "weddingguest" not in got.suggested


def test_a_tag_the_neighbourhood_agrees_with_keeps_its_weight() -> None:
    """The common case must not be punished.

    A genuine wedding-guest fit on boards full of wedding-guest fits
    keeps its tag at full strength.
    """
    g = graph_of({50: [1, 2, 3, 4, 5, 6, 7, 8, 9]})
    tags = {EVERY[i]: ["weddingguest", "occasion"] for i in range(2, 10)}

    got = read(
        g, post_id=EVERY[1], author_tags=["weddingguest"], tags_by_post=tags
    )
    assert got.weights["weddingguest"] == 1.0
    assert got.doubted() == ()


def test_a_tag_a_minority_shares_still_counts() -> None:
    """**Deliberately forgiving.**

    A fit tagged `weddingguest` sitting on general "going out" boards
    should survive. Only a tag essentially nothing nearby shares gets
    marked down.
    """
    # Two of eight neighbours share it: a quarter, over the floor.
    g = graph_of({50: [1, 2, 3, 4, 5, 6, 7, 8, 9]})
    tags = {EVERY[i]: ["evening"] for i in range(2, 10)}
    tags[EVERY[2]] = ["weddingguest", "evening"]
    tags[EVERY[3]] = ["weddingguest", "evening"]

    got = read(
        g, post_id=EVERY[1], author_tags=["weddingguest"], tags_by_post=tags
    )
    assert 2 / 8 >= AGREEMENT_FLOOR
    assert got.weights["weddingguest"] == 1.0


def test_a_pin_nobody_has_boarded_keeps_its_authors_tags() -> None:
    """**No evidence is not evidence against.**

    A new pin has no second opinion, so the author's label stands -
    which is correct rather than a gap. `confident` is how a caller
    tells "agreed" from "nobody has looked yet".
    """
    g = graph_of({50: [1, 2]})
    got = read(
        g,
        post_id=EVERY[1],
        author_tags=["weddingguest"],
        tags_by_post={EVERY[2]: ["interiors"]},
    )
    assert not got.confident
    assert got.neighbours < ENOUGH_NEIGHBOURS
    assert got.weights["weddingguest"] == 1.0


def test_a_pin_on_no_board_at_all_is_handled() -> None:
    g = graph_of({50: [2, 3]})
    got = read(
        g, post_id=EVERY[1], author_tags=["ootd"], tags_by_post={}
    )
    assert got.neighbours == 0
    assert got.weights == {"ootd": 1.0}


def test_a_doubted_tag_barely_scores_against_a_match() -> None:
    """The consequence, where it is actually used.

    The couch and a wedding outfit share `weddingguest`. With the tag
    doubted, that shared tag is worth almost nothing, so the outfit
    no longer outranks everything else under the couch.
    """
    g = graph_of({50: [1, 2, 3, 4, 5, 6, 7, 8, 9]})
    tags = {EVERY[i]: ["interiors", "bedroom"] for i in range(2, 10)}
    couch = read(
        g,
        post_id=EVERY[1],
        author_tags=["weddingguest", "bedroom"],
        tags_by_post=tags,
    )

    a_dress = overlap(couch, ["weddingguest", "bedroom"], ["weddingguest"])
    a_room = overlap(couch, ["weddingguest", "bedroom"], ["bedroom"])
    assert a_room > a_dress, (
        "a room should out-score a dress under a photograph of a bed"
    )


def test_an_untouched_reading_scores_tags_normally() -> None:
    """Without consensus, overlap is the old plain count."""
    g = graph_of({50: [1, 2]})
    fresh = read(
        g, post_id=EVERY[1], author_tags=["a", "b"], tags_by_post={}
    )
    assert overlap(fresh, ["a", "b"], ["a", "b"]) == 2.0
    assert overlap(fresh, ["a", "b"], ["a"]) == 1.0
