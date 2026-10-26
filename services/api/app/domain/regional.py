"""Regional style context, and the precedence the user always wins.

**Location is never used to infer who a person is.** Not ethnicity, not
religion, not income, not personal taste. A place name supports exactly two
inferences — what the local climate does across the year, and what the local
dress conventions for a named occasion are — and both are sourced, reviewed and
versioned so they can be argued with. ``assert_no_demographic_inference``
refuses any profile that tries to key guidance on who somebody is, and the only
geographic input this module accepts is a *name*: no coordinate reaches here,
and none is stored.

**Three concerns, three types.** This module owns geographic style context and
nothing else. Live weather is the weather provider module; retailer stock is
Task 11. ``GeographicStyleContext`` has no field for either, and this module
imports neither — which is the cheapest way to keep that true.

**The user outranks the region.** Regional patterns are *contextual guidance*.
``apply_precedence`` is a pure function implementing
``hard_constraint > preference > regional_guidance``: a hard constraint or an
explicit preference always wins, every dropped regional suggestion is recorded
with the directive that beat it, and re-running the function cannot let the
region creep back in.

**Plurality is preserved.** Two reviewed sources may cover the same place and
occasion with different advice. Both are returned with their own provenance and
confidence, and the disagreement is reported as a ``GuidanceConflict`` rather
than being flattened into one winner. Guidance is retrieval plus deterministic
constraints — not a trained model (regional training is Phase E).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.errors import ApiError
from app.models.preference import Preference
from app.models.regional_profile import GRANULARITY_RANK, RegionalStyleProfile
from app.schemas.regional import RegionalProfileDraft, SeedDocument, normalise_key

#: Reviewed seed data lives beside the service, not in the database image.
SEED_DIR: Path = Path(__file__).resolve().parents[2] / "data" / "regional" / "seed"

#: The order in which guidance is applied. Stated, not implied.
PRECEDENCE: tuple[str, ...] = ("hard_constraint", "preference", "regional_guidance")

#: How a place reached us. There is deliberately **no** device-fix source: this
#: layer accepts a place *name* only, so a coarse device location would have to
#: be reverse-geocoded to a name before it ever got here, and declining is a
#: first-class state rather than an error.
PlaceSource = Literal["user_manual", "declined", "unspecified"]
PLACE_SOURCES: tuple[str, ...] = ("user_manual", "declined", "unspecified")

DirectiveKind = Literal["hard_constraint", "preference"]
DirectiveRule = Literal["exclude", "require", "prefer"]

#: Key tokens that would turn a place into a claim about a person. Refused.
FORBIDDEN_INFERENCE_TOKENS: frozenset[str] = frozenset(
    {
        "ethnicity",
        "ethnicities",
        "ethnic",
        "ethnicity_group",
        "race",
        "racial",
        "religion",
        "religions",
        "religious",
        "faith",
        "denomination",
        "income",
        "incomes",
        "salary",
        "earnings",
        "wealth",
        "affluence",
        "affluent",
        "class",
        "caste",
        "tribe",
        "tribal",
        "taste",
        "tastes",
        "demographic",
        "demographics",
        "nationality",
        "citizenship",
    }
)

#: Preference keys this layer understands, and what each one means.
PREFERENCE_RULES: dict[str, DirectiveRule] = {
    "never_wears": "exclude",
    "avoids": "exclude",
    "must_include": "require",
    "always_wears": "require",
    "prefers": "prefer",
}


class ProfileValidationError(ApiError):
    status_code = 422
    code = "invalid_regional_profile"
    default_message = "That regional profile cannot be stored."


# --------------------------------------------------------------------------- #
# value types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Provenance:
    """Where one profile's guidance came from, and how much to trust it."""

    profile_id: uuid.UUID
    source_slug: str
    source_provenance: str
    reviewer: str
    confidence: float
    review_date: date_type
    version: int
    supersedes: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class OccasionGuidance:
    occasion: str
    suggests: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SeasonGuidance:
    name: str
    months: tuple[int, ...]
    guidance: str
    layers: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StyleVariant:
    """Within-region variation — alternative, international, local practice."""

    kind: str
    name: str
    description: str
    suggests: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileGuidance:
    """One reviewed profile, read for a particular date."""

    geography: str
    granularity: str
    occasions: tuple[OccasionGuidance, ...]
    seasonality: tuple[SeasonGuidance, ...]
    styling_examples: tuple[str, ...]
    variants: tuple[StyleVariant, ...]
    provenance: Provenance
    season: str | None = None
    notes: str | None = None

    def guidance_for(self, occasion: str | None) -> OccasionGuidance:
        """This profile's advice for an occasion, or an empty record."""
        if occasion:
            wanted = occasion.strip().lower()
            for entry in self.occasions:
                if entry.occasion.strip().lower() == wanted:
                    return entry
            return OccasionGuidance(occasion=wanted)
        merged: list[str] = []
        for entry in self.occasions:
            merged.extend(entry.suggests)
        return OccasionGuidance(occasion="any", suggests=tuple(_dedupe(merged)))

    def season_guidance(self) -> SeasonGuidance | None:
        for entry in self.seasonality:
            if entry.name == self.season:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class GuidanceConflict:
    """Two reviewed sources disagreeing about the same place and occasion."""

    occasion: str
    left_source: str
    right_source: str
    left_suggests: tuple[str, ...]
    right_suggests: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class GeographicStyleContext:
    """Geographic style context — and nothing else.

    No temperature, no timestamp of an observation, no stock. Those belong to
    the weather provider module and to Task 11 respectively.
    """

    place: str | None
    place_source: PlaceSource
    resolved_geography: str | None
    granularity: str | None
    coverage: Literal["city", "region", "country", "none"]
    as_of: date_type | None
    season: str | None
    occasion: str | None
    profiles: tuple[ProfileGuidance, ...] = ()
    conflicts: tuple[GuidanceConflict, ...] = ()
    #: Highest confidence among the matched profiles; 0.0 when none matched.
    confidence: float = 0.0
    notes: tuple[str, ...] = ()
    precedence: tuple[str, ...] = PRECEDENCE

    def suggested_items(self, *, occasion: str | None = None) -> tuple[str, ...]:
        """Every item any matched profile suggests, in a stable order.

        Nothing is dropped because another source disagrees — a conflict is
        reported separately, not resolved by discarding one side.
        """
        items: list[str] = []
        for profile in self.profiles:
            items.extend(profile.guidance_for(occasion or self.occasion).suggests)
            season = profile.season_guidance()
            if season is not None:
                items.extend(season.layers)
        return tuple(_dedupe(items))

    def avoided_items(self, *, occasion: str | None = None) -> tuple[str, ...]:
        """What the region advises against. Still only guidance."""
        items: list[str] = []
        for profile in self.profiles:
            items.extend(profile.guidance_for(occasion or self.occasion).avoid)
            season = profile.season_guidance()
            if season is not None:
                items.extend(season.avoid)
        return tuple(_dedupe(items))

    @property
    def seasonal_guidance(self) -> tuple[SeasonGuidance, ...]:
        return tuple(
            guidance
            for guidance in (profile.season_guidance() for profile in self.profiles)
            if guidance is not None
        )

    @property
    def variants(self) -> tuple[StyleVariant, ...]:
        return tuple(variant for profile in self.profiles for variant in profile.variants)


