"""A picture of a garment nobody here owns, drawn once for everybody.

**The gap this fills.** The stylist can say "you'd need baggy skater
shorts, a white t-shirt and white sneakers", link all three, and show
nothing - because the figure beside it is composed from cut-outs, and
a cut-out only exists for a garment somebody has photographed. So the
one answer where seeing it would help most was the one answer with no
picture, and the reply read as a refusal dressed up as advice.

**Keyed on the words, and shared by everybody.** "white sneakers" is
the same request whoever asks it, so the row is keyed on the
normalised phrase rather than on a user. The first person to need a
piece pays for it once; everybody after them gets it instantly and
free. That is what makes showing the look affordable at all - the
alternative was a billed render per person per question, which is
precisely the cost this app has been removing.

**Not a claim about a product.** This is a generic picture of the
*kind* of garment named, not of any item in the shop links beside it.
The client says so. Nothing here is evidence that a particular seller
sells a particular thing.
"""

from __future__ import annotations

import re
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk

#: The longest phrase that will be drawn.
#:
#: A description, not a sentence. Past this the model is being asked
#: to illustrate a paragraph and returns a scene rather than a
#: garment, and the key stops being something a second person would
#: ever match.
MOST_WORDS = 10

#: How long a stored phrase may be, after normalising.
MAX_PHRASE = 120

_SPACE = re.compile(r"\s+")
_NOISE = re.compile(r"[^a-z0-9 ]+")


def phrase_key(words: str) -> str:
    """The shared key for a garment phrase.

    **The whole saving lives in this function.** "White Sneakers",
    "white sneakers" and "white  sneakers." have to land on one row,
    or the cache is a per-user cache with extra steps.

    Lowercased, stripped of punctuation, collapsed on whitespace, and
    capped at `MOST_WORDS`. Deliberately not stemmed and deliberately
    not reordered: "white shirt dress" and "white dress shirt" are
    different garments, and a normaliser that merged them would be
    silently serving the wrong picture - a worse failure than a miss.
    """
    lowered = _NOISE.sub(" ", (words or "").lower())
    return " ".join(_SPACE.sub(" ", lowered).strip().split()[:MOST_WORDS])[
        :MAX_PHRASE
    ]


class PiecePackshot(Base, TimestampMixin):
    """One garment phrase, and the picture drawn for it."""

    __tablename__ = "piece_packshots"

    id: Mapped[uuid.UUID] = uuid_pk()

    #: The normalised phrase. Unique: one picture per garment, for
    #: everybody.
    phrase: Mapped[str] = mapped_column(
        sa.String(MAX_PHRASE), nullable=False, unique=True, index=True
    )

    #: Where it goes on the figure - `tops`, `bottoms`, `shoes`,
    #: `outerwear`, `accessories`. Stored rather than re-derived so
    #: the composite does not have to guess from the words every time
    #: it draws.
    slot: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    #: `queued`, `ready` or `failed`. The client polls on this.
    state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default="queued", server_default="queued"
    )

    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    #: Why it failed, when it did. Shown to nobody; read when a phrase
    #: that should work does not.
    error: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)


__all__ = ["MAX_PHRASE", "MOST_WORDS", "PiecePackshot", "phrase_key"]
