"""Reading what a photograph is of, through the vendor's vision model.

**Not an embeddings call, because there is no embeddings endpoint.**
`POST /v1/embeddings` is a 404 on every model in the catalogue,
re-verified against the live API on 2026-11-03; ADR-004 recorded the
same in October. What the vendor has is a vision model with
structured output, so the content signal is a closed vocabulary it
fills in rather than a dense vector it emits.

**One cheap call per pin, once.** The model is the cheap one, the
budget is small, and the result is stored - a pin is read when it is
posted and then never again unless the prompt changes. Reading on
every feed request would be absurd; this is a backfill plus a hook on
publish.

**A refusal is a `subject` of `other`, not an exception.** A pin that
could not be read must still appear in the feed: `other` passes every
gate, so an unreadable photograph is ranked by tags and boards as it
was before this existed. Failing closed here would make a vendor
outage look like half the corpus being deleted.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.domain.discovery.subject import (
    FACETS,
    PRESENTATIONS,
    SUBJECTS,
    Reading,
)
from app.providers.base import JsonSchemaFormat

VISION_JOB_KIND = "post.vision"

#: The cheap model. This is a classification into a short closed list,
#: not a reasoning task, and the expensive model costs five times as
#: much for an answer that has eight possible values.
POST_VISION_MODEL = "muse-spark-1.3"

#: Bumped whenever the prompt or the vocabulary changes, so a later
#: change can find every row that predates it.
POST_VISION_PROMPT_VERSION = "pv-1"

POST_VISION_PURPOSE = "post.vision"

#: Room to think before answering.
#:
#: Reasoning tokens come out of this budget *before* any content is
#: emitted, so too tight a number returns an empty response rather
#: than a short one - 600 gave `text: None` on every call when the
#: fit reader was built. 2048 is what works in this codebase.
POST_VISION_MAX_TOKENS = 2048

#: Deterministic. The same photograph must classify the same way on
#: two runs, or a backfill and a re-read disagree about the same pin.
POST_VISION_TEMPERATURE = 0.0

POST_VISION_SYSTEM = (
    "You label photographs for a fashion and interiors app. You answer "
    "only with JSON matching the schema. You never guess at a person's "
    "appearance, age, body or ethnicity, and you never describe them: "
    "you are labelling what the picture is OF, not who is in it."
)

POST_VISION_USER_TEXT = (
    "What is this picture of?\n\n"
    "Pick exactly one `subject` from the list. Use `other` only when it "
    "genuinely fits none of them - it is better than a wrong guess.\n\n"
    "Then pick every `facet` that clearly applies. Choose only from the "
    "list; do not invent words. Three to six is typical. If the picture "
    "is of a room, say so with `subject: interior` even if a person is "
    "standing in it; if it is of what somebody is wearing, say `outfit` "
    "even if the room behind them is striking.\n\n"
    "`note` is one short phrase describing the picture, under twelve "
    "words, for an internal log. Not a caption."
)

#: The vocabulary, as a schema the vendor will enforce.
#:
#: `enum` on both fields rather than free strings: the model is held
#: to the closed list by the API itself, so `Reading.clean` is a
#: second line of defence rather than the only one.
POST_VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "facets", "presentation", "confidence", "note"],
    "properties": {
        "subject": {"type": "string", "enum": list(SUBJECTS)},
        "presentation": {
            "type": "string",
            "enum": list(PRESENTATIONS),
            "description": (
                "Who the garments are cut and styled for. Describe the "
                "clothes, never the person: say unspecified whenever the "
                "cut does not clearly read one way, and for anything that "
                "is not an outfit."
            ),
        },
        "facets": {
            "type": "array",
            "items": {"type": "string", "enum": list(FACETS)},
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "note": {"type": "string"},
    },
}

POST_VISION_RESPONSE_FORMAT = JsonSchemaFormat(
    name="post_vision", json_schema=POST_VISION_SCHEMA
)


class MetaPostVisionReader:
    """The reading, through the vendor's model with an image in.

    Thin, like `MetaFitReader`: it owns the call and the refusal. The
    prompt and the schema are module constants, so changing what is
    asked for is a change to data rather than to a code path.
    """

    def __init__(
        self,
        provider: Any,
        *,
        model: str = POST_VISION_MODEL,
        prompt_version: str = POST_VISION_PROMPT_VERSION,
    ) -> None:
        self._provider = provider
        self._model = model
        self.prompt_version = prompt_version

    @property
    def model(self) -> str:
        return self._model

    def build_request(self, *, image: bytes, content_type: str):
        from app.config import get_settings
        from app.providers.base import AIMessage, AIRequest, Capabilities
        from app.workers.fit_vision import data_uri, prepare_image

        sent, sent_type = prepare_image(image, content_type=content_type)
        return AIRequest(
            model=self._model,
            system=POST_VISION_SYSTEM,
            messages=(
                AIMessage(
                    "user",
                    [
                        {"type": "text", "text": POST_VISION_USER_TEXT},
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
                text_in=True,
                image_in=True,
                text_out=True,
                structured_output=True,
            ),
            response_format=POST_VISION_RESPONSE_FORMAT,
            max_completion_tokens=POST_VISION_MAX_TOKENS,
            reasoning_effort=get_settings().model_reasoning_effort,
            temperature=POST_VISION_TEMPERATURE,
            prompt_version=self.prompt_version,
            purpose=POST_VISION_PURPOSE,
        )

    async def read(
        self,
        *,
        image: bytes,
        content_type: str,
        user_id: uuid.UUID | None = None,
    ) -> Reading:
        response = await self._provider.complete(
            self.build_request(image=image, content_type=content_type),
            user_id=user_id,
        )
        return parse(response.text)


def parse(text: str | None) -> Reading:
    """The model's JSON as a `Reading`. Never raises.

    A malformed answer becomes `other`, which passes every gate, so a
    pin whose reading failed is ranked exactly as it was before this
    existed. Raising would turn a bad response into a dead pin.
    """
    try:
        payload = json.loads(text or "")
    except (TypeError, ValueError):
        return Reading(subject="other", confidence=0.0)
    if not isinstance(payload, dict):
        return Reading(subject="other", confidence=0.0)

    raw_facets = payload.get("facets")
    facets = tuple(f for f in raw_facets if isinstance(f, str)) if isinstance(
        raw_facets, list
    ) else ()
    note = payload.get("note")
    try:
        confidence = float(payload.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0

    # `clean` drops anything outside the vocabulary, so a model that
    # invents a word gets it ignored rather than stored.
    return Reading(
        subject=str(payload.get("subject") or "other"),
        facets=facets,
        presentation=str(payload.get("presentation") or "unspecified"),
        note=(note.strip()[:160] if isinstance(note, str) and note.strip() else None),
        confidence=confidence,
    ).clean()


__all__ = [
    "POST_VISION_MAX_TOKENS",
    "POST_VISION_MODEL",
    "POST_VISION_PROMPT_VERSION",
    "POST_VISION_RESPONSE_FORMAT",
    "POST_VISION_SYSTEM",
    "POST_VISION_USER_TEXT",
    "VISION_JOB_KIND",
    "MetaPostVisionReader",
    "parse",
]


async def read_post_vision(
    session: Any, job: Any, *, reader: Any, store: Any
) -> dict[str, Any]:
    """Read one pin's photograph and store what it is of. Idempotent.

    Re-running replaces the row rather than adding one: a reading is
    a current opinion about a picture, not a history of opinions.
    """
    import logging

    import sqlalchemy as sa

    from app.domain.discovery.subject import vector_for
    from app.errors import CapabilityUnavailable
    from app.models.media_asset import MediaAsset
    from app.models.post_vision import PostVisionRow
    from app.models.posts import PostMedia

    logger = logging.getLogger(__name__)
    payload = job.payload or {}
    raw = payload.get("post_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no post_id")
    post_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))

    link = await session.scalar(
        sa.select(PostMedia).where(
            PostMedia.post_id == post_id, PostMedia.position == 0
        )
    )
    if link is None:
        return {"post_id": str(post_id), "state": "no_picture"}
    asset = await session.get(MediaAsset, link.media_asset_id)
    if asset is None or not asset.storage_key or asset.deleted_at is not None:
        return {"post_id": str(post_id), "state": "no_picture"}

    existing = await session.get(PostVisionRow, post_id)
    if (
        existing is not None
        and existing.asset_id == asset.id
        and existing.prompt_version == reader.prompt_version
    ):
        # Same picture, same prompt. Nothing to learn by asking again,
        # and asking again is a billed call.
        return {"post_id": str(post_id), "state": "already_read"}

    try:
        data = await store.read(asset)
    except CapabilityUnavailable as exc:
        return {"post_id": str(post_id), "state": "unreadable", "reason": exc.code}

    reading = await reader.read(
        image=data,
        content_type=asset.content_type or "image/jpeg",
        user_id=asset.user_id,
    )

    row = existing or PostVisionRow(post_id=post_id)
    row.asset_id = asset.id
    row.subject = reading.subject
    row.presentation = reading.presentation
    row.confidence = reading.confidence
    row.facets = list(reading.facets)
    row.vector = vector_for(reading)
    row.note = reading.note
    row.model = reader.model
    row.prompt_version = reader.prompt_version
    session.add(row)
    await session.commit()

    logger.info(
        "read a pin",
        extra={
            "post": str(post_id),
            "subject": reading.subject,
            "facets": len(reading.facets),
        },
    )
    return {
        "post_id": str(post_id),
        "state": "read",
        "subject": reading.subject,
    }
