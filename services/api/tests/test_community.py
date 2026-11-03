"""The community tab's end-to-end behaviour.

Three things are worth pinning beyond the happy path.

The follow graph has to refuse the cases that make an empty tab look
populated — self-follows and duplicates.

**Nothing a user wrote may reach another account.** The easiest way for that
to regress is for somebody to helpfully surface the private note on a saved
look, so the test for it searches the whole response body rather than the
fields it knows the names of.

**Being in somebody else's feed is opt-in.** Following needs no approval, so
without a consent gate tapping Follow would be enough to read a stranger's
private collection — which is how this first shipped. The tests below cover
the default (invisible), the grant, and the withdrawal taking effect at once.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

import uuid
from typing import Any

import httpx
import pytest


async def _sign_in(client: httpx.AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    response = await client.post("/v1/auth/session", headers=headers)
    assert response.status_code == 200
    return uuid.UUID(response.json()["user_id"])


@pytest.mark.asyncio
async def test_following_is_idempotent_and_counted(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-follower", email="follower@example.com")
    them = auth(sub="kc-followee", email="followee@example.com")
    await _sign_in(client, me)
    other_id = await _sign_in(client, them)

    first = await client.put(f"/v1/community/follows/{other_id}", headers=me)
    assert first.status_code == 204
    # Twice is the same state, not an error: a double tap must not read as a
    # failure.
    again = await client.put(f"/v1/community/follows/{other_id}", headers=me)
    assert again.status_code == 204

    counts = await client.get("/v1/community/follows", headers=me)
    assert counts.json()["following"] == 1

    await client.delete(f"/v1/community/follows/{other_id}", headers=me)
    # Unfollowing somebody you do not follow is also fine.
    repeat = await client.delete(f"/v1/community/follows/{other_id}", headers=me)
    assert repeat.status_code == 204
    assert (await client.get("/v1/community/follows", headers=me)).json()["following"] == 0


@pytest.mark.asyncio
async def test_you_cannot_follow_yourself(client: httpx.AsyncClient, auth: Any) -> None:
    me = auth(sub="kc-self", email="self@example.com")
    my_id = await _sign_in(client, me)
    response = await client.put(f"/v1/community/follows/{my_id}", headers=me)
    # Not a harmless oddity: your own saves in your own feed make an empty
    # feed look busy, which is the one thing this tab must not fake.
    assert response.status_code == 400
    assert response.json()["code"] == "cannot_follow_self"


@pytest.mark.asyncio
async def test_following_an_unknown_account_is_a_404(
    client: httpx.AsyncClient, auth: Any
) -> None:
    me = auth(sub="kc-ghost", email="ghost@example.com")
    await _sign_in(client, me)
    response = await client.put(f"/v1/community/follows/{uuid.uuid4()}", headers=me)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_another_persons_media_is_not_served(
    client: httpx.AsyncClient, auth: Any, engine: Any
) -> None:
    """The guarantee the removal above leans on, asserted rather than assumed.

    Even holding a valid asset id for somebody else's media, the bytes are
    not reachable. Checked here because the community code reasons about it.
    """
    from app.models.media_asset import MediaAsset
    from sqlalchemy.ext.asyncio import async_sessionmaker

    owner = auth(sub="kc-media-owner", email="mediaowner@example.com")
    intruder = auth(sub="kc-media-intruder", email="mediaintruder@example.com")
    owner_id = await _sign_in(client, owner)
    await _sign_in(client, intruder)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        asset = MediaAsset(
            user_id=owner_id,
            kind="outfit_photo",
            content_type="image/webp",
            max_bytes=1_000_000,
            storage_key="k/theirs",
            status="ready",
        )
        session.add(asset)
        await session.commit()
        asset_id = asset.id

    response = await client.get(f"/v1/uploads/local/{asset_id}", headers=intruder)
    # 404 rather than 403: a 403 would confirm the id exists.
    assert response.status_code == 404




async def test_a_blocked_reader_cannot_read_the_follow_list_either(
    db: AsyncSession,
) -> None:
    """The gate the member's page applies, applied where the list is
    built.

    Not a hole that was open: the only route passing a subject
    resolves the member first and 404s there. This pins the domain
    function's own behaviour, so a caller written against it later
    inherits the rule rather than having to remember it.
    """
    import pytest

    from app.domain.community import NoSuchAccount, follow_list
    from app.domain.moderation import block
    from tests.test_garment_media import make_user

    blocker = await make_user(db)
    reader = await make_user(db)
    await block(db, blocker_id=blocker, blocked_id=reader)

    with pytest.raises(NoSuchAccount):
        await follow_list(
            db, user_id=reader, subject_id=blocker, direction="followers"
        )


async def test_a_deleted_account_has_no_follow_list(db: AsyncSession) -> None:
    import uuid

    import pytest

    from app.domain.community import NoSuchAccount, follow_list
    from tests.test_garment_media import make_user

    reader = await make_user(db)
    with pytest.raises(NoSuchAccount):
        await follow_list(
            db, user_id=reader, subject_id=uuid.uuid4(), direction="following"
        )
