"""Cutting the garments out of a posted fit, one packshot each.

**Why this exists, and why it is not the try-on that already works.**
Trying a fit on reads the photograph, writes a sentence describing
the clothes, and pays an image model to draw somebody wearing that
sentence. The result looks *like* the outfit. It is not the outfit:
the model is reconstructing from a description, so a logo moves, a
pattern becomes a different pattern, a jacket gains a pocket.

What somebody means by "try it on" is the clothes in the picture.
So each garment is cut out of the photograph it is actually in and
kept as a packshot, and the free stylised figure wears those
cut-outs directly. Nothing is reconstructed, because nothing is
redrawn. The photoreal render stays exactly where it was, as the
paid thing somebody asks for when they want it.

**Computed once per post, for everybody.** It rides with the
description, which is already shared: the first person to open a fit
pays the reading, and the hundredth pays nothing. Cutting per viewer
would multiply a fixed cost by an audience.

**It never fails the description.** The sentence is the result and
these are an improvement on it, so a segmenter that is down or out
of quota costs the cut-outs and leaves the fit described, captioned
and tryable the old way.
"""

from __future__ import annotations

import uuid
from typing import Any

#: The kind a cut piece is stored under.
#:
#: `outfit_photo`, deliberately, and not `garment_photo`. A media
#: kind is a boundary: `garment_photo` means evidence of something
#: somebody owns, and a piece cut from a stranger's post is nothing
#: of the sort. Filing it as one would let it through every path
#: that scans a person's own clothes.
PIECE_MEDIA_KIND = "outfit_photo"


def piece_prompt(piece: dict[str, Any]) -> str:
    """What to ask the segmenter to find, from a described piece.

    Colour first, then the garment, because that is the order the
    describing model writes them in and the order that disambiguates
    fastest when a photograph holds two of the same thing - "the
    black boots" against "the boots", when there is also a bag.
    """
    colour = str(piece.get("colour") or "").strip()
    name = str(piece.get("name") or piece.get("category") or "").strip()
    return f"{colour} {name}".strip() or "the garment"


async def cut_pieces(
    session: Any,
    *,
    post_id: uuid.UUID,
    segmenter: Any,
    store: Any,
    job_id: uuid.UUID | None = None,
) -> int:
    """Cut each described piece out of the fit's photograph. Returns how many.

    Each cut-out gets a `FitPieceRow`, not an id in the
    description's JSON. Media readability here is decided by a live
    join, so an id that cannot be joined is an id the gate cannot
    check - see the revision that added the table.
    """
    import logging

    import sqlalchemy as sa

    from app.domain import fit_descriptions
    from app.models.fit_description import FitDescriptionRow, FitPieceRow
    from app.models.media_asset import MediaAsset
    from app.providers.segmentation import (
        CUTOUT_BACKGROUND,
        CUTOUT_CONTENT_TYPE,
        SegmentationUnavailable,
    )
    from app.workers.outfit import crop_to_subject
    from app.workers.shell_fit import fit_to_shell, measure

    logger = logging.getLogger(__name__)

    row = await session.scalar(
        sa.select(FitDescriptionRow).where(FitDescriptionRow.post_id == post_id)
    )
    if row is None or not row.pieces:
        return 0
    # Already cut. A re-dispatched job must not pay twice.
    done = await session.scalar(
        sa.select(sa.func.count())
        .select_from(FitPieceRow)
        .where(FitPieceRow.post_id == post_id)
    )
    if done:
        return 0

    asset = await fit_descriptions.photograph(session, post_id=post_id)
    if asset is None or not asset.storage_key:
        return 0
    try:
        image = await store.read(asset)
    except Exception:  # noqa: BLE001 - no photograph is not a failure
        return 0

    cut = 0
    for position, piece in enumerate(row.pieces):
        entry = dict(piece)
        try:
            result = await segmenter.cutout(
                image=image,
                prompt=piece_prompt(entry),
                content_type=asset.content_type or CUTOUT_CONTENT_TYPE,
                background=CUTOUT_BACKGROUND,
                user_id=asset.user_id,
                job_id=job_id,
            )
        except (SegmentationUnavailable, Exception) as caught:  # noqa: BLE001
            # Deliberately broad, and the narrow class is named first
            # so the intent is legible: one piece that will not cut
            # costs that piece. A bag half behind a hip is the normal
            # case here, not a failure.
            logger.debug(
                "a piece would not cut",
                extra={"post": str(post_id), "reason": type(caught).__name__},
            )
            continue
        if result is None or result.image is None:
            continue

        shaped = fit_to_shell(
            crop_to_subject(result.image, result.records),
            content_type=CUTOUT_CONTENT_TYPE,
            portrait=True,
        )
        size = measure(shaped)
        key = f"posts/{post_id}/pieces/{uuid.uuid4().hex[:12]}.png"
        try:
            await store.write(key, shaped, content_type=CUTOUT_CONTENT_TYPE)
        except Exception:  # noqa: BLE001
            continue

        derived = MediaAsset(
            # The post's author, because it is cut from their
            # photograph. Readability is decided by the fit being
            # published, exactly as the cover is - not by who asked.
            user_id=asset.user_id,
            kind=PIECE_MEDIA_KIND,
            status="ready",
            content_type=CUTOUT_CONTENT_TYPE,
            width=size[0] if size else None,
            height=size[1] if size else None,
            max_bytes=len(shaped),
            byte_size=len(shaped),
            storage_key=key,
            version=1,
            # Carried by the post being published, like the cover.
            publication_consent=True,
        )
        session.add(derived)
        await session.flush()

        session.add(
            FitPieceRow(
                post_id=post_id,
                media_asset_id=derived.id,
                position=position,
                name=str(entry.get("name") or "")[:120] or None,
                colour=str(entry.get("colour") or "")[:60] or None,
                category=str(entry.get("category") or "")[:60] or None,
            )
        )
        cut += 1

    if cut:
        await session.commit()
        logger.info("cut pieces from a fit", extra={"post": str(post_id), "cut": cut})
    return cut


__all__ = ["PIECE_MEDIA_KIND", "cut_pieces", "piece_prompt"]