@dataclass(frozen=True, slots=True)
class UserDirective:
    """Something the user actually said. Never inferred from their location."""

    kind: DirectiveKind
    rule: DirectiveRule
    values: tuple[str, ...]
    #: What the user said, kept for the audit trail.
    stated: str = ""


@dataclass(frozen=True, slots=True)
class Override:
    """A regional suggestion (or weaker directive) that lost, and to what."""

    item: str
    dropped_from: str
    beaten_by: DirectiveKind
    stated: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedGuidance:
    """The outcome of applying precedence. Deterministic and re-runnable."""

    excluded: frozenset[str] = frozenset()
    required: frozenset[str] = frozenset()
    suggested: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    overrides: tuple[Override, ...] = ()
    regional_confidence: float = 0.0
    precedence: tuple[str, ...] = field(default=PRECEDENCE)


# --------------------------------------------------------------------------- #
# the rule this module exists to enforce
# --------------------------------------------------------------------------- #
def assert_no_demographic_inference(payload: Any, *, path: str = "") -> None:
    """Refuse a profile that keys guidance on who a person is.

    Location supports climate and local convention. It does not support
    ethnicity, religion, income, or personal taste, so a key naming one of
    those is rejected rather than quietly stored.
    """
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            text = str(key)
            tokens = {token for token in normalise_key(text).split("-") if token}
            offending = tokens & FORBIDDEN_INFERENCE_TOKENS
            if offending:
                where = f"{path}.{text}" if path else text
                raise ProfileValidationError(
                    f"Field {where!r} would infer {min(offending)!r} from a place. "
                    "Location describes climate and local convention, never a person.",
                    detail={"field": where, "attribute": sorted(offending)},
                )
            assert_no_demographic_inference(value, path=f"{path}.{text}" if path else text)
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            assert_no_demographic_inference(item, path=f"{path}[{index}]")


