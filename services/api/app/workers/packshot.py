"""Turn a photograph of a garment somebody owns into a catalogue shot.

**Why the wardrobe needed this and a cut-out was not enough.** A
garment arrives as a phone photograph: on a bed, on a floor, half in
shadow, at an angle, with a foot in the frame. Background removal is
segmentation - it finds the garment's pixels and drops everything
else - so the best it can do is that same crumpled, badly-lit garment
with the room taken away. On a dark garment it does noticeably worse:
a black sock against a dim duvet cuts out as a black blob, which is
what the wardrobe was showing.

A packshot is a different operation. It is an **edit of their own
photograph** that re-stages the garment the way a shop would
photograph stock: laid flat, squared to the camera, evenly lit on a
plain ground. The print, the weave, the colour and the wear are all
still theirs, because they are in the source pixels - this is not a
drawing of a garment like theirs, and it is not badged as one.

**It supersedes the cut-out rather than replacing the photograph.**
`media_asset_id` still points at what they took; the packshot lands in
`background_removed_asset_id`, which is already defined as "the
garment on a plain ground" and is already what every client prefers.
So a wardrobe tile, a try-on, a collage and the stylist all pick it up
with no change: one shot, made once, reused everywhere.

**The cut-out is the fallback, which is why this runs last.** If the
edit is unavailable, refused or returns nothing, the garment keeps
whatever background removal gave it, and before that the photograph.
Every failure here leaves the wardrobe exactly as usable as it was.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import guard_write
from app.errors import CapabilityUnavailable
from app.models.garment import Garment
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.workers.categorise import (
    MediaStore,
    UnavailableMediaStore,
    read_payload,
)
from app.workers.garment_studio import GarmentStudio, treatment_by_id

logger = logging.getLogger(__name__)

PACKSHOT_JOB_KIND = "garment.packshot"

#: The treatment this runs. Named rather than inlined so the wardrobe
#: and the Studio tab cannot drift into producing two different things
#: under the same word.
PACKSHOT_TREATMENT = "packshot"

#: The media kind a wardrobe packshot is stored under.
#:
#: Distinct from `garment_studio`, which is a shot somebody asked for
#: in the Studio and may delete. This one is wardrobe plumbing: it is
#: the garment's picture, it is created without being asked for, and
#: it is deleted with the garment.
PACKSHOT_MEDIA_KIND = "garment_packshot"

#: Used only when the result does not say what it is.
#:
#: **Read from the response, never assumed.** The vendor's image
#: endpoint returns WEBP where the OpenAI-shaped client makes PNG the
#: natural guess, and bytes stored under the wrong type render on some
#: clients and silently fail on others. `GeneratedImage.content_type`
#: documents exactly this trap.
PACKSHOT_CONTENT_TYPE = "image/webp"

#: Pictures that already serve as a garment's catalogue shot.
#:
#: **`garment_studio` counts, and leaving it out cost a second
#: generation.** The fan-out path asked the Studio for each piece's
#: packshot long before this worker existed; those pictures are real
#: packshots and are already paid for, they just live under the
#: Studio's media kind. A garment that has adopted one must not be
#: redrawn - the backfill queued thirty-three drawings on an account
#: where nine of them already had their picture.
ALREADY_A_PACKSHOT = (PACKSHOT_MEDIA_KIND, "garment_studio")

#: Used when the source photograph holds more than this garment.
#:
#: **The reported failure, and it was my own doing.** A photograph of
#: somebody wearing six things is split into six garments, and each
#: one's `media_asset_id` points at its *cut-out* rather than at the
#: photograph - a documented workaround for the one-garment-per-upload
#: index. Feeding that cut-out to the packshot meant re-staging a
#: pixelated, part-occluded silhouette: the headphones came back as a
#: speckled stone blob, faithfully rendered from rubbish.
#:
#: So the edit reads the original upload and is told which garment to
#: take out of it. The model can see the whole photograph, which is
#: the only thing that knows what the garment actually looks like -
#: the cut-out has already thrown that away.
#: Said in every packshot prompt, because the model does not assume it.
#:
#: **Reported: one packshot per shoe.** Asked for "white chunky
#: sneakers" it returned one sneaker, and the wardrobe then showed a
#: single shoe as the thing somebody owns. Nobody owns one sneaker.
#: The same goes for socks, gloves and earrings, which are all one
#: wardrobe item and two objects.
AS_A_PAIR = (
    "If this item is naturally a pair or a set - shoes, trainers, "
    "boots, socks, gloves, earrings - show both of them together in "
    "the one picture, arranged side by side as a pair. A single shoe "
    "is not the item somebody owns. "
)

ISOLATE = (
    "From this photograph, take only the {subject} and nothing else, "
    "and photograph it as a flat catalogue packshot: laid out neatly, "
    "squared to the camera, shot from directly above, centred and "
    "filling the frame with a small even margin. "
    "Keep that exact item - its real colour, material, markings, wear "
    "and proportions - as it appears in the photograph. Do not "
    "redesign it, do not clean it up and do not invent detail that is "
    "not there. "
    "Nothing else in the picture: no person, no other clothing, no "
    "hands, no hanger, no props. Plain pure white background with no "
    "shadow and no visible surface. No brand marks, no logos and no "
    "text. Evenly lit, true colour, photographed rather than "
    "illustrated. " + AS_A_PAIR
)


def packshot_storage_key(asset: MediaAsset, *, content_type: str) -> str:
    """Keyed by source asset and version, like the cut-out beside it.

    A new photograph for the same garment is a new version and so a
    new key, which is what stops a re-upload being served the previous
    garment's packshot out of a cache. The extension follows the bytes
    rather than the other way round.
    """
    suffix = "png" if "png" in content_type else "webp"
    return f"packshots/{asset.user_id}/{asset.id}/v{asset.version}.{suffix}"


async def make_packshot(
    session: AsyncSession,
    job: Job,
    *,
    studio: GarmentStudio,
    store: MediaStore | None = None,
) -> dict[str, Any]:
    """Shoot one garment, and point the wardrobe at the result."""
    store = store or UnavailableMediaStore()
    payload = read_payload(job)
    job_ref, asset_ref = str(job.id), str(payload.asset_id)

    asset = await guard_write(
        session,
        payload.asset_id,
        version=payload.asset_version,
        user_id=payload.user_id,
    )

    garment = await session.scalar(
        sa.select(Garment).where(
            Garment.id == payload.garment_id, Garment.deleted_at.is_(None)
        )
    )
    if garment is None:
        return {"packshot": False, "reason": "garment_deleted"}

    # Already shot. The job's idempotency key makes a second enqueue
    # impossible; this covers a retry after a partial failure, and it
    # is checked on the asset's *kind* rather than on the field being
    # set - the field is also where a plain cut-out lands, and a
    # cut-out is precisely what this is here to improve on.
    # **`force` exists because a redraw is a real need and the guard
    # below silently defeated it.** A garment whose packshot was made
    # from the wrong source, or before a prompt was fixed, *has* a
    # packshot - so the check said "already present", the job
    # succeeded, and nothing changed. Verified the hard way: a
    # redraw of seven garments returned byte-for-byte identical
    # pictures. Only the backfill's `--redo` sets this.
    forced = bool((job.payload or {}).get("force"))
    current = (
        await session.get(MediaAsset, garment.background_removed_asset_id)
        if garment.background_removed_asset_id is not None
        else None
    )
    if not forced and current is not None and current.kind in ALREADY_A_PACKSHOT:
        return {
            "packshot": True,
            "reason": "already_present",
            "asset_id": str(current.id),
        }

    treatment = treatment_by_id(PACKSHOT_TREATMENT)
    if treatment is None:  # pragma: no cover - a constant, guarded
        return {"packshot": False, "reason": "no_such_treatment"}

    # **Which garment, when the photograph holds several.**
    #
    # The fan-out path sends the original upload plus the name of the
    # piece to take out of it. A single-garment upload sends neither
    # and runs the treatment's own wording, which says "this exact
    # garment" and means the only one in frame.
    subject = (job.payload or {}).get("subject")
    prompt = ISOLATE.format(subject=subject) if subject else None

    try:
        photo = await store.read(asset)
        shot = await studio.shoot(
            photo=photo,
            treatment=treatment,
            content_type=asset.content_type or "image/jpeg",
            user_id=payload.user_id,
            prompt=prompt,
        )
    except CapabilityUnavailable as exc:
        # No edit capability, no credit, or the model refused. None of
        # these improve on a retry, and the garment still has its
        # cut-out and its photograph.
        logger.info(
            "packshot skipped; the existing picture stands",
            extra={"job_id": job_ref, "asset_id": asset_ref, "code": exc.code},
        )
        return {"packshot": False, "reason": exc.code}

    image = shot.data
    if not image:
        logger.info(
            "packshot returned no image; the existing picture stands",
            extra={"job_id": job_ref, "asset_id": asset_ref},
        )
        return {"packshot": False, "reason": "no_image"}

    content_type = shot.content_type or PACKSHOT_CONTENT_TYPE
    key = packshot_storage_key(asset, content_type=content_type)
    try:
        await store.write(key, image, content_type=content_type)
    except CapabilityUnavailable as exc:
        logger.info(
            "packshot could not be stored; the existing picture stands",
            extra={"job_id": job_ref, "asset_id": asset_ref, "code": exc.code},
        )
        return {"packshot": False, "reason": exc.code}

    derived = MediaAsset(
        user_id=asset.user_id,
        kind=PACKSHOT_MEDIA_KIND,
        status="ready",
        content_type=content_type,
        max_bytes=len(image),
        byte_size=len(image),
        storage_key=key,
        version=1,
        # A derivative of a private photograph. Nothing here consents
        # to publication on the owner's behalf.
        publication_consent=False,
    )
    session.add(derived)
    await session.flush()

    garment.background_removed_asset_id = derived.id
    # **Not a render, and must never be badged as one.** The flag means
    # "this is a drawing of a garment like yours". A packshot is an
    # edit of the owner's own photograph: it is their garment.
    garment.image_is_rendered = False

    logger.info(
        "packshot ready",
        extra={
            "job_id": job_ref,
            "asset_id": asset_ref,
            "packshot_asset_id": str(derived.id),
        },
    )
    return {"packshot": True, "asset_id": str(derived.id)}


__all__ = [
    "ALREADY_A_PACKSHOT",
    "AS_A_PAIR",
    "ISOLATE",
    "PACKSHOT_CONTENT_TYPE",
    "PACKSHOT_JOB_KIND",
    "PACKSHOT_MEDIA_KIND",
    "PACKSHOT_TREATMENT",
    "make_packshot",
    "packshot_storage_key",
]
