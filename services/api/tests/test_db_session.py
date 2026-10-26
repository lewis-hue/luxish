"""Task 3 — session factory and bounded pool."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.session import build_engine, session_factory


def test_postgres_engine_uses_a_bounded_pool() -> None:
    engine = build_engine("postgresql+asyncpg://u:p@h/db")
    assert engine.pool.size() == 10
    assert engine.pool._max_overflow == 5


def test_sqlite_engine_skips_pool_sizing() -> None:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    assert engine.dialect.name == "sqlite"


async def test_session_factory_yields_async_sessions() -> None:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = session_factory(engine)
    async with maker() as session:
        assert isinstance(session, AsyncSession)
    await engine.dispose()