# --------------------------------------------------------------------------- #
# seed loading
# --------------------------------------------------------------------------- #
def load_seed_drafts(directory: Path | None = None) -> list[RegionalProfileDraft]:
    """Parse and validate every seed document. Raises on a bad one."""
    root = directory or SEED_DIR
    drafts: list[RegionalProfileDraft] = []
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ProfileValidationError(f"{path.name} is not a mapping.")
        assert_no_demographic_inference(raw, path=path.name)
        drafts.extend(SeedDocument(**raw).drafts())
    return drafts


async def seed_regional_profiles(
    session: AsyncSession, *, directory: Path | None = None
) -> int:
    """Insert any seeded profile not already present. Returns the count added.

    Idempotent: the natural key is ``(geography_key, source_slug, version)``, so
    re-running adds nothing and never edits a stored row.
    """
    drafts = load_seed_drafts(directory)
    existing = {
        (key, slug, version)
        for key, slug, version in (
            await session.execute(
                sa.select(
                    RegionalStyleProfile.geography_key,
                    RegionalStyleProfile.source_slug,
                    RegionalStyleProfile.version,
                )
            )
        ).all()
    }

    added = 0
    by_lineage: dict[tuple[str, str, int], RegionalStyleProfile] = {}
    for draft in drafts:
        natural = (draft.geography_key or "", draft.source_slug, draft.version)
        if natural in existing:
            continue
        profile = RegionalStyleProfile(**draft.row_kwargs())
        session.add(profile)
        by_lineage[natural] = profile
        added += 1

    if added:
        await session.flush()
        # Chain versions only after every row has an id.
        for draft in drafts:
            if draft.supersedes_version is None:
                continue
            current = by_lineage.get(
                (draft.geography_key or "", draft.source_slug, draft.version)
            )
            if current is None:
                continue
            previous = await session.scalar(
                sa.select(RegionalStyleProfile).where(
                    RegionalStyleProfile.geography_key == draft.geography_key,
                    RegionalStyleProfile.source_slug == draft.source_slug,
                    RegionalStyleProfile.version == draft.supersedes_version,
                )
            )
            if previous is not None:
                current.supersedes_id = previous.id
                previous.retired_at = utcnow()
        await session.commit()
    return added


# --------------------------------------------------------------------------- #
# retrieval
# --------------------------------------------------------------------------- #
def place_candidates(place: str) -> tuple[str, ...]:
    """Lookup keys to try for a typed place, finest first.

    ``"Kisumu, Kenya"`` yields ``("kisumu-kenya", "kisumu", "kenya")`` — the
    whole string, then each comma-separated part. No geocoding, no coordinates.
    """
    cleaned = " ".join((place or "").split())
    if not cleaned:
        return ()
    candidates = [normalise_key(cleaned)]
    for part in cleaned.split(","):
        key = normalise_key(part)
        if key and key not in candidates:
            candidates.append(key)
    return tuple(candidates)


