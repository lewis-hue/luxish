"""Retailers, products and offers: §10's shapes, honestly populated.

**The provider behind these tables is a curated fixture and every row says
so.** Live retailer and affiliate feeds are blocked on commercial
agreements (INTEGRATION-MATRIX); what ships now is the Phase B adapter the
roadmap names: a seeded catalogue with real outbound URLs, behind the same
interface a live feed implements. Three honesty rules are schema, not
discipline:

* ``Offer.availability`` only holds ``unverified`` today, because nothing
  has checked a shelf. A live feed adds its values to the enum; no seeded
  row can ever claim stock it never saw.
* ``Retailer.verified`` defaults false and nothing in this build can set
  it true, because §10 requires a completed verification record first and
  the verification operation lives in the admin surface, which is planned.
* Prices are ``(price_minor, currency)`` integers (ADR-011) stamped with
  ``retrieved_at``/``expires_at``, so a card can say when the price was
  true instead of implying it still is.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    JSONB,
    Base,
    TimestampMixin,
    UTCDateTime,
    named_enum,
    uuid_fk,
    uuid_pk,
)

#: What a seeded offer can say about stock: nothing. Live feeds extend this
#: with ``in_stock`` / ``out_of_stock`` when one exists to ask.
OFFER_AVAILABILITY: tuple[str, ...] = ("unverified", "in_stock", "out_of_stock")

offer_availability_enum = named_enum("offer_availability", *OFFER_AVAILABILITY)


class Retailer(Base, TimestampMixin):
    __tablename__ = "retailers"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    homepage: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    #: §10: a verified badge requires a completed verification record.
    #: Nothing in this build writes one, so this stays false everywhere.
    verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )


class ShopProduct(Base, TimestampMixin):
    __tablename__ = "shop_products"
    __table_args__ = (
        sa.Index("ix_shop_products_category_id", "category_id"),
        sa.Index("ix_shop_products_slot", "slot"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    retailer_id: Mapped[uuid.UUID] = uuid_fk("retailers.id")
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    brand: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    #: The app's own piece vocabulary (`tshirt`, `trousers`, `jacket`...),
    #: so a look's piece can be matched without free-text guessing.
    category_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    #: The outfit slot vocabulary (`tops`, `bottoms`, `outerwear`...).
    slot: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    colour: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    #: Aesthetic ids from the app's taxonomy, for taste matching.
    aesthetics: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    offers: Mapped[list[Offer]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    retailer: Mapped[Retailer] = relationship()


class Offer(Base, TimestampMixin):
    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = uuid_fk("shop_products.id")
    price_minor: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    sizes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    availability: Mapped[str] = mapped_column(
        offer_availability_enum,
        nullable=False,
        default="unverified",
        server_default="unverified",
    )
    ships_to: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    #: When this price was true, and until when it may be repeated without
    #: the `stale` label. §10: an expired offer is labelled, never dropped.
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    source_url: Mapped[str] = mapped_column(sa.String(600), nullable=False)
    #: Extra provenance a live feed would carry. The fixture stamps
    #: ``{"provider": "curated"}``, so no row can shed its origin.
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    product: Mapped[ShopProduct] = relationship(back_populates="offers")
