"""Populate the app with a community, for showing it to somebody.

**This is a demonstration fixture and it says so in the data.** Every
account's email ends in ``@sample.luxish.invalid`` — ``.invalid`` is
reserved by RFC 2606 and can never be a real address — and every post
carries ``screen_mode="seed"``, which is the column that exists so a
fixture can never be mistaken for screened content. Nothing here
pretends to be a live integration.

**It is built so the engine has something to do.** A recommendation
system with forty posts and no reactions ranks nothing; the interesting
behaviour — trending groups, taste-ordered boards, people worth
following — only appears when there is a spread of engagement across a
spread of tastes. So the reactions are deliberately uneven: a few fits
are loved, most are quiet, and the people who react cluster by the
aesthetic they are into, which is what makes personalisation visible
rather than theoretical.

    python scripts/seed_demo_world.py --join me@luxish.local --photos "E:/FASHION"
    python scripts/seed_demo_world.py --remove

Deterministic: the same cast and the same numbers every run, so a demo
rehearsed once looks the same the second time.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _assets import seed_photos

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlalchemy as sa  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import build_engine, session_factory  # noqa: E402
from app.models.follow import Follow  # noqa: E402
from app.models.moodboard import Moodboard, MoodboardPin
from app.models.posts import Post, PostSave  # noqa: E402
from app.models.profile import PostReaction, PostTag, Profile, REACTIONS  # noqa: E402
from app.models.media_asset import MediaAsset  # noqa: E402
from app.models.posts import PostMedia  # noqa: E402
from app.models.user import User  # noqa: E402
from app.storage.local import build_local_store  # noqa: E402

DOMAIN = "sample.luxish.invalid"
SEED = 20261031

UTC = timezone.utc

#: The groups people here are actually into, and the hashtags each one
#: writes. Taken from `app.domain.feed.GROUP_TAGS`, which is what the
#: board groups by — so a seeded post lands somewhere real rather than
#: in a group nobody browses.
SCENES: dict[str, list[str]] = {
    "streetwear": ["streetwear", "street", "y2k", "skater", "grunge"],
    "workout": ["gym", "activewear", "athleisure", "running"],
    "office": ["office", "workwear", "tailoring", "corporate"],
    "evening": ["evening", "datenight", "cocktail", "nightout"],
    "minimal": ["minimal", "cleangirl", "capsule", "quietluxury"],
    "vintage": ["thrifted", "vintage", "archive", "secondhand"],
    "romantic": ["coquette", "balletcore", "feminine", "lace"],
    "outdoors": ["gorpcore", "techwear", "utility", "hiking"],
    "occasion": ["weddingguest", "festival", "party"],
    "denim": ["denim", "doubledenim", "jeans"],
    # Three verticals that are not clothes.
    #
    # A recommender that has only ever seen outfits cannot be shown to
    # be recommending anything: every candidate matches every person,
    # so a feed that ignored the user entirely would look correct.
    # Decor, accessories and beauty give it populations that genuinely
    # should not reach the same people, which is what makes a wrong
    # answer visible.
    "decor": ["interiors", "homedecor", "bedroom", "livingroom"],
    "accessories": ["jewellery", "accessories", "piercing", "bags"],
    "beauty": ["beauty", "nails", "makeup", "lips"],
}

#: Cast across the regions this app ships to and the age band it is for.
#: Four or five per scene, so every group clears the trending floor and
#: `style_twins` has cohorts to find.
PEOPLE: list[tuple[str, str, str]] = [
    # (first name, handle, scene)
    ("Amara", "amaraonthe9", "streetwear"),
    ("Tunde", "tundewears", "streetwear"),
    ("Kai", "kai.exe", "streetwear"),
    ("Sade", "sadeinlagos", "streetwear"),
    ("Jun", "jun.streets", "streetwear"),
    ("Noor", "noormoves", "workout"),
    ("Mateo", "mateoruns", "workout"),
    ("Dami", "damidoesreps", "workout"),
    ("Lena", "lena.lifts", "workout"),
    ("Mei", "meiatwork", "office"),
    ("Jonas", "jonas.suits", "office"),
    ("Keiko", "keikotailored", "office"),
    ("Ravi", "ravi.9to5", "office"),
    ("Zara", "zaraafterdark", "evening"),
    ("Ines", "inesnights", "evening"),
    ("Camille", "camille.pm", "evening"),
    ("Yuki", "yuki.less", "minimal"),
    ("Anders", "anders.plain", "minimal"),
    ("Priya", "priya.capsule", "minimal"),
    ("Sofia", "sofiathrifts", "vintage"),
    ("Theo", "theo.archive", "vintage"),
    ("Marta", "marta.secondhand", "vintage"),
    ("Elodie", "elodie.lace", "romantic"),
    ("Hana", "hana.ribbons", "romantic"),
    ("Isla", "isla.soft", "romantic"),
    ("Bram", "bram.outside", "outdoors"),
    ("Nia", "nia.trails", "outdoors"),
    ("Oskar", "oskar.shell", "outdoors"),
    ("Fatima", "fatima.guest", "occasion"),
    ("Luca", "luca.invited", "occasion"),
    ("Ada", "ada.celebrates", "occasion"),
    ("Jess", "jess.indigo", "denim"),
    ("Omar", "omar.raw", "denim"),
    ("Pia", "pia.doubledenim", "denim"),
    # Five apiece, matching the rule above the list: enough that each
    # group clears the trending floor on its own, so "trending in
    # decor" is a real population rather than one enthusiastic person.
    ("Wanjiru", "wanjiru.athome", "decor"),
    ("Eli", "eli.interiors", "decor"),
    ("Mira", "mira.softrooms", "decor"),
    ("Kwame", "kwame.builds", "decor"),
    ("Juno", "juno.cloudbed", "decor"),
    ("Ayesha", "ayesha.gold", "accessories"),
    ("Dior", "dior.stacks", "accessories"),
    ("Tomi", "tomi.hoops", "accessories"),
    ("Suki", "suki.charms", "accessories"),
    ("Rae", "rae.pierced", "accessories"),
    ("Chidi", "chidi.gloss", "beauty"),
    ("Yara", "yara.nails", "beauty"),
    ("Bea", "bea.lipcombo", "beauty"),
    ("Nneka", "nneka.glow", "beauty"),
    ("Soo", "soo.chrome", "beauty"),
]

#: Captions per scene. Written as things somebody would actually post,
#: because a feed of "Outfit 1", "Outfit 2" demonstrates nothing.
CAPTIONS: dict[str, list[str]] = {
    "streetwear": [
        "Layered for the matatu commute.",
        "Baggy everything, finally got the proportions right.",
        "Found these at a stall in Gikomba. No regrets.",
        "Third day running in this jacket.",
        "Cargos doing the heavy lifting again.",
    ],
    "workout": [
        "Gym to lunch without going home.",
        "Track jacket does office hours now.",
        "Ran for the bus in these and regretted nothing.",
        "Matching set because the laundry won.",
        "Leggings with pockets. Life changing.",
    ],
    "office": [
        "Same blazer, third way this week.",
        "No tie. Nobody has said anything.",
        "Trousers finally taken in. Worth the wait.",
        "Soft tailoring for a hard Monday.",
        "This is what I wear when there are meetings.",
    ],
    "evening": [
        "Slip dress, flat shoes, zero regrets.",
        "Dressed for a table of eight.",
        "The coat is the outfit.",
        "Going out in what I wore all day, plus earrings.",
    ],
    "minimal": [
        "Three colours, that is the whole wardrobe.",
        "White shirt, again.",
        "Everything here has been worn fifty times.",
        "Bought nothing this month.",
    ],
    "vintage": [
        "All of this is second hand.",
        "Ninety bob at the market.",
        "My mother wore this in the eighties.",
        "Mended the elbow myself.",
    ],
    "romantic": [
        "Ribbons are back and I am not sorry.",
        "Lace with heavy boots. Balance.",
        "Soft everything kind of day.",
    ],
    "outdoors": [
        "Technical, but for town.",
        "Rained the whole way and I stayed dry.",
        "Shell jacket over everything, as usual.",
    ],
    "occasion": [
        "Wedding guest, not upstaging anybody.",
        "Festival fit, day two.",
        "Dressed for a party that turned out casual.",
    ],
    "denim": [
        "Broke in the straight legs properly.",
        "Double denim, one shade apart. It works.",
        "These were my sister's.",
        "Raw denim, six months, no wash.",
    ],
    "decor": [
        "Finally finished the bedroom corner.",
        "Boucle headboard was the whole budget.",
        "Rearranged everything for the light.",
        "Thrifted the side table in Ngara.",
        "Warm whites only in this house.",
    ],
    "accessories": [
        "Stacked three today, no regrets.",
        "Gold against this top, every time.",
        "Got the second piercing done.",
        "Charm bracelet is slowly getting heavy.",
        "Sunglasses doing the whole outfit.",
    ],
    "beauty": [
        "Chrome on the tips, nothing else.",
        "This gloss over a brown liner.",
        "Took two hours and worth it.",
        "Matching the nails to the bag now.",
        "Glitter lip, one layer, let it set.",
    ],
}

#: Looks from the app's own taxonomy, so a seeded fit has a cover to
#: render until it has a photograph of its own.
#: What people call their boards, per scene.
#:
#: **Boards are the other half of the graph, and without them there is
#: no graph at all.** This app's recommender walks
#: person -> pin -> board -> pin, which is the shape this rests on: two
#: pins are related because somebody put them on the same board, not
#: because a model decided they looked alike. Thirty-four accounts
#: with no boards between them leave that walk with nowhere to go
#: after its first step, so every "related" answer falls back to tags.
BOARD_NAMES: dict[str, list[str]] = {
    "streetwear": ["baggy szn", "street archive", "fits i steal"],
    "workout": ["gym fits", "run club", "sets"],
    "office": ["work capsule", "tailoring", "monday"],
    "evening": ["going out", "after dark", "dress code"],
    "minimal": ["quiet", "capsule", "neutrals"],
    "vintage": ["thrift finds", "archive", "second hand"],
    "romantic": ["soft", "ribbons", "lace"],
    "outdoors": ["trail", "shell layers", "utility"],
    "occasion": ["wedding guest", "invited", "the function"],
    "denim": ["indigo", "denim on denim", "raw"],
    "decor": ["the bedroom", "soft rooms", "someday house", "corners"],
    "accessories": ["gold only", "stacks", "second hole", "charms"],
    "beauty": ["nails", "lip combos", "chrome", "glow"],
}

#: Which scenes bleed into each other on a real person's boards.
#:
#: **This is the part that makes the recommender worth testing.** If
#: every board held one scene, a walk could never leave the scene it
#: started in and a recommender that simply returned "more of the same
#: tag" would score perfectly. People do not curate that way: somebody
#: boarding streetwear also boards the jewellery worn with it, and
#: somebody boarding minimal interiors boards minimal clothes. Those
#: crossings are the edges that let the walk discover something the
#: tag index could not.
NEAR: dict[str, list[str]] = {
    "streetwear": ["accessories", "denim"],
    "workout": ["streetwear"],
    "office": ["minimal"],
    "evening": ["beauty", "accessories"],
    "minimal": ["decor", "office"],
    "vintage": ["denim", "decor"],
    "romantic": ["beauty", "decor"],
    "outdoors": ["workout"],
    "occasion": ["evening", "beauty"],
    "denim": ["streetwear", "vintage"],
    "decor": ["minimal", "romantic"],
    "accessories": ["beauty", "streetwear"],
    "beauty": ["accessories", "evening"],
}

#: Photographs to post, grouped the way this app groups them.
#:
#: **Supplied by the operator, on disk, not fetched from anywhere.** The
#: rule in `AGENTS.md` is that no code downloads from Instagram, TikTok
#: or another platform, and that analysis runs on user-supplied media; this
#: reads a folder the operator pointed at. Several of the filenames look
#: like saved pins, so these are fine for a demonstration and are **not**
#: licensed for production — the rights question is real and belongs to
#: whoever ships it, which is why nothing here claims otherwise.
#:
#: Point at it with `--photos "E:/FASHION"`, or set `LUXISH_PHOTO_LIBRARY`.
PHOTO_ROOT_ENV = "LUXISH_PHOTO_LIBRARY"

#: Folder name to the hashtags somebody posting it would write. The
#: folders are already the app's categories, which is the whole reason
#: this works: the grouping is the operator's, not a guess.
FOLDER_TAGS: dict[str, list[str]] = {
    "AFRICAN WEAR FOR BOTH MEN AND WOMEN": ["heritage", "ankara", "ootd"],
    "COLORS YOU CAN MATCH": ["colour", "styling", "ootd"],
    "LGBT CASUAL WEAR": ["casual", "androgynous", "ootd"],
    "LGBT ELEGANT WEAR": ["evening", "androgynous", "cocktail"],
    "LGBT OFFICIAL WEAR": ["office", "tailoring", "androgynous"],
    "LGBT SPORT WEAR": ["gym", "activewear", "androgynous"],
    "LGBT STREET WEAR": ["streetwear", "androgynous", "street"],
    "MEN CASUAL": ["casual", "menswear", "ootd"],
    "MEN ELEGANT": ["evening", "menswear", "tailoring"],
    "MEN OFFICIAL": ["office", "menswear", "workwear"],
    "MEN SPORT WEAR": ["gym", "activewear", "menswear"],
    "MEN STREETWEAR": ["streetwear", "menswear", "street"],
    "MODEST OUTFITS": ["modest", "layering", "ootd"],
    "OCCASIONS OUTFIT FOR WOMEN": ["weddingguest", "party", "occasion"],
    "OCCATION OUTFITS": ["weddingguest", "party", "occasion"],
    "WOMEN CASUAL": ["casual", "ootd"],
    "WOMEN ELEGANT": ["evening", "cocktail"],
    "WOMEN OFFICIAL": ["office", "workwear", "tailoring"],
    "WOMEN SPORT WEAR": ["gym", "activewear"],
    "WOMEN STREETWEAR": ["streetwear", "street", "y2k"],
    # The three folders added to the drive in November, in the
    # drive's own spelling. The lower-case keys below are the same
    # pictures once `import_seed_photos.py` has brought them into the
    # repository, so seeding works pointed at either place.
    "ACCESSORIES": ["jewellery", "accessories", "piercing"],
    "FURNITURE": ["interiors", "homedecor", "bedroom"],
    # Named PORTRAITS at the source and it is not portraits: lips,
    # nails and makeup. Tagged on what the pictures are.
    "PORTRAITS": ["beauty", "nails", "makeup"],
    # The folders committed to this repository, so a clone with no
    # external library still seeds something real. Lower-case because
    # `import_seed_photos.py` writes them that way; the upper-case
    # keys above are the external drive's own folder names.
    "modest": ["modest", "layering", "ootd"],
    "furniture": ["interiors", "homedecor", "bedroom"],
    "accessories": ["jewellery", "accessories", "piercing"],
    # Filed as PORTRAITS at the source and renamed on import: the
    # folder is lips, nails and makeup close-ups, not portraits of
    # people. Tagged on what it is.
    "beauty": ["beauty", "nails", "makeup"],
}


#: Photographs committed to the repository, so the seed works on a
#: fresh clone with no external drive attached. A subset — the full
#: library is too large to carry — but enough that Discover is never
#: empty for somebody who just checked the project out.
BUNDLED_PHOTOS = seed_photos()


def photo_root() -> Path | None:
    """Where the pictures are.

    The flag wins, then the environment, then whatever is committed.
    Falling back to the bundled set rather than to nothing is what makes
    `seed_demo_world.py` work immediately after a clone.
    """
    if "--photos" in sys.argv:
        at = sys.argv.index("--photos")
        if at + 1 < len(sys.argv):
            return Path(sys.argv[at + 1])
    raw = os.environ.get(PHOTO_ROOT_ENV)
    if raw:
        return Path(raw)
    return BUNDLED_PHOTOS if BUNDLED_PHOTOS.exists() else None


#: Pictures whose folder is wrong at the source, and where they go.
#:
#: **A mislabelled picture is not a cosmetic problem here.** Twelve
#: beds and sofas arrived in `OCCATION OUTFITS`, so they were seeded
#: as occasion-wear and tagged `#weddingguest` - and then the feed
#: faithfully offered wedding outfits to somebody looking at a couch,
#: because every relatedness signal in the app ultimately read that
#: tag. `import_seed_photos.py` already routes these correctly on the
#: way into the repository; this is the same rule for seeding straight
#: from the drive, which is how the bad rows got in.
MISFILED_INTO: dict[str, str] = {"OCCATION OUTFITS": "FURNITURE"}
MISFILED_MARKERS = (
    "bedroom",
    "sofa",
    "sectional",
    "chaise",
    "living room",
    "bed with",
    "cloud bed",
    "platform bed",
    "headboard",
    "upholstered",
)

#: The ones no rule can catch, listed by name.
#:
#: Six of the twelve misfiled pictures are called `download (5).jpg`
#: through `download (10).jpg`. There is nothing in a filename like
#: that to match on, which is the whole lesson of this list: a label
#: is a claim, and when the claim is empty the only way to know what
#: a picture is, is to look at it. These were looked at.
MISFILED_BY_NAME: frozenset[str] = frozenset(f"download ({n}).jpg" for n in range(5, 11))


def photos_by_folder(root: Path) -> dict[str, list[Path]]:
    """Every readable picture, by the folder that groups it.

    The folder is the label, so a picture in the wrong folder gets
    the wrong label. The few that are known to be misfiled at the
    source are moved here rather than at the far end, where the only
    evidence left is a hashtag nobody can check.
    """
    out: dict[str, list[Path]] = {}
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        found = sorted(
            path
            for path in folder.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        if not found:
            continue
        elsewhere = MISFILED_INTO.get(folder.name)
        if elsewhere:
            moved = [
                path
                for path in found
                if path.name in MISFILED_BY_NAME
                or any(m in path.name.lower() for m in MISFILED_MARKERS)
            ]
            if moved:
                out.setdefault(elsewhere, []).extend(moved)
                found = [path for path in found if path not in set(moved)]
                print(
                    f"  {len(moved)} pictures moved from "
                    f"{folder.name} to {elsewhere} (misfiled at the source)"
                )
        if found:
            out.setdefault(folder.name, []).extend(found)
    return out


async def store_photo(db, store, *, user_id, path: Path) -> MediaAsset | None:
    """Import one picture as a media asset the app can serve.

    Re-encoded to WEBP at a sane width: the library holds everything
    from thumbnails to 4000px, and a feed that ships the originals is a
    feed nobody on a Kenyan mobile connection will scroll.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if image.width > 1200:
                ratio = 1200 / image.width
                image = image.resize((1200, int(image.height * ratio)))
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=82, method=4)
            body = buffer.getvalue()
            width, height = image.width, image.height
    except Exception:
        # One unreadable file must not stop the seed.
        return None

    asset = MediaAsset(
        user_id=user_id,
        kind="outfit_photo",
        # `ready`, not `uploaded`: nothing is going to process these, and
        # `uploaded` would leave a permanent spinner on a finished post.
        status="ready",
        content_type="image/webp",
        max_bytes=len(body),
        byte_size=len(body),
        width=width,
        height=height,
        checksum_sha256=hashlib.sha256(body).hexdigest(),
        # Published by being posted, which is what a post *is*.
        publication_consent=True,
    )
    db.add(asset)
    await db.flush()
    key = f"users/{user_id}/media/{asset.id}"
    await store.write(key, body, content_type="image/webp")
    asset.storage_key = key
    return asset


