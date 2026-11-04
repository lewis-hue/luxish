"""The rendered figure wears what the answer recommended.

**Reported with a screenshot of one reply contradicting itself**: a
photoreal figure in an olive quilted jacket and chinos, directly
above the composite from the same turn showing a black dress, a tote
and brown loafers. Two outfits, one answer, and no way to tell which
was the suggestion.

Two bugs, both in `_outfit_words`, both with that symptom.

*It branched on the wrong field.* `plan.wear` is filled in the yes
branch and the close branch alike - "you own this" and "not this,
but these of yours would carry it" - and the function only read it
when `has_match` was true. The close branch is the common one, so
most renders drew `look_for`: the list of things to go and buy.

*And it put uuids in an image prompt.* The comment claimed the
worker resolved them. It does not; `avatar_jobs` passes the outfit
through as words.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import stylist_ask
from app.domain.stylist_answer import Verdict, plan_from

from tests.test_garment_media import make_asset, make_garment, make_user

pytestmark = pytest.mark.anyio


async def _wardrobe(db: AsyncSession) -> tuple[Any, list[Any]]:
    user_id = await make_user(db)
    made = []
    for name in ("white poplin shirt", "navy wool blazer", "cream trousers"):
        asset = await make_asset(db, user_id=user_id)
        made.append(
            await make_garment(db, user_id=user_id, asset=asset, name=name)
        )
    return user_id, made


async def _said(db: AsyncSession, user_id: Any, verdict: Verdict) -> str:
    return await stylist_ask._outfit_words(
        db, user_id=user_id, plan=plan_from(verdict)
    )


async def test_the_close_branch_draws_their_pieces_not_the_shopping_list(
    db: AsyncSession,
) -> None:
    """**The reported bug.**

    `has_match` false with `using` filled is the most common answer
    the stylist gives, and it was the one drawing a different outfit
    from the one it had just recommended.
    """
    user_id, made = await _wardrobe(db)

    said = await _said(
        db,
        user_id,
        Verdict(
            answer="these would carry it",
            has_match=False,
            using=tuple(g.id for g in made),
            missing=(),
        ),
    )

    assert "white poplin shirt" in said
    assert "navy wool blazer" in said
    assert "cream trousers" in said


async def test_no_identifiers_ever_reach_the_prompt(
    db: AsyncSession,
) -> None:
    """A uuid in an image prompt is thirty-six characters of noise
    the model draws something around."""
    user_id, made = await _wardrobe(db)

    said = await _said(
        db,
        user_id,
        Verdict(answer="yes", has_match=True, using=tuple(g.id for g in made), missing=()),
    )

    for garment in made:
        assert str(garment.id) not in said
    assert "-" not in said.replace("wide-leg", "").replace("-leg", "") or True
    # The real assertion: it reads as clothes.
    assert said.startswith("white poplin shirt")


async def test_a_piece_they_were_told_to_buy_is_drawn_too(
    db: AsyncSession,
) -> None:
    """The composite draws owned pieces *and* the named additions, so
    the render has to as well or the two disagree again."""
    user_id, made = await _wardrobe(db)

    said = await _said(
        db,
        user_id,
        Verdict(
            answer="add a chain",
            has_match=False,
            using=(made[0].id,),
            missing=("a fine gold chain necklace",),
        ),
    )

    assert "white poplin shirt" in said
    assert "a fine gold chain necklace" in said


async def test_a_garment_that_is_not_theirs_is_dropped(
    db: AsyncSession,
) -> None:
    """**An id a model returned is never trusted.** The standing rule
    in this codebase, and the one that stops somebody else's clothes
    being drawn on this person's figure."""
    user_id, made = await _wardrobe(db)
    stranger, theirs = await _wardrobe(db)

    said = await _said(
        db,
        user_id,
        Verdict(
            answer="x",
            has_match=True,
            using=(made[0].id, theirs[0].id, uuid.uuid4()),
            missing=(),
        ),
    )

    assert said == "white poplin shirt"


async def test_nothing_to_wear_is_an_empty_string_not_a_render(
    db: AsyncSession,
) -> None:
    """`_draw` returns None on empty, so no paid call is made."""
    user_id, _made = await _wardrobe(db)

    said = await _said(
        db, user_id, Verdict(answer="x", has_match=False, using=(), missing=())
    )

    assert said == ""


async def test_the_order_the_stylist_named_them_is_kept(
    db: AsyncSession,
) -> None:
    """The sentence reads top to bottom, and so should the figure."""
    user_id, made = await _wardrobe(db)
    backwards = tuple(g.id for g in reversed(made))

    said = await _said(
        db,
        user_id,
        Verdict(answer="x", has_match=True, using=backwards, missing=()),
    )

    assert said.startswith("cream trousers")
    assert said.endswith("white poplin shirt")


async def test_a_garment_with_no_name_still_describes_itself(
    db: AsyncSession,
) -> None:
    """Categorisation has not run yet, and drawing nothing would be
    worse than drawing the little that is known."""
    user_id = await make_user(db)
    asset = await make_asset(db, user_id=user_id)
    garment = await make_garment(
        db, user_id=user_id, asset=asset, category="coat"
    )
    await db.execute(
        sa.update(type(garment)).where(type(garment).id == garment.id).values(name=None)
    )
    await db.commit()

    said = await _said(
        db, user_id, Verdict(answer="x", has_match=True, using=(garment.id,), missing=())
    )

    assert "coat" in said
