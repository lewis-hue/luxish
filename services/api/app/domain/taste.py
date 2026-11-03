"""What somebody says they like, asked once at sign-up.

**Asked, never inferred**, and the reasoning is the same one the avatar's
appearance vocabulary settled: a taste profile derived from somebody's clothes
rather than from their answers is an inference about a person, and this
service does not make those. It lives in `preferences` because that table's
own rule is that a stated preference beats an inference — which is what makes
"asked" structural rather than a convention somebody has to remember.

**Every field is optional and the whole thing is skippable.** A new account
with nothing stated is a valid account; the personalised shelf simply falls
back to the general one and says so. Making this a wall between sign-up and
the product would be worse than having no personalisation at all, because
browsing already works with no account and this would be the thing that
stopped it.

**It is a starting point, not the profile.** Interaction history and wardrobe
composition are the other two signals and they decay and grow; this one does
not, so it is what a brand-new account has on day one and what the others
override as they accumulate. Nothing here should be read as a permanent
statement about a person's taste.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.preference import Preference

#: The key the stated taste lives under in `preferences`.
TASTE_KEY = "taste"

#: The aesthetics somebody can say they are drawn to.
#:
#: These are collection ids from the mobile taxonomy rather than a vocabulary
#: invented here, so an answer maps straight onto a shelf with no translation
#: layer that could drift. Validated against this tuple: an id the client
#: sends that is not here is rejected rather than stored, because a stored
#: answer that matches no collection is an answer that silently does nothing.
AESTHETICS = (
    "streetwear",
    "quiet-luxury",
    "clean-girl",
    "downtown-romantic",
    "dark-academia",
    "gorpcore",
    "blokecore",
    "y2k",
    "minimalist",
    "monochrome",
    "heritage",
    "modest",
)

#: Where somebody actually needs outfits. Collection ids again.
#: Six was too few to describe what people actually dress for.
#:
#: Kept to things somebody would genuinely file an outfit under, and
#: ordered roughly by how often they come up rather than
#: alphabetically - a list people scan should start with the common
#: ones. Hyphenated ids, because that is what the six already here
#: used and changing the spelling would orphan every post tagged
#: with them.
OCCASIONS = (
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
    "dinner",
    "interview",
    "graduation",
    "funeral",
    "place-of-worship",
    "gym",
    "outdoors",
    "beach",
    "rainy-day",
    "cold-weather",
    "loungewear",
)

#: How formally they dress on an ordinary working day.
#:
#: Single answer rather than several: this is one scale, and somebody who
#: picks both "no dress code" and "business formal" has told you nothing.
DRESS_CODES = ("none", "smart_casual", "business", "formal", "unspecified")

#: What they are here to do, which decides which shelf leads.
#:
#: `more_from_what_i_own` points at the formula lens, `what_to_wear_to` at
#: occasion, `find_my_look` at aesthetic. The shelves already exist; this says
#: which order to put them in.
GOALS = ("more_from_what_i_own", "what_to_wear_to", "find_my_look")

#: The most answers accepted per multiple-choice question.
#:
#: Somebody who picks every aesthetic has expressed no preference, and storing
#: it as one would make their shelf identical to the default while looking
#: personalised. The cap is a bound on the request, not a judgement: six of
#: twelve is already a wide taste.
MAX_CHOICES = 6


class UnknownTaste(ApiError):
    status_code = 422
    code = "unknown_taste"
    default_message = "That is not something this service records."


@dataclass(frozen=True, slots=True)
class Taste:
    """What somebody said. Every field optional."""

    aesthetics: tuple[str, ...] = ()
    occasions: tuple[str, ...] = ()
    dress_code: str = "unspecified"
    goal: str | None = None

    def __post_init__(self) -> None:
        for name, values, allowed in (
            ("aesthetics", self.aesthetics, AESTHETICS),
            ("occasions", self.occasions, OCCASIONS),
        ):
            unknown = [value for value in values if value not in allowed]
            if unknown:
                raise UnknownTaste(
                    f"{name} contains {', '.join(sorted(unknown))}, which this "
                    "service does not record."
                )
            if len(values) > MAX_CHOICES:
                raise UnknownTaste(
                    f"{name} may carry at most {MAX_CHOICES} answers, got "
                    f"{len(values)}."
                )
            if len(set(values)) != len(values):
                raise UnknownTaste(f"{name} contains the same answer twice.")

        if self.dress_code not in DRESS_CODES:
            raise UnknownTaste(
                f"dress_code must be one of {', '.join(DRESS_CODES)}, got "
                f"{self.dress_code!r}."
            )
        if self.goal is not None and self.goal not in GOALS:
            raise UnknownTaste(
                f"goal must be one of {', '.join(GOALS)}, got {self.goal!r}."
            )

    @property
    def answered(self) -> bool:
        """Whether anything was said at all.

        The screen is skippable, so "asked and declined" and "never asked" are
        different states and a client has to be able to tell them apart — one
        is a question still to put, the other an answer already given.
        """
        return bool(
            self.aesthetics
            or self.occasions
            or self.dress_code != "unspecified"
            or self.goal
        )

    @classmethod
    def from_stored(cls, value: Any) -> Taste:
        """Read a stored preference, tolerating anything written before now."""
        if not isinstance(value, dict):
            return cls()

        def listed(key: str, allowed: tuple[str, ...]) -> tuple[str, ...]:
            raw = value.get(key)
            if not isinstance(raw, list):
                return ()
            # Silently dropping an unrecognised id rather than raising: a
            # collection retired in a later release must not make somebody's
            # whole profile unreadable.
            seen: list[str] = []
            for item in raw:
                if item in allowed and item not in seen:
                    seen.append(str(item))
            return tuple(seen[:MAX_CHOICES])

        dress_code = value.get("dress_code")
        goal = value.get("goal")
        return cls(
            aesthetics=listed("aesthetics", AESTHETICS),
            occasions=listed("occasions", OCCASIONS),
            dress_code=dress_code if dress_code in DRESS_CODES else "unspecified",
            goal=goal if goal in GOALS else None,
        )

    def as_stored(self) -> dict[str, Any]:
        return {
            "aesthetics": list(self.aesthetics),
            "occasions": list(self.occasions),
            "dress_code": self.dress_code,
            "goal": self.goal,
        }


async def read_taste(session: AsyncSession, *, user_id: uuid.UUID) -> Taste:
    """What this person said, or nothing at all."""
    stored = await session.scalar(
        sa.select(Preference.value).where(
            Preference.user_id == user_id, Preference.key == TASTE_KEY
        )
    )
    return Taste.from_stored(stored)


async def write_taste(
    session: AsyncSession, *, user_id: uuid.UUID, taste: Taste
) -> Taste:
    """Record it. Idempotent, and overwrites rather than accumulating.

    Overwrite rather than merge, unlike the saved collection: this is one
    answer to one set of questions, and somebody who deselects an aesthetic
    means they no longer want it. Merging would make a choice impossible to
    take back, which is the same asymmetry consent deliberately avoids.
    """
    existing = await session.scalar(
        sa.select(Preference).where(
            Preference.user_id == user_id, Preference.key == TASTE_KEY
        )
    )
    if existing is None:
        session.add(
            Preference(user_id=user_id, key=TASTE_KEY, value=taste.as_stored())
        )
    else:
        existing.value = taste.as_stored()
    await session.commit()
    return taste


#: Which shelf each goal puts first. Shelf ids from the mobile taxonomy.
GOAL_TO_LENS: dict[str, str] = {
    "more_from_what_i_own": "formula",
    "what_to_wear_to": "occasion",
    "find_my_look": "aesthetic",
}

#: The order when nothing has been said.
DEFAULT_LENS_ORDER = ("occasion", "aesthetic", "formula")


def lens_order(taste: Taste) -> tuple[str, ...]:
    """Which order to show the Discover shelves in.

    The smallest useful thing a stated taste can do, and it is deliberately
    the first thing built on top of it: it needs no model call, no schedule
    and no cohort, so personalisation starts working the moment somebody
    answers rather than waiting for the rest of the system.
    """
    leading = GOAL_TO_LENS.get(taste.goal or "")
    if leading is None:
        return DEFAULT_LENS_ORDER
    return (leading, *(lens for lens in DEFAULT_LENS_ORDER if lens != leading))


__all__ = [
    "AESTHETICS",
    "DEFAULT_LENS_ORDER",
    "DRESS_CODES",
    "GOALS",
    "GOAL_TO_LENS",
    "MAX_CHOICES",
    "OCCASIONS",
    "TASTE_KEY",
    "Taste",
    "UnknownTaste",
    "lens_order",
    "read_taste",
    "write_taste",
]
