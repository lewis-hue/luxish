"""Reading a posted fit: what the clothes are, in words.

One vision pass, three jobs it does at once:

**The caption names the clothes.** A caption like "saturday" tells Discover
nothing and reaches nobody. A caption that says "cream linen shirt over wide
black trousers" is the content-matching signal: it is what a person searching
for linen shirts is searching with, and what the grouping below keys on.

**The hashtags come from the garments, not from a mood.** Groups on Discover
are keyed on tags, so tags decided by what is actually in the photograph are
what make the board true. The vocabulary is closed to the groups that exist
(``feed.GROUP_TAGS``) plus plain garment words, so a tag either lands
somewhere people browse or describes a thing.

**The outfit sentence is what the avatar wears.** Try-on edits the asker's
own avatar, and the edit needs the outfit in words. Describing the fit once
and storing it means tapping "Try it on" spends one image call rather than a
vision call and an image call, and means two people trying the same fit pay
for the description once between them.

**Nothing here describes the person.** The prompt forbids it by name, and the
schema has no field for it. Three reasons, all of them hard rules in this
repository: appearance is asked and never inferred; the output rides into an
image prompt, where a description of somebody's face would be a way to
generate their likeness; and the person in the photograph posted an outfit,
not a portrait for a model to study.

**A caption the author wrote is never overwritten.** Their words are theirs.
The description is stored alongside, and the generated caption is offered
only where the author left the field empty.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.config import get_settings
from app.errors import ApiError
from app.providers.base import (
    AIMessage,
    AIRequest,
    Capabilities,
    JsonSchemaFormat,
)
from app.providers.segmentation import data_uri
from app.workers.categorise import prepare_image

#: Bumped when the prompt or the schema below changes, so a stored
#: description records which wording produced it.
FIT_VISION_PROMPT_VERSION = "1"

FIT_VISION_PURPOSE = "post.describe"

#: The text model that takes an image. Named rather than configured, like
#: every other model in this service whose shape has a test behind it.
FIT_VISION_MODEL = "muse-spark-1.3"

#: Generous on purpose. Reasoning tokens are drawn from this budget
#: before any content is emitted, so a tight limit returns an empty
#: response rather than a short one - which is exactly what 600 did.
FIT_VISION_MAX_TOKENS = 2048

#: Low, not zero. Describing a garment is not a creative task, and two runs
#: over the same photograph disagreeing about the colour of a coat would
#: make the stored description unreliable as a search key.
FIT_VISION_TEMPERATURE = 0.2

#: The most garments read out of one photograph. A fit with more than this
#: many nameable pieces is a flat lay of a wardrobe, and the tail adds
#: nothing to either search or the try-on sentence.
MAX_PIECES = 8

#: The most tags kept. Enough to land in two or three groups and still say
#: what the clothes are.
MAX_TAGS = 8

MAX_CAPTION = 140
MAX_OUTFIT = 400


FIT_VISION_SYSTEM = (
    "You are a fashion cataloguer. You look at a photograph of an outfit "
    "and name the clothes in it, plainly and accurately, the way a shop "
    "assistant describes stock. You never describe the person wearing the "
    "clothes."
)

FIT_VISION_USER_TEXT = (
    "Describe the clothes in this photograph.\n\n"
    "Name each visible garment: what it is, its colour, and its fabric or "
    "cut if either is clear. Then write one sentence that describes the "
    "whole outfit as worn, suitable for telling an illustrator what to "
    "draw. Then write a short caption, under fifteen words, that names the "
    "main pieces. Then list tags.\n\n"
    "Rules:\n"
    "- Do not describe the person: not their face, body, build, skin, hair, "
    "age, gender or identity. Describe only clothes, shoes and accessories.\n"
    "- Do not guess a brand, and do not read out any logo or text.\n"
    "- Use plain lowercase words for tags, no punctuation, no hash.\n"
    "- If something is cut off or unclear, leave it out rather than "
    "inventing it.\n"
    "- Write in plain English with no sales language and no adjectives of "
    "praise.\n"
    # On the product owner's instruction. The caption is shown under
    # a pin as though a person wrote it, and an em dash is the
    # clearest tell that one did not. It is also the only
    # punctuation here with no plainer substitute already in use.
    "- Never use an em dash or an en dash. Use a comma or a full stop."
)


#: Strict mode needs a root object with `additionalProperties: false`, and
#: every property listed in `required` (verified; see `JsonSchemaFormat`).
FIT_VISION_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pieces", "outfit", "caption", "tags"],
    "properties": {
        "pieces": {
            "type": "array",
            "maxItems": MAX_PIECES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "colour", "category"],
                "properties": {
                    "name": {"type": "string", "maxLength": 60},
                    "colour": {"type": "string", "maxLength": 30},
                    # Left open rather than enumerated: this is a free
                    # photograph rather than a wardrobe upload, so forcing
                    # it into the wardrobe taxonomy would throw away detail
                    # that the caption and the tags both want.
                    "category": {"type": "string", "maxLength": 40},
                },
            },
        },
        "outfit": {"type": "string", "maxLength": MAX_OUTFIT},
        "caption": {"type": "string", "maxLength": MAX_CAPTION},
        "tags": {
            "type": "array",
            "maxItems": MAX_TAGS,
            "items": {"type": "string", "maxLength": 30},
        },
    },
}

FIT_VISION_RESPONSE_FORMAT = JsonSchemaFormat(
    name="fit_description", json_schema=FIT_VISION_SCHEMA
)


@dataclass(frozen=True)
class Piece:
    name: str
    colour: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class FitDescription:
    """What a photograph of an outfit contains, in words."""

    #: Each garment, as named. Rides with a try-on so the finished picture
    #: can be labelled without a second model call.
    pieces: tuple[Piece, ...] = ()
    #: The whole outfit as one sentence. This is what the avatar wears.
    outfit: str = ""
    #: A caption naming the main pieces. Offered only where the author
    #: wrote none of their own.
    caption: str = ""
    #: Plain lowercase words. Normalised and grouped by `domain.feed`.
    tags: tuple[str, ...] = ()
    model: str | None = None
    prompt_version: str = FIT_VISION_PROMPT_VERSION
    #: Kept so a stored row says where its words came from.
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """True when there is enough here to be worth storing.

        An outfit sentence is the one field everything else depends on: the
        try-on needs it, and a description without it is a row that looks
        complete and cannot be used.
        """
        return bool(self.outfit.strip())


def _text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _tag(value: Any) -> str | None:
    """One tag, normalised the way the feed normalises them.

    Deliberately strict: anything that is not letters and digits is dropped
    rather than cleaned up, because a tag is a join key and a nearly-right
    one silently makes its own group of size one.
    """
    word = str(value or "").strip().lower().lstrip("#")
    word = "".join(ch for ch in word if ch.isalnum())
    return word if 2 <= len(word) <= 30 else None


def parse_description(
    payload: Mapping[str, Any], *, model: str | None = None
) -> FitDescription:
    """Read the model's JSON into the stored shape.

    Every field is re-validated here rather than trusted from the schema:
    strict mode constrains shape, not content, and these strings end up in
    a caption, a search index and an image prompt.
    """
    pieces: list[Piece] = []
    for item in payload.get("pieces") or ():
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"), limit=60)
        if not name:
            continue
        pieces.append(
            Piece(
                name=name,
                colour=_text(item.get("colour"), limit=30) or None,
                category=_text(item.get("category"), limit=40) or None,
            )
        )
        if len(pieces) >= MAX_PIECES:
            break

    seen: set[str] = set()
    tags: list[str] = []
    for raw in payload.get("tags") or ():
        tag = _tag(raw)
        if tag is not None and tag not in seen:
            seen.add(tag)
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break

    return FitDescription(
        pieces=tuple(pieces),
        outfit=_text(payload.get("outfit"), limit=MAX_OUTFIT),
        caption=_text(payload.get("caption"), limit=MAX_CAPTION),
        tags=tuple(tags),
        model=model,
        raw=dict(payload),
    )


@runtime_checkable
class FitReader(Protocol):
    async def describe(
        self, *, image: bytes, content_type: str, user_id: uuid.UUID | None = None
    ) -> FitDescription: ...


class MetaFitReader:
    """The description, through the vendor's text model with an image in.

    Thin on purpose: it owns the call and the refusal. The prompt and the
    schema are module constants, so changing what is asked for is a change
    to data rather than to a code path.
    """

    def __init__(
        self,
        provider: Any,
        *,
        model: str = FIT_VISION_MODEL,
        prompt_version: str = FIT_VISION_PROMPT_VERSION,
    ) -> None:
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version

    def build_request(self, *, image: bytes, content_type: str) -> AIRequest:
        sent, sent_type = prepare_image(image, content_type=content_type)
        return AIRequest(
            model=self._model,
            system=FIT_VISION_SYSTEM,
            messages=(
                AIMessage(
                    "user",
                    [
                        {"type": "text", "text": FIT_VISION_USER_TEXT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_uri(sent, content_type=sent_type)
                            },
                        },
                    ],
                ),
            ),
            needs=Capabilities(
                text_in=True, image_in=True, text_out=True, structured_output=True
            ),
            response_format=FIT_VISION_RESPONSE_FORMAT,
            max_completion_tokens=FIT_VISION_MAX_TOKENS,
            reasoning_effort=get_settings().model_reasoning_effort,
            temperature=FIT_VISION_TEMPERATURE,
            prompt_version=self._prompt_version,
            purpose=FIT_VISION_PURPOSE,
        )

    async def describe(
        self, *, image: bytes, content_type: str, user_id: uuid.UUID | None = None
    ) -> FitDescription:
        response = await self._provider.complete(
            self.build_request(image=image, content_type=content_type),
            user_id=user_id,
        )
        try:
            payload = json.loads(response.text or "")
        except (TypeError, ValueError) as exc:
            raise ApiError(
                "The reader did not return JSON.",
                status_code=502,
                code="malformed_description",
            ) from exc
        if not isinstance(payload, Mapping):
            raise ApiError(
                "The reader returned a non-object.",
                status_code=502,
                code="malformed_description",
            )
        return parse_description(payload, model=response.model)


__all__ = [
    "FIT_VISION_MAX_TOKENS",
    "FIT_VISION_MODEL",
    "FIT_VISION_PROMPT_VERSION",
    "FIT_VISION_PURPOSE",
    "FIT_VISION_RESPONSE_FORMAT",
    "FIT_VISION_SCHEMA",
    "MAX_CAPTION",
    "MAX_OUTFIT",
    "MAX_PIECES",
    "MAX_TAGS",
    "FitDescription",
    "FitReader",
    "MetaFitReader",
    "Piece",
    "parse_description",
]
