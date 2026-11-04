"""The thing the question points at has to be in the answer and the picture.

Reported with two screenshots, one turn apart.

A white printed tee was attached and the question was "What pants and
accessories can I wear with this?". The reply named indigo jeans,
cream trousers, brown loafers, a tan tote and an ochre scarf, and the
figure beside it wore trousers, loafers and a scarf **and no top at
all**. The next turn, "Show it as a mannequin", produced "your sand
linen shirt tucked into the indigo straight jeans" - a shirt that had
never been mentioned, in place of the tee the whole conversation was
about.

Both come from the same hole: `AskCreate` carried a question, a pin id
and the history, and had no way at all to name a garment. The
attachment reached the transcript and stopped there. So the model was
handed those words and a hundred-odd wardrobe rows and had to guess
which one "this" was; it guessed, and the figure - drawn from
`verdict.using` - could not show a subject that was in no list.

Three things had to be true, and each is tested here:

  * the request can carry a garment, scoped to its owner;
  * the model is told which garment it is, by id;
  * the outfit contains it **whatever the model returned**, because a
    prompt is a request and this is the guarantee.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import stylist_ask
from app.domain.stylist_answer import build_request
from app.models.garment import Garment
from app.schemas.stylist import AskCreate

from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def _garment(
    db: AsyncSession, *, user_id: uuid.UUID, name: str = "white printed tee"
) -> Garment:
    row = Garment(user_id=user_id, name=name, category="top", availability="available")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# --------------------------------------------------------------------------
# The request can carry it at all.
# --------------------------------------------------------------------------


def test_a_question_can_name_a_garment() -> None:
    """The field whose absence was the whole bug."""
    asked = AskCreate(question="What goes with this?", garment_id=uuid.uuid4())
    assert asked.garment_id is not None


def test_naming_a_garment_stays_optional() -> None:
    """Most questions point at nothing, and must still work."""
    assert AskCreate(question="What should I wear today?").garment_id is None


# --------------------------------------------------------------------------
# Resolving it, scoped to the asker.
# --------------------------------------------------------------------------


async def test_the_subject_resolves_to_its_own_words_and_id(db: AsyncSession) -> None:
    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)

    words, _picture, _type, found = await stylist_ask.about_garment(
        db, user_id=user_id, garment_id=tee.id
    )

    assert words == "white printed tee"
    assert found == tee.id


async def test_another_persons_garment_is_not_resolved(db: AsyncSession) -> None:
    """Scoped like every other id that arrives in a request body.

    `about_post` answers a pin somebody may not see exactly as it
    answers one that does not exist. This does the same.
    """
    owner_id = await make_user(db)
    stranger_id = await make_user(db)
    tee = await _garment(db, user_id=owner_id)

    words, picture, _type, found = await stylist_ask.about_garment(
        db, user_id=stranger_id, garment_id=tee.id
    )

    assert (words, picture, found) == (None, None, None)


async def test_a_deleted_garment_is_not_resolved(db: AsyncSession) -> None:
    from datetime import UTC, datetime

    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)
    tee.deleted_at = datetime.now(UTC)
    await db.commit()

    _words, _picture, _type, found = await stylist_ask.about_garment(
        db, user_id=user_id, garment_id=tee.id
    )
    assert found is None


async def test_naming_nothing_resolves_to_nothing(db: AsyncSession) -> None:
    user_id = await make_user(db)
    assert await stylist_ask.about_garment(db, user_id=user_id, garment_id=None) == (
        None,
        None,
        "image/jpeg",
        None,
    )


async def test_a_garment_with_no_picture_still_gives_its_words(
    db: AsyncSession,
) -> None:
    """Words alone still answer the question.

    The same choice `about_post` makes: a missing picture is a worse
    answer, not a failed one.
    """
    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)
    assert tee.media_asset_id is None

    words, picture, _type, found = await stylist_ask.about_garment(
        db, user_id=user_id, garment_id=tee.id
    )
    assert words == "white printed tee"
    assert picture is None
    assert found == tee.id


# --------------------------------------------------------------------------
# Telling the model, and then making sure.
# --------------------------------------------------------------------------


def test_the_prompt_names_the_subject_and_requires_it() -> None:
    subject_id = uuid.uuid4()
    request = build_request(
        question="What pants and accessories can I wear with this?",
        lines=[],
        subject_id=subject_id,
        subject="white printed tee",
    )
    text = request.messages[-1].content[0]["text"]

    assert "white printed tee" in text, "the model is not told what `this` is"
    assert str(subject_id) in text, "the model cannot put it in `using` without the id"
    assert "must appear in" in text


def test_the_prompt_says_nothing_when_nothing_was_pointed_at() -> None:
    text = build_request(question="What should I wear?", lines=[]).messages[-1].content[0]["text"]
    assert '"this" is their own' not in text


# --------------------------------------------------------------------------
# The guarantee: the subject is worn whatever came back.
# --------------------------------------------------------------------------


class _Says:
    """A model that answers with exactly what it is given."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompt = ""

    async def stream(self, request, *, user_id=None):
        self.prompt = str(request.messages[-1].content)
        yield self.reply


async def _ask(db: AsyncSession, *, user_id, garment_id, reply: str):
    """Run one turn and hand back the final `Asked`."""
    done = None
    async for name, body in stylist_ask.stream_answer(
        db,
        user_id=user_id,
        question="What pants and accessories can I wear with this?",
        post_id=None,
        garment_id=garment_id,
        provider=_Says(reply),
    ):
        if name == "done":
            done = body
    assert done is not None, "the stream never finished"
    return done


