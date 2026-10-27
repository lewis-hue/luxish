#!/usr/bin/env python3
"""Generate the sample wardrobe imagery with `muse-image-1.0`.

§3 asks to "allow a sample wardrobe demonstration before lengthy setup" — someone
evaluating the app should be able to see styling work before photographing forty
garments. These are the items behind that demonstration.

Different art direction from the Discover covers on purpose: those are editorial
photographs of people, these are flat product shots on a plain ground. Mixing the two
treatments in one app is what makes a catalogue look assembled from stock.

Square (1:1), matching `AspectRatio.garment`, so the wardrobe grid never crops.

    python scripts/generate_sample_wardrobe.py
    python scripts/generate_sample_wardrobe.py --force
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
OUT_DIR = REPO_ROOT / "apps" / "mobile" / "assets" / "images" / "wardrobe"
ENDPOINT = "https://api.meta.ai/v1/images/generations"
MODEL = "muse-image-1.0"
SIZE = "1024x1024"

DIRECTION = (
    " Single garment photographed flat from directly above on a plain warm off-white "
    "paper background, soft even studio light, gentle natural shadow, true colour, "
    "centred with generous margin, nothing else in frame. No model, no hanger, no "
    "text, no logos, no branding."
)

#: id -> (prompt, the attributes the app shows for it)
ITEMS: dict[str, str] = {
    "white-shirt": "A crisp white cotton poplin shirt with a classic collar, long sleeves",
    "navy-blazer": "A navy wool single-breasted blazer, notch lapel, unstructured shoulder",
    "cream-trousers": "A pair of cream wide-leg pleated trousers in a soft drapey fabric",
    "indigo-jeans": "A pair of indigo straight-leg denim jeans, mid wash, no distressing",
    "black-midi-dress": "A black midi dress in matte crepe, long sleeves, simple neckline",
    "brown-loafers": "A pair of brown leather penny loafers, worn-in patina, flat sole",
    "white-trainers": "A pair of clean white leather low-top trainers, minimal design",
    "camel-coat": "A camel wool overcoat, long, single-breasted, soft tailored shoulder",
    "linen-shirt": "An oversized sand-coloured linen shirt, relaxed fit, visible texture",
    "striped-knit": "A fine-gauge knit jumper with narrow navy and cream horizontal stripes",
    "leather-tote": "A structured tan leather tote bag, simple hardware, top handles",
    "silk-scarf": "A silk scarf in muted ochre and terracotta, loosely folded square",
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
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = load_key()

    generated = skipped = failed = 0
    for index, (name, prompt) in enumerate(ITEMS.items(), start=1):
        destination = OUT_DIR / f"{name}.webp"
        if destination.exists() and not args.force:
            print(f"[{index:2}/{len(ITEMS)}] {name}: present, skipping")
            skipped += 1
            continue

        started = time.time()
        try:
            image = generate(key, prompt)
        except urllib.error.HTTPError as error:
            print(f"[{index:2}/{len(ITEMS)}] {name}: HTTP {error.code} {error.read()[:140]!r}")
            failed += 1
            continue
        except Exception as error:  # noqa: BLE001
            print(f"[{index:2}/{len(ITEMS)}] {name}: {type(error).__name__}: {error}")
            failed += 1
            continue

        destination.write_bytes(image)
        generated += 1
        print(
            f"[{index:2}/{len(ITEMS)}] {name}: {len(image) // 1024} KB "
            f"in {time.time() - started:.0f}s"
        )

    print(
        f"\ngenerated {generated}, skipped {skipped}, failed {failed} "
        f"— approximately ${generated * 0.01:.2f}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
