"""Regional style context contracts.

Two jobs in one module.

*Ingest.* ``SeedDocument`` / ``RegionalProfileDraft`` are the validated shape a
reviewed profile must take before it reaches the database. Provenance and a
reviewer role are **required** — a profile missing either fails validation —
and so is at least one within-region variant, because a profile with no
variation is a stereotype.

*Response.* ``RegionalContextResponse`` is what ``GET /v1/regional/context``
returns: the matching profile set, each with its own provenance and confidence,
plus any disagreement between sources and the precedence the caller must apply.

It carries **no** weather and **no** retailer inventory. Those are separate
concerns with separate types (``app.providers.weather`` and Task 11), and the
whole point of keeping them apart is that a wrong answer can be attributed.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

if TYPE_CHECKING:  # pragma: no cover - typing only; avoids a domain/schema cycle
    from app.domain.regional import GeographicStyleContext

Granularity = Literal["city", "region", "country"]
VariantKind = Literal["mainstream", "alternative", "international", "practice"]
PlaceSourceLiteral = Literal["user_manual", "declined", "unspecified"]
Coverage = Literal["city", "region", "country", "none"]

#: A reviewer descriptor is a role, a place and a month — never a person.
Reviewer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=200)]
#: Long enough that "n/a" cannot pass for an account of where this came from.
Provenance = Annotated[str, StringConstraints(strip_whitespace=True, min_length=20)]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalise_key(value: str) -> str:
    """Lowercase, collapse separators: ``"Mombasa, Kenya"`` → ``mombasa-kenya``."""
    return _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #
class OccasionGuidanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    occasion: NonEmpty
    suggests: list[NonEmpty] = Field(min_length=1)
    avoid: list[NonEmpty] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=600)


class SeasonGuidanceIn(BaseModel):
    """A period of the local year, with its months stated explicitly.

    Months rather than a season name because "summer" is not a
    hemisphere-independent fact and an equatorial year has no four seasons.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmpty
    months: list[Annotated[int, Field(ge=1, le=12)]] = Field(min_length=1, max_length=12)
    guidance: NonEmpty
    layers: list[NonEmpty] = Field(default_factory=list)
    avoid: list[NonEmpty] = Field(default_factory=list)


class StyleVariantIn(BaseModel):
    """Within-region variation. At least one is required per profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: VariantKind
    name: NonEmpty
    description: NonEmpty
    suggests: list[NonEmpty] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=600)


class RegionalProfileDraft(BaseModel):
    """One reviewed profile, validated before it reaches the database."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geography: NonEmpty
    geography_key: str | None = None
    granularity: Granularity
    country_key: str | None = None
    aliases: list[NonEmpty] = Field(default_factory=list)

    occasions: list[OccasionGuidanceIn] = Field(min_length=1)
    seasonality: list[SeasonGuidanceIn] = Field(min_length=1)
    styling_examples: list[NonEmpty] = Field(min_length=1)
    #: Required. A profile with no within-region variation is a stereotype.
    variants: list[StyleVariantIn] = Field(min_length=1)

    source_slug: NonEmpty
    source_provenance: Provenance
    reviewer: Reviewer
    confidence: float = Field(ge=0.0, le=1.0)
    review_date: date
    version: int = Field(default=1, ge=1)
    #: The version of the same lineage this draft replaces, if any.
    supersedes_version: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def _derive_keys(cls, data: Any) -> Any:
        """Lookup keys are derived, never hand-typed inconsistently."""
        if not isinstance(data, dict):  # pragma: no cover - defensive
            return data
        derived = dict(data)
        geography = derived.get("geography")
        if not derived.get("geography_key") and isinstance(geography, str):
            derived["geography_key"] = normalise_key(geography)
        country = derived.get("country_key")
        if isinstance(country, str) and country:
            derived["country_key"] = normalise_key(country)
        return derived

    def row_kwargs(self) -> dict[str, Any]:
        """Column values for ``RegionalStyleProfile``."""
        return {
            "geography": self.geography,
            "geography_key": self.geography_key,
            "country_key": self.country_key,
            "granularity": self.granularity,
            "aliases": list(self.aliases),
            "occasions": [o.model_dump(mode="json") for o in self.occasions],
            "seasonality": [s.model_dump(mode="json") for s in self.seasonality],
            "styling_examples": list(self.styling_examples),
            "variants": [v.model_dump(mode="json") for v in self.variants],
            "source_slug": self.source_slug,
            "source_provenance": self.source_provenance,
            "reviewer": self.reviewer,
            "confidence": self.confidence,
            "review_date": self.review_date,
            "version": self.version,
            "notes": self.notes,
        }


class SeedProfileEntry(BaseModel):
    """A profile inside a seed document, which supplies the geography once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_slug: NonEmpty
    source_provenance: Provenance
    reviewer: Reviewer
    confidence: float = Field(ge=0.0, le=1.0)
    review_date: date
    version: int = Field(default=1, ge=1)
    supersedes_version: int | None = Field(default=None, ge=1)
    occasions: list[OccasionGuidanceIn] = Field(min_length=1)
    seasonality: list[SeasonGuidanceIn] = Field(min_length=1)
    styling_examples: list[NonEmpty] = Field(min_length=1)
    variants: list[StyleVariantIn] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2000)


class SeedDocument(BaseModel):
    """One YAML file: a place, and the profiles reviewed for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geography: NonEmpty
    geography_key: str | None = None
    granularity: Granularity
    country_key: str | None = None
    aliases: list[NonEmpty] = Field(default_factory=list)
    profiles: list[SeedProfileEntry] = Field(min_length=1)

    def drafts(self) -> list[RegionalProfileDraft]:
        return [
            RegionalProfileDraft(
                geography=self.geography,
                geography_key=self.geography_key,
                granularity=self.granularity,
                country_key=self.country_key,
                aliases=list(self.aliases),
                **entry.model_dump(),
            )
            for entry in self.profiles
        ]


