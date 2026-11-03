"""What a picture is of, read off the picture.

**The signal an author cannot write.** Tags are a claim typed once by
one person; board placement is the crowd's opinion but needs somebody
to have saved the pin first. Neither helps a brand-new photograph
that was captioned wrongly - and that was the reported failure: a
boucle bed captioned "Wedding guest, not upstaging anybody", offering
a shelf of eveningwear under a photograph of a couch.

This reads the photograph instead.

**Why a vocabulary and a sparse vector rather than CLIP.** The
vendor's API has no embeddings model and no embeddings endpoint -
re-verified against the live API on 2026-11-03, where
``POST /v1/embeddings`` is a 404 on every model in the catalogue
(ADR-004 said the same in October and still holds). What it *does*
have is a vision model with structured output, which the app already
uses to read clothes out of photographs.

So the content signal here is a closed vocabulary filled in by the
vision model, turned into a fixed-length vector. Against a real dense
embedding it is coarser, and it is better in two ways that matter
here: every dimension has a name, so "why am I seeing this" has an
answer; and `subject` is a hard category that can gate retrieval,
which a cosine distance cannot do - a couch and a cream dress are
genuinely close in CLIP space, and must never sit under one another.

**Swappable.** `Embedder` is the seam. A CLIP or Vertex implementation
drops in without touching storage, retrieval or the pipeline; only
`vector_for` and `DIMENSIONS` change, and `model` on the row records
which produced it so a mixed table can be migrated rather than
guessed at.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol

#: What a pin can be *of*. Closed, and the first dimension of
#: everything here.
#:
#: Deliberately coarse. These are the lines across which a
#: recommendation is simply wrong rather than merely weak - nobody
#: looking at a sofa wants a dress, however similar their colours.
#: Finer distinctions are what the attributes below are for.
SUBJECTS: tuple[str, ...] = (
    "outfit",
    "garment",
    "interior",
    "jewellery",
    "beauty",
    "footwear",
    "bag",
    "other",
)

#: Subjects that may be recommended under one another.
#:
#: **Not symmetric, and not transitive.** Jewellery under an outfit is
#: useful - it is what somebody would wear with it. An outfit under a
#: close-up of a ring is a change of subject. Written out in full
#: rather than derived, because every one of these pairs is a product
#: decision somebody should be able to argue with.
GOES_UNDER: dict[str, frozenset[str]] = {
    "outfit": frozenset({"outfit", "garment", "footwear", "bag", "jewellery"}),
    "garment": frozenset({"garment", "outfit", "footwear", "bag"}),
    "interior": frozenset({"interior"}),
    "jewellery": frozenset({"jewellery", "beauty", "bag"}),
    "beauty": frozenset({"beauty", "jewellery"}),
    "footwear": frozenset({"footwear", "outfit", "garment", "bag"}),
    "bag": frozenset({"bag", "outfit", "footwear", "jewellery"}),
    "other": frozenset(SUBJECTS),
}

#: Descriptive facets, each a dimension of the vector.
#:
#: One closed list rather than free text: a vector is only comparable
#: if two pins describing the same thing land on the same word, and
#: free text never does.
FACETS: tuple[str, ...] = (
    # palette
    "neutral", "warm", "cool", "monochrome", "bright", "pastel", "dark",
    # texture and material
    "knit", "denim", "leather", "silk", "linen", "boucle", "metallic",
    "wood", "velvet",
    # mood and setting
    "minimal", "maximal", "vintage", "sporty", "formal", "casual",
    "romantic", "street", "luxury", "cosy",
    # composition
    "closeup", "full_length", "flat_lay", "room_wide", "mirror",
    "outdoors", "studio",
)

#: Length of a vector: one slot per subject, then one per facet.
DIMENSIONS = len(SUBJECTS) + len(FACETS)

#: How much the subject block counts against the facets.
#:
#: High, because subject is the thing that must dominate. Two pins
#: that agree on every facet but disagree on subject - a cream boucle
#: sofa and a cream knit dress - should not be neighbours, and this
#: is what keeps them apart inside the cosine as well as at the gate.
SUBJECT_WEIGHT = 3.0


@dataclass(frozen=True)
class Reading:
    """What the vision model saw. The structured output's shape."""

    subject: str
    facets: tuple[str, ...] = ()
    #: One short phrase, for the "why am I seeing this" line. Never
    #: shown as a caption: it is a machine's description, and this
    #: app does not put those where an author's words go.
    note: str | None = None
    #: 0-1, the model's own confidence in `subject`.
    confidence: float = 1.0

    def clean(self) -> Reading:
        """The same reading with anything unrecognised dropped.

        A model that invents a subject or a facet gets it ignored
        rather than stored: an open vocabulary is not comparable, and
        one typo would quietly create a category of one.
        """
        subject = self.subject if self.subject in SUBJECTS else "other"
        facets = tuple(f for f in dict.fromkeys(self.facets) if f in FACETS)
        confidence = min(1.0, max(0.0, self.confidence))
        return Reading(
            subject=subject, facets=facets, note=self.note, confidence=confidence
        )


