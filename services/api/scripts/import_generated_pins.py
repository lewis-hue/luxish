"""Post the generated board: new people, their pins, their words.

`generate_seed_pins.py` draws the photographs and writes
`assets/seed-photos/generated/pins.json` beside them. This turns that
into something the app can actually serve: accounts that own the
pictures, published fits carrying the captions and hashtags the specs
describe, and a vision row per pin so discovery can rank them the
moment they land.

**New people, not more posts for the existing ones.** A recommender
learns from who did what. Three hundred pins spread over the handful
of accounts already here would teach it that four people like
everything, which is the opposite of the signal trending and
personalisation need. Each new account gets a scene it mostly posts
in, so the board has actual communities in it.

**The vision row is written here rather than left to the worker.**
The spec already states the subject and the presentation - they are
what the picture was drawn from, so they are facts rather than
guesses, and reading them back off the photograph with a model would
cost 300 calls to recover what we already know. `scripts/
backfill_post_vision.py` still exists for pins that arrive the
ordinary way.

    python scripts/import_generated_pins.py
    python scripts/import_generated_pins.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
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

PINS = (
    seed_photos() / "generated" / "pins.json"
)

#: Who posts them. First name, handle, the scene they mostly post in.
#:
#: Handles are written out rather than minted so a reviewer's board
#: matches the one this repository describes, and so two runs do not
#: produce two sets of people.
POSTERS: tuple[tuple[str, str, str], ...] = (
    ("Imani", "imaniwears", "streetwear"),
    ("Theo", "theo.fits", "streetwear"),
    ("Rena", "renadaily", "minimal"),
    ("Alix", "alixinwool", "minimal"),
    ("Dami", "damitailors", "workwear"),
    ("Priya", "priyaatwork", "workwear"),
    ("Nour", "nourcovered", "modest"),
    ("Yara", "yarainlinen", "modest"),
    ("Kwame", "kwameprints", "heritage"),
    ("Zola", "zolawax", "heritage"),
    ("Esme", "esmeafterdark", "eveningwear"),
    ("Luca", "lucablacktie", "blacktie"),
    ("Robin", "robinonfoot", "outdoors"),
    ("Sam", "samtrailing", "outdoors"),
    ("Mira", "miraindigo", "denim"),
    ("Otis", "otisdenim", "denim"),
    ("Hana", "hanaruns", "training"),
    ("Bea", "beamoves", "workout"),
    ("Ivo", "ivothrifts", "vintage"),
    ("Celeste", "celestelace", "romantic"),
    ("Jonah", "jonahknits", "knitwear"),
    ("Tala", "talaoccasion", "occasion"),
)

#: How far back the board stretches.
#:
#: Trending measures the last 24 hours against a 7-day baseline, so a
#: board posted entirely "now" has no baseline and nothing can rise.
#: Spread over three weeks with a bias toward recent, which is what a
#: real board looks like.
OVER_DAYS = 21


def scene_of(slug: str) -> str:
    """The look a generated slug came from. `workwear-feminine-012`."""
    return slug.split("-")[0]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not PINS.exists():
        print(f"no manifest at {PINS}. Run generate_seed_pins.py first.")
        return 2
    specs = json.loads(PINS.read_text(encoding="utf-8"))
    here = [s for s in specs if (PINS.parent / f"{s['slug']}.webp").is_file()]
    print(f"{len(here)} generated pins on disk")

    if args.dry_run:
        by_scene: dict[str, int] = {}
        for spec in here:
            by_scene[scene_of(spec["slug"])] = (
                by_scene.get(scene_of(spec["slug"]), 0) + 1
            )
        for scene, n in sorted(by_scene.items(), key=lambda kv: -kv[1]):
            print(f"  {scene:14} {n}")
        print(f"\n{len(POSTERS)} people would be created. Nothing written.")
        return 0

    from app.models.media_asset import MediaAsset
    from app.models.posts import Post, PostMedia
    from app.models.post_vision import PostVisionRow
    from app.models.profile import PostTag, Profile
    from app.models.user import User
    from app.storage.local import build_local_store

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = build_local_store(
        environment=settings.environment, root=settings.local_media_root
    )
    rng = random.Random(20261103)
    now = datetime.now(UTC)

    made_people = made_pins = skipped = 0
    try:
        async with maker() as db:
            # The people. Matched on handle, so re-running adds nobody.
            people: dict[str, uuid.UUID] = {}
            for first, handle, scene in POSTERS:
                found = await db.scalar(
                    sa.select(Profile).where(Profile.handle == handle)
                )
                if found is not None:
                    people[handle] = found.user_id
                    continue
                user = User(
                    email=f"{handle}@luxish.local",
                    display_name=first,
                )
                db.add(user)
                await db.flush()
                db.add(
                    Profile(
                        user_id=user.id,
                        handle=handle,
                        links={},
                    )
                )
                people[handle] = user.id
                made_people += 1
            await db.commit()
            print(f"people: {made_people} new, {len(people)} in total")

            # Who posts what: mostly their own scene, sometimes not,
            # because a person who only ever posts one thing is not a
            # person and gives the graph nothing to connect.
            by_scene: dict[str, list[str]] = {}
            for _first, handle, scene in POSTERS:
                by_scene.setdefault(scene, []).append(handle)
            every_handle = [h for _f, h, _s in POSTERS]

            for spec in here:
                slug = spec["slug"]
                raw = (PINS.parent / f"{slug}.webp").read_bytes()
                digest = hashlib.sha256(raw).hexdigest()

                # **Matched on the picture, not on the words.**
                #
                # Captions come from a small set of voices crossed with
                # a small set of garment phrases, so two different pins
                # legitimately share a sentence - and a caption match
                # silently skipped 190 of 300 on the first run. The
                # file is the thing that is actually unique.
                taken = await db.scalar(
                    sa.select(MediaAsset.id).where(
                        MediaAsset.checksum_sha256 == digest
                    )
                )
                if taken is not None:
                    skipped += 1
                    continue

                scene = scene_of(slug)
                pool = by_scene.get(scene) or every_handle
                handle = (
                    pool[rng.randrange(len(pool))]
                    if rng.random() < 0.8
                    else every_handle[rng.randrange(len(every_handle))]
                )
                owner = people[handle]

                with Image.open(io.BytesIO(raw)) as im:
                    width, height = im.size

                asset = MediaAsset(
                    user_id=owner,
                    kind="outfit_photo",
                    # `ready`, not `uploaded`: nothing is going to
                    # process these, and `uploaded` leaves a spinner.
                    status="ready",
                    content_type="image/webp",
                    max_bytes=len(raw),
                    byte_size=len(raw),
                    width=width,
                    height=height,
                    checksum_sha256=digest,
                    publication_consent=True,
                )
                db.add(asset)
                await db.flush()
                key = f"users/{owner}/media/{asset.id}"
                await store.write(key, raw, content_type="image/webp")
                asset.storage_key = key

                # Weighted toward recent, so trending has both a
                # baseline and something rising above it.
                age = timedelta(
                    days=rng.random() ** 2 * OVER_DAYS,
                    hours=rng.randrange(24),
                )
                when = now - age
                post = Post(
                    user_id=owner,
                    caption=spec["caption"],
                    state="published",
                    published_at=when,
                    created_at=when,
                )
                db.add(post)
                await db.flush()
                db.add(
                    PostMedia(post_id=post.id, media_asset_id=asset.id, position=0)
                )
                for tag in spec["tags"]:
                    db.add(PostTag(post_id=post.id, tag=tag))

                # What the picture is of, from the spec it was drawn
                # from. Facts, not a second guess at our own output.
                from app.domain.discovery.subject import Reading, vector_for

                reading = Reading(
                    subject=spec["subject"],
                    presentation=spec["presentation"],
                    facets=(),
                    confidence=1.0,
                ).clean()
                db.add(
                    PostVisionRow(
                        post_id=post.id,
                        asset_id=asset.id,
                        subject=reading.subject,
                        presentation=reading.presentation,
                        confidence=1.0,
                        facets=[],
                        vector=vector_for(reading),
                        note=None,
                        model="spec",
                        prompt_version="seed-pins-v1",
                    )
                )
                made_pins += 1
                if made_pins % 50 == 0:
                    await db.commit()
                    print(f"  {made_pins} posted", flush=True)

            await db.commit()

        print(f"\nposted {made_pins}, already there {skipped}")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
