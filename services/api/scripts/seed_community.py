"""Seed sample accounts so the community tab has something to show.

**These are obviously fake and must stay obviously fake.** Every seeded
account's email ends in ``@sample.luxish.invalid`` — `.invalid` is reserved
by RFC 2606 and can never be registered, so none of these can collide with a
real address or be mistaken for one in a support query. The repo's standing
rule is that a fixture must never read as a live integration, and a social
tab populated with plausible strangers is the easiest place in the product
to break it.

They exist because the community tab is unfalsifiable with one account: a
follow graph with one node, a feed of your own saves and a cohort of one
person all look identical whether the code works or not.

    python scripts/seed_community.py                      # create or refresh
    python scripts/seed_community.py --join you@mail.com  # ...and join a cohort
    python scripts/seed_community.py --remove             # take them out again

Idempotent. Re-running updates the same accounts rather than adding more.
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Run as a script from anywhere, the way the other scripts in this folder do.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import build_engine, session_factory  # noqa: E402
from app.models.consent import Consent  # noqa: E402
from app.models.follow import Follow  # noqa: E402
from app.models.media_asset import MediaAsset  # noqa: E402
from app.models.posts import Post, PostMedia, PostSave  # noqa: E402
from app.models.profile import PostTag  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_cohort import UserCohort  # noqa: E402
from app.storage.local import build_local_store  # noqa: E402

# The photograph library and the re-encode, shared with the seeder that owns
# them. Duplicating either would mean two ways of deciding where the pictures
# are, which is one more than anybody can keep in step.
from scripts.seed_demo_world import (  # noqa: E402
    photo_root,
    photos_by_folder,
    store_photo,
)

#: Reserved by RFC 2606: never resolvable, never registrable.
DOMAIN = "sample.luxish.invalid"

#: Deterministic, so a re-run produces the same people rather than a new
#: cast every time somebody looks at the tab.
SEED = 20261030

#: Cast across regions and in the age band this app is for, matching the
#: casting rules the imagery follows.
#:
#: **Grouped into four cohorts of three, on purpose.** The first version of
#: this table varied `size_band` within each wardrobe style, which looked
#: like a realistic spread and gave almost everybody a cohort of one — so
#: `style_twins` correctly returned nothing and the suggestions section was
#: untestable. A cohort key is `owns|dress|size`, so all three parts have to
#: match for two people to be twins. Keep three people per key.
PEOPLE: list[tuple[str, str, str, str]] = [
    # (first name, cohort owns_key, dress_code, size_band)
    ("Amara", "outerwear-heavy", "casual", "m"),
    ("Zara", "outerwear-heavy", "casual", "m"),
    ("Tunde", "outerwear-heavy", "casual", "m"),
    ("Mei", "tailoring-led", "smart_casual", "s"),
    ("Keiko", "tailoring-led", "smart_casual", "s"),
    ("Jonas", "tailoring-led", "smart_casual", "s"),
    ("Priya", "denim-led", "casual", "l"),
    ("Sofia", "denim-led", "casual", "l"),
    ("Ines", "denim-led", "casual", "l"),
    ("Noor", "athleisure-led", "casual", "m"),
    ("Mateo", "athleisure-led", "casual", "m"),
    ("Dami", "athleisure-led", "casual", "m"),
]


#: The narrow pool the sample accounts all tag their fits with.
#:
#: Narrow on purpose: Discover groups by hashtag, and twelve accounts
#: spread over thirty-five tags leaves every group with one fit in it,
#: which is not a group. Chosen as the aesthetics this audience actually
#: shares rather than at random.
TAGS = [
    "streetwear",
    "y2k",
    "clean-girl",
    "dark-academia",
    "smart-casual",
    "balletcore",
    "elevated-basics",
    "monochrome",
    "denim",
    "skater",
]


def _cohort_key(owns: str, dress: str, size: str) -> str:
    """The same shape `app.domain.cohort` builds, so these group with real users."""
    return f"{owns}|{dress}|{size}"


def _join_target() -> str | None:
    """``--join <email>`` puts a real account into a sample cohort."""
    if "--join" not in sys.argv:
        return None
    index = sys.argv.index("--join")
    return sys.argv[index + 1] if index + 1 < len(sys.argv) else None


async def main() -> int:
    remove = "--remove" in sys.argv
    join = _join_target()
    settings = get_settings()
    engine = build_engine(settings.database_url)
    maker = session_factory(engine)

    # Where the photographs are, resolved once. Empty is a real answer on a
    # clone with no library: the run then says so rather than writing fits
    # with nothing to show.
    root = photo_root()
    library = photos_by_folder(root) if root and root.exists() else {}
    store = (
        build_local_store(environment=settings.environment, root=settings.local_media_root)
        if library
        else None
    )

    async with maker() as db:
        if remove:
            emails = [f"{name.lower()}@{DOMAIN}" for name, *_ in PEOPLE]
            ids = list(await db.scalars(sa.select(User.id).where(User.email.in_(emails))))
            if not ids:
                print("No sample accounts to remove.")
                return 0
            # Follows and saves cascade from the user rows; cohorts do not
            # declare a cascade, so they are cleared explicitly.
            await db.execute(sa.delete(Consent).where(Consent.user_id.in_(ids)))
            await db.execute(sa.delete(UserCohort).where(UserCohort.user_id.in_(ids)))
            await db.execute(sa.delete(Post).where(Post.user_id.in_(ids)))
            await db.execute(
                sa.delete(Follow).where(
                    sa.or_(Follow.follower_id.in_(ids), Follow.followee_id.in_(ids))
                )
            )
            await db.execute(sa.delete(User).where(User.id.in_(ids)))
            await db.commit()
            print(f"Removed {len(ids)} sample accounts.")
            return 0

        rng = random.Random(SEED)
        now = datetime.now(timezone.utc)
        created: list[User] = []

        for name, owns, dress, size in PEOPLE:
            email = f"{name.lower()}@{DOMAIN}"
            user = await db.scalar(sa.select(User).where(User.email == email))
            if user is None:
                user = User(email=email, email_verified=True, display_name=name)
                db.add(user)
                await db.flush()
            else:
                user.display_name = name
            created.append(user)

            cohort = await db.scalar(sa.select(UserCohort).where(UserCohort.user_id == user.id))
            key = _cohort_key(owns, dress, size)
            if cohort is None:
                db.add(
                    UserCohort(
                        user_id=user.id,
                        cohort_key=key,
                        owns_key=owns,
                        dress_code=dress,
                        size_band=size,
                        signature={"seeded": True},
                        # Not nullable: the recompute job stamps when a
                        # cohort was last worked out, and the scheduled
                        # refresh reads it to decide what is stale.
                        computed_at=now,
                    )
                )
            else:
                cohort.cohort_key = key
                cohort.owns_key = owns
                cohort.dress_code = dress
                cohort.size_band = size
                cohort.computed_at = now

            # **Each sample account opts in to being seen.** The feed reads
            # only from accounts holding a live `community_sharing` consent,
            # because following needs no approval and a save is private
            # until its owner says otherwise. Without this the seeded feed
            # would be empty and the feature would look broken rather than
            # private — which is the failure mode a fixture exists to rule
            # out. Real accounts are untouched and default to off.
            consent = await db.scalar(
                sa.select(Consent).where(
                    Consent.user_id == user.id,
                    Consent.kind == "community_sharing",
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

        await db.flush()

        # One fit each, with a caption written here, in this file, by us.
        # `screen_mode="seed"` is stamped on every row because these never
        # met the screen; a fixture that could pass for screened content
        # would break the capability-label rule.
        #
        # This is the whole population Discover ranks now. The fixture used
        # to write saved looks and taps against a catalogue as well, for
        # shelves that measured content nobody could open.
        CAPTION_POOL = {
            "outerwear-heavy": [
                "Layered for the matatu commute.",
                "Shell over knit over tee. Cold morning, warm bus.",
                "Third winter in this coat and it has not given up.",
                None,
            ],
            "tailoring-led": [
                "Same blazer, third way this week.",
                "Trousers finally taken in. Worth the wait.",
                "No tie. Nobody has said anything.",
                None,
            ],
            "denim-led": [
                "Broke in the straight legs properly.",
                "Double denim, one shade apart. It works.",
                "These were my sister's.",
                None,
            ],
            "athleisure-led": [
                "Track jacket does office hours now.",
                "Ran for the bus in these and regretted nothing.",
                "Gym to lunch without going home.",
                None,
            ],
        }
        post_ids = [user.id for user in created]
        # The old assets go with the old posts, or every re-run leaves
        # another dozen orphaned rows in the media table.
        old_posts = list(await db.scalars(sa.select(Post.id).where(Post.user_id.in_(post_ids))))
        if old_posts:
            await db.execute(sa.delete(PostMedia).where(PostMedia.post_id.in_(old_posts)))
        await db.execute(sa.delete(Post).where(Post.user_id.in_(post_ids)))
        await db.execute(
            sa.delete(MediaAsset).where(
                MediaAsset.user_id.in_(post_ids),
                MediaAsset.kind == "outfit_photo",
            )
        )

        # **A fit is a photograph.** These used to post a caption and a
        # catalogue reference, and the card drew the catalogue's artwork;
        # without it those rows are empty frames on Discover. The pictures
        # come from the same library `seed_demo_world.py` reads.
        deck = [path for paths in library.values() for path in paths]
        rng.shuffle(deck)
        # One each when the library is small, so no two accounts post the
        # same picture - two people posting one photograph is the thing
        # that makes a seeded feed obviously seeded. More each when there
        # is enough to go round.
        each = 1 if not deck else max(1, min(4, len(deck) // len(PEOPLE)))
        dealt = 0

        posts: list[tuple[Post, list[str], datetime]] = []
        for user, (name, owns, dress, size) in zip(created, PEOPLE):
            # Spread over the fortnight the feed looks back over, so the
            # ordering is not twelve rows with the same timestamp.
            for _ in range(each):
                if dealt >= len(deck):
                    break
                asset = await store_photo(db, store, user_id=user.id, path=deck[dealt])
                dealt += 1
                if asset is None:
                    continue
                when = now - timedelta(hours=rng.randint(1, 13 * 24))
                tags = rng.sample(TAGS, rng.randint(1, 2))
                written = rng.choice(CAPTION_POOL.get(owns, [None]))
                post = Post(
                    user_id=user.id,
                    # The hashtags go in the caption as well as the table:
                    # that is where an author would have typed them, and a
                    # fit whose tags only exist in the index reads as
                    # tagged by somebody else.
                    caption=" ".join(
                        part for part in (written, *(f"#{tag}" for tag in tags)) if part
                    ),
                    state="published",
                    screen_mode="seed",
                    published_at=when,
                )
                db.add(post)
                await db.flush()
                db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
                posts.append((post, tags, when))

        # The tags, once the posts have ids. Denormalised onto their own
        # rows because that is the join Discover groups by.
        for post, tags, when in posts:
            for tag in tags:
                db.add(PostTag(post_id=post.id, tag=tag, created_at=when))

        # Saves between them, so the figure on a card rests on something.
        # Nobody keeps their own fit: a self-save would inflate every count
        # by one and mean nothing.
        await db.execute(sa.delete(PostSave).where(PostSave.user_id.in_(post_ids)))
        for post, _tags, _when in posts:
            others = [uid for uid in post_ids if uid != post.user_id]
            for saver in rng.sample(others, rng.randint(0, min(6, len(others)))):
                db.add(PostSave(user_id=saver, post_id=post.id))
        if not deck:
            print(
                "  posts: none - no photograph library found, and a fit with no\n"
                "         photograph renders as an empty tile. Point at one with\n"
                "         --photos <dir> or LUXISH_PHOTO_LIBRARY, or run\n"
                "         seed_demo_world.py, then run this again."
            )
        else:
            print(f"  posts: {len(posts)} published with photographs, with saves between them")

        # A follow graph among themselves, so follower counts are not all
        # zero before a real person touches anything.
        ids = [user.id for user in created]
        await db.execute(
            sa.delete(Follow).where(
                sa.and_(Follow.follower_id.in_(ids), Follow.followee_id.in_(ids))
            )
        )
        for user in created:
            others = [other for other in ids if other != user.id]
            for target in rng.sample(others, rng.randint(2, 5)):
                db.add(Follow(follower_id=user.id, followee_id=target))

        # Optionally drop a real account into one of these cohorts, so the
        # suggestions section can be seen now rather than after the next
        # twice-weekly recompute. Does not touch their wardrobe or saves.

        # The inbox is derived rather than stored: it reads wardrobe jobs,
        # stylist runs and saves. The one kind the sample accounts can
        # produce is `fit_reactions`, which fires when enough *other*
        # people keep a fit the reader has kept - so they are pointed at
        # the join target's own saves rather than at anything of their
        # own, or the inbox stays empty however much activity there is.
        if join:
            reader = await db.scalar(sa.select(User).where(User.email == join))
            if reader is not None:
                kept = list(
                    await db.scalars(
                        sa.select(PostSave.post_id).where(PostSave.user_id == reader.id)
                    )
                )
                if not kept:
                    print("  inbox: nothing kept to react to yet")
                else:
                    ids = [user.id for user in created]
                    chosen = rng.sample(kept, min(3, len(kept)))
                    for post_id in chosen:
                        # Comfortably over the distinct-people floor the
                        # inbox enforces. Keeping a fit is a pair primary
                        # key, so whoever already keeps it is skipped
                        # rather than inserted twice.
                        already = set(
                            await db.scalars(
                                sa.select(PostSave.user_id).where(PostSave.post_id == post_id)
                            )
                        )
                        for actor in rng.sample(ids, min(5, len(ids))):
                            if actor in already:
                                continue
                            db.add(
                                PostSave(
                                    user_id=actor,
                                    post_id=post_id,
                                    created_at=now - timedelta(hours=rng.randint(1, 6 * 24)),
                                )
                            )
                    print(
                        f"  inbox: {len(chosen)} of the fits you kept now have "
                        "keeps from several people"
                    )

        if join:
            mine = await db.scalar(sa.select(User).where(User.email == join))
            if mine is None:
                print(f"No account for {join}. Sign in on the device first.")
            else:
                name, owns, dress, size = PEOPLE[0]
                key = _cohort_key(owns, dress, size)
                existing = await db.scalar(
                    sa.select(UserCohort).where(UserCohort.user_id == mine.id)
                )
                if existing is None:
                    db.add(
                        UserCohort(
                            user_id=mine.id,
                            cohort_key=key,
                            owns_key=owns,
                            dress_code=dress,
                            size_band=size,
                            signature={"seeded_join": True},
                            computed_at=now,
                        )
                    )
                else:
                    existing.cohort_key = key
                    existing.owns_key = owns
                    existing.dress_code = dress
                    existing.size_band = size
                    existing.computed_at = now
                print(f"Put {join} in cohort {key}, alongside 3 sample accounts.")

        await db.commit()
        print(f"Seeded {len(created)} sample accounts at @{DOMAIN}.")
        print("Cohorts:", ", ".join(sorted({_cohort_key(o, d, s) for _, o, d, s in PEOPLE})))
        if not join:
            print()
            print("Suggestions are cohort-based, so these appear only once your own")
            print("wardrobe lands in one of those cohorts. To skip that wait:")
            print("  python scripts/seed_community.py --join <your email>")
        print("Remove them with: python scripts/seed_community.py --remove")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