async def _match_profiles(
    session: AsyncSession, candidates: Sequence[str]
) -> list[RegionalStyleProfile]:
    """Current profiles for these keys, finest granularity first."""
    if not candidates:
        return []
    rank = sa.case(
        *[
            (RegionalStyleProfile.granularity == name, value)
            for name, value in GRANULARITY_RANK.items()
        ],
        else_=len(GRANULARITY_RANK),
    )
    statement = (
        sa.select(RegionalStyleProfile)
        .where(
            RegionalStyleProfile.retired_at.is_(None),
            sa.or_(
                RegionalStyleProfile.geography_key.in_(candidates),
                sa.and_(
                    RegionalStyleProfile.granularity == "country",
                    RegionalStyleProfile.country_key.in_(candidates),
                ),
            ),
        )
        .order_by(rank, RegionalStyleProfile.confidence.desc(), RegionalStyleProfile.source_slug)
    )
    rows = list((await session.scalars(statement)).all())
    if rows:
        return rows

    # Key miss: fall back to the declared aliases. This scans the knowledge
    # table, which holds tens of reviewed rows, and only on a miss.
    wanted = set(candidates)
    everything = (
        await session.scalars(
            sa.select(RegionalStyleProfile)
            .where(RegionalStyleProfile.retired_at.is_(None))
            .order_by(rank, RegionalStyleProfile.confidence.desc())
        )
    ).all()
    return [
        profile
        for profile in everything
        if any(normalise_key(alias) in wanted for alias in (profile.aliases or []))
    ]


def season_for(seasonality: Iterable[SeasonGuidance], when: date_type) -> str | None:
    for entry in seasonality:
        if when.month in entry.months:
            return entry.name
    return None


def _to_guidance(profile: RegionalStyleProfile, *, when: date_type) -> ProfileGuidance:
    seasonality = tuple(
        SeasonGuidance(
            name=str(entry.get("name", "")),
            months=tuple(int(month) for month in entry.get("months", ())),
            guidance=str(entry.get("guidance", "")),
            layers=tuple(str(item) for item in entry.get("layers", ())),
            avoid=tuple(str(item) for item in entry.get("avoid", ())),
        )
        for entry in (profile.seasonality or [])
    )
    return ProfileGuidance(
        geography=profile.geography,
        granularity=profile.granularity,
        occasions=tuple(
            OccasionGuidance(
                occasion=str(entry.get("occasion", "")),
                suggests=tuple(str(item) for item in entry.get("suggests", ())),
                avoid=tuple(str(item) for item in entry.get("avoid", ())),
                note=entry.get("note"),
            )
            for entry in (profile.occasions or [])
        ),
        seasonality=seasonality,
        styling_examples=tuple(str(item) for item in (profile.styling_examples or [])),
        variants=tuple(
            StyleVariant(
                kind=str(entry.get("kind", "mainstream")),
                name=str(entry.get("name", "")),
                description=str(entry.get("description", "")),
                suggests=tuple(str(item) for item in entry.get("suggests", ())),
                note=entry.get("note"),
            )
            for entry in (profile.variants or [])
        ),
        provenance=Provenance(
            profile_id=profile.id,
            source_slug=profile.source_slug,
            source_provenance=profile.source_provenance,
            reviewer=profile.reviewer,
            confidence=profile.confidence,
            review_date=profile.review_date,
            version=profile.version,
            supersedes=profile.supersedes_id,
        ),
        season=season_for(seasonality, when),
        notes=profile.notes,
    )


def _conflicts(
    profiles: Sequence[ProfileGuidance], *, occasion: str | None
) -> tuple[GuidanceConflict, ...]:
    """Pairwise disagreement between sources, for the occasions in scope."""
    if len(profiles) < 2:
        return ()
    if occasion:
        occasions = [occasion.strip().lower()]
    else:
        occasions = sorted(
            {entry.occasion.strip().lower() for profile in profiles for entry in profile.occasions}
        )

    found: list[GuidanceConflict] = []
    for name in occasions:
        covering = [
            (profile, profile.guidance_for(name))
            for profile in profiles
            if any(entry.occasion.strip().lower() == name for entry in profile.occasions)
        ]
        for index, (left, left_guidance) in enumerate(covering):
            for right, right_guidance in covering[index + 1 :]:
                left_items = {item.lower() for item in left_guidance.suggests}
                right_items = {item.lower() for item in right_guidance.suggests}
                if left_items == right_items:
                    continue
                found.append(
                    GuidanceConflict(
                        occasion=name,
                        left_source=left.provenance.source_slug,
                        right_source=right.provenance.source_slug,
                        left_suggests=left_guidance.suggests,
                        right_suggests=right_guidance.suggests,
                        note=(
                            "Two reviewed sources disagree about this occasion. "
                            "Both are shown with their own confidence; neither has "
                            "been discarded."
                        ),
                    )
                )
    return tuple(found)


