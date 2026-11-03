"""Where to buy it: shops near somebody, and the big stores.

Its own route rather than part of the stylist's stream, and that is a
measured decision. Three identical lookups upstream took 2.2, 25.1
and 44.6 seconds; folding that into the answer would stall a reply
that otherwise arrives in six. So the stylist streams its answer and
the client asks this afterwards, with the gaps the verdict named.

**Location is sent, never stored.** There is no column for it
anywhere. The coordinates arrive in the query string, are rounded to
about a kilometre before they leave this service, and are gone when
the request ends. The consent gate is `location_coarse`, which is
exactly what that describes.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import AuthDep, SessionDep
from app.errors import ApiError
from app.schemas.shops import NearbyShopsOut, RetailerSearchOut, ShopOut

router = APIRouter(prefix="/shops", tags=["shops"])


@router.get("/nearby", response_model=NearbyShopsOut)
async def nearby(
    db: SessionDep,
    ctx: AuthDep,
    lat: float = Query(ge=-90.0, le=90.0),
    lon: float = Query(ge=-180.0, le=180.0),
    radius_m: int = Query(default=5000, ge=250, le=20000),
) -> NearbyShopsOut:
    """Clothing shops near a point, from OpenStreetMap.

    **Refused without `location_coarse`.** Somebody has to have
    agreed to this before their whereabouts is sent anywhere, and the
    refusal names the consent so the client can ask for it rather
    than showing an error.
    """
    from app.domain import consents as consent_domain
    from app.providers.retail import (
        ATTRIBUTION,
        CachedShops,
        OverpassShops,
    )

    # `list_consents` returns an entry for every kind, so "never
    # asked" is distinguishable from "declined" - both refuse here,
    # and the client can tell which to say.
    standing = await consent_domain.list_consents(db, user_id=ctx.user_id)
    held = standing.get("location_coarse")
    allowed = bool(held and held.granted_at and not held.revoked_at)
    if not allowed:
        raise ApiError(
            "Turn on coarse location and I can find shops near you.",
            status_code=403,
            code="location_consent_required",
        )

    shops = await CachedShops(OverpassShops(), redis=_redis()).around(
        latitude=lat, longitude=lon, radius_m=radius_m
    )
    if shops is None:
        # Nobody could be asked. Said plainly rather than as an empty
        # list, which would read as "there are no shops near you".
        return NearbyShopsOut(
            items=[],
            reachable=False,
            attribution=ATTRIBUTION,
            note="The shop directory is not answering just now.",
        )
    return NearbyShopsOut(
        items=[
            ShopOut(
                name=s.name,
                kind=s.kind,
                latitude=s.latitude,
                longitude=s.longitude,
                distance_m=s.distance_m,
                brand=s.brand,
                opening_hours=s.opening_hours,
            )
            for s in shops
        ],
        reachable=True,
        attribution=ATTRIBUTION,
    )


@router.get("/retailers", response_model=RetailerSearchOut)
async def retailers(
    db: SessionDep,
    ctx: AuthDep,
    q: str = Query(min_length=1, max_length=120),
) -> RetailerSearchOut:
    """The big stores - Zara, H&M, a Shopify storefront.

    **Answers honestly that it cannot search them.** None of them
    has a usable public search: Zara publishes no API, a Shopify
    storefront needs a token from that store's owner, and the
    aggregators that cover them are paid and keyed. Returning an
    empty list would tell somebody nothing matched; this tells them
    nobody looked, which is the true and more useful thing.
    """
    from app.providers.retail import NoRetailerConfigured

    found = await NoRetailerConfigured().search(query=q)
    return RetailerSearchOut(
        items=[],
        configured=found.configured,
        note=found.note,
    )


def _redis():
    """The shared client, or None. A missing cache is slower, not broken."""
    try:
        from redis.asyncio import Redis

        from app.config import get_settings

        return Redis.from_url(get_settings().redis_url)
    except Exception:  # noqa: BLE001
        return None
