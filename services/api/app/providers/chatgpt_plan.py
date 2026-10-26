"""The ChatGPT-plan (Sign in with ChatGPT) inference route — ADR-008.

**It ships ``unavailable``.** Commercial access is waitlisted, the self-service
token-sharing path is scoped to open-source / locally hosted apps, and we are
neither. The eight-state machine exists so that the day approval arrives, the
transitions are already written and tested rather than invented under pressure.

Four verified facts shape everything here.

1. **Signing in and using the plan are separate permissions.** A valid ID token
   alone does not authorise plan usage; that needs
   ``offline_access resource.invoke chatgpt.tokens.use.direct``. So identity and
   inference are separate records with separate states.

2. **There is no allowance-remaining API.** Exhaustion is observable only as a
   429 ``subscription_sharing_usage_limit_exceeded`` — which can also arrive
   *mid-stream* as a ``response.failed`` event, after a 200. Both paths land in
   ``allowance_exhausted``; :attr:`HAS_ALLOWANCE_API` records the absence so a
   future reader does not go looking for a poller.

3. **There is no revocation webhook.** OpenAI "does not currently notify your
   tool when a user disconnects the app in ChatGPT settings", so ``revoked`` is
   always *our* inference from a confirmed failure — never from a dropped
   connection, which is why a transport error is handled separately from an HTTP
   status.

4. **Image generation, file search, Code Interpreter, the Files upload API and
   audio/video input are unsupported on this route.** Image generation is
   therefore never routed here in any state, enforced by a declared
   ``image_out=False`` *and* by a check in ``complete``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import (
    AIRequest,
    AIResponse,
    AIRunRecorder,
    Capabilities,
    InvalidProviderRequest,
    ProviderCapabilities,
    ProviderUnavailable,
    UnsupportedCapability,
)

#: The eight states, in the order a connection moves through them.
CHATGPT_PLAN_STATES: tuple[str, ...] = (
    #: No approval to use the route at all. What this build ships in.
    "unavailable",
    #: We have asked OpenAI for commercial access and are waiting.
    "approval_pending",
    #: Approved, but this user has not linked their ChatGPT account.
    "disconnected",
    #: Identity linked. **Not** permission to use their plan.
    "identity_connected",
    #: The plan-usage scopes were granted. The only state that may infer.
    "inference_authorized",
    #: A 429 told us the shared allowance is spent for now.
    "allowance_exhausted",
    #: A confirmed disconnection or refresh failure. Needs a fresh consent.
    "revoked",
    #: Terminal ineligibility, or an error we must not retry into.
    "error",
)

#: ADR-008: the app ships with inference unavailable.
INITIAL_STATE = "unavailable"

#: Verified endpoints. Inference is the Responses API; the OAuth endpoints are
#: on ``auth.openai.com`` and PKCE S256 is required.
RESPONSES_URL = "https://api.openai.com/v1/responses"
AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
REVOKE_URL = "https://auth.openai.com/api/accounts/oauth/revoke"

#: Verified: plan usage requires all three. An ID token alone is not enough.
REQUIRED_SCOPES: tuple[str, ...] = (
    "offline_access",
    "resource.invoke",
    "chatgpt.tokens.use.direct",
)

#: Verified: only Plus and Pro are named eligible. Free / Business / Enterprise
#: are **not stated**, which is not the same as eligible.
ELIGIBLE_PLAN_TIERS: tuple[str, ...] = ("plus", "pro")

#: Verified: ``store: false`` and ``stream: true`` are mandatory on this route.
MANDATORY_STORE = False
MANDATORY_STREAM = True

#: Verified absences, recorded as constants so a reader does not search for the
#: thing that is not there.
HAS_ALLOWANCE_API = False
HAS_REVOCATION_WEBHOOK = False

ALLOWANCE_EXHAUSTED_CODE = "subscription_sharing_usage_limit_exceeded"
NOT_ELIGIBLE_CODE = "subscription_sharing_user_not_eligible"
UNSUPPORTED_CAPABILITY_CODE = "subscription_sharing_unsupported_capability"
INVALID_USER_CODE = "subscription_sharing_invalid_user"

#: 503s: the route is momentarily unusable. Retry with backoff; change nothing.
TRANSIENT_ERROR_CODES: frozenset[str] = frozenset(
    {
        "subscription_sharing_usage_unavailable",
        "subscription_sharing_user_unavailable",
    }
)

#: Refresh failures that *prove* the grant is gone. Only these revoke.
REVOKING_REFRESH_ERRORS: frozenset[str] = frozenset(
    {"invalid_grant", "refresh_token_expired", "refresh_token_reused"}
)

#: Capabilities unsupported on the plan route, named so a reviewer can check
#: them against the declared record below.
UNSUPPORTED_ON_PLAN_ROUTE: tuple[str, ...] = (
    "image_generation",
    "file_search",
    "code_interpreter",
    "files_upload_api",
    "audio_input",
    "video_input",
)

#: Bounded backoff for the 503 path. Bounded is the point: an unbounded retry
#: against a route whose allowance we cannot query is a way to spend someone
#: else's quota.
BACKOFF_BASE_SECONDS = 2
BACKOFF_CAP_SECONDS = 300

#: What this route can honestly do.
#:
#: ``image_in`` is **False and that is a judgement, not a verified fact**: image
#: *input* is not on the published unsupported list, but the Files upload API
#: is, so there is no verified way to supply an image. ADR-006 says the router
#: must not guess, and False is the answer that cannot cause a silent billed
#: failure.
CHATGPT_PLAN_CAPABILITIES = ProviderCapabilities(
    text_in=True,
    text_out=True,
    tools=True,
    structured_output=True,
    streaming=True,
    image_in=False,
    image_out=False,
    audio_in=False,
    video_in=False,
    file_upload=False,
    embeddings=False,
    max_output_tokens=None,
    currency="USD",
    # No unit price: the user's own ChatGPT plan pays for this, not us. That is
    # the whole point of the route, and why `billing_source` is part of routing.
)


def _backoff_seconds(failures: int) -> int:
    return min(BACKOFF_BASE_SECONDS * (2 ** max(0, failures - 1)), BACKOFF_CAP_SECONDS)


@dataclass(slots=True)
class ChatGPTConnection:
    """The eligibility state machine, with no database and no transport.

    Deliberately a plain object: every transition is a pure function of an
    observed error, so the interesting behaviour is testable without a session,
    a token, or a socket. :class:`app.models.provider_connection.ProviderConnection`
    is the persisted projection of this.
    """

    state: str = INITIAL_STATE
    scopes: tuple[str, ...] = ()
    plan_tier: str | None = None
    terminal: bool = False
    refresh_required: bool = False
    last_error_code: str | None = None
    last_error_status: int | None = None
    unsupported_param: str | None = None
    retry_after_seconds: int = 0
    consecutive_transient_failures: int = 0
    retry_same_body_allowed: bool = True
    history: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state not in CHATGPT_PLAN_STATES:
            raise InvalidProviderRequest(
                f"{self.state!r} is not a ChatGPT-plan state; expected one of "
                f"{CHATGPT_PLAN_STATES}"
            )

    # -- read-only questions ----------------------------------------------- #
    @property
    def can_infer(self) -> bool:
        """Only one state may issue a request. Ships False."""
        return self.state == "inference_authorized" and not self.terminal

    @property
    def should_retry(self) -> bool:
        return not self.terminal and self.retry_after_seconds > 0

    @property
    def should_reauthorize(self) -> bool:
        """A refresh is owed before the next attempt."""
        return self.refresh_required and not self.terminal

    # -- transitions -------------------------------------------------------- #
    def _move(self, state: str) -> str:
        if state not in CHATGPT_PLAN_STATES:  # pragma: no cover - programming error
            raise InvalidProviderRequest(f"unknown state {state!r}")
        if state != self.state:
            self.history.append(f"{self.state}->{state}")
            self.state = state
        return self.state

    def request_approval(self) -> str:
        return self._move("approval_pending")

    def grant_approval(self) -> str:
        """Approval is for the *tool*, not for a user. Users start disconnected."""
        return self._move("disconnected")

    def connect_identity(self) -> str:
        return self._move("identity_connected")

    def disconnect(self) -> str:
        """Our own observation; there is no webhook that tells us this."""
        self.refresh_required = False
        return self._move("disconnected")

    def authorize_inference(self, *, scopes: Sequence[str], plan_tier: str | None) -> str:
        """Record the plan-usage grant.

        Refuses a partial scope set outright: a grant missing
        ``chatgpt.tokens.use.direct`` cannot infer, and recording it as
        authorised would turn a configuration error into a run-time 403.
        """
        missing = [s for s in REQUIRED_SCOPES if s not in scopes]
        if missing:
            raise InvalidProviderRequest(
                f"plan usage needs {REQUIRED_SCOPES}; missing {tuple(missing)}"
            )
        self.scopes = tuple(scopes)
        self.plan_tier = plan_tier
        if plan_tier is not None and plan_tier.lower() not in ELIGIBLE_PLAN_TIERS:
            # Not "ineligible" as a vendor fact — only Plus and Pro are *named*
            # eligible, and the rest is unstated. We refuse rather than spend a
            # call to find out, and the first eligible tier clears it.
            self.last_error_code = "plan_tier_not_eligible"
            return self._move("error")
        return self._move("inference_authorized")

    # -- observations ------------------------------------------------------- #
    def observe_success(self) -> str:
        """A call worked: clear the backoff and the last error."""
        self.retry_after_seconds = 0
        self.consecutive_transient_failures = 0
        self.last_error_code = None
        self.last_error_status = None
        self.retry_same_body_allowed = True
        return self.state

    def observe_error(
        self,
        *,
        status: int,
        code: str | None = None,
        param: str | None = None,
        mid_stream: bool = False,
    ) -> str:
        """Apply one observed error. The only driver of this machine.

        ``mid_stream`` is accepted because the same 429 can arrive after a 200;
        it changes nothing about the destination state, which is the point —
        exhaustion is exhaustion however it is delivered.
        """
        self.last_error_status = status
        self.last_error_code = code

        if code == ALLOWANCE_EXHAUSTED_CODE:
            self.retry_after_seconds = 0
            return self._move("allowance_exhausted")

        if code == NOT_ELIGIBLE_CODE:
            # Terminal. Do not retry and do not start a re-auth loop: the user
            # is not eligible, and asking again will not change that.
            self.terminal = True
            self.retry_after_seconds = 0
            self.refresh_required = False
            return self._move("error")

        if code in TRANSIENT_ERROR_CODES or status in (500, 502, 503, 504):
            self.consecutive_transient_failures += 1
            self.retry_after_seconds = _backoff_seconds(self.consecutive_transient_failures)
            return self.state  # deliberately unchanged

        if code == UNSUPPORTED_CAPABILITY_CODE:
            # The body is wrong, not the connection. Inspect `error.param` and
            # change it; retrying the same body buys the same 400.
            self.unsupported_param = param
            self.retry_same_body_allowed = False
            self.retry_after_seconds = 0
            return self.state

        if code == INVALID_USER_CODE or status == 401:
            # Not revocation yet. A 401 means "refresh and find out"; only a
            # confirmed refresh failure proves the grant is gone.
            self.refresh_required = True
            self.retry_after_seconds = 0
            return self.state

        if status == 429:
            # A plain rate limit, not allowance exhaustion. Back off.
            self.consecutive_transient_failures += 1
            self.retry_after_seconds = _backoff_seconds(self.consecutive_transient_failures)
            return self.state

        return self.state

    def observe_stream_event(self, event: Mapping[str, Any]) -> str:
        """Apply a Responses-API stream event.

        Verified: the allowance 429 can arrive here as ``response.failed`` after
        the HTTP response already succeeded. A handler that only reads statuses
        would miss it and keep calling.
        """
        if event.get("type") != "response.failed":
            return self.state
        error = (event.get("response") or {}).get("error") or {}
        return self.observe_error(
            status=int(error.get("status") or 429),
            code=error.get("code"),
            param=error.get("param"),
            mid_stream=True,
        )

    def observe_transport_error(self, exc: BaseException | None = None) -> str:
        """A timeout, reset or DNS failure. Never a revocation.

        This is the distinction ADR-008 insists on: a dropped connection tells
        us nothing about the user's consent, and treating it as revocation would
        log people out of a working integration.
        """
        self.consecutive_transient_failures += 1
        self.retry_after_seconds = _backoff_seconds(self.consecutive_transient_failures)
        self.last_error_code = type(exc).__name__ if exc is not None else "transport_error"
        return self.state

    def observe_refresh_success(self) -> str:
        self.refresh_required = False
        return self.observe_success()

    def observe_refresh_failure(self, *, code: str | None) -> str:
        """Only a documented grant failure revokes."""
        self.last_error_code = code
        if code in REVOKING_REFRESH_ERRORS:
            self.terminal = True
            self.refresh_required = False
            self.retry_after_seconds = 0
            return self._move("revoked")
        self.consecutive_transient_failures += 1
        self.retry_after_seconds = _backoff_seconds(self.consecutive_transient_failures)
        return self.state

    # -- persistence projection -------------------------------------------- #
    @classmethod
    def from_row(cls, row: Any) -> ChatGPTConnection:
        return cls(
            state=row.state,
            scopes=tuple(row.scopes or ()),
            plan_tier=row.plan_tier,
            terminal=bool(row.terminal),
            refresh_required=bool(row.refresh_required),
            last_error_code=row.last_error_code,
            last_error_status=row.last_error_status,
            unsupported_param=row.unsupported_param,
            retry_after_seconds=int(row.retry_after_seconds or 0),
            consecutive_transient_failures=int(row.consecutive_transient_failures or 0),
        )

    def apply_to(self, row: Any) -> None:
        row.state = self.state
        row.scopes = list(self.scopes)
        row.plan_tier = self.plan_tier
        row.terminal = self.terminal
        row.refresh_required = self.refresh_required
        row.last_error_code = self.last_error_code
        row.last_error_status = self.last_error_status
        row.unsupported_param = self.unsupported_param
        row.retry_after_seconds = self.retry_after_seconds
        row.consecutive_transient_failures = self.consecutive_transient_failures


class ChatGPTPlanProvider:
    """The plan route as an adapter. Refuses, in this build.

    It is a real adapter rather than a stub so the registry has something to
    reject on *declared capability* instead of on a special case, and so the
    request shape (``store: false``, ``stream: true``) is already correct.
    """

    name = "chatgpt_plan"
    capabilities = CHATGPT_PLAN_CAPABILITIES

    def __init__(
        self,
        *,
        connection: ChatGPTConnection | None = None,
        http: Any | None = None,
        recorder: AIRunRecorder | None = None,
        model: str = "gpt-5.1",
    ) -> None:
        self.connection = connection or ChatGPTConnection()
        self._http = http
        self._recorder = recorder
        self.model = model

    # -- request shape ----------------------------------------------------- #
    def _build_body(self, request: AIRequest) -> dict[str, Any]:
        """A Responses-API body with the two mandatory fields forced.

        A caller asking for ``store=True`` is refused rather than silently
        corrected: they believe something about retention that is not true, and
        quietly fixing the body leaves that belief in place.
        """
        if request.store:
            raise InvalidProviderRequest(
                "store must be false on the ChatGPT-plan route; it is mandatory, "
                "not a default"
            )
        body: dict[str, Any] = {
            "model": request.model or self.model,
            "input": list(request.as_messages()),
            "store": MANDATORY_STORE,
            "stream": MANDATORY_STREAM,
        }
        if request.max_completion_tokens is not None:
            body["max_output_tokens"] = request.max_completion_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.tools:
            body["tools"] = [dict(t) for t in request.tools]
            if request.tool_choice is not None:
                body["tool_choice"] = request.tool_choice
        if request.response_format is not None:
            body["text"] = {"format": request.response_format.as_response_format()}
        if request.metadata is not None:
            body["metadata"] = dict(request.metadata)
        return body

    # -- the call ---------------------------------------------------------- #
    async def complete(
        self, request: AIRequest, *, user_id: uuid.UUID | None = None
    ) -> AIResponse:
        """Refuse, with the reason the current state gives.

        The capability check comes **first**, deliberately: image generation is
        never routed here *in any state*, so an authorised connection must not
        produce a different refusal from an unavailable one.
        """
        need = request.required_capabilities()
        missing = need.missing(self.capabilities)
        if missing:
            raise UnsupportedCapability(
                missing,
                f"the ChatGPT-plan route does not support: {', '.join(missing)}",
            )
        if not self.connection.can_infer:
            raise ProviderUnavailable(
                "ChatGPT-plan inference is not available in this build.",
                code="chatgpt_plan_unavailable",
                detail={"state": self.connection.state, "terminal": self.connection.terminal},
            )
        # Reached only once approval lands; the streaming client is Phase D.
        raise ProviderUnavailable(
            "ChatGPT-plan inference is authorised but not implemented in this build.",
            code="chatgpt_plan_not_implemented",
            detail={"state": self.connection.state},
        )

    def supports(self, need: Capabilities) -> bool:
        return need.satisfied_by(self.capabilities)


__all__ = [
    "ALLOWANCE_EXHAUSTED_CODE",
    "AUTHORIZE_URL",
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_CAP_SECONDS",
    "CHATGPT_PLAN_CAPABILITIES",
    "CHATGPT_PLAN_STATES",
    "ELIGIBLE_PLAN_TIERS",
    "HAS_ALLOWANCE_API",
    "HAS_REVOCATION_WEBHOOK",
    "INITIAL_STATE",
    "INVALID_USER_CODE",
    "MANDATORY_STORE",
    "MANDATORY_STREAM",
    "NOT_ELIGIBLE_CODE",
    "REQUIRED_SCOPES",
    "RESPONSES_URL",
    "REVOKE_URL",
    "REVOKING_REFRESH_ERRORS",
    "TOKEN_URL",
    "TRANSIENT_ERROR_CODES",
    "UNSUPPORTED_CAPABILITY_CODE",
    "UNSUPPORTED_ON_PLAN_ROUTE",
    "ChatGPTConnection",
    "ChatGPTPlanProvider",
]
