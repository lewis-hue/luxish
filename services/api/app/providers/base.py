"""The provider contract: declared capabilities, request/response shapes,
usage reservation, and run accounting.

Three ideas carry this module.

**Adapters declare, the router never guesses (ADR-006).** Every adapter
publishes a :class:`ProviderCapabilities` record — ten independent booleans
plus limits and unit price. Defaults are all ``False``, so an adapter that
forgets to declare something is treated as not having it. Silence is never a
yes.

**Requests are built from an allowlist, never by filtering a dict.** An
:class:`AIRequest` carries named fields, including the parameters we know a
vendor refuses; an adapter copies the ones it is allowed to send and cannot
accidentally forward the rest.

**Money is integer minor units (ADR-011).** Published prices are minor units
per million tokens, which makes ``tokens x price`` exactly *micro-minor* units
with no division and no float. Rounding to the ledger's minor unit happens once,
upwards, at the end.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.ai_run import AIRun

#: Micro-minor units per minor unit. A minor unit is the smallest *currency*
#: unit (a cent); a micro-minor unit is a millionth of one, which is the
#: resolution per-million-token pricing actually needs.
MICRO_PER_MINOR = 1_000_000

#: Values Meta documents for ``reasoning_effort`` (ADR-007).
REASONING_EFFORT_VALUES: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

#: Values Meta documents for ``prompt_cache_retention``.
PROMPT_CACHE_RETENTIONS: tuple[str, ...] = ("in_memory", "24h")

#: Verified: ``safety_identifier`` is capped at 64 characters.
MAX_SAFETY_IDENTIFIER_LENGTH = 64

#: The ten capability booleans ADR-006 requires every adapter to declare.
CAPABILITY_FLAGS: tuple[str, ...] = (
    "text_in",
    "image_in",
    "video_in",
    "audio_in",
    "text_out",
    "image_out",
    "tools",
    "structured_output",
    "streaming",
    "embeddings",
)


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class ProviderError(ApiError):
    """Base class for every provider-layer failure."""

    status_code = 502
    code = "provider_error"
    default_message = "The model provider could not be used."


class InvalidProviderRequest(ProviderError):
    """The request is malformed by *our* rules, before anyone is billed.

    Raised for a parameter the vendor documents as invalid, a strict schema that
    cannot be strict, or a model id that does not exist. Every instance of this
    is a round trip we did not pay for.
    """

    status_code = 400
    code = "invalid_provider_request"
    default_message = "The model request is not valid."


class UnsupportedCapability(ProviderError):
    """The chosen provider or model does not declare what the request needs.

    Always raised before a network call: ADR-006 exists because a router that
    assumes parity fails silently and bills for it.
    """

    status_code = 400
    code = "unsupported_capability"
    default_message = "The selected model does not support that request."

    def __init__(self, missing: Sequence[str], message: str | None = None, **kw: Any) -> None:
        self.missing = tuple(missing)
        super().__init__(
            message or f"unsupported capability: {', '.join(self.missing) or 'unknown'}",
            detail={"missing": list(self.missing)},
            **kw,
        )


class NoEligibleProvider(ProviderError):
    """No registered provider satisfies capability + entitlement + consent +
    billing source.

    ``reasons`` names the *first* failing question per candidate, so an operator
    reading a log learns which of the four to fix rather than guessing.
    """

    status_code = 503
    code = "no_eligible_provider"
    default_message = "No model provider is eligible for this request."

    def __init__(self, reasons: Mapping[str, str], message: str | None = None) -> None:
        self.reasons = dict(reasons)
        super().__init__(message, detail={"reasons": self.reasons})


class ProviderUnavailable(ProviderError):
    """The provider is reachable in principle but not usable right now."""

    status_code = 503
    code = "provider_unavailable"
    default_message = "The model provider is not available."


class ProviderRateLimited(ProviderError):
    """A reservation was refused because a published limit would be exceeded.

    Meta's limits are per *team*, so this is raised from a team-wide counter —
    a per-key counter would let one team sail past 3000 RPM with two keys.
    """

    status_code = 429
    code = "provider_rate_limited"
    default_message = "The team's model rate limit is exhausted for this window."

    def __init__(self, limit: str, *, team_id: str | None = None) -> None:
        self.limit = limit
        super().__init__(
            f"team rate limit reached: {limit}",
            detail={"limit": limit, **({"team_id": team_id} if team_id else {})},
        )


# --------------------------------------------------------------------------- #
# capabilities
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderCapabilities:
    """What an adapter can honestly do, plus its limits and unit price.

    Every boolean defaults to ``False`` and every limit to ``None``. ``None`` on
    a limit means *undocumented* — notably ``max_output_tokens``, which Meta does
    not publish. Writing a number there would be an invention, and the router
    would then enforce a ceiling the vendor never stated.
    """

    text_in: bool = False
    image_in: bool = False
    video_in: bool = False
    audio_in: bool = False
    text_out: bool = False
    image_out: bool = False
    tools: bool = False
    structured_output: bool = False
    streaming: bool = False
    embeddings: bool = False
    #: Whether the route accepts an uploaded file. The ChatGPT-plan route does
    #: not (the Files API is unsupported there), which is a separate question
    #: from whether it accepts an image in a message.
    file_upload: bool = False

    # -- limits ------------------------------------------------------------ #
    max_context_tokens: int | None = None
    #: NOT DOCUMENTED by Meta. Stays ``None``; see the class docstring.
    max_output_tokens: int | None = None
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    max_request_bytes: int | None = None
    max_audio_seconds: int | None = None
    accepted_audio_formats: tuple[str, ...] = ()

    # -- unit price, integer minor units (ADR-011) ------------------------- #
    input_price_minor_per_million_tokens: int | None = None
    output_price_minor_per_million_tokens: int | None = None
    #: Priced per image in micro-minor units so $2.50/1000 images is exact.
    price_micro_minor_per_image: int | None = None
    currency: str = "USD"


def union_capabilities(*records: ProviderCapabilities) -> ProviderCapabilities:
    """Merge model-level records into one provider-level record.

    Booleans are OR-ed and limits take the largest stated value, because the
    question the router asks is "can this *provider* do X at all". Prices are
    deliberately dropped: a price belongs to one model, and a merged price would
    be a number nobody charges.
    """
    merged: dict[str, Any] = {}
    for name in CAPABILITY_FLAGS + ("file_upload",):
        merged[name] = any(getattr(r, name) for r in records)
    for name in (
        "max_context_tokens",
        "max_output_tokens",
        "requests_per_minute",
        "tokens_per_minute",
        "max_request_bytes",
        "max_audio_seconds",
    ):
        stated = [getattr(r, name) for r in records if getattr(r, name) is not None]
        merged[name] = max(stated) if stated else None
    formats: list[str] = []
    for record in records:
        formats.extend(f for f in record.accepted_audio_formats if f not in formats)
    merged["accepted_audio_formats"] = tuple(formats)
    currencies = {r.currency for r in records} or {"USD"}
    merged["currency"] = currencies.pop() if len(currencies) == 1 else "USD"
    return ProviderCapabilities(**merged)


@dataclass(frozen=True, slots=True, kw_only=True)
class Capabilities:
    """What a request *needs*. Only the ``True`` flags are requirements."""

    text_in: bool = False
    image_in: bool = False
    video_in: bool = False
    audio_in: bool = False
    text_out: bool = False
    image_out: bool = False
    tools: bool = False
    structured_output: bool = False
    streaming: bool = False
    embeddings: bool = False
    file_upload: bool = False

    def missing(self, capabilities: ProviderCapabilities) -> tuple[str, ...]:
        """The required flags this record does not declare, in field order."""
        return tuple(
            f.name
            for f in fields(self)
            if getattr(self, f.name) and not getattr(capabilities, f.name)
        )

    def satisfied_by(self, capabilities: ProviderCapabilities) -> bool:
        return not self.missing(capabilities)


#: The need every plain text completion has, spelled once.
TEXT_COMPLETION: Capabilities = Capabilities(text_in=True, text_out=True)


# --------------------------------------------------------------------------- #
# cost
# --------------------------------------------------------------------------- #
def token_cost_micro_minor(
    capabilities: ProviderCapabilities, *, input_tokens: int, output_tokens: int
) -> int:
    """Token cost in micro-minor units, by integer multiplication only.

    ``price`` is minor units per million tokens, so ``tokens x price`` is
    ``tokens x minor / 10^6`` expressed in millionths of a minor unit — exactly
    micro-minor units. No division, no rounding, no float.
    """
    inbound = capabilities.input_price_minor_per_million_tokens or 0
    outbound = capabilities.output_price_minor_per_million_tokens or 0
    return max(0, input_tokens) * inbound + max(0, output_tokens) * outbound


def image_cost_micro_minor(capabilities: ProviderCapabilities, *, images: int) -> int:
    return max(0, images) * (capabilities.price_micro_minor_per_image or 0)


def minor_units(micro_minor: int) -> int:
    """Round micro-minor units up to whole minor units.

    Upwards on purpose: a cost that rounds to zero is a cost somebody else pays.
    """
    return math.ceil(micro_minor / MICRO_PER_MINOR)


# --------------------------------------------------------------------------- #
# requests
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AIMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: Any

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True, kw_only=True)
class JsonSchemaFormat:
    """A structured-output contract, validated at construction.

    Verified: strict mode requires a root ``object`` with
    ``additionalProperties: false``. Checking it here means a malformed schema
    costs nothing instead of a 400 from the vendor.
    """

    name: str
    json_schema: Mapping[str, Any]
    strict: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidProviderRequest("a json_schema response format needs a name")
        if not self.strict:
            return
        if self.json_schema.get("type") != "object":
            raise InvalidProviderRequest(
                "strict structured output requires a root object schema"
            )
        if self.json_schema.get("additionalProperties") is not False:
            raise InvalidProviderRequest(
                "strict structured output requires additionalProperties: false on the root"
            )

    def as_response_format(self) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self.name,
                "schema": dict(self.json_schema),
                "strict": self.strict,
            },
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AIRequest:
    """One model call, described in vendor-neutral terms.

    The block of **refused parameters** at the bottom exists so that a caller
    migrating code from another SDK is refused *structurally* rather than
    silently: the fields are accepted here and no adapter is allowed to copy
    them into a request body. Each one returns HTTP 400 from Meta (ADR-007),
    and ``max_tokens`` is deprecated in favour of ``max_completion_tokens``.
    """

    # -- content ----------------------------------------------------------- #
    prompt: str | None = None
    messages: tuple[AIMessage, ...] = ()
    system: str | None = None
    model: str | None = None

    # -- accounting -------------------------------------------------------- #
    #: Recorded on every AIRun. Prompts are versioned modules (Task 8).
    prompt_version: str = "unversioned"
    purpose: str | None = None
    #: What the request needs. ``None`` means "plain text in, text out".
    needs: Capabilities | None = None

    # -- supported parameters ---------------------------------------------- #
    max_completion_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stream: bool = False
    stream_options: Mapping[str, Any] | None = None
    reasoning_effort: str | None = None
    seed: int | None = None
    tools: tuple[Mapping[str, Any], ...] = ()
    tool_choice: str | Mapping[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    response_format: JsonSchemaFormat | None = None
    #: Verified default is false, and we send it explicitly rather than relying
    #: on a default that could change.
    store: bool = False
    prompt_cache_key: str | None = None
    prompt_cache_retention: str | None = None
    safety_identifier: str | None = None
    service_tier: str | None = None
    metadata: Mapping[str, str] | None = None

    # -- refused parameters: accepted here, never sent anywhere ------------ #
    stop: Any = None
    n: Any = None
    verbosity: Any = None
    logit_bias: Any = None
    prediction: Any = None
    web_search_options: Any = None
    modalities: Any = None
    audio: Any = None
    logprobs: Any = None
    top_logprobs: Any = None
    max_tokens: Any = None

    def __post_init__(self) -> None:
        if not self.prompt and not self.messages:
            raise InvalidProviderRequest("a request needs either a prompt or messages")
        if self.reasoning_effort is not None and self.reasoning_effort not in (
            REASONING_EFFORT_VALUES
        ):
            raise InvalidProviderRequest(
                f"reasoning_effort must be one of {REASONING_EFFORT_VALUES}, "
                f"got {self.reasoning_effort!r}"
            )
        if (
            self.prompt_cache_retention is not None
            and self.prompt_cache_retention not in PROMPT_CACHE_RETENTIONS
        ):
            raise InvalidProviderRequest(
                f"prompt_cache_retention must be one of {PROMPT_CACHE_RETENTIONS}, "
                f"got {self.prompt_cache_retention!r}"
            )
        if (
            self.safety_identifier is not None
            and len(self.safety_identifier) > MAX_SAFETY_IDENTIFIER_LENGTH
        ):
            raise InvalidProviderRequest(
                f"safety_identifier is capped at {MAX_SAFETY_IDENTIFIER_LENGTH} characters"
            )
        if self.max_completion_tokens is not None and self.max_completion_tokens <= 0:
            raise InvalidProviderRequest("max_completion_tokens must be positive")

    # -- derived views ----------------------------------------------------- #
    def as_messages(self) -> tuple[dict[str, Any], ...]:
        """The message list, whichever way the caller described the request."""
        rendered: list[dict[str, Any]] = []
        if self.system:
            rendered.append({"role": "system", "content": self.system})
        rendered.extend(m.as_dict() for m in self.messages)
        if self.prompt:
            rendered.append({"role": "user", "content": self.prompt})
        return tuple(rendered)

    def required_capabilities(self) -> Capabilities:
        """What this request needs, falling back to plain text in/text out."""
        if self.needs is not None:
            return self.needs
        need = {"text_in": True, "text_out": True}
        if self.tools:
            need["tools"] = True
        if self.response_format is not None:
            need["structured_output"] = True
        if self.stream:
            need["streaming"] = True
        return Capabilities(**need)

    def estimated_prompt_tokens(self) -> int:
        """A cheap pre-call estimate, used only to size a reservation.

        Four characters per token is the usual rule of thumb; it is an estimate,
        which is exactly why the reservation is reconciled against the real
        usage afterwards rather than trusted.
        """
        characters = sum(len(str(m["content"])) for m in self.as_messages())
        return max(1, characters // 4)


# --------------------------------------------------------------------------- #
# responses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True, kw_only=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedImage:
    """One image an adapter produced, with the type its bytes actually are.

    ``content_type`` is read from the response rather than assumed: Meta's
    image endpoint returns WEBP, not the PNG the OpenAI-shaped client makes it
    easy to expect, and storing bytes under the wrong type gives a picture
    that silently fails to render on some clients and not others.
    """

    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AIResponse:
    provider: str
    model: str
    usage: TokenUsage
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    images: int = 0
    #: The generated images themselves, decoded, in the order returned.
    #:
    #: Carried rather than counted. ``images`` records how many were produced
    #: and therefore what was charged; this is what was produced, which is the
    #: only thing a caller that needs to store a picture can use. Empty for
    #: every text completion, and for an adapter that reports a count without
    #: returning data.
    image_data: tuple[GeneratedImage, ...] = ()
    finish_reason: str | None = None
    response_id: str | None = None
    cost_micro_minor: int = 0

    @property
    def cost_minor(self) -> int:
        return minor_units(self.cost_micro_minor)


@runtime_checkable
class AIProvider(Protocol):
    """What the registry is allowed to assume about an adapter.

    ``user_id`` is keyword-only and optional so the protocol stays
    ``complete(request) -> AIResponse`` while adapters that must attribute spend
    can still be handed an owner.
    """

    name: str
    capabilities: ProviderCapabilities

    async def complete(
        self, request: AIRequest, *, user_id: uuid.UUID | None = None
    ) -> AIResponse: ...


# --------------------------------------------------------------------------- #
# usage reservation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True, kw_only=True)
class UsageLimits:
    """Published limits for one window. ``None`` means "not limited by us"."""

    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    #: Our own cap on simultaneous in-flight calls per team. ASSUMED; the vendor
    #: publishes rate, not concurrency.
    max_concurrent: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    """A claim on a team's window, taken before the call is made."""

    id: str
    team_id: str
    model: str
    tokens: int
    micro_minor: int


