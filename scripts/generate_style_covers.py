"""Generate the Discover cover for one or more style categories.

The covers are generated rather than licensed, which is what lets the app ship
them: `imagery.ts` records `provider: 'generated'` against each one, so the
provenance is a fact in the code rather than a claim in a readme.

They have to match each other more than they have to be individually striking.
A browse screen is twenty-odd of these seen together, and one shot on a
different backdrop, at a different distance, or in different light is the tile
that looks pasted in. So the framing is fixed and only the clothes change.

**Saved exactly as returned.** An earlier version of this resized every image
to 1344x1792 to match the first covers. The model returns 1280x1920, so that
was an 11% horizontal squash applied to every person in the set. Nothing is
resized now. `expo-image` crops to the tile at display time, which is what it
is for, and a source file that has already been distorted cannot be uncropped.

**One person per cover, balanced across the set.** Not two people in a frame:
a man and a woman standing together reads as a couple, which is a different
subject from the aesthetic being shown. Each category shows one person, the
genders alternate down the list, and `couples` exists as its own category for
people actually dressing with someone else.

**Representation is specified, not left to the model.** Asked for "a person",
an image model returns the same narrow default over and over, and a wardrobe
app whose browse screen shows one kind of body and one skin tone tells most of
the people opening it that it was not built for them. So every entry names who
is in the frame, and the set spans skin tones, ages and body types.

    MODEL_API_KEY=LLM_... python scripts/generate_style_covers.py y2k gorpcore

Costs $0.01 per image. Writes WEBP into apps/mobile/assets/images/styles/.
Re-run compute_blurhashes.py afterwards: the placeholder has to be computed
from the file that actually shipped.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STYLES = REPO / "apps" / "mobile" / "assets" / "images" / "styles"

#: `(who is in frame, what they are wearing)`.
#:
#: Casting is written out per entry rather than randomised, so the set can be
#: read as a whole and checked for balance, and so regenerating one cover does
#: not quietly change who the collection represents. Genders alternate; the
#: ages run from twenties to sixties; the skin tones span the range.
SUBJECTS: dict[str, tuple[str, str]] = {
    # -- aesthetics ------------------------------------------------------- #
    "streetwear": (
        "a Black man in his twenties, broad build",
        "an oversized graphic tee under a boxy varsity jacket, with wide "
        "cargo trousers and chunky high-top trainers",
    ),
    "minimalist": (
        "an East Asian woman in her fifties, slim",
        "a grey wool crew-neck with straight ivory trousers and plain "
        "leather loafers, three pieces and nothing else",
    ),
    "heritage": (
        "a Black woman in her sixties",
        "a tailored jacket and wide trousers cut from bold West African wax "
        "print, with simple leather sandals",
    ),
    "modest": (
        "a Middle Eastern woman in her thirties wearing a hijab",
        "a long-sleeved column dress in deep olive over wide trousers, "
        "fully covering and sharply cut",
    ),
    "evening": (
        "a white woman in her forties, plus size",
        "a floor-length black crepe gown with a high neck and long sleeves, "
        "and plain black heels",
    ),
    "office": (
        "a South Asian man in his fifties",
        "a navy single-breasted suit with a pale blue shirt, no tie, and "
        "brown leather derbies",
    ),
    "athleisure": (
        "a Latino man in his thirties, athletic",
        "a charcoal zip-through technical jacket over a fitted tee, with "
        "tapered joggers and clean running shoes",
    ),
    "quiet-luxury": (
        "a Black woman in her forties",
        "unbranded neutral tailoring: a camel overcoat over a cream "
        "roll-neck and wide beige trousers, in obviously good cloth",
    ),
    "clean-girl": (
        "a South Asian woman in her twenties",
        "a crisp white shirt tucked into straight ivory trousers, with "
        "simple gold jewellery and flat leather slides",
    ),
    "downtown-romantic": (
        "a white woman in her twenties with visible tattoos",
        "an oversized black leather jacket over a cream lace top, a dark "
        "pleated mini skirt and chunky knee-high boots",
    ),
    "dark-academia": (
        "a Middle Eastern man in his twenties",
        "a brown tweed blazer over a dark roll-neck, pleated wool trousers "
        "and leather brogues",
    ),
    "gorpcore": (
        "a Black man in his thirties",
        "technical outdoor layers in town: a weatherproof shell jacket over "
        "a zip fleece, wide cargo trousers and trail running shoes",
    ),
    "blokecore": (
        "a white man in his twenties",
        "a vintage football shirt worn loose over straight jeans, with "
        "retro leather trainers",
    ),
    "y2k": (
        "a Latina woman in her twenties",
        "low-rise baggy denim with a fitted baby tee, a small shoulder bag "
        "and chunky trainers, early-2000s in cut",
    ),
    "monochrome": (
        "an East Asian man in his thirties",
        "an all-black outfit: a long-sleeved knit, wide tailored trousers "
        "and leather loafers, with no contrasting colour anywhere",
    ),
    # -- what this audience is actually wearing --------------------------- #
    #
    # Added after the welcome screen was recast for the people this app is
    # for. The twenty-seven above are a reasonable map of fashion; these are
    # the aesthetics that came up through TikTok rather than through a
    # magazine, plus the smart-casual register that the same people wear to
    # anything that is not a night out. Cast in their twenties throughout,
    # and across eight regions so the set does not repeat one.
    "coquette": (
        "a white woman in her twenties",
        "soft romantic dressing: a cream ruffled blouse with a satin ribbon "
        "at the collar, a short pleated skirt, sheer tights and ballet flats",
    ),
    "balletcore": (
        "an East Asian woman in her twenties, slim",
        "a wrap cardigan over a fitted bodysuit, with a long soft skirt, "
        "ribbed legwarmers and flat ballet shoes",
    ),
    "mob-wife": (
        "a Latina woman in her thirties",
        "a loud faux-fur coat worn open over a black slip dress, with gold "
        "jewellery, dark sunglasses and heeled boots",
    ),
    "techwear": (
        "a Black man in his twenties",
        "all-black technical dressing: a shell jacket with taped seams and a "
        "harness strap, tapered ripstop trousers and heavy-soled boots",
    ),
    "skater": (
        "a Southeast Asian man in his twenties",
        "a loose graphic tee over a long-sleeve, wide-leg worn jeans, a "
        "beanie and scuffed skate shoes",
    ),
    "grunge": (
        "a South Asian woman in her twenties",
        "an oversized flannel shirt open over a faded band tee, ripped "
        "straight jeans and heavy lace-up boots",
    ),
    "smart-casual": (
        "a Black woman in her twenties",
        "smart without a suit: a relaxed blazer over a fine knit, straight "
        "tailored trousers and clean leather trainers",
    ),
    "elevated-basics": (
        "a Middle Eastern man in his twenties",
        "plain pieces cut well: a heavyweight crew-neck tee, straight "
        "charcoal trousers and minimal leather sneakers, no logos anywhere",
    ),
    # -- occasions -------------------------------------------------------- #
    "office-siren": (
        "an East Asian woman in her thirties",
        "a fitted pinstripe blazer with a tailored pencil skirt, "
        "tortoiseshell glasses and pointed heels",
    ),
    "wedding-guest": (
        "a Black woman in her thirties",
        "a column dress in deep green with fine jewellery and low heels, "
        "dressed for a wedding without upstaging anyone",
    ),
    "festival": (
        "a white man in his twenties",
        "festival dressing: a loose patterned shirt over a plain tee, "
        "straight jeans and worn leather boots",
    ),
    "date-night": (
        "a Latina woman in her thirties",
        "a dark silk slip dress with a fine knit cardigan over the "
        "shoulders and heeled sandals",
    ),
    "travel": (
        "a Middle Eastern woman in her thirties",
        "airport dressing: soft wide trousers with a loose cotton shirt and "
        "canvas trainers, a leather holdall held at the side",
    ),
    "couples": (
        "a Black man in his thirties and a South Asian woman in her "
        "thirties, standing together as a couple",
        "complementary outfits that clearly belong together without "
        "matching: a navy overcoat with grey trousers, and a camel coat "
        "over an ivory knit",
    ),
    # -- formulas --------------------------------------------------------- #
    "capsule": (
        "a Southeast Asian woman in her fifties",
        "a small set of interchangeable neutrals: a white shirt under a "
        "navy knit, straight charcoal trousers and a beige trench",
    ),
    "denim": (
        "a white woman in her thirties",
        "straight-leg indigo jeans with a matching denim jacket over a "
        "plain white t-shirt, and worn leather boots",
    ),
    "tailoring": (
        "a Black man in his forties",
        "a single-breasted wool suit in charcoal, worn open over a fine "
        "knit, with polished leather derbies",
    ),
    "layering": (
        "a white man in his sixties",
        "a heavy wool overcoat open over a roll-neck and a mid-weight "
        "jacket, with thick trousers and leather boots",
    ),
    "utility": (
        "a Black woman in her twenties",
        "a cotton chore jacket in olive over a work shirt, with cargo "
        "trousers and sturdy boots",
    ),
    "colour": (
        "a South Asian woman in her forties",
        "a deep burgundy knit with ochre wide-leg trousers and tan leather "
        "shoes, bold but muted rather than bright",
    ),
}

#: Who appears in the *second* and *third* picture of each collection.
#:
#: A rotation rather than fifty-four more hand-written entries, and that is
#: the better shape here rather than a shortcut: balance becomes a property
#: of the structure, checkable by printing the assignment, instead of
#: something somebody has to verify by reading fifty-four paragraphs.
#:
#: Written to fill the gaps the first set left. Those twenty are overwhelmingly
#: in their twenties and thirties, and not one of them names a body type —
#: which the docstring above claimed the set spanned and it did not. These do,
#: and they run older.
VARIANT_CASTING: tuple[str, ...] = (
    "a white man in his sixties, slim",
    "a Black woman in her fifties, plus size",
    "an East Asian man in his forties, broad build",
    "a Latina woman in her sixties",
    "a South Asian woman in her twenties, athletic",
    "a Middle Eastern man in his fifties",
    "a Black man in his seventies",
    "a white woman in her thirties, plus size",
    "a Southeast Asian man in his twenties, slim",
    "a Latino man in his forties, broad build",
    "an East Asian woman in her sixties",
    "a Black woman in her twenties, athletic",
)


#: Collections that are cast for one gender, and which.
#:
#: **Two different reasons land a collection here, and both are the
#: garment or the name rather than a rule about who may wear what.**
#:
#: *The outfit is gendered.* `balletcore`, `coquette`, `date-night`,
#: `downtown-romantic`, `evening`, `mob-wife`, `office-siren` and
#: `wedding-guest` are written as a slip dress, a pleated tennis skirt, a
#: pencil skirt with stilettos, a floor-length gown. This list exists
#: because the rotation below is blind and the outfit is fixed:
#: `prompt_for` holds `wearing` constant and swaps only the person, so
#: with nothing stopping it the rotation cast men into all of them. Nine
#: such pictures reached the app and were deleted.
#:
#: *The collection itself is gendered.* `clean-girl` and `blokecore` are
#: named for who wears them. Their garments are unisex — a white shirt and
#: cream trousers, a football shirt over jeans — so the first rule does
#: not catch them, and the result was a man filed under "Clean girl" and a
#: woman under "Blokecore". A collection is a thing somebody browses *to*,
#: and the cover has to be what the name promised.
#:
#: Everything else is cast across the whole rotation, which is most of the
#: catalogue: a suit, a trench, a football shirt, tailoring and a chore
#: jacket are not on this list, and the set shows women and men in all of
#: them because they read correctly either way.
CAST_LIMITS: dict[str, str] = {
    # The outfit decides.
    "balletcore": "women",
    "coquette": "women",
    "date-night": "women",
    "downtown-romantic": "women",
    "evening": "women",
    "mob-wife": "women",
    "office-siren": "women",
    "wedding-guest": "women",
    # The collection decides.
    "clean-girl": "women",
    "blokecore": "men",
}

#: Kept as a name because the module's tests and its docstring both use it.
WOMENSWEAR: frozenset[str] = frozenset(
    name for name, who in CAST_LIMITS.items() if who == "women"
)


def _castable(category: str, subject: str) -> bool:
    """Whether `subject` can be cast in this collection.

    The cast strings are written as "a <description> man|woman in their
    <decade>", so the gender word is found by looking for it with spaces
    around it — "woman" contains "man", which is exactly the bug a
    substring check would ship.
    """
    limit = CAST_LIMITS.get(category)
    if limit is None:
        return True
    padded = f" {subject} "
    is_man = " man " in padded or " men " in padded
    is_woman = " woman " in padded or " women " in padded
    return is_woman if limit == "women" else is_man


def variant_subject(category: str, index: int, variant: int) -> str:
    """Who is in variant `variant` of `category`.

    Deterministic from the collection's position in the sorted set, which
    holds the property that matters day to day: re-running the script never
    re-rolls a picture that already exists, because every job checks the file
    first.

    **It is positional, so adding a collection reshuffles the assignment for
    everything sorted after it.** The fifty-four variants already on disk
    were cast before `coquette` and the rest were added, so this function no
    longer reports who is in those files — it reports who *would* be cast if
    they were generated today. Delete a variant and regenerate it and you
    will get a different person. That is survivable because the files are the
    artefact and they are never regenerated in bulk, but it is the reason not
    to trust this function as a record of the existing set.
    """
    # The rotation is taken over who can actually wear this outfit, rather
    # than over everybody with a skip: skipping would land both of a
    # collection's variants on the same first eligible person, and two
    # pictures of one person in one outfit is not a variant set.
    pool = [who for who in VARIANT_CASTING if _castable(category, who)]
    return pool[(index * 2 + variant) % len(pool)]


#: Fixed for every cover. This is what makes the set read as one set.
#:
#: **Written to describe a photograph that was taken, not an image to be
#: invented.** The first version of this asked for "editorial fashion
#: photography" and got it: clean, even, and plastic, with skin like
#: moulded resin and clothes that had never been sat down in. Three
#: changes fixed it, and each is here for a reason rather than as a
#: keyword.
#:
#: *Named gear and real lighting.* A camera body, a focal length and a
#: lighting setup are constraints a photograph has; "good lighting" is
#: not. The 35mm at f/2.8 also fixes the depth of field, which is why the
#: wall falls off behind the figure instead of being a flat backdrop.
#:
#: *Imperfections, asked for by name.* Visible pores, stray hairs,
#: creases at the elbow and knee. These are the details the eye uses to
#: decide whether it is looking at a person, and a generator leaves them
#: out unless told.
#:
#: *No "perfect", "flawless", "hyperrealistic" or "8k".* Those words pull
#: hard toward the over-processed, airbrushed look they appear to promise.
#: The way to a real photograph is to describe a real one.
FRAMING = (
    "Candid full-length fashion photograph, head to feet in frame, the "
    "person standing naturally and facing the camera. "
    "Shot on a Sony a7R V with a 35mm lens at f/2.8, editorial fashion "
    "photography, eye-level, slight natural depth of field so the wall "
    "falls off gently behind. "
    "Soft diffuse daylight through a large window to one side, a gentle "
    "fill on the shadow side, a soft natural shadow on the pale concrete "
    "floor. Plain warm off-white plaster wall behind, its texture visible. "
    "Subtle skin texture with visible pores and fine lines, a few stray "
    "hairs out of place, natural fabric wrinkles and creases where the "
    "garment folds at the elbows and knees, the weave and stitching of "
    "the cloth legible. A relaxed, unposed expression. "
    "Muted warm colour, fine photographic film grain, true-to-life "
    "contrast without heavy retouching. "
    "No text, no logo, no brand mark, no watermark, no border, no props."
)


def prompt_for(category: str, who: str | None = None) -> str:
    """The prompt for one picture.

    `who` overrides the cast subject, which is how a variant shows a
    different person in the same clothes. The outfit never changes between a
    collection's pictures: the collection *is* the aesthetic, so swapping the
    clothes would make three pictures of three different collections.
    """
    cast, wearing = SUBJECTS[category]
    return f"{FRAMING}\n\nIn frame: {who or cast}, wearing {wearing}."


async def main() -> int:
    key = os.environ.get("MODEL_API_KEY") or os.environ.get("LUXISH_META_API_KEY")
    if not key:
        print("MODEL_API_KEY is not set. Refusing to pretend this ran.")
        return 2

    args = sys.argv[1:]
    # `--variants` adds the second and third picture of each collection
    # rather than replacing the first. The covers that shipped are not
    # re-rolled by it: they are fine, and paying to change pictures nobody
    # asked to change is the wrong trade.
    variants = "--variants" in args
    # Reshoot. The skip below exists so an interrupted run of paid calls can
    # be restarted without paying twice; it is not meant to stop a
    # deliberate reshoot after the framing changed.
    force = "--force" in args
    wanted = [a for a in args if not a.startswith("--")] or sorted(SUBJECTS)
    unknown = [name for name in wanted if name not in SUBJECTS]
    if unknown:
        print(f"No subject written for: {', '.join(unknown)}")
        print(f"Known: {', '.join(sorted(SUBJECTS))}")
        return 2

    from openai import AsyncOpenAI
    from PIL import Image

    client = AsyncOpenAI(api_key=key, base_url="https://api.meta.ai/v1")
    STYLES.mkdir(parents=True, exist_ok=True)

    ordered = sorted(SUBJECTS)
    jobs: list[tuple[str, int, str | None]] = []
    for category in wanted:
        if variants:
            index = ordered.index(category)
            jobs.append((category, 2, variant_subject(category, index, 0)))
            jobs.append((category, 3, variant_subject(category, index, 1)))
        else:
            jobs.append((category, 0, None))

    for category, variant, who in jobs:
        name = category if variant == 0 else f"{category}-{variant}"
        out = STYLES / f"{name}.webp"
        # Resumable. A run of fifty-four paid calls that cannot be restarted
        # without paying for the ones it already made is a run nobody dares
        # interrupt.
        if variant != 0 and out.exists() and not force:
            print(f"{name} ... already there")
            continue

        print(f"{name} ...", end=" ", flush=True)
        try:
            response = await client.images.generate(
                model="muse-image-1.0", prompt=prompt_for(category, who), n=1
            )
        except Exception as exc:  # noqa: BLE001 - one refusal must not stop the set
            print(f"FAILED {type(exc).__name__}: {str(exc)[:80]}")
            continue

        raw = base64.b64decode(response.model_dump()["data"][0]["b64_json"])
        # Re-encoded to WEBP, never resized. See the module docstring.
        with Image.open(io.BytesIO(raw)) as image:
            image.convert("RGB").save(out, "WEBP", quality=88, method=6)
            print(f"{out.name}  {image.width}x{image.height}  {out.stat().st_size:,} bytes")

    print("\nNow run: python scripts/compute_blurhashes.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
