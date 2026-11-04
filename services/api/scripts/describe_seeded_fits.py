"""Read the clothes out of every seeded fit, and caption them with it.

Discover groups by tags and matches on words, so a board of photographs
captioned "saturday" reaches nobody. This reads each photograph once and
stores what is actually in it: the pieces, an outfit sentence, a caption
naming the main garments, and tags.

**It rewrites a caption only on a seeded post.** `screen_mode == "seed"`
marks a fixture this repository wrote, and improving a fixture is not the
same as overwriting a person's words. A real post keeps its author's
caption; the reading is stored beside it and shown only where they left
the field empty, which is what `fit_descriptions.shown_caption` does.

**The outfit sentence is what makes "Try it on" one call.** Somebody
tapping it under a described fit pays for the drawing alone, because the
reading is already here.

Usage::

    python scripts/describe_seeded_fits.py            # everything undescribed
    python scripts/describe_seeded_fits.py --limit 5  # a sample first
    python scripts/describe_seeded_fits.py --force    # re-read described ones
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.domain import fit_descriptions  # noqa: E402
from app.models.fit_description import FitDescriptionRow  # noqa: E402
from app.models.posts import Post  # noqa: E402
from app.providers.base import AIRunRecorder  # noqa: E402
from app.providers.meta import MetaProvider  # noqa: E402
from app.workers.fit_vision import MetaFitReader  # noqa: E402
from app.workers.runner import build_media_store  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="stop after N")
    parser.add_argument("--force", action="store_true", help="re-read fits already described")
    args = parser.parse_args()

    cfg = get_settings()
    if not cfg.meta_api_key:
        print("No model credential configured. Nothing was read.")
        return 1

    store = build_media_store(cfg)
    read = 0
    skipped = 0
    failed = 0

    async with session_scope() as db:
        query = (
            sa.select(Post)
            .where(Post.state == "published", Post.deleted_at.is_(None))
            .order_by(Post.published_at.asc())
        )
        if not args.force:
            query = query.where(~sa.exists().where(FitDescriptionRow.post_id == Post.id))
        posts = list((await db.scalars(query)).all())

    if args.limit:
        posts = posts[: args.limit]
    print(f"{len(posts)} fits to read.")

    for index, post in enumerate(posts, start=1):
        async with session_scope() as db:
            # Built per session rather than once: every model call writes
            # an `AIRun` against the session that made it, and the adapter
            # refuses to run without a recorder. An unaccounted call is a
            # cost nobody can attribute.
            reader = MetaFitReader(MetaProvider(recorder=AIRunRecorder(db)))
            try:
                row = await fit_descriptions.describe_now(
                    db, post_id=post.id, reader=reader, objects=store
                )
            except fit_descriptions.NoPhotograph:
                skipped += 1
                print(f"  [{index}/{len(posts)}] no photograph, skipped")
                continue
            except Exception as caught:  # noqa: BLE001 - one bad fit is not a run
                failed += 1
                print(f"  [{index}/{len(posts)}] failed: {caught}")
                continue

            # A fixture's caption is this repository's own placeholder, so
            # replacing it with what is in the photograph improves the
            # fixture. A real author's caption is never touched.
            live = await db.get(Post, post.id)
            if live is not None and live.screen_mode == "seed" and row.caption:
                live.caption = row.caption
                await db.commit()

            read += 1
            print(f"  [{index}/{len(posts)}] {row.caption or row.outfit[:60]}")

    print(f"\nRead {read}. Skipped {skipped} with no photograph. {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
