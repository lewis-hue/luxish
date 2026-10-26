"""Task 6 — deletion tombstones that outlive in-flight jobs (ADR-012).

Review Focus item 3: a delete lands while a media worker is mid-flight. The
worker's write must be discarded, and the asset must not reappear in any feed,
search, or CDN path. Checking at job start is not enough — deletion can land
after that check, so ``guard_write`` re-checks ownership, tombstone,
publication consent and asset version in the same transaction as the write.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import (
    AssetGone,
    count_derivatives,
    delete_asset,
    enqueue,
    guard_statement,
    guard_write,
    tombstone_exists,
)
from app.models.media_asset import MediaAsset, MediaDerivative
from app.models.tombstone import Tombstone
from app.models.user import User
from app.workers import media as media_worker


async def make_user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_asset(
    db: AsyncSession, *, user: User | None = None, publication_consent: bool = False
) -> MediaAsset:
    owner = user or await make_user(db)
    asset = MediaAsset(
        user_id=owner.id,
        kind="garment_photo",
        status="uploaded",
        content_type="image/jpeg",
        max_bytes=1024 * 1024,
        storage_key=f"raw/{uuid.uuid4().hex}.jpg",
        publication_consent=publication_consent,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


def thumb() -> media_worker.DerivativeSpec:
    return media_worker.DerivativeSpec(
        kind="thumbnail",
        storage_key=f"thumb/{uuid.uuid4().hex}.webp",
        content_type="image/webp",
        byte_size=4096,
        width=256,
        height=256,
    )


# --------------------------------------------------------------------------- #
# the load-bearing test
# --------------------------------------------------------------------------- #
async def test_late_worker_result_cannot_resurrect_deleted_asset(db: AsyncSession) -> None:
    asset = await make_asset(db)
    # Held as plain values: the refusal rolls the transaction back, which
    # expires every instance attached to the session.
    asset_id, version = asset.id, asset.version
    job = await enqueue(db, "media.derive", {"asset_id": str(asset_id)})

    await delete_asset(db, asset_id)  # happens mid-flight

    with pytest.raises(AssetGone):
        await media_worker.persist(db, job, derivatives=[thumb()], asset_version=version)

    assert await count_derivatives(db, asset_id) == 0
    assert await tombstone_exists(db, asset_id)


async def test_a_successful_persist_writes_the_derivatives(db: AsyncSession) -> None:
    asset = await make_asset(db)
    job = await enqueue(db, "media.derive", {"asset_id": str(asset.id)})

    written = await media_worker.persist(
        db, job, derivatives=[thumb()], asset_version=asset.version
    )

    assert len(written) == 1
    assert await count_derivatives(db, asset.id) == 1


async def test_nothing_is_written_when_the_guard_fails_mid_batch(db: AsyncSession) -> None:
    """The write and the check share a transaction, so a refusal leaves nothing."""
    asset = await make_asset(db)
    asset_id, version = asset.id, asset.version
    job = await enqueue(db, "media.derive", {"asset_id": str(asset_id)})
    await delete_asset(db, asset_id)

    with pytest.raises(AssetGone):
        await media_worker.persist(
            db, job, derivatives=[thumb(), thumb(), thumb()], asset_version=version
        )

    assert await count_derivatives(db, asset_id) == 0
    assert (await db.scalar(sa.select(sa.func.count()).select_from(MediaDerivative))) == 0


# --------------------------------------------------------------------------- #
# guard_write — the four checks
# --------------------------------------------------------------------------- #
async def test_guard_write_passes_for_a_live_owned_asset(db: AsyncSession) -> None:
    asset = await make_asset(db)
    guarded = await guard_write(db, asset.id, version=asset.version, user_id=asset.user_id)
    assert guarded.id == asset.id


async def test_guard_write_refuses_a_tombstoned_asset(db: AsyncSession) -> None:
    asset = await make_asset(db)
    await delete_asset(db, asset.id)
    with pytest.raises(AssetGone) as exc:
        await guard_write(db, asset.id, version=asset.version)
    assert exc.value.reason == "tombstoned"


async def test_guard_write_refuses_an_unknown_asset(db: AsyncSession) -> None:
    with pytest.raises(AssetGone) as exc:
        await guard_write(db, uuid.uuid4())
    assert exc.value.reason == "missing"


async def test_guard_write_refuses_a_stale_version(db: AsyncSession) -> None:
    """Derivatives computed from v1 must not be attached to v2 of the bytes."""
    asset = await make_asset(db)
    asset.version = 2
    await db.commit()
    with pytest.raises(AssetGone) as exc:
        await guard_write(db, asset.id, version=1)
    assert exc.value.reason == "version_changed"


async def test_guard_write_refuses_a_different_owner(db: AsyncSession) -> None:
    asset = await make_asset(db)
    other = await make_user(db)
    with pytest.raises(AssetGone) as exc:
        await guard_write(db, asset.id, version=asset.version, user_id=other.id)
    assert exc.value.reason == "not_owner"


async def test_guard_write_refuses_publishing_without_consent(db: AsyncSession) -> None:
    asset = await make_asset(db, publication_consent=False)
    with pytest.raises(AssetGone) as exc:
        await guard_write(
            db, asset.id, version=asset.version, require_publication_consent=True
        )
    assert exc.value.reason == "no_publication_consent"


async def test_guard_write_allows_publishing_with_consent(db: AsyncSession) -> None:
    asset = await make_asset(db, publication_consent=True)
    guarded = await guard_write(
        db, asset.id, version=asset.version, require_publication_consent=True
    )
    assert guarded.publication_consent is True


def test_the_guard_locks_the_asset_row_on_postgres() -> None:
    """A concurrent delete must serialise behind the guard, not race it."""
    compiled = str(
        guard_statement(uuid.uuid4()).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "FOR UPDATE" in compiled


# --------------------------------------------------------------------------- #
# deletion semantics
# --------------------------------------------------------------------------- #
async def test_delete_removes_existing_derivatives(db: AsyncSession) -> None:
    asset = await make_asset(db)
    job = await enqueue(db, "media.derive", {"asset_id": str(asset.id)})
    await media_worker.persist(db, job, derivatives=[thumb()], asset_version=asset.version)
    assert await count_derivatives(db, asset.id) == 1

    await delete_asset(db, asset.id)

    assert await count_derivatives(db, asset.id) == 0


async def test_delete_is_idempotent_and_keeps_one_tombstone(db: AsyncSession) -> None:
    asset = await make_asset(db)
    await delete_asset(db, asset.id)
    await delete_asset(db, asset.id)
    count = await db.scalar(
        sa.select(sa.func.count()).select_from(Tombstone).where(Tombstone.asset_id == asset.id)
    )
    assert count == 1


async def test_a_tombstone_for_an_unknown_asset_is_still_recorded(db: AsyncSession) -> None:
    """Deleting something we have already forgotten must still deny it."""
    orphan = uuid.uuid4()
    await delete_asset(db, orphan)
    assert await tombstone_exists(db, orphan)


async def test_the_tombstone_outlives_the_asset_row(db: AsyncSession) -> None:
    asset = await make_asset(db)
    await delete_asset(db, asset.id)
    await db.execute(sa.delete(MediaAsset).where(MediaAsset.id == asset.id))
    await db.commit()

    assert await tombstone_exists(db, asset.id)
    with pytest.raises(AssetGone):
        await guard_write(db, asset.id)


def test_the_tombstone_table_has_no_foreign_key_to_the_asset() -> None:
    """An FK would be deleted with the row it is supposed to outlive."""
    assert Tombstone.__table__.foreign_keys == set() or all(
        fk.column.table.name != "media_assets" for fk in Tombstone.__table__.foreign_keys
    )


async def test_the_asset_is_marked_deleted_as_well_as_tombstoned(db: AsyncSession) -> None:
    asset = await make_asset(db)
    asset_id = asset.id
    await delete_asset(db, asset_id)
    db.expire_all()
    refreshed = await db.get(MediaAsset, asset_id)
    assert refreshed is not None
    assert refreshed.deleted_at is not None