def _args() -> tuple[str | None, bool]:
    join = None
    if "--join" in sys.argv:
        at = sys.argv.index("--join")
        if at + 1 < len(sys.argv):
            join = sys.argv[at + 1]
    return join, "--remove" in sys.argv


async def _remove(db) -> int:
    ids = list(await db.scalars(sa.select(User.id).where(User.email.like(f"%@{DOMAIN}"))))
    if not ids:
        print("Nothing seeded.")
        return 0
    posts = list(await db.scalars(sa.select(Post.id).where(Post.user_id.in_(ids))))
    for table, column in (
        (PostReaction, PostReaction.post_id),
        (PostSave, PostSave.post_id),
        (PostTag, PostTag.post_id),
    ):
        if posts:
            await db.execute(sa.delete(table).where(column.in_(posts)))
    # Reactions and saves *by* these accounts on anybody's posts.
    await db.execute(sa.delete(PostReaction).where(PostReaction.user_id.in_(ids)))
    await db.execute(sa.delete(PostSave).where(PostSave.user_id.in_(ids)))
    if posts:
        await db.execute(sa.delete(PostMedia).where(PostMedia.post_id.in_(posts)))
    # Boards first: a pin references a post, so deleting posts out
    # from under them leaves rows pointing at nothing.
    boards = list(await db.scalars(sa.select(Moodboard.id).where(Moodboard.user_id.in_(ids))))
    if boards:
        await db.execute(sa.delete(MoodboardPin).where(MoodboardPin.moodboard_id.in_(boards)))
    await db.execute(sa.delete(Moodboard).where(Moodboard.user_id.in_(ids)))
    await db.execute(sa.delete(Post).where(Post.user_id.in_(ids)))
    await db.execute(sa.delete(MediaAsset).where(MediaAsset.user_id.in_(ids)))
    await db.execute(sa.delete(Profile).where(Profile.user_id.in_(ids)))
    await db.execute(
        sa.delete(Follow).where(sa.or_(Follow.follower_id.in_(ids), Follow.followee_id.in_(ids)))
    )
    await db.execute(sa.delete(User).where(User.id.in_(ids)))
    await db.commit()
    print(f"Removed {len(ids)} sample accounts and {len(posts)} posts.")
    return 0


