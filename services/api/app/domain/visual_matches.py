"""What a photographed search actually finds, and what to show instead.

**The reported gap.** Search by picture read the photograph, took the
strongest tag and jumped to that tag's page. When no tag matched it
said "Nothing to go on" in an alert and left the person where they
started - which is the worst possible answer to somebody who opened
a camera, framed a shot and waited nine seconds for it.

The instruction was specific: *"if there is no pin that has the palm
shown, the app can show results for pins that include accessories
worn on hands, or pins of people where hands are visible."* So there
are two answers here, and the second one is the point:

* **close** - pins actually tagged with what the reader saw. Exact,
  and often empty, because a tag only exists if somebody typed it.
* **loosely** - the nearest pins by what they are *of*, using the
  vision vectors Discover already ranks on. A photograph of rings on
  a hand reads as `jewellery`, and the nearest jewellery pins are the
  hand-accessory pins the instruction describes. No extra model call:
  the reading is already paid for and every pin's vector is stored.

Both are gated by the same visibility rules as the feed, through the
same helpers, because a search is not a way around a block.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.discovery.subject import (
    FACETS,
    SUBJECTS,
    Reading,
    nearest,
    vector_for,
)
from app.models.post_vision import PostVisionRow

#: Most pins returned, close and loose together.
MOST_MATCHES = 40

#: How alike a pin has to be to count as a loose match.
#:
#: Lower than the board's own floor. A person who photographed
#: something and waited is owed an attempt, and "here is the nearest
#: thing" is a better answer than an empty sheet - as long as it is
#: labelled, which the client does.
LOOSE_FLOOR = 0.15

#: Words in a read garment that place it in the subject vocabulary.
#:
#: **Derived from the words, not from a second model call.** The
#: reader has already named the pieces; asking a model again what
#: kind of thing they are would be paying twice for something the
#: nouns already say. Ordered most specific first - a "leather bag"
#: is a bag before it is leather.
_SUBJECT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "footwear",
        (
            "shoe", "shoes", "trainer", "sneaker", "boot", "loafer",
            "sandal", "heel", "mule", "brogue", "pump", "clog",
        ),
    ),
    (
        "jewellery",
        (
            "necklace", "pendant", "bracelet", "anklet", "earring", "ring",
            "chain", "brooch", "cufflink", "watch",
        ),
    ),
    (
        "bag",
        ("bag", "tote", "clutch", "backpack", "handbag", "purse", "satchel"),
    ),
    (
        "beauty",
        ("makeup", "lipstick", "nail", "manicure", "hair", "fragrance"),
    ),
)


def subject_of(pieces: list[str]) -> str:
    """Which kind of thing a photograph was read as.

    **The count decides first, and it has to.** Matching on words
    alone made "white poplin shirt, indigo jeans, brown loafers" read
    as `footwear`, because `loafers` is the only one of the three
    this table knows a word for - a whole outfit narrowed to the one
    garment it happened to recognise. More than one piece is a look,
    however it was framed.

    `outfit` is also the answer when nothing matches, and it is the
    safe default rather than the lazy one: it has the widest gate in
    `may_sit_under`, so a photograph we could not place still gets
    results instead of an empty sheet.
    """
    named = [piece for piece in pieces if piece.strip()]
    if len(named) != 1:
        return "outfit"
    said = named[0].lower()
    for subject, terms in _SUBJECT_WORDS:
        if any(term in said for term in terms):
            return subject if subject in SUBJECTS else "outfit"
    return "outfit"


def reading_from(*, pieces: list[str], tags: list[str]) -> Reading:
    """A query reading, built from words the reader already produced.

    `clean()` drops anything outside the vocabulary, which is what
    keeps an invented facet from creating a category of one.
    """
    said = {word.lower() for word in [*pieces, *tags]}
    return Reading(
        # The pieces only. A tag is a word somebody typed about the
        # whole photograph, so counting tags as pieces would make
        # every picture a multi-piece outfit.
        subject=subject_of(pieces),
        facets=tuple(facet for facet in FACETS if facet in said),
        presentation="unspecified",
        confidence=1.0,
    ).clean()


@dataclass(frozen=True)
class Matched:
    """Pins for one photographed search, in two bands."""

    #: Tagged with what the reader saw.
    close: list[uuid.UUID] = field(default_factory=list)
    #: The nearest pins by what they are of. Shown under their own
    #: heading, because presenting these as exact matches would be a
    #: claim the app cannot support.
    loosely: list[uuid.UUID] = field(default_factory=list)
    #: The subject the picture was read as, for the heading.
    subject: str = "outfit"


async def matches(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tags: list[str],
    pieces: list[str],
    limit: int = MOST_MATCHES,
) -> Matched:
    """Close matches, then the nearest things to them."""
    from app.domain import feed as feed_domain

    reading = reading_from(pieces=pieces, tags=tags)

    close: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for tag in tags[:3]:
        # Three, not all of them. Past the third the tags describe
        # the setting rather than the clothes, and the results stop
        # being about the photograph.
        try:
            found = await feed_domain.by_tag(db, user_id=user_id, tag=tag)
        except Exception:  # noqa: BLE001 - a missing tag is not a failure
            continue
        for entry in found:
            if entry.post.id in seen:
                continue
            seen.add(entry.post.id)
            close.append(entry.post.id)
        if len(close) >= limit:
            break

    loosely: list[uuid.UUID] = []
    if len(close) < limit:
        loosely = await _nearest_pins(
            db,
            user_id=user_id,
            reading=reading,
            skip=seen,
            limit=limit - len(close),
        )

    return Matched(
        close=close[:limit], loosely=loosely, subject=reading.subject
    )


async def _nearest_pins(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    reading: Reading,
    skip: set[uuid.UUID],
    limit: int,
) -> list[uuid.UUID]:
    """The most similar pins this person may see.

    A scan over the stored vectors rather than an index, for the
    reason `post_vision` gives: at this corpus size the cosine over a
    few hundred unit vectors is microseconds, and an index would be
    machinery with nothing to do.
    """
    from app.domain.moderation import hidden_either_way

    rows = (
        await db.execute(
            sa.select(
                PostVisionRow.post_id,
                PostVisionRow.subject,
                PostVisionRow.vector,
            )
        )
    ).all()
    if not rows:
        return []

    candidates = {
        str(post_id): (subject, list(vector or []))
        for post_id, subject, vector in rows
        if post_id not in skip and vector
    }
    ranked = nearest(
        viewing_subject=reading.subject,
        viewing_vector=vector_for(reading),
        candidates=candidates,
        limit=limit * 3,
        floor=LOOSE_FLOOR,
    )
    if not ranked:
        return []

    # **Visibility is applied after ranking and before the cap.**
    #
    # The vectors table knows nothing about blocks, private accounts
    # or deleted authors, and a search must not be a way around any
    # of them. Resolved through the feed's own query so there is one
    # answer to "may this person see this pin".
    from app.models.posts import Post
    from app.models.user import User

    wanted = [uuid.UUID(key) for key, _score in ranked]
    hidden = await hidden_either_way(db, user_id=user_id)
    query = (
        sa.select(Post.id)
        .join(User, User.id == Post.user_id)
        .where(
            Post.id.in_(wanted),
            Post.state == "published",
            Post.deleted_at.is_(None),
            User.deleted_at.is_(None),
        )
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    allowed = set((await db.scalars(query)).all())

    # Back into similarity order, which the id query lost.
    return [
        uuid.UUID(key) for key, _score in ranked if uuid.UUID(key) in allowed
    ][:limit]


__all__ = [
    "LOOSE_FLOOR",
    "MOST_MATCHES",
    "Matched",
    "matches",
    "reading_from",
    "subject_of",
]
