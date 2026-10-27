#!/usr/bin/env python3
"""Load reviewed reference data into the database.

Deliberately **not** an Alembic data migration. Regional style knowledge is reviewed
editorial content with its own provenance, reviewer and version chain; welding it to
schema history would mean a correction to a styling note becomes a schema migration,
and a schema rollback silently reverts reviewed knowledge.

Idempotent. The natural key is ``(geography_key, source_slug, version)``, so re-running
inserts nothing and reports zero.

    python scripts/seed.py                 # all seed sets
    python scripts/seed.py --only regional
    python scripts/seed.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# The service root, so this runs as a plain script from any directory. pytest gets
# this from `pythonpath` in pyproject.toml; a direct `python scripts/seed.py` does
# not.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Importing the model registry is what puts every table on Base.metadata.
import app.models  # noqa: E402, F401
from app.config import get_settings  # noqa: E402
from app.domain import regional  # noqa: E402

SEED_SETS = ("regional",)


async def seed_regional(session: AsyncSession, *, dry_run: bool) -> int:
    inserted = await regional.seed_regional_profiles(session)
    if dry_run:
        await session.rollback()
        print(f"regional: would insert {inserted} profile(s) (rolled back)")
        return inserted
    await session.commit()
    print(f"regional: inserted {inserted} profile(s)")
    return inserted


async def main_async(only: str | None, dry_run: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    requested = (only,) if only else SEED_SETS
    unknown = [name for name in requested if name not in SEED_SETS]
    if unknown:
        print(f"unknown seed set(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"available: {', '.join(SEED_SETS)}", file=sys.stderr)
        return 2

    total = 0
    try:
        async with factory() as session:
            for name in requested:
                if name == "regional":
                    total += await seed_regional(session, dry_run=dry_run)
    finally:
        await engine.dispose()

    print(f"total inserted: {total}" + (" (dry run)" if dry_run else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=SEED_SETS, help="seed one set instead of all")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be inserted, then roll back",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.only, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
