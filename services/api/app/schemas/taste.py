"""Taste request and response shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.taste import (
    AESTHETICS,
    DRESS_CODES,
    GOALS,
    MAX_CHOICES,
    OCCASIONS,
)


class TasteIn(BaseModel):
    """What somebody says they like. Every field optional.

    Sending `{}` is a valid, meaningful request: it is somebody declining the
    questions, which is a different state from never having been asked.
    """

    aesthetics: list[str] = Field(default_factory=list, max_length=MAX_CHOICES)
    occasions: list[str] = Field(default_factory=list, max_length=MAX_CHOICES)
    dress_code: str = "unspecified"
    goal: str | None = None


class TasteOut(TasteIn):
    #: Whether anything was said at all, so a client can tell "asked and
    #: declined" from "not yet asked" without inferring it from empty lists.
    answered: bool
    #: Which order to show the Discover shelves in, decided by the goal.
    #: Returned rather than computed on the client so the rule has one home.
    lens_order: list[str]


class TasteOptions(BaseModel):
    """The vocabularies, so a client renders what the server will accept.

    Served rather than hardcoded in the app: an aesthetic added here and not
    there is a question nobody can answer, and one removed here but still
    offered is an answer that is rejected after somebody taps it.
    """

    aesthetics: list[str] = list(AESTHETICS)
    occasions: list[str] = list(OCCASIONS)
    dress_codes: list[str] = list(DRESS_CODES)
    goals: list[str] = list(GOALS)
    max_choices: int = MAX_CHOICES
