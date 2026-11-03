"""Speech shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field

#: 32 MB of audio is about ten minutes of 16-bit mono PCM, which is the
#: vendor's own ceiling. Base64 inflates by a third, so the field is
#: sized for the encoded form.
MAX_BASE64 = 44 * 1024 * 1024


class TranscriptIn(BaseModel):
    #: The recording, base64-encoded. Inline rather than an upload: it is
    #: transient, it is never stored, and a round trip through the media
    #: pipeline would double the latency of the one feature whose whole
    #: point is being faster than typing.
    audio_base64: str = Field(max_length=MAX_BASE64)
    content_type: str = Field(default="audio/wav", max_length=100)
    duration_seconds: float = Field(default=0.0, ge=0, le=600)


class TranscriptOut(BaseModel):
    #: What was heard. Empty when the recording was silent, which is not
    #: an error.
    text: str
