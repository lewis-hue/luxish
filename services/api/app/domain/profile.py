"""What we know about somebody's taste, from the three things that say it.

Three signals, and they disagree. That disagreement is the whole design
problem, so the rule is written here rather than discovered per feature:

* **Stated** (`domain.taste`) — what they answered. Asked, never inferred,
  and it does not decay. It is all a brand-new account has.
* **Owned** (`garments`) — what is actually in their wardrobe. Ground truth
  about what they *can* wear, and silent about what they want to.
* **Reached for** (`post_saves`, `post_reactions`) — the fits they keep and
  react to, scored per hashtag, weighted and decayed. Aspiration, and silent
  about whether they own any of it.

**Which one leads depends on the shelf, and that is not arbitrary.** Somebody
whose wardrobe is entirely workwear and who only ever opens festival looks is
telling you two different true things; a profile that averages them serves
neither.

* *How to wear what you own* — **owned leads**. The shelf is literally about
  their clothes, and suggesting layering to somebody with no layers is a
  shelf about somebody else.
* *What they are drawn to* — **reached-for leads**, with stated as the seed
  on day one.
  Aspiration is the point; a wardrobe of plain basics does not mean somebody
  wants a shelf of plain basics.
* *Where you are going* — **stated leads**. They answered where they need
  outfits; nothing inferred beats being told.

**Nothing here is a claim about a person.** These are counts of garment
categories and tallies of taps. No part of this reads identity, body or
demographics off a wardrobe, and the vocabularies are the closed ones the rest
of the service already uses so nothing new can be invented here.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.garment_media import CATEGORY_SLOT, SLOTS
from app.domain.taste import Taste, read_taste
from app.domain.ranking import WEIGHTS, WINDOW_DAYS, decay
from app.models.garment import Garment
from app.models.posts import PostSave

#: How many garments in a category before it counts as something they *have*.
#:
#: One pair of jeans is not a denim wardrobe, and building a denim shelf for
#: somebody who owns one pair is the kind of personalisation that reads as a
#: guess. Two is the smallest number that is a pattern rather than an item.
OWNS_THRESHOLD = 2

#: A slot with fewer than this is a gap worth naming.
#:
#: Not zero: somebody with one pair of shoes has a shoe gap in every practical
#: sense, and a profile that only notices empty slots misses it.
GAP_THRESHOLD = 2

#: Formula collections, and what owning says about each.
#:
#: Ids from the mobile taxonomy, so a match maps straight onto a shelf. The
#: rule is deliberately legible rather than learned: each entry says which
#: garment categories make that collection worth showing somebody, and anybody
#: can check whether it is true of their own wardrobe.
FORMULA_EVIDENCE: dict[str, tuple[str, ...]] = {
    "denim": ("jeans",),
    "tailoring": ("blazer", "trousers"),
    "layering": ("knitwear", "jacket", "coat", "shirt"),
    "athleisure": ("sweatshirt", "shoes"),
    "utility": ("jacket", "trousers"),
    "colour": (),  # applies to anybody; ranked last by evidence count
    "capsule": (),  # the fallback, and the right answer for a small wardrobe
}

#: At or under this many garments, `capsule` leads whatever else is owned.
#:
#: Twelve pieces of pure tailoring and twelve pieces of nothing in particular
#: have the same most-useful answer: how to get more outfits out of few
#: clothes. Concentration only becomes the more interesting fact once there
#: is enough of a wardrobe for the gaps to stop dominating.
CAPSULE_CEILING = 12

#: Where the two collections that fit anybody sit when they are not leading.
#:
#: Below one met category, so a real match always outranks them, and above
#: nothing, so they still appear rather than leaving a short shelf.
GENERAL_SCORE = 0.3


@dataclass(frozen=True, slots=True)
class Profile:
    """The three signals, side by side rather than averaged."""

    stated: Taste
    #: Garment category -> how many they own. Only categories they have.
    owns: dict[str, int] = field(default_factory=dict)
    #: Slot -> how many. Every slot present, including the empty ones.
    slots: dict[str, int] = field(default_factory=dict)
    #: Aesthetic -> decayed weight, from what they reached for.
    reaches_for: dict[str, float] = field(default_factory=dict)

    @property
    def wardrobe_size(self) -> int:
        return sum(self.owns.values())

    @property
    def gaps(self) -> tuple[str, ...]:
        """Slots with too little in them to build an outfit from."""
        return tuple(
            slot for slot in SLOTS if self.slots.get(slot, 0) < GAP_THRESHOLD
        )

    def has(self, category: str) -> bool:
        return self.owns.get(category, 0) >= OWNS_THRESHOLD


async def _owned(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[dict[str, int], dict[str, int]]:
    """What is in the wardrobe, by category and by slot.

    Deleted garments are excluded, and so are unavailable ones: something in
    the wash or lent out is still owned, but something marked gone is not, and
    a profile built on clothes somebody no longer has recommends outfits they
    cannot make.
    """
    rows = (
        await session.execute(
            sa.select(Garment.category, sa.func.count())
            .where(
                Garment.user_id == user_id,
                Garment.deleted_at.is_(None),
                Garment.category.is_not(None),
            )
            .group_by(Garment.category)
        )
    ).all()

    owns: dict[str, int] = {}
    slots: dict[str, int] = {slot: 0 for slot in SLOTS}
    for category, count in rows:
        owns[category] = int(count)
        slot = CATEGORY_SLOT.get(category)
        if slot in slots:
            slots[slot] += int(count)
    return owns, slots


async def _reached_for(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime
) -> dict[str, float]:
    """What they keep and react to, weighted by intent and decayed by age.

    The same weights and half-life every other claim about attention
    uses, deliberately: two different notions of "what this person is
    into" in one service would disagree visibly, on two screens, about
    the same taps.

    Counted per hashtag rather than per fit, because a profile is about
    what somebody is drawn to rather than which particular photograph
    they opened. The author's own tags are the evidence - what the
    clothes are, in the words of the person who wore them.

    It used to count taps against a catalogue of curated looks. The
    catalogue is gone; a kept fit is the thing people actually act on,
    and it is a stronger signal than a view ever was.
    """
    from app.models.profile import PostReaction, PostTag

    cutoff = now - timedelta(days=WINDOW_DAYS)
    scores: Counter[str] = Counter()

    # Two queries rather than a union: the kinds carry different
    # weights, and a union would have to invent a column to say which
    # row came from where.
    for model, kind in ((PostSave, "save"), (PostReaction, "reaction")):
        weight = WEIGHTS.get(kind, 0.0)
        if not weight:
            continue
        rows = (
            await session.execute(
                sa.select(PostTag.tag, model.created_at)
                .join(PostTag, PostTag.post_id == model.post_id)
                .where(model.user_id == user_id, model.created_at >= cutoff)
            )
        ).all()
        for tag, at in rows:
            when = at if at.tzinfo else at.replace(tzinfo=UTC)
            scores[tag] += weight * decay(when, now)

    return dict(scores)


async def reaches_for(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> dict[str, float]:
    """What this person keeps reaching for, by hashtag.

    The same signal the stylist reads, exposed on its own so a feed can
    rank by it without building a whole profile - which would also go
    and count their wardrobe, and a shelf of ideas has no use for that.

    Scores are decayed weights, not counts: comparable with each other
    and meaningless on their own.
    """
    return await _reached_for(
        session, user_id=user_id, now=now or datetime.now(UTC)
    )


async def build_profile(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> Profile:
    """Gather all three signals. Cheap: three queries, no model call."""
    moment = now or datetime.now(UTC)
    owns, slots = await _owned(session, user_id=user_id)
    return Profile(
        stated=await read_taste(session, user_id=user_id),
        owns=owns,
        slots=slots,
        reaches_for=await _reached_for(session, user_id=user_id, now=moment),
    )


def formula_focus(profile: Profile, *, limit: int = 4) -> tuple[str, ...]:
    """Which "how to wear what you own" collections fit this wardrobe.

    **Owned leads here**, per the rule at the top of this module. Ranked by
    how much of the evidence a wardrobe actually satisfies, so somebody with
    three pairs of jeans and no blazer gets denim before tailoring.

    Returns the general order for an empty wardrobe rather than an empty
    tuple: a shelf that disappears because somebody has not photographed
    anything yet is worse than a general shelf honestly labelled.
    """
    if profile.wardrobe_size == 0:
        return tuple(FORMULA_EVIDENCE)[:limit]

    # A small wardrobe has one most-useful answer, and ranking its two
    # jackets is not it.
    if profile.wardrobe_size <= CAPSULE_CEILING:
        rest = [name for name in FORMULA_EVIDENCE if name != "capsule"]
        return ("capsule", *_by_evidence(profile, rest))[:limit]

    return _by_evidence(profile, list(FORMULA_EVIDENCE))[:limit]


def _by_evidence(profile: Profile, collections: list[str]) -> tuple[str, ...]:
    """Rank by how many evidence categories a wardrobe actually satisfies.

    **Count, not fraction**, and the difference matters more than it looks.
    `denim` rests on one category and `layering` on four, so a fraction makes
    one pair of jeans a *perfect* denim match that outranks a wardrobe with
    knitwear and a jacket in it. Counting met categories ranks by how much of
    somebody's wardrobe a shelf is actually about, which is the question. The
    fraction survives only as a tiebreak, so a complete small match edges out
    an equally deep partial one.
    """
    scored: list[tuple[float, str]] = []
    for collection in collections:
        evidence = FORMULA_EVIDENCE.get(collection, ())
        if not evidence:
            scored.append((GENERAL_SCORE, collection))
            continue
        met = sum(1 for category in evidence if profile.has(category))
        if not met:
            continue
        scored.append((met + (met / len(evidence)) * 0.1, collection))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return tuple(collection for _, collection in scored)


def aesthetic_focus(profile: Profile, *, limit: int = 6) -> tuple[str, ...]:
    """Which aesthetics to lead "the look" with.

    **Reached-for leads here**, with stated as the seed. A brand-new account
    has no taps, so without the stated answers this returns nothing on the
    one day it most needs to return something; once taps accumulate they are
    what moves the ranking, because a stated answer is from sign-up and does
    not decay.

    Stated answers are kept in the result even once taps exist, rather than
    being out-ranked away: somebody who said they like quiet luxury and has
    not tapped it yet has told us something, and dropping it would make
    answering the question look like it did nothing.
    """
    ranked = sorted(
        profile.reaches_for.items(), key=lambda row: (-row[1], row[0])
    )
    out: list[str] = []
    for aesthetic in profile.stated.aesthetics:
        if aesthetic not in out:
            out.append(aesthetic)
    for aesthetic, _ in ranked:
        if aesthetic not in out:
            out.append(aesthetic)
    return tuple(out[:limit])


__all__ = [
    "CAPSULE_CEILING",
    "FORMULA_EVIDENCE",
    "GENERAL_SCORE",
    "GAP_THRESHOLD",
    "OWNS_THRESHOLD",
    "Profile",
    "aesthetic_focus",
    "build_profile",
    "formula_focus",
]
