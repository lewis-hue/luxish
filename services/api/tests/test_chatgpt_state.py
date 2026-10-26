"""Task 7 — the ChatGPT-plan eligibility state machine (ADR-008).

There is **no allowance-remaining API**, so every transition here is driven by
an observed error code. Three distinctions carry the module:

* 429 ``subscription_sharing_usage_limit_exceeded`` means the allowance is gone
  — and it can arrive *mid-stream* as a ``response.failed`` event, not only as
  an HTTP status.
* 503 means "try later". It must never look like revocation.
* 401 ``subscription_sharing_invalid_user`` means "refresh and find out". Only a
  *confirmed* refresh failure revokes; a dropped TCP connection does not.

The app ships with inference ``unavailable``, and image generation is never
routed here in any state.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.providers.base import (
    AIRequest,
    Capabilities,
    InvalidProviderRequest,
    ProviderUnavailable,
    UnsupportedCapability,
)
from app.providers.chatgpt_plan import (
    ALLOWANCE_EXHAUSTED_CODE,
    AUTHORIZE_URL,
    BACKOFF_CAP_SECONDS,
    CHATGPT_PLAN_CAPABILITIES,
    CHATGPT_PLAN_STATES,
    ELIGIBLE_PLAN_TIERS,
    INITIAL_STATE,
    INVALID_USER_CODE,
    NOT_ELIGIBLE_CODE,
    REQUIRED_SCOPES,
    RESPONSES_URL,
    REVOKE_URL,
    REVOKING_REFRESH_ERRORS,
    TOKEN_URL,
    TRANSIENT_ERROR_CODES,
    UNSUPPORTED_CAPABILITY_CODE,
    ChatGPTConnection,
    ChatGPTPlanProvider,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test attempted a real network request")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


# --------------------------------------------------------------------------- #
# the plan's named tests
# --------------------------------------------------------------------------- #
def test_usage_limit_429_moves_connection_to_allowance_exhausted() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=429, code="subscription_sharing_usage_limit_exceeded")
    assert conn.state == "allowance_exhausted"


def test_transient_503_does_not_revoke() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=503, code="subscription_sharing_usage_unavailable")
    assert conn.state == "inference_authorized"


# --------------------------------------------------------------------------- #
# the eight states, and the one we ship in
# --------------------------------------------------------------------------- #
def test_the_machine_has_exactly_the_eight_documented_states() -> None:
    assert CHATGPT_PLAN_STATES == (
        "unavailable",
        "approval_pending",
        "disconnected",
        "identity_connected",
        "inference_authorized",
        "allowance_exhausted",
        "revoked",
        "error",
    )


def test_it_ships_unavailable() -> None:
    assert INITIAL_STATE == "unavailable"
    assert ChatGPTConnection().state == "unavailable"
    assert ChatGPTConnection().can_infer is False


def test_an_undeclared_state_is_refused() -> None:
    with pytest.raises(InvalidProviderRequest):
        ChatGPTConnection(state="probably_fine")


# --------------------------------------------------------------------------- #
# every documented error code, one at a time
# --------------------------------------------------------------------------- #
def test_a_mid_stream_response_failed_event_also_exhausts_the_allowance() -> None:
    """Verified: the 429 can arrive inside the stream, after a 200."""
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_stream_event(
        {
            "type": "response.failed",
            "response": {"error": {"code": ALLOWANCE_EXHAUSTED_CODE, "message": "no"}},
        }
    )
    assert conn.state == "allowance_exhausted"


def test_a_stream_event_that_is_not_a_failure_changes_nothing() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_stream_event({"type": "response.output_text.delta", "delta": "hi"})
    assert conn.state == "inference_authorized"


def test_403_not_eligible_is_terminal_and_must_not_be_retried() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=403, code=NOT_ELIGIBLE_CODE)
    assert conn.state == "error"
    assert conn.terminal is True
    assert conn.should_retry is False
    assert conn.should_reauthorize is False


@pytest.mark.parametrize("code", sorted(TRANSIENT_ERROR_CODES))
def test_503_keeps_the_current_state_and_asks_for_bounded_backoff(code: str) -> None:
    conn = ChatGPTConnection(state="allowance_exhausted")
    conn.observe_error(status=503, code=code)
    assert conn.state == "allowance_exhausted"
    assert conn.should_retry is True
    assert 0 < conn.retry_after_seconds <= BACKOFF_CAP_SECONDS


def test_repeated_503s_back_off_but_stay_bounded() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    delays = []
    for _ in range(20):
        conn.observe_error(status=503, code="subscription_sharing_usage_unavailable")
        delays.append(conn.retry_after_seconds)
    assert delays == sorted(delays)
    assert max(delays) == BACKOFF_CAP_SECONDS
    assert conn.state == "inference_authorized"


def test_400_unsupported_capability_names_the_parameter_and_forbids_the_same_body() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=400, code=UNSUPPORTED_CAPABILITY_CODE, param="tools[0].type")
    assert conn.state == "inference_authorized"
    assert conn.unsupported_param == "tools[0].type"
    assert conn.retry_same_body_allowed is False


def test_401_invalid_user_asks_for_a_refresh_and_does_not_revoke_on_its_own() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=401, code=INVALID_USER_CODE)
    assert conn.state == "inference_authorized"
    assert conn.should_reauthorize is True


def test_revocation_requires_a_confirmed_refresh_failure() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=401, code=INVALID_USER_CODE)
    conn.observe_refresh_failure(code="invalid_grant")
    assert conn.state == "revoked"
    assert conn.terminal is True


@pytest.mark.parametrize("code", sorted(REVOKING_REFRESH_ERRORS))
def test_each_documented_refresh_error_revokes(code: str) -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_refresh_failure(code=code)
    assert conn.state == "revoked"


def test_a_transport_error_never_revokes() -> None:
    """A dropped connection is not a disconnected user."""
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=401, code=INVALID_USER_CODE)
    conn.observe_transport_error(TimeoutError("read timeout"))
    assert conn.state == "inference_authorized"
    assert conn.should_retry is True


def test_a_refresh_failure_that_is_not_a_grant_error_does_not_revoke() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_refresh_failure(code="temporarily_unavailable")
    assert conn.state == "inference_authorized"


def test_a_bare_429_without_the_sharing_code_is_rate_limiting_not_exhaustion() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=429, code="rate_limit_exceeded")
    assert conn.state == "inference_authorized"
    assert conn.should_retry is True


def test_an_unrecognised_5xx_leaves_the_state_alone() -> None:
    conn = ChatGPTConnection(state="identity_connected")
    conn.observe_error(status=500, code=None)
    assert conn.state == "identity_connected"


def test_a_successful_refresh_clears_the_reauthorisation_flag() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=401, code=INVALID_USER_CODE)
    conn.observe_refresh_success()
    assert conn.should_reauthorize is False
    assert conn.state == "inference_authorized"


def test_a_successful_call_clears_the_backoff() -> None:
    conn = ChatGPTConnection(state="inference_authorized")
    conn.observe_error(status=503, code="subscription_sharing_usage_unavailable")
    conn.observe_success()
    assert conn.retry_after_seconds == 0
    assert conn.last_error_code is None


# --------------------------------------------------------------------------- #
# the forward path, and the separation of the two permissions
# --------------------------------------------------------------------------- #
def test_identity_alone_does_not_authorise_inference() -> None:
    """Verified: "A valid ID token alone does not authorize ChatGPT plan usage.\""""
    conn = ChatGPTConnection(state="unavailable")
    conn.request_approval()
    assert conn.state == "approval_pending"
    conn.grant_approval()
    assert conn.state == "disconnected"
    conn.connect_identity()
    assert conn.state == "identity_connected"
    assert conn.can_infer is False

    conn.authorize_inference(scopes=REQUIRED_SCOPES, plan_tier="plus")
    assert conn.state == "inference_authorized"
    assert conn.can_infer is True


