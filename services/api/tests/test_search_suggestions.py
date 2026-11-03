"""What the field offers while somebody types, and what the filter drops.

**A suggestion is a promise.** Every row under the field has to be a
tag with fits behind it, because the one thing worse than no
suggestions is a suggestion that opens the empty state.

**"Photographs only" has to mean something checkable.** Nothing on a
post records how it was made, so the only honest basis is the kind of
the media on it: a fit built from a render or an avatar is a picture of
clothes nobody wore.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import feed as domain
from app.models.posts import PostMedia
from tests.test_feed import _fit
from tests.test_garment_media import make_asset, make_user

pytestmark = pytest.mark.anyio


async def test_suggestions_come_from_tags_people_used(db: AsyncSession) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    await _fit(db, user_id=author, caption="", tags=["linen", "linenshirt"])
    await _fit(db, user_id=author, caption="", tags=["linen"])
    await _fit(db, user_id=author, caption="", tags=["denim"])

    found = await domain.popular_tags(db, user_id=reader, starting="lin")
    assert [tag for tag, _ in found] == ["linen", "linenshirt"]
    # And the count is the count, so a row can say how much is behind it.
    assert dict(found)["linen"] == 2


async def test_a_tag_that_begins_with_what_was_typed_comes_first(
    db: AsyncSession,
) -> None:
    """Substring matching finds `crewneck` from "neck"; ordering still
    has to put the word somebody was most likely spelling at the top."""
    author = await make_user(db)
    reader = await make_user(db)
    # The contains-match is the popular one, so only the ordering rule
    # can put the prefix-match above it.
    for _ in range(3):
        await _fit(db, user_id=author, caption="", tags=["crewneck"])
    await _fit(db, user_id=author, caption="", tags=["neckline"])

    found = await domain.popular_tags(db, user_id=reader, starting="neck")
    assert [tag for tag, _ in found] == ["neckline", "crewneck"]


async def test_an_underscore_is_a_character_not_a_wildcard(
    db: AsyncSession,
) -> None:
    """`_` is a single-character wildcard in LIKE and an ordinary
    character in a hashtag. Unescaped, typing "off_" would offer every
    four-letter tag starting "off"."""
    author = await make_user(db)
    reader = await make_user(db)
    await _fit(db, user_id=author, caption="", tags=["off_duty"])
    await _fit(db, user_id=author, caption="", tags=["offday"])

    found = await domain.popular_tags(db, user_id=reader, starting="off_")
    assert [tag for tag, _ in found] == ["off_duty"]


async def test_no_query_still_returns_the_popular_ones(db: AsyncSession) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    for _ in range(2):
        await _fit(db, user_id=author, caption="", tags=["denim"])
    await _fit(db, user_id=author, caption="", tags=["linen"])

    found = await domain.popular_tags(db, user_id=reader)
    assert [tag for tag, _ in found] == ["denim", "linen"]


async def _fit_with_media(db: AsyncSession, *, user_id, tags, kind: str):
    post = await _fit(db, user_id=user_id, caption="", tags=tags)
    asset = await make_asset(db, user_id=user_id)
    asset.kind = kind
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    await db.commit()
    return post


async def test_photographs_only_drops_fits_a_machine_drew(
    db: AsyncSession,
) -> None:
    author = await make_user(db)
    reader = await make_user(db)
    shot = await _fit_with_media(
        db, user_id=author, tags=["linen"], kind="outfit_photo"
    )
    drawn = await _fit_with_media(
        db, user_id=author, tags=["linen"], kind="garment_studio"
    )

    everything = await domain.by_tag(db, user_id=reader, tag="linen")
    assert {entry.post.id for entry in everything} == {shot.id, drawn.id}

    photographs = await domain.by_tag(
        db, user_id=reader, tag="linen", photographs_only=True
    )
    assert [entry.post.id for entry in photographs] == [shot.id]


async def test_one_generated_frame_disqualifies_the_whole_fit(
    db: AsyncSession,
) -> None:
    """A set whose second picture is a render is still a set somebody
    is shown a render in."""
    author = await make_user(db)
    reader = await make_user(db)
    post = await _fit_with_media(
        db, user_id=author, tags=["linen"], kind="outfit_photo"
    )
    extra = await make_asset(db, user_id=author)
    extra.kind = "garment_render"
    db.add(PostMedia(post_id=post.id, media_asset_id=extra.id, position=1))
    await db.commit()

    found = await domain.by_tag(
        db, user_id=reader, tag="linen", photographs_only=True
    )
    assert found == []
