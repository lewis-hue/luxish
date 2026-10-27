"""Alembic environment.

Async by necessity (asyncpg has no sync driver) and dialect-agnostic so the
same migration chain can be applied to PostgreSQL 16 in deployment and to
SQLite in the reversibility test.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base

config = context.config

if config.config_file_name is not None and not context.config.attributes.get("skip_logging"):
    try:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except Exception:  # noqa: BLE001, S110 - logging config is not load-bearing
        # A migration must still run when the logging section is absent or
        # malformed; the alternative is an unmigratable database.
        pass

target_metadata = Base.metadata


def resolve_url() -> str:
    overrides = context.get_x_argument(as_dictionary=True)
    url = (
        # Most explicit first: `-x url=...`, then an explicitly configured
        # option, then the environment the service itself runs against.
        overrides.get("url")
        or config.get_main_option("sqlalchemy.url")
        or os.environ.get("LUXISH_ALEMBIC_URL")
        or os.environ.get("LUXISH_DATABASE_URL")
    )
    if not url:
        raise RuntimeError(
            "No database URL. Set LUXISH_DATABASE_URL or pass -x url=<dsn>."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite cannot ALTER in place; batch mode keeps downgrades workable.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(resolve_url(), future=True, poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
