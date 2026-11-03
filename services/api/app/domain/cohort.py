"""Grouping people by what they own, so inspiration can be generated once.

The cost problem this solves: generating fresh inspiration per user per week
is a per-user model bill that grows linearly with sign-ups. Users with similar
wardrobes can be served the same generated set, so the bill grows with the
number of *distinct kinds of wardrobe* instead — a number that flattens.

**A signature, not a clustering algorithm.** No k-means, no embeddings, no
training. The key is assembled from facts already computed in
:mod:`app.domain.profile`, which makes it deterministic (the same wardrobe
always lands in the same group), stable (a new sign-up never relabels
everybody else), explainable in one sentence to the person it describes, and
auditable — anybody can check that their own key is true of their own
wardrobe. A learned clustering would be better at finding structure nobody
anticipated and worse at every one of those.

**The privacy property is structural.** A key is built from garment
*category* counts and a stated dress code. No garment id, no photograph, no
cut-out, no name, nothing a user typed. That is what makes it safe to share
generated content across a cohort: there is nothing in the key that could
carry one person's wardrobe to another, so a downstream feature cannot leak
one by using this carelessly. Anything generated for a cohort must be
conditioned on the key alone — never on a member's specific items — and that
rule is only enforceable because the key is the whole of what a cohort knows.

**A cohort of one is not a cohort.** Below :data:`MIN_COHORT_SIZE` the key is
widened rather than used, for the reason trending has a distinct-user floor:
a group of one is that person's wardrobe with a label on it, and generating
"for their cohort" would be generating for them while implying otherwise. The
ladder ends at a key everybody shares, so there is always an answer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.profile import Profile, build_profile, formula_focus
from app.models.user import User
from app.models.user_cohort import UserCohort

#: How many people a cohort needs before it may be treated as one.
#:
#: Three, matching trending's distinct-user floor. The reasoning is the same
#: and so should the number be: two services in one product disagreeing about
#: how many people constitute "people" would be visible and indefensible.
MIN_COHORT_SIZE = 3

#: How many owned-collections go into the key.
#:
#: Two. One is too coarse to be a taste and four splits the population into
#: groups too small to clear the floor, which defeats the whole point — every
#: key that has to be widened is a key that bought nothing.
SIGNATURE_DEPTH = 2

#: Wardrobe size bands. Named rather than numeric so a key stays legible.
#:
#: The boundaries are where advice genuinely changes: under 13 the useful
#: answer is how to get more outfits from few pieces, over 40 it is how to
#: find anything.
SIZE_BANDS: tuple[tuple[int, str], ...] = (
    (0, "none"),
    (1, "small"),
    (13, "medium"),
    (41, "large"),
)

#: The key everybody shares, and the bottom of the widening ladder.
EVERYONE = "everyone"


def size_band(count: int) -> str:
    band = "none"
    for floor, name in SIZE_BANDS:
        if count >= floor:
            band = name
    return band


@dataclass(frozen=True, slots=True)
class Signature:
    """The parts of a key, kept so it can be explained rather than re-derived."""

    owns: tuple[str, ...]
    dress_code: str
    size: str

    def as_stored(self) -> dict[str, object]:
        return {
            "owns": list(self.owns),
            "dress_code": self.dress_code,
            "size": self.size,
        }


def signature_of(profile: Profile) -> Signature:
    """What this wardrobe is, in the only terms a cohort is allowed to know.

    `formula_focus` is reused rather than reimplemented so a cohort cannot
    drift from the shelf it exists to populate: if the two disagreed about
    what somebody owns, the generated set would be for a group they are not
    really in.
    """
    return Signature(
        owns=tuple(sorted(formula_focus(profile, limit=SIGNATURE_DEPTH))),
        dress_code=profile.stated.dress_code,
        size=size_band(profile.wardrobe_size),
    )


def cohort_key(signature: Signature) -> str:
    """The most specific key, for display and for storage.

    Sorted components, so the same wardrobe never produces two keys depending
    on the order anything came back in.
    """
    owns = "+".join(signature.owns) or "any"
    return f"{owns}|{signature.dress_code}|{signature.size}"


#: The widening ladder, most specific first.
#:
#: Each rung names which parts of the signature still have to match. Dress
#: code is dropped first because it is the one somebody may simply never have
#: answered, so it is the part most likely to be splitting a group for no real
#: reason. Wardrobe contents is dropped last because it is the part the shelf
#: is actually about.
LADDER: tuple[tuple[str, ...], ...] = (
    ("owns", "dress_code", "size"),
    ("owns", "size"),
    ("owns",),
    (),  # everyone
)


@dataclass(frozen=True, slots=True)
class Cohort:
    """A resolved group: the key actually used, and how many people share it."""

    key: str
    members: int
    #: Which rung of the ladder answered, so a caller can tell a precise
    #: cohort from the general fallback.
    level: int
    #: The full key before widening, so a caller can say what was asked for
    #: as well as what was answered.
    requested: str

    @property
    def widened(self) -> bool:
        return self.level > 0

    @property
    def general(self) -> bool:
        """The bottom rung: everybody. Content for this is a general shelf."""
        return self.level >= len(LADDER) - 1


def key_at(signature: Signature, level: int) -> str:
    """The key for one rung of the ladder."""
    parts = LADDER[level]
    if not parts:
        return EVERYONE
    owns = "+".join(signature.owns) or "any"
    pieces = []
    if "owns" in parts:
        pieces.append(owns)
    if "dress_code" in parts:
        pieces.append(signature.dress_code)
    if "size" in parts:
        pieces.append(signature.size)
    return "|".join(pieces)


async def assign(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> UserCohort:
    """Compute and store this person's key. Idempotent."""
    moment = now or datetime.now(UTC)
    profile = await build_profile(session, user_id=user_id, now=moment)
    signature = signature_of(profile)
    key = cohort_key(signature)

    existing = await session.scalar(
        sa.select(UserCohort).where(UserCohort.user_id == user_id)
    )
    if existing is None:
        existing = UserCohort(
            user_id=user_id,
            cohort_key=key,
            owns_key="+".join(signature.owns) or "any",
            dress_code=signature.dress_code,
            size_band=signature.size,
            signature=signature.as_stored(),
            computed_at=moment,
        )
        session.add(existing)
    else:
        existing.cohort_key = key
        existing.owns_key = "+".join(signature.owns) or "any"
        existing.dress_code = signature.dress_code
        existing.size_band = signature.size
        existing.signature = signature.as_stored()
        existing.computed_at = moment
    await session.commit()
    await session.refresh(existing)
    return existing


