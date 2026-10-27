"""Every migration must be reversible, and must agree with the models.

These tests run the real Alembic chain. By default they run on SQLite, which is
what keeps them runnable with no server; set ``LUXISH_TEST_PG_URL`` and select
the ``postgres`` marker to run the same chain against PostgreSQL 16, where the
native enum and JSONB paths are actually exercised.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

API_ROOT = Path(__file__).resolve().parents[1]

# 0005 is intentionally skipped: the number was reserved while the chain was being
# planned and was never used. The stylist tables landed as 0008 instead. The chain
# must stay linear with a single head.
#
# This list is the test's whole point: autogenerate is not trusted to keep the chain
# linear, so a new migration has to be declared here deliberately.
EXPECTED_ORDER = [
    "0001_core",
    "0002_wardrobe",
    "0003_jobs",
    "0004_ai",
    "0006_regional",
    "0007_external",
    "0008_stylist",
    "0009_wardrobe_media",
]


def _config(url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["skip_logging"] = True
    return cfg


def _sync_url(url: str) -> str:
    return url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")


def test_the_revision_chain_is_linear_and_numbered_as_planned() -> None:
    scripts = ScriptDirectory(str(API_ROOT / "alembic"))
    revisions = [s.revision for s in scripts.walk_revisions()][::-1]
    assert revisions == EXPECTED_ORDER
    heads = scripts.get_heads()
    assert len(heads) == 1, f"migration history has branched: {heads}"


def _tables(url: str) -> set[str]:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            return set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_head_then_downgrade_base_on_sqlite(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'chain.sqlite3').as_posix()}"
    cfg = _config(url)

    command.upgrade(cfg, "head")
    after_upgrade = _tables(url)
    assert "users" in after_upgrade
    assert "garments" in after_upgrade
    assert "jobs" in after_upgrade
    assert "external_references" in after_upgrade

    command.downgrade(cfg, "base")
    after_downgrade = _tables(url) - {"alembic_version"}
    assert after_downgrade == set(), f"downgrade left tables behind: {after_downgrade}"


def test_each_revision_is_individually_reversible(tmp_path: Path) -> None:
    """Step up one revision at a time, then step all the way back down."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'stepwise.sqlite3').as_posix()}"
    cfg = _config(url)
    for _ in EXPECTED_ORDER:
        command.upgrade(cfg, "+1")
    for _ in EXPECTED_ORDER:
        command.downgrade(cfg, "-1")
    assert _tables(url) - {"alembic_version"} == set()


def test_migrations_cover_every_model_table(tmp_path: Path) -> None:
    """A table in the models but not in a migration is a deploy-time surprise."""
    from app import models  # noqa: F401
    from app.db.base import Base

    url = f"sqlite+aiosqlite:///{(tmp_path / 'parity.sqlite3').as_posix()}"
    cfg = _config(url)
    command.upgrade(cfg, "head")
    migrated = _tables(url) - {"alembic_version"}
    declared = set(Base.metadata.tables)
    assert declared - migrated == set(), f"missing from migrations: {declared - migrated}"
    assert migrated - declared == set(), f"migrated but undeclared: {migrated - declared}"


@pytest.mark.postgres
def test_upgrade_head_then_downgrade_base_on_postgres() -> None:
    url = os.environ.get("LUXISH_TEST_PG_URL")
    if not url:
        pytest.skip("LUXISH_TEST_PG_URL is not set")
    cfg = _config(url)
    command.upgrade(cfg, "head")
    assert "garments" in _tables(url)
    command.downgrade(cfg, "base")
    assert _tables(url) - {"alembic_version"} == set()

    # Native enum types must not survive a full downgrade.
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            leftovers = conn.execute(
                sa.text("SELECT typname FROM pg_type WHERE typname IN "
                        "('identity_provider','consent_kind','garment_availability',"
                        "'media_asset_status','job_state','social_platform',"
                        "'regional_granularity')")
            ).scalars().all()
        assert leftovers == [], f"enum types left behind: {leftovers}"
    finally:
        engine.dispose()
