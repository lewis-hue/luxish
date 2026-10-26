"""Async engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def build_engine(
    database_url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 5,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
    echo: bool = False,
) -> AsyncEngine:
    """Build an async engine with a bounded pool.

    SQLite uses SQLAlchemy's own pool policy and accepts no sizing arguments, so
    the bounds are applied only to server-backed dialects.
    """
    if database_url.startswith("sqlite"):
        return create_async_engine(database_url, echo=echo, future=True)
    return create_async_engine(
        database_url,
        echo=echo,
        future=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@lru_cache(maxsize=1)
def _engine_and_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    cfg: Settings = get_settings()
    engine = build_engine(
        cfg.database_url,
        pool_size=cfg.db_pool_size,
        max_overflow=cfg.db_max_overflow,
        pool_timeout=cfg.db_pool_timeout_seconds,
        pool_recycle=cfg.db_pool_recycle_seconds,
    )
    return engine, session_factory(engine)


def get_engine() -> AsyncEngine:
    return _engine_and_factory()[0]


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return _engine_and_factory()[1]


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    maker = get_session_factory()
    async with maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    engine, _ = _engine_and_factory()
    await engine.dispose()
    _engine_and_factory.cache_clear()