class Embedder(Protocol):
    """Anything that can turn a picture into a `Reading`."""

    async def read(
        self, *, image: bytes, content_type: str
    ) -> Reading: ...


def vector_for(reading: Reading) -> list[float]:
    """A fixed-length unit vector. Same vocabulary, same slots, always."""
    cleaned = reading.clean()
    out = [0.0] * DIMENSIONS
    out[SUBJECTS.index(cleaned.subject)] = SUBJECT_WEIGHT * max(
        0.1, cleaned.confidence
    )
    base = len(SUBJECTS)
    for facet in cleaned.facets:
        out[base + FACETS.index(facet)] = 1.0
    return normalise(out)


def normalise(vector: list[float]) -> list[float]:
    """Unit length, so cosine is a dot product and magnitude cannot
    smuggle in "this pin had more facets filled in"."""
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0.0:
        return vector
    return [value / length for value in vector]


def similarity(first: list[float], second: list[float]) -> float:
    """Cosine, on the assumption both are unit length.

    Returns 0.0 for a length mismatch rather than raising. Vectors
    from two different models will be different lengths, and a feed
    must not fall over because a backfill is half done.
    """
    if len(first) != len(second):
        return 0.0
    return sum(a * b for a, b in zip(first, second, strict=False))


def may_sit_under(viewing: str, candidate: str) -> bool:
    """Whether a pin of `candidate` belongs under a pin of `viewing`.

    **The gate the cosine cannot provide.** A cream couch and a cream
    knit dress are genuinely close in any visual space; they are
    still the wrong answer to each other.
    """
    return candidate in GOES_UNDER.get(viewing, frozenset(SUBJECTS))


@dataclass
class Shelf:
    """Candidates ranked by visual similarity, subject respected."""

    viewing: str
    items: list[tuple[str, float]] = field(default_factory=list)


def nearest(
    *,
    viewing_subject: str,
    viewing_vector: list[float],
    candidates: dict[str, tuple[str, list[float]]],
    limit: int = 40,
    floor: float = 0.25,
) -> list[tuple[str, float]]:
    """The most visually similar candidates that may sit under this one.

    `candidates` maps an id to `(subject, vector)`. The subject gate
    is applied before the cosine, not after: filtering afterwards
    would let near-misses of the wrong subject push real matches out
    of the limit.
    """
    scored: list[tuple[str, float]] = []
    for key, (subject, vector) in candidates.items():
        if not may_sit_under(viewing_subject, subject):
            continue
        score = similarity(viewing_vector, vector)
        if score >= floor:
            scored.append((key, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:limit]


__all__ = [
    "DIMENSIONS",
    "FACETS",
    "GOES_UNDER",
    "SUBJECTS",
    "SUBJECT_WEIGHT",
    "Embedder",
    "Reading",
    "Shelf",
    "may_sit_under",
    "nearest",
    "normalise",
    "similarity",
    "vector_for",
]
