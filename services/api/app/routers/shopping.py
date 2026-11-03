"""Shopping routes: search and recommendations over the curated catalogue.

`GET /v1/shopping/search` is the endpoint §10 names. The provider behind
it is the Phase B fixture adapter, and the payload says so in a field
rather than a comment, because a client must render that fact.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.deps import AuthDep, SessionDep
from app.domain import feed as feed_domain
from app.domain import shopping
from app.errors import ApiError
from app.schemas.shopping import (
    OfferMatchOut,
    RetailerOut,
    ShopRecommendationsOut,
    ShopSectionOut,
    ShoppingSearchOut,
)

router = APIRouter(prefix="/shopping", tags=["shopping"])


def _out(match: shopping.Match) -> OfferMatchOut:
    return OfferMatchOut(
        product_id=match.product.id,
        title=match.product.title,
        brand=match.product.brand,
        category_id=match.product.category_id,
        slot=match.product.slot,
        colour=match.product.colour,
        retailer=RetailerOut(
            name=match.retailer.name,
            homepage=match.retailer.homepage,
            verified=match.retailer.verified,
        ),
        price_minor=match.offer.price_minor,
        currency=match.offer.currency,
        sizes=list(match.offer.sizes or []),
        availability=match.offer.availability,  # type: ignore[arg-type]
        retrieved_at=match.offer.retrieved_at,
        stale=match.stale,
        source_url=match.offer.source_url,
        match_label=match.match_label,  # type: ignore[arg-type]
        evidence=match.evidence,
    )


@router.get("/search", response_model=ShoppingSearchOut)
async def search(
    db: SessionDep,
    ctx: AuthDep,
    category: str | None = Query(default=None),
    slot: str | None = Query(default=None),
    colour: str | None = Query(default=None),
    aesthetic: list[str] = Query(default=[]),
) -> ShoppingSearchOut:
    """Offers resembling the ask, best first.

    Every result is labelled with how much the match actually knows:
    `similar_style` is the ceiling the curated catalogue's evidence
    supports, and an unknown ask simply returns nothing.
    """
    items = await shopping.search(
        db,
        category_id=category,
        slot=slot,
        colour=colour,
        aesthetics=tuple(aesthetic),
    )
    return ShoppingSearchOut(items=[_out(match) for match in items])


@router.get("/recommendations", response_model=ShopRecommendationsOut)
async def recommendations(db: SessionDep, ctx: AuthDep) -> ShopRecommendationsOut:
    """What to look at, from the stylist's unfilled slots and your taste.

    Sections are omitted when empty rather than padded with "popular":
    a recommendation this app cannot explain is one it does not make.
    """
    sections = await shopping.recommendations(db, user_id=ctx.user_id)
    return ShopRecommendationsOut(
        sections=[
            ShopSectionOut(
                key=section.key,
                title=section.title,
                reason=section.reason,
                items=[_out(match) for match in section.items],
            )
            for section in sections
        ]
    )


@router.get("/for-fit/{post_id}", response_model=ShopRecommendationsOut)
async def for_fit(
    post_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> ShopRecommendationsOut:
    """Something like each garment in one posted fit, a section per piece.

    **What "shop the look" was always supposed to mean.** That row
    pushed the generic recommendations screen - a shelf built from
    gaps in your own wardrobe - which is a fine shelf and has
    nothing to do with the photograph it was tapped from.

    404 when the fit is not one this reader may see, which is the
    same answer as never having existed: the sections name the
    garments in it, so handing them over would describe a private
    fit to somebody who cannot open it.

    Empty sections are omitted and an empty list is a real answer -
    the catalogue simply has nothing like that garment. It is not
    padded, for the reason the recommendations route gives: a
    suggestion this app cannot explain is one it does not make.
    """
    if await feed_domain.one(db, user_id=ctx.user_id, post_id=post_id) is None:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    sections = await shopping.like_this_fit(
        db, user_id=ctx.user_id, post_id=post_id
    )
    return ShopRecommendationsOut(
        sections=[
            ShopSectionOut(
                key=section.key,
                title=section.title,
                reason=section.reason,
                items=[_out(match) for match in section.items],
            )
            for section in sections
        ]
    )