async def test_the_subject_is_worn_even_when_the_model_forgets_it(
    db: AsyncSession,
) -> None:
    """The screenshot, as a test.

    The model named trousers, loafers and a scarf and left the tee
    out. That is the answer that produced a figure with no top, and no
    prompt wording prevents it reliably: this is the check that does.
    """
    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)
    trousers = await _garment(db, user_id=user_id, name="cream wide-leg trousers")

    done = await _ask(
        db,
        user_id=user_id,
        garment_id=tee.id,
        reply=(
            '{"answer":"Those go best with your cream wide-leg trousers.",'
            f'"has_match":true,"using":["{trousers.id}"],"missing":[]}}'
        ),
    )

    assert tee.id in done.using, (
        "the garment the question was about is not in the outfit, which is "
        "the figure-with-no-top bug"
    )
    assert trousers.id in done.using, "the model's own choice was dropped"


async def test_the_subject_reads_first_in_the_outfit(db: AsyncSession) -> None:
    """It is what the question is about, so it is the base.

    Order matters downstream: `_outfit_words` builds the render's
    sentence in this order, and the sentence reads as an outfit built
    on the subject rather than one that mentions it last.
    """
    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)
    trousers = await _garment(db, user_id=user_id, name="cream wide-leg trousers")

    done = await _ask(
        db,
        user_id=user_id,
        garment_id=tee.id,
        reply=(f'{{"answer":"These.","has_match":true,"using":["{trousers.id}"],"missing":[]}}'),
    )

    assert done.using[0] == tee.id


async def test_a_subject_the_model_did_name_is_not_duplicated(
    db: AsyncSession,
) -> None:
    """The common case, once the prompt is doing its job."""
    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)

    done = await _ask(
        db,
        user_id=user_id,
        garment_id=tee.id,
        reply=(
            f'{{"answer":"Wear it with these.","has_match":true,"using":["{tee.id}"],"missing":[]}}'
        ),
    )

    assert list(done.using).count(tee.id) == 1


async def test_a_question_about_nothing_adds_nothing(db: AsyncSession) -> None:
    """The guarantee must not invent a subject where there was none."""
    user_id = await make_user(db)
    trousers = await _garment(db, user_id=user_id, name="cream wide-leg trousers")

    done = await _ask(
        db,
        user_id=user_id,
        garment_id=None,
        reply=(f'{{"answer":"These.","has_match":true,"using":["{trousers.id}"],"missing":[]}}'),
    )

    assert done.using == (trousers.id,)


async def test_a_stranger_cannot_force_a_garment_into_their_outfit(
    db: AsyncSession,
) -> None:
    """The guarantee runs on what `about_garment` resolved, not on the input.

    Otherwise naming somebody else's garment id would put it in the
    answer and, through `_outfit_words`, into a paid render prompt.
    """
    owner_id = await make_user(db)
    stranger_id = await make_user(db)
    theirs = await _garment(db, user_id=owner_id)
    mine = await _garment(db, user_id=stranger_id, name="black jeans")

    done = await _ask(
        db,
        user_id=stranger_id,
        garment_id=theirs.id,
        reply=(f'{{"answer":"These.","has_match":true,"using":["{mine.id}"],"missing":[]}}'),
    )

    assert theirs.id not in done.using
    assert done.using == (mine.id,)


# --------------------------------------------------------------------------
# And through to the render: the picture wears what the answer named.
# --------------------------------------------------------------------------


async def test_the_render_prompt_names_the_subject_first(db: AsyncSession) -> None:
    """The last link in the chain the screenshots broke.

    `_outfit_words` turns the plan into the sentence the image model
    is given. The subject is prepended to `wear`, so it reads as the
    garment the outfit is built on rather than an afterthought - and
    more importantly it is in the sentence at all, which is what the
    figure with no top was missing.
    """
    from app.domain.stylist_answer import Verdict, plan_from

    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)
    trousers = await _garment(db, user_id=user_id, name="cream wide-leg trousers")

    # The plan as `stream_answer` builds it once the guarantee has run.
    verdict = Verdict(
        answer="Those go best with your cream wide-leg trousers.",
        has_match=True,
        using=(tee.id, trousers.id),
        missing=(),
    )
    words = await stylist_ask._outfit_words(db, user_id=user_id, plan=plan_from(verdict))

    assert "white printed tee" in words, (
        "the render would draw an outfit without the garment it is about"
    )
    assert "cream wide-leg trousers" in words
    assert words.index("white printed tee") < words.index("cream wide-leg trousers")


async def test_the_render_prompt_carries_no_identifiers(db: AsyncSession) -> None:
    """Prepending an id must not prepend a uuid into the prompt.

    Ids reaching the image model is a bug this file's neighbour was
    written for; the guarantee adds an id to `wear`, so it is worth
    re-checking at this end.
    """
    from app.domain.stylist_answer import Verdict, plan_from

    user_id = await make_user(db)
    tee = await _garment(db, user_id=user_id)

    words = await stylist_ask._outfit_words(
        db,
        user_id=user_id,
        plan=plan_from(Verdict(answer="x", has_match=True, using=(tee.id,), missing=())),
    )

    assert str(tee.id) not in words
    assert "-" not in words.replace("wide-leg", ""), f"an identifier leaked: {words!r}"
