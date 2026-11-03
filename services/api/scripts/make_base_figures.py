"""Draw the two base figures the app dresses, once, and keep them.

**Run this by hand, once, and commit what it writes.** It is not a
job, not a route and nothing calls it: it spends two image
generations and then nobody ever spends another. Every look in the
app is those two pictures with garment cut-outs layered over them on
the phone, which is why a hundred and fifty outfits cost nothing.

That is the whole point of the change it belongs to. A per-account
avatar meant a generation per account; a per-look render meant a
generation per question. Two figures for everybody means two.

    cd services/api
    python scripts/make_base_figures.py

Writes `apps/mobile/assets/images/figures/{menswear,womenswear}.png`,
replacing the flat placeholders already committed there. The canvas
and the proportions must match those placeholders, because the slot
anchors in `apps/mobile/src/features/avatar/figure.tsx` are measured
against them - a figure standing in a different place on the canvas
puts every garment in the wrong place.

**Nothing here reads appearance off anybody.** The two casts below are
written out in full, from the closed vocabulary in
`app.workers.avatar`, exactly as the house rule requires.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIGURES = REPO / "apps" / "mobile" / "assets" / "images" / "figures"

#: What the figure wears, so a cut-out laid over it has something
#: neutral underneath rather than a bare body.
BASE = (
    "a plain mid-grey long-sleeved top and plain mid-grey straight "
    "trousers, with simple white trainers, all unbranded"
)

#: Flat, stylized, and deliberately not a photograph.
#:
#: A cut-out of a real garment laid over a photoreal body invites the
#: eye to check the drape and the shadow and find them wrong. Over a
#: flat figure it reads as what it is: these clothes, in this order,
#: roughly this shape.
STYLE = (
    "Full-length front-facing figure illustration, flat vector style, "
    "clean even line weight, no gradients, no shadows, no background, "
    "fully transparent background, centred in frame with the whole "
    "body visible from head to feet, arms slightly away from the body, "
    "neutral standing pose, neutral expression, soft warm grey skin "
    "tone, simple unstyled hair. Not photorealistic."
)

#: The two, named by the presentation somebody already told us.
CASTS: dict[str, str] = {
    "menswear": "an adult figure with a straight build and broader shoulders",
    "womenswear": "an adult figure with a curved build and narrower shoulders",
}


async def main() -> int:
    try:
        from app.workers.avatar import MetaAvatarRenderer
    except Exception as problem:  # pragma: no cover - a setup problem
        print(f"could not load the renderer: {problem}", file=sys.stderr)
        return 1

    FIGURES.mkdir(parents=True, exist_ok=True)
    renderer = MetaAvatarRenderer()

    for name, cast in CASTS.items():
        prompt = f"{STYLE}\n\nIn frame: {cast}, wearing {BASE}."
        print(f"drawing {name}...")
        try:
            image = await renderer.draw(prompt=prompt)
        except AttributeError:
            print(
                "This renderer has no plain `draw(prompt=...)`. Call whatever "
                "it does expose with the prompt above, or paste the prompt "
                "into the vendor console by hand - the point of this script "
                "is the prompt and the canvas, not the transport.",
                file=sys.stderr,
            )
            print("\n--- prompt ---\n" + prompt + "\n", file=sys.stderr)
            return 2

        out = FIGURES / f"{name}.png"
        out.write_bytes(image.data if hasattr(image, "data") else image)
        print(f"wrote {out}")

    print(
        "\nNow check both against the placeholders they replaced: same "
        "canvas, head and feet in the same place. If the figure sits "
        "differently, move the anchors in "
        "apps/mobile/src/features/avatar/figure.tsx to match."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
