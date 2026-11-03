"""Building the archive somebody downloads.

**A zip with the files in it, not a JSON of links.** The first version
of this was going to be a manifest naming each picture by the URL that
serves it, which is smaller and much easier to write. It is also not
portability: those URLs die with the account, so an export taken on
the way out would be a file full of dead links - useless at exactly
the moment it is for. The pictures go in the archive.

**Capped, and the cap is reported.** A wardrobe of two hundred
photographs is not a phone download, so the archive stops adding
pictures at a byte budget. What matters is that it says so: the
manifest carries `pictures_omitted` and lists which ids were left out,
and the row carries the same counts. A truncated archive that does not
mention truncation reads as a complete copy of somebody's account, and
somebody would find out it was not at the worst possible time.

**The manifest is written whatever happens to the pictures.** A
picture whose bytes have gone missing from storage must not take the
whole export down with it - the textual data is the part somebody
cannot reconstruct from their own phone. A missing file is recorded
and the archive carries on.
"""

from __future__ import annotations

import uuid
from typing import Any

EXPORT_JOB_KIND = "account.export"

#: How large an archive may get before it stops adding pictures.
#:
#: 200 MB is about the largest thing worth pushing through a phone on
#: a mobile connection, and the textual manifest is kilobytes, so in
#: practice this is a picture budget.
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024


async def build_export(session: Any, job: Any, *, store: Any) -> dict[str, Any]:
    """Gather one account, write the archive, mark the row ready.

    Returns what happened, for the job record.
    """
    import io
    import json
    import logging
    import zipfile
    from datetime import UTC, datetime

    from app.domain.account_export import (
        NothingToExport,
        deadline_from,
        gather,
    )
    from app.errors import CapabilityUnavailable
    from app.models.account_export import AccountExport
    from app.models.media_asset import MediaAsset

    logger = logging.getLogger(__name__)
    payload = job.payload or {}
    raw = payload.get("export_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no export_id")
    export_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))

    row = await session.get(AccountExport, export_id)
    if row is None:
        return {"export_id": str(export_id), "state": "gone"}
    if row.state != "gathering":
        # Re-dispatched after finishing. Not an error: the archive is
        # already there and rebuilding it would bill every picture
        # read a second time.
        return {"export_id": str(export_id), "state": row.state}

    try:
        manifest = await gather(session, user_id=row.user_id)
    except NothingToExport as exc:
        row.state = "failed"
        row.failure = "This account no longer exists."
        await session.commit()
        return {"export_id": str(export_id), "state": "failed", "reason": str(exc)}

    # Pictures in the order `gather` returns them, which is oldest
    # first. So if the budget runs out it is the newest that are left
    # out, deterministically - the same account exported twice leaves
    # out the same ones, which is why the note below does not promise
    # that asking again gets the rest. It would not.
    wanted = list(manifest.get("pictures") or [])
    included: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        budget = MAX_ARCHIVE_BYTES
        for entry in wanted:
            asset = await session.get(MediaAsset, uuid.UUID(entry["id"]))
            if asset is None or asset.deleted_at is not None:
                omitted.append({"id": entry["id"], "reason": "deleted"})
                continue
            try:
                data = await store.read(asset)
            except CapabilityUnavailable:
                # The row says the bytes exist and they do not. Recorded
                # rather than raised: losing one photograph must not
                # cost somebody their whole export.
                omitted.append({"id": entry["id"], "reason": "file_missing"})
                continue
            if len(data) > budget:
                omitted.append({"id": entry["id"], "reason": "archive_full"})
                continue
            archive.writestr(entry["file"], data)
            budget -= len(data)
            included.append(entry)

        # Written last, so it can describe what actually went in.
        manifest["pictures"] = included
        manifest["pictures_omitted"] = omitted
        if omitted:
            # Worded carefully, because the obvious reassurance is
            # false: the cap is deterministic, so asking again
            # produces the same archive minus the same pictures. The
            # honest thing to say is where they still are.
            manifest["about_omitted_pictures"] = (
                "These pictures are not in this archive. 'archive_full' "
                "means the archive reached its size limit before "
                "reaching them - they are still in the app, and they "
                "are listed here by id so you can tell which. "
                "'file_missing' means the stored file could not be "
                "read. 'deleted' means it was deleted."
            )
        archive.writestr(
            "my-data.json", json.dumps(manifest, indent=2, ensure_ascii=False)
        )

    body = buffer.getvalue()
    key = f"exports/{row.user_id}/{row.id}.zip"
    try:
        await store.write(key, body, content_type="application/zip")
    except CapabilityUnavailable as exc:
        row.state = "failed"
        row.failure = "The file could not be saved. Try again."
        await session.commit()
        return {
            "export_id": str(export_id),
            "state": "failed",
            "reason": exc.code,
        }

    finished = datetime.now(UTC)
    row.storage_key = key
    row.byte_size = len(body)
    row.pictures_included = len(included)
    row.pictures_omitted = len(omitted)
    row.state = "ready"
    row.expires_at = deadline_from(finished)
    await session.commit()

    if omitted:
        # Said out loud rather than only in the file: a cap nobody can
        # see in a log is a cap nobody knows is being hit.
        logger.info(
            "an export left pictures out",
            extra={
                "export": str(row.id),
                "included": len(included),
                "omitted": len(omitted),
            },
        )
    logger.info(
        "built an account export",
        extra={"export": str(row.id), "bytes": len(body)},
    )
    return {
        "export_id": str(export_id),
        "state": "ready",
        "bytes": len(body),
        "pictures_included": len(included),
        "pictures_omitted": len(omitted),
    }


__all__ = ["EXPORT_JOB_KIND", "MAX_ARCHIVE_BYTES", "build_export"]
