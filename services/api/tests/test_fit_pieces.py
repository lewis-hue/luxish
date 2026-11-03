"""Each garment in a posted fit, cut out and kept.

Trying a fit on used to read the photograph, write a sentence about
the clothes, and pay an image model to draw somebody wearing that
sentence - so the result looked *like* the outfit rather than being
it. These are the clothes themselves, cut from the photograph they
were worn in, so the stylised figure wears the real thing.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import posts as posts_domain
from app.models.fit_description import FitDescriptionRow, FitPieceRow
from app.models.media_asset import MediaAsset
from app.models.posts import Post, PostMedia
from app.workers.fit_pieces import cut_pieces, piece_prompt
from tests.test_garment_media import make_user


def png(width: int = 400, height: int = 600) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (120, 110, 100)).save(buffer, format="PNG")
    return buffer.getvalue()


class Store:
    """An in-memory object store, enough for one photograph."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def read(self, asset: Any) -> bytes:
        return self.objects[asset.storage_key]

    async def write(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data


class Cuts:
    """A segmenter that returns a cut-out for every prompt."""

    def __init__(self, *, fails: set[str] | None = None) -> None:
        self.fails = fails or set()
        self.prompts: list[str] = []

    async def cutout(self, *, prompt: str, **_: Any) -> Any:
        self.prompts.append(prompt)
        if prompt in self.fails:
            from app.providers.segmentation import SegmentationUnavailable

            raise SegmentationUnavailable("no subject found")

        class Result:
            image = png(200, 300)
            records = ()

        return Result()


async def _described(
    db: AsyncSession, *, pieces: list[dict[str, Any]]
) -> tuple[Post, Store]:
    owner = await make_user(db)
    store = Store()

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
    store.objects[asset.storage_key] = png()

    post = Post(user_id=owner, caption="", state="published", screen_mode="seed")
    db.add(post)
    await db.flush()
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    db.add(
        FitDescriptionRow(
            post_id=post.id, outfit="an outfit", caption=None, pieces=pieces
        )
    )
    await db.commit()
    await db.refresh(post)
    return post, store


PIECES = [
    {"name": "tee", "colour": "lilac", "category": "tops"},
    {"name": "cargo trousers", "colour": "olive", "category": "bottoms"},
]


# --------------------------------------------------------------------------- #
# cutting
# --------------------------------------------------------------------------- #
def test_the_prompt_leads_with_the_colour() -> None:
    # The order the describing model writes them in, and the order
    # that disambiguates fastest when a photograph holds two of the
    # same thing.
    assert piece_prompt({"colour": "black", "name": "boots"}) == "black boots"
    assert piece_prompt({"name": "boots"}) == "boots"
    assert piece_prompt({"category": "tops"}) == "tops"
    assert piece_prompt({}) == "the garment"


async def test_each_described_piece_is_cut_from_the_photograph(
    db: AsyncSession,
) -> None:
    post, store = await _described(db, pieces=PIECES)
    segmenter = Cuts()

    assert await cut_pieces(db, post_id=post.id, segmenter=segmenter, store=store) == 2
    assert segmenter.prompts == ["lilac tee", "olive cargo trousers"]

    rows = (
        await db.scalars(
            sa.select(FitPieceRow)
            .where(FitPieceRow.post_id == post.id)
            .order_by(FitPieceRow.position)
        )
    ).all()
    assert [row.name for row in rows] == ["tee", "cargo trousers"]
    assert len({row.media_asset_id for row in rows}) == 2


async def test_cutting_the_same_fit_twice_pays_once(db: AsyncSession) -> None:
    """A re-dispatched job must not buy a second set."""
    post, store = await _described(db, pieces=PIECES)

    assert await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store) == 2
    again = Cuts()
    assert await cut_pieces(db, post_id=post.id, segmenter=again, store=store) == 0
    assert again.prompts == []


async def test_a_piece_that_will_not_cut_costs_only_itself(
    db: AsyncSession,
) -> None:
    """A bag half behind a hip is the normal case, not a failure."""
    post, store = await _described(db, pieces=PIECES)
    segmenter = Cuts(fails={"olive cargo trousers"})

    assert await cut_pieces(db, post_id=post.id, segmenter=segmenter, store=store) == 1
    rows = (
        await db.scalars(sa.select(FitPieceRow).where(FitPieceRow.post_id == post.id))
    ).all()
    assert [row.name for row in rows] == ["tee"]


async def test_a_fit_nobody_has_described_is_not_cut(db: AsyncSession) -> None:
    post, store = await _described(db, pieces=[])
    assert await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store) == 0


# --------------------------------------------------------------------------- #
# who may read one
# --------------------------------------------------------------------------- #
async def _a_piece_asset(db: AsyncSession, post: Post) -> uuid.UUID:
    row = await db.scalar(sa.select(FitPieceRow).where(FitPieceRow.post_id == post.id))
    assert row is not None
    return row.media_asset_id


async def test_a_piece_of_a_published_fit_is_readable_by_anybody(
    db: AsyncSession,
) -> None:
    """The point of cutting them: the figure has to be able to wear them.

    A piece is not in `post_media`, so the gate for the fit's own
    photographs answers no - and without a gate of its own nobody
    could read one, including the author.
    """
    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)
    asset_id = await _a_piece_asset(db, post)

    stranger = await make_user(db)
    assert await posts_domain.piece_is_published_to(
        db, viewer_id=stranger, asset_id=asset_id
    )
    assert await posts_domain.piece_is_published_to(
        db, viewer_id=post.user_id, asset_id=asset_id
    )


