"""Queue a catalogue shot for wardrobe garments that never got one.

The packshot step runs when a garment is added, so every garment
added before it existed still shows whatever background removal
managed - which on a dark garment photographed on a dark surface is
a silhouette, and on a phone photo of a tee on a sofa is a tee on a
sofa. That is the state a reviewer's wardrobe is in.

    python scripts/backfill_packshots.py --dry-run
    python scripts/backfill_packshots.py
    python scripts/backfill_packshots.py --user someone@example.com
    python scripts/backfill_packshots.py --redo

**`--redo` is for a specific past mistake.** For one release the
fan-out sent each piece's own cut-out as the packshot's source, so
the model re-staged a pixelated silhouette: a pair of headphones
came back as a speckled stone blob. Those garments look done - they
have a packshot - and the picture is wrong. `--redo` finds them by
the one marker there is, a source key containing `/piece/`, and
draws them again from the photograph. It costs a generation each,
so it is opt-in.

**It adopts before it buys.** The fan-out path used to ask the
Studio for each piece's packshot and then never point the garment at
the result - measured on a real account as nine ready packshots and
zero garments showing one. Those pictures exist and are paid for, so
this claims them first and only queues a drawing for what is left.

**It queues; it does not draw.** Each shot is a billed image edit on
a worker, so this writes job rows and returns. The idempotency key is
the garment's, the same one the intake pipeline uses, so a garment
that already has a job queued or a packshot stored is skipped and
running this twice costs nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LUXISH_ENVIRONMENT", "local")

import sqlalchemy as sa  # noqa: E402  (after the path insert, deliberately)
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="count, change nothing"
    )
    parser.add_argument("--user", help="one account's email, instead of all")
    parser.add_argument(
        "--redo",
        action="store_true",
        help=(
            "re-draw garments whose packshot was made from a piece cut-out "
            "rather than from the photograph. Costs a generation each."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=500, help="most garments to queue"
    )
    args = parser.parse_args()

    from app.domain.jobs import enqueue
    from app.models.garment import Garment
    from app.models.garment_studio import GarmentShot
    from app.models.media_asset import MediaAsset
    from app.models.user import User
    from app.workers.packshot import ALREADY_A_PACKSHOT, PACKSHOT_JOB_KIND

    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    queued = skipped = 0
    try:
        async with maker() as db:
            # A garment is a candidate when it has a photograph and
            # its current picture is not already a packshot. The
            # outer join is how "has no derived picture at all" and
            # "has a plain cut-out" come back together: both want a
            # shot, and only a stored packshot does not.
            shot = sa.orm.aliased(MediaAsset)
            query = (
                sa.select(Garment)
                .outerjoin(shot, shot.id == Garment.background_removed_asset_id)
                .where(
                    Garment.deleted_at.is_(None),
                    Garment.media_asset_id.is_not(None),
                    sa.true()
                    if args.redo
                    else sa.or_(
                        shot.id.is_(None),
                        shot.kind.not_in(ALREADY_A_PACKSHOT),
                    ),
                )
                .order_by(Garment.created_at.desc())
                .limit(args.limit)
            )
            if args.user:
                owner = await db.scalar(
                    sa.select(User.id).where(User.email == args.user)
                )
                if owner is None:
                    print(f"no account for {args.user}")
                    return 2
                query = query.where(Garment.user_id == owner)

            garments = list((await db.scalars(query)).all())
            if args.redo:
                # The marker, and the only one: a packshot drawn from
                # the photograph has no record of what it was drawn
                # from, but the garment still points at the cut-out
                # that was wrongly used as the source.
                kept = []
                for g in garments:
                    src = await db.get(MediaAsset, g.media_asset_id)
                    if src is not None and "/piece/" in (src.storage_key or ""):
                        kept.append(g)
                garments = kept
                print(f"{len(garments)} garment(s) drawn from a cut-out")
            else:
                print(f"{len(garments)} garment(s) without a packshot")

            # Claim the ones already drawn, before buying any.
            adopted = 0
            if not args.dry_run and not args.redo:
                for garment in garments:
                    shot = await db.scalar(
                        sa.select(GarmentShot)
                        .where(
                            GarmentShot.garment_id == garment.id,
                            GarmentShot.treatment == "packshot",
                            GarmentShot.state == "ready",
                            GarmentShot.media_asset_id.is_not(None),
                            GarmentShot.deleted_at.is_(None),
                        )
                        .order_by(GarmentShot.created_at.desc())
                    )
                    if shot is None:
                        continue
                    garment.background_removed_asset_id = shot.media_asset_id
                    # An edit of their own photograph, so not a render.
                    garment.image_is_rendered = False
                    adopted += 1
                if adopted:
                    await db.commit()
                    print(f"adopted {adopted} packshot(s) already drawn")
                # A garment that just adopted one is done; drawing
                # it again would buy a picture it already has.
                still_wanting = []
                for g in garments:
                    if g.background_removed_asset_id is None:
                        still_wanting.append(g)
                        continue
                    have = await db.get(
                        MediaAsset, g.background_removed_asset_id
                    )
                    if have is None or have.kind not in ALREADY_A_PACKSHOT:
                        still_wanting.append(g)
                garments = still_wanting
            if args.dry_run:
                for one in garments[:20]:
                    print(f"  {one.name or '(unnamed)'}")
                if len(garments) > 20:
                    print(f"  ... and {len(garments) - 20} more")
                print("\nNothing written.")
                return 0

            for garment in garments:
                asset = await db.get(MediaAsset, garment.media_asset_id)
                if asset is None:
                    skipped += 1
                    continue

                # **The original photograph, never a piece cut-out.**
                #
                # A garment split out of a worn photograph points
                # `media_asset_id` at its own cut-out - the documented
                # workaround for the one-garment-per-upload index -
                # and re-staging one of those produced a speckled
                # blob where a pair of headphones should have been.
                #
                # The cut-out's storage key carries its parent: the
                # worker writes `{source key}/piece/{hex}.png`, so
                # the photograph is recoverable from the prefix. A
                # string prefix is a weak join and it is the only one
                # there is; a piece whose parent has gone is skipped
                # rather than shot from itself.
                subject: str | None = None
                key = asset.storage_key or ""
                if "/piece/" in key:
                    parent_key = key.split("/piece/", 1)[0]
                    parent = await db.scalar(
                        sa.select(MediaAsset).where(
                            MediaAsset.storage_key == parent_key,
                            MediaAsset.deleted_at.is_(None),
                        )
                    )
                    if parent is None:
                        skipped += 1
                        continue
                    asset = parent
                    # The photograph holds every piece, so the job has
                    # to say which one it is for.
                    subject = garment.name or "the garment"

                await enqueue(
                    db,
                    PACKSHOT_JOB_KIND,
                    {
                        "garment_id": str(garment.id),
                        "asset_id": str(asset.id),
                        "asset_version": asset.version,
                        "user_id": str(garment.user_id),
                        **({"subject": subject} if subject else {}),
                    },
                    # The intake pipeline's own key. A garment whose
                    # shot is already queued is not queued twice, and
                    # neither is one this script has already seen.
                    # `--redo` needs a fresh key, or the original
                    # job's key makes the re-queue a no-op.
                    idempotency_key=(
                        f"{PACKSHOT_JOB_KIND}:redo:{garment.id}"
                        if args.redo
                        else f"{PACKSHOT_JOB_KIND}:{garment.id}"
                    ),
                )
                queued += 1
            await db.commit()

        print(f"\nqueued {queued}, skipped {skipped}")
        print("The workers draw them. Watch with: docker logs -f luxish-worker-ai")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
