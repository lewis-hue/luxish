"""Where to buy it, as the client renders it."""

from __future__ import annotations

from pydantic import BaseModel


class ShopOut(BaseModel):
    name: str
    #: An OpenStreetMap `shop` tag: clothes, shoes, jewelry and so on.
    kind: str
    latitude: float
    longitude: float
    #: From the coarse point they sent. Null if it could not be worked out.
    distance_m: int | None = None
    brand: str | None = None
    opening_hours: str | None = None


class NearbyShopsOut(BaseModel):
    items: list[ShopOut]
    #: **False means nobody could be asked**, not that there are no
    #: shops. The directory upstream is a free service that is
    #: routinely overloaded, and an empty list would tell somebody
    #: their neighbourhood has no clothes shops in it.
    reachable: bool = True
    #: Required by ODbL wherever this data is shown.
    attribution: str
    note: str | None = None


class RetailerSearchOut(BaseModel):
    items: list[dict]
    #: False until a shopping provider is connected. The screen says
    #: so rather than showing an empty shelf.
    configured: bool = False
    note: str | None = None
