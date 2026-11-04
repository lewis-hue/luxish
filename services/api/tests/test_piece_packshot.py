"""Showing somebody a look they own none of.

**The reported failure.** "How would baggy skater shorts with white
sneakers and a white t-shirt look on me?" was answered with: you do
not own those, here are three places to buy them - and nothing to
look at. Every other reply in that thread carries a figure wearing
the look, composed on the device from the pieces' own cut-outs, and
a cut-out only exists for a garment somebody has photographed. So
the one answer where seeing it would have helped most was the only
answer with no picture.

Each named piece now gets a plain packshot drawn from its words.
Three properties carry it, and each is a way it could cost more than
it is worth:

* it is drawn **once for everybody**, keyed on the normalised
  phrase - a per-user cache would turn a one-off cost into a cost
  per person per question, which is the pattern this release has
  been removing;
* a phrase with **nowhere to go on the figure** is never drawn,
  because a picture with no slot is spend for nothing;
* a failure **costs the picture only** - the answer and its shop
  links have already arrived and must not be taken down by a
  drawing service.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CapabilityUnavailable
from app.models.job import Job
from app.models.media_asset import MediaAsset
from app.models.piece_packshot import PiecePackshot, phrase_key
from app.providers.base import GeneratedImage
from app.workers.packshot import PACKSHOT_MEDIA_KIND
from app.workers.piece_packshot import (
    PIECE_PACKSHOT_JOB_KIND,
    PIECE_PROMPT,
    draw_piece,
    ensure,
    slot_for_phrase,
)

from tests.test_garment_media import InMemoryMediaStore, make_user

pytestmark = pytest.mark.anyio


class Artist:
    def __init__(self, *, image: bytes = b"a-garment") -> None:
        self.image = image
        self.asked: list[str] = []

    async def draw(self, phrase: str, **_: Any) -> GeneratedImage:
        self.asked.append(phrase)
        return GeneratedImage(data=self.image, content_type="image/webp")


class Refuses:
    async def draw(self, *_: Any, **__: Any) -> GeneratedImage:
        raise CapabilityUnavailable(
            "no generation", detail={"capability": "image_generate"}
        )


# --------------------------------------------------------------------------- #
# One picture per garment, for everybody
# --------------------------------------------------------------------------- #
def test_the_same_garment_asked_three_ways_is_one_key() -> None:
    """**The whole saving is in this function.**

    "White Sneakers", "white sneakers" and "white  sneakers." have
    to land on one row, or the cache is a per-user cache with extra
    steps and a generation per person per question.
    """
    assert (
        phrase_key("White Sneakers")
        == phrase_key("white  sneakers.")
        == phrase_key("WHITE SNEAKERS!")
        == "white sneakers"
    )


def test_two_different_garments_stay_two_rows() -> None:
    """**Not stemmed and not reordered, deliberately.**

    "white shirt dress" and "white dress shirt" are different
    garments. A normaliser that merged them would serve the wrong
    picture, which is a worse failure than a miss.
    """
    assert phrase_key("white shirt dress") != phrase_key("white dress shirt")


def test_a_sentence_is_capped_rather_than_stored_whole() -> None:
    """Past ten words the model illustrates a paragraph, and the key
    stops being something a second person would ever match."""
    assert len(phrase_key(" ".join(["word"] * 40)).split()) == 10


# --------------------------------------------------------------------------- #
# Where it goes on the figure
# --------------------------------------------------------------------------- #
def test_each_kind_of_garment_finds_its_slot() -> None:
    assert slot_for_phrase("baggy skater shorts") == "bottoms"
    assert slot_for_phrase("white t shirt") == "tops"
    assert slot_for_phrase("white sneakers") == "shoes"
    assert slot_for_phrase("camel overcoat") == "outerwear"
    assert slot_for_phrase("gold pendant necklace") == "accessories"


def test_a_dress_is_a_top_before_a_shirt_can_claim_it() -> None:
    """Order within the table is load-bearing: "shirt dress" is one
    garment covering the body, not a shirt."""
    assert slot_for_phrase("white shirt dress") == "tops"


def test_words_that_name_no_garment_get_no_slot() -> None:
    assert slot_for_phrase("a nice holiday") is None
    assert slot_for_phrase("") is None


# --------------------------------------------------------------------------- #
# Queuing
# --------------------------------------------------------------------------- #
async def test_asking_for_three_pieces_queues_three_drawings(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)

    rows = await ensure(
        db,
        phrases=["baggy skater shorts", "a white t-shirt", "white sneakers"],
        user_id=user_id,
    )
    await db.commit()

    assert [row.phrase for row in rows] == [
        "baggy skater shorts",
        # The hyphen is punctuation, so "a white t-shirt" and "a
        # white t shirt" are one row.
        "a white t shirt",
        "white sneakers",
    ]
    assert all(row.state == "queued" for row in rows)
    jobs = (await db.scalars(sa.select(Job).where(Job.kind == PIECE_PACKSHOT_JOB_KIND))).all()
    assert len(jobs) == 3


async def test_the_second_person_to_ask_pays_nothing(db: AsyncSession) -> None:
    """**The point of the whole table.**

    One drawing per garment in the life of the product, not one per
    person per question.
    """
    mine = await make_user(db)
    theirs = await make_user(db)

    first = await ensure(db, phrases=["white sneakers"], user_id=mine)
    await db.commit()
    second = await ensure(db, phrases=["White Sneakers"], user_id=theirs)
    await db.commit()

    assert first[0].id == second[0].id, "the same row, so the same picture"
    jobs = (await db.scalars(sa.select(Job).where(Job.kind == PIECE_PACKSHOT_JOB_KIND))).all()
    assert len(jobs) == 1, "and only one drawing was ever queued"


async def test_a_phrase_with_nowhere_to_go_is_not_drawn(
    db: AsyncSession,
) -> None:
    """A picture with no slot on the figure is spend for nothing."""
    user_id = await make_user(db)

    rows = await ensure(db, phrases=["a nice holiday", "confidence"], user_id=user_id)
    await db.commit()

    assert rows == []
    assert (await db.scalars(sa.select(Job))).all() == []


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
async def _queued(db: AsyncSession, phrase: str = "white sneakers") -> tuple[Any, Job]:
    user_id = await make_user(db)
    [row] = await ensure(db, phrases=[phrase], user_id=user_id)
    await db.commit()
    job = await db.scalar(
        sa.select(Job).where(Job.kind == PIECE_PACKSHOT_JOB_KIND)
    )
    assert job is not None
    return row, job


async def test_the_drawing_lands_on_the_row(db: AsyncSession) -> None:
    row, job = await _queued(db)
    store = InMemoryMediaStore()

    out = await draw_piece(db, job, artist=Artist(), store=store)
    await db.commit()
    await db.refresh(row)

    assert out["drawn"] is True
    assert row.state == "ready"
    assert row.media_asset_id is not None
    shot = await db.get(MediaAsset, row.media_asset_id)
    assert shot is not None and shot.kind == PACKSHOT_MEDIA_KIND


async def test_it_is_drawn_from_the_phrase_and_nothing_else(
    db: AsyncSession,
) -> None:
    _row, job = await _queued(db, "brown penny loafers")
    artist = Artist()

    await draw_piece(db, job, artist=artist, store=InMemoryMediaStore())

    assert artist.asked == ["brown penny loafers"]


def test_the_prompt_asks_for_one_garment_alone_on_white() -> None:
    """**Every clause here is load-bearing for the composite**, which
    lays the result into a fixed box over a flat figure.

    A model asked for "white sneakers" will happily return a person
    wearing them, and a person laid over a figure is two people.
    There is no background removal downstream either, so anything
    that is not the garment is drawn as part of the garment.
    """
    said = PIECE_PROMPT.format(phrase="white sneakers").lower()
    assert "no person" in said and "no model" in said
    assert "pure white background" in said and "no shadow" in said
    # It sits beside links to real shops, so anything that reads as a
    # label would be a claim about a product.
    assert "no logos" in said and "no text" in said


async def test_a_drawing_that_fails_says_so_on_the_row(
    db: AsyncSession,
) -> None:
    row, job = await _queued(db)

    out = await draw_piece(db, job, artist=Refuses(), store=InMemoryMediaStore())
    await db.commit()
    await db.refresh(row)

    assert out["drawn"] is False
    assert row.state == "failed"
    assert row.media_asset_id is None


async def test_drawing_twice_does_not_pay_twice(db: AsyncSession) -> None:
    row, job = await _queued(db)
    store = InMemoryMediaStore()
    await draw_piece(db, job, artist=Artist(), store=store)
    await db.commit()

    second = Artist()
    out = await draw_piece(db, job, artist=second, store=store)

    assert out["reason"] == "already_present"
    assert second.asked == []


async def test_a_row_deleted_under_the_job_is_not_a_crash(
    db: AsyncSession,
) -> None:
    _row, job = await _queued(db)
    await db.execute(sa.delete(PiecePackshot))
    await db.commit()

    out = await draw_piece(db, job, artist=Artist(), store=InMemoryMediaStore())

    assert out == {"drawn": False, "reason": "row_deleted"}


async def test_a_job_with_no_row_named_is_not_a_crash(db: AsyncSession) -> None:
    from datetime import UTC, datetime

    job = Job(
        kind=PIECE_PACKSHOT_JOB_KIND,
        payload={},
        state="queued",
        available_at=datetime.now(UTC),
    )
    db.add(job)
    await db.flush()

    out = await draw_piece(db, job, artist=Artist(), store=InMemoryMediaStore())

    assert out == {"drawn": False, "reason": "no_packshot_id"}


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
def test_drawing_a_garment_sits_on_the_paid_queue() -> None:
    from app.queue.celery_app import QUEUE_AI, QUEUE_BY_PREFIX

    assert QUEUE_BY_PREFIX["garment.piece_packshot"] == QUEUE_AI


def test_the_id_namespace_cannot_collide_with_a_garment() -> None:
    """The client keys these `gap:<phrase>` beside real garment ids,
    which are uuids. A phrase can never parse as one."""
    with pytest.raises(ValueError):
        uuid.UUID("gap:white sneakers")
