"""Requesting a studio shot, and keeping what comes back.

**The garment id is re-validated against the caller's own wardrobe before
anything is read or written.** An id from a client is a claim, and this one
would otherwise be a way to read somebody else's photograph through a
generation call. Not yours is a 404, never a 403, so a refusal confirms
nothing about what exists.

**A shot is requested, not awaited.** An image edit is a billed call that
takes the better part of a minute; like every other paid call here it runs
on a worker and the handler answers with a queued row (ADR-005, ADR-013).

**Results are their own assets, never a replacement.** A studio shot is a
derivative of a photograph the owner took. Overwriting the original would
make the treatment irreversible and would quietly change what the
categoriser and the stylist see, so the garment keeps pointing at its real
photograph and the shots hang off it.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import enqueue
from app.models.garment import Garment
from app.models.garment_studio import GarmentShot
from app.models.media_asset import MediaAsset
from app.workers.brand_studio import clean_brief
from app.workers.shell_fit import fit_to_shell, measure
from app.workers.garment_studio import (
    STUDIO_MEDIA_KIND,
    GarmentStudio,
    Treatment,
    treatment_by_id,
    with_brief,
)

#: Routed to the AI queue by prefix, like every other paid call.
SHOT_JOB_KIND = "garment.studio"

#: Splitting one photograph into a packshot per garment in it.
#:
#: A separate kind because it is a different shape of work: the job
#: above edits one picture into one picture, where this one looks at a
#: picture, finds the garments in it, and asks for a shot of each. It
#: cannot be a flag on the first without that handler having two
#: unrelated bodies.
SPLIT_JOB_KIND = "garment.studio_split"

#: Treatments that photograph garments lying flat.
#:
#: These are the two that come back landscape, because laying a shirt
#: next to a pair of trousers is a wide arrangement. Their output is
#: brought upright; everything else is left at whatever shape it
#: arrived in, inside the shell's own bounds.
LAID_OUT_FLAT: frozenset[str] = frozenset({"packshot", "cutout"})


class NotYourGarment(Exception):
    """The id is not a live garment belonging to this user."""


class NoPhotograph(Exception):
    """The garment has no usable photograph to work from."""


async def owned(
    session: AsyncSession, *, user_id: uuid.UUID, garment_id: uuid.UUID
) -> Garment:
    garment = await session.scalar(
        sa.select(Garment).where(
            Garment.id == garment_id,
            Garment.user_id == user_id,
            Garment.deleted_at.is_(None),
        )
    )
    if garment is None:
        raise NotYourGarment()
    return garment


async def owned_asset(
    session: AsyncSession, *, user_id: uuid.UUID, asset_id: uuid.UUID
) -> MediaAsset:
    """A photograph this caller owns and which can actually be read.

    Ownership is re-checked here rather than trusted from the request: an
    asset id from a client is a claim, and this one would otherwise be a
    way to read somebody else's photograph through a generation call and
    bill it to them.
    """
    asset = await session.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.user_id == user_id,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status.in_(("uploaded", "ready")),
        )
    )
    if asset is None or not asset.storage_key:
        raise NoPhotograph()
    return asset


async def resolve_source(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    garment_id: uuid.UUID | None,
    asset_id: uuid.UUID | None,
) -> tuple[MediaAsset, uuid.UUID | None]:
    """The photograph to edit, and the garment it came from if any.

    Exactly one of the two is expected. A garment is resolved to the
    photograph its owner took — never to a previous shot, because
    treatments compounding on each other would drift away from the real
    garment one generation at a time.
    """
    if asset_id is not None:
        return await owned_asset(session, user_id=user_id, asset_id=asset_id), None
    if garment_id is None:
        raise NoPhotograph()
    garment = await owned(session, user_id=user_id, garment_id=garment_id)
    if garment.media_asset_id is None:
        raise NoPhotograph()
    asset = await owned_asset(
        session, user_id=user_id, asset_id=garment.media_asset_id
    )
    return asset, garment.id


async def shots_for(
    session: AsyncSession, *, user_id: uuid.UUID, garment_id: uuid.UUID
) -> list[GarmentShot]:
    """Every shot of this garment, newest first, whatever state it is in."""
    await owned(session, user_id=user_id, garment_id=garment_id)
    rows = await session.scalars(
        sa.select(GarmentShot)
        .where(GarmentShot.garment_id == garment_id, GarmentShot.deleted_at.is_(None))
        .order_by(GarmentShot.created_at.desc())
    )
    return list(rows)


async def recent(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 30
) -> list[GarmentShot]:
    """Everything this person has shot, newest first.

    The stylist's view: shots taken there are often of a photograph with
    no wardrobe row, so there is no garment to group them under.
    """
    rows = await session.scalars(
        sa.select(GarmentShot)
        .where(GarmentShot.user_id == user_id, GarmentShot.deleted_at.is_(None))
        .order_by(GarmentShot.created_at.desc())
        .limit(limit)
    )
    return list(rows)


async def get(
    session: AsyncSession, *, user_id: uuid.UUID, shot_id: uuid.UUID
) -> GarmentShot | None:
    return await session.scalar(
        sa.select(GarmentShot).where(
            GarmentShot.id == shot_id,
            GarmentShot.user_id == user_id,
            GarmentShot.deleted_at.is_(None),
        )
    )


async def in_flight(
    session: AsyncSession,
    *,
    source_asset_id: uuid.UUID,
    treatment: str,
    brief: str | None = None,
) -> GarmentShot | None:
    """The same request already running, if there is one.

    **The brief is part of what "the same" means.** Two different
    directions on one photograph are two different pictures, and
    matching on the photograph and treatment alone would hand somebody
    the answer to the question they asked a minute ago.
    """
    return await session.scalar(
        sa.select(GarmentShot).where(
            GarmentShot.source_asset_id == source_asset_id,
            GarmentShot.treatment == treatment,
            GarmentShot.brief.is_(None) if brief is None else GarmentShot.brief == brief,
            GarmentShot.state.in_(("queued", "running")),
            GarmentShot.deleted_at.is_(None),
        )
    )


async def request(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    treatment: Treatment,
    garment_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    #: The person's own direction, in their words. Optional: a
    #: treatment on its own is a complete request.
    brief: str | None = None,
    landscape: bool = False,
) -> GarmentShot:
    """Record the request and queue the work. Returns immediately.

    Returns the shot already in flight rather than starting a second one:
    two pictures of the same treatment on the same photograph is two
    billed calls, and one of them is discarded before anybody sees it.
    The brief counts towards sameness - a different direction is a
    different picture.
    """
    asset, resolved_garment = await resolve_source(
        session, user_id=user_id, garment_id=garment_id, asset_id=asset_id
    )

    direction = clean_brief(brief) or None

    existing = await in_flight(
        session,
        source_asset_id=asset.id,
        treatment=treatment.id,
        brief=direction,
    )
    if existing is not None:
        return existing

    shot = GarmentShot(
        user_id=user_id,
        source_asset_id=asset.id,
        garment_id=resolved_garment,
        treatment=treatment.id,
        brief=direction,
        landscape=landscape,
        # Composed now rather than at run time, so the row records the
        # exact wording this picture was asked for with - including
        # where in it somebody's own direction landed.
        prompt=with_brief(treatment, direction) if direction else None,
        state="queued",
    )
    session.add(shot)
    await session.flush()

    job = await enqueue(
        session,
        SHOT_JOB_KIND,
        {"shot_id": str(shot.id), "user_id": str(user_id)},
        # Keyed on the shot, so a retried request rides the same job rather
        # than paying for a second picture.
        idempotency_key=f"{SHOT_JOB_KIND}:{shot.id}",
    )
    shot.job_id = job.id
    await session.commit()
    await session.refresh(shot)
    return shot


async def request_each(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    treatment: Treatment,
    garment_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    brief: str | None = None,
) -> uuid.UUID:
    """One picture per garment in the photograph. Returns the job id.

    **The studio groups by default and this is the exception**, on the
    product owner's instruction (2026-11-02). A studio shot is one
    picture: hand it a photograph of a shirt and trousers and the
    packshot it returns has both, laid out together, which is what
    somebody making one image wants. This is for the other case - the
    same photograph wanted as two catalogue images, one per garment.

    **Nothing is returned to poll but the job.** How many pictures
    there will be is not known here: the answer is however many
    garments a vision call finds, and deciding what a photograph
    contains is a model call, so it belongs on a worker and never in
    a handler (ADR-013). The shots appear in the studio's own list as
    the worker creates them, which is where somebody is already
    looking.
    """
    asset, resolved_garment = await resolve_source(
        session, user_id=user_id, garment_id=garment_id, asset_id=asset_id
    )
    job = await enqueue(
        session,
        SPLIT_JOB_KIND,
        {
            "asset_id": str(asset.id),
            "asset_version": asset.version,
            "garment_id": str(resolved_garment) if resolved_garment else None,
            "user_id": str(user_id),
            "treatment": treatment.id,
            "brief": clean_brief(brief) or None,
        },
        # Keyed on the photograph and the treatment, so a double tap
        # rides the same job rather than paying for every garment
        # twice.
        idempotency_key=f"{SPLIT_JOB_KIND}:{asset.id}:{treatment.id}",
    )
    await session.commit()
    return job.id

async def mark_running(session: AsyncSession, *, shot: GarmentShot) -> None:
    shot.state = "running"
    await session.commit()


async def mark_failed(session: AsyncSession, *, shot: GarmentShot, error: str) -> None:
    shot.state = "failed"
    shot.error = error[:300]
    await session.commit()


async def take(
    session: AsyncSession,
    *,
    shot: GarmentShot,
    studio: GarmentStudio,
    store: Any,
) -> GarmentShot:
    """Run the treatment over the garment's own photograph.

    The source read is the garment's `media_asset_id` — the photograph the
    owner took — and never a previous shot. Treatments compounding on each
    other would drift away from the real garment one generation at a time,
    which is the whole thing this feature exists not to do.
    """
    # A brand frame names a scene rather than one of the four treatments,
    # and carries the exact wording to run. Either way there has to be a
    # prompt: a shot with neither is a row that cannot be executed.
    treatment = treatment_by_id(shot.treatment)
    if treatment is None:
        if not shot.prompt:
            raise NoPhotograph()
        treatment = Treatment(id=shot.treatment, label=shot.treatment)

    # The stored source, re-read rather than trusted: the photograph may
    # have been deleted between the request and the run.
    source = await session.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == shot.source_asset_id,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status.in_(("uploaded", "ready")),
        )
    )
    if source is None or not source.storage_key:
        raise NoPhotograph()

    data = await store.read(source)
    result = await studio.shoot(
        photo=data,
        treatment=treatment,
        content_type=source.content_type or "image/jpeg",
        user_id=shot.user_id,
        # Set for a brand frame, null for a studio treatment.
        prompt=shot.prompt,
    )

    # **Brought to the shape the app draws it in, here.**
    #
    # An edit returns the shape it was handed, so a full-length figure
    # photographed on a phone at about 0.47 comes back at 0.47 - taller
    # than the shell, which then crops it. Cropping a full-length
    # fashion photograph takes the shoes, and the reshaping is visible
    # on the way in as the card settles from one guess to another.
    #
    # Settled once, at the only point where the bytes can be fixed
    # rather than worked around. Widened rather than cropped, so
    # nothing of the garment is lost; see `workers/shell_fit`.
    # Upright for the two that lay garments out flat. A packshot of a
    # shirt beside a pair of trousers is naturally landscape and was
    # the only card in the feed lying on its side; a model shot or a
    # scene already comes back upright, and forcing those would pad a
    # picture that needs nothing.
    shaped = fit_to_shell(
        result.data,
        content_type=result.content_type,
        # Upright unless this shot was asked for wide.
        portrait=treatment.id in LAID_OUT_FLAT and not shot.landscape,
    )

    # **Recorded, because every studio asset was stored without them.**
    # A tile is laid out from the stored width and height before any
    # bytes arrive. With none, the app guesses, then re-lays the
    # column out the moment the picture decodes - which is the
    # movement generated pictures showed and photographs did not.
    size = measure(shaped)

    asset = MediaAsset(
        user_id=shot.user_id,
        kind=STUDIO_MEDIA_KIND,
        status="processing",
        content_type=result.content_type,
        width=size[0] if size else None,
        height=size[1] if size else None,
        max_bytes=len(shaped),
        byte_size=len(shaped),
        version=1,
        # A studio shot is not published by making it. Sharing one is a
        # separate decision, taken on the screen that shares it.
        publication_consent=False,
    )
    session.add(asset)
    await session.flush()

    key = f"users/{shot.user_id}/garment-studio/{asset.id}"
    await store.write(key, shaped, content_type=result.content_type)
    asset.storage_key = key
    asset.checksum_sha256 = hashlib.sha256(shaped).hexdigest()
    asset.status = "ready"

    shot.media_asset_id = asset.id
    shot.state = "ready"
    shot.error = None
    await session.commit()
    await session.refresh(shot)

    # Worth a banner precisely because nobody is watching: a shot
    # takes long enough that people leave the screen, and the whole
    # point of a notification is the thing that finished while you
    # were elsewhere.
    from app.domain import push

    await push.notify(
        session,
        user_id=shot.user_id,
        kind="studio_ready",
        title="Your picture is ready",
        body="The studio finished it.",
        subject=str(shot.id),
        deep_link="/studio",
    )
    return shot


async def discard(
    session: AsyncSession, *, user_id: uuid.UUID, shot_id: uuid.UUID
) -> bool:
    """Throw a shot away. Tombstoned, like every other deletion here."""
    shot = await get(session, user_id=user_id, shot_id=shot_id)
    if shot is None:
        return False
    shot.deleted_at = sa.func.now()
    if shot.media_asset_id is not None:
        asset = await session.get(MediaAsset, shot.media_asset_id)
        if asset is not None and asset.user_id == user_id:
            asset.deleted_at = sa.func.now()
    await session.commit()
    return True


__all__ = [
    "SHOT_JOB_KIND",
    "SPLIT_JOB_KIND",
    "request_each",
    "NoPhotograph",
    "NotYourGarment",
    "discard",
    "get",
    "in_flight",
    "mark_failed",
    "mark_running",
    "owned",
    "owned_asset",
    "recent",
    "request",
    "resolve_source",
    "shots_for",
    "take",
]
