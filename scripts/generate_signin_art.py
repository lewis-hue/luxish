"""Generate the three detail crops behind the sign-in screen.

Separate from `generate_style_covers.py` because these are a different kind of
picture doing a different job. The covers are full-length figures that have to
match each other so a browse grid reads as one set. These are close crops of
cloth, and they exist so the screen after "Get started" is not the brand name
printed a second time.

**No faces, and that is the point.** Welcome opens on six people; repeating
that register one screen later is the same screen twice. A crop of a cuff, a
shoulder seam and a shoe is the other half of how fashion is photographed, and
it sidesteps the question of who the one face on the sign-in screen would be.

**Smart and casual, deliberately.** A shirt cuff, a wool coat shoulder and a
trainer with a cargo hem: the three registers this audience moves between in a
week, rather than three versions of one.

    MODEL_API_KEY=LLM_... python scripts/generate_signin_art.py

Costs $0.01 per image. Writes WEBP into apps/mobile/assets/images/signin/.
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
OUT = REPO / "apps" / "mobile" / "assets" / "images" / "signin"

#: Shared so the three crops read as one shoot, exactly as `FRAMING` does for
#: the covers. Same plaster wall and same daylight, so these sit beside the
#: covers without looking borrowed from another app.
FRAMING = (
    "Close-crop editorial fashion detail photograph, filling the frame. Warm "
    "off-white plaster and pale concrete behind, soft diffused daylight from "
    "one side. Shot on medium format film, natural grain, muted warm colour, "
    "shallow depth of field. "
    "No face, no text, no logo, no brand mark, no watermark, no border."
)

SUBJECTS: dict[str, str] = {
    "cuff": (
        "a close crop of hands fastening the cuff button of an oversized "
        "ivory cotton shirt, the fabric creased and the stitching visible"
    ),
    "shoulder": (
        "a close crop of the shoulder and collar of a heavy camel wool coat "
        "worn over a cream roll-neck, showing the weave and the seam"
    ),
    "step": (
        "a close crop of chunky white leather trainers and the wide hem of "
        "charcoal cargo trousers, mid-stride on pale concrete"
    ),
}


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
        # Resumable, for the same reason the cover script is: a paid run that
        # cannot be restarted without paying again is one nobody dares stop.
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
        # Never resized. `expo-image` crops at display time; a source file that
        # has already been squashed cannot be unsquashed.
        with Image.open(io.BytesIO(raw)) as image:
            image.convert("RGB").save(target, "WEBP", quality=88, method=6)
            print(f"{target.name}  {image.width}x{image.height}  {target.stat().st_size:,} bytes")

    print("\nNow run: python scripts/compute_blurhashes.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
