"""Shopping shapes: offers with labels that say how much they know."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RetailerOut(BaseModel):
    name: str
    homepage: str
    #: §10: true only after a completed verification record, which this
    #: build cannot write. Rendered, never assumed.
    verified: bool


class OfferMatchOut(BaseModel):
    product_id: uuid.UUID
    title: str
    brand: str
    category_id: str
    slot: str
    colour: str | None = None
    retailer: RetailerOut
    price_minor: int
    currency: str
    sizes: list[str] = Field(default_factory=list)
    #: ``unverified`` for every curated row: nothing checked a shelf.
    availability: Literal["unverified", "in_stock", "out_of_stock"]
    #: When the price was true. The card shows this date.
    retrieved_at: datetime
    #: Past its window: shown with the label, never dropped (§10).
    stale: bool
    source_url: str
    #: The ceiling the evidence supports. ``confirmed_item`` needs
    #: identifier agreement this build does not have, so today only
    #: ``similar_style`` is ever emitted; the contract carries the others
    #: so a live feed does not change the shape.
    match_label: Literal["confirmed_item", "likely_match", "similar_style"]
    #: Which fields agreed, so the label can be interrogated.
    evidence: dict[str, list[str] | str] = Field(default_factory=dict)


class ShoppingSearchOut(BaseModel):
    items: list[OfferMatchOut] = Field(default_factory=list)
    #: Stated on the payload, not just the docs: these are curated
    #: references, and availability is not live.
    provider: Literal["curated"] = "curated"


class ShopLinkOut(BaseModel):
    """A place on the open web that appears to sell this piece.

    **Separate from `items`, and deliberately so.** `OfferMatchOut`
    carries a price, a currency, stock and the date the price was
    true, because a catalogue row knows all of that. A search result
    knows none of it, and forcing one into that shape would mean
    inventing a price - which is the exact failure the recommendation
    rules in this module exist to prevent. A link is offered as what
    it is: somewhere to go and look.
    """

    title: str
    retailer: str
    url: str


class ShopSectionOut(BaseModel):
    key: str
    title: str
    reason: str
    items: list[OfferMatchOut] = Field(default_factory=list)
    #: Where to buy this piece on the open web, when the catalogue
    #: has nothing like it - which, for a catalogue this size, is
    #: most of the time.
    links: list[ShopLinkOut] = Field(default_factory=list)


class ShopRecommendationsOut(BaseModel):
    sections: list[ShopSectionOut] = Field(default_factory=list)
    provider: Literal["curated"] = "curated"
    #: True while the fit is still being read.
    #:
    #: The sections come from the garments a vision pass names in the
    #: photograph, and a pin nobody has opened has not been read yet.
    #: The client polls rather than concluding the fit has nothing
    #: shoppable in it.
    working: bool = False
