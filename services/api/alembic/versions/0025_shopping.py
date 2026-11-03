"""shopping: retailers, products, offers (§10 Phase B)

Revision ID: 0025_shopping
Revises: 0024_gift_ledger
Create Date: 2026-10-30

The curated catalogue the Phase B provider serves. The honesty properties
documented on the models — availability defaults `unverified`, retailer
verification defaults false, prices are integer minor units with a
retrieved/expires window — are all server defaults here, so a row written
by any future code path starts honest.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_shopping"
down_revision = "0024_gift_ledger"
branch_labels = None
depends_on = None

AVAILABILITY = ("unverified", "in_stock", "out_of_stock")


def _json(bind):  # type: ignore[no-untyped-def]
    return postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json(bind)

    availability: sa.types.TypeEngine
    if bind.dialect.name == "postgresql":
        availability = postgresql.ENUM(
            *AVAILABILITY, name="offer_availability", create_type=False
        )
        sa.Enum(*AVAILABILITY, name="offer_availability").create(bind, checkfirst=True)
    else:
        availability = sa.Enum(*AVAILABILITY, name="offer_availability")

    op.create_table(
        "retailers",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("homepage", sa.String(300), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "shop_products",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "retailer_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("retailers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(120), nullable=False),
        sa.Column("category_id", sa.String(64), nullable=False),
        sa.Column("slot", sa.String(32), nullable=False),
        sa.Column("colour", sa.String(40), nullable=True),
        sa.Column("aesthetics", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_shop_products_retailer_id", "shop_products", ["retailer_id"])
    op.create_index("ix_shop_products_category_id", "shop_products", ["category_id"])
    op.create_index("ix_shop_products_slot", "shop_products", ["slot"])

    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("shop_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("sizes", json_type, nullable=False),
        sa.Column(
            "availability",
            availability,
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("ships_to", json_type, nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(600), nullable=False),
        sa.Column("evidence", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_offers_product_id", "offers", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_offers_product_id", table_name="offers")
    op.drop_table("offers")
    op.drop_index("ix_shop_products_slot", table_name="shop_products")
    op.drop_index("ix_shop_products_category_id", table_name="shop_products")
    op.drop_index("ix_shop_products_retailer_id", table_name="shop_products")
    op.drop_table("shop_products")
    op.drop_table("retailers")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="offer_availability").drop(bind, checkfirst=True)