# --------------------------------------------------------------------------- #
# response
# --------------------------------------------------------------------------- #
class ProvenanceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: uuid.UUID
    source_slug: str
    source_provenance: str
    reviewer: str
    confidence: float
    review_date: date
    version: int
    #: The profile version this one replaced, when there is one.
    supersedes: uuid.UUID | None = None


class OccasionGuidanceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    occasion: str
    suggests: list[str]
    avoid: list[str] = Field(default_factory=list)
    note: str | None = None


class SeasonGuidanceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    months: list[int]
    guidance: str
    layers: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class StyleVariantView(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    name: str
    description: str
    suggests: list[str] = Field(default_factory=list)
    note: str | None = None


class RegionalProfileView(BaseModel):
    model_config = ConfigDict(frozen=True)

    geography: str
    granularity: str
    season: str | None = None
    occasions: list[OccasionGuidanceView]
    seasonality: list[SeasonGuidanceView]
    styling_examples: list[str]
    variants: list[StyleVariantView]
    provenance: ProvenanceView
    notes: str | None = None


class GuidanceConflictView(BaseModel):
    """Two reviewed sources disagreeing. Reported, never silently resolved."""

    model_config = ConfigDict(frozen=True)

    occasion: str
    left_source: str
    right_source: str
    left_suggests: list[str]
    right_suggests: list[str]
    note: str


class RegionalContextResponse(BaseModel):
    """``GET /v1/regional/context?place=&date=&occasion=``.

    Geographic style context only. No weather, no inventory — see the module
    docstring.
    """

    model_config = ConfigDict(frozen=True)

    place: str | None
    place_source: PlaceSourceLiteral
    resolved_geography: str | None
    granularity: str | None
    coverage: Coverage
    as_of: date | None
    season: str | None
    occasion: str | None
    #: Highest confidence among the matched profiles; 0.0 when none matched.
    confidence: float
    #: Everything here is *guidance*. The caller applies this order.
    precedence: list[str]
    profiles: list[RegionalProfileView]
    conflicts: list[GuidanceConflictView]
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def from_context(cls, context: GeographicStyleContext) -> RegionalContextResponse:
        return cls(
            place=context.place,
            place_source=context.place_source,
            resolved_geography=context.resolved_geography,
            granularity=context.granularity,
            coverage=context.coverage,
            as_of=context.as_of,
            season=context.season,
            occasion=context.occasion,
            confidence=context.confidence,
            precedence=list(context.precedence),
            profiles=[
                RegionalProfileView(
                    geography=profile.geography,
                    granularity=profile.granularity,
                    season=profile.season,
                    occasions=[
                        OccasionGuidanceView(
                            occasion=o.occasion,
                            suggests=list(o.suggests),
                            avoid=list(o.avoid),
                            note=o.note,
                        )
                        for o in profile.occasions
                    ],
                    seasonality=[
                        SeasonGuidanceView(
                            name=s.name,
                            months=list(s.months),
                            guidance=s.guidance,
                            layers=list(s.layers),
                            avoid=list(s.avoid),
                        )
                        for s in profile.seasonality
                    ],
                    styling_examples=list(profile.styling_examples),
                    variants=[
                        StyleVariantView(
                            kind=v.kind,
                            name=v.name,
                            description=v.description,
                            suggests=list(v.suggests),
                            note=v.note,
                        )
                        for v in profile.variants
                    ],
                    provenance=ProvenanceView(
                        profile_id=profile.provenance.profile_id,
                        source_slug=profile.provenance.source_slug,
                        source_provenance=profile.provenance.source_provenance,
                        reviewer=profile.provenance.reviewer,
                        confidence=profile.provenance.confidence,
                        review_date=profile.provenance.review_date,
                        version=profile.provenance.version,
                        supersedes=profile.provenance.supersedes,
                    ),
                    notes=profile.notes,
                )
                for profile in context.profiles
            ],
            conflicts=[
                GuidanceConflictView(
                    occasion=conflict.occasion,
                    left_source=conflict.left_source,
                    right_source=conflict.right_source,
                    left_suggests=list(conflict.left_suggests),
                    right_suggests=list(conflict.right_suggests),
                    note=conflict.note,
                )
                for conflict in context.conflicts
            ],
            notes=list(context.notes),
        )


__all__ = [
    "Coverage",
    "Granularity",
    "GuidanceConflictView",
    "OccasionGuidanceIn",
    "OccasionGuidanceView",
    "ProvenanceView",
    "RegionalContextResponse",
    "RegionalProfileDraft",
    "RegionalProfileView",
    "SeasonGuidanceIn",
    "SeasonGuidanceView",
    "SeedDocument",
    "SeedProfileEntry",
    "StyleVariantIn",
    "StyleVariantView",
    "VariantKind",
    "normalise_key",
]
