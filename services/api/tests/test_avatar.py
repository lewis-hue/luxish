"""The avatar, and the rule that keeps it honest.

A feature that shows somebody how they would look in an outfit has to know
something about how they look. The only safe way to get that is to ask: every
other prompt in this service forbids reading identity off clothing, and a
model whose inputs force it to guess presentation from a wardrobe cannot
honour that rule at inference time.

So the tests that matter here are not about image quality. They are about
where the appearance comes from, what the stored picture is labelled, and
whether a try-on can reach somebody else's avatar.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import avatar as domain
from app.providers.base import GeneratedImage
from app.workers.avatar import (
    Appearance,
    UnknownAppearance,
    avatar_prompt,
    try_on_prompt,
)


class StubRenderer:
    """Records what it was asked for, returns a byte string."""

    def __init__(self) -> None:
        self.generated: list[Appearance] = []
        self.tried: list[tuple[bytes, str]] = []

    async def generate(self, *, appearance: Appearance, **_: Any) -> GeneratedImage:
        self.generated.append(appearance)
        return GeneratedImage(data=b"RIFFavatar", content_type="image/webp")

    async def try_on(self, *, avatar: bytes, outfit: str, **_: Any) -> GeneratedImage:
        self.tried.append((avatar, outfit))
        return GeneratedImage(data=b"RIFFdressed", content_type="image/webp")


async def _user(db: AsyncSession) -> uuid.UUID:
    from app.models import User

    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@example.test")
    db.add(user)
    await db.commit()
    return user.id


# --------------------------------------------------------------------------- #
# appearance is stated, never derived
# --------------------------------------------------------------------------- #
async def test_an_unanswered_appearance_still_draws_someone(
    db: AsyncSession,
) -> None:
    """Every field is optional, and the prompt simply omits what was not said.

    Describing somebody as "of unspecified build" would put the gap in the
    picture.
    """
    user_id = await _user(db)
    appearance = await domain.read_appearance(db, user_id=user_id)

    assert appearance == Appearance()
    assert appearance.describe() == "a person"
    assert "unspecified" not in avatar_prompt(appearance)


async def test_what_was_said_reaches_the_prompt(db: AsyncSession) -> None:
    user_id = await _user(db)
    await domain.write_appearance(
        db,
        user_id=user_id,
        appearance=Appearance(
            presentation="feminine",
            body_type="curvy",
            age_band="40s",
            skin_tone="dark_brown",
        ),
    )

    described = (await domain.read_appearance(db, user_id=user_id)).describe()
    # Adjectives before the noun, which is where English puts them. The naive
    # concatenation produced "a woman curvy in their forties", and an image
    # model handed a sentence that reads as broken draws accordingly.
    assert described == "a curvy woman in their forties with dark brown skin"


def test_height_joins_the_sentence_as_an_adjective() -> None:
    """Bands rather than a measurement.

    A number would be a measurement of a person held on a server, and the
    prompt can only act on the difference anyway: an image model draws "tall"
    and "short", not 174cm.
    """
    assert (
        Appearance(presentation="feminine", body_type="athletic", height="tall")
        .describe()
        == "a tall athletic woman"
    )
    assert Appearance(presentation="masculine", height="short").describe() == (
        "a short man"
    )


def test_average_is_stored_but_says_nothing_to_the_model() -> None:
    """Two different questions.

    An image model handed "a person" already draws an average build at an
    average height, so "of average build" adds words without adding
    information — and does not compose into a sentence ("an of average height
    of average build person"). What somebody stated is still recorded.
    """
    stated = Appearance(body_type="average", height="average")
    assert stated.describe() == "a person"
    assert stated.as_stored()["body_type"] == "average"
    assert stated.as_stored()["height"] == "average"


def test_the_article_agrees_with_what_follows_it() -> None:
    """an athletic man, not a athletic man."""
    assert Appearance(presentation="masculine", body_type="athletic").describe() == (
        "an athletic man"
    )
    assert Appearance(presentation="feminine", body_type="slim").describe() == (
        "a slim woman"
    )


async def test_a_value_outside_the_vocabulary_is_refused() -> None:
    """A closed set, so nothing unreviewed reaches an image prompt."""
    with pytest.raises(UnknownAppearance):
        Appearance(presentation="something-else")


async def test_a_stored_value_that_is_no_longer_valid_reads_as_unsaid(
    db: AsyncSession,
) -> None:
    """The vocabulary can change; somebody's old row should not crash them."""
    recovered = Appearance.from_stored(
        {"presentation": "retired-value", "age_band": "30s"}
    )
    assert recovered.presentation == "unspecified"
    assert recovered.age_band == "30s"


async def test_setting_appearance_twice_overwrites_rather_than_accumulating(
    db: AsyncSession,
) -> None:
    user_id = await _user(db)
    await domain.write_appearance(
        db, user_id=user_id, appearance=Appearance(presentation="masculine")
    )
    await domain.write_appearance(
        db, user_id=user_id, appearance=Appearance(presentation="androgynous")
    )

    assert (await domain.read_appearance(db, user_id=user_id)).presentation == (
        "androgynous"
    )


# --------------------------------------------------------------------------- #
# the picture, and what it is labelled
# --------------------------------------------------------------------------- #
async def test_an_avatar_is_stored_as_an_avatar_not_a_photograph(
    db: AsyncSession,
) -> None:
    """It is a drawing of somebody who looks like the user, not the user."""
    from tests.test_garment_media import InMemoryMediaStore

    user_id = await _user(db)
    asset = await domain.generate_avatar(
        db, user_id=user_id, renderer=StubRenderer(), store=InMemoryMediaStore()
    )

    assert asset.kind == "avatar"
    assert asset.kind != "garment_photo"
    assert asset.status == "ready"
    assert asset.publication_consent is False


async def test_having_an_avatar_does_not_move_try_on_onto_it(
    db: AsyncSession,
) -> None:
    """**Making an avatar is not the same as choosing to wear everything
    on it.**

    This asserted the opposite until 2026-11-03, on the reasoning that
    an avatar somebody built is a better figure than a shared one.
    True, and it made the avatar unavoidable: building one once, to see
    what it looked like, silently redirected every later try-on onto a
    photorealistic likeness with no way back short of deleting it. The
    mannequin is the default now; the avatar is a preference.

    The invariant the old test protected - a stable figure, so two
    outfits can be compared - is untouched. It is simply the same
    mannequin every time instead of the same avatar.
    """
    from tests.test_garment_media import InMemoryMediaStore

    store = InMemoryMediaStore()
    user_id = await _user(db)
    renderer = StubRenderer()

    await domain.generate_avatar(
        db, user_id=user_id, renderer=renderer, store=store
    )
    await domain.try_on(
        db,
        user_id=user_id,
        outfit="a charcoal wool suit",
        renderer=renderer,
        store=store,
    )

    assert len(renderer.tried) == 1
    source, outfit = renderer.tried[0]
    assert source != b"RIFFavatar", "the avatar was used without being asked for"
    assert source.startswith(b"RIFF"), "a mannequin webp"
    assert outfit == "a charcoal wool suit"


async def test_asking_for_the_avatar_moves_try_on_onto_it(
    db: AsyncSession,
) -> None:
    """And the preference is the only thing that moves it."""
    from app.domain.mannequin import ON_MY_AVATAR, VEHICLE_KEY
    from app.models.preference import Preference
    from tests.test_garment_media import InMemoryMediaStore

    store = InMemoryMediaStore()
    user_id = await _user(db)
    renderer = StubRenderer()

    await domain.generate_avatar(
        db, user_id=user_id, renderer=renderer, store=store
    )
    db.add(Preference(user_id=user_id, key=VEHICLE_KEY, value=ON_MY_AVATAR))
    await db.commit()

    await domain.try_on(
        db,
        user_id=user_id,
        outfit="a charcoal wool suit",
        renderer=renderer,
        store=store,
    )

    source, outfit = renderer.tried[0]
    assert source == b"RIFFavatar"
    assert outfit == "a charcoal wool suit"


async def test_the_figure_is_the_same_one_every_time(
    db: AsyncSession,
) -> None:
    """The property the old test existed for, stated directly.

    A fresh figure per try-on would make comparing two outfits
    meaningless, whichever figure it is.
    """
    from tests.test_garment_media import InMemoryMediaStore

    store = InMemoryMediaStore()
    user_id = await _user(db)
    renderer = StubRenderer()

    for outfit in ("a charcoal wool suit", "a cream linen shirt"):
        await domain.try_on(
            db, user_id=user_id, outfit=outfit, renderer=renderer, store=store
        )

    first, second = renderer.tried[0][0], renderer.tried[1][0]
    assert first == second, "the figure changed between two try-ons"


async def test_trying_on_without_an_avatar_uses_a_mannequin(
    db: AsyncSession,
) -> None:
    """**This used to refuse, and the refusal was the bug.**

    Eight of the last eight try-ons failed with "create your avatar
    before trying clothes on it" - a wall in front of the feature
    somebody came for, while fifteen mannequin figures sat in the
    repository unreachable from the server.

    It now dresses a shared figure instead. The person's own avatar
    still wins when they have one; this is only what happens when
    they do not.
    """
    from tests.test_garment_media import InMemoryMediaStore

    user_id = await _user(db)
    renderer = StubRenderer()
    await domain.try_on(
        db,
        user_id=user_id,
        outfit="a linen shirt",
        renderer=renderer,
        store=InMemoryMediaStore(),
    )

    assert len(renderer.tried) == 1
    source, outfit = renderer.tried[0]
    assert outfit == "a linen shirt"
    # A real picture, not a blank: the shipped mannequin's bytes.
    assert len(source) > 1000


async def test_trying_on_says_so_when_there_is_no_figure_at_all(
    db: AsyncSession,
) -> None:
    """The refusal is still there for the case that warrants it.

    If the shipped figures are missing from the image - a broken
    build rather than a new account - there is genuinely nothing to
    draw on, and saying so beats rendering nothing.
    """
    from tests.test_garment_media import InMemoryMediaStore

    user_id = await _user(db)
    with mock.patch(
        "app.domain.mannequin.bytes_for", return_value=None
    ), pytest.raises(domain.NoAvatarYet):
        await domain.try_on(
            db,
            user_id=user_id,
            outfit="a linen shirt",
            renderer=StubRenderer(),
            store=InMemoryMediaStore(),
        )


async def test_one_persons_avatar_is_never_another_persons(
    db: AsyncSession,
) -> None:
    """Scoping, asserted rather than assumed: this is a picture of somebody."""
    from tests.test_garment_media import InMemoryMediaStore

    store = InMemoryMediaStore()
    mine = await _user(db)
    stranger = await _user(db)
    await domain.generate_avatar(
        db, user_id=mine, renderer=StubRenderer(), store=store
    )

    assert await domain.current_avatar(db, user_id=mine) is not None
    assert await domain.current_avatar(db, user_id=stranger) is None


# --------------------------------------------------------------------------- #
# the try-on prompt
# --------------------------------------------------------------------------- #
def test_the_try_on_prompt_pins_everything_except_the_clothes() -> None:
    """An image edit will redraw the person given the chance.

    An avatar whose face changes between outfits is not an avatar, and
    region-limited editing is unavailable here (`mask` is a verified 400), so
    the prompt has to carry the constraint.
    """
    prompt = try_on_prompt("a green corduroy suit")

    assert "a green corduroy suit" in prompt
    for held in ("same person", "same face", "same pose", "same background"):
        assert held in prompt


# --------------------------------------------------------------------------- #
# over HTTP
# --------------------------------------------------------------------------- #
async def test_appearance_round_trips(client: httpx.AsyncClient, auth: Any) -> None:
    await client.post("/v1/auth/session", headers=auth(sub="kc-avatar-1"))

    sent = await client.put(
        "/v1/avatar/appearance",
        headers=auth(sub="kc-avatar-1"),
        json={"presentation": "masculine", "age_band": "30s"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["presentation"] == "masculine"

    read = await client.get("/v1/avatar", headers=auth(sub="kc-avatar-1"))
    assert read.status_code == 200
    body = read.json()
    # Nothing drawn yet, and the client is told so rather than shown a blank.
    assert body["asset_id"] is None
    assert body["appearance"]["presentation"] == "masculine"
    assert body["appearance"]["skin_tone"] == "unspecified"


async def test_an_unknown_appearance_value_is_refused_over_http(
    client: httpx.AsyncClient, auth: Any
) -> None:
    await client.post("/v1/auth/session", headers=auth(sub="kc-avatar-2"))
    r = await client.put(
        "/v1/avatar/appearance",
        headers=auth(sub="kc-avatar-2"),
        json={"presentation": "something-else"},
    )
    assert r.status_code == 422


async def test_the_avatar_needs_a_session(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/avatar")).status_code == 401
    assert (
        await client.put("/v1/avatar/appearance", json={"presentation": "feminine"})
    ).status_code == 401


# --------------------------------------------------------------------------- #
# The outfit sentence an edit can actually follow
#
# A pin of toe rings and anklets was read as "Bare feet with silver
# and gold toe rings... around one ankle", and that went into an image
# edit which also says "keep the same person, the same body". The
# vendor refused it: 400, "the response was filtered due to the prompt
# triggering our content management policy", four times in a row. The
# reading was accurate about the photograph and useless as an
# instruction - nobody wears bare feet.
# --------------------------------------------------------------------------- #
def test_a_body_part_is_not_something_to_wear() -> None:
    from app.workers.avatar import wearable_words

    said = wearable_words(
        "Bare feet with silver toe rings and chain bracelets around one ankle."
    )
    assert "bare feet" not in said.lower()
    assert "toe rings" in said, "the jewellery is the point and must survive"


def test_the_refused_prompt_no_longer_contains_the_phrase() -> None:
    """The whole prompt, as it goes to the vendor."""
    from app.workers.avatar import try_on_prompt

    sent = try_on_prompt("Bare feet with silver toe rings.")
    assert "bare feet" not in sent.lower()


def test_an_accessory_on_its_own_is_given_something_to_sit_on() -> None:
    """**A necklace alone is not an outfit.**

    A pin can legitimately be one piece - a scarf, a pair of socks, a
    single chain. Asking an edit to dress a figure in only that
    leaves it unchanged or undressed, and the second is the same
    refusal arriving a different way.
    """
    from app.workers.avatar import BASE_OUTFIT, wearable_words

    for only in ("a gold chain necklace", "white sneakers", "a silk scarf"):
        said = wearable_words(only)
        assert BASE_OUTFIT in said, f"{only!r} was left with nothing to sit on"
        assert only.split()[-1] in said, "the piece itself must survive"


def test_a_full_outfit_is_left_exactly_as_it_was() -> None:
    """Nothing is added to something already wearable - a base outfit
    under a complete look would be two outfits."""
    from app.workers.avatar import BASE_OUTFIT, wearable_words

    full = "oversized teal t-shirt, black baggy cargo pants, white sneakers"
    assert wearable_words(full) == full
    assert BASE_OUTFIT not in wearable_words(full)


def test_a_garment_whose_name_contains_a_body_word_survives() -> None:
    """Matched on the phrase, not the word: a shoulder bag keeps its
    bag and barefoot sandals keep their sandals."""
    from app.workers.avatar import wearable_words

    assert "shoulder bag" in wearable_words("a tan shoulder bag")


def test_an_empty_description_still_dresses_the_figure() -> None:
    from app.workers.avatar import BASE_OUTFIT, wearable_words

    assert wearable_words("Bare feet.") == BASE_OUTFIT
