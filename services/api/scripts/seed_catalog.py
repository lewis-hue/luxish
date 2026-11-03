"""Seed the curated shopping catalogue (§10's Phase B provider).

**What this is and is not.** Every row is a curated reference: a real
retailer, a plausible piece in that retailer's actual range, and an
outbound URL that lands the person on that retailer's own search for the
piece. No price was scraped and no shelf was checked, which is why every
offer carries ``availability="unverified"``, an ``evidence`` stamp of
``{"provider": "curated"}``, and a ``retrieved_at`` of the moment this ran
— the card renders "checked <date>", and that claim is true.

Prices are indicative integers in KES minor units, chosen to sit inside
each retailer's published range for the piece class. They exist so the
screens can be built and judged with realistic numbers on them; the
`curated` provider label travels with every payload so no client renders
them as live quotes.

Idempotent on (retailer slug, product title): re-running refreshes the
offer window rather than duplicating the shelf.

    python scripts/seed_catalog.py
    python scripts/seed_catalog.py --remove
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402

import app.models  # noqa: E402, F401
from app.config import get_settings  # noqa: E402
from app.db.session import build_engine, session_factory  # noqa: E402
from app.models.shopping import Offer, Retailer, ShopProduct  # noqa: E402

#: How long a curated price may be repeated before the card labels it
#: stale. Thirty days: long enough to be useful, short enough to be honest.
WINDOW = timedelta(days=30)

#: slug, name, homepage, search URL template.
RETAILERS: list[tuple[str, str, str, str]] = [
    ("zara", "Zara", "https://www.zara.com", "https://www.zara.com/ke/en/search?searchTerm={q}"),
    ("hm", "H&M", "https://www2.hm.com", "https://www2.hm.com/en_asia5/search-results.html?q={q}"),
    ("cos", "COS", "https://www.cos.com", "https://www.cos.com/en/search.html?q={q}"),
    ("mango", "Mango", "https://shop.mango.com", "https://shop.mango.com/ke/en/search?q={q}"),
    ("asos", "ASOS", "https://www.asos.com", "https://www.asos.com/search/?q={q}"),
    ("nike", "Nike", "https://www.nike.com", "https://www.nike.com/w?q={q}"),
    ("vivo", "Vivo Fashion", "https://vivofashiongroup.com", "https://vivofashiongroup.com/search?q={q}"),
]

#: retailer slug, title, brand, category_id, slot, colour, aesthetics,
#: price in whole KES. Categories and slots come from the app's own piece
#: vocabulary so a look's piece matches without free-text guessing.
PRODUCTS: list[tuple[str, str, str, str, str, str | None, list[str], int]] = [
    # Tops
    ("zara", "Boxy heavyweight t-shirt", "Zara", "tshirt", "tops", "charcoal", ["streetwear", "skater", "elevated-basics"], 2990),
    ("hm", "Oversized graphic tee", "H&M", "tshirt", "tops", "white", ["streetwear", "y2k", "skater"], 1790),
    ("cos", "Poplin shirt, relaxed cut", "COS", "shirt", "tops", "white", ["clean-girl", "minimalist", "smart-casual"], 8990),
    ("mango", "Cream lace blouse", "Mango", "blouse", "tops", "cream", ["downtown-romantic", "coquette"], 4990),
    ("asos", "Fitted baby tee", "ASOS DESIGN", "tshirt", "tops", "white", ["y2k", "balletcore"], 1590),
    ("cos", "Fine merino crew neck", "COS", "knitwear", "tops", "navy", ["minimalist", "smart-casual", "elevated-basics"], 10990),
    ("vivo", "Ankara print shirt", "Vivo", "shirt", "tops", None, ["heritage", "colour"], 3490),
    # Bottoms
    ("zara", "Wide-leg cargo trousers", "Zara", "trousers", "bottoms", "olive", ["streetwear", "gorpcore", "utility"], 4990),
    ("hm", "Low-rise baggy jeans", "H&M", "jeans", "bottoms", "indigo", ["y2k", "skater", "denim"], 3990),
    ("cos", "Pleated wool trousers", "COS", "trousers", "bottoms", "charcoal", ["dark-academia", "smart-casual", "office"], 12990),
    ("mango", "Pleated mini skirt", "Mango", "skirt", "bottoms", "black", ["downtown-romantic", "coquette", "grunge"], 3990),
    ("asos", "Straight tailored trousers", "ASOS DESIGN", "trousers", "bottoms", "black", ["smart-casual", "monochrome", "office"], 3290),
    ("zara", "Satin slip skirt", "Zara", "skirt", "bottoms", "ivory", ["balletcore", "date-night", "quiet-luxury"], 3990),
    # Outerwear
    ("zara", "Oversized leather-effect jacket", "Zara", "jacket", "outerwear", "black", ["downtown-romantic", "grunge", "mob-wife"], 8990),
    ("hm", "Boxy varsity jacket", "H&M", "jacket", "outerwear", "navy", ["streetwear", "blokecore", "y2k"], 5490),
    ("cos", "Wool-blend overcoat", "COS", "coat", "outerwear", "camel", ["quiet-luxury", "smart-casual", "minimalist"], 24990),
    ("mango", "Relaxed blazer", "Mango", "blazer", "outerwear", "beige", ["smart-casual", "office-siren", "elevated-basics"], 8990),
    ("asos", "Brown tweed blazer", "ASOS DESIGN", "blazer", "outerwear", "brown", ["dark-academia", "heritage"], 6490),
    ("nike", "Technical shell jacket", "Nike", "jacket", "outerwear", "black", ["gorpcore", "techwear", "athleisure"], 12990),
    # Shoes
    ("nike", "Chunky high-top trainers", "Nike", "shoes", "shoes", "white", ["streetwear", "y2k", "athleisure"], 11990),
    ("asos", "Chunky lace-up knee boots", "ASOS DESIGN", "shoes", "shoes", "black", ["downtown-romantic", "grunge", "mob-wife"], 7990),
    ("zara", "Leather penny loafers", "Zara", "shoes", "shoes", "brown", ["dark-academia", "smart-casual", "office"], 6990),
    ("hm", "Ballet flats", "H&M", "shoes", "shoes", "black", ["balletcore", "coquette", "clean-girl"], 2490),
    ("vivo", "Leather sandals", "Vivo", "shoes", "shoes", "tan", ["heritage", "minimalist"], 2990),
    # Accessories
    ("zara", "Small shoulder bag", "Zara", "bag", "accessories", "black", ["y2k", "date-night", "monochrome"], 3990),
    ("cos", "Structured leather tote", "COS", "bag", "accessories", "tan", ["quiet-luxury", "office", "smart-casual"], 17990),
    ("mango", "Fine gold-tone jewellery set", "Mango", "jewellery", "accessories", None, ["clean-girl", "office-siren", "date-night"], 2490),
    ("asos", "Silk-feel scarf", "ASOS DESIGN", "accessory", "accessories", "ochre", ["heritage", "quiet-luxury", "smart-casual"], 1490),
]


async def main() -> int:
    remove = "--remove" in sys.argv
    settings = get_settings()
    engine = build_engine(settings.database_url)
    maker = session_factory(engine)
    now = datetime.now(UTC)

    async with maker() as db:
        if remove:
            await db.execute(sa.delete(Offer))
            await db.execute(sa.delete(ShopProduct))
            await db.execute(sa.delete(Retailer))
            await db.commit()
            print("Removed the curated catalogue.")
            return 0

        retailers: dict[str, Retailer] = {}
        for slug, name, homepage, _template in RETAILERS:
            row = await db.scalar(sa.select(Retailer).where(Retailer.slug == slug))
            if row is None:
                row = Retailer(slug=slug, name=name, homepage=homepage)
                db.add(row)
                await db.flush()
            retailers[slug] = row
        templates = {slug: template for slug, _n, _h, template in RETAILERS}

        written = 0
        for slug, title, brand, category, slot, colour, aesthetics, kes in PRODUCTS:
            retailer = retailers[slug]
            product = await db.scalar(
                sa.select(ShopProduct).where(
                    ShopProduct.retailer_id == retailer.id,
                    ShopProduct.title == title,
                )
            )
            if product is None:
                product = ShopProduct(
                    retailer_id=retailer.id,
                    title=title,
                    brand=brand,
                    category_id=category,
                    slot=slot,
                    colour=colour,
                    aesthetics=aesthetics,
                )
                db.add(product)
                await db.flush()
            else:
                product.category_id = category
                product.slot = slot
                product.colour = colour
                product.aesthetics = aesthetics

            offer = await db.scalar(
                sa.select(Offer).where(Offer.product_id == product.id)
            )
            url = templates[slug].format(q=quote_plus(title))
            if offer is None:
                db.add(
                    Offer(
                        product_id=product.id,
                        price_minor=kes * 100,
                        currency="KES",
                        sizes=["XS", "S", "M", "L", "XL"],
                        availability="unverified",
                        ships_to=["KE"],
                        retrieved_at=now,
                        expires_at=now + WINDOW,
                        source_url=url,
                        evidence={"provider": "curated"},
                    )
                )
            else:
                offer.price_minor = kes * 100
                offer.currency = "KES"
                offer.retrieved_at = now
                offer.expires_at = now + WINDOW
                offer.source_url = url
            written += 1

        await db.commit()
        print(f"Curated catalogue: {len(RETAILERS)} retailers, {written} products.")
        print("Every offer is availability=unverified, provider=curated.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
