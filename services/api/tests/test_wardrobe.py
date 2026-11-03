"""Task 5 — wardrobe: separated inference, corrections, and owner scoping.

Two invariants carry this module:

* A user correction is never overwritten by a later worker inference. Confirmed
  and inferred attributes live in separate columns and are merged on read.
* A garment belonging to another user is reported as **404, not 403** — a 403
  would confirm that the id exists.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.wardrobe import GarmentRepository, apply_inference
from app.errors import NotFound
from app.models.garment import AVAILABILITY_VALUES, Garment


async def make_user_via_token(client: httpx.AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    r = await client.post("/v1/auth/session", headers=headers)
    assert r.status_code == 200, r.text
    return uuid.UUID(r.json()["user_id"])


async def make_garment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str = "navy blazer",
    category: str = "outerwear",
    inferred: dict[str, Any] | None = None,
    confirmed: dict[str, Any] | None = None,
    confidence: float | None = None,
    availability: str = "available",
) -> Garment:
    garment = Garment(
        user_id=user_id,
        name=name,
        category=category,
        inferred_attributes=inferred or {},
        confirmed_attributes=confirmed or {},
        inference_confidence=confidence,
        availability=availability,
    )
    db.add(garment)
    await db.commit()
    await db.refresh(garment)
    return garment


async def get_garment(db: AsyncSession, garment_id: uuid.UUID) -> Garment:
    db.expire_all()
    garment = await db.get(Garment, garment_id)
    assert garment is not None
    return garment


# --------------------------------------------------------------------------- #
# corrections vs inference
# --------------------------------------------------------------------------- #
async def test_correction_overrides_inference_and_is_not_overwritten(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-w1"))
    garment = await make_garment(
        db, user_id=user_id, inferred={"colour": "navy"}, confidence=0.4
    )

    patched = await client.patch(
        f"/v1/wardrobe/garments/{garment.id}",
        headers=auth(sub="kc-w1"),
        json={"confirmed_attributes": {"colour": "black"}},
    )
    assert patched.status_code == 200, patched.text

    # A later, more confident worker result must not win.
    await apply_inference(db, garment.id, {"colour": "navy"}, 0.9)

    fresh = await get_garment(db, garment.id)
    assert fresh.effective_attributes["colour"] == "black"
    assert fresh.confirmed_attributes == {"colour": "black"}
    assert fresh.inferred_attributes == {"colour": "navy"}
    assert fresh.inference_confidence == pytest.approx(0.9)


async def test_effective_attributes_merges_per_key_not_per_document(
    db: AsyncSession, client: httpx.AsyncClient, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-w2"))
    garment = await make_garment(
        db,
        user_id=user_id,
        inferred={"colour": "navy", "fabric": "wool", "formality": "smart"},
        confirmed={"colour": "black"},
        confidence=0.5,
    )
    assert garment.effective_attributes == {
        "colour": "black",
        "fabric": "wool",
        "formality": "smart",
    }


async def test_inference_cannot_write_into_the_confirmed_column(
    db: AsyncSession, client: httpx.AsyncClient, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-w3"))
    garment = await make_garment(db, user_id=user_id, confirmed={"colour": "black"})
    await apply_inference(db, garment.id, {"colour": "navy", "fabric": "linen"}, 0.99)
    fresh = await get_garment(db, garment.id)
    assert fresh.confirmed_attributes == {"colour": "black"}
    assert fresh.effective_attributes == {"colour": "black", "fabric": "linen"}


async def test_a_correction_can_clear_a_key_with_an_explicit_null(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-w4"))
    garment = await make_garment(
        db, user_id=user_id, confirmed={"colour": "black", "fit": "slim"}
    )
    r = await client.patch(
        f"/v1/wardrobe/garments/{garment.id}",
        headers=auth(sub="kc-w4"),
        json={"confirmed_attributes": {"fit": None}},
    )
    assert r.status_code == 200
    fresh = await get_garment(db, garment.id)
    assert fresh.confirmed_attributes == {"colour": "black"}


async def test_patch_merges_rather_than_replacing_confirmed_attributes(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-w5"))
    garment = await make_garment(db, user_id=user_id, confirmed={"colour": "black"})
    await client.patch(
        f"/v1/wardrobe/garments/{garment.id}",
        headers=auth(sub="kc-w5"),
        json={"confirmed_attributes": {"fabric": "wool"}},
    )
    fresh = await get_garment(db, garment.id)
    assert fresh.confirmed_attributes == {"colour": "black", "fabric": "wool"}


async def test_inference_confidence_is_recorded_separately(
    db: AsyncSession, client: httpx.AsyncClient, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-w6"))
    garment = await make_garment(db, user_id=user_id)
    await apply_inference(db, garment.id, {"colour": "olive"}, 0.72, inference_version="sam-3.1")
    fresh = await get_garment(db, garment.id)
    assert fresh.inference_confidence == pytest.approx(0.72)
    assert fresh.inference_version == "sam-3.1"


# --------------------------------------------------------------------------- #
# owner scoping: 404, never 403
# --------------------------------------------------------------------------- #
async def test_another_users_garment_is_not_readable(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_a = await make_user_via_token(client, auth(sub="kc-a-owner"))
    await make_user_via_token(client, auth(sub="kc-b-reader"))
    garment_of_a = await make_garment(db, user_id=user_a)

    r = await client.get(
        f"/v1/wardrobe/garments/{garment_of_a.id}", headers=auth(sub="kc-b-reader")
    )
    # 404 not 403 — do not confirm existence.
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


async def test_another_users_garment_is_not_patchable(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_a = await make_user_via_token(client, auth(sub="kc-a2"))
    await make_user_via_token(client, auth(sub="kc-b2"))
    garment_of_a = await make_garment(db, user_id=user_a, confirmed={"colour": "black"})

    r = await client.patch(
        f"/v1/wardrobe/garments/{garment_of_a.id}",
        headers=auth(sub="kc-b2"),
        json={"confirmed_attributes": {"colour": "pink"}},
    )
    assert r.status_code == 404
    fresh = await get_garment(db, garment_of_a.id)
    assert fresh.confirmed_attributes == {"colour": "black"}


async def test_another_users_garment_is_not_deletable(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_a = await make_user_via_token(client, auth(sub="kc-a3"))
    await make_user_via_token(client, auth(sub="kc-b3"))
    garment_of_a = await make_garment(db, user_id=user_a)
    r = await client.delete(
        f"/v1/wardrobe/garments/{garment_of_a.id}", headers=auth(sub="kc-b3")
    )
    assert r.status_code == 404
    assert (await get_garment(db, garment_of_a.id)).deleted_at is None


async def test_a_missing_id_and_a_stranger_id_are_indistinguishable(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_a = await make_user_via_token(client, auth(sub="kc-a4"))
    await make_user_via_token(client, auth(sub="kc-b4"))
    garment_of_a = await make_garment(db, user_id=user_a)

    stranger = await client.get(
        f"/v1/wardrobe/garments/{garment_of_a.id}", headers=auth(sub="kc-b4")
    )
    absent = await client.get(
        f"/v1/wardrobe/garments/{uuid.uuid4()}", headers=auth(sub="kc-b4")
    )
    assert stranger.status_code == absent.status_code == 404
    assert stranger.json()["code"] == absent.json()["code"]


async def test_the_list_only_contains_your_own_garments(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_a = await make_user_via_token(client, auth(sub="kc-a5"))
    user_b = await make_user_via_token(client, auth(sub="kc-b5"))
    await make_garment(db, user_id=user_a, name="a-coat")
    await make_garment(db, user_id=user_b, name="b-coat")

    r = await client.get("/v1/wardrobe/garments", headers=auth(sub="kc-b5"))
    assert r.status_code == 200
    names = [item["name"] for item in r.json()["items"]]
    assert names == ["b-coat"]


async def test_repository_refuses_to_build_an_unscoped_query(db: AsyncSession) -> None:
    """The scoping lives in the repository, so it cannot be forgotten upstream."""
    repo = GarmentRepository(db, user_id=uuid.uuid4())
    compiled = str(repo.scoped_select())
    assert "garments.user_id" in compiled
    assert "garments.deleted_at IS NULL" in compiled


async def test_repository_require_raises_not_found_for_a_stranger(
    db: AsyncSession, client: httpx.AsyncClient, auth: Any
) -> None:
    user_a = await make_user_via_token(client, auth(sub="kc-a6"))
    garment = await make_garment(db, user_id=user_a)
    repo = GarmentRepository(db, user_id=uuid.uuid4())
    with pytest.raises(NotFound):
        await repo.require(garment.id)


def test_routers_do_not_query_garments_directly() -> None:
    """Every wardrobe query filters user_id in the repository, not the router."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "routers" / "wardrobe.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("select(", "sa.select", "db.get(", "session.get("):
        assert forbidden not in source, f"router builds its own query: {forbidden}"


