#!/usr/bin/env python3
"""Generate the Discover category imagery with `muse-image-1.0`.

Why generated rather than licensed: every free stock source that would fit
(Unsplash, Pexels) prohibits an app whose content *is* their library, and Unsplash
additionally mandates hotlinking as a material-breach term, which rules out a CDN
derivative. Generated imagery we own outright, with no attribution obligation and no
re-hosting restriction — see docs/architecture/image-sourcing.md.

Two things are deliberate and should stay that way:

* **One art direction across the whole set.** A grid whose tiles were each prompted
  differently reads as a collage, not a collection. The shared suffix is what makes
  twelve separate generations look like one shoot.
* **Deliberately varied casting.** A fashion app that renders one body type and one
  skin tone is making a statement whether or not anyone intended it, and the product
  explicitly serves Nairobi and Mombasa among others.

Every output is marked `isGenerated` in the app, which renders the AI disclosure
badge Google Play policy requires.

    python scripts/generate_style_imagery.py              # only what is missing
    python scripts/generate_style_imagery.py --force      # regenerate everything
    python scripts/generate_style_imagery.py --only office
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "apps" / "mobile" / "assets" / "images" / "styles"
ENDPOINT = "https://api.meta.ai/v1/images/generations"
MODEL = "muse-image-1.0"

#: 3:4, matching `AspectRatio.editorial` so tiles never letterbox or crop badly.
SIZE = "768x1024"

#: Appended to every prompt. This is what makes the grid cohere.
DIRECTION = (
    " Editorial fashion photograph, full length, 35mm film look, soft diffused "
    "natural light, muted warm colour grade, shallow depth of field, calm confident "
    "posture, photographed slightly below eye level. No text, no logos, no graphics, "
    "no watermark."
)

PROMPTS: dict[str, str] = {
    "streetwear": (
        "A young Black man in relaxed streetwear: oversized charcoal bomber jacket, "
        "wide cargo trousers, chunky white sneakers, crossbody bag. Standing against a "
        "weathered painted brick wall in late afternoon."
    ),
    "casual": (
        "A woman in her thirties in easy daily clothes: straight-leg indigo denim, a "
        "cream ribbed knit, clean low-profile trainers. Walking a quiet residential "
        "street lined with trees."
    ),
    "smart-casual": (
        "A man in his forties in smart casual tailoring: unstructured oatmeal blazer, "
        "fine-gauge navy knit, stone chinos, brown suede loafers. Outside a stone "
        "building with tall windows."
    ),
    "office": (
        "A Black woman in office tailoring: charcoal wide-leg trousers, crisp white "
        "shirt, structured leather tote, low block-heel shoes. In a bright modern "
        "lobby with pale concrete and glass."
    ),
    "formal": (
        "A South Asian man in full tailoring: midnight navy two-piece suit, white "
        "shirt, dark silk tie, polished black oxfords. Standing in a panelled "
        "interior with warm lamplight."
    ),
    "evening": (
        "A woman in evening wear: deep burgundy satin slip dress with a fine gold "
        "chain, strappy heeled sandals, small clutch. Warm low light against a dark "
        "textured wall, evening atmosphere."
    ),
    "athleisure": (
        "An athletic woman in athleisure: technical slate running jacket, black "
        "leggings, bright running shoes, small crossbody. On a park path in early "
        "morning light with mist."
    ),
    "minimalist": (
        "A person in minimalist dress: a long column-shaped stone-grey coat over a "
        "white tee and tapered trousers, unbranded leather flat sandals. Against a "
        "plain pale plaster wall, almost no colour."
    ),
    "warm-weather": (
        "A woman in warm-weather clothes: oversized white linen shirt, wide sand "
        "linen trousers, flat leather sandals, woven straw bag. Bright coastal light, "
        "whitewashed wall, strong warm sun."
    ),
    "rainy-season": (
        "A man in rainy-season clothing: olive water-resistant hooded shell jacket, "
        "cropped dark trousers, sturdy closed leather boots. On a wet city pavement "
        "with reflections, overcast grey light."
    ),
    "modest": (
        "A woman in modest dress: a long sand-coloured abaya-style layer over a "
        "high-neck cream top and loose trousers, draped headscarf, flat leather "
        "shoes. Against a warm sandstone wall in soft late light."
    ),
    "heritage": (
        "A Black woman in a heritage print look: a tailored jacket in bold West "
        "African woven print over plain black trousers, simple leather sandals, "
        "sculptural brass earrings. Against a plain warm ochre wall."
    ),
}


def load_key() -> str:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        sys.exit("no .env at the repository root; MODEL_API_KEY is required")
    env = dict(
        line.split("=", 1)
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    )
    key = env.get("MODEL_API_KEY", "").strip()
    if not key:
        sys.exit("MODEL_API_KEY is empty in .env")
    return key


def generate(key: str, prompt: str) -> bytes:
    body = {
        "model": MODEL,
        "prompt": prompt + DIRECTION,
        "n": 1,
        "size": SIZE,
        "response_format": "b64_json",
        "output_format": "webp",
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        payload = json.loads(response.read())
    return base64.b64decode(payload["data"][0]["b64_json"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate existing files")
    parser.add_argument("--only", help="generate a single category by id")
    args = parser.parse_args()

    targets = {args.only: PROMPTS[args.only]} if args.only else PROMPTS
    if args.only and args.only not in PROMPTS:
        sys.exit(f"unknown category {args.only!r}; known: {', '.join(PROMPTS)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = load_key()

    generated = skipped = failed = 0
    for index, (name, prompt) in enumerate(targets.items(), start=1):
        destination = OUT_DIR / f"{name}.webp"
        if destination.exists() and not args.force:
            print(f"[{index:2}/{len(targets)}] {name}: already present, skipping")
            skipped += 1
            continue

        started = time.time()
        try:
            image = generate(key, prompt)
        except urllib.error.HTTPError as error:
            # Keep going: one refused prompt should not cost the whole batch.
            print(f"[{index:2}/{len(targets)}] {name}: HTTP {error.code} — {error.read()[:160]!r}")
            failed += 1
            continue
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"[{index:2}/{len(targets)}] {name}: {type(error).__name__}: {error}")
            failed += 1
            continue

        destination.write_bytes(image)
        generated += 1
        print(
            f"[{index:2}/{len(targets)}] {name}: {len(image) // 1024} KB "
            f"in {time.time() - started:.0f}s"
        )

    # $0.01 per generated image, verified from dev.meta.ai/docs/pricing-rate-limits.
    print(
        f"\ngenerated {generated}, skipped {skipped}, failed {failed} "
        f"— approximately ${generated * 0.01:.2f}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