async def regional_context(
    session: AsyncSession,
    *,
    place: str | None = None,
    date: date_type | None = None,
    occasion: str | None = None,
    place_source: PlaceSource = "user_manual",
) -> GeographicStyleContext:
    """Geographic style context for a place name, a date and an occasion.

    No place is a supported state, not an error: a user who declines to share
    one still gets a usable context (empty, zero confidence) so manual styling
    carries on. Nothing here touches weather or stock.
    """
    if place_source not in PLACE_SOURCES:
        raise ProfileValidationError(
            f"place_source must be one of {PLACE_SOURCES!r}, got {place_source!r}"
        )
    when = date or utcnow().date()
    wanted = occasion.strip().lower() if occasion else None

    typed = (place or "").strip()
    if not typed:
        return GeographicStyleContext(
            place=None,
            place_source=place_source,
            resolved_geography=None,
            granularity=None,
            coverage="none",
            as_of=when,
            season=None,
            occasion=wanted,
            notes=(
                (
                    "No place was supplied, so no regional guidance is included. "
                    "Styling continues from the wardrobe and the user's own directives."
                ),
            ),
        )

    rows = await _match_profiles(session, place_candidates(typed))
    if not rows:
        return GeographicStyleContext(
            place=typed,
            place_source=place_source,
            resolved_geography=None,
            granularity=None,
            coverage="none",
            as_of=when,
            season=None,
            occasion=wanted,
            notes=(f"No reviewed profile covers {typed!r}; no regional guidance applied.",),
        )

    # Finest granularity present wins; a coarse profile is a fallback, never a
    # supplement to a city that already has one.
    best_rank = min(profile.granularity_rank for profile in rows)
    selected = [profile for profile in rows if profile.granularity_rank == best_rank]
    guidance = tuple(_to_guidance(profile, when=when) for profile in selected)

    seasons = {profile.season for profile in guidance if profile.season}
    notes: list[str] = []
    if len(seasons) > 1:
        notes.append(
            "Sources describe the local year differently; the highest-confidence "
            "source's season is reported."
        )
    coverage = selected[0].granularity
    if coverage != "city":
        notes.append(
            f"The closest reviewed profile is {coverage}-level, which is a weaker "
            "generalisation than a city profile. Its confidence reflects that."
        )
    notes.extend(profile.notes for profile in guidance if profile.notes)

    return GeographicStyleContext(
        place=typed,
        place_source=place_source,
        resolved_geography=selected[0].geography,
        granularity=coverage,
        coverage=coverage,  # type: ignore[arg-type]
        as_of=when,
        season=guidance[0].season,
        occasion=wanted,
        profiles=guidance,
        conflicts=_conflicts(guidance, occasion=wanted),
        confidence=max(profile.provenance.confidence for profile in guidance),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- #
# precedence — pure, and the reason the region can never overrule the user
# --------------------------------------------------------------------------- #
async def load_user_directives(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[UserDirective, ...]:
    """Turn stored preferences into directives this layer understands.

    Only the keys in ``PREFERENCE_RULES`` are interpreted; anything else is
    left alone rather than guessed at.
    """
    rows = (
        await session.scalars(sa.select(Preference).where(Preference.user_id == user_id))
    ).all()
    directives: list[UserDirective] = []
    for row in sorted(rows, key=lambda r: r.key):
        rule = PREFERENCE_RULES.get(row.key)
        if rule is None:
            continue
        values = _as_values(row.value)
        if not values:
            continue
        directives.append(
            UserDirective(kind="preference", rule=rule, values=values, stated=f"{row.key}={values}")
        )
    return tuple(directives)


def apply_precedence(
    *,
    context: GeographicStyleContext | None,
    directives: Iterable[UserDirective],
    occasion: str | None = None,
) -> ResolvedGuidance:
    """Resolve regional guidance against what the user said. Pure.

    ``hard_constraint > preference > regional_guidance``. A hard constraint
    beats a preference; either beats the region. Every regional suggestion the
    user's directives removed is recorded in ``overrides`` with the directive
    that beat it, so the reason is reportable rather than invisible.
    """
    directive_list = list(directives)
    hard_exclude = _values_for(directive_list, "hard_constraint", "exclude")
    hard_require = _values_for(directive_list, "hard_constraint", "require")
    soft_exclude = _values_for(directive_list, "preference", "exclude")
    soft_require = _values_for(directive_list, "preference", "require")
    soft_prefer = _values_for(directive_list, "preference", "prefer")

    overrides: list[Override] = []

    # A hard constraint requiring something outranks a preference excluding it.
    excluded = set(hard_exclude)
    for item in sorted(soft_exclude):
        if item in hard_require:
            overrides.append(
                Override(
                    item=item,
                    dropped_from="preference",
                    beaten_by="hard_constraint",
                    stated=_stated_for(directive_list, "hard_constraint", "require", item),
                )
            )
            continue
        excluded.add(item)

    required = {item for item in hard_require if item not in hard_exclude}
    for item in sorted(soft_require):
        if item in excluded:
            overrides.append(
                Override(
                    item=item,
                    dropped_from="preference",
                    beaten_by="hard_constraint" if item in hard_exclude else "preference",
                    stated=_stated_for(directive_list, "hard_constraint", "exclude", item),
                )
            )
            continue
        required.add(item)

    regional_items = context.suggested_items(occasion=occasion) if context else ()
    regional_avoid = context.avoided_items(occasion=occasion) if context else ()
    source_slug = (
        context.profiles[0].provenance.source_slug
        if context and context.profiles
        else "regional_guidance"
    )

    kept: list[str] = []
    for item in regional_items:
        normalised = item.strip().lower()
        if normalised in excluded:
            overrides.append(
                Override(
                    item=normalised,
                    dropped_from=source_slug,
                    beaten_by="hard_constraint" if normalised in hard_exclude else "preference",
                    stated=_stated_for(
                        directive_list,
                        "hard_constraint" if normalised in hard_exclude else "preference",
                        "exclude",
                        normalised,
                    ),
                )
            )
            continue
        kept.append(normalised)

    # Stated preferences come before regional suggestions in the surviving order.
    ordered = _dedupe([*sorted(required), *sorted(soft_prefer - excluded), *kept])

    return ResolvedGuidance(
        excluded=frozenset(excluded),
        required=frozenset(required),
        suggested=tuple(ordered),
        avoid=tuple(_dedupe([item.strip().lower() for item in regional_avoid])),
        overrides=tuple(overrides),
        regional_confidence=context.confidence if context else 0.0,
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(item.strip())
    return kept


def _as_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip().lower(),) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(_dedupe([str(item).lower() for item in value]))
    if isinstance(value, Mapping):
        return tuple(_dedupe([str(item).lower() for item in value.get("values", ())]))
    return ()


def _values_for(
    directives: Sequence[UserDirective], kind: DirectiveKind, rule: DirectiveRule
) -> set[str]:
    return {
        value.strip().lower()
        for directive in directives
        if directive.kind == kind and directive.rule == rule
        for value in directive.values
    }


def _stated_for(
    directives: Sequence[UserDirective], kind: DirectiveKind, rule: DirectiveRule, item: str
) -> str:
    for directive in directives:
        if directive.kind != kind or directive.rule != rule:
            continue
        if item in {value.strip().lower() for value in directive.values}:
            return directive.stated
    return ""


__all__ = [
    "FORBIDDEN_INFERENCE_TOKENS",
    "PLACE_SOURCES",
    "PRECEDENCE",
    "PREFERENCE_RULES",
    "SEED_DIR",
    "GeographicStyleContext",
    "GuidanceConflict",
    "OccasionGuidance",
    "Override",
    "PlaceSource",
    "ProfileGuidance",
    "ProfileValidationError",
    "Provenance",
    "ResolvedGuidance",
    "SeasonGuidance",
    "StyleVariant",
    "UserDirective",
    "apply_precedence",
    "assert_no_demographic_inference",
    "load_seed_drafts",
    "load_user_directives",
    "place_candidates",
    "regional_context",
    "season_for",
    "seed_regional_profiles",
    "utcnow",
]
