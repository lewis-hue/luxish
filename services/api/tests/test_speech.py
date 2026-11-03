"""Speech to text.

The properties worth pinning are about refusal, because this is the one
endpoint where the thing being rejected is an upload somebody already
waited to make.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from app.providers.base import InvalidProviderRequest
from app.providers.meta import (
    TRANSCRIBE_ACCEPTED_FORMATS,
    TRANSCRIBE_MAX_AUDIO_SECONDS,
    TRANSCRIBE_MAX_REQUEST_BYTES,
    MetaProvider,
)

pytestmark = pytest.mark.anyio


def _provider() -> MetaProvider:
    return MetaProvider(api_key="LLM_test", recorder=None)


async def test_the_preflight_refuses_what_the_vendor_would(
) -> None:
    """Each of these is a verified 400 or 413, caught before the upload."""
    provider = _provider()

    # The one accepted family passes.
    for accepted in TRANSCRIBE_ACCEPTED_FORMATS:
        provider.check_transcription(
            content_type=accepted, duration_seconds=5, byte_size=1024
        )

    with pytest.raises(InvalidProviderRequest):
        provider.check_transcription(
            content_type="audio/m4a", duration_seconds=5, byte_size=1024
        )
    with pytest.raises(InvalidProviderRequest):
        provider.check_transcription(
            content_type="audio/wav",
            duration_seconds=TRANSCRIBE_MAX_AUDIO_SECONDS + 1,
            byte_size=1024,
        )
    with pytest.raises(InvalidProviderRequest):
        provider.check_transcription(
            content_type="audio/wav",
            duration_seconds=5,
            byte_size=TRANSCRIBE_MAX_REQUEST_BYTES + 1,
        )


async def test_an_unreadable_recording_is_refused_not_sent(
    client: httpx.AsyncClient, auth: Any
) -> None:
    headers = auth(sub="kc-speech-1")
    await client.post("/v1/auth/session", headers=headers)
    response = await client.post(
        "/v1/speech/transcribe",
        headers=headers,
        json={"audio_base64": "not base64 at all!!", "content_type": "audio/wav"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "bad_audio"


async def test_a_format_the_vendor_cannot_take_is_refused_with_the_reason(
    client: httpx.AsyncClient, auth: Any
) -> None:
    """Rejected locally, so nobody pays to upload an m4a that cannot work."""
    headers = auth(sub="kc-speech-2")
    await client.post("/v1/auth/session", headers=headers)
    response = await client.post(
        "/v1/speech/transcribe",
        headers=headers,
        json={
            "audio_base64": base64.b64encode(b"fake audio").decode(),
            "content_type": "audio/m4a",
            "duration_seconds": 3,
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "bad_audio"
    # The message names the real limit rather than saying "bad request".
    assert "WAV" in response.json()["message"]


async def test_transcription_needs_a_run_recorder() -> None:
    """An unaccounted paid call is spend nobody can attribute."""
    with pytest.raises(RuntimeError):
        await _provider().transcribe(audio=b"x", content_type="audio/wav")