def usage_keys(team_id: str, bucket: int, *, namespace: str = "aiusage") -> tuple[str, str, str]:
    """The three counter keys for one team-window.

    Keyed on the **team**, never on the API key: Meta's limits are per team, so
    two keys on one team share one budget (ADR-007).
    """
    return (
        f"{namespace}:{team_id}:{bucket}:requests",
        f"{namespace}:{team_id}:{bucket}:tokens",
        f"{namespace}:{team_id}:in_flight",
    )


@runtime_checkable
class UsageStore(Protocol):
    """Reserve before the call, reconcile from the response, release on failure.

    Redis is one implementation; :class:`InMemoryUsageStore` is the other, which
    is what lets the test suite and a single-process dev box run with no Redis.
    """

    async def reserve(
        self,
        *,
        team_id: str,
        model: str,
        tokens: int,
        micro_minor: int,
        limits: UsageLimits,
    ) -> Reservation: ...

    async def reconcile(
        self, reservation: Reservation, *, tokens: int, micro_minor: int
    ) -> None: ...

    async def release(self, reservation: Reservation) -> None: ...

    async def snapshot(self, team_id: str) -> dict[str, int]: ...


@dataclass
class _Window:
    bucket: int
    requests: int = 0
    tokens: int = 0
    micro_minor: int = 0


