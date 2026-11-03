"""Finding somewhere to actually buy the thing.

Two sources with opposite characters, and the tests are mostly about
keeping them distinguishable. Shops near somebody are real data from
OpenStreetMap; the big named retailers have no usable public search
between them, and an empty list from that half would read as "nothing
matched" when it means "nobody looked".
"""

from __future__ import annotations

import pytest

from app.providers.retail import (
    COARSE_PLACES,
    MOST_SHOPS,
    OVERPASS_MIRRORS,
    OVERPASS_URL,
    USER_AGENT,
    CachedShops,
    Shop,
    NoRetailerConfigured,
    OverpassShops,
    coarse,
    metres_between,
    parse_overpass,
)

NAIROBI = (-1.2921, 36.8219)


def node(**tags):
    lat = tags.pop("lat", -1.30)
    lon = tags.pop("lon", 36.80)
    return {"type": "node", "id": 1, "lat": lat, "lon": lon, "tags": tags}


# --------------------------------------------------------------------------- #
# Reading the data
# --------------------------------------------------------------------------- #
def test_a_shop_comes_back_with_what_somebody_needs_to_find_it() -> None:
    shops = parse_overpass(
        {"elements": [node(name="Bata", shop="shoes", brand="Bata",
                           opening_hours="09:00-20:00")]}
    )
    assert len(shops) == 1
    assert shops[0].name == "Bata"
    assert shops[0].kind == "shoes"
    assert shops[0].brand == "Bata"
    assert shops[0].opening_hours == "09:00-20:00"


def test_an_unnamed_shop_is_dropped() -> None:
    """"A clothes shop, somewhere over there" is not somewhere to go."""
    shops = parse_overpass(
        {"elements": [node(shop="clothes"), node(name="Real One", shop="clothes")]}
    )
    assert [s.name for s in shops] == ["Real One"]


def test_nearest_comes_first() -> None:
    far = node(name="Far", shop="clothes", lat=-1.40, lon=36.90)
    near = node(name="Near", shop="clothes", lat=-1.295, lon=36.825)
    shops = parse_overpass({"elements": [far, near]}, origin=NAIROBI)
    assert [s.name for s in shops] == ["Near", "Far"]
    assert shops[0].distance_m < shops[1].distance_m


def test_a_malformed_element_does_not_lose_the_rest() -> None:
    shops = parse_overpass(
        {
            "elements": [
                "not a dict",
                {"type": "node", "tags": {"name": "No coords", "shop": "clothes"}},
                node(name="Fine", shop="clothes"),
            ]
        }
    )
    assert [s.name for s in shops] == ["Fine"]


def test_an_empty_or_broken_payload_is_an_empty_list() -> None:
    for payload in (None, {}, {"elements": None}, {"elements": []}):
        assert parse_overpass(payload) == []


def test_the_result_count_is_capped() -> None:
    many = {"elements": [node(name=f"Shop {i}", shop="clothes") for i in range(40)]}
    assert len(parse_overpass(many)) == MOST_SHOPS


# --------------------------------------------------------------------------- #
# Not sending more location than was agreed to
# --------------------------------------------------------------------------- #
def test_coordinates_are_coarsened_before_they_leave() -> None:
    """**The consent is `location_coarse`.**

    A precise fix handed to a third party collects more than was
    agreed to. Two decimal places is about a kilometre, which is the
    right grain for "shops near me" anyway.
    """
    assert coarse(-1.29213456) == -1.29
    assert COARSE_PLACES == 2


def test_the_query_carries_only_the_coarse_point() -> None:
    query = OverpassShops().query_for(
        latitude=-1.29213456, longitude=36.82194321, radius_m=4000
    )
    assert "-1.29," in query
    assert "36.82" in query
    assert "1.29213456" not in query, "the precise latitude reached the query"
    assert "36.82194321" not in query


def test_the_query_asks_only_for_places_that_sell_clothes() -> None:
    query = OverpassShops().query_for(latitude=0.0, longitude=0.0, radius_m=1000)
    assert "clothes" in query and "shoes" in query
    assert "supermarket" not in query


