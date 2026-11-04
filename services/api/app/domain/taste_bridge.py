"""Turning what somebody said they like into pins that exist.

**Three vocabularies, and none of them agreed.** Onboarding asks in
one language (`AESTHETICS`, `OCCASIONS`), the board groups pins in a
second (`feed.GROUP_TAGS`), and authors tag in a third. Measured
against the 633 published pins:

* three aesthetics reached no group at all - `downtown-romantic`,
  `dark-academia`, `blokecore`;
* ten occasions reached no group - `travel`, `holiday`, `brunch`,
  `dinner`, `interview`, `funeral`, `place-of-worship`, `beach`,
  `rainy-day`, `cold-weather`;
* and occasions were never consulted for retrieval **at all**. They
  were asked for, stored, and read by nothing.

So the most specific question in onboarding - "where you actually
need outfits" - changed nothing about what anybody saw, and a third
of the aesthetics led to an empty shelf.

**Why a map and not a retagging.** The pins carry the right content;
they carry it under the words authors and the vision pass actually
use - `ootd` on 317 of them, `cocktail` on 45, `workwear` on 44.
Rewriting 633 posts to match an onboarding vocabulary would be
editing what people wrote to suit a form. Rewriting the form to drop
`funeral` would be worse: somebody genuinely needs that outfit, and
the answer is real signal even when no pin is tagged for it. A map
keeps both sides honest and has one place to change.

**It bridges to groups, not to tags.** `feed.GROUP_TAGS` already
collapses the long tail of real tags into thirteen groups, every one
of which has pins. Pointing at a group means a taste answer lands on
a shelf with something on it, which is the whole point.

Each mapping below is a judgement, and the ones that are a stretch
say so.
"""

from __future__ import annotations

from app.domain.taste import AESTHETICS, OCCASIONS

#: What each aesthetic is, in the board's own groups.
#:
#: Several share a group deliberately: `quiet-luxury`, `clean-girl`,
#: `minimalist` and `monochrome` are four names for a shelf of pared
#: back clothes, and splitting them four ways would give each a
#: thinner board than the one shelf they all describe.
AESTHETIC_GROUPS: dict[str, tuple[str, ...]] = {
    "streetwear": ("streetwear",),
    "quiet-luxury": ("minimal",),
    "clean-girl": ("minimal",),
    # Lace, softness, a bow. The smallest group at eight pins, and
    # the honest home for it: the alternative was nothing.
    "downtown-romantic": ("romantic",),
    # Tweed, archive tailoring, a library. `vintage` carries the
    # second-hand and archive tags, which is where these pins are.
    "dark-academia": ("vintage", "office"),
    "gorpcore": ("outdoors",),
    # Terrace wear: a football shirt and jeans. Adjacent to
    # streetwear here rather than a group of its own, because a
    # group of its own would have no pins in it.
    "blokecore": ("streetwear", "denim"),
    "y2k": ("streetwear",),
    "minimalist": ("minimal",),
    "monochrome": ("minimal",),
    "heritage": ("heritage",),
    "modest": ("modest",),
}

#: Where each occasion's clothes live.
#:
#: **These were the ten that reached nothing.** Each is mapped to the
#: shelf somebody dressing for it would actually want, which is not
#: always the obvious word:
#:
#: * `funeral` goes to `office`, because that group is this app's
#:   tailoring and sober formality. Nobody tags a pin `funeral`, and
#:   somebody dressing for one is looking at exactly those clothes.
#: * `place-of-worship` goes to `modest`, which is the one mapping
#:   here that is not a compromise.
#: * `beach`, `holiday` and `brunch` go to `casual` for want of a
#:   warm-weather group. If the board ever grows one, they move.
OCCASION_GROUPS: dict[str, tuple[str, ...]] = {
    "everyday": ("casual",),
    "office": ("office",),
    "evening": ("evening",),
    "date-night": ("evening",),
    "weekend": ("casual",),
    "wedding-guest": ("occasion", "evening"),
    "party": ("occasion", "evening"),
    "festival": ("occasion", "streetwear"),
    "travel": ("casual", "outdoors"),
    "holiday": ("casual",),
    "brunch": ("casual",),
    "dinner": ("evening",),
    "interview": ("office",),
    "graduation": ("occasion",),
    "funeral": ("office",),
    "place-of-worship": ("modest",),
    "gym": ("workout",),
    "outdoors": ("outdoors",),
    "beach": ("casual",),
    "rainy-day": ("outdoors",),
    "cold-weather": ("outdoors",),
    "loungewear": ("casual",),
}


def groups_for(
    *, aesthetics: tuple[str, ...] = (), occasions: tuple[str, ...] = ()
) -> set[str]:
    """Every board group this person's answers point at.

    A set, because two answers landing on one shelf is one shelf and
    not a stronger preference for it: somebody who picked
    `minimalist` and `monochrome` has described one taste twice.

    Unknown values are ignored rather than raised on. A vocabulary
    entry retired in a later release must not make somebody's stored
    profile unreadable - the same rule `Taste.from_stored` follows.
    """
    found: set[str] = set()
    for one in aesthetics:
        found.update(AESTHETIC_GROUPS.get(one, ()))
    for one in occasions:
        found.update(OCCASION_GROUPS.get(one, ()))
    return found


def unmapped() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Vocabulary entries that reach no group. Both should be empty.

    Exported so a test can say which one broke rather than only that
    something did, and so adding a word to either vocabulary without
    giving it a home fails loudly instead of quietly producing an
    empty shelf.
    """
    return (
        tuple(a for a in AESTHETICS if not AESTHETIC_GROUPS.get(a)),
        tuple(o for o in OCCASIONS if not OCCASION_GROUPS.get(o)),
    )


__all__ = [
    "AESTHETIC_GROUPS",
    "OCCASION_GROUPS",
    "groups_for",
    "unmapped",
]
