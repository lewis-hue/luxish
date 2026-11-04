"""The whole of "ask the stylist about it": answer, then act.

    1. gather the wardrobe and the pin being asked about
    2. stream the answer, word by word, as it is written
    3. decide, from the same reply, whether they already own this
    4. yes -> queue their own clothes onto their avatar
       no  -> find the missing pieces to buy, and queue those onto it

Steps 2 and 3 are one model call, because they are one judgement -
asking twice would cost twice and could disagree with itself. The
prose streams out of the reply while the structured half is still
arriving (`app.domain.partial_json`).

**The avatar stays queued.** Drawing a person in clothes is 15 to 30
seconds of billed image work and belongs on a worker (ADR-013). Only
the sentence is produced in the request, because somebody is sitting
there waiting to be answered and a sentence takes six.

**Shopping is not the fallback for a failed answer.** It is the
answer to a different question. "You cannot make this from what you
own" is only useful if it is followed by what would - so a `no`
carries the gaps straight into the catalogue and comes back with
things to buy, drawn on the same avatar so they can see it before
they spend anything.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import Any

logger = logging.getLogger(__name__)

#: How many garments go into the prompt.
#:
#: A whole wardrobe is the point - a stylist that can only see twenty
#: of your sixty things will tell you that you own nothing. Capped
#: only so a collector cannot blow the context window.
MOST_GARMENTS = 120


@dataclass
class Asked:
    """Everything one question produced."""

    answer: str = ""
    has_match: bool = False
    using: tuple[uuid.UUID, ...] = ()
    missing: tuple[str, ...] = ()
    #: Things to buy, when they own nothing that works.
    buy: list[Any] = field(default_factory=list)
    #: A picture per named gap, so the look can be shown even when
    #: they own none of it. Drawn once per phrase and shared by
    #: everybody; see `workers.piece_packshot`.
    pieces: list[Any] = field(default_factory=list)
    #: A photorealistic render, when one was explicitly asked for.
    render_id: uuid.UUID | None = None


#: Punctuation the assistant is asked not to use, and then stopped
#: from using.
#:
#: **A prompt is a request; this is the guarantee.** On the product
#: owner's instruction the stylist is told never to write an em dash,
#: and models comply most of the time, which is not the same as
#: complying. The substitution is per character and the character is
#: not part of any word, so it survives being applied to a stream one
#: token at a time with no buffering.
#:
#: An em dash between clauses becomes a comma and a space; where the
#: model already spaced it, the surrounding whitespace collapses so
#: the sentence does not end up with a gap before its comma.
_DASHES = {
    "—": ", ",  # em dash
    "–": ", ",  # en dash
}


def plainly(text: str) -> str:
    """The reply without the punctuation that marks it as written."""
    if not text:
        return text
    for dash, instead in _DASHES.items():
        if dash not in text:
            continue
        # " - " and "- " both collapse to one comma, not two spaces
        # around one.
        text = text.replace(f" {dash} ", instead)
        text = text.replace(f"{dash} ", instead)
        text = text.replace(f" {dash}", instead)
        text = text.replace(dash, instead)
    return text


async def wardrobe_for(db: Any, *, user_id: uuid.UUID, limit: int = MOST_GARMENTS) -> list[Any]:
    """Everything they own and could actually wear.

    The same availability filter the stylist's own candidate query
    uses, so the two cannot disagree about what is in somebody's
    wardrobe.
    """
    import sqlalchemy as sa

    from app.domain.stylist import STYLEABLE_AVAILABILITY
    from app.models.garment import Garment

    return list(
        (
            await db.scalars(
                sa.select(Garment)
                .where(
                    Garment.user_id == user_id,
                    Garment.deleted_at.is_(None),
                    Garment.availability.in_(STYLEABLE_AVAILABILITY),
                )
                .order_by(Garment.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


async def about_post(
    db: Any, *, user_id: uuid.UUID, post_id: uuid.UUID | None
) -> tuple[str | None, bytes | None, str]:
    """What the pin they are asking about is, in words and in pixels.

    The picture is what makes "match the fit above" answerable. The
    words come from the description the app already reads off every
    photograph, so this costs no extra model call.

    **Resolved through `feed.one`, which is the gate.** This read a
    post by id and nothing else, which was a real hole and was found
    by a security review rather than by me: a private account's fit,
    or one by somebody who had blocked the asker, could be named in a
    request and its caption, its machine-read description and its
    photograph would all be handed to the model and described back in
    the answer. The feed refused that exact post to that exact person
    while this handed it over.

    It is the same mistake the discovery pipeline was built to make
    impossible - one gate, applied to every source, because a second
    path that does its own checking is a second chance to forget one.
    A new path was added and it forgot.

    `feed.one` already refuses a deleted post, an unpublished one, a
    private author, a deleted author and a block, in both directions,
    and refuses all of them identically so a 404 confirms nothing.
    """
    if post_id is None:
        return None, None, "image/jpeg"

    import sqlalchemy as sa

    from app.config import get_settings
    from app.domain.feed import one as visible_post
    from app.errors import CapabilityUnavailable
    from app.models.fit_description import FitDescriptionRow
    from app.models.media_asset import MediaAsset
    from app.models.posts import PostMedia
    from app.workers.runner import build_media_store

    seen = await visible_post(db, user_id=user_id, post_id=post_id)
    if seen is None:
        # Not theirs to look at. Indistinguishable from "no such pin",
        # which is the point.
        return None, None, "image/jpeg"
    post = seen.post

    words: str | None = post.caption or None
    described = await db.get(FitDescriptionRow, post_id)
    if described is not None and described.outfit:
        # The machine's reading, which names the pieces. Better input
        # than a caption, which is often a joke.
        words = described.outfit

    link = await db.scalar(
        sa.select(PostMedia).where(PostMedia.post_id == post_id, PostMedia.position == 0)
    )
    if link is None:
        return words, None, "image/jpeg"
    asset = await db.get(MediaAsset, link.media_asset_id)
    if asset is None or not asset.storage_key:
        return words, None, "image/jpeg"

    try:
        store = build_media_store(get_settings())
        data = await store.read(asset)
    except (CapabilityUnavailable, Exception):  # noqa: BLE001
        # No picture is a worse answer, not a failed one.
        return words, None, "image/jpeg"
    return words, data, asset.content_type or "image/jpeg"


async def about_garment(
    db: Any, *, user_id: uuid.UUID, garment_id: uuid.UUID | None
) -> tuple[str | None, bytes | None, str, uuid.UUID | None]:
    """The garment the question is about, in words and in pixels.

    **"This" had no referent.** The composer lets somebody attach one
    of their own clothes and ask about it, and the attachment reached
    the transcript and stopped there: `AskCreate` carried a question,
    a pin id and the history, and no way at all to name a garment. So
    "What pants and accessories can I wear with this?" arrived at the
    model as those words and a wardrobe list, with nothing saying
    which of the hundred-odd rows "this" was.

    The model did what anyone would: it picked something plausible
    and answered about that. Reported with two screenshots - a
    question about a white printed tee answered with trousers, shoes
    and a scarf and a figure wearing no top at all, and then "Show it
    as a mannequin" which produced a sand linen shirt that had never
    been mentioned.

    Returns the subject's id as well as its words, because naming it
    to the model is only half: the id is what lets the outfit be
    checked afterwards, and a prompt is a request rather than a
    guarantee.

    Scoped to the asker, like everything else that resolves an id out
    of a request body. A garment that is not theirs, or is deleted,
    answers as though it were not named - the same shape `about_post`
    uses, so a 404 confirms nothing.
    """
    if garment_id is None:
        return None, None, "image/jpeg", None

    import sqlalchemy as sa

    from app.config import get_settings
    from app.errors import CapabilityUnavailable
    from app.models.garment import Garment
    from app.models.media_asset import MediaAsset
    from app.workers.runner import build_media_store

    garment = await db.scalar(
        sa.select(Garment).where(
            Garment.id == garment_id,
            Garment.user_id == user_id,
            Garment.deleted_at.is_(None),
        )
    )
    if garment is None:
        return None, None, "image/jpeg", None

    words = _plainly(garment) or None

    if garment.media_asset_id is None:
        return words, None, "image/jpeg", garment.id
    asset = await db.get(MediaAsset, garment.media_asset_id)
    if asset is None or not asset.storage_key:
        return words, None, "image/jpeg", garment.id

    try:
        store = build_media_store(get_settings())
        data = await store.read(asset)
    except (CapabilityUnavailable, Exception):  # noqa: BLE001
        # The words alone still answer the question. A missing
        # picture is a worse answer, not a failed one - the same
        # choice `about_post` makes.
        return words, None, "image/jpeg", garment.id
    return words, data, asset.content_type or "image/jpeg", garment.id


async def stream_answer(
    db: Any,
    *,
    user_id: uuid.UUID,
    question: str,
    post_id: uuid.UUID | None,
    provider: Any,
    history: list[tuple[str, str]] | None = None,
    garment_id: uuid.UUID | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """Yield `(event, payload)` as the answer is written and acted on.

    Events, in order:

    - `("token", str)` repeatedly, as the sentence is written
    - `("verdict", Asked)` once the structured half has arrived
    - `("shopping", list)` when there is nothing they own that works
    - `("pieces", list)` a picture per gap, so a look they own none
      of can still be shown rather than only described
    - `("render", uuid)` only when they asked to *see* it, not on
      every answer that happens to name clothes
    - `("done", Asked)` last, always

    A generator rather than a return value because the first token
    has to reach the phone before the last one has been written;
    that is the entire difference between a conversation and a
    spinner.
    """
    from app.domain.partial_json import FieldStream
    from app.domain.stylist_answer import (
        build_request,
        parse,
        plan_from,
        wants_a_picture,
        wardrobe_lines,
    )

    garments = await wardrobe_for(db, user_id=user_id)
    lines = wardrobe_lines(garments)
    owned = {g.id for g in garments}
    words, picture, content_type = await about_post(db, user_id=user_id, post_id=post_id)

    # **What "this" refers to, when they attached one of their own.**
    #
    # A pin wins where both are given: it is the thing on screen. A
    # garment is the other way somebody points at something, and until
    # now it reached the transcript and went no further.
    subject_words, subject_picture, subject_type, subject_id = await about_garment(
        db, user_id=user_id, garment_id=garment_id
    )
    if post_id is None and subject_words:
        words = subject_words
        if subject_picture is not None:
            picture, content_type = subject_picture, subject_type
    # **A pin they may not see is not a pin they asked about.**
    # Dropped here as well as above, so an id that failed the gate
    # cannot still ride along on the avatar render as
    # `source_post_id` and reappear attached to the result.
    if words is None and picture is None:
        post_id = None

    request = build_request(
        question=question,
        lines=lines,
        about=words,
        image=picture,
        content_type=content_type,
        history=history,
        subject_id=subject_id,
        subject=subject_words,
    )

    reader = FieldStream("answer")
    try:
        async for chunk in provider.stream(request, user_id=user_id):
            fresh = reader.feed(chunk)
            if fresh:
                yield "token", plainly(fresh)
    except Exception as caught:  # noqa: BLE001 - reported, not swallowed
        logger.warning("the stylist could not answer: %s", caught)
        yield "token", ("I could not reach the stylist just then. Try me again in a moment.")
        yield "done", Asked(answer="")
        return

    verdict = parse(reader.raw, owned=owned)
    plan = plan_from(verdict)

    # **The subject is worn, whatever the model returned.**
    #
    # Telling it "this must appear in `using`" is a request. This is
    # the guarantee, and the two screenshots that prompted it show why
    # a request is not enough: a question about a white printed tee
    # produced trousers, loafers and a scarf, and the figure beside it
    # wore no top, because the tee was in neither `using` nor the
    # picture. An outfit built around a garment that is not in the
    # outfit is the one answer that cannot be right.
    #
    # The same move as `plainly` stripping em dashes the prompt
    # already forbids: ask, then make sure.
    #
    # Prepended, not appended: it is what the question is about, so it
    # reads first in the sentence the renderer is given and is drawn
    # as the base the rest is built on.
    if subject_id is not None and subject_id not in plan.wear:
        plan = replace(plan, wear=(subject_id, *plan.wear))
        verdict = replace(verdict, using=(subject_id, *verdict.using))

    out = Asked(
        answer=verdict.answer,
        has_match=verdict.has_match,
        using=verdict.using,
        missing=verdict.missing,
    )

    # The prose may never have streamed - a vendor that buffers, or a
    # reply that arrived in one chunk after the reader had given up.
    # Sending it now is better than an empty bubble.
    if not reader.text and verdict.answer:
        yield "token", plainly(verdict.answer)

    yield "verdict", out

    if plan.look_for:
        out.buy = await _shop_for(
            db,
            user_id=user_id,
            wants=plan.look_for,
            # The look narrows the search from 'every cream
            # trouser' to the right cut and weight.
            look=verdict.answer,
        )
        yield "shopping", out.buy

        # **And a picture of each one, so the answer can be seen.**
        #
        # The reported failure: told they own none of it, linked
        # three shops, and shown nothing - while every reply around
        # it carries a figure wearing the look. An answer that only
        # says no is not an answer somebody can act on.
        #
        # These are drawn once per phrase and shared by every
        # account, so the second person to wonder about white
        # sneakers waits for a row lookup. That is what makes
        # showing it affordable; a render per person per question
        # was not, which is why the one above this was removed.
        out.pieces = await _picture_gaps(db, user_id=user_id, wants=plan.look_for)
        if out.pieces:
            yield "pieces", out.pieces

    # **A photoreal render only when somebody asked to see one.**
    #
    # This used to run on every answer that named clothes: a billed
    # image call of fifteen to thirty seconds, queued beside a
    # composite that draws the same look instantly and for nothing
    # and is wearing the *actual* garments rather than a model's
    # impression of a description of them. Slower, dearer and less
    # accurate than the thing already on the screen next to it.
    #
    # It is not gone, because "generate a mannequin wearing the
    # outfits above" is a real request and the composite is not an
    # answer to it. It is gated: `wants_a_picture` reads the question
    # for somebody asking to be *shown* rather than told, so the
    # spend follows an intention instead of a side effect.
    if wants_a_picture(question):
        render_id = await _draw(db, user_id=user_id, plan=plan, post_id=post_id)
        if render_id is not None:
            out.render_id = render_id
            yield "render", render_id

    yield "done", out


@dataclass(frozen=True)
class _WebOffer:
    """A web result, shaped the way `routers.stylist._offer` reads one.

    Duck-typed rather than converted, because that serialiser already
    accepts anything with these names and inventing a second shape
    would mean two things to keep in step.
    """

    product_id: str
    title: str
    retailer: str
    url: str
    match_label: str | None = None


async def _shop_for(
    db: Any, *, user_id: uuid.UUID, wants: tuple[str, ...], look: str | None = None
) -> list[Any]:
    """Where to buy each missing piece.

    **The catalogue first, then the open web.** The internal
    catalogue is a seeded table: when it has the thing it is the
    better answer, because it carries a real price and stock. Most of
    the time it does not have it, and before this that meant "where
    to get them" came back empty under a list of things to get - the
    question asked and visibly unanswered, which is how it was
    reported.

    The web lookup takes the gap *and the look*, which is what makes
    it worth doing: "cream trousers" alone returns every cream
    trouser made, and the look narrows it to the right cut.

    One search per gap, never one merged search: "cream trousers" and
    "a tan tote" are two different shelves and merging them returns
    whichever had more stock.
    """
    from app.domain import shopping
    from app.domain.web_shopping import where_to_buy

    found: list[Any] = []
    seen: set[Any] = set()
    unmet: list[str] = []

    for want in wants:
        matches: list[Any] = []
        try:
            matches = await shopping.search(db, colour=None, aesthetics=(want,))
        except Exception as caught:  # noqa: BLE001
            logger.warning("catalogue search failed for %r: %s", want, caught)
        kept = 0
        for match in matches[:3]:
            key = getattr(match, "product_id", None) or id(match)
            if key in seen:
                continue
            seen.add(key)
            found.append(match)
            kept += 1
        if kept == 0:
            unmet.append(want)

    if unmet:
        # Never raises and never blocks the reply: the answer has
        # already streamed, and this is an extra underneath it.
        for result in await where_to_buy(unmet, look=look):
            for shop in result.shops:
                if shop.url in seen:
                    continue
                seen.add(shop.url)
                found.append(
                    _WebOffer(
                        product_id=shop.url,
                        title=shop.title,
                        retailer=shop.seller,
                        url=shop.url,
                        match_label=result.gap,
                    )
                )

    return found


async def _picture_gaps(db: Any, *, user_id: uuid.UUID, wants: Any) -> list[Any]:
    """A drawable picture for each gap, as the client composes them.

    Failure-tolerant on purpose. This hangs off an answer that has
    already arrived and already carries its shops; a drawing service
    that is down must cost the pictures and nothing else.
    """
    from app.workers.piece_packshot import ensure

    try:
        rows = await ensure(db, phrases=list(wants), user_id=user_id)
    except Exception as caught:  # noqa: BLE001
        logger.info("could not picture the gaps: %s", caught)
        return []
    return [
        {
            "phrase": row.phrase,
            "slot": row.slot,
            "state": row.state,
            "asset_id": str(row.media_asset_id) if row.media_asset_id else None,
        }
        for row in rows
    ]


async def _draw(
    db: Any, *, user_id: uuid.UUID, plan: Any, post_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Queue a picture, for somebody who asked to see one.

    **Two gates, and both were learned the hard way.**

    `wants_a_picture` is upstream: this used to run on every answer
    that named clothes, so an ordinary "does this go with that" cost
    a billed render nobody had asked for and nobody waited for.

    `plan.renders` is the one here, and it went unconsulted for two
    reported releases. The plan had already worked out that a verdict
    owning nothing should not be drawn, and this function drew it
    anyway as long as the sentence named any garment - so somebody
    told "you have none of this" waited half a minute for a picture
    of clothes they would have to go and buy.

    Returns None rather than raising when there is no avatar to dress
    yet: being told "you own this" is useful on its own, and a person
    who has not made an avatar should get an answer, not an error.
    """
    from app.domain import avatar_renders

    if not plan.renders:
        return None

    outfit = await _outfit_words(db, user_id=user_id, plan=plan)
    if not outfit:
        return None
    try:
        render = await avatar_renders.request(
            db,
            user_id=user_id,
            kind="try_on",
            outfit=outfit,
            source_post_id=post_id,
            note=("from your wardrobe" if plan.verdict.has_match else "pieces to look for"),
            # **The stylist draws on the mannequin, always.**
            #
            # Asked for by the product owner, and it is the right
            # default for what this picture is: an answer to "what
            # would these look like together", shown on a neutral
            # figure. Somebody who has switched the rest of the app
            # onto their likeness has said where *they* want to be
            # seen, which is a different question from what an
            # assistant's illustration should stand on.
            on_mannequin=True,
        )
    except Exception as caught:  # noqa: BLE001
        logger.info("no avatar to dress: %s", caught)
        return None
    return getattr(render, "id", None)


