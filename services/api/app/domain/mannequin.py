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
import os
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


#: Where the generated figures live, shipped with the repository.
#:
#: **Found, not counted.** This was `parents[4]`, which is the
#: repository root only when the file sits at
#: `<repo>/services/api/app/domain/`. In a container it sits at
#: `/srv/app/domain/`, which has three parents, so importing this
#: module raised `IndexError: 4` and every request to `/v1/avatar`
#: answered 500. The same counting bug had already broken six seed
#: scripts the same way.
#:
#: `LUXISH_MANNEQUIN_DIR` wins where it is set, which is how
#: docker-compose points at the mounted copy. Otherwise the
#: directory is searched for upward, and a missing one is reported
#: as an empty roster rather than an import-time crash: a figure
#: nobody can draw is a feature degraded, not a service down.
def _mannequin_dir() -> Path:
    named = os.environ.get("LUXISH_MANNEQUIN_DIR")
    if named:
        return Path(named)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "apps" / "mobile" / "assets" / "images" / "mannequins"
        if candidate.is_dir():
            return candidate
    # Nothing found. Returned rather than raised; see above.
    return here.parents[-1] / "mannequins-not-found"


MANNEQUIN_DIR = _mannequin_dir()

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


async def stated_figure(session: AsyncSession, *, user_id: uuid.UUID) -> str:
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


#: The preference that moves try-on off the mannequin.
#:
#: Absent means the mannequin, which is the point: a default has to be
#: what happens when nobody has said anything.
VEHICLE_KEY = "tryon_vehicle"

#: The only value that opts out of the mannequin.
ON_MY_AVATAR = "avatar"


async def dresses_their_avatar(session: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """Whether this person asked for try-ons on their own avatar."""
    from app.models.preference import Preference

    held = await session.scalar(
        sa.select(Preference).where(
            Preference.user_id == user_id,
            Preference.key == VEHICLE_KEY,
        )
    )
    return held is not None and _as_text(held.value) == ON_MY_AVATAR


async def choose_vehicle(session: AsyncSession, *, user_id: uuid.UUID, on_my_avatar: bool) -> None:
    """Record whether to use their likeness or the mannequin.

    Written beside `dresses_their_avatar` so the key, its values and
    both halves of the decision stay in one file.
    """
    from app.models.preference import Preference

    wanted = ON_MY_AVATAR if on_my_avatar else "mannequin"
    held = await session.scalar(
        sa.select(Preference).where(Preference.user_id == user_id, Preference.key == VEHICLE_KEY)
    )
    if held is None:
        session.add(Preference(user_id=user_id, key=VEHICLE_KEY, value=wanted))
    else:
        held.value = wanted
    await session.commit()


async def figure_to_dress(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    store: object,
    force: bool = False,
) -> tuple[bytes, str] | None:
    """What to draw the clothes on: `(pixels, content type)`.

    **The mannequin, unless they have asked for otherwise.** This used
    to prefer somebody's avatar whenever one existed, on the reasoning
    that an avatar they had built was a better answer than a shared
    figure. That is a defensible argument and it was the wrong default:
    making an avatar once, to see what it looked like, silently
    redirected every try-on thereafter onto a photorealistic likeness,
    and there was no way back to the mannequin short of deleting it.
    Reported as "the mannequin appears but the clothes are worn on the
    photorealistic avatar, which is wrong".

    So the mannequin is what a try-on uses, and the avatar is a setting
    somebody turns on (`VEHICLE_KEY`). Having built an avatar is no
    longer the same as having chosen to wear everything on it.

    **`force` ignores that setting, and only the stylist uses it.**
    An assistant's picture is an illustration of an answer - "these
    would go together" - and it belongs on a neutral figure the same
    way a catalogue does. Somebody who has switched the app onto
    their likeness has said where *they* want to be seen, which is a
    different question, and the product owner's instruction is that
    the assistant does not follow it.

    Everything else still honours the preference: the avatar screen's
    own try-on is about them, so it is drawn on whatever they chose.
    """
    from app.domain.avatar import current_avatar

    # `force` is the stylist, which draws on the mannequin whatever
    # anybody has switched on. See the note in the docstring.
    if not force and await dresses_their_avatar(session, user_id=user_id):
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
    "ON_MY_AVATAR",
    "PRESENTATIONS",
    "VEHICLE_KEY",
    "bytes_for",
    "choose_vehicle",
    "dresses_their_avatar",
    "figure_id",
    "figure_to_dress",
    "file_for",
    "stated_figure",
]
