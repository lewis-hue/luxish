"""Answering the question, before making anything.

**The reported failure.** Somebody opened a fit, tapped "ask the
stylist about it", and typed "Do I have any outfits that could match
the fit above?". They got an avatar wearing clothes and an offer to
render it photorealistically. Nobody had answered them.

The cause is not subtle: `style` is the intent every question falls
into, its own description says it will "answer a question about what
to wear", and the implementation has only ever built an outfit. The
description promised a conversation and the code shipped a render.

**So the answer comes first, and the picture is a consequence of it.**

    question -> verdict -> yes: show the outfit they already own
                        -> no:  name what is missing, find it to buy,
                                and show that on them

`Verdict.has_match` is what branches. It is produced by a structured
call with the person's actual wardrobe in the prompt, so "yes" means
"these specific garments you own", not "probably". `using` carries the
garment ids and is re-validated against the wardrobe before anything
is rendered - the standing rule in this codebase is that an id a model
returns is never trusted, and a model that invents one here would put
clothes somebody does not own onto their avatar.

**Why this one call is allowed to happen in a request.** Every other
model call in this service is queued, because Cloud Run request
timeouts are the constraint and image work takes 15 to 30 seconds
(ADR-013). This is a short text completion against a wardrobe list -
a second or two - and the person is sitting there waiting for it. The
expensive half, the avatar, is still queued. Cheap and interactive in
the request; expensive and durable on a worker.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import (
    AIMessage,
    AIRequest,
    Capabilities,
    JsonSchemaFormat,
)

ANSWER_MODEL = "muse-spark-1.3"
ANSWER_PROMPT_VERSION = "ans-1"
ANSWER_PURPOSE = "stylist.answer"

#: Reasoning tokens come out of this before any content is emitted, so
#: too small a budget returns nothing rather than something short.
ANSWER_MAX_TOKENS = 2048

#: Warm but not inventive. This is a judgement about somebody's own
#: clothes, and the same wardrobe should get the same verdict twice.
ANSWER_TEMPERATURE = 0.2

#: How hard to think before speaking. Deliberately the least.
#:
#: **Measured, not guessed.** Reasoning tokens are emitted before any
#: content, so on a streamed reply they are dead air: at the service
#: default of `low` the first word reached the screen after 13.8
#: seconds and the whole answer took 14.6 - fourteen seconds of
#: spinner followed by eight tenths of a second of streaming, which
#: is a worse experience than not streaming at all.
#:
#: This is a judgement about a list of clothes, not a reasoning
#: problem. `minimal` is the setting that makes the stream a stream.
ANSWER_REASONING = "minimal"

#: How many pieces may be suggested for buying when nothing matches.
#:
#: Three. A list of ten is a shopping trip nobody takes, and the
#: honest answer to "you have nothing for this" is usually one or two
#: specific gaps.
MOST_GAPS = 3

#: How many earlier turns go into the prompt.
#:
#: Ten is about five exchanges, which is as far back as anything in
#: a styling conversation stays relevant - and the wardrobe list,
#: which is the bulk of the prompt, is sent once regardless.
MOST_HISTORY = 10

ANSWER_SYSTEM = (
    "You are a stylist talking to one person about their own wardrobe. "
    "You are given every garment they own that is available to wear, "
    "and a photograph or description of a look they are asking about.\n\n"
    "Answer their question directly and briefly, the way a friend who "
    "knows clothes would. Two or three sentences. No preamble, no "
    "restating the question, no bullet lists.\n\n"
    "Then decide honestly whether they can put this look together "
    "from what they own. Be strict: a rough approximation is not a "
    "match. If they cannot, say so plainly - telling somebody they "
    "own something they do not is the one thing that makes this "
    "useless to them.\n\n"
    # **The middle answer, which the schema always allowed and the
    # prompt never asked for.** `has_match` false with `using`
    # filled in is "not this look, but these of yours would carry
    # it" - the most useful thing a stylist says, and the only
    # branch that ends in a picture they can act on. Without this
    # paragraph the model treated the decision as yes-or-no and the
    # branch was dead code.
    "There is a third answer and it is often the right one: they "
    "cannot make this exact look, but they own pieces that would "
    "carry its idea. When that is true, set has_match false, name "
    "those pieces in `using`, and say in your answer what to wear "
    "and how it differs. Leave `missing` empty in that case - do "
    "not send somebody shopping for what you have just told them "
    "they can already wear.\n\n"
    "Fill `missing` only when they own nothing that works at all."
)

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "has_match", "using", "missing"],
    "properties": {
        # First in the schema so it is first out of a streamed
        # response: the prose is what somebody reads while the rest
        # is still arriving.
        "answer": {
            "type": "string",
            "description": "Two or three sentences, spoken to them.",
        },
        "has_match": {
            "type": "boolean",
            "description": "Whether their own clothes can make this look.",
        },
        "using": {
            "type": "array",
            "description": "Garment ids from the list, when has_match.",
            "items": {"type": "string"},
        },
        "missing": {
            "type": "array",
            "description": (
                "What they would need to buy, as short shopping "
                "phrases - 'wide-leg cream trousers'. Only when there "
                "is no match."
            ),
            "items": {"type": "string"},
        },
    },
}

ANSWER_RESPONSE_FORMAT = JsonSchemaFormat(
    name="stylist_answer", json_schema=ANSWER_SCHEMA
)


@dataclass(frozen=True)
class Verdict:
    """What the stylist decided, and what it is going to do about it."""

    answer: str
    has_match: bool
    #: Garments they own that make the look. Already re-validated.
    using: tuple[uuid.UUID, ...] = ()
    #: Short shopping phrases for what is missing.
    missing: tuple[str, ...] = ()

    @property
    def shops(self) -> bool:
        """Whether this verdict should go looking for things to buy."""
        return not self.has_match and bool(self.missing)


@dataclass
class WardrobeLine:
    """One garment, as the model sees it. Id plus plain words."""

    garment_id: uuid.UUID
    words: str

    def __str__(self) -> str:
        return f"{self.garment_id} - {self.words}"


def wardrobe_lines(garments: list[Any]) -> list[WardrobeLine]:
    """The wardrobe as text, with ids the model can point back at."""
    from app.domain.stylist import describe

    return [
        WardrobeLine(garment_id=g.id, words=describe(g)) for g in garments
    ]


def build_request(
    *,
    question: str,
    lines: list[WardrobeLine],
    about: str | None = None,
    image: bytes | None = None,
    content_type: str = "image/jpeg",
    history: list[tuple[str, str]] | None = None,
) -> AIRequest:
    """The one call. Wardrobe in, verdict out.

    The picture is attached when there is one, because "match the fit
    above" is unanswerable from a caption - and a caption is all this
    had before.
    """
    catalogue = (
        "\n".join(str(line) for line in lines)
        or "(this person has nothing available in their wardrobe)"
    )
    said = question.strip() or "What should I wear?"

    parts: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"They asked: {said}\n\n"
                + (f"About this look: {about}\n\n" if about else "")
                + "Everything they own and can wear right now, as "
                "`id - description`:\n"
                f"{catalogue}\n\n"
                "Use only ids from that list in `using`. Never invent "
                "one."
            ),
        }
    ]
    if image is not None:
        from app.workers.fit_vision import data_uri, prepare_image

        sent, sent_type = prepare_image(image, content_type=content_type)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": data_uri(sent, content_type=sent_type)},
            }
        )

    # What was said before, as real turns rather than pasted into
    # the question. A model handles its own message format better
    # than a transcript inside one prompt, and it keeps the wardrobe
    # list attached to the latest question where it belongs.
    said: list[AIMessage] = []
    for who, text in (history or [])[-MOST_HISTORY:]:
        if not text.strip():
            continue
        said.append(
            AIMessage(
                "assistant" if who == "stylist" else "user",
                text.strip()[:2000],
            )
        )

    return AIRequest(
        model=ANSWER_MODEL,
        system=ANSWER_SYSTEM,
        messages=(*said, AIMessage("user", parts)),
        needs=Capabilities(
            text_in=True,
            image_in=image is not None,
            text_out=True,
            structured_output=True,
        ),
        response_format=ANSWER_RESPONSE_FORMAT,
        max_completion_tokens=ANSWER_MAX_TOKENS,
        reasoning_effort=ANSWER_REASONING,
        temperature=ANSWER_TEMPERATURE,
        prompt_version=ANSWER_PROMPT_VERSION,
        purpose=ANSWER_PURPOSE,
    )


def parse(text: str | None, *, owned: set[uuid.UUID]) -> Verdict:
    """The model's JSON as a `Verdict`, with every id re-validated.

    **An id a model returns is never trusted.** That is the standing
    rule in this codebase and it is load-bearing here: a hallucinated
    garment id would put clothes somebody does not own onto their own
    avatar and tell them they already had them.

    A malformed answer is a `has_match: False` with no suggestions
    rather than an exception - the person asked a question and should
    get words back, not a failure.
    """
    try:
        payload = json.loads(text or "")
    except (TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return Verdict(
            answer=(
                "I could not read that one. Ask me again and I will "
                "take another look."
            ),
            has_match=False,
        )

    answer = str(payload.get("answer") or "").strip()
    raw_using = payload.get("using")
    using: list[uuid.UUID] = []
    if isinstance(raw_using, list):
        for item in raw_using:
            try:
                found = uuid.UUID(str(item))
            except (TypeError, ValueError):
                continue
            # The re-validation. Anything not in their wardrobe is
            # dropped silently rather than rendered.
            if found in owned and found not in using:
                using.append(found)

    raw_missing = payload.get("missing")
    missing = (
        tuple(
            str(m).strip()[:80]
            for m in raw_missing
            if isinstance(m, str) and m.strip()
        )[:MOST_GAPS]
        if isinstance(raw_missing, list)
        else ()
    )

    claimed = bool(payload.get("has_match"))
    # **A match with nothing behind it is not a match.** The model
    # saying "yes" while naming no garment it was shown is the exact
    # shape of a confident wrong answer, and acting on it would
    # render an empty avatar.
    has_match = claimed and bool(using)

    if claimed and not using:
        answer = answer or ""
        answer = (
            answer + " "
            if answer and not answer.endswith((".", "!", "?"))
            else answer
        )

    return Verdict(
        answer=answer
        or ("Nothing in your wardrobe quite does it, but here is what would."),
        has_match=has_match,
        using=tuple(using),
        missing=() if has_match else missing,
    )


@dataclass
class Plan:
    """What happens after the verdict. The branch, named."""

    verdict: Verdict
    #: Garments to draw on their avatar. Owned, or bought-and-drawn.
    wear: tuple[uuid.UUID, ...] = ()
    #: Shopping phrases to go looking for.
    look_for: tuple[str, ...] = field(default_factory=tuple)

    @property
    def renders(self) -> bool:
        """Whether a picture is worth paying for.

        **Only when they own the clothes.** This used to render for a
        "no" as well, on the argument that "what would this look like
        on me" is the question underneath the question. It is - and
        the answer to it, when the person owns none of the garments,
        is a picture of somebody else's outfit on their figure. They
        cannot wear it, cannot buy it from the picture and learn
        nothing they did not learn from the sentence above it. It
        costs a paid render and half a minute to say the same "no"
        again, slower.

        A "no" ends in words and somewhere to buy. A "yes", or a
        "not quite, but these would do it", ends in a picture -
        because then there is something to actually put on.
        """
        return bool(self.wear)


def plan_from(verdict: Verdict) -> Plan:
    """Turn a verdict into the two things that follow it.

    **Three outcomes, not two.**

    *Yes* - they own what the look needs. Wear it, and draw it.

    *Close* - they own nothing exact, but the model named pieces of
    theirs that would carry the look. Wear those, draw those, and do
    not send them shopping: they already have something to try.

    *No* - nothing of theirs works. Words and somewhere to buy, and
    **no picture**. Drawing somebody else's outfit on their figure
    when they own none of it teaches them nothing the sentence did
    not, and costs a paid render to say it.
    """
    if verdict.has_match:
        return Plan(verdict=verdict, wear=verdict.using)
    # The middle case. `using` can be non-empty under a "no": the
    # model names pieces that are close without claiming they match.
    if verdict.using:
        return Plan(verdict=verdict, wear=verdict.using)
    return Plan(verdict=verdict, look_for=verdict.missing)


__all__ = [
    "ANSWER_MAX_TOKENS",
    "ANSWER_MODEL",
    "ANSWER_PROMPT_VERSION",
    "ANSWER_RESPONSE_FORMAT",
    "ANSWER_SCHEMA",
    "ANSWER_SYSTEM",
    "MOST_GAPS",
    "Plan",
    "Verdict",
    "WardrobeLine",
    "build_request",
    "parse",
    "plan_from",
    "wardrobe_lines",
]
