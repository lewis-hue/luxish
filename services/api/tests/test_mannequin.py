"""The figure clothes are shown on when somebody has no avatar.

Eight of the last eight try-ons failed with "Create your avatar
before trying clothes on it", and the thread spun on every one. The
figures were already in this repository and simply unreachable from
the server.

The tests that matter most are the two about inference: which figure
somebody gets must come from what they said, never from a guess, and
a fallback is exactly where that rule would be easiest to break
quietly.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.mannequin import (
    BUILDS,
    DEFAULT_FIGURE,
    MANNEQUIN_DIR,
    PRESENTATIONS,
    bytes_for,
    figure_id,
    figure_to_dress,
    file_for,
    stated_figure,
)
from tests.test_garment_media import make_user


def test_every_figure_in_the_vocabulary_has_a_picture() -> None:
    """A choice with no file behind it is a choice that silently
    falls back to somebody else's figure."""
    missing = [
        f"{shown}-{shape}"
        for shown in PRESENTATIONS
        for shape in BUILDS
        if file_for(f"{shown}-{shape}") is None
    ]
    assert missing == [], f"no picture for: {missing}"


def test_the_directory_is_where_the_generator_writes() -> None:
    """The path was wrong by one level when this was written, and
    the only symptom was a silent fallback to nothing."""
    assert MANNEQUIN_DIR.is_dir(), MANNEQUIN_DIR
    assert MANNEQUIN_DIR.name == "mannequins"


def test_the_default_is_the_one_that_guesses_least() -> None:
    assert DEFAULT_FIGURE.startswith("androgynous")
    assert bytes_for() is not None


# --------------------------------------------------------------------------- #
# Nothing is inferred
# --------------------------------------------------------------------------- #
def test_an_unstated_choice_is_the_neutral_default() -> None:
    """**Never a guess.**

    No presentation stated means the neutral figure, not a
    assumption drawn from anything else about them.
    """
    assert figure_id(None, None) == DEFAULT_FIGURE
    assert figure_id("", "") == DEFAULT_FIGURE


def test_a_stated_choice_is_honoured() -> None:
    assert figure_id("feminine", "slim") == "feminine-slim"
    assert figure_id("Masculine", "ATHLETIC") == "masculine-athletic"


def test_a_stale_value_costs_the_figure_not_the_feature() -> None:
    """Somebody's profile holding a word this version no longer
    knows should not take try-on away from them."""
    assert figure_id("robot", "average") == DEFAULT_FIGURE
    assert figure_id("feminine", "enormous") == DEFAULT_FIGURE


def test_a_figure_name_cannot_escape_the_directory() -> None:
    """**It is built from a stored preference**, so it is input.

    Without the guard this reads any file the process can see.
    """
    for nasty in ("../../../etc/passwd", r"..\..\secrets", "a/b"):
        assert file_for(nasty) is None


# --------------------------------------------------------------------------- #
# What gets dressed
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self, data: bytes | None = b"an avatar") -> None:
        self.data = data

    async def read(self, asset):
        if self.data is None:
            raise RuntimeError("gone")
        return self.data


async def test_somebody_with_no_avatar_still_gets_a_figure(
    db: AsyncSession,
) -> None:
    """**The whole point.** This used to raise and stop the feature."""
    me = await make_user(db)
    found = await figure_to_dress(db, user_id=me, store=Store())
    assert found is not None
    pixels, content_type = found
    assert len(pixels) > 1000
    assert content_type == "image/webp"


async def test_their_own_avatar_wins_over_a_mannequin(
    db: AsyncSession,
) -> None:
    """It is a better answer, and the reason they made one."""
    from app.models.media_asset import MediaAsset

    me = await make_user(db)
    db.add(
        MediaAsset(
            user_id=me,
            kind="avatar",
            status="ready",
            content_type="image/png",
            max_bytes=1,
            byte_size=1,
            storage_key=f"avatars/{uuid.uuid4().hex}",
            version=1,
        )
    )
    await db.commit()

    found = await figure_to_dress(db, user_id=me, store=Store(b"their avatar"))
    assert found == (b"their avatar", "image/png")


async def test_an_unreadable_avatar_falls_back_rather_than_failing(
    db: AsyncSession,
) -> None:
    """The row says it exists and the bytes have gone. A mannequin is
    a better answer than an error."""
    from app.models.media_asset import MediaAsset

    me = await make_user(db)
    db.add(
        MediaAsset(
            user_id=me,
            kind="avatar",
            status="ready",
            content_type="image/png",
            max_bytes=1,
            byte_size=1,
            storage_key=f"avatars/{uuid.uuid4().hex}",
            version=1,
        )
    )
    await db.commit()

    found = await figure_to_dress(db, user_id=me, store=Store(None))
    assert found is not None
    assert found[1] == "image/webp", "did not fall back to a mannequin"


async def test_a_stated_preference_picks_the_figure(
    db: AsyncSession,
) -> None:
    from app.models.preference import Preference

    me = await make_user(db)
    db.add(Preference(user_id=me, key="avatar_presentation", value="feminine"))
    db.add(Preference(user_id=me, key="avatar_build", value="athletic"))
    await db.commit()

    assert await stated_figure(db, user_id=me) == "feminine-athletic"


async def test_no_preference_is_the_default(db: AsyncSession) -> None:
    me = await make_user(db)
    assert await stated_figure(db, user_id=me) == DEFAULT_FIGURE