# --------------------------------------------------------------------------- #
# Distance
# --------------------------------------------------------------------------- #
def test_distance_is_great_circle_not_flat() -> None:
    """The app ships to several countries; a flat earth reorders the
    list at some of their latitudes."""
    # Roughly a kilometre north of the city centre.
    assert 950 <= metres_between(NAIROBI, (-1.2831, 36.8219)) <= 1050


def test_distance_to_the_same_point_is_zero() -> None:
    assert metres_between(NAIROBI, NAIROBI) == 0


# --------------------------------------------------------------------------- #
# The half that is not implemented
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_the_big_stores_say_nobody_looked() -> None:
    """**Not an empty list.**

    "No shops near you sell that" is an answer. "We cannot search
    Zara" is a missing feature. A bare `[]` would say the first while
    meaning the second.
    """
    got = await NoRetailerConfigured().search(query="cream trousers")
    assert got.items == ()
    assert got.configured is False
    assert got.note and "provider" in got.note.lower()


def test_the_user_agent_is_set() -> None:
    """Verified live: Overpass answers 406 to an anonymous client and
    returns JSON with this header."""
    assert "LUXish" in USER_AGENT


@pytest.mark.anyio
async def test_an_unreachable_overpass_says_so_rather_than_raising() -> None:
    """A shop lookup hangs off the end of an answer and must not take
    one down. It returns `None`, not `[]` - see the next test."""

    class Dead:
        async def post(self, *a, **k):
            raise RuntimeError("no network")

        async def aclose(self):
            pass

    shops = await OverpassShops(client=Dead()).around(
        latitude=NAIROBI[0], longitude=NAIROBI[1]
    )
    assert shops is None


@pytest.mark.anyio
async def test_a_failure_is_never_cached_as_no_shops_here() -> None:
    """**A real bug, caught by running it.**

    The main Overpass instance returned a 502, the cache stored that
    as an empty list, and everybody within a kilometre was told there
    were no shops near them for the next day. `None` means nobody
    could be asked and is never written; `[]` means the query ran.
    """

    class Dead:
        async def post(self, *a, **k):
            raise RuntimeError("502")

        async def aclose(self):
            pass

    written: dict[str, str] = {}

    class Cache:
        async def get(self, key):
            return written.get(key)

        async def setex(self, key, ttl, value):
            written[key] = value

    shops = await CachedShops(
        OverpassShops(client=Dead()), redis=Cache()
    ).around(latitude=NAIROBI[0], longitude=NAIROBI[1])

    assert shops is None
    assert written == {}, "a failure was cached as an answer"


@pytest.mark.anyio
async def test_a_genuinely_empty_place_is_cached() -> None:
    """The opposite case. Somewhere with no shops should not re-ask a
    slow free service every time somebody there opens the app."""
    written: dict[str, str] = {}

    class Nowhere:
        async def around(self, **kwargs):
            return []

    class Cache:
        async def get(self, key):
            return written.get(key)

        async def setex(self, key, ttl, value):
            written[key] = value

    shops = await CachedShops(Nowhere(), redis=Cache()).around(
        latitude=NAIROBI[0], longitude=NAIROBI[1]
    )
    assert shops == []
    assert written, "an honest empty answer was not cached"


@pytest.mark.anyio
async def test_a_second_ask_is_served_from_the_cache() -> None:
    calls = {"n": 0}
    held: dict[str, str] = {}

    class Counting:
        async def around(self, **kwargs):
            calls["n"] += 1
            return [Shop(name="A shop", kind="clothes", latitude=0.0, longitude=0.0)]

    class Cache:
        async def get(self, key):
            return held.get(key)

        async def setex(self, key, ttl, value):
            held[key] = value

    shops = CachedShops(Counting(), redis=Cache())
    first = await shops.around(latitude=NAIROBI[0], longitude=NAIROBI[1])
    second = await shops.around(latitude=NAIROBI[0], longitude=NAIROBI[1])
    assert calls["n"] == 1, "upstream was asked twice for the same place"
    assert [s.name for s in first] == [s.name for s in second]


def test_there_is_more_than_one_mirror() -> None:
    """The main instance 502s under load; one unlucky request must not
    be the end of the feature."""
    assert len(OVERPASS_MIRRORS) > 1
    assert OVERPASS_MIRRORS[0] == OVERPASS_URL
