"""Generate the welcome screen's own photographs.

Separate from `generate_style_covers.py` because these are not collections.
A cover stands for an aesthetic somebody can browse into; these exist only
for the first screen, and putting them in the taxonomy would add collections
nobody can open.

Right now that is one picture: the figure the yoyo drops from. The welcome
screen animates a yoyo out of this card, rolls it down the page and turns it
into the three croquis — so the frame has to actually contain a yoyo on a
string, and the casting has to match the card it replaces (`streetwear`: a
Black man in his twenties) or the representation table in
`features/onboarding/welcome.ts` stops being true.

    MODEL_API_KEY=LLM_... python scripts/generate_welcome_art.py

Costs $0.01 per image. Writes WEBP into apps/mobile/assets/images/welcome/.
Re-run compute_blurhashes.py afterwards.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "apps" / "mobile" / "assets" / "images" / "welcome"

#: The shape the welcome collage renders a card at: `AspectRatio.editorial`.
#:
#: **Cropped here rather than at display time, and that is the whole point of
#: this constant.** The model returns 1120x2240 (1:2). A card is 3:4 with
#: `contentFit="cover"`, which scales by width and keeps only the middle two
#: thirds of the height — it cut this subject off at the mouth and discarded
#: the yoyo entirely, which is the one thing the picture exists for. Nothing
#: errored; the first screen in the product simply showed a headless torso
#: and a drawn yoyo rolling out of his shin.
#:
#: Pre-cropping means the file *is* the card. That also makes
#: `YOYO_IN_CARD` honest: it is measured on this file, and this file is what
#: the card shows, so photo space and card space are the same space.
CARD_RATIO = 3 / 4

#: Crop from the top: the head and the yoyo matter, the boots do not.
CROP_ANCHOR = 0.0

#: Copied from `generate_style_covers.FRAMING` rather than imported, and
#: deliberately: these sit in the same pile as the covers and must match them
#: exactly, but the covers' framing is free to change for the browse grid
#: without silently restyling the first screen in the product.
FRAMING = (
    "Full-length editorial fashion photograph, head to feet in frame, facing "
    "the camera. Plain warm off-white plaster wall behind, soft diffused "
    "daylight from one side, a soft natural shadow on the pale concrete "
    "floor. Calm, understated styling. Shot on medium format film, natural "
    "grain, muted warm colour. "
    "No text, no logo, no brand mark, no watermark, no border."
)

#: Not a photograph, so it does not take `FRAMING`. Handled separately below.
LINE_ART: dict[str, str] = {
    "globe": (
        "A simple flat vector illustration of planet Earth as a sphere, seen "
        "from space, with the major continents shown as solid shapes and the "
        "oceans left empty. Clean even outline, no shading, no gradient, no "
        "stars, no clouds, no grid lines, no text. Centred, filling the "
        "frame, on plain white."
    ),
}

SUBJECTS: dict[str, str] = {
    "yoyo": (
        "a Black man in his twenties, broad build, wearing an oversized "
        "graphic tee under a boxy varsity jacket, wide cargo trousers and "
        "chunky high-top trainers, one hand raised to chest height holding "
        "a yoyo that dangles on its string down to about his waist, the "
        "string taut and clearly visible, the yoyo at rest in mid air"
    ),
}


def crop_to_card(image):
    """Cut the photograph down to the shape the card renders at.

    Never resized, only cropped — a source that has already been squashed
    cannot be unsquashed, and `expo-image` would crop anyway. Doing it here
    means the crop is chosen rather than inherited.
    """
    want = image.width / CARD_RATIO
    if want >= image.height:
        return image
    top = int((image.height - want) * CROP_ANCHOR)
    return image.crop((0, top, image.width, top + int(want)))


async def main() -> int:
    key = os.environ.get("MODEL_API_KEY") or os.environ.get("LUXISH_META_API_KEY")
    if not key:
        print("MODEL_API_KEY is not set. Refusing to pretend this ran.")
        return 2

    from openai import AsyncOpenAI
    from PIL import Image

    client = AsyncOpenAI(api_key=key, base_url="https://api.meta.ai/v1")
    OUT.mkdir(parents=True, exist_ok=True)

    wanted = [a for a in sys.argv[1:] if not a.startswith("--")] or sorted(SUBJECTS)
    for name in wanted:
        if name not in SUBJECTS:
            print(f"No subject written for: {name}")
            return 2

        target = OUT / f"{name}.webp"
        if target.exists():
            print(f"{name} ... already there")
            continue

        print(f"{name} ...", end=" ", flush=True)
        try:
            response = await client.images.generate(
                model="muse-image-1.0",
                prompt=f"{FRAMING}\n\nIn frame: {SUBJECTS[name]}.",
                n=1,
            )
        except Exception as exc:  # noqa: BLE001 - one refusal must not stop the set
            print(f"FAILED {type(exc).__name__}: {str(exc)[:80]}")
            continue

        raw = base64.b64decode(response.model_dump()["data"][0]["b64_json"])
        # Never resized. `expo-image` crops at display time; a source file
        # that has already been squashed cannot be unsquashed.
        with Image.open(io.BytesIO(raw)) as image:
            cropped = crop_to_card(image.convert("RGB"))
            cropped.save(target, "WEBP", quality=88, method=6)
            print(
                f"{target.name}  {image.width}x{image.height}"
                f" -> {cropped.width}x{cropped.height}"
                f"  {target.stat().st_size:,} bytes"
            )

    print("\nNow run: python scripts/compute_blurhashes.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
