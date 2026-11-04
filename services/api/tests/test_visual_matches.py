"""What a photographed search finds, and what it shows instead.

**The reported gap.** Search by picture read the photograph, took the
strongest tag and jumped to that tag's page. With no tag match it
showed an alert saying "Nothing to go on" and left the person where
they started, which is the worst answer available to somebody who
opened a camera, framed a shot and waited nine seconds.

The instruction named the case exactly: *"if there is no pin that has
the palm shown, the app can show results for pins that include
accessories worn on hands, or pins of people where hands are
visible."* So the loose band is the point of this module, and the
tests below are mostly about it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.discovery.subject import Reading, vector_for
from app.domain.visual_matches import (
    LOOSE_FLOOR,
    matches,
    reading_from,
    subject_of,
)
from app.domain.feed import by_ids
from app.models.post_vision import PostVisionRow

from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


# --------------------------------------------------------------------------- #
# Reading the words into a query
# --------------------------------------------------------------------------- #
def test_one_accessory_photographed_alone_is_that_accessory() -> None:
    assert subject_of(["silver toe rings"]) == "jewellery"
    assert subject_of(["white leather trainers"]) == "footwear"
    assert subject_of(["tan leather tote"]) == "bag"


def test_several_pieces_are_a_look_however_it_was_framed() -> None:
    """**The count decides before the words do, and it has to.**

    Matching on words alone read "white poplin shirt, indigo jeans,
    brown loafers" as `footwear`: `loafers` is the only one of the
    three the table knows a word for, so a whole outfit narrowed to
    the one garment it happened to recognise.
    """
    assert (
        subject_of(["white poplin shirt", "indigo jeans", "brown loafers"])
        == "outfit"
    )


def test_an_unplaceable_photograph_still_gets_a_subject() -> None:
    """`outfit` has the widest gate, so this is the answer that still
    returns results rather than an empty sheet."""
    assert subject_of(["oversized tee"]) == "outfit"
    assert subject_of([]) == "outfit"


def test_tags_colour_the_query_without_counting_as_pieces() -> None:
    """A tag is a word about the whole picture. Counting tags as
    pieces would make every photograph a multi-piece outfit."""
    read = reading_from(
        pieces=["gold hoop earrings"], tags=["minimal", "gold", "street"]
    )
    assert read.subject == "jewellery"
    # Only words in the facet vocabulary survive `clean()`.
    assert "minimal" in read.facets and "street" in read.facets
    assert "gold" not in read.facets


# --------------------------------------------------------------------------- #
# Finding the pins
# --------------------------------------------------------------------------- #
async def _pin(
    db: AsyncSession, *, owner: uuid.UUID, subject: str, facets: tuple[str, ...]
) -> uuid.UUID:
    from app.models.media_asset import MediaAsset
    from app.models.posts import Post, PostMedia

    asset = MediaAsset(
        user_id=owner,
        kind="outfit_photo",
        status="ready",
        content_type="image/png",
        max_bytes=1,
        byte_size=1,
        storage_key=f"posts/{uuid.uuid4().hex}",
        version=1,
        publication_consent=True,
    )
    db.add(asset)
    await db.flush()

    post = Post(user_id=owner, caption="", state="published")
    db.add(post)
    await db.flush()
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))

    reading = Reading(subject=subject, facets=facets, confidence=1.0).clean()
    db.add(
        PostVisionRow(
            post_id=post.id,
            asset_id=asset.id,
            subject=reading.subject,
            presentation=reading.presentation,
            confidence=1.0,
            facets=list(reading.facets),
            vector=vector_for(reading),
            note=None,
            model="test",
            prompt_version="test",
        )
    )
    await db.commit()
    return post.id


async def test_nothing_tagged_still_returns_the_nearest_pins(
    db: AsyncSession,
) -> None:
    """**The whole reason this module exists.**

    Nobody has tagged anything, so the close band is empty. Before
    this, that was an alert and a dead end.
    """
    owner = await make_user(db)
    asker = await make_user(db)
    ring = await _pin(db, owner=owner, subject="jewellery", facets=("metallic",))

    found = await matches(
        db, user_id=asker, tags=["nothing-is-tagged-this"], pieces=["gold ring"]
    )

    assert found.close == []
    assert ring in found.loosely
    assert found.subject == "jewellery"


async def test_the_loose_band_respects_what_the_picture_was_of(
    db: AsyncSession,
) -> None:
    """A photograph of rings finds jewellery, not a sofa.

    The subject gate runs before the cosine, so a near-miss of the
    wrong kind cannot push a real match out of the limit.
    """
    owner = await make_user(db)
    asker = await make_user(db)
    ring = await _pin(db, owner=owner, subject="jewellery", facets=("metallic",))
    room = await _pin(db, owner=owner, subject="interior", facets=("wood",))

    found = await matches(db, user_id=asker, tags=[], pieces=["gold ring"])

    assert ring in found.loosely
    assert room not in found.loosely


async def test_a_blocked_authors_pin_is_not_a_result(
    db: AsyncSession,
) -> None:
    """**A search is not a way round a block.**

    The vectors table knows nothing about blocks, so the gate has to
    be applied after ranking. Worth a test precisely because the
    ranking step is the one place it would be easy to forget.
    """
    from app.models.moderation import Block

    owner = await make_user(db)
    asker = await make_user(db)
    theirs = await _pin(db, owner=owner, subject="jewellery", facets=())
    db.add(Block(blocker_id=asker, blocked_id=owner))
    await db.commit()

    found = await matches(db, user_id=asker, tags=[], pieces=["gold ring"])

    assert theirs not in found.loosely
    assert theirs not in found.close


async def test_an_empty_board_is_an_empty_answer_not_a_crash(
    db: AsyncSession,
) -> None:
    asker = await make_user(db)
    found = await matches(db, user_id=asker, tags=[], pieces=["gold ring"])
    assert found.close == [] and found.loosely == []


async def test_the_close_band_comes_from_tags_people_actually_typed(
    db: AsyncSession,
) -> None:
    from app.models.profile import PostTag

    owner = await make_user(db)
    asker = await make_user(db)
    tagged = await _pin(db, owner=owner, subject="outfit", facets=("street",))
    db.add(PostTag(post_id=tagged, tag="streetwear"))
    await db.commit()

    found = await matches(
        db, user_id=asker, tags=["streetwear"], pieces=["oversized tee"]
    )

    assert tagged in found.close
    # And it is not repeated in the loose band underneath it.
    assert tagged not in found.loosely


def test_the_loose_floor_is_lower_than_the_boards_own() -> None:
    """A person who photographed something and waited is owed an
    attempt. "Here is the nearest thing" beats an empty sheet, as
    long as it is labelled - which is why these are two bands."""
    from app.domain.discovery.subject import nearest
    import inspect

    board_floor = inspect.signature(nearest).parameters["floor"].default
    assert LOOSE_FLOOR < board_floor


async def test_the_order_asked_for_survives_the_database(
    db: AsyncSession,
) -> None:
    """**A ranked list that comes back unranked is not a ranked list.**

    `by_ids` re-orders in Python because SQL has no cheap way to sort
    by a literal list across both dialects here.
    """
    owner = await make_user(db)
    asker = await make_user(db)
    first = await _pin(db, owner=owner, subject="outfit", facets=())
    second = await _pin(db, owner=owner, subject="outfit", facets=())
    third = await _pin(db, owner=owner, subject="outfit", facets=())

    asked = [third, first, second]
    got = await by_ids(db, user_id=asker, ids=asked)

    assert [entry.post.id for entry in got] == asked


async def test_by_ids_drops_what_may_not_be_seen(db: AsyncSession) -> None:
    owner = await make_user(db)
    asker = await make_user(db)
    shown = await _pin(db, owner=owner, subject="outfit", facets=())
    gone = await _pin(db, owner=owner, subject="outfit", facets=())
    # Through the model, not raw SQL: `deleted_at` is a typed column
    # and a bare string slips past the type without being stored.
    from datetime import UTC, datetime

    from app.models.posts import Post

    (await db.get(Post, gone)).deleted_at = datetime.now(UTC)
    await db.commit()

    got = await by_ids(db, user_id=asker, ids=[shown, gone])

    assert [entry.post.id for entry in got] == [shown]
