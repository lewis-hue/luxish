"""Weather readings — one of three deliberately separate concerns.

Task 9 keeps three things apart because they are three different kinds of
claim, and merging them would make it impossible to say which one was wrong:

1. **Geographic style context** — ``app.domain.regional``. Reviewed, versioned
   knowledge about how people dress somewhere. Slow-moving, provenanced.
2. **Weather** — this module. What the air is doing right now, with a timestamp
   and an explicit freshness label.
3. **Retailer inventory** — Task 11. What can actually be bought today.

A ``WeatherReading`` therefore carries no styling guidance and no stock, and
nothing in this module reads a style profile.

**Provenance is enforced by the type, not by convention.** A reading the user
described in their own words sets ``described_by_user`` and carries ``source =
None``; it is not a measurement and must never be dressed up as one. A reading
from a machine must name the service it came from. The constructor refuses both
impossible combinations, so a fabricated source cannot enter through a careless
call site.

**No provider has been selected or credentialed for this build.** The shipped
implementation is ``UnavailableWeatherProvider``: it holds no key, names no
endpoint, performs no I/O, and raises ``CapabilityUnavailable``. The interface
is the one a real service would implement. The user-described path works with
no provider at all, which is why it is a plain function rather than a provider
method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from app.errors import CapabilityUnavailable

#: Declared on every reading. There is no implicit default unit system.
Units = Literal["metric", "imperial"]
UNITS: tuple[str, ...] = ("metric", "imperial")

#: A reading older than this is labelled stale. It is still returned — a
#: visible timestamp is more useful than a silent omission — but no caller can
#: mistake it for current. ASSUMED; revisit when a provider is chosen.
STALE_AFTER_SECONDS: int = 3600

#: Condition words recognised in a user's own description. This is a
#: classification of what the user said, not an inference about the weather,
#: which is why the resulting reading is still ``described_by_user``.
_CONDITION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rain", ("rain", "raining", "rainy", "drizzle", "drizzly", "wet", "pouring", "showers")),
    ("snow", ("snow", "snowing", "snowy", "sleet", "blizzard")),
    ("cold", ("cold", "freezing", "chilly", "chilled", "frosty", "bitter")),
    ("hot", ("hot", "scorching", "boiling", "sweltering", "heat")),
    ("humid", ("humid", "humidity", "muggy", "sticky", "clammy")),
    ("wind", ("wind", "windy", "breezy", "gusty", "blustery", "gale")),
    ("sun", ("sun", "sunny", "clear", "bright", "cloudless")),
    ("cloud", ("cloud", "cloudy", "overcast", "grey", "gray", "dull")),
    ("mild", ("mild", "pleasant", "temperate", "fine")),
)


@dataclass(frozen=True, slots=True)
class WeatherReading:
    """One observation, with its origin and its freshness both explicit."""

    #: A place *name*. Never a coordinate — coordinates are redacted from logs
    #: (see ``app.middleware``) and are not reintroduced here.
    place: str
    observed_at: datetime
    units: Units
    #: The service that measured this. ``None`` if and only if the user
    #: described it, in which case there is nothing honest to put here.
    source: str | None
    #: Explicit, never inferred by the reader.
    is_stale: bool
    #: True when this came from the user's own words rather than a measurement.
    described_by_user: bool

    #: The user's words, verbatim and truncated. Empty for machine readings.
    description: str | None = None
    #: Only ever a number somebody actually stated or measured.
    temperature: float | None = None
    #: Condition words recognised in whichever of the two the reading came from.
    conditions: tuple[str, ...] = field(default=())
    stale_after_seconds: int = STALE_AFTER_SECONDS
    #: How old the reading was when it was built, so freshness is auditable.
    age_seconds: float | None = None

    def __post_init__(self) -> None:
        if not (self.place or "").strip():
            raise ValueError("a reading needs a place name")
        if self.units not in UNITS:
            raise ValueError(f"units must be one of {UNITS!r}, got {self.units!r}")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware; pass an aware UTC datetime")
        if self.described_by_user:
            if self.source is not None:
                raise ValueError(
                    "a described_by_user reading must carry source=None — "
                    "naming a service the user did not consult would fabricate provenance"
                )
        elif not (self.source or "").strip():
            raise ValueError("a measured reading must name its source")

    @property
    def freshness(self) -> Literal["fresh", "stale"]:
        return "stale" if self.is_stale else "fresh"

    @property
    def origin(self) -> Literal["user_description", "provider"]:
        return "user_description" if self.described_by_user else "provider"


def classify_conditions(text: str) -> tuple[str, ...]:
    """Map a free-text description onto coarse condition labels.

    Lossy on purpose: it recognises words, and never converts a word into a
    number. "freezing" does not become a temperature.
    """
    lowered = (text or "").lower()
    found: list[str] = []
    for label, words in _CONDITION_WORDS:
        if any(word in lowered for word in words) and label not in found:
            found.append(label)
    return tuple(found)


def reading_from_user_description(
    *,
    place: str,
    description: str,
    units: str = "metric",
    observed_at: datetime | None = None,
    temperature: float | None = None,
    now: datetime | None = None,
    stale_after_seconds: int = STALE_AFTER_SECONDS,
) -> WeatherReading:
    """Build a reading from what the user said. Needs no provider and no key.

    ``temperature`` is accepted only because the user may have stated one; it
    is never derived from ``description``.
    """
    if units not in UNITS:
        raise ValueError(f"units must be one of {UNITS!r}, got {units!r}")
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:  # pragma: no cover - defensive
        raise ValueError("now must be timezone-aware")
    seen_at = observed_at or reference
    if seen_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware; pass an aware UTC datetime")

    age = (reference - seen_at).total_seconds()
    return WeatherReading(
        place=place.strip(),
        observed_at=seen_at,
        units=units,  # type: ignore[arg-type]
        source=None,
        is_stale=age > stale_after_seconds,
        described_by_user=True,
        description=(description or "").strip()[:500] or None,
        temperature=temperature,
        conditions=classify_conditions(description),
        stale_after_seconds=stale_after_seconds,
        age_seconds=age,
    )


@runtime_checkable
class WeatherProvider(Protocol):
    """What a real weather service would have to provide.

    Declared now so the adapter boundary exists before a vendor is chosen; no
    implementation in this build performs I/O.
    """

    #: Stable identifier recorded as ``WeatherReading.source``.
    name: str
    #: Whether this build can actually call it.
    available: bool
    #: ``implemented`` | ``unavailable`` — the labelling rule in the plan.
    status: str

    async def current(self, *, place: str, units: str = "metric") -> WeatherReading: ...


class UnavailableWeatherProvider:
    """The shipped provider. **UNAVAILABLE** — no vendor chosen, no credential.

    It is not a stub that returns plausible numbers: a fixture that reads as a
    live integration is the failure mode the plan forbids. It refuses, and the
    caller falls back to the user-described path or to no weather at all.
    """

    name = "unconfigured"
    available = False
    status = "unavailable"

    async def current(self, *, place: str, units: str = "metric") -> WeatherReading:
        raise CapabilityUnavailable(
            "Live weather is not available in this build: no weather provider has "
            "been selected or credentialed. Describe the weather instead and the "
            "reading will be labelled as yours.",
            detail={
                "provider": self.name,
                "status": self.status,
                "fallback": "user_description",
                "place": place,
                "units": units,
            },
        )


def build_weather_provider(mode: str = "unavailable") -> WeatherProvider:
    """Select the weather provider for this build.

    There is exactly one, and it is labelled unavailable. A future vendor
    adapter registers here rather than being constructed at call sites.
    """
    if mode != "unavailable":
        raise CapabilityUnavailable(
            f"No weather provider is registered under {mode!r}; "
            "this build ships only the unavailable provider."
        )
    return UnavailableWeatherProvider()


__all__ = [
    "STALE_AFTER_SECONDS",
    "UNITS",
    "UnavailableWeatherProvider",
    "Units",
    "WeatherProvider",
    "WeatherReading",
    "build_weather_provider",
    "classify_conditions",
    "reading_from_user_description",
]
