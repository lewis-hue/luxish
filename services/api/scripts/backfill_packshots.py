"""Queue a catalogue shot for wardrobe garments that never got one.

The packshot step runs when a garment is added, so every garment
added before it existed still shows whatever background removal
managed - which on a dark garment photographed on a dark surface is
a silhouette, and on a phone photo of a tee on a sofa is a tee on a
sofa. That is the state a reviewer's wardrobe is in.

    python scripts/backfill_packshots.py --dry-run
    python scripts/backfill_packshots.py
    python scripts/backfill_packshots.py --user someone@example.com

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
        "--limit", type=int, default=500, help="most garments to queue"
    )
    args = parser.parse_args()

    from app.domain.jobs import enqueue
    from app.models.garment import Garment
    from app.models.media_asset import MediaAsset
    from app.models.user import User
    from app.workers.packshot import PACKSHOT_JOB_KIND, PACKSHOT_MEDIA_KIND

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
                    sa.or_(
                        shot.id.is_(None),
                        shot.kind != PACKSHOT_MEDIA_KIND,
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
            print(f"{len(garments)} garment(s) without a packshot")
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
                await enqueue(
                    db,
                    PACKSHOT_JOB_KIND,
                    {
                        "garment_id": str(garment.id),
                        "asset_id": str(garment.media_asset_id),
                        "asset_version": asset.version,
                        "user_id": str(garment.user_id),
                    },
                    # The intake pipeline's own key. A garment whose
                    # shot is already queued is not queued twice, and
                    # neither is one this script has already seen.
                    idempotency_key=f"{PACKSHOT_JOB_KIND}:{garment.id}",
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
