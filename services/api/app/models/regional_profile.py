"""Regional style profiles — a reviewed, versioned knowledge layer.

A profile records how people dress *in a place*: the occasions that have a
recognisable dress expectation, how the year is shaped there, worked styling
examples, and — mandatory, enforced by both validation and a CHECK constraint —
where the guidance came from and who reviewed it.

**Location is never used to infer who a person is.** There is no column here for
ethnicity, religion, income, or personal taste, and no code path derives one.
A place name tells you the climate and the local dress conventions; it tells you
nothing about an individual, and this table is shaped so that it cannot be made
to pretend otherwise.

**A profile is not a stereotype.** ``variants`` carries within-region variation
— alternative scenes, international and visiting styles, local sourcing idioms —
and the draft validator refuses a profile that has none.

**Disagreement is representable.** The unique constraint is
``(geography_key, source_slug, version)``, *not* ``(geography, occasion)``: two
reviewed sources may cover the same place and occasion with different advice and
both are kept. Versions chain through ``supersedes_id``, and a superseded row is
retired rather than deleted so a stored decision stays explainable.

This is retrieval plus deterministic constraints, not a trained model — regional
model training is Phase E (ADR-004 keeps Phase B retrieval deterministic).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, named_enum, uuid_pk

GRANULARITIES: tuple[str, ...] = ("city", "region", "country")

granularity_enum = named_enum("regional_granularity", *GRANULARITIES)

#: Finer granularity wins when more than one profile matches a place.
GRANULARITY_RANK: dict[str, int] = {"city": 0, "region": 1, "country": 2}


class RegionalStyleProfile(Base, TimestampMixin):
    __tablename__ = "regional_style_profiles"
    __table_args__ = (
        # One version per source per geography. Deliberately *not* unique on
        # (geography, occasion) — conflicting guidance is data, not an error.
        sa.UniqueConstraint(
            "geography_key",
            "source_slug",
            "version",
            name="uq_regional_style_profiles_geography_key_source_slug_version",
        ),
        sa.Index("ix_regional_style_profiles_geography_key", "geography_key"),
        sa.Index("ix_regional_style_profiles_country_key", "country_key"),
        # Provenance is a schema property, not a matter of application
        # diligence: an unattributed profile cannot exist even if a validator
        # were bypassed.
        sa.CheckConstraint("length(trim(source_provenance)) > 0", name="provenance_present"),
        sa.CheckConstraint("length(trim(reviewer)) > 0", name="reviewer_present"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    #: Display name of the place, as a human would write it.
    geography: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    #: Normalised lookup key for ``geography``. A *name*, never a coordinate.
    geography_key: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    #: Normalised key of the containing country, for coarse fallback.
    country_key: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    granularity: Mapped[str] = mapped_column(granularity_enum, nullable=False)
    #: Other names the same place is typed as.
    aliases: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )

    #: ``[{occasion, suggests[], avoid[], note}]`` — occasions with a
    #: recognisable local dress expectation.
    occasions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    #: ``[{name, months[], guidance, layers[], avoid[]}]``. Months are explicit
    #: because "winter" is not a hemisphere-independent fact, and an equatorial
    #: year is not four seasons at all.
    seasonality: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    styling_examples: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    #: ``[{kind, name, description, suggests[], note}]`` — within-region
    #: variation. A profile with none of this is a stereotype, so the draft
    #: validator requires at least one entry.
    variants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )

    #: Stable identifier for the reviewing lineage, so two sources that
    #: disagree stay distinguishable across versions.
    source_slug: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    #: How the guidance was assembled, in plain words. Mandatory.
    source_provenance: Mapped[str] = mapped_column(sa.Text, nullable=False)
    #: The reviewing **role**, place and month — never a personal name.
    reviewer: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    #: 0..1. Lower where the data is sparse or the geography is coarse.
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False)
    review_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=1, server_default=sa.text("1")
    )
    #: The row this one replaces, so versions chain.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("regional_style_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Set when a newer version takes over. Retired rows are kept, not deleted.
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Caveats worth showing the user alongside the guidance.
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    @property
    def is_current(self) -> bool:
        return self.retired_at is None

    @property
    def occasion_names(self) -> tuple[str, ...]:
        return tuple(
            str(entry["occasion"]) for entry in (self.occasions or []) if entry.get("occasion")
        )

    def covers(self, occasion: str | None) -> bool:
        if occasion is None:
            return True
        return occasion.strip().lower() in {name.lower() for name in self.occasion_names}

    @property
    def granularity_rank(self) -> int:
        return GRANULARITY_RANK.get(self.granularity, len(GRANULARITY_RANK))


__all__ = [
    "GRANULARITIES",
    "GRANULARITY_RANK",
    "RegionalStyleProfile",
    "granularity_enum",
]