def test_inference_requires_every_documented_scope() -> None:
    conn = ChatGPTConnection(state="identity_connected")
    with pytest.raises(InvalidProviderRequest):
        conn.authorize_inference(scopes=("offline_access",), plan_tier="plus")
    assert conn.state == "identity_connected"


def test_only_plus_and_pro_are_recorded_as_eligible() -> None:
    assert ELIGIBLE_PLAN_TIERS == ("plus", "pro")
    conn = ChatGPTConnection(state="identity_connected")
    conn.authorize_inference(scopes=REQUIRED_SCOPES, plan_tier="free")
    # Free is "not stated", not "known eligible": the authorisation is recorded
    # but eligibility is unproven until the first call succeeds.
    assert conn.state == "error"
    assert conn.last_error_code == "plan_tier_not_eligible"


def test_disconnecting_is_our_own_observation_not_a_webhook() -> None:
    """Verified: OpenAI does not notify us when a user disconnects."""
    conn = ChatGPTConnection(state="inference_authorized")
    conn.disconnect()
    assert conn.state == "disconnected"


def test_the_documented_scopes_and_endpoints_are_recorded_verbatim() -> None:
    assert REQUIRED_SCOPES == ("offline_access", "resource.invoke", "chatgpt.tokens.use.direct")
    assert RESPONSES_URL == "https://api.openai.com/v1/responses"
    assert AUTHORIZE_URL == "https://auth.openai.com/api/accounts/authorize"
    assert TOKEN_URL == "https://auth.openai.com/api/accounts/oauth/token"
    assert REVOKE_URL == "https://auth.openai.com/api/accounts/oauth/revoke"


