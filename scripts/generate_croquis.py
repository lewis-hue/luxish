"""Generate the fashion illustrations that stand on the welcome screen.

**Why these are generated and the first one was hand-authored.** The welcome
sketch started as hand-written Lottie bezier coordinates — polylines for a
hat, a hoodie, two legs. It animated well and it looked like what it was: a
geometric approximation of a figure. A croquis is a drawing with confident,
varying line weight, and that is not something worth hand-coding vertex by
vertex when an image model draws it properly.

**Matted to alpha, not saved on white.** A line drawing on a white rectangle
sits on the app's warm paper as a visible white box. Everything lighter than
`INK_CUTOFF` becomes transparent and the ink keeps its own softness in the
alpha channel, so the figure sits on any ground. The app then renders it with
`tintColor`, which means one file serves light and dark rather than a drawing
that disappears in one of them.

PNG rather than WEBP: the alpha channel is the whole point here, and this is
one small asset per figure rather than the eighty photographs where the size
difference pays for itself.

    MODEL_API_KEY=LLM_... python scripts/generate_croquis.py

Costs $0.01 per image. Writes PNG into apps/mobile/assets/images/croquis/.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "apps" / "mobile" / "assets" / "images" / "croquis"

#: Anything at least this bright on every channel is paper, not ink.
#: Measured rather than guessed: the model returns near-white paper around
#: 248-255, and the lightest real pencil tone in these drawings sits near 210.
INK_CUTOFF = 232

#: The two lifting poses carry a face, which the house style otherwise
#: forbids.
#:
#: Every other croquis is drawn without features because a face makes one
#: figure a person rather than a silhouette, and the rest of the set is
#: meant to read as anybody. These two are the exception for a reason the
#: picture needs: the welcome screen drops the collage onto this figure and
#: the whole point is that it is heavy. Strain is carried in a face. A blank
#: oval holding a weight reads as a mannequin, not as effort.
LIFT_STYLE = (
    "Fashion croquis, black ink line drawing on plain white, full length "
    "figure, head to feet in frame. Confident varying line weight, loose and "
    "elegant, the kind of sketch in a designer's book. Line only, no shading, "
    "no colour, no fill, no background. Simple drawn facial features showing "
    "effort. Plenty of white space around the figure. "
    "No text, no logo, no watermark, no border, no frame."
)

#: Figures drawn with `LIFT_STYLE` instead of `STYLE`.
LIFTERS = ("lift-ready", "lift-strain")

STYLE = (
    "Fashion croquis, black ink line drawing on plain white, full length "
    "figure standing, head to feet in frame. Confident varying line weight, "
    "loose and elegant, the kind of sketch in a designer's book. Line only, "
    "no shading, no colour, no fill, no background, no face features drawn. "
    "Plenty of white space around the figure. "
    "No text, no logo, no watermark, no border, no frame."
)

#: Streetwear first because it is the silhouette this audience wears, and the
#: two smart-casual figures because that is what the same people wear to
#: everything that is not a night out.
FIGURES: dict[str, str] = {
    # The row on the welcome screen, left to right. Three figures rather
    # than one: a lone croquis makes a single silhouette the product, and a
    # row reads as a line-up, which is how a collection is presented.
    "cargo": (
        "a young woman in a cropped puffer jacket over a fitted baby tee, "
        "low-rise baggy cargo jeans and chunky platform trainers"
    ),
    # Three poses of the same outfit, which the welcome screen dissolves
    # between so the centre figure shifts stance the way a model does. The
    # outfit wording is identical across the three on purpose: it is the
    # only lever on keeping the clothes consistent between generations, and
    # a dissolve that changes the jacket reads as a glitch.
    "street": (
        "a young man in an oversized hoodie, wide baggy cargo trousers "
        "and chunky high-top trainers, a bucket hat on, standing square on "
        "with arms relaxed at his sides"
    ),
    "street-b": (
        "a young man in an oversized hoodie, wide baggy cargo trousers "
        "and chunky high-top trainers, a bucket hat on, weight shifted onto "
        "one hip with one hand in his pocket"
    ),
    "street-c": (
        "a young man in an oversized hoodie, wide baggy cargo trousers "
        "and chunky high-top trainers, a bucket hat on, turned slightly to "
        "one side with hands tucked into the front pocket"
    ),
    "blazer": (
        "a young woman in a relaxed oversized blazer over a fitted top, "
        "wide tailored trousers and chunky leather loafers"
    ),
    # The crowd on the globe. Silhouettes chosen to differ from each other
    # at a glance — a long coat, a dress, a skirt, a suit, a tracksuit —
    # because at this size the outline is the only thing that reads, and
    # five variations on "jacket and trousers" would look like one figure
    # copied five times.
    "trench": (
        "a young woman in a long open trench coat over a crew-neck and "
        "straight trousers, with ankle boots"
    ),
    "slip": (
        "a young woman in a bias-cut slip dress with a fine cardigan worn "
        "off the shoulders and strappy flat sandals"
    ),
    "suit": (
        "a young man in an oversized double-breasted suit worn with a plain "
        "tee and square-toed loafers"
    ),
    "skirt": (
        "a young person in an oversized hoodie over a long pleated skirt, "
        "with chunky lace-up boots"
    ),
    "track": (
        "a young man in a zip-up track jacket and matching wide track "
        "trousers, with retro running trainers"
    ),
    # The welcome screen's lifter, in two poses the app cuts between at the
    # moment the collage lands. The outfit wording is identical in both and
    # must stay that way: the cut is meant to read as one person taking the
    # weight, and a jacket that changes between frames reads as a glitch.
    # **Nothing is drawn above the hands.** The app puts the photo collage
    # there, and the first attempt came back with a crate resting on them —
    # two objects in the same place, one of which the layout cannot move.
    "lift-ready": (
        "a young man in an oversized hoodie, wide baggy cargo trousers and "
        "chunky high-top trainers, a bucket hat pushed back off his "
        "forehead, standing upright and square on, both arms stretched "
        "straight up above his head with palms open and flat and empty, "
        "hands empty and nothing above them, waiting to catch something. "
        "His face is clearly visible under the hat brim, calm and looking "
        "up. Draw nothing above his hands - no box, no object, no load"
    ),
    "lift-strain": (
        "a young man in an oversized hoodie, wide baggy cargo trousers and "
        "chunky high-top trainers, a bucket hat pushed back off his "
        "forehead, both arms bent above his head with palms up and empty, "
        "pressing upward as if holding up something enormously heavy, "
        "shoulders compressed, one knee dropped to the ground and the other "
        "leg folded under the load. His face is clearly visible under the "
        "hat brim, screwed up and grimacing with effort, teeth gritted. "
        "Draw nothing above his hands - no box, no object, no load"
    ),
}


#: The tallest these are ever drawn, in pixels, with headroom.
#:
#: The welcome screen stands them on a globe at roughly 50 points, which is
#: 160 pixels on a 3x phone. The model returns about 2000, so shipping the
#: masters meant sending twelve times the pixels any screen can show — about
#: 1.9 MB of the first screen's payload, over a phone's connection, to draw
#: figures the size of a fingernail. 480 keeps three times what the current
#: layout needs, so a future design can grow them without regenerating.
MAX_HEIGHT = 480

#: How far the outline is dilated before the fill, in pixels.
#:
#: A croquis is drawn with the pen lifted — the outline has gaps, and a flood
#: fill walks straight out through every one of them. Closing the line first
#: seals them; eroding by the same amount afterwards puts the silhouette's
#: edge back where the drawing actually is.
CLOSE = 11


def silhouette(image):
    """The figure's solid body, as an alpha mask.

    **Why a figure needs one.** These drawings are line art on transparency:
    everything that is not a stroke is see-through, including the inside of
    the person. Stand one on a drawn floor and the floor's lines run
    straight through their legs, which is the single most unreal thing on
    the screen. The app paints this mask in the page colour behind the ink,
    so the body occludes what is behind it the way a body does.

    **The frame is padded before the fill, and that is load-bearing.** The
    figures are trimmed to their own ink, so the drawing touches all four
    edges. Flooding the outside from pixel (0, 0) then starts *on* the
    subject — the fill goes nowhere, "outside" comes back empty, and the
    complement is the whole rectangle. That is not a subtle failure: every
    mask became a solid block, and the drawn floor stopped dead in a square
    around each figure. A transparent margin guarantees the fill has a
    connected outside to start from.
    """
    from PIL import Image, ImageDraw, ImageFilter

    pad = CLOSE + 2
    ink = image.getchannel("A").point(lambda v: 255 if v > 18 else 0).convert("L")
    framed = Image.new("L", (ink.width + pad * 2, ink.height + pad * 2), 0)
    framed.paste(ink, (pad, pad))

    closed = framed.filter(ImageFilter.MaxFilter(CLOSE))
    # Flood the *outside* from the corner, then take the complement: filling
    # the inside directly would need a seed point inside the figure, and
    # there is no point that is reliably inside all of them.
    work = closed.copy()
    ImageDraw.floodfill(work, (0, 0), 128, thresh=10)
    outside = work.point(lambda v: 255 if v == 128 else 0)
    inside = outside.point(lambda v: 0 if v else 255)
    # Undo the dilation, and take a little more: the mask should sit just
    # *inside* the drawn outline so the floor runs right up under the line
    # rather than stopping a few pixels short of it with a pale halo.
    inside = inside.filter(ImageFilter.MinFilter(CLOSE + 4))
    inside = inside.crop((pad, pad, pad + ink.width, pad + ink.height))

    covered = sum(inside.histogram()[200:]) / (inside.width * inside.height)
    if not 0.12 < covered < 0.80:
        # A standing figure covers roughly a third of its own frame. Far
        # outside that means the fill leaked or failed, and a silently wrong
        # mask is a solid block on the screen with nothing in any log.
        raise RuntimeError(
            f"silhouette covers {covered:.0%} of the frame, which is not a figure"
        )

    mask = Image.new("RGBA", image.size, (0, 0, 0, 0))
    mask.putalpha(inside)
    return mask


def matte(raw: bytes) -> bytes:
    """White paper out, ink in, as a PNG with a real alpha channel."""
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as source:
        image = source.convert("RGBA")
        pixels = image.load()
        assert pixels is not None
        width, height = image.size
        for y in range(height):
            for x in range(width):
                r, g, b, _ = pixels[x, y]
                lightest = max(r, g, b)
                if lightest >= INK_CUTOFF:
                    pixels[x, y] = (0, 0, 0, 0)
                else:
                    # Alpha from how dark the pixel is, so a soft stroke stays
                    # soft instead of being clipped to a hard black edge.
                    pixels[x, y] = (0, 0, 0, 255 - int(lightest * 255 / INK_CUTOFF))
        buffer = io.BytesIO()
        trim(image).save(buffer, "PNG", optimize=True)
        return buffer.getvalue()


def trim(image):
    """Crop a figure down to its own ink.

    **The app stands these on a drawn floor**, anchoring each one to the
    bottom of its box with `contentPosition="bottom"`. The model leaves four
    or five percent of empty frame below the shoes, so anchoring the *image*
    to the floor left the *figure* hovering above it — the two at the back
    floated a little over the far edge they are supposed to be standing on.

    Trimming means the file is the figure: its bottom edge is the soles, and
    the box's bottom edge is the floor. Masks are derived after this, so
    they trim with it and stay in register.
    """
    bbox = image.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
    return image.crop(bbox) if bbox else image


def downscale(image):
    """Shrink a figure to the largest size any screen actually draws it at."""
    from PIL import Image

    if image.height <= MAX_HEIGHT:
        return image
    width = max(1, round(image.width * MAX_HEIGHT / image.height))
    return image.resize((width, MAX_HEIGHT), Image.LANCZOS)


def write_mask(figure: Path) -> Path:
    """Write `<name>-mask.webp` beside a figure."""
    from PIL import Image

    with Image.open(figure) as image:
        mask = silhouette(image.convert("RGBA"))
    out = figure.with_name(f"{figure.stem}-mask.webp")
    # Lossless: a mask is a hard-edged solid, and lossy compression puts a
    # halo on exactly that kind of edge.
    # The mask is a hard-edged solid, which lossy compression haloes — and
    # it compresses to a couple of kilobytes losslessly anyway.
    mask.save(out, "WEBP", lossless=True, method=6)
    return out


async def main() -> int:
    # Before the key check: rebuilding masks from files already on disk is
    # pure local image work, and refusing it for want of an API key would
    # make the cheap half of this script depend on the expensive half.
    if "--trim" in sys.argv:
        from PIL import Image

        for figure in sorted(OUT.glob("*.webp")):
            if figure.stem.endswith("-mask"):
                continue
            with Image.open(figure) as image:
                before = image.size
                trimmed = downscale(trim(image.convert("RGBA")))
            # Lossy, with alpha. Lossless was the right call on a 2000px
            # master where a soft edge could ring; at 480 the artefacts are
            # smaller than a pixel on screen and the file is a tenth the
            # size. The alpha channel itself stays lossless either way.
            trimmed.save(figure, "WEBP", quality=86, method=6)
            print(f"{figure.name}  {before[0]}x{before[1]} -> {trimmed.width}x{trimmed.height}")
            out = write_mask(figure)
            print(f"  {out.name} rebuilt")
        return 0

    if "--masks" in sys.argv:
        for figure in sorted(OUT.glob("*.webp")):
            if figure.stem.endswith("-mask"):
                continue
            out = write_mask(figure)
            print(f"{out.name}  {out.stat().st_size:,} bytes")
        return 0

    key = os.environ.get("MODEL_API_KEY") or os.environ.get("LUXISH_META_API_KEY")
    if not key:
        print("MODEL_API_KEY is not set. Refusing to pretend this ran.")
        return 2

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key, base_url="https://api.meta.ai/v1")
    OUT.mkdir(parents=True, exist_ok=True)

    wanted = [a for a in sys.argv[1:] if not a.startswith("--")] or sorted(FIGURES)
    for name in wanted:
        if name not in FIGURES:
            print(f"No figure written for: {name}")
            return 2

        target = OUT / f"{name}.png"
        if target.exists():
            print(f"{name} ... already there")
            continue

        print(f"{name} ...", end=" ", flush=True)
        try:
            response = await client.images.generate(
                model="muse-image-1.0",
                prompt=f"{STYLE}\n\nIn frame: {FIGURES[name]}.",
                n=1,
            )
        except Exception as exc:  # noqa: BLE001 - one refusal must not stop the set
            print(f"FAILED {type(exc).__name__}: {str(exc)[:80]}")
            continue

        raw = base64.b64decode(response.model_dump()["data"][0]["b64_json"])
        target.write_bytes(matte(raw))
        write_mask(target)
        print(f"{target.name}  {target.stat().st_size:,} bytes")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
