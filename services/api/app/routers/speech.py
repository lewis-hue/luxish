"""Speech to text, for the stylist's microphone.

One endpoint, and it exists because typing a paragraph about where you
are going on a phone keyboard is the slowest part of asking for an
outfit. The answer goes into the composer as editable text rather than
being sent straight to the model: a transcript is a guess, and the
person has to be able to fix it before it becomes a request.

**WAV only, and the refusal says so.** The vendor's ASR endpoint takes
nothing else (verified), so an unsupported recording is rejected here
with a reason rather than being paid for and rejected upstream.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter

from app.deps import AuthDep, SessionDep
from app.errors import ApiError, CapabilityUnavailable
from app.providers.base import InvalidProviderRequest
from app.schemas.speech import TranscriptIn, TranscriptOut

router = APIRouter(prefix="/speech", tags=["speech"])


@router.post("/transcribe", response_model=TranscriptOut)
async def transcribe(
    payload: TranscriptIn, db: SessionDep, ctx: AuthDep
) -> TranscriptOut:
    """Turn a recording into text. Answers inline: this is seconds, not minutes."""
    from app.providers.base import AIRunRecorder
    from app.providers.meta import MetaProvider

    try:
        audio = base64.b64decode(payload.audio_base64, validate=True)
    except Exception:
        raise ApiError(
            "That recording could not be read.",
            status_code=422,
            code="bad_audio",
        ) from None

    provider = MetaProvider(recorder=AIRunRecorder(db))
    try:
        text = await provider.transcribe(
            audio=audio,
            content_type=payload.content_type,
            duration_seconds=payload.duration_seconds,
            user_id=ctx.user_id,
        )
    except InvalidProviderRequest as refusal:
        # The pre-flight's own words: they name the real limit.
        raise ApiError(str(refusal), status_code=422, code="bad_audio") from None
    except CapabilityUnavailable:
        raise
    except Exception:
        raise ApiError(
            "Could not turn that into text. Try again, or type it.",
            status_code=503,
            code="transcription_unavailable",
        ) from None

    return TranscriptOut(text=text)
