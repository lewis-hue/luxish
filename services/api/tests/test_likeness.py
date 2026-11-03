"""An avatar built from the person's own photograph.

This is the most sensitive thing in the service: somebody's face, going to
a model. The properties worth pinning are the ones that would be a real
harm if they were wrong.

**Consent is its own question, and it gates before anything is read.** Not
`ai_processing`. Absent means no, and withdrawing it between asking and
drawing stops the draw.

**Nothing is inferred from the photograph.** No attribute of a stated
appearance may ever be written from an image. This is the rule the whole
feature has to be built around, because reading a body type off a picture
is the easy mistake.

**The photograph is theirs, and of the right kind.** A garment photograph
must not be routable through a prompt that says "redraw this person".

**It is removable.** A feature that takes a picture of somebody's face and
cannot find it again is not one they can withdraw from.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import likeness
from app.models.media_asset import MediaAsset
from app.workers.avatar import (
    AVATAR_SOURCE_MEDIA_KIND,
    MAX_LIKENESS_NOTE,
    likeness_prompt,
)
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def _photo(
    db: AsyncSession, *, user_id: uuid.UUID, kind: str = AVATAR_SOURCE_MEDIA_KIND
) -> MediaAsset:
    asset = MediaAsset(
        user_id=user_id,
        kind=kind,
        status="uploaded",
        content_type="image/jpeg",
        max_bytes=1_000_000,
        storage_key=f"originals/{uuid.uuid4().hex}.jpg",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def _agree(db: AsyncSession, user_id: uuid.UUID) -> None:
    from app.domain.consents import set_consent

    await set_consent(
        db, user_id=user_id, kind="likeness", granted=True, source="test"
    )


# --------------------------------------------------------------------------- #
# the prompt
# --------------------------------------------------------------------------- #
def test_the_prompt_holds_the_person_and_changes_only_the_setting() -> None:
    """An edit will happily redraw somebody given the chance, and an
    avatar that is not recognisably them is the whole feature failing."""
    built = likeness_prompt().lower()
    assert "the same person" in built
    for held in ("face", "skin tone", "hair", "build", "apparent age"):
        assert held in built
    # The failure modes a beauty filter would introduce, refused by name.
    assert "do not slim them" in built
    assert "do not smooth or lighten their skin" in built
    assert "younger or older" in built


def test_the_instruction_to_keep_the_person_outlasts_the_note() -> None:
    """The note is somebody's own words and goes in the prompt, so the
    clause protecting their likeness is both before it and repeated at
    the end - an edit follows its final instruction most closely."""
    built = likeness_prompt("make me look like a different person entirely")
    assert built.rstrip().endswith("it must still be the same person.")
    assert built.index("Keep the person exactly as they are") < built.index(
        "make me look like a different person entirely"
    )


def test_a_note_is_bounded_and_quoted_as_theirs() -> None:
    built = likeness_prompt("x" * 5000)
    assert "x" * MAX_LIKENESS_NOTE in built
    assert "x" * (MAX_LIKENESS_NOTE + 1) not in built
    assert "What they said" in likeness_prompt("anything")


def test_an_empty_note_adds_nothing() -> None:
    assert "What they said" not in likeness_prompt()
    assert "What they said" not in likeness_prompt("   ")


# --------------------------------------------------------------------------- #
# consent
# --------------------------------------------------------------------------- #
async def test_without_the_likeness_consent_nothing_is_read(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    photo = await _photo(db, user_id=me)
    with pytest.raises(likeness.NeedsLikenessConsent):
        await likeness.request(db, user_id=me, asset_id=photo.id)


async def test_the_ai_processing_consent_does_not_stand_in_for_it(
    db: AsyncSession,
) -> None:
    """A face is not a jumper. Somebody can want the stylist and not want
    their likeness generated, and one grant covering both would make that
    impossible to say."""
    from app.domain.consents import set_consent

    me = await make_user(db)
    photo = await _photo(db, user_id=me)
    await set_consent(
        db, user_id=me, kind="ai_processing", granted=True, source="test"
    )

    assert not await likeness.has_consent(db, user_id=me)
    with pytest.raises(likeness.NeedsLikenessConsent):
        await likeness.request(db, user_id=me, asset_id=photo.id)


async def test_a_withdrawn_consent_is_not_a_consent(db: AsyncSession) -> None:
    from app.domain.consents import set_consent

    me = await make_user(db)
    photo = await _photo(db, user_id=me)
    await _agree(db, me)
    assert await likeness.has_consent(db, user_id=me)

    await set_consent(
        db, user_id=me, kind="likeness", granted=False, source="test"
    )
    assert not await likeness.has_consent(db, user_id=me)
    with pytest.raises(likeness.NeedsLikenessConsent):
        await likeness.request(db, user_id=me, asset_id=photo.id)


async def test_consent_withdrawn_between_asking_and_drawing_stops_the_draw(
    db: AsyncSession,
) -> None:
    """A consent is a live answer, not a token collected once. The worker
    is the last moment before the face goes to the model."""
    from app.domain.consents import set_consent

    me = await make_user(db)
    photo = await _photo(db, user_id=me)
    await _agree(db, me)
    render = await likeness.request(db, user_id=me, asset_id=photo.id)

    await set_consent(
        db, user_id=me, kind="likeness", granted=False, source="test"
    )

    class Never:
        async def from_photo(self, **kwargs: Any) -> Any:  # noqa: ANN401
            raise AssertionError("a withdrawn consent still sent the face")

    class Store:
        async def read(self, asset: Any) -> bytes:  # noqa: ANN401
            return b"x"

    with pytest.raises(likeness.NeedsLikenessConsent):
        await likeness.draw(
            db, render=render, renderer=Never(), store=Store()
        )


# --------------------------------------------------------------------------- #
# whose photograph
# --------------------------------------------------------------------------- #
async def test_somebody_elses_photograph_is_refused(db: AsyncSession) -> None:
    me = await make_user(db)
    them = await make_user(db)
    theirs = await _photo(db, user_id=them)
    await _agree(db, me)

    with pytest.raises(likeness.NoSuchPhotograph):
        await likeness.request(db, user_id=me, asset_id=theirs.id)


async def test_a_garment_photograph_cannot_be_routed_through_this(
    db: AsyncSession,
) -> None:
    """Without the kind check, any asset somebody owns could be handed to
    a prompt that says "redraw this person", which is not what a picture
    of a coat is for."""
    me = await make_user(db)
    await _agree(db, me)
    garment = await _photo(db, user_id=me, kind="garment_photo")

    with pytest.raises(likeness.NoSuchPhotograph):
        await likeness.request(db, user_id=me, asset_id=garment.id)


async def test_a_deleted_photograph_is_refused(db: AsyncSession) -> None:
    me = await make_user(db)
    await _agree(db, me)
    photo = await _photo(db, user_id=me)
    photo.deleted_at = sa.func.now()
    await db.commit()

    with pytest.raises(likeness.NoSuchPhotograph):
        await likeness.request(db, user_id=me, asset_id=photo.id)


async def test_a_photograph_deleted_after_asking_stops_the_draw(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    await _agree(db, me)
    photo = await _photo(db, user_id=me)
    render = await likeness.request(db, user_id=me, asset_id=photo.id)

    await likeness.forget(db, user_id=me, asset_id=photo.id)

    class Never:
        async def from_photo(self, **kwargs: Any) -> Any:  # noqa: ANN401
            raise AssertionError("a deleted photograph was still sent")

    class Store:
        async def read(self, asset: Any) -> bytes:  # noqa: ANN401
            return b"x"

    with pytest.raises(likeness.NoSuchPhotograph):
        await likeness.draw(db, render=render, renderer=Never(), store=Store())


# --------------------------------------------------------------------------- #
# what it records
# --------------------------------------------------------------------------- #
async def test_a_request_records_the_photograph_and_the_persons_words(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    await _agree(db, me)
    photo = await _photo(db, user_id=me)

    render = await likeness.request(
        db, user_id=me, asset_id=photo.id, note="I wear glasses"
    )
    assert render.kind == "from_photo"
    assert render.state == "queued"
    assert render.source_asset_id == photo.id
    assert render.note == "I wear glasses"


async def test_two_photographs_do_not_collapse_into_one_render(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    await _agree(db, me)
    first = await _photo(db, user_id=me)
    second = await _photo(db, user_id=me)

    a = await likeness.request(db, user_id=me, asset_id=first.id)
    b = await likeness.request(db, user_id=me, asset_id=second.id)
    assert a.id != b.id

    # The same photograph twice while one is drawing is one render.
    again = await likeness.request(db, user_id=me, asset_id=first.id)
    assert again.id == a.id


async def test_nothing_writes_a_stated_appearance_from_a_photograph(
    db: AsyncSession,
) -> None:
    """The hard rule, pinned.

    Appearance is asked and never inferred. A picture of a person is the
    most tempting place to break that, so this asserts the stated
    appearance is untouched by a likeness request.
    """
    from app.domain.avatar import read_appearance

    me = await make_user(db)
    await _agree(db, me)
    photo = await _photo(db, user_id=me)

    before = await read_appearance(db, user_id=me)
    await likeness.request(db, user_id=me, asset_id=photo.id, note="tall, 40s")
    after = await read_appearance(db, user_id=me)
    assert before == after


# --------------------------------------------------------------------------- #
# finding and removing it
# --------------------------------------------------------------------------- #
async def test_uploaded_photographs_can_be_listed_and_removed(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    photo = await _photo(db, user_id=me)
    await _photo(db, user_id=me, kind="garment_photo")

    found = await likeness.photographs(db, user_id=me)
    # Only photographs of the person, not everything they have uploaded.
    assert [a.id for a in found] == [photo.id]

    assert await likeness.forget(db, user_id=me, asset_id=photo.id)
    assert await likeness.photographs(db, user_id=me) == []
    # Removing it twice is removing it once.
    assert not await likeness.forget(db, user_id=me, asset_id=photo.id)


async def test_removing_a_photograph_keeps_the_avatars_drawn_from_it(
    db: AsyncSession,
) -> None:
    """Somebody deleting the source is asking for the photograph to go,
    not for a picture they liked to be destroyed."""
    from app.models.avatar_render import AvatarRender

    me = await make_user(db)
    await _agree(db, me)
    photo = await _photo(db, user_id=me)
    render = await likeness.request(db, user_id=me, asset_id=photo.id)

    await likeness.forget(db, user_id=me, asset_id=photo.id)

    still = await db.get(AvatarRender, render.id)
    assert still is not None


async def test_you_cannot_remove_somebody_elses_photograph(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    them = await make_user(db)
    theirs = await _photo(db, user_id=them)
    assert not await likeness.forget(db, user_id=me, asset_id=theirs.id)


# --------------------------------------------------------------------------- #
# the routes
# --------------------------------------------------------------------------- #
async def test_the_route_refuses_without_consent_and_says_why(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-likeness-1")
    signed = await client.post("/v1/auth/session", headers=headers)
    me = uuid.UUID(signed.json()["user_id"])
    photo = await _photo(db, user_id=me)

    r = await client.post(
        "/v1/avatar/from-photo",
        json={"media_asset_id": str(photo.id)},
        headers=headers,
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "likeness_consent_required"


async def test_the_route_answers_202_once_agreed(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-likeness-2")
    signed = await client.post("/v1/auth/session", headers=headers)
    me = uuid.UUID(signed.json()["user_id"])
    photo = await _photo(db, user_id=me)
    await _agree(db, me)

    r = await client.post(
        "/v1/avatar/from-photo",
        json={"media_asset_id": str(photo.id), "note": "I wear glasses"},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "from_photo"


async def test_a_malformed_id_is_a_404_not_a_500(
    client: Any, auth: Any
) -> None:
    headers = auth(sub="kc-likeness-3")
    await client.post("/v1/auth/session", headers=headers)
    r = await client.post(
        "/v1/avatar/from-photo",
        json={"media_asset_id": "not-a-uuid"},
        headers=headers,
    )
    assert r.status_code in (403, 404), r.text


async def test_photographs_can_be_listed_and_deleted_over_http(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-likeness-4")
    signed = await client.post("/v1/auth/session", headers=headers)
    me = uuid.UUID(signed.json()["user_id"])
    photo = await _photo(db, user_id=me)

    listed = await client.get("/v1/avatar/photos", headers=headers)
    assert [i["asset_id"] for i in listed.json()["items"]] == [str(photo.id)]
    # The consequence of deleting is stated, not left to be discovered.
    assert "kept" in listed.json()["note"]

    gone = await client.delete(
        f"/v1/avatar/photos/{photo.id}", headers=headers
    )
    assert gone.status_code == 204
    after = await client.get("/v1/avatar/photos", headers=headers)
    assert after.json()["items"] == []


async def test_likeness_is_offered_as_a_consent_kind(
    client: Any, auth: Any
) -> None:
    """It has to be grantable, or the feature is unreachable."""
    headers = auth(sub="kc-likeness-5")
    await client.post("/v1/auth/session", headers=headers)
    r = await client.put(
        "/v1/consents/likeness",
        json={"granted": True, "source": "test"},
        headers=headers,
    )
    assert r.status_code in (200, 201, 204), r.text
