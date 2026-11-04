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
    "0010_garment_render",
    "0011_garment_image_is_rendered",
    "0012_look_interactions",
    "0013_saved_looks",
    "0014_user_cohorts",
    "0015_cohort_inspirations",
    "0016_outfit_plans",
    "0017_moodboards",
    "0018_avatar_renders",
    "0019_profile_photo",
    "0020_follows",
    "0021_community_sharing",
    "0022_subscriptions",
    "0023_moderation",
    "0024_gift_ledger",
    "0025_shopping",
    "0026_posts",
    "0027_post_saves",
    "0028_garment_shots",
    "0029_profiles_tags_reactions",
    "0030_board_post_pins",
    "0031_fit_descriptions_brand_stories",
    "0032_stylist_subject_and_intent",
    "0033_likeness_avatar",
    "0034_post_comments",
    "0035_report_guidelines",
    "0036_profile_banner",
    "0037_post_hides",
    "0038_private_accounts",
    "0039_direct_messages",
    "0040_message_media",
    "0041_clear_thread",
    "0042_plan_garments",
    "0043_drop_looks",
    "0044_comment_likes",
    "0045_push_notifications",
    "0046_post_visibility",
    "0047_shot_brief",
    "0048_message_hidden_for",
    "0049_plan_reference_post",
    "0050_fit_pieces",
    "0051_shot_landscape",
    "0052_account_exports",
    "0053_post_vision",
    "0054_vision_presentation",
    "0055_packshot_media_kind",
    "0056_piece_packshots",
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


def _reset_schema(url: str) -> None:
    """Drop everything, including the version table and the native enums.

    Needed because `Base.metadata.drop_all` (used by the other PostgreSQL
    test) removes the model tables but leaves `alembic_version` behind, and a
    version table claiming head makes `upgrade head` a no-op against an empty
    database. Dropping the schema also clears the native enum types, which
    outlive their tables and would otherwise collide on the next upgrade.

    Safe because this only ever runs against LUXISH_TEST_PG_URL, which is a
    database the test suite owns.
    """
    engine = sa.create_engine(_sync_url(url), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            conn.execute(sa.text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_upgrade_head_then_downgrade_base_on_postgres() -> None:
    url = os.environ.get("LUXISH_TEST_PG_URL")
    if not url:
        pytest.skip("LUXISH_TEST_PG_URL is not set")
    cfg = _config(url)
    # Independent of whatever ran before, including a sibling test that
    # dropped the tables without resetting the version.
    _reset_schema(url)
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
