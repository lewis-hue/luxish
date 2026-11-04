"""How many answers each taste question accepts.

**Reported as "Saving failed", with "Request validation failed."
underneath it.** Eleven occasions were selected on a screen that
says "Pick any", against a schema that stopped at six. The message
named no field, so nothing on screen said which question was the
problem or what the limit was.

Two faults, and the second is why the first was hard to see.
"""

from __future__ import annotations

import pytest

from app.domain.taste import (
    AESTHETICS,
    MAX_CHOICES,
    MAX_OCCASIONS,
    OCCASIONS,
    Taste,
    UnknownTaste,
)

#: The exact selection from the report.
REPORTED = (
    "everyday",
    "office",
    "evening",
    "date-night",
    "weekend",
    "wedding-guest",
    "party",
    "festival",
    "travel",
    "holiday",
    "brunch",
)


def test_the_reported_selection_saves() -> None:
    taste = Taste(
        occasions=REPORTED,
        dress_code="smart_casual",
        goal="more_from_what_i_own",
    )
    assert len(taste.occasions) == 11


def test_needing_outfits_for_everything_is_a_real_answer() -> None:
    """**Why the cap was wrong here and right next door.**

    "Where you actually need outfits" is a factual question. Someone
    who needs outfits for work, weekends, the gym, travel, evenings
    and a wedding has given six honest answers before running out,
    and the seventh is not noise. The aesthetics cap exists because
    picking every aesthetic expresses no preference; that reasoning
    does not transfer.
    """
    assert Taste(occasions=OCCASIONS).occasions == OCCASIONS
    assert MAX_OCCASIONS == len(OCCASIONS)


def test_there_is_still_a_bound() -> None:
    """A request is still a request, and an unbounded list is a way
    to write arbitrary data into a profile."""
    assert MAX_OCCASIONS < 1000
    with pytest.raises(UnknownTaste):
        Taste(occasions=(*OCCASIONS, "everyday"))


def test_aesthetics_are_still_capped_at_six() -> None:
    """The reasoning that justified the cap still holds there."""
    assert MAX_CHOICES == 6
    with pytest.raises(UnknownTaste) as caught:
        Taste(aesthetics=AESTHETICS[:7])
    assert "at most 6" in str(caught.value)


def test_the_schema_bound_matches_the_domain_bound() -> None:
    """**This is where the 422 actually came from.**

    FastAPI rejects on the schema before the handler runs, so a
    domain rule the schema disagrees with is a rule nobody reaches
    and an error nobody can read.
    """
    from app.schemas.taste import TasteIn

    def bound(field: str) -> int | None:
        for mark in TasteIn.model_fields[field].metadata:
            if hasattr(mark, "max_length"):
                return mark.max_length
        return None

    assert bound("occasions") == MAX_OCCASIONS
    assert bound("aesthetics") == MAX_CHOICES


def test_the_options_endpoint_publishes_both_bounds() -> None:
    """Served rather than hardcoded in the app, for the reason the
    vocabularies are: a bound the client guesses is a bound the
    client gets wrong, and it did - the screen offered "Pick any"
    against a server that stopped at six."""
    from app.schemas.taste import TasteOptions

    options = TasteOptions()
    assert options.max_choices == MAX_CHOICES
    assert options.max_occasions == MAX_OCCASIONS


def test_a_stored_profile_is_not_truncated_to_six() -> None:
    """Reading back must not quietly drop answers that saving
    accepted."""
    stored = Taste.from_stored({"occasions": list(REPORTED)})
    assert len(stored.occasions) == 11


# --------------------------------------------------------------------------- #
# Saying which field failed
# --------------------------------------------------------------------------- #
def test_a_validation_error_names_the_field() -> None:
    """"Request validation failed." was the entire message, and the
    client shows the message. The details were in the body all
    along, under `errors`, where nobody looking at a phone sees
    them."""
    from fastapi.exceptions import RequestValidationError

    from app.errors import _why

    said = _why(
        RequestValidationError(
            [
                {
                    "loc": ("body", "occasions"),
                    "msg": "List should have at most 6 items",
                    "type": "too_long",
                }
            ]
        )
    )
    assert said == "occasions: List should have at most 6 items."


def test_an_error_with_no_field_still_reads_as_a_sentence() -> None:
    from fastapi.exceptions import RequestValidationError

    from app.errors import _why

    assert _why(RequestValidationError([])) == "Request validation failed."
    assert (
        _why(RequestValidationError([{"loc": ("body",), "msg": "Field required"}]))
        == "Field required."
    )
