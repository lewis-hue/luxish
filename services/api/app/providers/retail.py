"""Where to actually buy the thing. Two very different sources.

**Shops near somebody** come from OpenStreetMap, through the public
Overpass API. Free, no credential, real data: a query around Nairobi
returns named clothing and shoe shops with their coordinates, brands
and opening hours. This is implemented and works today.

**Named retailers** - Zara, H&M, a Shopify storefront - do not have a
usable public search between them. Zara publishes no API; Shopify's
Storefront API is per-store and needs a token issued by that store's
owner; the aggregators that do cover them (SerpAPI, Google Shopping)
are paid and keyed. So that half is a seam with no implementation
behind it, and it says so rather than returning an empty list that
reads like "nothing matched".

The distinction matters to somebody using this: "no shops near you
sell that" is an answer, and "we cannot search Zara" is a missing
feature. A single empty list would say the first while meaning the
second.

**Attribution is not optional.** OpenStreetMap data is ODbL, which
requires the source to be credited wherever the data is shown.
`ATTRIBUTION` travels with every result for that reason, and the
client renders it.

**Coordinates are rounded before they leave this service.** The
consent this is gated on is `location_coarse`, and sending a precise
fix to a third party would collect more than was agreed to. Two
decimal places is about a kilometre, which is the right grain for
"shops near me" anyway.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: Required by ODbL wherever this data is shown.
ATTRIBUTION = "Shop locations © OpenStreetMap contributors"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: Mirrors, tried in order.
#:
#: The main instance returned a 502 during testing and is routinely
#: overloaded - it is a free service carrying the whole world's
#: queries. One unlucky request should not be the end of the feature,
#: and these are the community-published mirrors of the same data.
OVERPASS_MIRRORS: tuple[str, ...] = (
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

#: Overpass refuses an anonymous client with 406. Verified
#: 2026-11-03: the identical query returns 406 without this header and
#: JSON with it.
USER_AGENT = "LUXish/1.0 (+https://luxish.app; shop lookup)"

#: Shop tags worth returning for a fashion app.
#:
#: A closed list rather than everything tagged `shop`: a supermarket
#: is not an answer to "where can I buy cream trousers", and the
#: query is cheaper for being narrow.
SHOP_KINDS: tuple[str, ...] = (
    "clothes",
    "boutique",
    "shoes",
    "bag",
    "jewelry",
    "fashion_accessories",
    "department_store",
    "second_hand",
)

#: How far out to look, in metres. A walkable-ish radius in a city.
DEFAULT_RADIUS_M = 5000

#: Overpass is a free community service shared by everybody.
#:
#: **Measured, because the first guess was wrong.** Three identical
#: queries took 2.2s (a busy page, not even JSON), 25.1s and 44.6s.
#: A 25-second budget failed outright. So the budget is generous and
#: the answer is cached hard - the alternative to caching is hammering
#: a free service, which gets the whole app blocked rather than one
#: user.
OVERPASS_TIMEOUT_S = 50
#: The HTTP read budget, which has to clear the server's own.
CLIENT_TIMEOUT_S = 70
MOST_SHOPS = 12

#: How long a set of shops is reused for a given place.
#:
#: A day. Shops do not open and close hourly, the coordinates are
#: rounded to about a kilometre so neighbours share an entry, and a
#: slow upstream makes the first lookup in an area the only slow one.
SHOPS_CACHE_SECONDS = 24 * 60 * 60

#: Rounded to about a kilometre before the query leaves this service.
COARSE_PLACES = 2


@dataclass(frozen=True)
class Shop:
    """One physical shop somebody could walk into."""

    name: str
    kind: str
    latitude: float
    longitude: float
    #: Metres from where they said they were, when known.
    distance_m: int | None = None
    brand: str | None = None
    opening_hours: str | None = None


@dataclass(frozen=True)
class RetailSearch:
    """What a retailer search returned, and whether it could run.

    `configured` is the honest half. False means nobody searched -
    not that nothing was found - and the screen must say so.
    """

    items: tuple[Any, ...] = ()
    configured: bool = False
    note: str | None = None


def coarse(value: float) -> float:
    """A coordinate at the grain the consent actually covers."""
    return round(value, COARSE_PLACES)


class NearbyShops(Protocol):
    #: `None` means nobody could be asked; `[]` means none were found.
    async def around(
        self, *, latitude: float, longitude: float, radius_m: int = DEFAULT_RADIUS_M
    ) -> list[Shop] | None: ...


class OverpassShops:
    """Clothing shops near a point, from OpenStreetMap.

    No credential and no account. The cost is that it is a shared
    free service: the timeout is short, the result count is small,
    and a failure is an empty list rather than an exception, because
    a shop lookup falling over must not take an answer down with it.
    """

    def __init__(self, *, url: str = OVERPASS_URL, client: Any | None = None) -> None:
        self._url = url
        self._client = client

    def query_for(
        self, *, latitude: float, longitude: float, radius_m: int
    ) -> str:
        kinds = "|".join(SHOP_KINDS)
        return (
            f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];"
            f'node["shop"~"^({kinds})$"]'
            f"(around:{radius_m},{coarse(latitude)},{coarse(longitude)});"
            f"out body {MOST_SHOPS};"
        )

    async def around(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_m: int = DEFAULT_RADIUS_M,
    ) -> list[Shop] | None:
        """Shops near a point, or `None` if nobody could be asked.

        **`None` and `[]` are different answers and conflating them
        was a real bug.** A 502 from an overloaded mirror cached as
        an empty list told everybody in that area there were no shops
        near them, for a day. `[]` means the query ran and found
        nothing; `None` means it never ran, and nothing caches it.
        """

        query = self.query_for(
            latitude=latitude, longitude=longitude, radius_m=radius_m
        )
        for url in self._urls():
            payload = await self._ask(url, query)
            if payload is not None:
                return parse_overpass(
                    payload, origin=(coarse(latitude), coarse(longitude))
                )
        return None

    def _urls(self) -> tuple[str, ...]:
        if self._url != OVERPASS_URL:
            # Explicitly pointed somewhere, so do not wander.
            return (self._url,)
        return OVERPASS_MIRRORS

    async def _ask(self, url: str, query: str):
        """One mirror. Returns the payload, or None to try the next."""
        import httpx

        client = self._client or httpx.AsyncClient(timeout=CLIENT_TIMEOUT_S)
        owned = self._client is None
        try:
            reply = await client.post(
                url,
                data={"data": query},
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
            )
            reply.raise_for_status()
            return reply.json()
        except Exception as caught:  # noqa: BLE001
            logger.warning(
                "overpass mirror %s unavailable: %s: %s",
                url,
                type(caught).__name__,
                caught,
            )
            return None
        finally:
            if owned:
                await client.aclose()


def parse_overpass(
    payload: Any, *, origin: tuple[float, float] | None = None
) -> list[Shop]:
    """Overpass JSON as shops, nearest first. Never raises.

    Anything unnamed is dropped: "a clothes shop, somewhere over
    there" is not a thing anybody can go to.
    """
    elements = (payload or {}).get("elements") or []
    found: list[Shop] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        try:
            lat = float(element["lat"])
            lon = float(element["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        found.append(
            Shop(
                name=name[:120],
                kind=str(tags.get("shop") or "shop"),
                latitude=lat,
                longitude=lon,
                distance_m=(
                    metres_between(origin, (lat, lon)) if origin else None
                ),
                brand=(tags.get("brand") or None),
                opening_hours=(tags.get("opening_hours") or None),
            )
        )
    found.sort(key=lambda s: (s.distance_m if s.distance_m is not None else 10**9, s.name))
    return found[:MOST_SHOPS]


def metres_between(
    first: tuple[float, float], second: tuple[float, float]
) -> int:
    """Great-circle distance, to the metre.

    Haversine rather than a flat approximation: the app ships to
    several countries and a flat earth is wrong by enough to reorder
    a list at the latitudes some of them are at.
    """
    import math

    radius = 6_371_000.0
    lat1, lon1 = math.radians(first[0]), math.radians(first[1])
    lat2, lon2 = math.radians(second[0]), math.radians(second[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return int(round(2 * radius * math.asin(math.sqrt(a))))


class CachedShops:
    """`OverpassShops` with a day of memory, keyed by coarse place.

    **Not an optimisation.** Upstream takes between two and
    forty-five seconds and is a free service shared by everybody, so
    an uncached lookup is both a bad experience and bad manners. The
    coordinates are already rounded to about a kilometre, which is
    what makes a cache key shared between neighbours rather than one
    entry per person.

    A missing or broken cache degrades to calling upstream, never to
    failing: this hangs off the end of an answer and must not be able
    to take one down.
    """

    def __init__(self, inner: Any, *, redis: Any | None = None) -> None:
        self._inner = inner
        self._redis = redis

    def _key(self, latitude: float, longitude: float, radius_m: int) -> str:
        return f"shops:{coarse(latitude)}:{coarse(longitude)}:{radius_m}"

    async def around(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_m: int = DEFAULT_RADIUS_M,
    ) -> list[Shop] | None:
        import json

        key = self._key(latitude, longitude, radius_m)
        if self._redis is not None:
            try:
                held = await self._redis.get(key)
                if held:
                    return [
                        Shop(**row) for row in json.loads(held)
                    ]
            except Exception as caught:  # noqa: BLE001
                logger.warning("shop cache unreadable: %s", caught)

        shops = await self._inner.around(
            latitude=latitude, longitude=longitude, radius_m=radius_m
        )
        if shops is None:
            # Nobody could be asked. Not cached, and reported as
            # unknown rather than as "no shops near you" - caching a
            # 502 told a whole neighbourhood there were no shops for
            # a day, which is the bug this distinction exists for.
            return None

        # A genuinely empty result *is* cached: a place with no shops
        # should not re-ask a slow free service every time somebody
        # there opens the app.
        if self._redis is not None:
            try:
                await self._redis.setex(
                    key,
                    SHOPS_CACHE_SECONDS,
                    json.dumps([vars(s) for s in shops]),
                )
            except Exception as caught:  # noqa: BLE001
                logger.warning("could not cache shops: %s", caught)
        return shops


class NamedRetailers(Protocol):
    async def search(self, *, query: str, limit: int = 6) -> RetailSearch: ...


class NoRetailerConfigured:
    """The honest default for Zara, H&M, Shopify and the rest.

    **Not an empty result.** Between them these have no usable public
    search: Zara publishes no API, a Shopify storefront needs a token
    from that store's owner, and the aggregators that cover them are
    paid and keyed. Returning `[]` would tell somebody nothing
    matched; this tells them nobody looked.
    """

    async def search(self, *, query: str, limit: int = 6) -> RetailSearch:
        return RetailSearch(
            items=(),
            configured=False,
            note=(
                "Searching the big stores needs a shopping provider "
                "connecting first."
            ),
        )


__all__ = [
    "ATTRIBUTION",
    "COARSE_PLACES",
    "DEFAULT_RADIUS_M",
    "CLIENT_TIMEOUT_S",
    "MOST_SHOPS",
    "SHOPS_CACHE_SECONDS",
    "OVERPASS_MIRRORS",
    "OVERPASS_URL",
    "SHOP_KINDS",
    "USER_AGENT",
    "NamedRetailers",
    "NearbyShops",
    "NoRetailerConfigured",
    "CachedShops",
    "OverpassShops",
    "RetailSearch",
    "Shop",
    "coarse",
    "metres_between",
    "parse_overpass",
]
