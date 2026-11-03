"""Inspiration generated for a cohort, with a window it is valid in.

One row serves everybody in a cohort, which is the whole cost argument: the
model bill grows with the number of distinct kinds of wardrobe rather than
with the number of users.

**Keyed by cohort, never by user**, and that is the privacy boundary made
structural. There is no `user_id` column here and there must never be one: a
row that belonged to a person could carry their wardrobe to the next person
in the group, and the only reliable way to prevent that is for the row to
have no idea who it is for. What it knows is a cohort key, which is built
from garment-category counts and a stated dress code and nothing else.

**A window rather than a timestamp.** The shelf refreshes twice a week, so
"which set is current" is a range check rather than a sort by recency: a set
generated early for next week must not become current the moment it is
written, and the previous set has to stay readable until its replacement is
actually valid so nobody sees an empty shelf during a regeneration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, uuid_pk


class CohortInspiration(Base, TimestampMixin):
    __tablename__ = "cohort_inspirations"
    __table_args__ = (
        # One set per cohort per window. Regenerating a window replaces it
        # rather than stacking, so a retried task cannot double the spend.
        sa.UniqueConstraint(
            "cohort_key", "valid_from", name="uq_cohort_inspirations_key_from"
        ),
        sa.Index("ix_cohort_inspirations_lookup", "cohort_key", "valid_until"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Which group this was made for. Deliberately the only identity here.
    cohort_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    #: The collection ids to show, in order. Bundled content, not garments.
    collections: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    #: One line saying why this set, shown so the shelf can explain itself
    #: instead of looking like a reshuffle.
    rationale: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
