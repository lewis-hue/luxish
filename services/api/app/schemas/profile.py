"""Taste profile response shapes."""

from __future__ import annotations

from pydantic import BaseModel


class ProfileOut(BaseModel):
    """What the app needs to personalise, and nothing about the person.

    Deliberately not the raw signals. A client has no use for the garment
    counts and every reason not to hold them, so what crosses the wire is the
    conclusion: which collections to lead each shelf with, and the two facts
    a screen needs to explain itself honestly.
    """

    #: Collection ids for "how to wear what you own", best fit first.
    formula: list[str]
    #: Collection ids for "the look", most reached-for first.
    aesthetics: list[str]
    #: How many garments this rests on, so a screen can say "from your 9
    #: pieces" rather than implying a confidence it has not earned.
    wardrobe_size: int
    #: Slots with too little in them to build an outfit from.
    gaps: list[str]
    #: Whether the taste questions have been answered. A client shows a
    #: different prompt for "not asked" than for "asked and skipped".
    answered: bool


class InspirationOut(BaseModel):
    """The "how to wear what you own" shelf, with its provenance.

    `personalised` is not decoration. False means this is a ranking from the
    viewer's own wardrobe or the general order, *not* a set made for a group
    they are in, and a client that renders the two identically is making a
    claim the data does not support.
    """

    collections: list[str]
    rationale: str
    personalised: bool
    #: How many people a personalised set was made for, so the claim can show
    #: its basis. Meaningless when `personalised` is false.
    cohort_size: int
