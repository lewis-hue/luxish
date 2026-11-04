"""Take down pins that cannot possibly render, and say which.

**Why this exists.** A pin is a photograph with words under it. A
published post carrying no photograph is not a quiet edge case - it is
a tile in the middle of the board that stays blank for ever, and a
reviewer scrolling Discover reads that as the app being broken.

`domain.posts.create` already refuses a fit with no media
("A fit needs at least one photograph"), so nothing arriving through
the API can be in this state. What produced it was seeding that wrote
rows directly, which is exactly the kind of thing a repair pass is for:
the guard is in the right place and the data predates it.

**What it does not do.** It does not invent a picture for a caption.
Attaching an unrelated photograph to "Blazer over the knit, third wear
this week" would make the board look whole while telling a lie about
what somebody wore, and a demo that lies is worse than a demo that is
two pins shorter.

Run it after seeding. It is idempotent and it prints what it touched.

    python scripts/repair_pins.py            # report only
    python scripts/repair_pins.py --fix      # take the broken ones down
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LUXISH_ENVIRONMENT", "local")

import sqlalchemy as sa  # noqa: E402  (after the path insert, deliberately)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import get_settings  # noqa: E402


async def unrenderable(session) -> list[tuple[str, str]]:
    """Published pins with no photograph attached: `(id, caption)`."""
    rows = (
        await session.execute(
            sa.text(
                """
                select p.id, coalesce(p.caption, '')
                from posts p
                where p.state = 'published'
                  and p.deleted_at is null
                  and not exists (
                      select 1 from post_media pm where pm.post_id = p.id
                  )
                order by p.created_at
                """
            )
        )
    ).all()
    return [(str(r[0]), str(r[1])) for r in rows]


async def not_fashion(session) -> list[tuple[str, str]]:
    """Published pins whose subject is not something this app hosts.

    The vision reading already names every pin's subject, so this is a
    lookup against `FASHION_SUBJECTS` rather than a judgement made here.
    """
    from app.domain.discovery.subject import FASHION_SUBJECTS

    rows = (
        await session.execute(
            sa.text(
                """
                select p.id, v.subject
                from posts p
                join post_vision v on v.post_id = p.id
                where p.state = 'published'
                  and p.deleted_at is null
                order by p.created_at
                """
            )
        )
    ).all()
    return [(str(r[0]), str(r[1])) for r in rows if str(r[1]) not in FASHION_SUBJECTS]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="take the broken pins down (otherwise only report them)",
    )
    args = parser.parse_args()

    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            broken = await unrenderable(session)
            offtopic = await not_fashion(session)
            if not broken and not offtopic:
                print("Every published pin has a photograph and is about clothes. Nothing to do.")
                return 0

            if broken:
                print(f"{len(broken)} published pin(s) cannot render:")
                for post_id, caption in broken:
                    shown = caption[:60] + ("…" if len(caption) > 60 else "")
                    print(f"  {post_id}  {shown!r}")

            if offtopic:
                counts: dict[str, int] = {}
                for _post_id, subject in offtopic:
                    counts[subject] = counts.get(subject, 0) + 1
                summary = ", ".join(f"{n} {subject}" for subject, n in sorted(counts.items()))
                print(f"{len(offtopic)} published pin(s) are not fashion: {summary}")

            if not args.fix:
                print("\nRe-run with --fix to take them down.")
                return 1

            # Tombstoned rather than deleted, which is how every other
            # removal in this app works: the row stays explicable and
            # anything already referencing it still resolves.
            await session.execute(
                sa.text(
                    "update posts set deleted_at = :now, updated_at = :now where id in :ids"
                ).bindparams(sa.bindparam("ids", expanding=True)),
                {
                    "now": datetime.now(UTC),
                    "ids": [b[0] for b in broken] + [o[0] for o in offtopic],
                },
            )
            await session.commit()
            total = len(broken) + len(offtopic)
            print(f"\nTook down {total} pin(s). The board is whole.")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