async def _seed(db, join: str | None) -> int:
    rng = random.Random(SEED)
    now = datetime.now(UTC)

    await _remove(db)

    print(f"Seeding {len(PEOPLE)} people ...")
    users: dict[str, User] = {}
    for name, handle, scene in PEOPLE:
        user = User(email=f"{handle}@{DOMAIN}", email_verified=True, display_name=name)
        db.add(user)
        await db.flush()
        db.add(
            Profile(
                user_id=user.id,
                handle=handle,
                bio=f"{scene} mostly. Nairobi.",
                # Approved, because a seeded profile that sat in review
                # would show the demo an empty bio and nothing else.
                bio_public=f"{scene} mostly. Nairobi.",
                bio_state="published",
                links=({"tiktok": handle.replace(".", "")} if rng.random() < 0.6 else {}),
            )
        )
        users[handle] = user
    await db.commit()

    # ---------------------------------------------------------------- #
    # Posting
    # ---------------------------------------------------------------- #
    root = photo_root()
    library = photos_by_folder(root) if root and root.exists() else {}
    store = (
        build_local_store(
            environment=get_settings().environment,
            root=get_settings().local_media_root,
        )
        if library
        else None
    )

    if library:
        total = sum(len(v) for v in library.values())
        print(f"Posting {total} photographs from {root} ...")
    else:
        print("Not posting: no photograph library found.")
        if root:
            print(f"  {root} is not readable")

    posts: list[tuple[Post, str]] = []

    if library:
        # **One photograph is posted once.** Two people posting the same
        # picture is the thing that makes a seeded feed obviously seeded,
        # so the library is dealt out rather than sampled.
        deck: list[tuple[str, Path]] = [
            (folder, path) for folder, paths in library.items() for path in paths
        ]
        rng.shuffle(deck)

        # Hand each person pictures from folders that match what they are
        # into where possible, so a streetwear account does not post
        # occasion wear.
        wanted: dict[str, list[str]] = {}
        for folder, tags in FOLDER_TAGS.items():
            for group in set(g for t in tags for g, ts in SCENES.items() if t in ts):
                wanted.setdefault(group, []).append(folder)

        cast = list(PEOPLE)
        at = 0
        for folder, path in deck:
            # Whose scene does this folder belong to? Anybody, if none.
            owners = [(n, h, sc) for n, h, sc in cast if folder in wanted.get(sc, [])] or cast
            name, handle, scene = owners[at % len(owners)]
            at += 1
            user = users[handle]

            asset = await store_photo(db, store, user_id=user.id, path=path)
            if asset is None:
                continue

            tags = list(FOLDER_TAGS.get(folder, ["ootd"]))
            caption = rng.choice(CAPTIONS.get(scene, CAPTIONS["streetwear"]))
            when = now - timedelta(days=rng.randint(0, 45), hours=rng.randint(0, 23))
            post = Post(
                user_id=user.id,
                caption=f"{caption} " + " ".join(f"#{t}" for t in tags),
                state="published",
                # Never met the screen, and the column says so.
                screen_mode="seed",
                published_at=when,
            )
            db.add(post)
            await db.flush()
            db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
            for tag in tags:
                db.add(PostTag(post_id=post.id, tag=tag, created_at=when))
            posts.append((post, scene))
        await db.commit()
    else:
        # **No library, no fits.** Every fit here is a photograph, and a
        # row with no media renders as an empty frame - a board of those
        # reads as a broken app rather than an unseeded one. This branch
        # used to write fits pointing at a catalogue entry and let the
        # card draw its artwork; the catalogue is gone, so the honest
        # answer is to say what is missing.
        print(
            "  no photograph library found, so no fits were posted.\n"
            "  Put images under the library folder and run this again."
        )

    print(f"  {len(posts)} fits")

    print("Reacting ...")
    # **Uneven on purpose.** People react most to their own scene, which
    # is what gives the ranking something to find; and a handful of fits
    # get far more than the rest, so the board has a clear top.
    by_scene: dict[str, list[User]] = {}
    for name, handle, scene in PEOPLE:
        by_scene.setdefault(scene, []).append(users[handle])

    reactions = saves = 0
    for post, scene in posts:
        same = [u for u in by_scene[scene] if u.id != post.user_id]
        others = [users[h] for _, h, s in PEOPLE if s != scene and users[h].id != post.user_id]
        # A long tail: most fits get a few, some get a crowd.
        appeal = rng.random()
        want = 0 if appeal < 0.15 else rng.randint(1, 4) if appeal < 0.8 else rng.randint(8, 16)

        pool = same + rng.sample(others, min(len(others), 8))
        for fan in rng.sample(pool, min(want, len(pool))):
            db.add(PostReaction(user_id=fan.id, post_id=post.id, kind=rng.choice(REACTIONS)))
            reactions += 1
            # Saving is rarer than reacting: it costs the person a place
            # in their own library, so it is a stronger signal.
            if rng.random() < 0.35:
                db.add(PostSave(user_id=fan.id, post_id=post.id))
                saves += 1
    await db.commit()
    print(f"  {reactions} reactions, {saves} saves")

    print("Curating boards ...")
    # **Pins come from the whole feed, not from the person's own
    # posts.** A board of your own photographs is a portfolio; a board
    # of other people's is what a recommender can learn from, because
    # it is the only place somebody states that two pins by two
    # strangers belong together.
    by_scene_posts: dict[str, list[Post]] = {}
    for post, scene in posts:
        by_scene_posts.setdefault(scene, []).append(post)

    boards_made = pins_made = 0
    for name, handle, scene in PEOPLE:
        me = users[handle]
        titles = BOARD_NAMES.get(scene, ["saved"])
        for title in rng.sample(titles, min(len(titles), rng.randint(2, len(titles)))):
            board = Moodboard(
                user_id=me.id,
                name=title,
                note=None,
            )
            db.add(board)
            await db.flush()
            boards_made += 1

            # Mostly this person's scene, with a real minority from an
            # adjacent one. The minority is the point: it is the edge
            # a walk crosses to find something the tag index cannot.
            home = [p for p in by_scene_posts.get(scene, []) if p.user_id != me.id]
            near_scenes = NEAR.get(scene, [])
            nearby = [
                p for sc in near_scenes for p in by_scene_posts.get(sc, []) if p.user_id != me.id
            ]
            want_home = rng.randint(4, 9)
            want_near = rng.randint(1, 4)
            chosen = rng.sample(home, min(want_home, len(home))) + rng.sample(
                nearby, min(want_near, len(nearby))
            )
            for position, pinned in enumerate(chosen):
                db.add(
                    MoodboardPin(
                        moodboard_id=board.id,
                        post_id=pinned.id,
                        position=position,
                    )
                )
                pins_made += 1
    await db.commit()
    print(f"  {boards_made} boards, {pins_made} pins")

    print("Following ...")
    follows = 0
    ids = [users[h].id for _, h, _ in PEOPLE]
    for name, handle, scene in PEOPLE:
        me = users[handle]
        # Mostly within your own scene, some outside it: a graph where
        # everybody follows everybody demonstrates nothing.
        peers = [u.id for u in by_scene[scene] if u.id != me.id]
        outside = [i for i in ids if i != me.id and i not in peers]
        targets = rng.sample(peers, min(len(peers), rng.randint(2, 4))) + rng.sample(
            outside, min(len(outside), rng.randint(1, 5))
        )
        for target in set(targets):
            db.add(Follow(follower_id=me.id, followee_id=target))
            follows += 1
    await db.commit()
    print(f"  {follows} follows")

    if join:
        mine = await db.scalar(sa.select(User).where(User.email == join))
        if mine is None:
            print(f"  no account for {join} — sign in on the device first")
        else:
            # Follow a spread, and have a spread follow back, so the
            # Community tab is populated from the first screen.
            existing = set(
                await db.scalars(sa.select(Follow.followee_id).where(Follow.follower_id == mine.id))
            )
            picked = rng.sample(ids, min(10, len(ids)))
            for target in picked:
                if target not in existing:
                    db.add(Follow(follower_id=mine.id, followee_id=target))
            back = set(
                await db.scalars(sa.select(Follow.follower_id).where(Follow.followee_id == mine.id))
            )
            for source in rng.sample(ids, min(14, len(ids))):
                if source not in back:
                    db.add(Follow(follower_id=source, followee_id=mine.id))
            await db.commit()
            print(f"  {join}: following 10, followed by 14")

    print()
    print("Done. Discover is now this app's own content.")
    print("Undo with:  python scripts/seed_demo_world.py --remove")
    return 0


async def main() -> int:
    join, remove = _args()
    settings = get_settings()
    engine = build_engine(settings.database_url)
    maker = session_factory(engine)
    async with maker() as db:
        return await (_remove(db) if remove else _seed(db, join))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