async def test_a_piece_stops_being_readable_when_its_fit_does(
    db: AsyncSession,
) -> None:
    """The whole reason this is a join and not a flag.

    Every way a fit stops being public is a change to the post, and
    a flag on the piece would have to be cleared on all of them.
    """
    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)
    asset_id = await _a_piece_asset(db, post)
    stranger = await make_user(db)

    post.visibility = "private"
    await db.commit()
    assert not await posts_domain.piece_is_published_to(
        db, viewer_id=stranger, asset_id=asset_id
    )
    # Still the author's to see, the same exception the cover gets.
    assert await posts_domain.piece_is_published_to(
        db, viewer_id=post.user_id, asset_id=asset_id
    )


async def test_taking_the_fit_down_closes_its_pieces(db: AsyncSession) -> None:
    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)
    asset_id = await _a_piece_asset(db, post)
    stranger = await make_user(db)

    await db.execute(sa.update(Post).where(Post.id == post.id).values(state="removed"))
    await db.commit()
    assert not await posts_domain.piece_is_published_to(
        db, viewer_id=stranger, asset_id=asset_id
    )


async def test_blocking_closes_the_pieces_too(db: AsyncSession) -> None:
    from app.domain.moderation import block

    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)
    asset_id = await _a_piece_asset(db, post)
    stranger = await make_user(db)

    await block(db, blocker_id=stranger, blocked_id=post.user_id)
    assert not await posts_domain.piece_is_published_to(
        db, viewer_id=stranger, asset_id=asset_id
    )


async def test_an_unrelated_asset_is_not_a_piece_of_anything(
    db: AsyncSession,
) -> None:
    stranger = await make_user(db)
    assert not await posts_domain.piece_is_published_to(
        db, viewer_id=stranger, asset_id=uuid.uuid4()
    )


async def test_a_fit_carries_its_cut_pieces_to_the_client(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """The figure cannot wear what it is not told about."""
    headers = auth(sub="kc-pieces-api")
    await client.post("/v1/auth/session", headers=headers)

    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)

    body = (await client.get(f"/v1/feed/{post.id}", headers=headers)).json()
    assert [piece["name"] for piece in body["pieces"]] == ["tee", "cargo trousers"]
    assert all(piece["media_asset_id"] for piece in body["pieces"])
    # Taxonomy facts only; the author's own words never travel here.
    assert set(body["pieces"][0]) == {
        "media_asset_id",
        "position",
        "name",
        "colour",
        "category",
    }


async def test_a_fit_nobody_has_cut_reports_no_pieces(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """Empty is the honest answer, and a client offers photoreal then."""
    headers = auth(sub="kc-pieces-api-2")
    await client.post("/v1/auth/session", headers=headers)
    post, _ = await _described(db, pieces=PIECES)

    body = (await client.get(f"/v1/feed/{post.id}", headers=headers)).json()
    assert body["pieces"] == []


# --------------------------------------------------------------------------- #
# shopping the pieces
# --------------------------------------------------------------------------- #
async def test_shopping_a_fit_is_a_section_per_garment(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """What "shop the look" was always supposed to mean.

    The row pushed the generic recommendations screen - a shelf
    built from gaps in your own wardrobe, which has nothing to do
    with the photograph it was tapped from.
    """
    headers = auth(sub="kc-shop-fit")
    await client.post("/v1/auth/session", headers=headers)
    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)

    r = await client.get(f"/v1/shopping/for-fit/{post.id}", headers=headers)
    assert r.status_code == 200, r.text
    # The catalogue is empty in this test, so an empty list is the
    # honest answer - and it is not padded with "popular".
    assert r.json()["sections"] == []


async def test_shopping_a_fit_nobody_may_see_is_a_404(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """The sections name the garments in it.

    Handing them over would describe a private fit to somebody who
    cannot open it.
    """
    headers = auth(sub="kc-shop-fit-2")
    await client.post("/v1/auth/session", headers=headers)
    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)

    post.visibility = "private"
    await db.commit()

    r = await client.get(f"/v1/shopping/for-fit/{post.id}", headers=headers)
    assert r.status_code == 404


async def test_shopping_a_fit_costs_no_model_call(db: AsyncSession) -> None:
    """The identification is already done and already paid for.

    Reading a fit writes down each garment because the try-on and
    the caption both need it, once per post for everybody. This is a
    catalogue query per piece and nothing else.
    """
    from app.domain import shopping

    post, store = await _described(db, pieces=PIECES)
    await cut_pieces(db, post_id=post.id, segmenter=Cuts(), store=store)

    sections = await shopping.like_this_fit(
        db, user_id=post.user_id, post_id=post.id
    )
    assert sections == []


async def test_a_fit_with_no_cut_pieces_has_nothing_to_shop(
    db: AsyncSession,
) -> None:
    from app.domain import shopping

    post, _ = await _described(db, pieces=PIECES)
    assert (
        await shopping.like_this_fit(db, user_id=post.user_id, post_id=post.id) == []
    )
