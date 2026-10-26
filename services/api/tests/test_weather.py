"""Task 9 — weather readings, kept honest about where they came from.

Two things are being defended here.

*Provenance.* A reading the user described in their own words is marked
``described_by_user`` and carries **no** ``source``. A machine reading must name
its source. Neither can be silently turned into the other, so the type refuses
the impossible combinations in its constructor rather than trusting call sites.

*Capability labelling.* No weather provider has been selected or credentialed
for this build, so the shipped provider is a clearly-labelled unavailable one
that raises ``CapabilityUnavailable``. It holds no API key and makes no network
call. The user-described path works with no provider at all — that is the point
of separating them.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.errors import CapabilityUnavailable
from app.providers import weather as weather_module
from app.providers.weather import (
    STALE_AFTER_SECONDS,
    UnavailableWeatherProvider,
    WeatherProvider,
    WeatherReading,
    build_weather_provider,
    reading_from_user_description,
)

MODULE_PATH = Path(weather_module.__file__)


# --------------------------------------------------------------------------- #
# a user-described reading is not a measurement, and never pretends to be
# --------------------------------------------------------------------------- #
def test_user_described_reading_sets_the_flag_and_carries_no_source() -> None:
    reading = reading_from_user_description(place="Nairobi", description="cold and drizzly")

    assert reading.described_by_user is True
    assert reading.source is None
    assert reading.place == "Nairobi"
    assert reading.description == "cold and drizzly"


def test_a_user_described_reading_cannot_be_handed_a_source() -> None:
    """The fabricated-provenance path is closed in the constructor."""
    with pytest.raises(ValueError, match="described_by_user"):
        WeatherReading(
            place="Nairobi",
            observed_at=datetime.now(UTC),
            units="metric",
            source="openweather",  # not where this came from
            is_stale=False,
            described_by_user=True,
        )


def test_a_machine_reading_must_name_its_source() -> None:
    with pytest.raises(ValueError, match="source"):
        WeatherReading(
            place="Nairobi",
            observed_at=datetime.now(UTC),
            units="metric",
            source=None,
            is_stale=False,
            described_by_user=False,
        )


def test_description_is_the_users_own_words_not_an_invented_measurement() -> None:
    """Words are classified; numbers are never conjured from them."""
    reading = reading_from_user_description(place="Mombasa", description="really humid today")

    assert reading.temperature is None
    assert "humid" in reading.conditions
    # The classification is of the user's own words, so its origin is the user.
    assert reading.described_by_user is True


def test_a_stated_temperature_is_kept_and_an_unstated_one_is_not_guessed() -> None:
    stated = reading_from_user_description(
        place="Reykjavik", description="about four degrees", temperature=4.0
    )
    unstated = reading_from_user_description(place="Reykjavik", description="chilly")

    assert stated.temperature == 4.0
    assert unstated.temperature is None
    assert unstated.source is None


def test_units_are_always_declared() -> None:
    assert reading_from_user_description(place="London", description="mild").units == "metric"
    assert (
        reading_from_user_description(place="Austin", description="mild", units="imperial").units
        == "imperial"
    )
    with pytest.raises(ValueError, match="units"):
        reading_from_user_description(place="London", description="mild", units="kelvin")


# --------------------------------------------------------------------------- #
# freshness is explicit
# --------------------------------------------------------------------------- #
def test_freshness_is_explicit_and_derived_from_observed_at() -> None:
    now = datetime.now(UTC)
    fresh = reading_from_user_description(
        place="Nairobi", description="sunny", observed_at=now - timedelta(minutes=5), now=now
    )
    stale = reading_from_user_description(
        place="Nairobi", description="sunny", observed_at=now - timedelta(hours=9), now=now
    )

    assert fresh.is_stale is False
    assert stale.is_stale is True
    assert fresh.age_seconds == pytest.approx(300, abs=2)
    assert fresh.stale_after_seconds == STALE_AFTER_SECONDS


def test_a_stale_reading_is_labelled_rather_than_dropped() -> None:
    """A timestamp the user can see beats a silent omission."""
    observed = datetime.now(UTC) - timedelta(days=2)
    reading = reading_from_user_description(
        place="Dubai", description="hot", observed_at=observed
    )

    assert reading.is_stale is True
    assert reading.observed_at == observed
    assert reading.freshness == "stale"


def test_a_naive_observed_at_is_refused() -> None:
    with pytest.raises(ValueError, match="aware"):
        reading_from_user_description(
            place="Nairobi", description="sunny", observed_at=datetime(2026, 7, 1, 12, 0)
        )


# --------------------------------------------------------------------------- #
# no provider has been selected or credentialed
# --------------------------------------------------------------------------- #
async def test_the_shipped_provider_is_unavailable_and_refuses_loudly() -> None:
    provider = build_weather_provider()

    assert isinstance(provider, UnavailableWeatherProvider)
    assert provider.available is False
    assert provider.status == "unavailable"
    with pytest.raises(CapabilityUnavailable) as excinfo:
        await provider.current(place="Nairobi")
    assert excinfo.value.code == "capability_unavailable"


async def test_the_unavailable_provider_holds_no_credential_and_calls_nothing() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert not hasattr(weather_module, "httpx")
    for forbidden in ("httpx", "requests", "aiohttp", "urllib.request"):
        assert f"import {forbidden}" not in source
    # No invented key, and no invented endpoint.
    assert not re.search(r"api[_-]?key\s*=\s*[\"'][^\"']+[\"']", source, re.IGNORECASE)
    assert not re.search(r"https?://", source, re.IGNORECASE), "no endpoint has been chosen"


def test_the_provider_interface_is_declared_so_a_real_one_can_drop_in() -> None:
    provider = UnavailableWeatherProvider()

    assert isinstance(provider, WeatherProvider)
    signature = inspect.signature(provider.current)
    assert "place" in signature.parameters
    assert "units" in signature.parameters


async def test_the_user_described_path_works_with_no_provider_at_all() -> None:
    """A declined or unavailable provider must not block styling."""
    provider = build_weather_provider()
    with pytest.raises(CapabilityUnavailable):
        await provider.current(place="Mombasa")

    reading = reading_from_user_description(place="Mombasa", description="hot and sticky")
    assert reading.described_by_user is True
    assert reading.source is None


# --------------------------------------------------------------------------- #
# weather is its own concern
# --------------------------------------------------------------------------- #
def test_a_weather_reading_carries_no_style_guidance_and_no_inventory() -> None:
    """Three concerns, three types: this one is only about the air outside."""
    names = {field.name for field in fields(WeatherReading)}

    assert {"place", "observed_at", "units", "source", "is_stale", "described_by_user"} <= names
    for leaked in (
        "styling_examples",
        "occasions",
        "seasonality",
        "profiles",
        "reviewer",
        "source_provenance",
        "offers",
        "products",
        "retailer",
        "price_minor",
        "garments",
    ):
        assert leaked not in names


def test_weather_never_records_a_coordinate() -> None:
    """``place`` is a name. Coordinates are redacted everywhere else; do not
    reintroduce them here (see the redaction filter in app.middleware)."""
    names = {field.name for field in fields(WeatherReading)}
    for coordinate in ("latitude", "longitude", "lat", "lon", "lng", "geohash"):
        assert coordinate not in names
