"""Draw a garment from its words, once, for everybody who asks for it.

**The reported failure.** "How would baggy skater shorts with white
sneakers and a white t-shirt look on me?" came back as: you do not own
those, here is where to buy them - and nothing to look at. The figure
beside every other answer is composed from cut-outs, and a cut-out
only exists for a garment somebody has photographed, so the one reply
where seeing it would help most was the one reply with no picture.

This fills that in. Each named piece becomes a plain packshot on a
white ground, which is exactly the shape the composite already lays
over the figure - the same treatment a wardrobe garment gets, run
from words instead of from a photograph.

**Once, globally.** The row is keyed on the normalised phrase, not on
a person, so the first ask pays and every ask after it is a lookup.
That is what makes this affordable where a photoreal try-on was not:
"white sneakers" is drawn one time in the life of the product.

**A generic garment, never a product.** The prompt asks for the kind
of thing named and nothing else - no brand, no logo, no graphic - so
the picture cannot read as a photograph of an item in the shop links
beside it. The client labels it as an illustration.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CapabilityUnavailable
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.models.piece_packshot import PiecePackshot
from app.providers.base import AIRequest, GeneratedImage
from app.workers.categorise import MediaStore, UnavailableMediaStore
from app.workers.packshot import AS_A_PAIR, PACKSHOT_MEDIA_KIND

logger = logging.getLogger(__name__)

PIECE_PACKSHOT_JOB_KIND = "garment.piece_packshot"

PIECE_PACKSHOT_PURPOSE = "garment.piece_packshot"

#: Bumped when the wording below changes, so a stored picture says
#: which prompt produced it.
PIECE_PACKSHOT_PROMPT_VERSION = 1

#: The same image model the wardrobe packshot and the avatar use.
PIECE_PACKSHOT_MODEL = "muse-image-1.0"

#: What to draw.
#:
#: **Every clause here is load-bearing for the composite**, which
#: lays this picture into a fixed box over a flat figure:
#:
#: * *one garment, alone* - a model asked for "white sneakers" will
#:   happily return a person wearing them, and a person laid over a
#:   figure is two people;
#: * *pure white, no shadow, no surface* - the composite has no way
#:   to key out a background, so anything that is not the garment is
#:   drawn as part of the garment;
#: * *squared, centred, filling the frame* - the slot it lands in is
#:   a fixed rectangle, so a garment photographed small sits as a
#:   postage stamp on the figure's chest;
#: * *no brand, no logo, no graphic, no text* - this is a picture of
#:   a kind of garment standing next to links to shops, and anything
#:   that reads as a label would be a claim about a product.
PIECE_PROMPT = (
    "A flat catalogue packshot of one single garment: {phrase}. "
    "The garment alone, laid out neatly and squared to the camera, "
    "shot from directly above, centred and filling the frame with a "
    "small even margin. Nothing else in the picture: no person, no "
    "model, no hands, no hanger, no props, no other clothing. "
    "Plain pure white background with no shadow and no visible "
    "surface. No brand marks, no logos, no printed graphics and no "
    "text of any kind. "
    "Natural fabric texture and the soft creases a real garment has, "
    "evenly lit, true colour, photographed rather than illustrated. "
    # A pair is one wardrobe item and two objects, and the model does
    # not assume it: asked for "white chunky sneakers" it returned a
    # single sneaker. Nobody owns one sneaker.
    + AS_A_PAIR
)

#: Where each kind of thing sits on the figure.
#:
#: Matched on words because that is all there is - the phrase came
#: from a language model naming a gap, not from a categorised row.
#: Ordered longest-first within each slot so "shirt dress" is a dress
#: before "shirt" can claim it.
_SLOT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "outerwear",
        (
            "overcoat", "trench", "parka", "puffer", "raincoat", "windbreaker",
            "blazer", "bomber", "coat", "jacket", "cardigan", "gilet", "vest",
        ),
    ),
    (
        "shoes",
        (
            "sneakers", "trainers", "loafers", "brogues", "sandals", "heels",
            "boots", "mules", "clogs", "shoes", "pumps", "flats",
        ),
    ),
    (
        "bottoms",
        (
            "trousers", "jeans", "chinos", "shorts", "skirt", "joggers",
            "leggings", "slacks", "culottes", "cargos", "pants",
        ),
    ),
    (
        "accessories",
        (
            "necklace", "bracelet", "earrings", "ring", "scarf", "belt", "bag",
            "tote", "hat", "cap", "beanie", "sunglasses", "watch", "socks",
            "gloves", "tie",
        ),
    ),
    (
        "tops",
        (
            "dress", "jumpsuit", "t-shirt", "tshirt", "tee", "shirt", "blouse",
            "sweater", "jumper", "knit", "hoodie", "sweatshirt", "top", "polo",
            "tank", "vest top",
        ),
    ),
)


def slot_for_phrase(phrase: str) -> str | None:
    """Which part of the figure this garment goes on.

    `None` when the words name nothing recognisable, and the caller
    draws nothing rather than guessing: a bag rendered across the
    torso is worse than a bag not rendered.
    """
    words = f" {(phrase or '').lower()} "
    for slot, terms in _SLOT_WORDS:
        if any(f" {term} " in words or words.strip().endswith(term) for term in terms):
            return slot
    return None


class PieceArtist:
    """Draws one garment from its words."""

    def __init__(self, provider: object, *, model: str = PIECE_PACKSHOT_MODEL) -> None:
        self._provider = provider
        self._model = model

    async def draw(self, phrase: str, *, user_id: uuid.UUID | None = None) -> GeneratedImage:
        generate = getattr(self._provider, "generate_image", None)
        if generate is None:
            raise CapabilityUnavailable(
                "This provider cannot generate images.",
                detail={"capability": "image_generate"},
            )
        response = await generate(
            AIRequest(
                prompt=PIECE_PROMPT.format(phrase=phrase),
                model=self._model,
                purpose=PIECE_PACKSHOT_PURPOSE,
                prompt_version=PIECE_PACKSHOT_PROMPT_VERSION,
            ),
            user_id=user_id,
        )
        if not response.image_data:
            raise CapabilityUnavailable(
                f"{self._model} returned no image data.",
                detail={"capability": "image_generate", "model": self._model},
            )
        return response.image_data[0]


def piece_storage_key(row: PiecePackshot, *, content_type: str) -> str:
    """Keyed by the row, not by a user: the picture belongs to everybody."""
    suffix = "png" if "png" in content_type else "webp"
    return f"pieces/{row.id}.{suffix}"


async def draw_piece(
    session: AsyncSession,
    job: Job,
    *,
    artist: PieceArtist,
    store: MediaStore | None = None,
) -> dict[str, Any]:
    """Draw one phrase and attach the picture to its row."""
    store = store or UnavailableMediaStore()
    payload = job.payload or {}
    row_id = payload.get("packshot_id")
    if row_id is None:
        return {"drawn": False, "reason": "no_packshot_id"}

    row = await session.get(PiecePackshot, uuid.UUID(str(row_id)))
    if row is None:
        return {"drawn": False, "reason": "row_deleted"}
    if row.state == "ready" and row.media_asset_id is not None:
        # The key is unique, so two people asking at once share one
        # row; this covers a retry after a partial failure.
        return {"drawn": True, "reason": "already_present"}

    owner = payload.get("user_id")
    try:
        shot = await artist.draw(
            row.phrase, user_id=uuid.UUID(str(owner)) if owner else None
        )
    except CapabilityUnavailable as exc:
        row.state = "failed"
        row.error = str(exc)[:300]
        logger.info(
            "piece packshot could not be drawn",
            extra={"phrase": row.phrase, "code": exc.code},
        )
        return {"drawn": False, "reason": exc.code}

    content_type = shot.content_type or "image/webp"
    key = piece_storage_key(row, content_type=content_type)
    try:
        await store.write(key, shot.data, content_type=content_type)
    except CapabilityUnavailable as exc:
        row.state = "failed"
        row.error = str(exc)[:300]
        return {"drawn": False, "reason": exc.code}

    asset = MediaAsset(
        # **Owned by whoever triggered it, read by everybody.**
        #
        # `media_assets.user_id` is not nullable, so the row needs an
        # owner. The *authorisation* for this picture is not
        # ownership though - it is that it depicts nothing personal:
        # a generic garment on white, drawn from three words. The
        # route that serves it says so rather than checking the id.
        user_id=uuid.UUID(str(owner)) if owner else row.id,
        kind=PACKSHOT_MEDIA_KIND,
        status="ready",
        content_type=content_type,
        max_bytes=len(shot.data),
        byte_size=len(shot.data),
        storage_key=key,
        version=1,
        publication_consent=False,
    )
    session.add(asset)
    await session.flush()

    row.media_asset_id = asset.id
    row.state = "ready"
    row.error = None
    logger.info(
        "piece packshot ready",
        extra={"phrase": row.phrase, "asset_id": str(asset.id)},
    )
    return {"drawn": True, "asset_id": str(asset.id)}


async def ensure(
    session: AsyncSession, *, phrases: list[str], user_id: uuid.UUID
) -> list[PiecePackshot]:
    """Rows for these phrases, drawing the ones nobody has drawn yet.

    Returns a row per recognisable phrase, in the order asked. A
    phrase that names no part of the figure is skipped: there is
    nowhere to put it, and a picture with no slot is spend for
    nothing.
    """
    from app.domain.jobs import enqueue
    from app.models.piece_packshot import phrase_key

    out: list[PiecePackshot] = []
    for words in phrases:
        key = phrase_key(words)
        if not key:
            continue
        slot = slot_for_phrase(key)
        if slot is None:
            continue

        row = await session.scalar(
            sa.select(PiecePackshot).where(PiecePackshot.phrase == key)
        )
        if row is None:
            row = PiecePackshot(phrase=key, slot=slot, state="queued")
            session.add(row)
            try:
                await session.flush()
            except sa.exc.IntegrityError:
                # Two people asked for the same garment at the same
                # moment. The unique index is the arbiter; take theirs.
                await session.rollback()
                row = await session.scalar(
                    sa.select(PiecePackshot).where(PiecePackshot.phrase == key)
                )
                if row is None:  # pragma: no cover - lost both ways
                    continue
                out.append(row)
                continue

            await enqueue(
                session,
                PIECE_PACKSHOT_JOB_KIND,
                {"packshot_id": str(row.id), "user_id": str(user_id)},
                # One drawing per garment, ever - including across a
                # retried request.
                idempotency_key=f"{PIECE_PACKSHOT_JOB_KIND}:{row.id}",
            )
        out.append(row)
    return out


__all__ = [
    "PIECE_PACKSHOT_JOB_KIND",
    "PIECE_PACKSHOT_MODEL",
    "PIECE_PACKSHOT_PROMPT_VERSION",
    "PIECE_PROMPT",
    "PieceArtist",
    "draw_piece",
    "ensure",
    "piece_storage_key",
    "slot_for_phrase",
]
