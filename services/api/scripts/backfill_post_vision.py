"""Read every pin's photograph, so the recommender knows what they are of.

    python scripts/backfill_post_vision.py            # everything unread
    python scripts/backfill_post_vision.py --limit 20 # a taste of it
    python scripts/backfill_post_vision.py --force    # re-read everything

**One cheap vision call per pin.** Posts published from now on are
read by the `post.vision` job on publish; this is for everything that
already exists. Pins already read at the current prompt version are
skipped, so running it twice costs nothing and an interrupted run
resumes where it stopped.

Sequential rather than concurrent, deliberately: the vendor's rate
limit is per team, and a burst of four hundred would spend the whole
budget that every other feature shares.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LUXISH_ENVIRONMENT", "local")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.models.post_vision import PostVisionRow
    from app.models.posts import Post
    from app.providers.base import AIRunRecorder
    from app.providers.meta import MetaProvider
    from app.workers.post_vision import (
        POST_VISION_PROMPT_VERSION,
        MetaPostVisionReader,
        read_post_vision,
    )
    from app.workers.runner import build_media_store

    cfg = get_settings()
    engine = create_async_engine(cfg.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    store = build_media_store(cfg)

    class Job:
        def __init__(self, post_id):
            import uuid as _uuid

            self.id = _uuid.uuid4()
            self.payload = {"post_id": str(post_id)}

    async with Session() as db:
        query = sa.select(Post.id).where(
            Post.deleted_at.is_(None), Post.state == "published"
        )
        if not args.force:
            read_already = sa.select(PostVisionRow.post_id).where(
                PostVisionRow.prompt_version == POST_VISION_PROMPT_VERSION
            )
            query = query.where(Post.id.not_in(read_already))
        if args.limit:
            query = query.limit(args.limit)
        todo = list((await db.scalars(query)).all())

    print(f"{len(todo)} pins to read at prompt {POST_VISION_PROMPT_VERSION}")
    if not todo:
        await engine.dispose()
        return 0

    done = failed = 0
    tally: dict[str, int] = {}
    for at, post_id in enumerate(todo, start=1):
        # A session per pin: the provider wants its run recorded
        # against the session that made it, and one long-lived
        # session over four hundred calls holds a transaction open
        # for the whole backfill.
        async with Session() as db:
            provider = MetaProvider(recorder=AIRunRecorder(db))
            reader = MetaPostVisionReader(provider)
            try:
                outcome = await read_post_vision(
                    db, Job(post_id), reader=reader, store=store
                )
            except Exception as caught:  # noqa: BLE001 - reported, not swallowed
                failed += 1
                print(f"  [{at}/{len(todo)}] FAILED {post_id}: "
                      f"{type(caught).__name__}: {str(caught)[:90]}")
                continue
            await db.commit()

        state = outcome.get("state")
        if state in {"read", "already_read"}:
            done += 1
            found = outcome.get("subject", "-")
            tally[found] = tally.get(found, 0) + 1
        if at % 25 == 0 or at == len(todo):
            print(f"  [{at}/{len(todo)}] {done} read, {failed} failed")

    print("\nwhat the pictures turned out to be:")
    for name, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {name:12s} {count:>4}")
    if failed:
        print(f"\n{failed} failed; run again to retry just those.")

    await engine.dispose()
    return 1 if failed and not done else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