class InMemoryUsageStore:
    """A process-local reservation store with Redis's semantics.

    Used by the test suite and by single-process local development. It holds the
    same three counters under one lock, so reserve-check-commit is atomic here
    for the same reason the Lua script is atomic there.

    ``snapshot`` reports the window it last *wrote* rather than the window the
    clock is in now, so a caller that straddles a minute boundary still reads
    its own writes.
    """

    def __init__(
        self,
        *,
        window_seconds: int = 60,
        clock: Any = time.monotonic,
        namespace: str = "aiusage",
    ) -> None:
        self._window_seconds = window_seconds
        self._clock = clock
        self._namespace = namespace
        self._windows: dict[str, _Window] = {}
        self._in_flight: dict[str, int] = {}
        self._open: dict[str, Reservation] = {}
        self._keys: list[str] = []
        self._lock = asyncio.Lock()
        #: ``(action, team_id)`` in order, so a test can assert the sequence.
        self.events: list[tuple[str, str]] = []

    def tracked_keys(self) -> tuple[str, ...]:
        """Every counter key this store has touched, in first-use order.

        Exposed so a test can assert the namespace is keyed on the team and
        never on an API key.
        """
        return tuple(dict.fromkeys(self._keys))

    def _bucket(self) -> int:
        return int(self._clock() // self._window_seconds)

    def _window_for(self, team_id: str, *, roll: bool) -> _Window:
        window = self._windows.get(team_id)
        bucket = self._bucket()
        if window is None or (roll and window.bucket != bucket):
            window = _Window(bucket=bucket)
            self._windows[team_id] = window
        return window

    async def reserve(
        self,
        *,
        team_id: str,
        model: str,
        tokens: int,
        micro_minor: int,
        limits: UsageLimits,
    ) -> Reservation:
        async with self._lock:
            window = self._window_for(team_id, roll=True)
            self._keys.extend(usage_keys(team_id, window.bucket, namespace=self._namespace))

            if (
                limits.requests_per_minute is not None
                and window.requests + 1 > limits.requests_per_minute
            ):
                raise ProviderRateLimited("requests_per_minute", team_id=team_id)
            if (
                limits.tokens_per_minute is not None
                and window.tokens + tokens > limits.tokens_per_minute
            ):
                raise ProviderRateLimited("tokens_per_minute", team_id=team_id)
            in_flight = self._in_flight.get(team_id, 0)
            if limits.max_concurrent is not None and in_flight + 1 > limits.max_concurrent:
                raise ProviderRateLimited("max_concurrent", team_id=team_id)

            window.requests += 1
            window.tokens += tokens
            window.micro_minor += micro_minor
            self._in_flight[team_id] = in_flight + 1

            reservation = Reservation(
                id=uuid.uuid4().hex,
                team_id=team_id,
                model=model,
                tokens=tokens,
                micro_minor=micro_minor,
            )
            self._open[reservation.id] = reservation
            self.events.append(("reserve", team_id))
            return reservation

    async def reconcile(
        self, reservation: Reservation, *, tokens: int, micro_minor: int
    ) -> None:
        async with self._lock:
            self.events.append(("reconcile", reservation.team_id))
            if self._open.pop(reservation.id, None) is None:
                return  # already settled; reconciling twice must not double count
            window = self._window_for(reservation.team_id, roll=False)
            window.tokens += tokens - reservation.tokens
            window.micro_minor += micro_minor - reservation.micro_minor
            self._in_flight[reservation.team_id] = max(
                0, self._in_flight.get(reservation.team_id, 0) - 1
            )

    async def release(self, reservation: Reservation) -> None:
        async with self._lock:
            self.events.append(("release", reservation.team_id))
            if self._open.pop(reservation.id, None) is None:
                return
            window = self._window_for(reservation.team_id, roll=False)
            window.tokens -= reservation.tokens
            window.micro_minor -= reservation.micro_minor
            window.requests = max(0, window.requests - 1)
            self._in_flight[reservation.team_id] = max(
                0, self._in_flight.get(reservation.team_id, 0) - 1
            )

    async def snapshot(self, team_id: str) -> dict[str, int]:
        window = self._windows.get(team_id)
        return {
            "requests": window.requests if window else 0,
            "tokens": window.tokens if window else 0,
            "micro_minor": window.micro_minor if window else 0,
            "in_flight": self._in_flight.get(team_id, 0),
        }


#: Reserve-and-check in one server-side step. Two round trips would be a race:
#: between an ``INCR`` and the limit comparison, another process can commit.
#:
#: This is a Redis ``EVAL`` (server-side Lua), not Python ``eval``. The script is
#: a module constant and no caller-supplied text is ever concatenated into it —
#: only ``KEYS``/``ARGV``, which Redis treats as data.
RESERVE_SCRIPT = """
local requests_key, tokens_key, inflight_key = KEYS[1], KEYS[2], KEYS[3]
local tokens = tonumber(ARGV[1])
local rpm = tonumber(ARGV[2])
local tpm = tonumber(ARGV[3])
local max_concurrent = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local requests = redis.call('INCR', requests_key)
if requests == 1 then redis.call('EXPIRE', requests_key, ttl) end
if rpm > 0 and requests > rpm then
  redis.call('DECR', requests_key)
  return {0, 'requests_per_minute'}
end

local used = redis.call('INCRBY', tokens_key, tokens)
if used == tokens then redis.call('EXPIRE', tokens_key, ttl) end
if tpm > 0 and used > tpm then
  redis.call('DECRBY', tokens_key, tokens)
  redis.call('DECR', requests_key)
  return {0, 'tokens_per_minute'}
end

local inflight = redis.call('INCR', inflight_key)
if inflight == 1 then redis.call('EXPIRE', inflight_key, ttl * 10) end
if max_concurrent > 0 and inflight > max_concurrent then
  redis.call('DECR', inflight_key)
  redis.call('DECRBY', tokens_key, tokens)
  redis.call('DECR', requests_key)
  return {0, 'max_concurrent'}
end

return {1, 'ok'}
"""

#: Settle a reservation: adjust the token counter by the difference and drop the
#: in-flight count. One call, so a reconcile cannot half-apply.
SETTLE_SCRIPT = """
local tokens_key, inflight_key = KEYS[1], KEYS[2]
local delta = tonumber(ARGV[1])
local drop_request = tonumber(ARGV[2])
local requests_key = KEYS[3]

if delta ~= 0 then redis.call('INCRBY', tokens_key, delta) end
if drop_request == 1 then
  local requests = redis.call('GET', requests_key)
  if requests and tonumber(requests) > 0 then redis.call('DECR', requests_key) end
end
local inflight = redis.call('DECR', inflight_key)
if inflight < 0 then redis.call('SET', inflight_key, 0) end
return 1
"""


class RedisUsageStore:
    """The deployed reservation store.

    One ``EVAL`` per reservation: the counters and the limit comparison happen
    on the server, in one step, so two API processes cannot both believe they
    were under the cap. Counters are keyed on the team (ADR-007).
    """

    def __init__(
        self, redis: Any, *, window_seconds: int = 60, namespace: str = "aiusage"
    ) -> None:
        self._redis = redis
        self._window_seconds = window_seconds
        self._namespace = namespace

    def _bucket(self) -> int:
        return int(time.time() // self._window_seconds)

    @staticmethod
    def _text(value: Any) -> str:
        return value.decode() if isinstance(value, bytes | bytearray) else str(value)

    async def reserve(
        self,
        *,
        team_id: str,
        model: str,
        tokens: int,
        micro_minor: int,
        limits: UsageLimits,
    ) -> Reservation:
        bucket = self._bucket()
        requests_key, tokens_key, inflight_key = usage_keys(
            team_id, bucket, namespace=self._namespace
        )
        reply = await self._redis.eval(
            RESERVE_SCRIPT,
            3,
            requests_key,
            tokens_key,
            inflight_key,
            tokens,
            limits.requests_per_minute or 0,
            limits.tokens_per_minute or 0,
            limits.max_concurrent or 0,
            self._window_seconds * 2,
        )
        allowed, detail = reply[0], self._text(reply[1])
        if int(allowed) != 1:
            raise ProviderRateLimited(detail, team_id=team_id)
        return Reservation(
            id=f"{team_id}:{bucket}:{uuid.uuid4().hex}",
            team_id=team_id,
            model=model,
            tokens=tokens,
            micro_minor=micro_minor,
        )

    async def _settle(
        self, reservation: Reservation, *, delta: int, drop_request: bool
    ) -> None:
        bucket = int(reservation.id.split(":")[1])
        requests_key, tokens_key, inflight_key = usage_keys(
            reservation.team_id, bucket, namespace=self._namespace
        )
        await self._redis.eval(
            SETTLE_SCRIPT,
            3,
            tokens_key,
            inflight_key,
            requests_key,
            delta,
            1 if drop_request else 0,
        )

    async def reconcile(
        self, reservation: Reservation, *, tokens: int, micro_minor: int
    ) -> None:
        await self._settle(
            reservation, delta=tokens - reservation.tokens, drop_request=False
        )

    async def release(self, reservation: Reservation) -> None:
        await self._settle(reservation, delta=-reservation.tokens, drop_request=True)

    async def snapshot(self, team_id: str) -> dict[str, int]:
        requests_key, tokens_key, inflight_key = usage_keys(
            team_id, self._bucket(), namespace=self._namespace
        )
        values = await self._redis.mget(requests_key, tokens_key, inflight_key)
        requests, tokens, in_flight = (int(v or 0) for v in values)
        return {
            "requests": requests,
            "tokens": tokens,
            "micro_minor": 0,  # cost is reconciled onto the AIRun, not into Redis
            "in_flight": in_flight,
        }


# --------------------------------------------------------------------------- #
# run accounting
# --------------------------------------------------------------------------- #
class AIRunRecorder:
    """Writes one :class:`AIRun` per model call.

    Every adapter's ``complete`` requires one. An unaccounted model call is a
    cost nobody can attribute and a run nobody can audit, so "forgot to record
    it" is made impossible rather than discouraged.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(
        self,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        user_id: uuid.UUID | None = None,
        purpose: str | None = None,
        team_id: str | None = None,
        reservation_id: str | None = None,
        currency: str = "USD",
    ) -> AIRun:
        run = AIRun(
            user_id=user_id,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            purpose=purpose,
            team_id=team_id,
            reservation_id=reservation_id,
            currency=currency,
            outcome="pending",
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def finish(
        self,
        run: AIRun,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        reasoning_tokens: int = 0,
        images: int = 0,
        cost_micro_minor: int = 0,
        finish_reason: str | None = None,
        response_id: str | None = None,
        outcome: str = "succeeded",
    ) -> AIRun:
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.cached_input_tokens = cached_input_tokens
        run.reasoning_tokens = reasoning_tokens
        run.images = images
        run.cost_micro_minor = cost_micro_minor
        run.cost_minor = minor_units(cost_micro_minor)
        run.finish_reason = finish_reason
        run.response_id = response_id
        run.outcome = outcome
        self._close(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def fail(
        self,
        run: AIRun,
        *,
        code: str,
        message: str | None = None,
        outcome: str = "failed",
    ) -> AIRun:
        run.outcome = outcome
        run.error_code = code
        run.error_message = (message or "")[:2000] or None
        self._close(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    @staticmethod
    def _close(run: AIRun) -> None:
        finished = datetime.now(UTC)
        run.finished_at = finished
        started = run.started_at or finished
        run.latency_ms = max(0, int((finished - started).total_seconds() * 1000))


__all__ = [
    "CAPABILITY_FLAGS",
    "MAX_SAFETY_IDENTIFIER_LENGTH",
    "MICRO_PER_MINOR",
    "PROMPT_CACHE_RETENTIONS",
    "REASONING_EFFORT_VALUES",
    "RESERVE_SCRIPT",
    "TEXT_COMPLETION",
    "AIMessage",
    "AIProvider",
    "AIRequest",
    "AIResponse",
    "AIRunRecorder",
    "Capabilities",
    "GeneratedImage",
    "InMemoryUsageStore",
    "InvalidProviderRequest",
    "JsonSchemaFormat",
    "NoEligibleProvider",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderUnavailable",
    "RedisUsageStore",
    "Reservation",
    "TokenUsage",
    "ToolCall",
    "UnsupportedCapability",
    "UsageLimits",
    "UsageStore",
    "image_cost_micro_minor",
    "minor_units",
    "token_cost_micro_minor",
    "union_capabilities",
    "usage_keys",
]