# --------------------------------------------------------------------------- #
# the provider: declared capabilities and a mandatory request shape
# --------------------------------------------------------------------------- #
def test_the_plan_route_declares_no_image_output_audio_or_video() -> None:
    caps = CHATGPT_PLAN_CAPABILITIES
    assert caps.image_out is False
    assert caps.audio_in is False
    assert caps.video_in is False
    assert caps.file_upload is False
    assert caps.embeddings is False
    assert caps.text_in is True
    assert caps.text_out is True
    assert caps.streaming is True


@pytest.mark.parametrize("state", CHATGPT_PLAN_STATES)
async def test_image_generation_is_refused_in_every_state(state: str) -> None:
    provider = ChatGPTPlanProvider(connection=ChatGPTConnection(state=state))
    with pytest.raises(UnsupportedCapability):
        await provider.complete(
            AIRequest(prompt="draw a blazer", needs=Capabilities(image_out=True))
        )


async def test_inference_is_refused_while_the_route_is_unavailable() -> None:
    provider = ChatGPTPlanProvider(connection=ChatGPTConnection())
    with pytest.raises(ProviderUnavailable):
        await provider.complete(AIRequest(prompt="style me"))


def test_the_request_body_forces_store_false_and_stream_true() -> None:
    """Both are mandatory on the plan route, not defaults we chose."""
    provider = ChatGPTPlanProvider(connection=ChatGPTConnection(state="inference_authorized"))
    body = provider._build_body(AIRequest(prompt="style me", stream=False, store=False))
    assert body["store"] is False
    assert body["stream"] is True
    assert body["input"]


def test_a_caller_asking_to_store_is_refused_rather_than_silently_corrected() -> None:
    provider = ChatGPTPlanProvider(connection=ChatGPTConnection(state="inference_authorized"))
    with pytest.raises(InvalidProviderRequest):
        provider._build_body(AIRequest(prompt="x", store=True))


def test_the_plan_route_never_sends_a_refused_meta_parameter_either() -> None:
    provider = ChatGPTPlanProvider(connection=ChatGPTConnection(state="inference_authorized"))
    body = provider._build_body(AIRequest(prompt="x", stop=["\n"], n=2, max_tokens=5))
    for banned in ("stop", "n", "max_tokens", "logit_bias"):
        assert banned not in body


def test_there_is_no_revocation_webhook_handler_to_rely_on() -> None:
    """Verified absence. If a handler appears, the comment above it is wrong."""
    import app.providers.chatgpt_plan as module

    assert not hasattr(module, "handle_revocation_webhook")
    assert module.HAS_REVOCATION_WEBHOOK is False


def test_there_is_no_allowance_remaining_lookup() -> None:
    import app.providers.chatgpt_plan as module

    assert module.HAS_ALLOWANCE_API is False
    assert not hasattr(module, "fetch_allowance_remaining")