# --------------------------------------------------------------------------- #
# listing, filtering, pagination
# --------------------------------------------------------------------------- #
async def test_availability_enum_is_exactly_the_four_states() -> None:
    assert AVAILABILITY_VALUES == ("available", "laundry", "unavailable", "archived")


async def test_list_filters_by_category_and_availability(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-f1"))
    await make_garment(db, user_id=user_id, name="shirt", category="tops")
    await make_garment(db, user_id=user_id, name="jeans", category="bottoms")
    await make_garment(
        db, user_id=user_id, name="gym tee", category="tops", availability="laundry"
    )

    tops = await client.get("/v1/wardrobe/garments?category=tops", headers=auth(sub="kc-f1"))
    assert {i["name"] for i in tops.json()["items"]} == {"shirt", "gym tee"}

    laundry = await client.get(
        "/v1/wardrobe/garments?availability=laundry", headers=auth(sub="kc-f1")
    )
    assert [i["name"] for i in laundry.json()["items"]] == ["gym tee"]


async def test_cursor_pagination_walks_every_garment_once(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-f2"))
    for index in range(5):
        await make_garment(db, user_id=user_id, name=f"item-{index}")

    seen: list[str] = []
    url = "/v1/wardrobe/garments?limit=2"
    for _ in range(5):
        page = await client.get(url, headers=auth(sub="kc-f2"))
        assert page.status_code == 200
        body = page.json()
        seen.extend(item["id"] for item in body["items"])
        if not body.get("next_cursor"):
            break
        url = f"/v1/wardrobe/garments?limit=2&cursor={body['next_cursor']}"

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_a_cursor_from_another_user_yields_nothing_of_theirs(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_a = await make_user_via_token(client, auth(sub="kc-f3a"))
    await make_user_via_token(client, auth(sub="kc-f3b"))
    for index in range(3):
        await make_garment(db, user_id=user_a, name=f"a-{index}")

    page = await client.get("/v1/wardrobe/garments?limit=1", headers=auth(sub="kc-f3a"))
    cursor = page.json()["next_cursor"]
    assert cursor

    other = await client.get(
        f"/v1/wardrobe/garments?limit=10&cursor={cursor}", headers=auth(sub="kc-f3b")
    )
    assert other.status_code == 200
    assert other.json()["items"] == []


async def test_a_malformed_cursor_is_a_422_not_a_500(
    client: httpx.AsyncClient, auth: Any
) -> None:
    await make_user_via_token(client, auth(sub="kc-f4"))
    r = await client.get("/v1/wardrobe/garments?cursor=!!!not-base64", headers=auth(sub="kc-f4"))
    assert r.status_code in (400, 422)


# --------------------------------------------------------------------------- #
# create / delete
# --------------------------------------------------------------------------- #
async def test_create_garment_is_owned_by_the_caller(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-c1"))
    r = await client.post(
        "/v1/wardrobe/garments",
        headers=auth(sub="kc-c1"),
        json={"name": "linen shirt", "category": "tops"},
    )
    assert r.status_code == 201, r.text
    garment = await get_garment(db, uuid.UUID(r.json()["id"]))
    assert garment.user_id == user_id
    assert garment.availability == "available"
    assert garment.confirmed_attributes == {}
    assert garment.inferred_attributes == {}


async def test_create_garment_cannot_attach_someone_elses_media(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    from app.models.media_asset import MediaAsset

    user_a = await make_user_via_token(client, auth(sub="kc-c2a"))
    await make_user_via_token(client, auth(sub="kc-c2b"))
    asset = MediaAsset(
        user_id=user_a, kind="garment_photo", content_type="image/jpeg", max_bytes=1024
    )
    db.add(asset)
    await db.commit()

    r = await client.post(
        "/v1/wardrobe/garments",
        headers=auth(sub="kc-c2b"),
        json={"name": "stolen", "category": "tops", "media_asset_id": str(asset.id)},
    )
    assert r.status_code == 404
    assert (await db.scalar(select(func.count()).select_from(Garment))) == 0


async def test_delete_is_a_soft_delete_and_leaves_the_row_invisible(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    user_id = await make_user_via_token(client, auth(sub="kc-d1"))
    garment = await make_garment(db, user_id=user_id)
    assert (
        await client.delete(f"/v1/wardrobe/garments/{garment.id}", headers=auth(sub="kc-d1"))
    ).status_code == 204

    after = await client.get(f"/v1/wardrobe/garments/{garment.id}", headers=auth(sub="kc-d1"))
    assert after.status_code == 404
    listed = await client.get("/v1/wardrobe/garments", headers=auth(sub="kc-d1"))
    assert listed.json()["items"] == []


async def test_wardrobe_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/wardrobe/garments")).status_code == 401


async def test_creating_one_garment_queues_the_work_its_photograph_needs(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A single upload must start the pipeline, not only a bulk one.

    This is the ordinary path through the app: one photograph, one garment.
    It queued nothing, so the garment kept a null category for ever and the
    client, which reads a null category as still-working, showed a spinner
    that never resolved. Only the bulk endpoint was covered, which is exactly
    how the gap survived a green suite.
    """
    from app.models.job import Job
    from app.models.media_asset import MediaAsset

    user_id = await make_user_via_token(client, auth(sub="kc-w-pipeline"))
    asset = MediaAsset(
        user_id=user_id,
        kind="garment_photo",
        status="uploaded",
        content_type="image/jpeg",
        max_bytes=1_000_000,
        storage_key=f"originals/{uuid.uuid4().hex}.jpg",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    created = await client.post(
        "/v1/wardrobe/garments",
        headers=auth(sub="kc-w-pipeline"),
        json={"name": "Linen shirt", "media_asset_id": str(asset.id)},
    )
    assert created.status_code == 201, created.text
    garment_id = created.json()["id"]

    queued = (await db.execute(select(Job))).scalars().all()
    kinds = {
        job.kind
        for job in queued
        if (job.payload or {}).get("garment_id") == garment_id
    }
    assert kinds == {
        "wardrobe.detect_outfit",
        "wardrobe.categorise",
        "wardrobe.remove_background",
    }


async def test_creating_a_garment_without_a_photograph_queues_nothing(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """No photograph, no work. There is nothing for a model to look at."""
    from app.models.job import Job

    await make_user_via_token(client, auth(sub="kc-w-nophoto"))
    created = await client.post(
        "/v1/wardrobe/garments",
        headers=auth(sub="kc-w-nophoto"),
        json={"name": "Hand-entered trousers"},
    )
    assert created.status_code == 201, created.text
    garment_id = created.json()["id"]

    queued = (await db.execute(select(Job))).scalars().all()
    assert not [
        job for job in queued if (job.payload or {}).get("garment_id") == garment_id
    ]
