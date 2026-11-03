"""The figure clothes are shown on when somebody has no avatar.

**The bug this answers.** Eight of the last eight try-ons failed with
"Create your avatar before trying clothes on it", and the thread sat
on a spinner for every one of them. Asking somebody to build an
avatar before they can see a jacket on anything is a wall in front of
the feature they came for.

**One shared set, drawn once, reused by everybody.** The figures are
already in this repository - `scripts/generate_mannequins.py`
produced fifteen of them and shipped them as bundled client assets,
on reasoning worth repeating: a mannequin has a build and a posture
and *no face to be wrong about*, which is exactly the job. They were
never reachable from the server, which is why try-on still demanded a
personal avatar.

**Bytes, not an asset row.** The obvious implementation is a shared
`MediaAsset` owned by nobody - and `media_assets.user_id` is not
nullable, for good reason: every read in this service is scoped to an
owner, and a row with no owner is either invisible to all of them or
visible to all of them, with no third option. The renderer wants
bytes. These are bytes on disk, shipped with the service, so they are
read as bytes and the *result* is stored as that person's own asset,
exactly as a try-on against a real avatar already is.

**Nothing is inferred.** Which figure somebody gets is their own
stated choice or a neutral default - never a guess from their name,
their photograph or their clothes. That rule is the standing one
about appearance in a generated picture, and a silent fallback is
precisely where it would be easiest to break.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Where the generated figures live, shipped with the repository.
MANNEQUIN_DIR = (
    # parents[4] is the repository root: this file is at
    # services/api/app/domain/, so four levels up rather than three.
    Path(__file__).resolve().parents[4]
    / "apps"
    / "mobile"
    / "assets"
    / "images"
    / "mannequins"
)

#: What somebody may choose. The file stem is the id.
#:
#: Presentation and build, which is what the generator produced. No
#: age and no skin tone: that is the point of a mannequin.
PRESENTATIONS: tuple[str, ...] = ("feminine", "masculine", "androgynous")
BUILDS: tuple[str, ...] = ("slim", "average", "athletic", "curvy", "plus")

#: Used when somebody has expressed no preference.
#:
#: Androgynous rather than either of the other two, because a default
#: is a guess and this is the one that guesses least.
DEFAULT_FIGURE = "androgynous-average"

MANNEQUIN_CONTENT_TYPE = "image/webp"


def figure_id(presentation: str | None, build: str | None) -> str:
    """A figure name from a stated choice, falling back to the default.

    Anything unrecognised becomes the default rather than an error: a
    stale value in somebody's profile should cost them the figure
    they picked, not the feature.
    """
    shown = (presentation or "").strip().lower()
    shape = (build or "").strip().lower()
    if shown not in PRESENTATIONS or shape not in BUILDS:
        return DEFAULT_FIGURE
    return f"{shown}-{shape}"


def file_for(figure: str) -> Path | None:
    """The shipped picture for a figure, if it is there."""
    # Guarded rather than trusted: `figure` is built from a stored
    # preference, and a path separator in one would otherwise read
    # any file this process can see.
    if "/" in figure or "\\" in figure or ".." in figure:
        return None
    candidate = MANNEQUIN_DIR / f"{figure}.webp"
    return candidate if candidate.is_file() else None


def bytes_for(figure: str = DEFAULT_FIGURE) -> bytes | None:
    """The figure's pixels, or the default's, or nothing."""
    source = file_for(figure) or file_for(DEFAULT_FIGURE)
    if source is None:
        logger.warning("no mannequin file for %r and no default", figure)
        return None
    return source.read_bytes()


async def stated_figure(
    session: AsyncSession, *, user_id: uuid.UUID
) -> str:
    """The figure this person chose, or the neutral default.

    Read from their own stated preferences and nowhere else.
    """
    from app.models.preference import Preference

    rows = (
        await session.scalars(
            sa.select(Preference).where(
                Preference.user_id == user_id,
                Preference.key.in_(("avatar_presentation", "avatar_build")),
            )
        )
    ).all()
    held = {row.key: _as_text(row.value) for row in rows}
    return figure_id(held.get("avatar_presentation"), held.get("avatar_build"))


async def figure_to_dress(
    session: AsyncSession, *, user_id: uuid.UUID, store: object
) -> tuple[bytes, str] | None:
    """What to draw the clothes on: `(pixels, content type)`.

    Their own avatar when they have made one - it is a better answer
    than any mannequin, and the whole point of having made it.
    Otherwise the shared figure they chose.
    """
    from app.domain.avatar import current_avatar

    mine = await current_avatar(session, user_id=user_id)
    if mine is not None and mine.storage_key:
        try:
            return await store.read(mine), (mine.content_type or "image/png")
        except Exception as caught:  # noqa: BLE001
            # Their avatar exists and its bytes do not. A mannequin is
            # a better answer than a failure.
            logger.warning("avatar unreadable, using a mannequin: %s", caught)

    figure = await stated_figure(session, user_id=user_id)
    pixels = bytes_for(figure)
    if pixels is None:
        return None
    return pixels, MANNEQUIN_CONTENT_TYPE


def _as_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        inner = value.get("value")
        return inner if isinstance(inner, str) else None
    return None


__all__ = [
    "BUILDS",
    "DEFAULT_FIGURE",
    "MANNEQUIN_CONTENT_TYPE",
    "MANNEQUIN_DIR",
    "PRESENTATIONS",
    "bytes_for",
    "figure_id",
    "figure_to_dress",
    "file_for",
    "stated_figure",
]
