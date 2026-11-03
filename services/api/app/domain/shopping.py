"""Matching pieces to offers, with labels that cannot overclaim.

**`classify` is a pure function of evidence (§10), and the evidence this
build can gather caps the label.** A `confirmed_item` requires identifier
agreement: a GTIN, an MPN, or a retailer product id on both sides. The
curated catalogue carries none and a look's pieces carry none, so nothing
here can emit `confirmed_item` — the strongest honest claim about a match
made on category, colour and aesthetics is `similar_style`, and that is
the only label this module produces. The weaker labels are not a
limitation bolted on; they are what the evidence supports, enforced where
the label is made.

**An expired offer is labelled, never dropped.** A price that was true in
October is still information in December, as long as the card says
October. Dropping it would quietly shrink results toward whatever was
seeded most recently, which reads as availability signal and is not.

**Recommendations are derived from what the app already knows**: the
slots the stylist could not fill from the wardrobe, and the aesthetics the
person actually picked in taste. No engagement loop, no "popular right
now" dressed as personal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.taste import read_taste
from app.models.shopping import Offer, Retailer, ShopProduct
from app.models.stylist import Outfit

#: The one label this build's evidence supports. See the module docstring.
SIMILAR_STYLE = "similar_style"

#: How many recent outfits are consulted for unfilled slots.
GAP_OUTFITS = 10

MAX_RESULTS = 12


@dataclass(frozen=True, slots=True)
class Match:
    product: ShopProduct
    offer: Offer
    retailer: Retailer
    match_label: str
    #: Which fields agreed, so the label can be interrogated on the card.
    evidence: dict[str, list[str] | str]
    stale: bool


def _stale(offer: Offer, now: datetime) -> bool:
    expires = offer.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= now


def _score(product: ShopProduct, *, category_id: str | None, slot: str | None,
           colour: str | None, aesthetics: tuple[str, ...]) -> tuple[int, list[str]]:
    """How well a product answers the ask, and which fields said so."""
    matched: list[str] = []
    score = 0
    if category_id and product.category_id == category_id:
        score += 4
        matched.append("category")
    if slot and product.slot == slot:
        score += 2
        matched.append("slot")
    if colour and product.colour and product.colour == colour:
        score += 2
        matched.append("colour")
    overlap = set(aesthetics) & set(product.aesthetics or [])
    if overlap:
        score += len(overlap)
        matched.append("aesthetics")
    return score, matched


async def search(
    db: AsyncSession,
    *,
    category_id: str | None = None,
    slot: str | None = None,
    colour: str | None = None,
    aesthetics: tuple[str, ...] = (),
    limit: int = MAX_RESULTS,
    now: datetime | None = None,
) -> list[Match]:
    """Offers that resemble the ask, best first, labelled `similar_style`.

    Candidates are narrowed in SQL on the structured fields and ranked in
    Python, because the catalogue is curated-sized and the scoring is the
    thing that must stay readable.
    """
    moment = now or datetime.now(UTC)

    conditions = []
    if category_id or slot:
        narrow = []
        if category_id:
            narrow.append(ShopProduct.category_id == category_id)
        if slot:
            narrow.append(ShopProduct.slot == slot)
        conditions.append(sa.or_(*narrow))

    products = (
        await db.scalars(
            sa.select(ShopProduct)
            .options(selectinload(ShopProduct.offers), selectinload(ShopProduct.retailer))
            .where(*conditions)
        )
    ).all()

    scored: list[tuple[int, Match]] = []
    for product in products:
        score, matched = _score(
            product,
            category_id=category_id,
            slot=slot,
            colour=colour,
            aesthetics=aesthetics,
        )
        if score <= 0 or not product.offers:
            continue
        offer = product.offers[0]
        scored.append(
            (
                score,
                Match(
                    product=product,
                    offer=offer,
                    retailer=product.retailer,
                    match_label=SIMILAR_STYLE,
                    evidence={"matched": matched, "provider": "curated"},
                    stale=_stale(offer, moment),
                ),
            )
        )

    scored.sort(key=lambda pair: (-pair[0], pair[1].offer.price_minor))
    return [match for _, match in scored[:limit]]


#: How many offers one piece of a fit may show.
#:
#: Smaller than a recommendation section: there is one of these per
#: garment, so a four-piece outfit at the full count would be a
#: screen nobody scrolls to the end of.
MAX_PER_PIECE = 4


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    title: str
    #: Why these are being shown, in a sentence the card can carry.
    reason: str
    items: list[Match]


async def like_this_fit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    post_id: uuid.UUID,
    now: datetime | None = None,
) -> list[Section]:
    """Something like each garment in a posted fit, a section per piece.

    **This is what "shop the look" was always supposed to mean.** The
    row has existed since the beginning and pushed the generic
    recommendations screen: a shelf assembled from gaps in your own
    wardrobe and the aesthetics you picked, which is a perfectly good
    shelf and has nothing to do with the photograph you were looking
    at. The label promised this fit and delivered a shelf about
    nothing in particular.

    The identification is already done and already paid for. Reading
    a fit writes down each garment in it - the category, the colour -
    because the try-on and the caption both need that, and it is
    computed once per post for everybody. So this costs a catalogue
    query per piece and no model call at all.

    **It matches against the catalogue this app has.** That is the
    honest limit and it is visible in the result: a piece with
    nothing like it in the catalogue returns an empty section rather
    than a padded one, and a caller shows what it got. Searching the
    open web would be a different thing entirely - a retailer or
    search vendor, with its own contract, caching and attribution -
    and `search` below is the seam it would be added behind.

    Ordered as the outfit was described, so the sections read top to
    bottom the way somebody looked at the picture.
    """
    from app.domain import fit_descriptions

    pieces = await fit_descriptions.pieces_of(db, post_id=post_id)
    if not pieces:
        return []

    sections: list[Section] = []
    for piece in pieces:
        if not piece.category and not piece.colour:
            continue
        matches = await search(
            db,
            category_id=piece.category,
            colour=piece.colour,
            limit=MAX_PER_PIECE,
            now=now,
        )
        if not matches:
            continue
        named = " ".join(
            part for part in (piece.colour, piece.name or piece.category) if part
        )
        sections.append(
            Section(
                key=f"piece:{piece.position}",
                title=f"Like the {piece.name or piece.category}",
                # Says what it matched on, so a card that looks wrong
                # can be argued with rather than guessed about.
                reason=f"Matched to the {named} in this fit.",
                items=matches,
            )
        )
    return sections

async def recommendations(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> list[Section]:
    """What to look at, derived from gaps and taste. Sections may be empty
    and empty sections are omitted rather than padded."""
    sections: list[Section] = []

    # Slots the stylist recently could not fill from the wardrobe. The
    # honest shopping prompt: the app itself said something was missing.
    rows = (
        await db.scalars(
            sa.select(Outfit)
            .where(Outfit.user_id == user_id, Outfit.deleted_at.is_(None))
            .order_by(Outfit.created_at.desc())
            .limit(GAP_OUTFITS)
        )
    ).all()
    gap_slots: list[str] = []
    for outfit in rows:
        for slot in outfit.missing_slots or []:
            if slot not in gap_slots:
                gap_slots.append(slot)
    for slot in gap_slots[:3]:
        items = await search(db, slot=slot, now=now)
        if items:
            sections.append(
                Section(
                    key=f"gap-{slot}",
                    title=f"The {slot} the stylist could not fill",
                    reason="An outfit of yours has this slot open.",
                    items=items[:6],
                )
            )

    # The aesthetics the person picked, in their own words' order.
    taste = await read_taste(db, user_id=user_id)
    picked = tuple(taste.aesthetics or [])
    if picked:
        items = await search(db, aesthetics=picked, now=now)
        if items:
            sections.append(
                Section(
                    key="taste",
                    title="In your aesthetics",
                    reason="Matched to what you said you wear.",
                    items=items[:8],
                )
            )

    return sections


__all__ = ["GAP_OUTFITS", "Match", "MAX_RESULTS", "Section", "SIMILAR_STYLE", "recommendations", "search"]
