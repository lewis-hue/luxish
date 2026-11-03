"""A posted picture, brought into the shape the app draws it in.

A landscape photograph kept its landscape frame all the way to the
board, where the shell is upright - so it was letterboxed or cropped
at display time, every time anybody looked at it.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media_asset import MediaAsset
from app.models.posts import Post, PostMedia
from app.workers.post_shape import SHAPE_JOB_KIND, shape_post_cover
from tests.test_garment_media import make_user


def png(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 110, 130)).save(buffer, format="PNG")
    return buffer.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as opened:
        return opened.size


class Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.writes = 0

    async def read(self, asset: Any) -> bytes:
        return self.objects[asset.storage_key]

    async def write(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data
        self.writes += 1


class Job:
    def __init__(self, post_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.payload = {"post_id": str(post_id)}


async def _posted(
    db: AsyncSession, *, width: int, height: int, record_size: bool = True
) -> tuple[Post, MediaAsset, Store]:
    owner = await make_user(db)
    store = Store()

    asset = MediaAsset(
        user_id=owner,
        kind="outfit_photo",
        status="ready",
        content_type="image/png",
        width=width if record_size else None,
        height=height if record_size else None,
        max_bytes=1,
        byte_size=1,
        storage_key=f"users/{owner}/media/{uuid.uuid4().hex}",
        version=1,
        publication_consent=True,
    )
    db.add(asset)
    await db.flush()
    store.objects[asset.storage_key] = png(width, height)

    post = Post(user_id=owner, caption="", state="published", screen_mode="seed")
    db.add(post)
    await db.flush()
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    await db.commit()
    await db.refresh(post)
    return post, asset, store


async def _cover(db: AsyncSession, post: Post) -> MediaAsset:
    link = await db.scalar(
        sa.select(PostMedia).where(
            PostMedia.post_id == post.id, PostMedia.position == 0
        )
    )
    assert link is not None
    found = await db.get(MediaAsset, link.media_asset_id)
    assert found is not None
    return found


async def test_a_landscape_post_is_stood_upright(db: AsyncSession) -> None:
    """The complaint: a landscape picture kept its frame to the board."""
    post, original, store = await _posted(db, width=900, height=600)

    outcome = await shape_post_cover(db, Job(post.id), store=store)
    assert outcome["state"] == "reshaped"

    cover = await _cover(db, post)
    assert cover.id != original.id
    assert (cover.width or 0) < (cover.height or 0), "upright now"


async def test_the_original_is_kept_exactly_as_uploaded(
    db: AsyncSession,
) -> None:
    """**It never replaces what the author took.**

    The description is pinned to the original precisely so a vision
    model is not handed a rotated photograph, and the original has
    to still be there for that to mean anything.
    """
    post, original, store = await _posted(db, width=900, height=600)
    before = store.objects[original.storage_key]

    await shape_post_cover(db, Job(post.id), store=store)

    await db.refresh(original)
    assert original.deleted_at is None
    assert store.objects[original.storage_key] == before
    assert size_of(store.objects[original.storage_key]) == (900, 600)


async def test_a_picture_already_in_the_shell_is_left_alone(
    db: AsyncSession,
) -> None:
    """Almost every photograph, and it should cost nothing."""
    post, original, store = await _posted(db, width=600, height=800)

    outcome = await shape_post_cover(db, Job(post.id), store=store)
    assert outcome["state"] == "already_fits"
    assert store.writes == 0

    cover = await _cover(db, post)
    assert cover.id == original.id


async def test_running_it_twice_reshapes_once(db: AsyncSession) -> None:
    """A re-dispatched job must not stack a second copy."""
    post, _, store = await _posted(db, width=900, height=600)

    first = await shape_post_cover(db, Job(post.id), store=store)
    assert first["state"] == "reshaped"
    after_first = store.writes

    second = await shape_post_cover(db, Job(post.id), store=store)
    assert second["state"] == "already_fits"
    assert store.writes == after_first


async def test_the_shaped_copy_carries_the_same_consent(
    db: AsyncSession,
) -> None:
    """The same picture in a different frame, not a new decision."""
    post, original, store = await _posted(db, width=900, height=600)
    original.publication_consent = False
    await db.commit()

    await shape_post_cover(db, Job(post.id), store=store)
    cover = await _cover(db, post)
    assert cover.publication_consent is False
    assert cover.user_id == original.user_id
    assert cover.kind == original.kind


async def test_a_post_with_no_picture_is_finished_not_failed(
    db: AsyncSession,
) -> None:
    owner = await make_user(db)
    post = Post(user_id=owner, caption="", state="published", screen_mode="seed")
    db.add(post)
    await db.commit()

    outcome = await shape_post_cover(db, Job(post.id), store=Store())
    assert outcome["state"] == "no_picture"


async def test_an_unmeasured_picture_is_measured_rather_than_reread(
    db: AsyncSession,
) -> None:
    """Dimensions are missing on older uploads.

    Without recording what it found, this job would read the same
    bytes again on every re-dispatch for ever.
    """
    post, original, store = await _posted(
        db, width=600, height=800, record_size=False
    )

    outcome = await shape_post_cover(db, Job(post.id), store=store)
    assert outcome["state"] == "already_fits"

    await db.refresh(original)
    assert (original.width, original.height) == (600, 800)


async def test_publishing_queues_the_shaping(db: AsyncSession) -> None:
    """Otherwise nothing ever runs it.

    It cannot happen in the upload handler: in a deployment the
    client PUTs straight to object storage and this service never
    sees the bytes.
    """
    from app.models.job import Job as JobRow

    owner = await make_user(db)
    asset = MediaAsset(
        user_id=owner,
        kind="outfit_photo",
        status="ready",
        content_type="image/png",
        max_bytes=1,
        byte_size=1,
        storage_key=f"users/{owner}/media/{uuid.uuid4().hex}",
        version=1,
        publication_consent=False,
    )
    db.add(asset)
    await db.commit()

    from app.domain import posts as posts_domain

    post = await posts_domain.create_post(
        db,
        user_id=owner,
        caption="A fit",
        occasion=None,
        media_asset_ids=[asset.id],
        garment_ids=[],
        product_ids=[],
    )
    await db.commit()

    queued = (
        await db.scalars(
            sa.select(JobRow).where(JobRow.kind == SHAPE_JOB_KIND)
        )
    ).all()
    assert [str(post.id)] == [str(row.payload["post_id"]) for row in queued]
