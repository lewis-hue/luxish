"""Task 11 — favourites: a stated preference, owner-scoped.

Two invariants, both of which a plain boolean column makes easy to get wrong:

* **A favourite is stated, never inferred.** It is user truth, in the same class
  as ``confirmed_attributes``, so no worker and no model may write it — and the
  stylist *weights* it rather than guessing at it, which is why there is a cheap
  id-only read for the retrieval step.
* **Another user cannot favourite your garment, and cannot learn that it
  exists.** The answer is 404, not 403, because a 403 confirms the id is real.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import session_factory
from app.domain.garment_media import (
    favourite_garment_ids,
    list_favourites,
    record_categorisation,
    set_favourite,
)
from app.errors import NotFound
from app.models.garment import Garment
from app.models.user import User


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test attempted a real network request")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


@pytest.fixture
async def media_client(engine: Any, verifier: Any) -> AsyncIterator[httpx.AsyncClient]:
    """The app with this task's router mounted; a no-op once it is registered
    in ``app/main.py`` upstream."""
    from app.db.session import get_session
    from app.deps import get_token_verifier
    from app.main import API_PREFIX, create_app
    from app.routers import wardrobe_media

    app = create_app()
    if not any(
        getattr(route, "path", "") == f"{API_PREFIX}/wardrobe/favourites"
        for route in app.routes
    ):
        app.include_router(wardrobe_media.router, prefix=API_PREFIX)

    maker = session_factory(engine)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def make_user(db: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def session_user(client: httpx.AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    response = await client.post("/v1/auth/session", headers=headers)
    assert response.status_code == 200, response.text
    return uuid.UUID(response.json()["user_id"])


async def make_garment(
    db: AsyncSession, *, user_id: uuid.UUID, name: str = "navy blazer", **kwargs: Any
) -> Garment:
    garment = Garment(
        user_id=user_id,
        name=name,
        confirmed_attributes={},
        inferred_attributes={},
        **kwargs,
    )
    db.add(garment)
    await db.commit()
    await db.refresh(garment)
    return garment


# --------------------------------------------------------------------------- #
# the column
# --------------------------------------------------------------------------- #
async def test_a_new_garment_is_not_a_favourite(db: AsyncSession) -> None:
    """The default is a column default, so a row created by any path has it."""
    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)
    assert garment.is_favourite is False


async def test_favourite_and_unfavourite_round_trip(db: AsyncSession) -> None:
    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)

    favourited = await set_favourite(
        db, user_id=user_id, garment_id=garment.id, favourite=True
    )
    assert favourited.is_favourite is True

    unfavourited = await set_favourite(
        db, user_id=user_id, garment_id=garment.id, favourite=False
    )
    assert unfavourited.is_favourite is False


async def test_favouriting_twice_is_the_same_as_once(db: AsyncSession) -> None:
    """Idempotent in both directions: a double tap on a flaky connection must
    not toggle."""
    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)

    await set_favourite(db, user_id=user_id, garment_id=garment.id, favourite=True)
    again = await set_favourite(
        db, user_id=user_id, garment_id=garment.id, favourite=True
    )
    assert again.is_favourite is True

    await set_favourite(db, user_id=user_id, garment_id=garment.id, favourite=False)
    twice = await set_favourite(
        db, user_id=user_id, garment_id=garment.id, favourite=False
    )
    assert twice.is_favourite is False


async def test_an_inference_cannot_set_or_clear_a_favourite(db: AsyncSession) -> None:
    """A favourite is stated. There is no column for a worker to write it into,
    which is the same guarantee that protects ``confirmed_attributes``."""
    from app.domain.garment_media import (
        CATEGORISATION_WRITABLE_COLUMNS,
        CategorisationResult,
    )

    assert "is_favourite" not in CATEGORISATION_WRITABLE_COLUMNS

    user_id = await make_user(db)
    garment = await make_garment(db, user_id=user_id)
    garment_id = garment.id
    await set_favourite(db, user_id=user_id, garment_id=garment_id, favourite=True)

    assert await record_categorisation(
        db,
        garment_id,
        CategorisationResult(
            slot="tops",
            category="blazer",
            colour="navy",
            pattern="plain",
            apparent_material="wool",
            category_confidence=0.99,
        ),
    )
    await db.commit()

    db.expunge_all()
    fresh = await db.get(Garment, garment_id)
    assert fresh is not None
    assert fresh.is_favourite is True


# --------------------------------------------------------------------------- #
# owner scoping
# --------------------------------------------------------------------------- #
async def test_another_user_cannot_favourite_your_garment(db: AsyncSession) -> None:
    owner = await make_user(db)
    stranger = await make_user(db)
    garment = await make_garment(db, user_id=owner)

    with pytest.raises(NotFound):
        await set_favourite(
            db, user_id=stranger, garment_id=garment.id, favourite=True
        )

    db.expunge_all()
    fresh = await db.get(Garment, garment.id)
    assert fresh is not None and fresh.is_favourite is False


async def test_a_stranger_id_and_a_missing_id_are_indistinguishable(
    db: AsyncSession,
) -> None:
    """A 403 would confirm the id exists, which is the leak the 404 avoids."""
    owner = await make_user(db)
    stranger = await make_user(db)
    garment = await make_garment(db, user_id=owner)

    with pytest.raises(NotFound) as theirs:
        await set_favourite(db, user_id=stranger, garment_id=garment.id, favourite=True)
    with pytest.raises(NotFound) as nobodys:
        await set_favourite(db, user_id=stranger, garment_id=uuid.uuid4(), favourite=True)

    assert str(theirs.value) == str(nobodys.value)


async def test_the_favourites_list_contains_only_your_own(db: AsyncSession) -> None:
    owner = await make_user(db)
    stranger = await make_user(db)
    mine = await make_garment(db, user_id=owner, name="mine")
    theirs = await make_garment(db, user_id=stranger, name="theirs")

    await set_favourite(db, user_id=owner, garment_id=mine.id, favourite=True)
    await set_favourite(db, user_id=stranger, garment_id=theirs.id, favourite=True)

    page = await list_favourites(db, user_id=owner)
    assert [g.id for g in page.items] == [mine.id]


# --------------------------------------------------------------------------- #
# reading favourites
# --------------------------------------------------------------------------- #
async def test_only_favourites_appear_and_deleted_ones_do_not(
    db: AsyncSession,
) -> None:
    from app.domain.wardrobe import GarmentRepository

    user_id = await make_user(db)
    kept = await make_garment(db, user_id=user_id, name="kept")
    plain = await make_garment(db, user_id=user_id, name="plain")
    removed = await make_garment(db, user_id=user_id, name="removed")

    for garment in (kept, removed):
        await set_favourite(
            db, user_id=user_id, garment_id=garment.id, favourite=True
        )
    await GarmentRepository(db, user_id=user_id).soft_delete(removed.id)

    page = await list_favourites(db, user_id=user_id)
    names = {g.name for g in page.items}
    assert names == {"kept"}
    assert plain.name not in names


async def test_the_favourites_cursor_walks_every_item_once(db: AsyncSession) -> None:
    user_id = await make_user(db)
    created = []
    for index in range(5):
        garment = await make_garment(db, user_id=user_id, name=f"fav-{index}")
        await set_favourite(
            db, user_id=user_id, garment_id=garment.id, favourite=True
        )
        created.append(garment.id)

    seen: list[uuid.UUID] = []
    cursor: str | None = None
    while True:
        page = await list_favourites(db, user_id=user_id, cursor=cursor, limit=2)
        seen.extend(g.id for g in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(map(str, seen)) == sorted(map(str, created))
    assert len(seen) == len(set(seen))


async def test_the_id_only_read_reports_its_own_truncation(db: AsyncSession) -> None:
    """A truncated read that looks complete is worse than one that says so: the
    stylist would silently weight a subset of the user's favourites."""
    user_id = await make_user(db)
    for index in range(4):
        garment = await make_garment(db, user_id=user_id, name=f"f{index}")
        await set_favourite(
            db, user_id=user_id, garment_id=garment.id, favourite=True
        )

    ids, total = await favourite_garment_ids(db, user_id=user_id, limit=2)
    assert total == 4
    assert len(ids) == 2

    everything, same_total = await favourite_garment_ids(db, user_id=user_id)
    assert len(everything) == same_total == 4


