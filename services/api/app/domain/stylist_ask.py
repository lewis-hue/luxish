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
from dataclasses import dataclass, field
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
    #: The queued avatar, if one was started.
    render_id: uuid.UUID | None = None


async def wardrobe_for(
    db: Any, *, user_id: uuid.UUID, limit: int = MOST_GARMENTS
) -> list[Any]:
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
        sa.select(PostMedia).where(
            PostMedia.post_id == post_id, PostMedia.position == 0
        )
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


async def stream_answer(
    db: Any,
    *,
    user_id: uuid.UUID,
    question: str,
    post_id: uuid.UUID | None,
    provider: Any,
    history: list[tuple[str, str]] | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """Yield `(event, payload)` as the answer is written and acted on.

    Events, in order:

    - `("token", str)` repeatedly, as the sentence is written
    - `("verdict", Asked)` once the structured half has arrived
    - `("shopping", list)` when there is nothing they own that works
    - `("render", uuid)` when an avatar has been queued
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
        wardrobe_lines,
    )

    garments = await wardrobe_for(db, user_id=user_id)
    lines = wardrobe_lines(garments)
    owned = {g.id for g in garments}
    words, picture, content_type = await about_post(
        db, user_id=user_id, post_id=post_id
    )
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
    )

    reader = FieldStream("answer")
    try:
        async for chunk in provider.stream(request, user_id=user_id):
            fresh = reader.feed(chunk)
            if fresh:
                yield "token", fresh
    except Exception as caught:  # noqa: BLE001 - reported, not swallowed
        logger.warning("the stylist could not answer: %s", caught)
        yield "token", (
            "I could not reach the stylist just then. Try me again in a moment."
        )
        yield "done", Asked(answer="")
        return

    verdict = parse(reader.raw, owned=owned)
    plan = plan_from(verdict)
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
        yield "token", verdict.answer

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


async def _draw(
    db: Any, *, user_id: uuid.UUID, plan: Any, post_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Queue the avatar, whichever branch we are on.

    Returns None rather than raising when there is no avatar to dress
    yet: being told "you own this" is useful on its own, and a person
    who has not made an avatar should not get an error instead of an
    answer.
    """
    from app.domain import avatar_renders
    from app.domain.avatar_renders import TRY_ON_JOB_KIND  # noqa: F401

    outfit = _outfit_words(plan)
    if not outfit:
        return None
    try:
        render = await avatar_renders.request(
            db,
            user_id=user_id,
            kind="try_on",
            outfit=outfit,
            source_post_id=post_id,
            note=(
                "from your wardrobe"
                if plan.verdict.has_match
                else "pieces to look for"
            ),
        )
    except Exception as caught:  # noqa: BLE001
        logger.info("no avatar to dress: %s", caught)
        return None
    return getattr(render, "id", None)


def _outfit_words(plan: Any) -> str:
    """What to draw, as the sentence the renderer wants."""
    if plan.verdict.has_match:
        # The ids are resolved to names by the worker, which already
        # holds the wardrobe; sending names from here would be a
        # second source of truth about what a garment is called.
        return ", ".join(str(g) for g in plan.wear)
    return ", ".join(plan.look_for)


__all__ = [
    "MOST_GARMENTS",
    "Asked",
    "about_post",
    "stream_answer",
    "wardrobe_for",
]
