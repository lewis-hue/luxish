"""Content-derived subjects and the vectors built from them.

The failure these exist for: a boucle bed captioned "Wedding guest,
not upstaging anybody" offered a shelf of eveningwear. Tags lied and
the pin was too new for board consensus to overrule them. Reading the
photograph is the only signal left.

The test that matters most is the last one in the first group: a
cream couch and a cream knit dress are genuinely similar - same
palette, same texture words, both soft and neutral - and must still
never sit under one another. A cosine alone cannot express that,
which is why there is a gate as well as a distance.
"""

from __future__ import annotations

from app.domain.discovery.subject import (
    DIMENSIONS,
    FACETS,
    SUBJECTS,
    Reading,
    may_sit_under,
    nearest,
    similarity,
    vector_for,
)


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def test_an_interior_never_sits_under_an_outfit() -> None:
    """**The reported bug, as a rule.**"""
    assert not may_sit_under("outfit", "interior")
    assert not may_sit_under("interior", "outfit")


def test_jewellery_sits_under_an_outfit_but_not_the_reverse() -> None:
    """Deliberately not symmetric.

    A ring under a full outfit is what somebody would wear with it. A
    full outfit under a close-up of a ring is a change of subject.
    """
    assert may_sit_under("outfit", "jewellery")
    assert not may_sit_under("jewellery", "outfit")


def test_every_subject_sits_under_itself() -> None:
    for subject in SUBJECTS:
        assert may_sit_under(subject, subject), subject


def test_an_unreadable_picture_is_not_a_filter() -> None:
    """`other` means the model could not tell, not that nothing matches.

    Gating on an unknown would make a failed read invisible, which is
    a worse outcome than a loose one.
    """
    assert all(may_sit_under("other", s) for s in SUBJECTS)


def test_a_couch_and_a_cream_dress_stay_apart() -> None:
    """**The case a cosine gets wrong.**

    Identical palette and texture words. Genuinely close in any
    visual space, and still the wrong answer to each other.
    """
    couch = Reading(subject="interior", facets=("neutral", "boucle", "cosy"))
    dress = Reading(subject="outfit", facets=("neutral", "boucle", "cosy"))

    # Every descriptive word they carry is identical, which is what a
    # purely visual embedding would be comparing. Shown by scoring
    # them with the subject held constant: 1.0, indistinguishable.
    same_subject = similarity(
        vector_for(Reading(subject="outfit", facets=couch.facets)),
        vector_for(dress),
    )
    assert abs(same_subject - 1.0) < 1e-9, (
        "on appearance alone these are the same pin, which is the "
        "whole difficulty"
    )

    # The subject weighting already separates them inside the cosine,
    # which is deliberate and is not sufficient on its own: a lower
    # score still leaves them rankable against each other.
    assert similarity(vector_for(couch), vector_for(dress)) < 0.5
    assert not may_sit_under("outfit", "interior")

    shelf = nearest(
        viewing_subject="outfit",
        viewing_vector=vector_for(dress),
        candidates={"the-couch": ("interior", vector_for(couch))},
    )
    assert shelf == [], "a couch reached the shelf under a dress"


# --------------------------------------------------------------------------- #
# The vector
# --------------------------------------------------------------------------- #
def test_a_vector_is_always_the_same_length() -> None:
    """Otherwise cosine silently compares different vocabularies."""
    assert len(vector_for(Reading(subject="outfit"))) == DIMENSIONS
    assert (
        len(vector_for(Reading(subject="interior", facets=FACETS)))
        == DIMENSIONS
    )


def test_a_vector_is_unit_length() -> None:
    """So magnitude cannot smuggle in "this pin had more facets"."""
    thin = vector_for(Reading(subject="outfit", facets=("neutral",)))
    fat = vector_for(Reading(subject="outfit", facets=FACETS[:10]))
    assert abs(similarity(thin, thin) - 1.0) < 1e-9
    assert abs(similarity(fat, fat) - 1.0) < 1e-9


def test_subject_dominates_the_facets() -> None:
    """Two interiors sharing nothing else beat an interior and an outfit
    that share everything else."""
    a_room = Reading(subject="interior", facets=("wood", "dark"))
    another_room = Reading(subject="interior", facets=("pastel", "bright"))
    an_outfit = Reading(subject="outfit", facets=("wood", "dark"))

    same_subject = similarity(vector_for(a_room), vector_for(another_room))
    same_facets = similarity(vector_for(a_room), vector_for(an_outfit))
    assert same_subject > same_facets


def test_an_invented_subject_becomes_other() -> None:
    """An open vocabulary is not comparable; one typo would make a
    category of one."""
    got = Reading(subject="sofa-ish", facets=("neutral",)).clean()
    assert got.subject == "other"


def test_invented_facets_are_dropped() -> None:
    got = Reading(subject="outfit", facets=("neutral", "swag", "cosy")).clean()
    assert got.facets == ("neutral", "cosy")


def test_duplicate_facets_count_once() -> None:
    got = Reading(subject="outfit", facets=("neutral", "neutral")).clean()
    assert got.facets == ("neutral",)


def test_confidence_is_clamped() -> None:
    assert Reading(subject="outfit", confidence=5.0).clean().confidence == 1.0
    assert Reading(subject="outfit", confidence=-1.0).clean().confidence == 0.0


def test_a_zero_confidence_reading_still_has_a_subject() -> None:
    """Otherwise an unsure read produces a zero vector that matches
    everything equally, which is worse than a weak opinion."""
    vector = vector_for(Reading(subject="interior", confidence=0.0))
    assert vector[SUBJECTS.index("interior")] > 0.0


def test_mismatched_vector_lengths_score_zero_rather_than_raise() -> None:
    """A half-finished backfill must not break the feed."""
    assert similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def test_nearest_ranks_by_similarity() -> None:
    viewing = Reading(subject="interior", facets=("neutral", "boucle", "cosy"))
    close = Reading(subject="interior", facets=("neutral", "boucle"))
    far = Reading(subject="interior", facets=("dark", "metallic"))

    ranked = nearest(
        viewing_subject="interior",
        viewing_vector=vector_for(viewing),
        candidates={
            "far": ("interior", vector_for(far)),
            "close": ("interior", vector_for(close)),
        },
        floor=0.0,
    )
    assert [key for key, _ in ranked] == ["close", "far"]


def test_nearest_gates_before_it_ranks() -> None:
    """**Order matters.**

    Filtering after the limit would let near-misses of the wrong
    subject push real matches out of the results entirely.
    """
    viewing = Reading(subject="interior", facets=("neutral", "cosy"))
    candidates = {
        f"outfit-{i}": ("outfit", vector_for(Reading(
            subject="outfit", facets=("neutral", "cosy")
        )))
        for i in range(20)
    }
    candidates["the-room"] = (
        "interior",
        vector_for(Reading(subject="interior", facets=("neutral",))),
    )

    ranked = nearest(
        viewing_subject="interior",
        viewing_vector=vector_for(viewing),
        candidates=candidates,
        limit=5,
    )
    assert [key for key, _ in ranked] == ["the-room"]


def test_a_floor_keeps_unrelated_pins_off_the_shelf() -> None:
    """An empty shelf is better than a wrong one."""
    viewing = Reading(subject="interior", facets=("dark", "metallic"))
    unrelated = Reading(subject="interior", facets=("pastel", "romantic"))
    ranked = nearest(
        viewing_subject="interior",
        viewing_vector=vector_for(viewing),
        candidates={"nope": ("interior", vector_for(unrelated))},
        floor=0.9,
    )
    assert ranked == []
