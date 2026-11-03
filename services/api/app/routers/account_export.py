"""Ask for a copy of your account, then download it.

Three routes, and the shape is the one every slow thing in this
service already uses (ADR-005, ADR-013): `POST` answers 202 with a row
to watch, `GET` reports where it got to, and a third serves the bytes
once there are some. Gathering reads every picture somebody owns out
of object storage, so it cannot happen inside a request.

**The download is a 404 for anybody but its owner, and a 404 once it
has expired.** Not 403: a 403 confirms the id exists, and the object
behind this id is somebody's whole account. The same doctrine as the
media route, and it matters more here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.config import get_settings
from app.deps import AuthDep, SessionDep
from app.domain import account_export as domain
from app.errors import ApiError, CapabilityUnavailable
from app.schemas.account_export import ExportOut

router = APIRouter(prefix="/account/export", tags=["account-export"])


def _view(row) -> ExportOut:
    return ExportOut(
        id=row.id,
        state=row.state,
        byte_size=row.byte_size,
        pictures_included=row.pictures_included,
        pictures_omitted=row.pictures_omitted,
        failure=row.failure,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


@router.post("", response_model=ExportOut, status_code=status.HTTP_202_ACCEPTED)
async def ask_for_export(db: SessionDep, ctx: AuthDep) -> ExportOut:
    """Start gathering. Answers at once with a row to watch.

    Asking again while one is already gathering returns the one that
    is running rather than starting a second: building an export reads
    every picture somebody owns, so an impatient finger must not be
    able to bill that ten times.
    """
    row = await domain.request(db, user_id=ctx.user_id)
    await db.commit()
    return _view(row)


@router.get("", response_model=ExportOut | None)
async def latest_export(db: SessionDep, ctx: AuthDep) -> ExportOut | None:
    """The most recent export for this account, or null if there is none."""
    row = await domain.latest_for(db, user_id=ctx.user_id)
    if row is None:
        return None
    await db.commit()
    return _view(row)


@router.get("/{export_id}/file")
async def download_export(
    export_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> Response:
    """The archive itself.

    Owner, state and deadline are all checked in
    `domain.readable`, and any of them failing is the same 404.
    """
    row = await domain.readable(db, user_id=ctx.user_id, export_id=export_id)
    if row is None:
        await db.commit()
        raise ApiError("No such export.", status_code=404, code="not_found")

    # `build_media_store`, not `build_local_store`: the latter refuses
    # outside local development by design, so this route would have
    # 500'd in every other environment - including the test one, which
    # is how it was caught. The store has to be the one the configured
    # upload mode implies, the same way the workers get theirs.
    from app.workers.runner import build_media_store

    store = build_media_store(get_settings())

    # `store.read` takes an asset; this is not one. A tiny stand-in
    # rather than a second read method: the store's contract is "given
    # something with a storage_key, give me the bytes", and widening
    # it for one caller would be the larger change.
    class _At:
        id = row.id
        storage_key = row.storage_key

    try:
        body = await store.read(_At())
    except CapabilityUnavailable:
        # The row says ready and the file is gone. Reported as missing
        # rather than as a server error: there is nothing to retry,
        # and the honest next move is to ask for another one.
        raise ApiError(
            "That file is no longer there. Ask for a new copy.",
            status_code=404,
            code="not_found",
        ) from None

    return Response(
        content=body,
        media_type="application/zip",
        headers={
            "Content-Length": str(len(body)),
            "Content-Disposition": f'attachment; filename="luxish-my-data-{row.id}.zip"',
            # Never cached, anywhere. This is the most sensitive object
            # this service serves, and a copy sitting in a proxy or a
            # browser cache outlives the deadline on the row.
            "Cache-Control": "no-store, private",
        },
    )
