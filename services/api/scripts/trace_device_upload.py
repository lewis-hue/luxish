"""Walk one photograph through the exact HTTP path the app takes.

Not a unit test and not the e2e script: this talks to the running API over the
network with a real Keycloak token, so it exercises the upload receiver, the
garment endpoint, and the job pipeline the way a phone does. The e2e script
deliberately bypasses the HTTP receiver, which is why a bug that lived only in
that hop survived a green suite.

    python scripts/trace_device_upload.py <image> <username> <password>
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

if key := os.environ.get("MODEL_API_KEY"):
    os.environ.setdefault("LUXISH_META_API_KEY", key)

API = os.environ.get("TRACE_API", "http://192.168.100.2:8010")
ISSUER = os.environ.get("TRACE_ISSUER", "https://luxish-kc.loca.lt/realms/luxish")

#: Tokens are minted against Keycloak directly, not through the public tunnel.
#:
#: `KC_HOSTNAME` makes the realm stamp the tunnel issuer on every token no
#: matter which address it was reached on, so a token minted here carries the
#: issuer the API validates against. The tunnel exists for the phone's browser
#: and for Google, neither of which is involved in a script, and routing these
#: through it only made every run depend on a third party staying up.
MINT_URL = "http://localhost:55080/realms/luxish"
CLIENT = os.environ.get("TRACE_CLIENT", "luxish-mobile")


async def main() -> int:
    image = Path(sys.argv[1])
    username, password = sys.argv[2], sys.argv[3]
    data = image.read_bytes()
    print(f"photo        : {image.name}, {len(data):,} bytes")

    async with httpx.AsyncClient(timeout=120) as http:
        token_response = await http.post(
            f"{MINT_URL}/protocol/openid-connect/token",
            data={
                "client_id": CLIENT,
                "grant_type": "password",
                "scope": "openid profile email",
                "username": username,
                "password": password,
            },
        )
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        print(f"token        : {len(token)} chars for {username}")

        authorized = await http.post(
            f"{API}/v1/uploads/authorize",
            headers=auth,
            json={
                "kind": "garment_photo",
                "content_type": "image/jpeg",
                "content_length": len(data),
            },
        )
        print(f"authorize    : {authorized.status_code}")
        authorized.raise_for_status()
        issued = authorized.json()
        asset_id = issued["asset_id"]

        put = await http.put(
            issued["upload_url"],
            headers={**auth, **issued.get("required_headers", {})},
            content=data,
        )
        print(f"PUT bytes    : {put.status_code}")
        put.raise_for_status()

        created = await http.post(
            f"{API}/v1/wardrobe/garments",
            headers=auth,
            json={
                "name": "Worn outfit",
                "media_asset_id": asset_id,
                "availability": "available",
            },
        )
        print(f"create       : {created.status_code}")
        created.raise_for_status()
        garment_id = uuid.UUID(created.json()["id"])
        print(f"garment      : {garment_id}\n")

    # The queue is Postgres-owned, so the jobs are already durable and
    # claimable. No worker is running locally, so drain them here rather than
    # pretend the pipeline is asynchronous when nothing is consuming it.
    from app.db.session import session_scope
    from app.domain.jobs import claim_job_by_id, complete_job, fail_job, ready_job_ids
    from app.workers.runner import all_handlers

    handlers = all_handlers()
    while True:
        async with session_scope() as session:
            pending = await ready_job_ids(session, limit=10)
        if not pending:
            break
        for job_id in pending:
            async with session_scope() as session:
                job = await claim_job_by_id(session, job_id, worker="trace")
                if job is None:
                    continue
                handler = handlers.get(job.kind)
                if handler is None:
                    print(f"  {job.kind}: no handler")
                    continue
                print(f"  running {job.kind} ...")
                try:
                    result = await handler(session, job)
                    await complete_job(session, job, result=result)
                    print(f"  {job.kind}: {result}")
                except Exception as exc:  # noqa: BLE001 - this is the report
                    print(f"  {job.kind} FAILED: {type(exc).__name__}: {exc}")
                    await session.rollback()
                    async with session_scope() as recovery:
                        stuck = await claim_job_by_id(recovery, job_id, worker="trace")
                        if stuck is not None:
                            await fail_job(recovery, stuck, error=str(exc))

    import sqlalchemy as sa

    from app.models import Garment

    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    sa.select(Garment)
                    .where(Garment.user_id == (await _user_id(session, username)))
                    .where(Garment.deleted_at.is_(None))
                    .order_by(Garment.created_at)
                )
            )
            .scalars()
            .all()
        )
        print(f"\nWARDROBE ({len(rows)} garments)")
        for row in rows:
            inferred = row.inferred_attributes or {}
            bits = ", ".join(f"{k}={v}" for k, v in inferred.items() if k != "slot" and v)
            print(f"  {row.name[:38]:<38} {str(row.category):<22} {bits[:70]}")
    return 0


async def _user_id(session, email: str):
    import sqlalchemy as sa

    from app.models import User

    return await session.scalar(sa.select(User.id).where(User.email == email))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
