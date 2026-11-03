"""Make small copies of the cover imagery for the places that draw it small.

Almost nothing in this app shows a cover at full size. A Discover tile is
about 114 points wide, a welcome collage card about 100, a board cover and an
inbox row about 55. On a 3x phone the largest of those is roughly 340 pixels
— and the masters are 1120 to 1280 wide, so every one of those screens was
fetching four times the pixels it could display.

Only two places want the master: the look detail hero, which is full-bleed,
and the featured tile on Discover, which spans the column.

    python scripts/make_thumbnails.py

Writes apps/mobile/assets/images/styles/thumbs/. Re-running overwrites.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STYLES = REPO / "apps" / "mobile" / "assets" / "images" / "styles"
THUMBS = STYLES / "thumbs"

#: Wide enough for the largest small use (a 114pt tile at 3x is 342px) with
#: room for a layout that grows a little, and no wider — the whole point is
#: to stop shipping pixels nothing can draw.
WIDTH = 420

#: Lower than the masters' 88. These are drawn at a third of their size, so
#: the artefacts that quality buys back are below a pixel on screen.
QUALITY = 78


def main() -> int:
    from PIL import Image

    THUMBS.mkdir(parents=True, exist_ok=True)
    before = after = 0
    made = 0

    for source in sorted(STYLES.glob("*.webp")):
        with Image.open(source) as image:
            if image.width <= WIDTH:
                continue
            height = round(image.height * WIDTH / image.width)
            small = image.convert("RGB").resize((WIDTH, height), Image.LANCZOS)
        target = THUMBS / source.name
        small.save(target, "WEBP", quality=QUALITY, method=6)
        before += source.stat().st_size
        after += target.stat().st_size
        made += 1

    print(f"{made} thumbnails: {before / 1024 / 1024:.1f}MB -> {after / 1024 / 1024:.1f}MB")
    print("Now re-run compute_blurhashes.py if the placeholder set changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
