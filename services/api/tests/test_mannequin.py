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


async def _give_them_an_avatar(db: AsyncSession, me: uuid.UUID) -> None:
    from app.models.media_asset import MediaAsset

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


async def _ask_for(db: AsyncSession, me: uuid.UUID, vehicle: str) -> None:
    from app.domain.mannequin import VEHICLE_KEY
    from app.models.preference import Preference

    db.add(Preference(user_id=me, key=VEHICLE_KEY, value=vehicle))
    await db.commit()


async def test_having_an_avatar_does_not_redirect_every_try_on_to_it(
    db: AsyncSession,
) -> None:
    """**The default is the mannequin, avatar or no avatar.**

    This asserted the opposite until 2026-11-03. Preferring an avatar
    whenever one existed meant that making one once, to see what it
    looked like, silently moved every later try-on onto a
    photorealistic likeness with no way back short of deleting it.
    """
    me = await make_user(db)
    await _give_them_an_avatar(db, me)

    found = await figure_to_dress(db, user_id=me, store=Store(b"their avatar"))
    assert found is not None
    pixels, content_type = found
    assert content_type == "image/webp", "a mannequin, not their avatar"
    assert pixels != b"their avatar"


async def test_the_avatar_is_used_when_they_have_asked_for_it(
    db: AsyncSession,
) -> None:
    """Opting in is what moves it, and nothing else."""
    from app.domain.mannequin import ON_MY_AVATAR

    me = await make_user(db)
    await _give_them_an_avatar(db, me)
    await _ask_for(db, me, ON_MY_AVATAR)

    found = await figure_to_dress(db, user_id=me, store=Store(b"their avatar"))
    assert found == (b"their avatar", "image/png")


async def test_asking_for_the_avatar_without_having_one_still_works(
    db: AsyncSession,
) -> None:
    """The preference is a wish, not a promise that a row exists."""
    from app.domain.mannequin import ON_MY_AVATAR

    me = await make_user(db)
    await _ask_for(db, me, ON_MY_AVATAR)

    found = await figure_to_dress(db, user_id=me, store=Store())
    assert found is not None
    assert found[1] == "image/webp"


async def test_an_unreadable_avatar_falls_back_rather_than_failing(
    db: AsyncSession,
) -> None:
    """The row says it exists and the bytes have gone. A mannequin is
    a better answer than an error.

    The preference is set deliberately. Without it the avatar branch
    is never entered at all, so this would pass while testing
    nothing - the mannequin would be returned because the mannequin is
    the default, not because the fallback worked.
    """
    from app.domain.mannequin import ON_MY_AVATAR

    me = await make_user(db)
    await _give_them_an_avatar(db, me)
    await _ask_for(db, me, ON_MY_AVATAR)

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


# --------------------------------------------------------------------------
# The stylist draws on the mannequin whatever anybody has switched on.
# --------------------------------------------------------------------------


async def test_the_stylist_ignores_a_chosen_likeness(db: AsyncSession) -> None:
    """**Asked for by the product owner: "let the assistant always use
    the mannequin".**

    An assistant's picture illustrates an answer - "these would go
    together" - and belongs on a neutral figure the way a catalogue
    does. Switching the app onto your likeness says where *you* want
    to be seen, which is a different question.

    The decisive part is that this account *has* opted in, and the
    reader is rigged to fail the test if the avatar is touched.
    """
    from app.domain.mannequin import (
        MANNEQUIN_CONTENT_TYPE,
        choose_vehicle,
    )

    user_id = await make_user(db)
    await _give_them_an_avatar(db, user_id)
    await choose_vehicle(db, user_id=user_id, on_my_avatar=True)

    # **Recorded, not raised.** `figure_to_dress` catches `Exception`
    # when an avatar cannot be read and falls back to the mannequin,
    # so a stub that raises makes this test pass whether `force`
    # works or not. It did, until the revert check caught it.
    read_attempts: list[object] = []

    class Watching:
        async def read(self, asset):
            read_attempts.append(asset)
            return b"their-likeness"

    forced = await figure_to_dress(db, user_id=user_id, store=Watching(), force=True)

    assert read_attempts == [], "the stylist read their likeness"

    assert forced is not None
    pixels, content_type = forced
    assert content_type == MANNEQUIN_CONTENT_TYPE
    assert pixels == bytes_for(await stated_figure(db, user_id=user_id))


async def test_without_force_a_chosen_likeness_is_still_honoured(
    db: AsyncSession,
) -> None:
    """The avatar screen's own try-on is about them, so it follows them.

    Guards against `force` quietly becoming the only behaviour, which
    would make the vehicle setting dead and the toggle a lie.
    """
    from app.domain.mannequin import choose_vehicle

    user_id = await make_user(db)
    await _give_them_an_avatar(db, user_id)
    await choose_vehicle(db, user_id=user_id, on_my_avatar=True)

    class Theirs:
        async def read(self, asset):
            return b"their-likeness"

    found = await figure_to_dress(db, user_id=user_id, store=Theirs())

    assert found is not None
    assert found[0] == b"their-likeness"


async def test_the_stylist_asks_for_the_mannequin_in_the_job(
    db: AsyncSession,
) -> None:
    """The flag has to reach the worker, which is where drawing happens.

    `figure_to_dress` taking `force` is no use if nothing sets it, and
    the path from the stylist to the worker runs through a job payload
    rather than the render row.
    """
    from app.domain import avatar_renders, stylist_ask
    from app.domain.stylist_answer import Verdict, plan_from
    from app.models.garment import Garment
    from app.models.job import Job

    user_id = await make_user(db)
    tee = Garment(user_id=user_id, name="white tee", category="top", availability="available")
    db.add(tee)
    await db.commit()
    await db.refresh(tee)

    # Through `_draw`, which is what the stylist actually calls. The
    # first version of this called `request` directly with the flag
    # already set, so it passed with the stylist not setting it.
    render_id = await stylist_ask._draw(
        db,
        user_id=user_id,
        plan=plan_from(Verdict(answer="Wear it.", has_match=True, using=(tee.id,), missing=())),
        post_id=None,
    )
    assert render_id is not None, "the stylist queued nothing to assert about"

    render = await avatar_renders.get(db, user_id=user_id, render_id=render_id)
    assert render is not None
    job = await db.get(Job, render.job_id)
    assert job is not None
    assert (job.payload or {}).get("on_mannequin") is True


async def test_an_ordinary_try_on_does_not_pin_the_figure(
    db: AsyncSession,
) -> None:
    """Absent rather than false, so the payload says only what it means."""
    from app.domain import avatar_renders
    from app.models.job import Job

    user_id = await make_user(db)
    render = await avatar_renders.request(
        db, user_id=user_id, kind="try_on", outfit="a navy blazer"
    )

    job = await db.get(Job, render.job_id)
    assert job is not None
    assert "on_mannequin" not in (job.payload or {})