def _plainly(garment: Any) -> str:
    """One garment, as somebody would say it out loud.

    **Not `stylist.describe`.** That builds the catalogue line the
    language model reads - "shirt seeded white colour business
    formality all_year seasons cotton material" - which is the right
    shape for a wardrobe listing and nonsense in an image prompt.
    The name is what a person typed or what categorisation wrote,
    and it is already a noun phrase: "cream wide-leg trousers".
    """
    name = (getattr(garment, "name", None) or "").strip()
    if name:
        return name.lower()
    # No name yet. Build the shortest honest phrase from what
    # categorisation found, rather than drawing nothing.
    found = getattr(garment, "effective_attributes", None) or {}
    colour = str(found.get("colour") or "").strip()
    kind = str(found.get("category") or getattr(garment, "category", "") or "").strip()
    return " ".join(word for word in (colour, kind) if word)


async def _outfit_words(db: Any, *, user_id: uuid.UUID, plan: Any) -> str:
    """What to draw, in the words the renderer actually needs.

    **Two bugs lived here and both produced the same symptom: a
    rendered figure wearing something the answer never mentioned.**
    Reported with a screenshot of one reply containing an olive
    quilted jacket and chinos above a composite of a black dress, a
    tote and loafers.

    *It branched on the wrong thing.* `plan.wear` is filled in both
    the yes branch and the close branch - "you own this" and "not
    this, but these of yours would carry it" - and this function
    only read it when `has_match` was true. The close branch is the
    common one, so most renders drew `look_for`, which is the list
    of things to go and *buy*: a different outfit from the one the
    reply recommended and the one the composite beside it drew.

    *And it sent uuids into an image prompt.* The comment here
    claimed the worker resolved them against the wardrobe. It does
    not - `avatar_jobs` passes `render.outfit` through as words - so
    the prompt contained thirty-six character identifiers and the
    model drew whatever it liked around them.

    So the ids are resolved here, where the session is, and the
    pieces they were told to buy are appended rather than
    substituted. The render and the composite now describe the same
    outfit, because they are built from the same two lists.
    """
    from app.models.garment import Garment

    said: list[str] = []
    if plan.wear:
        import sqlalchemy as sa

        owned = {
            garment.id: garment
            for garment in await db.scalars(
                sa.select(Garment).where(
                    Garment.id.in_(list(plan.wear)),
                    Garment.user_id == user_id,
                    Garment.deleted_at.is_(None),
                )
            )
        }
        # In the order the stylist named them, which is the order the
        # sentence reads in.
        for one in plan.wear:
            garment = owned.get(one)
            if garment is None:
                continue
            words = _plainly(garment)
            if words:
                said.append(words)

    # The additions, named in plain words already.
    said.extend(phrase.strip() for phrase in plan.look_for if phrase.strip())
    return ", ".join(said)


__all__ = [
    "MOST_GARMENTS",
    "Asked",
    "about_post",
    "stream_answer",
    "plainly",
    "wardrobe_for",
]
