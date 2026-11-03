"""Fill one real account with demo data, so every screen has something on it.

`seed_community.py` populates the *other* side of the community tab — twelve
sample strangers to follow and be followed by. This fills your own side: a
wardrobe with photographs in it, a capsule, a shelf of fits kept from other
people, boards holding those fits, a week of plans made of their own clothes,
and a finished stylist outfit. Without it a freshly signed-in account meets
eight empty states, which demonstrates the empty states and nothing else.

**The shelf and the boards need fits to exist.** Both are filled from what
is already published, so run `seed_demo_world.py` first if Discover is
empty; this says what it found rather than writing rows no screen can draw.

    python scripts/seed_demo.py --email you@example.com
    python scripts/seed_demo.py --email you@example.com --remove

**Sign in on the device first.** This refuses to create the account, and the
refusal is the point: provisioning links a Keycloak subject to a user row the
first time a token arrives, and a row that already carries your address makes
that first sign-in raise `IdentityLinkRequired` instead of letting you in. A
seeder that locks you out of the app it is seeding is worse than no seeder.

**Everything it writes, it can take back.** The ids go into one preference
row (:data:`MANIFEST_KEY`), and `--remove` reads that row rather than guessing
from names or timestamps, so it can never delete a garment you added
yourself.

**Local only, and it will not run anywhere else.** It writes image bytes
through the filesystem media store, which refuses outside the local
environment, and the photographs it writes are the app's own bundled sample
wardrobe — stock pictures of clothes, not anybody's possessions.

**It calls no model.** Categorisation and segmentation are real, billed, and
already proven by `e2e_wardrobe_pipeline.py`. Here every attribute is written
as `confirmed_attributes`, which is what a user who corrected the sorter would
have produced, and `inferred_attributes` carries `{"seeded": true}` so nothing
downstream mistakes a fixture for a model's opinion.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402

import app.models  # noqa: E402, F401  (registers every table on Base.metadata)
from app.config import get_settings  # noqa: E402
from app.db.session import build_engine, session_factory  # noqa: E402
from app.models.consent import Consent  # noqa: E402
from app.models.follow import Follow  # noqa: E402
from app.models.garment import Collection, CollectionGarment, Garment  # noqa: E402
from app.models.media_asset import MediaAsset  # noqa: E402
from app.models.moodboard import Moodboard, MoodboardPin  # noqa: E402
from app.models.outfit_plan import OutfitPlan, OutfitPlanItem  # noqa: E402
from app.models.posts import Post, PostMedia, PostSave  # noqa: E402
from app.models.preference import Preference  # noqa: E402
from app.models.stylist import (  # noqa: E402
    Conversation,
    Message,
    Outfit,
    OutfitItem,
    StylistRun,
)
from app.models.user import User  # noqa: E402
from app.storage.local import build_local_store  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
WARDROBE_IMAGES = REPO / "apps" / "mobile" / "assets" / "images" / "wardrobe"

#: Where the list of everything this wrote is kept, so `--remove` is exact.
MANIFEST_KEY = "demo_seed"

#: Deterministic, so a re-run produces the same wardrobe rather than a new one.
SEED = 20261030

#: The app's own `features/wardrobe/sample.ts`, which was written to mirror the
#: `Garment` model exactly so these records could be posted as real garments
#: "with no translation layer". This is that promise being collected on — the
#: names, categories and attributes are the same table, so what a reviewer
#: sees here is what the sample-wardrobe demo shows.
#:
#: (file stem, name, category, colour, formality, seasons, material)
GARMENTS: list[tuple[str, str, str, str, str, tuple[str, ...], str | None]] = [
    ("white-shirt", "White poplin shirt", "shirt", "white", "business", ("all_year",), "cotton"),
    ("navy-blazer", "Navy wool blazer", "blazer", "navy", "business", ("cool", "transitional"), "wool"),
    ("cream-trousers", "Cream wide-leg trousers", "trousers", "cream", "smart_casual", ("warm", "transitional"), None),
    ("indigo-jeans", "Indigo straight jeans", "jeans", "indigo", "casual", ("all_year",), "denim"),
    ("black-midi-dress", "Black crepe midi dress", "dress", "black", "formal", ("all_year",), None),
    ("brown-loafers", "Brown penny loafers", "shoes", "brown", "smart_casual", ("all_year",), "leather"),
    ("white-trainers", "White leather trainers", "shoes", "white", "casual", ("all_year",), None),
    ("camel-coat", "Camel wool overcoat", "coat", "camel", "smart_casual", ("cool",), "wool"),
    ("linen-shirt", "Sand linen shirt", "shirt", "sand", "casual", ("warm",), "linen"),
    ("striped-knit", "Striped fine knit", "knitwear", "navy", "casual", ("cool", "transitional"), None),
    ("leather-tote", "Tan leather tote", "bag", "tan", "business", ("all_year",), "leather"),
    ("silk-scarf", "Ochre silk scarf", "accessory", "ochre", "smart_casual", ("all_year",), "silk"),
]

#: One garment is in the wash, matching the sample wardrobe. The stylist has
#: to route around it, which is the only way to see that it does.
IN_LAUNDRY = "white-trainers"

#: And one carries a weak inference, so the correction flow has something to
#: correct and the detail sheet can show inferred against confirmed.
WEAK_INFERENCE = "striped-knit"

FAVOURITES = {"camel-coat", "indigo-jeans", "leather-tote"}

#: Collection ids from `apps/mobile/src/features/discover/collections.ts`. A
#: save pointing anywhere else is a row that opens onto nothing.
#: Boards and their notes, named the way somebody names a board rather
#: than the way a fixture generator does.
#:
#: What goes on each is not listed here any more. A board holds published
#: fits, and which fits exist depends on what has been seeded, so they are
#: dealt out from the database at run time.
BOARDS: list[tuple[str, str | None]] = [
    ("Back to the office", "Things I would actually wear on a Tuesday"),
    ("Weekend", "Nothing that needs ironing"),
    ("Winter", None),
]

#: A week ahead, plus a few days behind so the planner has history and the
#: "did you wear it" state has something to show.
#: Days from today, and the note. The clothes come from the wardrobe
#: this seeder creates, because that is what a plan holds.
PLANS: list[tuple[int, str | None]] = [
    (-6, "Long day, kept it simple"),
    (-4, None),
    (-2, "Wore the loafers"),
    (0, None),
    (1, "Review meeting"),
    (2, None),
    (3, "Dinner with the in-laws"),
    (5, None),
    (6, "Flight at six"),
]

def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="the account to fill")
    parser.add_argument(
        "--remove", action="store_true", help="take back everything this wrote"
    )
    return parser.parse_args()


async def _manifest(db, user_id: uuid.UUID) -> Preference | None:
    return await db.scalar(
        sa.select(Preference).where(
            Preference.user_id == user_id, Preference.key == MANIFEST_KEY
        )
    )


async def _remove(db, user: User) -> int:
    """Undo a previous run, using the manifest rather than guesswork."""
    row = await _manifest(db, user.id)
    if row is None:
        print("Nothing seeded for this account.")
        return 0

    kept = row.value or {}
    ids = {name: [uuid.UUID(i) for i in kept.get(name, [])] for name in (
        "garments", "assets", "collections", "boards", "plans",
        "conversations", "outfits",
    )}
    removed = sum(len(v) for v in ids.values())

    # Children first: outfit items and pins reference rows about to go, and
    # a garment cannot be deleted while an outfit item still points at it
    # with `SET NULL` deferred to the database.
    await db.execute(sa.delete(OutfitItem).where(OutfitItem.outfit_id.in_(ids["outfits"] or [uuid.uuid4()])))
    await db.execute(sa.delete(Outfit).where(Outfit.id.in_(ids["outfits"] or [uuid.uuid4()])))
    await db.execute(sa.delete(Message).where(Message.conversation_id.in_(ids["conversations"] or [uuid.uuid4()])))
    await db.execute(sa.delete(StylistRun).where(StylistRun.conversation_id.in_(ids["conversations"] or [uuid.uuid4()])))
    await db.execute(sa.delete(Conversation).where(Conversation.id.in_(ids["conversations"] or [uuid.uuid4()])))
    await db.execute(sa.delete(MoodboardPin).where(MoodboardPin.moodboard_id.in_(ids["boards"] or [uuid.uuid4()])))
    await db.execute(sa.delete(Moodboard).where(Moodboard.id.in_(ids["boards"] or [uuid.uuid4()])))
    await db.execute(sa.delete(CollectionGarment).where(CollectionGarment.collection_id.in_(ids["collections"] or [uuid.uuid4()])))
    await db.execute(sa.delete(Collection).where(Collection.id.in_(ids["collections"] or [uuid.uuid4()])))
    await db.execute(sa.delete(OutfitPlan).where(OutfitPlan.id.in_(ids["plans"] or [uuid.uuid4()])))
    # Keeps are a pair, not a row with an id, so they are undone by
    # naming this account rather than by remembering ids.
    await db.execute(sa.delete(PostSave).where(PostSave.user_id == user.id))
    await db.execute(
        sa.delete(OutfitPlanItem).where(
            OutfitPlanItem.plan_id.in_(ids["plans"] or [uuid.uuid4()])
        )
    )
    await db.execute(sa.delete(Garment).where(Garment.id.in_(ids["garments"] or [uuid.uuid4()])))
    await db.execute(sa.delete(MediaAsset).where(MediaAsset.id.in_(ids["assets"] or [uuid.uuid4()])))

    # The follow edges this created, and only those: the sample accounts are
    # identified by their reserved domain, so a real person you followed is
    # never touched.
    sample_ids = list(
        await db.scalars(
            sa.select(User.id).where(User.email.like("%@sample.luxish.invalid"))
        )
    )
    if sample_ids:
        await db.execute(
            sa.delete(Follow).where(
                sa.or_(
                    sa.and_(Follow.follower_id == user.id, Follow.followee_id.in_(sample_ids)),
                    sa.and_(Follow.followee_id == user.id, Follow.follower_id.in_(sample_ids)),
                )
            )
        )

    await db.delete(row)
    await db.commit()
    print(f"Removed {removed} seeded row(s) from {user.email}.")
    print("Left alone: your consents, your cohort, and anything you added yourself.")
    return 0


async def _seed_wardrobe(db, store, user: User, now: datetime, kept: dict) -> list[Garment]:
    """Twelve garments with real stored bytes behind them.

    The asset is written exactly the way `receive_local_upload` writes one —
    same key shape, same checksum, same `byte_size` — because a garment whose
    photograph is reachable by a different route than the app's own would
    prove nothing about the app.
    """
    garments: list[Garment] = []
    for stem, name, category, colour, formality, seasons, material in GARMENTS:
        source = WARDROBE_IMAGES / f"{stem}.webp"
        if not source.exists():
            print(f"  missing image: {source.name}, skipping {name}")
            continue
        body = source.read_bytes()

        asset = MediaAsset(
            user_id=user.id,
            kind="garment_photo",
            # `ready`, not `uploaded`: nothing is going to process this, and
            # `uploaded` would leave the grid showing a permanent spinner on
            # a garment that is in fact finished.
            status="ready",
            content_type="image/webp",
            max_bytes=len(body),
            byte_size=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
            publication_consent=False,
        )
        db.add(asset)
        await db.flush()

        key = f"users/{user.id}/media/{asset.id}"
        await store.write(key, body, content_type="image/webp")
        asset.storage_key = key

        confirmed: dict[str, object] = {
            "colour": colour,
            "formality": formality,
            "seasons": list(seasons),
        }
        if material:
            confirmed["material"] = material

        garment = Garment(
            user_id=user.id,
            media_asset_id=asset.id,
            name=name,
            category=category,
            availability="laundry" if stem == IN_LAUNDRY else "available",
            confirmed_attributes=confirmed,
            # Stamped rather than left empty, so nothing downstream can read
            # a fixture as something a model said about a real photograph.
            inferred_attributes=(
                {"seeded": True, "pattern": "horizontal stripe"}
                if stem == WEAK_INFERENCE
                else {"seeded": True}
            ),
            inference_confidence=0.42 if stem == WEAK_INFERENCE else None,
            inferred_at=now if stem == WEAK_INFERENCE else None,
            is_favourite=stem in FAVOURITES,
        )
        db.add(garment)
        await db.flush()
        garments.append(garment)
        kept["assets"].append(str(asset.id))
        kept["garments"].append(str(garment.id))

    return garments


async def _seed(db, store, user: User) -> int:
    rng = random.Random(SEED)
    now = datetime.now(UTC)
    today = now.date()
    kept: dict[str, list[str]] = {
        name: []
        for name in (
            "garments", "assets", "collections", "boards", "plans",
            "conversations", "outfits",
        )
    }

    # Refuse to stack one seed on another. Two wardrobes of the same twelve
    # shirts is not a better demonstration of anything.
    if await _manifest(db, user.id) is not None:
        print("This account is already seeded. Run with --remove first.")
        return 1

    print(f"Seeding {user.email} ...")

    garments = await _seed_wardrobe(db, store, user, now, kept)
    print(f"  wardrobe: {len(garments)} garments, each with a stored photograph")

    # A capsule, built from the pieces that actually go together rather than
    # from the first six in the list.
    capsule_names = {
        "Navy wool blazer", "White poplin shirt", "Cream wide-leg trousers",
        "Brown penny loafers", "Camel wool overcoat", "Tan leather tote",
    }
    capsule = Collection(
        user_id=user.id,
        name="Autumn capsule",
        description="Six pieces that make a fortnight",
    )
    db.add(capsule)
    await db.flush()
    kept["collections"].append(str(capsule.id))
    for position, garment in enumerate(g for g in garments if g.name in capsule_names):
        db.add(
            CollectionGarment(
                collection_id=capsule.id, garment_id=garment.id, position=position
            )
        )
    print(f"  collection: {capsule.name}")

    # The shelf: other people's fits this account kept.
    #
    # Taken from whatever is already published rather than created here.
    # `seed_demo_world.py` is what puts photographs on the database, so
    # this says what it found instead of writing rows no screen can draw.
    publishable = list(
        await db.scalars(
            sa.select(Post.id)
            .join(PostMedia, PostMedia.post_id == Post.id)
            .where(
                Post.user_id != user.id,
                Post.state == "published",
                Post.deleted_at.is_(None),
            )
            .order_by(Post.published_at.desc())
            .limit(40)
        )
    )
    if not publishable:
        print("  saved: nothing published to keep yet - run seed_demo_world.py")
    else:
        for days, post_id in enumerate(publishable[:11]):
            db.add(
                PostSave(
                    user_id=user.id,
                    post_id=post_id,
                    created_at=now - timedelta(days=days, hours=rng.randint(0, 20)),
                )
            )
        print(f"  saved: {min(11, len(publishable))} fits")

    # Boards, holding the same fits. Dealt out rather than sampled, so one
    # photograph is not on two boards - which is what makes a seeded set of
    # boards look generated.
    deck = list(publishable)
    rng.shuffle(deck)
    at = 0
    for name, note in BOARDS:
        board = Moodboard(user_id=user.id, name=name, note=note)
        db.add(board)
        await db.flush()
        kept["boards"].append(str(board.id))
        for position in range(min(5, max(0, len(deck) - at))):
            db.add(
                MoodboardPin(
                    moodboard_id=board.id, post_id=deck[at], position=position
                )
            )
            at += 1
    print(f"  boards: {len(BOARDS)}" + ("" if deck else " (empty - nothing to pin)"))

    # Plans hold garments out of this wardrobe, which is what a plan is.
    # Three pieces a day, dealt round so the week is not nine copies of the
    # same outfit.
    wearable = [g for g in garments if g.deleted_at is None]
    for index, (offset, note) in enumerate(PLANS):
        plan = OutfitPlan(
            user_id=user.id,
            planned_for=today + timedelta(days=offset),
            note=note,
            # Only the past can have been worn. Left null for the future,
            # which is what "not answered yet" means on that screen.
            worn=(offset < 0) or None,
        )
        db.add(plan)
        await db.flush()
        kept["plans"].append(str(plan.id))
        for position in range(3):
            if not wearable:
                break
            garment = wearable[(index * 3 + position) % len(wearable)]
            db.add(
                OutfitPlanItem(
                    plan_id=plan.id, garment_id=garment.id, position=position
                )
            )
    print(f"  plans: {len(PLANS)} days, three pieces each")

    # One finished stylist turn, so the tab opens on a conversation rather
    # than on a prompt, and the inbox has a `stylist_ready` item.
    #
    # **Marked as seeded in every field that could be mistaken for a model's
    # work.** `provider` and `model` say `seed`, not a vendor and a version,
    # because an audit trail that names a model nobody called is worse than
    # an empty one.
    conversation = Conversation(
        user_id=user.id, title="Something for Thursday", last_run_at=now - timedelta(hours=6)
    )
    db.add(conversation)
    await db.flush()
    kept["conversations"].append(str(conversation.id))
    db.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content="Something for a long day at the office that still works for dinner.",
            position=0,
        )
    )
    run = StylistRun(
        conversation_id=conversation.id,
        user_id=user.id,
        state="completed",
        progress=1.0,
        request_text="Something for a long day at the office that still works for dinner.",
        occasion="office",
        styled_for=today + timedelta(days=1),
        provider="seed",
        model="seed",
        prompt_version="seed",
        started_at=now - timedelta(hours=6, seconds=40),
        finished_at=now - timedelta(hours=6),
        explanation=(
            "Tailoring that is not a suit: the blazer carries the day, the "
            "loafers carry the evening, and nothing here needs changing in "
            "between."
        ),
    )
    db.add(run)
    await db.flush()

    by_name = {garment.name: garment for garment in garments}
    chosen = [
        ("top", "White poplin shirt"),
        ("bottom", "Cream wide-leg trousers"),
        ("outer", "Navy wool blazer"),
        ("shoes", "Brown penny loafers"),
        ("bag", "Tan leather tote"),
    ]
    outfit = Outfit(
        user_id=user.id,
        conversation_id=conversation.id,
        run_id=run.id,
        rationale=run.explanation,
        occasion="office",
        styled_for=run.styled_for,
        missing_slots=[],
        saved=True,
    )
    db.add(outfit)
    await db.flush()
    kept["outfits"].append(str(outfit.id))
    for position, (role, name) in enumerate(chosen):
        garment = by_name.get(name)
        if garment is None:
            continue
        db.add(
            OutfitItem(
                outfit_id=outfit.id,
                garment_id=garment.id,
                role=role,
                owned=True,
                position=position,
            )
        )
    db.add(
        Message(
            conversation_id=conversation.id,
            run_id=run.id,
            role="assistant",
            content=run.explanation,
            position=1,
        )
    )
    print("  stylist: one finished outfit, five owned pieces")

    # Community: opt in, and follow the sample accounts both ways so the
    # feed, the follower count and the suggestions all have something real
    # to read. Consent is written as `seed` so its provenance is visible in
    # the row rather than inferred from the date.
    consent = await db.scalar(
        sa.select(Consent).where(
            Consent.user_id == user.id, Consent.kind == "community_sharing"
        )
    )
    if consent is None:
        db.add(
            Consent(
                user_id=user.id,
                kind="community_sharing",
                granted_at=now,
                source="seed",
            )
        )
    else:
        consent.granted_at = now
        consent.revoked_at = None

    samples = list(
        await db.scalars(
            sa.select(User.id).where(User.email.like("%@sample.luxish.invalid"))
        )
    )
    if not samples:
        print("  community: no sample accounts — run seed_community.py for a feed")
    else:
        existing = set(
            await db.scalars(
                sa.select(Follow.followee_id).where(Follow.follower_id == user.id)
            )
        )
        following = [i for i in rng.sample(samples, min(6, len(samples))) if i not in existing]
        for target in following:
            db.add(Follow(follower_id=user.id, followee_id=target))
        back = set(
            await db.scalars(
                sa.select(Follow.follower_id).where(Follow.followee_id == user.id)
            )
        )
        followers = [i for i in rng.sample(samples, min(8, len(samples))) if i not in back]
        for source_id in followers:
            db.add(Follow(follower_id=source_id, followee_id=user.id))
        print(f"  community: following {len(following)}, followed by {len(followers)}")

    db.add(Preference(user_id=user.id, key=MANIFEST_KEY, value=kept))
    await db.commit()

    print()
    print("Done. Sign in on the device and every tab has something on it.")
    print("Undo with:  python scripts/seed_demo.py --email "
          f"{user.email} --remove")
    return 0


async def main() -> int:
    args = _args()
    settings = get_settings()

    # Refuses outside the local environment, which is the guard that keeps
    # this script from ever touching a deployment.
    store = build_local_store(
        environment=settings.environment, root=settings.local_media_root
    )

    engine = build_engine(settings.database_url)
    maker = session_factory(engine)
    async with maker() as db:
        user = await db.scalar(
            sa.select(User).where(
                sa.func.lower(User.email) == args.email.lower(),
                User.deleted_at.is_(None),
            )
        )
        if user is None:
            print(f"No account for {args.email}.")
            print()
            print("Sign in on the device first, then run this again. This script")
            print("will not create the row: provisioning links your Keycloak")
            print("subject on first sight of a token, and a row already carrying")
            print("your address makes that sign-in fail with a link challenge.")
            return 2

        if args.remove:
            return await _remove(db, user)
        return await _seed(db, store, user)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
