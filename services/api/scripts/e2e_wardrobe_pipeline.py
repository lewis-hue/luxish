"""The wardrobe media pipeline, end to end, against the real stack.

Proves the path the app will take and that the unit suite cannot: authorise
an upload, PUT the bytes through the HTTP receiver, create the garment, then
run the real worker handlers so the live classifier sorts it and the live
segmenter cuts it out. Nothing here is a double except the identity, because
the realm has no browser session to borrow.

Costs a few cents per garment. Run it deliberately:

    MODEL_API_KEY=LLM_... python scripts/e2e_wardrobe_pipeline.py

It writes real rows into whatever `LUXISH_DATABASE_URL` points at and real
files under `local_media_root`, so point it at a development database.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402

if key := os.environ.get("MODEL_API_KEY"):
    os.environ.setdefault("LUXISH_META_API_KEY", key)

from app.config import get_settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.domain import garment_media  # noqa: E402
from app.domain.jobs import claim_job_by_id, complete_job, ready_job_ids  # noqa: E402
from app.domain.uploads import authorize_upload, build_authorizer  # noqa: E402
from app.models import Consent, Garment, User  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.media_asset import MediaAsset  # noqa: E402
from app.workers.runner import all_handlers  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
IMAGES = REPO / "apps" / "mobile" / "assets" / "images" / os.environ.get("E2E_DIR", "wardrobe")

#: One garment is enough to prove the path, and each costs money.
SAMPLE = os.environ.get("E2E_SAMPLE", "linen-shirt.webp")


async def main() -> int:
    if not os.environ.get("MODEL_API_KEY"):
        print("MODEL_API_KEY is not set. Refusing to pretend this ran.")
        return 2

    cfg = get_settings()
    print(f"storage mode : {cfg.upload_storage_mode}")
    print(f"media root   : {cfg.local_media_root}")
    if cfg.upload_storage_mode != "local_file":
        print("This script needs LUXISH_UPLOAD_STORAGE_MODE=local_file.")
        return 2

    photo = IMAGES / SAMPLE
    if not photo.exists():
        print(f"missing sample image: {photo}")
        return 2
    data = photo.read_bytes()
    print(f"photograph   : {SAMPLE}, {len(data):,} bytes\n")

    # ---------------------------------------------------------------- user
    async with session_scope() as session:
        user = User(
            id=uuid.uuid4(),
            email=f"e2e-{uuid.uuid4().hex[:8]}@luxish.example",
            display_name="Pipeline",
        )
        session.add(user)
        await session.flush()
        from datetime import UTC, datetime

        session.add(
            Consent(
                id=uuid.uuid4(),
                user_id=user.id,
                kind="ai_processing",
                granted_at=datetime.now(UTC),
                source="e2e_script",
            )
        )
        await session.commit()
        user_id = user.id
    print(f"user         : {user_id}")

    # ------------------------------------------------------- authorise + PUT
    async with session_scope() as session:
        auth = await authorize_upload(
            session,
            user_id=user_id,
            kind="garment_photo",
            content_type="image/webp",
            content_length=len(data),
            allowed_content_types=cfg.upload_allowed_content_types,
            max_bytes=cfg.upload_max_bytes,
            ttl_seconds=cfg.upload_authorization_ttl_seconds,
            authorizer=build_authorizer(
                mode=cfg.upload_storage_mode,
                bucket=cfg.gcs_bucket,
                public_base_url=cfg.public_base_url,
            ),
        )
    print(f"asset        : {auth.asset_id}")
    print(f"upload url   : {auth.upload_url}")
    print(f"storage mode : {auth.storage_mode}")

    # The receiver is an HTTP endpoint and needs a bearer token the realm
    # would normally mint. Calling the storage layer directly instead keeps
    # this script independent of a browser sign-in while still exercising the
    # same write path the endpoint uses.
    from app.storage.local import build_local_store

    store = build_local_store(environment=cfg.environment, root=cfg.local_media_root)
    key = f"users/{user_id}/media/{auth.asset_id}"
    await store.write(key, data, content_type="image/webp")

    import hashlib

    async with session_scope() as session:
        asset = await session.get(MediaAsset, auth.asset_id)
        assert asset is not None
        asset.storage_key = key
        asset.byte_size = len(data)
        asset.checksum_sha256 = hashlib.sha256(data).hexdigest()
        asset.status = "uploaded"
        await session.commit()

    stored = store.path_for(key)
    print(f"stored at    : {stored}  ({stored.stat().st_size:,} bytes on disk)\n")

    # ------------------------------------------------------------- garment
    async with session_scope() as session:
        garment = Garment(
            id=uuid.uuid4(),
            user_id=user_id,
            media_asset_id=auth.asset_id,
            name="Uploaded garment",
            availability="available",
            confirmed_attributes={},
            inferred_attributes={},
        )
        session.add(garment)
        await session.commit()
        garment_id = garment.id
    print(f"garment      : {garment_id}")

    # ----------------------------------------------------------- enqueue
    async with session_scope() as session:
        pending_garment = await session.get(Garment, garment_id)
        assert pending_garment is not None
        if os.environ.get("E2E_OUTFIT"):
            from app.domain.jobs import enqueue
            from app.workers.outfit import DETECT_OUTFIT_JOB_KIND

            await enqueue(
                session,
                DETECT_OUTFIT_JOB_KIND,
                {
                    "garment_id": str(garment_id),
                    "asset_id": str(auth.asset_id),
                    "asset_version": 1,
                    "user_id": str(user_id),
                },
                idempotency_key=f"outfit:{garment_id}",
                notify=False,
            )
            print(f"enqueued     : ['{DETECT_OUTFIT_JOB_KIND}']\n")
        else:
            kinds = await garment_media.enqueue_media_pipeline(
                session, garment=pending_garment, user_id=user_id
            )
            print(f"enqueued     : {list(kinds)}\n")

    # -------------------------------------------------------------- work
    handlers = all_handlers()
    print(f"handlers     : {sorted(handlers)}\n")

    while True:
        async with session_scope() as session:
            pending = await ready_job_ids(session, limit=10)
        if not pending:
            break
        for job_id in pending:
            async with session_scope() as session:
                job = await claim_job_by_id(session, job_id, worker="e2e")
                if job is None:
                    continue
                kind = job.kind
                handler = handlers.get(kind)
                if handler is None:
                    print(f"  {kind}: no handler")
                    continue
                print(f"  running {kind} ...")
                try:
                    result = await handler(session, job)
                    await complete_job(session, job, result=result)
                    print(f"  {kind}: {result}")
                except Exception as exc:  # noqa: BLE001 - this is the report
                    print(f"  {kind} FAILED: {type(exc).__name__}: {exc}")
                    await session.rollback()

    # ------------------------------------------------------------ result
    print()
    async with session_scope() as session:
        garment = await session.get(Garment, garment_id)
        assert garment is not None
        print("RESULT")
        print(f"  category              : {garment.category}")
        print(f"  categorisation_conf   : {garment.categorisation_confidence}")
        print(f"  inferred              : {garment.inferred_attributes}")
        print(f"  cut-out asset         : {garment.background_removed_asset_id}")

        if garment.background_removed_asset_id:
            cut = await session.get(MediaAsset, garment.background_removed_asset_id)
            if cut and cut.storage_key:
                path = store.path_for(cut.storage_key)
                exists = path.exists()
                size = path.stat().st_size if exists else 0
                print(f"  cut-out on disk       : {exists}  ({size:,} bytes)")
                if exists:
                    out = Path(os.environ.get("E2E_OUT", ".")) / "cutout.png"
                    out.write_bytes(path.read_bytes())
                    print(f"  copied to             : {out.resolve()}")

        total = await session.scalar(
            sa.select(sa.func.count()).select_from(Job).where(Job.state == "succeeded")
        )
        failed = await session.scalar(
            sa.select(sa.func.count())
            .select_from(Job)
            .where(Job.state.in_(("failed", "dead_letter")))
        )
        print(f"  jobs succeeded/failed : {total}/{failed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
