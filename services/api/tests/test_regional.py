"""Task 9 — regional style profiles: provenance, precedence, and plurality.

Four invariants carry this module.

* **Provenance is mandatory.** A profile without ``source_provenance`` or
  ``reviewer`` does not exist — it fails validation, and the database refuses an
  empty one even if validation were bypassed.
* **The user outranks the region.** Regional patterns are contextual guidance.
  An explicit preference, and above it a hard constraint, always wins. That
  precedence is a pure function so it can be asserted without a stylist.
* **Disagreement is data.** Two profiles may cover the same geography and
  occasion with different advice. Both are kept and the conflict is reported;
  nothing silently picks a winner.
* **A profile is not a stereotype, and location is not a person.** Every profile
  carries within-region variation, and nothing anywhere keys guidance on
  ethnicity, religion, income, or personal taste.

Scope note: the plan's Task 9 tests call ``style(db, user, ctx)``, which is
Task 8's stylist. These tests therefore exercise the layer this task owns — the
regional context and the precedence function the stylist consumes — rather than
stubbing a whole stylist inside another task's boundary.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import fields
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import regional
from app.domain.regional import (
    PRECEDENCE,
    SEED_DIR,
    GeographicStyleContext,
    ProfileValidationError,
    UserDirective,
    apply_precedence,
    load_seed_drafts,
    load_user_directives,
    regional_context,
    seed_regional_profiles,
)
from app.models.regional_profile import GRANULARITIES, RegionalStyleProfile
from app.models.user import User
from app.schemas.regional import RegionalContextResponse, RegionalProfileDraft

JULY = date(2026, 7, 15)
JANUARY = date(2026, 1, 15)

MODEL_PATH = Path(regional.__file__).resolve().parents[1] / "models" / "regional_profile.py"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
async def seeded(db: AsyncSession) -> AsyncSession:
    await seed_regional_profiles(db)
    return db


async def make_user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def set_preference(db: AsyncSession, user: User, key: str, value: object) -> None:
    from app.models.preference import Preference

    db.add(Preference(user_id=user.id, key=key, value=value))
    await db.commit()


def draft_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "geography": "Testville",
        "geography_key": "testville",
        "granularity": "city",
        "country_key": "testland",
        "aliases": [],
        "source_slug": "desk-research",
        "version": 1,
        "review_date": date(2026, 10, 1),
        "reviewer": "local stylist review, Testville, 2026-10",
        "source_provenance": "Compiled from a survey of publicly visible retail assortments.",
        "confidence": 0.4,
        "occasions": [{"occasion": "casual", "suggests": ["linen shirt"], "avoid": []}],
        "seasonality": [{"name": "year_round", "months": list(range(1, 13)), "guidance": "Mild."}],
        "styling_examples": ["Linen shirt with light trousers."],
        "variants": [
            {
                "kind": "alternative",
                "name": "alternative scene",
                "description": "Layered black, heavy boots.",
                "suggests": ["heavy boots"],
            }
        ],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# the user outranks the region
# --------------------------------------------------------------------------- #
async def test_explicit_preference_overrides_regional_default(seeded: AsyncSession) -> None:
    """Mombasa casual guidance suggests shorts. The user does not wear shorts."""
    user = await make_user(seeded)
    await set_preference(seeded, user, "never_wears", ["shorts"])

    ctx = await regional_context(seeded, place="Mombasa", occasion="casual", date=JULY)
    regional_items = {item.lower() for item in ctx.suggested_items(occasion="casual")}
    assert "shorts" in regional_items, "the seed must actually suggest shorts here"

    directives = await load_user_directives(seeded, user_id=user.id)
    resolved = apply_precedence(context=ctx, directives=directives, occasion="casual")

    assert "shorts" not in resolved.suggested
    assert "shorts" in resolved.excluded
    assert any(o.item == "shorts" and o.beaten_by == "preference" for o in resolved.overrides)


async def test_a_hard_constraint_beats_both_a_preference_and_the_region(
    seeded: AsyncSession,
) -> None:
    ctx = await regional_context(seeded, place="Mombasa", occasion="casual", date=JULY)
    directives = (
        UserDirective(kind="preference", rule="require", values=("shorts",), stated="I like shorts"),
        UserDirective(kind="hard_constraint", rule="exclude", values=("shorts",), stated="no shorts"),
    )

    resolved = apply_precedence(context=ctx, directives=directives, occasion="casual")

    assert "shorts" in resolved.excluded
    assert "shorts" not in resolved.required
    assert "shorts" not in resolved.suggested
    assert any(o.beaten_by == "hard_constraint" for o in resolved.overrides)


def test_the_precedence_order_is_stated_not_implied() -> None:
    assert PRECEDENCE == ("hard_constraint", "preference", "regional_guidance")


async def test_an_excluded_item_is_never_reintroduced_by_repeated_resolution(
    seeded: AsyncSession,
) -> None:
    """Echoes the stylist's three-swap requirement at this layer: re-resolving
    the same constraint set must not let the region win on a later pass."""
    ctx = await regional_context(seeded, place="Mombasa", occasion="casual", date=JULY)
    directives = (
        UserDirective(kind="hard_constraint", rule="exclude", values=("shorts",), stated="no shorts"),
    )

    resolved = apply_precedence(context=ctx, directives=directives, occasion="casual")
    for _ in range(3):
        again = apply_precedence(context=ctx, directives=directives, occasion="casual")
        assert again.suggested == resolved.suggested
        assert "shorts" not in again.suggested


# --------------------------------------------------------------------------- #
# location is optional, and never a device fix
# --------------------------------------------------------------------------- #
async def test_declined_location_still_permits_manual_styling(seeded: AsyncSession) -> None:
    """No place at all is a supported state, not an error."""
    ctx = await regional_context(seeded, place=None, place_source="declined", date=JULY)

    assert ctx.coverage == "none"
    assert ctx.profiles == ()
    assert ctx.confidence == 0.0
    assert ctx.place_source == "declined"

    directives = (
        UserDirective(kind="hard_constraint", rule="exclude", values=("heels",), stated="no heels"),
        UserDirective(kind="preference", rule="require", values=("blazer",), stated="blazer please"),
    )
    resolved = apply_precedence(context=ctx, directives=directives, occasion="office")

    assert "heels" in resolved.excluded
    assert "blazer" in resolved.required
    assert resolved.regional_confidence == 0.0


async def test_a_manually_typed_place_is_not_a_device_location(seeded: AsyncSession) -> None:
    ctx = await regional_context(
        seeded, place="Nairobi", place_source="user_manual", occasion="office", date=JULY
    )

    assert ctx.place_source == "user_manual"
    assert ctx.coverage == "city"
    assert ctx.profiles != ()


def test_the_context_records_no_coordinate() -> None:
    names = {field.name for field in fields(GeographicStyleContext)}
    for coordinate in ("latitude", "longitude", "lat", "lon", "lng", "geohash", "coordinates"):
        assert coordinate not in names


async def test_an_unknown_place_reports_no_coverage_rather_than_failing(
    seeded: AsyncSession,
) -> None:
    ctx = await regional_context(seeded, place="Zzyzx-on-Sea", date=JULY)

    assert ctx.coverage == "none"
    assert ctx.profiles == ()
    assert ctx.resolved_geography is None


# --------------------------------------------------------------------------- #
# the region actually changes the answer
# --------------------------------------------------------------------------- #
async def test_regional_context_changes_suggestions_between_two_distinct_climates(
    seeded: AsyncSession,
) -> None:
    nairobi = await regional_context(seeded, place="Nairobi", occasion="casual", date=JULY)
    reykjavik = await regional_context(seeded, place="Reykjavik", occasion="casual", date=JULY)

    a = apply_precedence(context=nairobi, directives=(), occasion="casual")
    b = apply_precedence(context=reykjavik, directives=(), occasion="casual")

    assert a.suggested != b.suggested
    assert set(a.suggested) - set(b.suggested)
    assert set(b.suggested) - set(a.suggested)
    assert nairobi.season != reykjavik.season


async def test_the_same_place_in_two_seasons_gives_different_guidance(
    seeded: AsyncSession,
) -> None:
    summer = await regional_context(seeded, place="Reykjavik", occasion="casual", date=JULY)
    winter = await regional_context(seeded, place="Reykjavik", occasion="casual", date=JANUARY)

    assert summer.season != winter.season
    assert summer.seasonal_guidance != winter.seasonal_guidance


async def test_the_season_is_resolved_from_the_supplied_date(seeded: AsyncSession) -> None:
    ctx = await regional_context(seeded, place="Nairobi", date=date(2026, 4, 10))
    assert ctx.season == "long_rains"


# --------------------------------------------------------------------------- #
# provenance is mandatory
# --------------------------------------------------------------------------- #
def test_a_profile_without_source_provenance_fails_validation() -> None:
    with pytest.raises(ValidationError):
        RegionalProfileDraft(**draft_kwargs(source_provenance=None))
    with pytest.raises(ValidationError):
        RegionalProfileDraft(**draft_kwargs(source_provenance="   "))


def test_a_profile_without_a_reviewer_fails_validation() -> None:
    with pytest.raises(ValidationError):
        RegionalProfileDraft(**draft_kwargs(reviewer=None))
    with pytest.raises(ValidationError):
        RegionalProfileDraft(**draft_kwargs(reviewer=""))


def test_confidence_outside_zero_to_one_fails_validation() -> None:
    for bad in (-0.1, 1.5):
        with pytest.raises(ValidationError):
            RegionalProfileDraft(**draft_kwargs(confidence=bad))


async def test_the_database_refuses_an_empty_provenance_even_without_validation(
    db: AsyncSession,
) -> None:
    """Belt and braces: the invariant is also a schema property."""
    db.add(
        RegionalStyleProfile(
            geography="Nowhere",
            geography_key="nowhere",
            granularity="city",
            occasions=[],
            seasonality=[],
            styling_examples=[],
            variants=[],
            source_slug="desk-research",
            source_provenance="",
            reviewer="a reviewer role",
            confidence=0.5,
            review_date=date(2026, 10, 1),
            version=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_every_seeded_profile_carries_provenance_and_a_reviewer_role(
    seeded: AsyncSession,
) -> None:
    profiles = (await seeded.scalars(sa.select(RegionalStyleProfile))).all()

    assert profiles
    for profile in profiles:
        assert profile.source_provenance.strip()
        assert profile.reviewer.strip()
        assert 0.0 <= profile.confidence <= 1.0
        assert profile.granularity in GRANULARITIES
        assert profile.review_date is not None
        assert profile.version >= 1


# --------------------------------------------------------------------------- #
# disagreement and uncertainty are represented, not resolved away
# --------------------------------------------------------------------------- #
async def test_two_profiles_may_disagree_about_the_same_geography_and_occasion(
    seeded: AsyncSession,
) -> None:
    ctx = await regional_context(seeded, place="Nairobi", occasion="office", date=JULY)

    assert len(ctx.profiles) >= 2, "Nairobi is seeded with two disagreeing sources"
    assert {p.provenance.source_slug for p in ctx.profiles} >= {
        "retail-assortment-survey",
        "venue-dress-code-review",
    }
    assert ctx.conflicts, "the disagreement must be reported, not flattened"
    conflict = ctx.conflicts[0]
    assert conflict.occasion == "office"
    assert conflict.left_source != conflict.right_source
    assert set(conflict.left_suggests) != set(conflict.right_suggests)


async def test_a_conflict_does_not_drop_either_side_from_the_suggestions(
    seeded: AsyncSession,
) -> None:
    ctx = await regional_context(seeded, place="Nairobi", occasion="office", date=JULY)
    suggested = {item.lower() for item in ctx.suggested_items(occasion="office")}

    left = {item.lower() for p in ctx.profiles for item in p.guidance_for("office").suggests}
    assert left <= suggested


async def test_confidence_is_lower_where_the_data_is_sparse(seeded: AsyncSession) -> None:
    """A country-wide profile spanning several climates is a weak
    generalisation and says so in its own confidence."""
    country = await seeded.scalar(
        sa.select(RegionalStyleProfile).where(
            RegionalStyleProfile.geography_key == "kenya",
            RegionalStyleProfile.granularity == "country",
        )
    )
    city = await seeded.scalar(
        sa.select(RegionalStyleProfile).where(RegionalStyleProfile.geography_key == "nairobi")
    )

    assert country is not None and city is not None
    assert country.confidence < city.confidence
    assert country.confidence <= 0.4


async def test_a_country_profile_is_only_used_when_no_closer_profile_matches(
    seeded: AsyncSession,
) -> None:
    kisumu = await regional_context(seeded, place="Kisumu, Kenya", occasion="casual", date=JULY)

    assert kisumu.coverage == "country"
    assert kisumu.resolved_geography == "Kenya"
    assert kisumu.confidence <= 0.4

    nairobi = await regional_context(seeded, place="Nairobi", occasion="casual", date=JULY)
    assert nairobi.coverage == "city"
    assert nairobi.confidence > kisumu.confidence


# --------------------------------------------------------------------------- #
# versions chain
# --------------------------------------------------------------------------- #
async def test_versions_chain_through_supersedes(seeded: AsyncSession) -> None:
    original = await seeded.scalar(
        sa.select(RegionalStyleProfile).where(
            RegionalStyleProfile.geography_key == "nairobi",
            RegionalStyleProfile.source_slug == "retail-assortment-survey",
        )
    )
    assert original is not None

    revised = RegionalStyleProfile(
        geography=original.geography,
        geography_key=original.geography_key,
        country_key=original.country_key,
        granularity=original.granularity,
        aliases=list(original.aliases),
        occasions=[{"occasion": "office", "suggests": ["safari jacket"], "avoid": []}],
        seasonality=list(original.seasonality),
        styling_examples=["Safari jacket over a shirt."],
        variants=list(original.variants),
        source_slug=original.source_slug,
        source_provenance=original.source_provenance,
        reviewer="local stylist review, Nairobi, 2026-11",
        confidence=0.6,
        review_date=date(2026, 11, 1),
        version=original.version + 1,
        supersedes_id=original.id,
    )
    seeded.add(revised)
    original.retired_at = regional.utcnow()
    await seeded.commit()

    ctx = await regional_context(seeded, place="Nairobi", occasion="office", date=JULY)
    slugs_and_versions = {(p.provenance.source_slug, p.provenance.version) for p in ctx.profiles}

    assert ("retail-assortment-survey", 2) in slugs_and_versions
    assert ("retail-assortment-survey", 1) not in slugs_and_versions
    assert any(p.provenance.supersedes == original.id for p in ctx.profiles)


# --------------------------------------------------------------------------- #
# the seed itself
# --------------------------------------------------------------------------- #
def test_the_seed_covers_six_distinct_cities_including_nairobi_and_mombasa() -> None:
    drafts = load_seed_drafts()
    cities = {d.geography_key for d in drafts if d.granularity == "city"}

    assert {"nairobi", "mombasa"} <= cities
    assert len(cities) >= 6, f"only {len(cities)} cities seeded: {sorted(cities)}"


def test_the_seeded_cities_span_genuinely_distinct_climates() -> None:
    """Distinct seasonality shapes, not six variations on 'temperate'."""
    drafts = load_seed_drafts()
    shapes = {
        d.geography_key: tuple(sorted(s.name for s in d.seasonality))
        for d in drafts
        if d.granularity == "city"
    }
    assert len(set(shapes.values())) >= 4, shapes


def test_every_seeded_profile_carries_within_region_variation() -> None:
    """A profile is not a stereotype."""
    for draft in load_seed_drafts():
        assert draft.variants, f"{draft.geography_key}/{draft.source_slug} has no variation"


def test_at_least_one_profile_names_alternative_and_international_variants() -> None:
    kinds = {v.kind for draft in load_seed_drafts() for v in draft.variants}
    assert {"alternative", "international"} <= kinds


def test_a_profile_with_no_variation_fails_validation() -> None:
    with pytest.raises(ValidationError):
        RegionalProfileDraft(**draft_kwargs(variants=[]))


def test_the_seed_cites_no_publication_and_names_no_person() -> None:
    """Provenance must be honest: role-based reviewers, no invented citations."""
    for path in sorted(SEED_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://", text), f"{path.name} cites a URL"
        assert not re.search(r"\b(?:doi|ISBN|et al\.?)\b", text, re.IGNORECASE), path.name
    role = re.compile(r"(review|stylist|reviewer|buyer|specialist)", re.IGNORECASE)
    for draft in load_seed_drafts():
        # A reviewer is a role plus a place and a month, never a personal name.
        assert role.search(draft.reviewer), draft.reviewer


# --------------------------------------------------------------------------- #
# location never infers who a person is
# --------------------------------------------------------------------------- #
def test_the_model_has_no_column_that_describes_a_person() -> None:
    columns = set(RegionalStyleProfile.__table__.columns.keys())
    for forbidden in (
        "ethnicity",
        "ethnic_group",
        "religion",
        "faith",
        "income",
        "income_band",
        "affluence",
        "social_class",
        "taste",
        "taste_profile",
        "demographic",
        "race",
    ):
        assert forbidden not in columns


def test_the_module_states_the_rule_it_enforces() -> None:
    for path in (Path(regional.__file__), MODEL_PATH):
        doc = path.read_text(encoding="utf-8")[:4000].lower()
        assert "ethnicity" in doc
        assert "religion" in doc
        assert "income" in doc
        assert "taste" in doc


def test_a_profile_keyed_on_a_forbidden_attribute_is_refused() -> None:
    with pytest.raises(ProfileValidationError):
        regional.assert_no_demographic_inference(
            {"occasions": [{"occasion": "office", "income_band": "high"}]}
        )
    with pytest.raises(ProfileValidationError):
        regional.assert_no_demographic_inference({"variants": [{"ethnicity": "any"}]})
    # A clean payload passes silently.
    regional.assert_no_demographic_inference({"occasions": [{"occasion": "office"}]})


def test_the_seed_text_makes_no_claim_about_who_a_wearer_is() -> None:
    pattern = re.compile(
        r"\b(ethnic\w*|religio\w*|muslim|christian|hindu|jewish|tribe|tribal|caste"
        r"|income|wealthy|affluent|poor|low-income|upper[- ]class|working[- ]class)\b",
        re.IGNORECASE,
    )
    for path in sorted(SEED_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path.name}: {pattern.search(text).group(0)!r}"


# --------------------------------------------------------------------------- #
# three concerns, three types
# --------------------------------------------------------------------------- #
def test_geographic_context_holds_no_weather_and_no_inventory() -> None:
    names = {field.name for field in fields(GeographicStyleContext)}
    for leaked in (
        "temperature",
        "weather",
        "observed_at",
        "is_stale",
        "described_by_user",
        "offers",
        "products",
        "inventory",
        "retailer",
        "price_minor",
        "availability",
    ):
        assert leaked not in names


def test_the_regional_module_imports_neither_weather_nor_inventory() -> None:
    source = Path(regional.__file__).read_text(encoding="utf-8")
    for forbidden in ("app.providers.weather", "WeatherReading", "Offer", "Retailer"):
        assert forbidden not in source


def test_the_context_response_carries_no_weather_field() -> None:
    names = set(RegionalContextResponse.model_fields)
    for leaked in ("weather", "temperature", "is_stale", "offers", "inventory"):
        assert leaked not in names


# --------------------------------------------------------------------------- #
# the endpoint's response shape
# --------------------------------------------------------------------------- #
async def test_the_context_response_exposes_provenance_and_confidence(
    seeded: AsyncSession,
) -> None:
    ctx = await regional_context(seeded, place="Nairobi", occasion="office", date=JULY)
    body = RegionalContextResponse.from_context(ctx).model_dump(mode="json")

    assert body["place"] == "Nairobi"
    assert body["resolved_geography"] == "Nairobi"
    assert body["granularity"] == "city"
    assert body["coverage"] == "city"
    assert body["occasion"] == "office"
    assert body["season"] == "cool_dry"
    assert 0.0 < body["confidence"] <= 1.0
    assert body["precedence"] == list(PRECEDENCE)
    assert len(body["profiles"]) >= 2
    for profile in body["profiles"]:
        assert profile["provenance"]["source_provenance"]
        assert profile["provenance"]["reviewer"]
        assert 0.0 <= profile["provenance"]["confidence"] <= 1.0
        assert profile["provenance"]["review_date"]
        assert profile["variants"]
    assert body["conflicts"]


async def test_seeding_is_idempotent(db: AsyncSession) -> None:
    first = await seed_regional_profiles(db)
    second = await seed_regional_profiles(db)
    total = await db.scalar(sa.select(sa.func.count()).select_from(RegionalStyleProfile))

    assert first > 0
    assert second == 0
    assert total == first
