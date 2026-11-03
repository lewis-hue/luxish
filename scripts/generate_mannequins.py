"""Generate the mannequin figures the avatar is chosen from.

**Generated once, here, and then shipped.** The avatar used to be a fresh
image-model call per person: a photorealistic figure with a *face*, billed
every time somebody set their appearance and regenerated on every change.
This produces the whole set once, as bundled assets, so picking an avatar
on the device costs nothing, happens instantly, and works offline.

**A mannequin, not a person, and that is the better answer anyway.** A
generated face is a face the app invented and attached to a real user: it
is never quite right, it is a new identity nobody asked for, and it is the
expensive part of the picture. A shop mannequin is what clothes are
actually shown on. It has a build and a posture and no face to be wrong
about, which is exactly the job.

**The grid is presentation x build, and nothing else.** A mannequin has no
age and no skin tone — that is the point of a mannequin — so those two
stated fields do not multiply this set. Height is a crop and a proportion
the renderer can express without a separate figure. Fifteen files total.

    MODEL_API_KEY=LLM_... python scripts/generate_mannequins.py
    MODEL_API_KEY=LLM_... python scripts/generate_mannequins.py feminine-slim

Costs about $0.01 per image, so roughly $0.15 for the full set. Writes
WEBP into apps/mobile/assets/images/mannequins/. Re-run
compute_blurhashes.py afterwards.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "apps" / "mobile" / "assets" / "images" / "mannequins"

#: The same world as the Discover covers and the try-on scene, so a figure
#: wearing an outfit sits in the collection it came from rather than
#: looking pasted in from another app.
SCENE = (
    "Full-length studio photograph of a faceless matte fashion mannequin, "
    "head to feet in frame, facing the camera, standing naturally with arms "
    "relaxed at the sides. Plain warm off-white plaster wall behind, soft "
    "diffused daylight from one side, a soft natural shadow on the pale "
    "concrete floor. Shot on medium format film, natural grain, muted warm "
    "colour. "
    "The mannequin is a smooth matte pale stone grey, with a plain featureless "
    "head: no face, no eyes, no mouth, no hair, no wig. "
    "No text, no logo, no brand mark, no watermark, no border, no props."
)

#: What the mannequin wears before anything is tried on it. Plain and
#: covered, for the same reason the generated avatar was: a bare figure
#: would be a worse thing to have made and a worse thing to show.
BASE_OUTFIT = (
    "a plain mid-grey long-sleeved top and plain mid-grey straight trousers, "
    "with simple white trainers, all unbranded"
)

#: `presentation` from the avatar vocabulary -> how the form reads.
PRESENTATIONS: dict[str, str] = {
    "feminine": "with a feminine dress-form silhouette",
    "masculine": "with a masculine dress-form silhouette",
    "androgynous": "with a neutral androgynous dress-form silhouette",
}

#: `body_type` -> the build. "average" carries no adjective, the same
#: decision `_PHRASES` makes: an image model already draws an average build
#: from a plain noun, and naming it only adds words to argue with.
BUILDS: dict[str, str] = {
    "slim": "a slim build",
    "average": "an average build",
    "athletic": "an athletic build",
    "curvy": "a curvy build",
    "plus": "a plus size build",
}


def prompt_for(presentation: str, build: str) -> str:
    silhouette = PRESENTATIONS[presentation]
    shape = BUILDS[build]
    return f"{SCENE}\n\nIn frame: a fashion mannequin {silhouette} and {shape}, wearing {BASE_OUTFIT}."


async def main() -> int:
    key = os.environ.get("MODEL_API_KEY") or os.environ.get("LUXISH_META_API_KEY")
    if not key:
        print("MODEL_API_KEY is required.", file=sys.stderr)
        return 2
    os.environ.setdefault("LUXISH_META_API_KEY", key)

    import io  # noqa: E402

    from openai import AsyncOpenAI  # noqa: E402
    from PIL import Image  # noqa: E402

    # The vendor client directly, as `generate_style_covers.py` does.
    # `MetaProvider` refuses a call with no `AIRunRecorder`, and it is
    # right to: an unaccounted call is spend nobody can attribute to a
    # user or a feature. This is a build-time script run by a person, so
    # there is no user to attribute it to and nothing to record.
    client = AsyncOpenAI(api_key=key, base_url="https://api.meta.ai/v1")

    wanted = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    pairs = [
        (presentation, build)
        for presentation in PRESENTATIONS
        for build in BUILDS
        if not wanted or f"{presentation}-{build}" in wanted
    ]
    if not pairs:
        print("Nothing matched.", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)

    for presentation, build in pairs:
        name = f"{presentation}-{build}"
        target = OUT / f"{name}.webp"
        # Resumable: a run of paid calls that cannot be restarted without
        # paying for the ones it already made is a run nobody dares
        # interrupt.
        if target.exists() and not wanted:
            print(f"{name} ... exists, skipping")
            continue
        print(f"{name} ... ", end="", flush=True)
        try:
            response = await client.images.generate(
                model="muse-image-1.0",
                prompt=prompt_for(presentation, build),
                n=1,
            )
        except Exception as exc:  # noqa: BLE001 - one refusal must not stop the set
            print(f"FAILED {type(exc).__name__}: {str(exc)[:80]}")
            continue

        raw = base64.b64decode(response.model_dump()["data"][0]["b64_json"])
        # Re-encoded to WEBP, never resized, for the reason the covers
        # script records at length.
        with Image.open(io.BytesIO(raw)) as image:
            image.convert("RGB").save(target, "WEBP", quality=88, method=6)
            print(
                f"{target.name}  {image.width}x{image.height}  "
                f"{target.stat().st_size:,} bytes"
            )

    print("\nNow run: python scripts/compute_blurhashes.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
