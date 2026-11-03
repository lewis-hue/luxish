"""Which taste group a user falls into.

Exists so "how many people are like this one" is a `GROUP BY` rather than a
scan of every wardrobe in the system. It is a derived cache, rebuilt on a
schedule: nothing here is authoritative, and dropping the whole table costs
one recomputation.

**The key contains no garment and no person.** It is assembled from counts of
garment *categories* and a stated dress code — "owns tailoring and layering,
dresses business, medium wardrobe" — and never from a garment id, a
photograph, a name or anything a user wrote. That is the property that makes
it safe to share generated inspiration across a cohort, and it is a property
of the key's construction rather than of how carefully the next feature uses
it.

The membership floor lives in :mod:`app.domain.cohort`, not here. A row in
this table says which group somebody computed into; whether that group is
large enough to be treated as a group is a question asked at read time, so
raising the floor does not require rewriting the table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, uuid_fk, uuid_pk


class UserCohort(Base, TimestampMixin):
    __tablename__ = "user_cohorts"
    __table_args__ = (
        # One row per person. This is a current-state cache, not a history.
        sa.UniqueConstraint("user_id", name="uq_user_cohorts_user"),
        # The read is always "everybody in this cohort" or "how many are".
        sa.Index("ix_user_cohorts_key", "cohort_key"),
        # Every rung of the widening ladder reads a prefix of these three.
        sa.Index("ix_user_cohorts_parts", "owns_key", "size_band", "dress_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: The full signature, most specific. See `domain.cohort.cohort_key`.
    cohort_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)

    # The three parts, as columns rather than only inside `signature`.
    #
    # Counting a cohort means asking "how many people share these two of the
    # three parts", and doing that against a composed string needs prefix
    # matching that silently stops working the moment the dropped part is in
    # the middle — `owns|size` cannot LIKE-match `owns|dress|size`. Columns
    # make every rung of the widening ladder an ordinary WHERE.
    #: The owned-collections part, sorted and joined. "any" when nothing.
    owns_key: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    #: Stated dress code, or `unspecified`.
    dress_code: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    #: Wardrobe size band: none, small, medium, large.
    size_band: Mapped[str] = mapped_column(sa.String(16), nullable=False)

    #: The parts it was built from, so a key can be explained to the person
    #: it describes without re-deriving it. Categories and bands only.
    signature: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: When this was last computed, so a stale cache is visible rather than
    #: silently old.
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