# --------------------------------------------------------------------------- #
# over HTTP
# --------------------------------------------------------------------------- #
async def test_the_favourite_endpoints_round_trip_over_http(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await session_user(media_client, auth(sub="kc-fav1"))
    garment = await make_garment(db, user_id=user_id)

    favourited = await media_client.post(
        f"/v1/wardrobe/garments/{garment.id}/favourite", headers=auth(sub="kc-fav1")
    )
    assert favourited.status_code == 200, favourited.text
    assert favourited.json()["is_favourite"] is True

    listed = await media_client.get("/v1/wardrobe/favourites", headers=auth(sub="kc-fav1"))
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [str(garment.id)]

    cleared = await media_client.delete(
        f"/v1/wardrobe/garments/{garment.id}/favourite", headers=auth(sub="kc-fav1")
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["is_favourite"] is False

    empty = await media_client.get("/v1/wardrobe/favourites", headers=auth(sub="kc-fav1"))
    assert empty.json()["items"] == []


async def test_another_users_garment_is_a_404_over_http(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    owner = await session_user(media_client, auth(sub="kc-owner"))
    await session_user(media_client, auth(sub="kc-stranger"))
    garment = await make_garment(db, user_id=owner)

    for method in (media_client.post, media_client.delete):
        response = await method(
            f"/v1/wardrobe/garments/{garment.id}/favourite",
            headers=auth(sub="kc-stranger"),
        )
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"


async def test_the_favourite_endpoints_require_authentication(
    media_client: httpx.AsyncClient,
) -> None:
    garment_id = uuid.uuid4()
    for request in (
        media_client.post(f"/v1/wardrobe/garments/{garment_id}/favourite"),
        media_client.delete(f"/v1/wardrobe/garments/{garment_id}/favourite"),
        media_client.get("/v1/wardrobe/favourites"),
        media_client.get("/v1/wardrobe/favourites/ids"),
    ):
        response = await request
        assert response.status_code == 401


async def test_the_favourites_path_is_not_shadowed_by_the_garment_id_route(
    media_client: httpx.AsyncClient, auth: Any
) -> None:
    """``/wardrobe/garments/favourites`` would be matched by
    ``/wardrobe/garments/{garment_id}`` and fail UUID parsing depending on
    router registration order. Keeping the path spaces disjoint means
    registration order cannot change behaviour."""
    await session_user(media_client, auth(sub="kc-shadow"))
    response = await media_client.get(
        "/v1/wardrobe/favourites", headers=auth(sub="kc-shadow")
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_the_id_endpoint_gives_the_stylist_what_it_needs(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await session_user(media_client, auth(sub="kc-ids"))
    garment = await make_garment(db, user_id=user_id)
    await media_client.post(
        f"/v1/wardrobe/garments/{garment.id}/favourite", headers=auth(sub="kc-ids")
    )

    response = await media_client.get(
        "/v1/wardrobe/favourites/ids", headers=auth(sub="kc-ids")
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "garment_ids": [str(garment.id)],
        "total": 1,
        "truncated": False,
    }


async def test_the_garment_response_exposes_this_tasks_fields(
    media_client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """The cut-out id is ``None`` in the normal case, not an error: background
    removal is optional processing and the original always works without it."""
    user_id = await session_user(media_client, auth(sub="kc-shape"))
    garment = await make_garment(db, user_id=user_id)

    response = await media_client.post(
        f"/v1/wardrobe/garments/{garment.id}/favourite", headers=auth(sub="kc-shape")
    )

    body = response.json()
    assert body["is_favourite"] is True
    assert body["background_removed_asset_id"] is None
    assert body["categorisation_confidence"] is None
    # Still a garment: the response extends the shared contract rather than
    # replacing it.
    for key in ("confirmed_attributes", "inferred_attributes", "effective_attributes"):
        assert key in body
