"""Draw the board: realistic fashion photographs, with words that match.

**Why generated rather than downloaded.** The brief was 300 real,
high-quality fashion photographs, with Pinterest named as the source.
Scraping a platform's media would put other people's copyrighted
photographs into a public repository and it contradicts this project's
own rule - no code downloads third-party platform media (CLAUDE.md,
ADR-009). Unsplash and Pexels would both be legitimate, and both want
an API key this machine does not have. The vendor's image model is
already configured, already paid for, and produces 1280x1920 editorial
photography indistinguishable from the seed set at a glance - so the
pictures are ours, they are safe to commit, and nobody's licence is
being borrowed.

**This is a fashion app and the board says so.** Clothes, and the
things worn with them. The specs below cover no rooms, no food and no
furniture, because a wardrobe app that hosts a photograph of a bed is
a worse version of a general pinboard - and because 60 such pins had
to be taken down to get here.

**The words are derived, not invented.** Every caption and hashtag is
built from the spec the picture was drawn from, so they describe what
is actually in the frame. A generated caption guessing at a generated
photograph is two guesses where the app needs one fact, and
mislabelled pins are exactly what the recommender was taught to
distrust.

    python scripts/generate_seed_pins.py --count 300
    python scripts/generate_seed_pins.py --count 6 --dry-run

Resumable: a spec whose file already exists is skipped, so an
interrupted run continues where it stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from _assets import seed_photos

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("LUXISH_ENVIRONMENT", "local")

import sqlalchemy as sa  # noqa: E402  (after the path insert, deliberately)
from PIL import Image  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings  # noqa: E402
from app.providers.base import (  # noqa: E402
    AIRequest,
    AIRunRecorder,
    Capabilities,
)
from app.providers.meta import MetaProvider  # noqa: E402

#: Where the pictures land. Inside the repository, because a reviewer
#: who clones this and runs the script must get a full board without
#: spending a penny on the vendor.
OUT = seed_photos() / "generated"

#: Long edge after downscaling.
#:
#: The model returns 1280x1920 at about 450KB. Three hundred of those
#: is 135MB in a repository reviewers have to clone, and the app never
#: shows a pin larger than a phone screen. 1440 on the long edge at
#: quality 82 keeps it indistinguishable in the grid and on a pin page
#: while costing roughly a third of that.
LONG_EDGE = 1440
QUALITY = 82

#: How many to draw at once. The vendor is the bottleneck, not this.
AT_ONCE = 5


@dataclass(frozen=True)
class Spec:
    """One pin: what is in it, and what it will be called."""

    slug: str
    #: `app.domain.discovery.subject.SUBJECTS`
    subject: str
    #: `app.domain.discovery.subject.PRESENTATIONS`
    presentation: str
    #: The sentence under the picture, in a person's voice.
    caption: str
    #: Hashtags, lower case, no leading hash.
    tags: tuple[str, ...]
    #: What the model is asked to draw.
    prompt: str

    @property
    def file(self) -> Path:
        return OUT / f"{self.slug}.webp"


#: The aesthetics the app groups by, each with the garments that
#: actually belong to it. Taken from `domain.feed.GROUP_TAGS` so a
#: generated pin lands in a real group rather than in none.
#:
#: **Each look names the presentations it supports.** Picking the
#: two independently produced `a man wearing a lace-trimmed blouse,
#: a full midi skirt and ballet flats`, which is not a menswear fit
#: and is not what anybody searching balletcore wants to see. The
#: constraint is about the garments listed beside it, not about who
#: is allowed to wear what: a look whose description is a skirt and
#: ballet flats describes womenswear, so that is what it is tagged.
LOOKS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "streetwear",
        "an oversized hoodie, wide cargo trousers and chunky trainers",
        ("streetwear", "street", "casual"),
        ("a bus stop at dusk", "a skate park", "a concrete underpass"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "workwear",
        "a sharp wool blazer, straight trousers and leather loafers",
        ("workwear", "office", "tailoring", "corporate"),
        ("a glass office lobby", "a city crossing at rush hour"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "eveningwear",
        "a draped satin slip dress and fine heeled sandals",
        ("evening", "nightout", "cocktail", "datenight"),
        ("a hotel bar", "a lamplit street at night"),
        ("feminine",),
    ),
    (
        "blacktie",
        "a midnight-blue dinner suit with a black bow tie",
        ("evening", "blacktie", "formal", "tailoring"),
        ("a theatre foyer", "a lamplit street at night"),
        ("masculine",),
    ),
    (
        "minimal",
        "a cream knit, wide ecru trousers and square-toe flats",
        ("minimal", "quietluxury", "capsule", "monochrome"),
        ("a white gallery wall", "a bare studio with north light"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "vintage",
        "a 1970s suede jacket, flared denim and a printed scarf",
        ("vintage", "thrifted", "retro", "secondhand"),
        ("a flea market", "a record shop doorway"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "romantic",
        "a lace-trimmed blouse, a full midi skirt and ballet flats",
        ("romantic", "coquette", "balletcore", "lace"),
        ("a park in spring", "a tiled hallway"),
        ("feminine",),
    ),
    (
        "outdoors",
        "a technical shell, a fleece midlayer and trail boots",
        ("outdoors", "gorpcore", "techwear", "utility"),
        ("a hillside path", "a wet city street"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "denim",
        "double denim: a washed jacket over straight indigo jeans",
        ("denim", "doubledenim", "jeans", "casual"),
        ("a brick wall in sunlight", "a car park at golden hour"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "workout",
        "a fitted training top, leggings and running shoes",
        ("activewear", "gym", "workout", "sportswear"),
        ("a running track", "a gym doorway"),
        ("feminine",),
    ),
    (
        "training",
        "a technical tee, training shorts and running shoes",
        ("activewear", "gym", "workout", "sportswear"),
        ("a running track", "a gym doorway"),
        ("masculine", "androgynous"),
    ),
    (
        "modest",
        "a long-sleeved maxi dress with a draped headscarf",
        ("modest", "modestfashion", "hijabi", "covered"),
        ("a sunlit courtyard", "a quiet city street"),
        ("feminine",),
    ),
    (
        "heritage",
        "a tailored jacket in bold west-african wax print",
        ("heritage", "ankara", "african", "traditional"),
        ("a market street", "a painted wall in strong sun"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "occasion",
        "a tailored two-piece in soft pastel with a clutch",
        ("occasion", "weddingguest", "party", "formal"),
        ("stone steps outside a venue", "a garden in late sun"),
        ("feminine", "masculine", "androgynous"),
    ),
    (
        "knitwear",
        "a heavy cable-knit jumper over straight wool trousers",
        ("knitwear", "wool", "casual", "basics"),
        ("a harbour wall", "a park in late autumn"),
        ("feminine", "masculine", "androgynous"),
    ),
)

#: The close-up subjects. Not outfits, so they carry their own
#: `subject` and almost always no presentation at all.
DETAILS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "footwear",
        "footwear",
        "a pair of worn tan leather chelsea boots on stone",
        ("shoes", "footwear", "leather", "boots"),
    ),
    (
        "trainers",
        "footwear",
        "a pair of white leather trainers, side on, on pale concrete",
        ("shoes", "trainers", "sneakers", "footwear"),
    ),
    (
        "bag",
        "bag",
        "a structured tan leather shoulder bag on a wooden bench",
        ("bags", "leather", "accessories", "handbag"),
    ),
    (
        "totebag",
        "bag",
        "a heavy canvas tote resting against a painted wall",
        ("bags", "tote", "accessories", "canvas"),
    ),
    (
        "jewellery",
        "jewellery",
        "a stack of fine gold rings and a thin chain bracelet on linen",
        ("jewellery", "gold", "accessories", "rings"),
    ),
    (
        "earrings",
        "jewellery",
        "a pair of sculptural gold hoop earrings on a marble surface",
        ("jewellery", "earrings", "gold", "accessories"),
    ),
    (
        "knitwear",
        "garment",
        "a folded oatmeal wool cable knit jumper on a plain surface",
        ("knitwear", "wool", "basics", "flatlay"),
    ),
    (
        "coat",
        "garment",
        "a camel wool overcoat hung against a plain wall",
        ("coats", "wool", "outerwear", "tailoring"),
    ),
    (
        "scarf",
        "garment",
        "a printed silk scarf folded loosely on a pale surface",
        ("accessories", "silk", "scarf", "print"),
    ),
    (
        "beauty",
        "beauty",
        "a close crop of softly brushed-out hair and bare, glowing skin",
        ("beauty", "hair", "skin", "natural"),
    ),
)

#: How a person actually writes about what they wore.
VOICES: tuple[str, ...] = (
    "{look}. Third wear this week and no regrets.",
    "Finally got {look} to sit right.",
    "{look} — the only thing I reach for when it is cold.",
    "Wore {look} out and nobody let me leave without asking.",
    "{look}. Charity shop, two pounds, still the best thing I own.",
    "Trying {look} again now the weather has turned.",
    "{look}. Simple, and it does everything.",
    "This is {look} and I am not taking it off.",
)

PRESENTATIONS = ("feminine", "masculine", "androgynous")


def specs(count: int) -> list[Spec]:
    """A deterministic, varied set. Same count, same board."""
    import random

    # Seeded, so a reviewer regenerating gets the board this repository
    # describes rather than a different one.
    rng = random.Random(20261103)
    out: list[Spec] = []
    n = 0
    while len(out) < count:
        n += 1
        # Roughly four outfits to every close-up: the board is mostly
        # people wearing things, which is what the app is for.
        if n % 5 == 0:
            name, subject, scene, tags = DETAILS[rng.randrange(len(DETAILS))]
            slug = f"{name}-{n:03d}"
            caption = scene[0].upper() + scene[1:] + "."
            prompt = (
                f"A high-quality editorial product photograph: {scene}. "
                "Soft natural daylight, shallow depth of field, 50mm, "
                "muted and realistic colour, fine film grain, no text, "
                "no watermark, no people's faces. Photorealistic. "
                # **Upright, like everything else.** Without saying so
                # the model returned these 1440x960 while the outfit
                # prompt - which does say it - came back vertical. The
                # app draws every picture in one upright shell, so 60
                # landscape close-ups sat in the grid letterboxed and
                # wrong. Said twice, because one mention lost to a
                # long prompt is what produced them.
                "Vertical portrait orientation, 3:4, taller than wide."
            )
            out.append(
                Spec(
                    slug=slug,
                    subject=subject,
                    presentation="unspecified",
                    caption=caption,
                    tags=tuple(dict.fromkeys(tags)),
                    prompt=prompt,
                )
            )
            continue

        look, garments, tags, settings, wearable_as = LOOKS[rng.randrange(len(LOOKS))]
        # Only a presentation this look actually describes. See the note
        # on LOOKS: picking the two independently produced a man in a
        # midi skirt and ballet flats.
        presentation = wearable_as[rng.randrange(len(wearable_as))]
        setting = settings[rng.randrange(len(settings))]
        slug = f"{look}-{presentation}-{n:03d}"
        caption = VOICES[rng.randrange(len(VOICES))].format(look=garments)
        # A caption starts with a capital. The garment phrases are
        # written lower case so they can sit mid-sentence in the voices
        # that need them to.
        caption = caption[0].upper() + caption[1:]
        who = {
            "feminine": "a woman",
            "masculine": "a man",
            "androgynous": "an androgynous person",
        }[presentation]
        prompt = (
            f"Editorial street-style photograph, full length, {who} wearing "
            f"{garments}, {setting}. Natural daylight, 35mm, shallow depth "
            "of field, muted realistic colour, fine film grain, candid pose, "
            "no text, no watermark, no logos. Photorealistic. "
            "Vertical portrait orientation, 2:3, taller than wide."
        )
        extra = (
            ("menswear",)
            if presentation == "masculine"
            else ("womenswear",)
            if presentation == "feminine"
            else ("androgynous", "unisex")
        )
        out.append(
            Spec(
                slug=slug,
                subject="outfit",
                presentation=presentation,
                caption=caption,
                tags=tuple(dict.fromkeys(tags + extra + ("ootd",))),
                prompt=prompt,
            )
        )
    return out


class NotUpright(Exception):
    """The model drew it wider than it is tall.

    A refusal rather than a crop. The app draws every picture in one
    upright shell, so a landscape pin is letterboxed in the grid and
    wrong on a pin page - and cropping a composition the model framed
    horizontally would take the subject out of half of them. Rejecting
    it means the retry draws a portrait one instead, which is the thing
    actually wanted.
    """


def shrink(raw: bytes) -> bytes:
    """Down to something a repository can carry and a phone can show."""
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        width, height = im.size
        if width >= height:
            raise NotUpright(f"{width}x{height}")
        scale = LONG_EDGE / max(width, height)
        if scale < 1:
            im = im.resize((round(width * scale), round(height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=QUALITY, method=6)
        return buf.getvalue()


async def draw(provider: MetaProvider, spec: Spec) -> tuple[Spec, bool, str]:
    """One picture, written to disk. Returns whether it is new."""
    if spec.file.exists() and spec.file.stat().st_size > 10_000:
        return spec, False, "already there"
    try:
        result = await provider.generate_image(
            AIRequest(
                prompt=spec.prompt,
                prompt_version="seed-pins-v1",
                purpose="seed_image",
                needs=Capabilities(text_in=True, image_out=True),
            ),
            user_id=uuid.uuid4(),
        )
        images = result.image_data or ()
        if not images:
            return spec, False, "no image came back"
        raw = images[0]
        data = getattr(raw, "data", raw)
        if isinstance(data, str):
            import base64

            data = base64.b64decode(data)
        spec.file.parent.mkdir(parents=True, exist_ok=True)
        try:
            body = shrink(bytes(data))
        except NotUpright as wrong:
            return spec, False, f"landscape ({wrong}); run again to retry"
        spec.file.write_bytes(body)
        return spec, True, f"{spec.file.stat().st_size // 1024}KB"
    except Exception as caught:  # noqa: BLE001 - reported, never swallowed
        return spec, False, f"{type(caught).__name__}: {str(caught)[:80]}"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the specs and draw nothing",
    )
    args = parser.parse_args()

    wanted = specs(args.count)
    if args.dry_run:
        for spec in wanted[:12]:
            print(f"  {spec.slug:34} {spec.subject:10} {spec.presentation:12}")
            print(f"      {spec.caption}")
            print(f"      #{' #'.join(spec.tags)}")
        print(f"\n{len(wanted)} specs. Nothing drawn.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(get_settings().database_url)

    # **SQLite has one writer, and five workers each record a cost.**
    #
    # Every vendor call writes an `ai_runs` row, so concurrency that is
    # harmless for the HTTP calls is five writers on one file. Without
    # these the second worker gets "database is locked" and the whole
    # batch fails on bookkeeping rather than on anything to do with
    # drawing. WAL lets readers and the writer coexist; the timeout
    # makes a blocked writer wait its turn instead of raising. Both are
    # no-ops on Postgres, where this script also has to run.
    if engine.dialect.name == "sqlite":

        @sa.event.listens_for(engine.sync_engine, "connect")
        def _wait_your_turn(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    maker = async_sessionmaker(engine, expire_on_commit=False)
    gate = asyncio.Semaphore(AT_ONCE)
    made = skipped = failed = 0

    try:
        # **A session per worker, not one shared across them.**
        #
        # An AsyncSession is not safe for concurrent use: every call
        # records its cost through `AIRunRecorder`, and five tasks
        # writing a run against one session fails five ways with
        # "this session is provisioning a new connection". Sessions are
        # cheap; the vendor call is what takes the time.
        async def one(spec: Spec, at: int):
            nonlocal made, skipped, failed
            async with gate:
                if spec.file.exists() and spec.file.stat().st_size > 10_000:
                    spec, fresh, note = spec, False, "already there"
                else:
                    async with maker() as db:
                        provider = MetaProvider(recorder=AIRunRecorder(db))
                        spec, fresh, note = await draw(provider, spec)
                        await db.commit()
            if fresh:
                made += 1
            elif "already" in note:
                skipped += 1
            else:
                failed += 1
            print(f"  [{at}/{len(wanted)}] {spec.slug:34} {note}", flush=True)

        await asyncio.gather(*(one(spec, i + 1) for i, spec in enumerate(wanted)))

        manifest = OUT / "pins.json"
        manifest.write_text(
            json.dumps(
                [asdict(s) for s in wanted if s.file.exists()],
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        total = sum(f.stat().st_size for f in OUT.glob("*.webp"))
        print(
            f"\ndrawn {made}, already there {skipped}, failed {failed}. "
            f"{total // (1024 * 1024)}MB on disk. Manifest: {manifest.name}"
        )
        return 0 if failed == 0 else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