async def _members(session: AsyncSession, row: UserCohort, level: int) -> int:
    """How many people match this row's signature at this rung.

    Ordinary equality on columns. The composed `cohort_key` is for display
    and for an exact-match index; it is deliberately not what membership is
    counted from, because counting a *prefix* of a composed string breaks the
    moment the dropped part is in the middle.
    """
    parts = LADDER[level]
    query = sa.select(sa.func.count()).select_from(UserCohort)
    if "owns" in parts:
        query = query.where(UserCohort.owns_key == row.owns_key)
    if "dress_code" in parts:
        query = query.where(UserCohort.dress_code == row.dress_code)
    if "size" in parts:
        query = query.where(UserCohort.size_band == row.size_band)
    return int(await session.scalar(query) or 0)


async def resolve(session: AsyncSession, *, user_id: uuid.UUID) -> Cohort:
    """The most specific group this person shares with enough other people.

    Widens until the floor is met, and the ladder bottoms out at a key
    everybody shares, so this always returns something. A widened cohort is
    marked as such: content generated for `everyone` is a general shelf and
    has to be labelled as one rather than presented as somebody's own.
    """
    row = await session.scalar(
        sa.select(UserCohort).where(UserCohort.user_id == user_id)
    )
    if row is None:
        row = await assign(session, user_id=user_id)

    signature = Signature(
        owns=tuple(row.signature.get("owns", ())),
        dress_code=row.dress_code,
        size=row.size_band,
    )
    for level in range(len(LADDER)):
        members = await _members(session, row, level)
        if members >= MIN_COHORT_SIZE or level == len(LADDER) - 1:
            return Cohort(
                key=key_at(signature, level),
                members=members,
                level=level,
                requested=row.cohort_key,
            )
    # Unreachable: the last rung always returns above.
    raise AssertionError("the widening ladder did not terminate")


async def recompute_all(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Rebuild every key. Returns how many were computed.

    Wardrobes change constantly and nothing recomputes a key when a garment
    is added, deliberately: a cohort that shifted on every upload would churn
    the generated sets it exists to let us reuse. Periodic is the right
    cadence for a cache whose whole value is being shared.
    """
    moment = now or datetime.now(UTC)
    ids: Sequence[uuid.UUID] = (
        await session.scalars(sa.select(User.id).where(User.deleted_at.is_(None)))
    ).all()
    for user_id in ids:
        await assign(session, user_id=user_id, now=moment)
    return len(ids)


__all__ = [
    "EVERYONE",
    "MIN_COHORT_SIZE",
    "SIGNATURE_DEPTH",
    "SIZE_BANDS",
    "LADDER",
    "Cohort",
    "Signature",
    "assign",
    "cohort_key",
    "key_at",
    "recompute_all",
    "resolve",
    "signature_of",
    "size_band",
]
