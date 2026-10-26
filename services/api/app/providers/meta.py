"""The Meta Model API adapter (ADR-005, ADR-006, ADR-007).

Every constant in this module is a **verified vendor fact**, fetched on
2026-10-26, not a preference:

* Base URL ``https://api.meta.ai/v1``; auth is a static key as
  ``Authorization: Bearer $MODEL_API_KEY`` (keys are prefixed ``LLM_``). There
  is no first-party Meta SDK, so we call it through the ``openai`` SDK with
  ``base_url`` set (``https://dev.meta.ai/docs/sdks``).
* Ten parameters return **HTTP 400** and are never sent — even though Meta's
  published OpenAPI schema still lists several of them. The prose page is
  authoritative (``https://dev.meta.ai/docs/protocols/chat-completions``). The
  body is therefore assembled from :data:`CHAT_BODY_ALLOWLIST` by name; it is
  *not* a dict with the bad keys filtered out, because a filter is one forgotten
  key away from a 400 and a new key away from a silent leak.
* ``max_tokens`` is deprecated in favour of ``max_completion_tokens``. The
  model's maximum output length is **not documented**, so no ceiling is
  hardcoded — :attr:`ProviderCapabilities.max_output_tokens` stays ``None`` and
  the number we send is *our* budget, which is a different claim.
* **There is no embeddings model and no embeddings endpoint** (ADR-004). Nothing
  here calls one, and every capability record says ``embeddings=False``.
* **Rate limits are per team, not per API key**, so the limiter is keyed on the
  team. Two keys belonging to one team share one budget.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.errors import CapabilityUnavailable
from app.providers.base import (
    PROMPT_CACHE_RETENTIONS,
    REASONING_EFFORT_VALUES,
    AIRequest,
    AIResponse,
    AIRunRecorder,
    Capabilities,
    InMemoryUsageStore,
    InvalidProviderRequest,
    ProviderCapabilities,
    TokenUsage,
    ToolCall,
    UnsupportedCapability,
    UsageLimits,
    UsageStore,
    image_cost_micro_minor,
    token_cost_micro_minor,
    union_capabilities,
)

#: Verified. The ``openai`` SDK is pointed at this; there is no Meta SDK.
META_BASE_URL = "https://api.meta.ai/v1"

#: Verified: Meta Model API keys carry this prefix.
API_KEY_PREFIX = "LLM_"

#: Verified paths. ``/images/*`` happens to match the OpenAI shape;
#: ``/asr/transcribe`` does not, which is why transcription is a direct HTTP
#: call rather than ``client.audio.transcriptions``.
IMAGE_GENERATIONS_PATH = "/images/generations"
IMAGE_EDITS_PATH = "/images/edits"
TRANSCRIBE_PATH = "/asr/transcribe"

#: Verified: each of these returns HTTP 400. ``max_tokens`` is deprecated.
REFUSED_PARAMETERS: frozenset[str] = frozenset(
    {
        "stop",
        "n",
        "verbosity",
        "logit_bias",
        "prediction",
        "web_search_options",
        "modalities",
        "audio",
        "logprobs",
        "top_logprobs",
        "max_tokens",
    }
)

#: The only keys that may appear in a chat body. An allowlist, by name.
CHAT_BODY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "model",
        "messages",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "stream",
        "stream_options",
        "reasoning_effort",
        "seed",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "store",
        "prompt_cache_key",
        "prompt_cache_retention",
        "safety_identifier",
        "service_tier",
        "metadata",
    }
)

#: Verified accepted values for ``reasoning_effort``.
REASONING_EFFORTS: tuple[str, ...] = REASONING_EFFORT_VALUES

#: Our per-request output budget. **Not** a model ceiling: Meta does not publish
#: one, so claiming to know it would be an invention. This is a cost control and
#: is meant to be overridden per call.
DEFAULT_MAX_COMPLETION_TOKENS = 4_096

DEFAULT_MODEL = "muse-spark-1.3"

#: Verified transcription limits: 400 above ten minutes or for non-WAV audio,
#: 413 for a body over 32 MB. Refusing locally costs nothing; a 400 costs a
#: round trip and an upload.
TRANSCRIBE_MAX_AUDIO_SECONDS = 600
TRANSCRIBE_MAX_REQUEST_BYTES = 32 * 1024 * 1024
TRANSCRIBE_ACCEPTED_FORMATS: tuple[str, ...] = ("audio/wav", "audio/x-wav", "audio/wave")

#: Published shared limits for the two text models: 3000 RPM / 4M TPM, per team.
_TEXT_RPM = 3000
_TEXT_TPM = 4_000_000
_CONTEXT_TOKENS = 1_048_576


@dataclass(frozen=True, slots=True, kw_only=True)
class MetaModel:
    """One model in the catalogue, with the endpoint it is reached through."""

    id: str
    capabilities: ProviderCapabilities
    #: Which API surface serves it. The router uses this to refuse a chat
    #: request aimed at the image model before building a body for it.
    endpoint: str
    notes: str = ""


META_MODELS: Mapping[str, MetaModel] = {
    #: Default. Text + image + video + audio + PDF in, text out, tools,
    #: structured output. $1.25 / 1M in, $4.25 / 1M out.
    "muse-spark-1.3": MetaModel(
        id="muse-spark-1.3",
        endpoint="chat.completions",
        capabilities=ProviderCapabilities(
            text_in=True,
            image_in=True,
            video_in=True,
            audio_in=True,
            text_out=True,
            tools=True,
            structured_output=True,
            streaming=True,
            file_upload=True,
            embeddings=False,
            max_context_tokens=_CONTEXT_TOKENS,
            max_output_tokens=None,  # not documented
            requests_per_minute=_TEXT_RPM,
            tokens_per_minute=_TEXT_TPM,
            input_price_minor_per_million_tokens=125,
            output_price_minor_per_million_tokens=425,
        ),
        notes="default text model; accepts PDF input",
    ),
    #: Same modalities as spark, strongest reasoning. $4.00 / 1M in,
    #: $20.00 / 1M out — roughly five times the price, so it is opt-in.
    "muse-wonder-1.0": MetaModel(
        id="muse-wonder-1.0",
        endpoint="chat.completions",
        capabilities=ProviderCapabilities(
            text_in=True,
            image_in=True,
            video_in=True,
            audio_in=True,
            text_out=True,
            tools=True,
            structured_output=True,
            streaming=True,
            file_upload=True,
            embeddings=False,
            max_context_tokens=_CONTEXT_TOKENS,
            max_output_tokens=None,  # not documented
            requests_per_minute=_TEXT_RPM,
            tokens_per_minute=_TEXT_TPM,
            input_price_minor_per_million_tokens=400,
            output_price_minor_per_million_tokens=2000,
        ),
        notes="strongest reasoning; five times spark's price",
    ),
    #: Text + image in, image out. 150 RPM. $0.01 per image.
    "muse-image-1.0": MetaModel(
        id="muse-image-1.0",
        endpoint="images.generations",
        capabilities=ProviderCapabilities(
            text_in=True,
            image_in=True,
            image_out=True,
            embeddings=False,
            max_output_tokens=None,
            requests_per_minute=150,
            price_micro_minor_per_image=1_000_000,
        ),
        notes="generation at /images/generations, editing at /images/edits",
    ),
    #: Audio to text. 400 above ten minutes or for non-WAV; 413 above 32 MB.
    "muse-voice-transcribe-1.0": MetaModel(
        id="muse-voice-transcribe-1.0",
        endpoint="asr.transcribe",
        capabilities=ProviderCapabilities(
            audio_in=True,
            text_out=True,
            embeddings=False,
            max_output_tokens=None,
            max_request_bytes=TRANSCRIBE_MAX_REQUEST_BYTES,
            max_audio_seconds=TRANSCRIBE_MAX_AUDIO_SECONDS,
            accepted_audio_formats=TRANSCRIBE_ACCEPTED_FORMATS,
        ),
        notes="server-side transcription; one implementation for both platforms (ADR-015)",
    ),
    #: Text prompt + image or video in, boxes and masks out (ADR-005).
    #: $2.50 / 1000 images, i.e. 250_000 micro-minor units per image.
    "sam-3.1": MetaModel(
        id="sam-3.1",
        endpoint="segmentation",
        capabilities=ProviderCapabilities(
            text_in=True,
            image_in=True,
            video_in=True,
            embeddings=False,
            max_output_tokens=None,
            price_micro_minor_per_image=250_000,
        ),
        notes="garment segmentation; a worker job, never a request-path call",
    ),
}

#: What the *provider* can do, for the router's first question. Unioned from the
#: catalogue so adding a model cannot leave the router out of date — and
#: ``embeddings`` is False here because it is False in every model.
META_PROVIDER_CAPABILITIES: ProviderCapabilities = union_capabilities(
    *(m.capabilities for m in META_MODELS.values())
)

CHAT_MODELS: tuple[str, ...] = tuple(
    m.id for m in META_MODELS.values() if m.endpoint == "chat.completions"
)


class MetaProvider:
    """The Meta Model API, as one adapter.

    ``client`` is injected so the unit suite needs neither a credential nor a
    network stack; in deployment it is an ``openai.AsyncOpenAI`` built lazily by
    :meth:`client` with ``base_url`` pointed at Meta.
    """

    name = "meta"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = META_BASE_URL,
        model: str = DEFAULT_MODEL,
        team_id: str = "default",
        client: Any | None = None,
        usage: UsageStore | None = None,
        recorder: AIRunRecorder | None = None,
        max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
        max_requests_per_minute: int | None = None,
        max_tokens_per_minute: int | None = None,
        max_concurrent: int | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self.model = model
        self.team_id = team_id
        self._client = client
        self._usage: UsageStore = usage or InMemoryUsageStore()
        self._recorder = recorder
        self._max_completion_tokens = max_completion_tokens
        self._rpm_override = max_requests_per_minute
        self._tpm_override = max_tokens_per_minute
        self._max_concurrent = max_concurrent
        self._timeout_seconds = timeout_seconds

    # -- declared capabilities --------------------------------------------- #
    @property
    def capabilities(self) -> ProviderCapabilities:
        return META_PROVIDER_CAPABILITIES

    def capabilities_for(self, model: str) -> ProviderCapabilities:
        return self._model(model).capabilities

    # -- credentials ------------------------------------------------------- #
    def auth_headers(self) -> dict[str, str]:
        """The verified auth shape: a static key as a bearer token."""
        return {"Authorization": f"Bearer {self._resolved_key()}"}

    def _resolved_key(self) -> str:
        if self._api_key:
            return self._api_key
        from app.config import get_settings

        return get_settings().meta_api_key.get_secret_value()

    def client(self) -> Any:
        """The ``openai`` SDK client, pointed at Meta.

        Imported lazily and built on first use: ``_build_body`` and the
        capability checks must work with no vendor package installed and no
        credential present, which is what keeps the unit suite offline.
        """
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._resolved_key(),
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )
        return self._client

    # -- model resolution, before any network call ------------------------- #
    def _model(self, model_id: str | None) -> MetaModel:
        chosen = model_id or self.model
        try:
            return META_MODELS[chosen]
        except KeyError:
            raise InvalidProviderRequest(
                f"unknown Meta model {chosen!r}; known models are "
                f"{', '.join(sorted(META_MODELS))}"
            ) from None

    def resolve_model(
        self, need: Capabilities | None = None, *, model: str | None = None
    ) -> MetaModel:
        """Pick a model that declares what the request needs, or refuse.

        This is the "fails before any network call" half of ADR-006. A request
        for a modality no model has — embeddings, notably — cannot reach a
        transport from here.
        """
        if model is not None or need is None:
            resolved = self._model(model)
            if need is not None:
                missing = need.missing(resolved.capabilities)
                if missing:
                    raise UnsupportedCapability(
                        missing,
                        f"{resolved.id} does not support: {', '.join(missing)}",
                    )
            return resolved

        preferred = self._model(self.model)
        if need.satisfied_by(preferred.capabilities):
            return preferred
        for candidate in META_MODELS.values():
            if need.satisfied_by(candidate.capabilities):
                return candidate
        raise UnsupportedCapability(
            need.missing(META_PROVIDER_CAPABILITIES),
            "no Meta model declares the requested capabilities",
        )

    # -- request body: an allowlist, by name ------------------------------- #
    def _build_body(
        self, request: AIRequest, *, model: MetaModel | None = None
    ) -> dict[str, Any]:
        """Assemble a chat body from named fields only.

        Nothing iterates the request, so a field added to :class:`AIRequest`
        later — including one of the refused parameters — cannot appear here
        without someone writing the line that puts it there.
        """
        model = model or self._model(request.model)
        if model.endpoint != "chat.completions":
            raise InvalidProviderRequest(
                f"{model.id} is served by {model.endpoint}, not chat completions"
            )

        body: dict[str, Any] = {
            "model": model.id,
            "messages": list(request.as_messages()),
            # Never `max_tokens`: deprecated. The value is our budget, not a
            # model ceiling, because the ceiling is undocumented.
            "max_completion_tokens": (
                request.max_completion_tokens or self._max_completion_tokens
            ),
            # Verified default is false; sent explicitly so a changed default
            # upstream cannot start retaining prompts on our behalf.
            "store": bool(request.store),
        }

        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.frequency_penalty is not None:
            body["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty is not None:
            body["presence_penalty"] = request.presence_penalty
        if request.stream:
            body["stream"] = True
            if request.stream_options is not None:
                body["stream_options"] = dict(request.stream_options)
        if request.reasoning_effort is not None:
            if request.reasoning_effort not in REASONING_EFFORTS:
                raise InvalidProviderRequest(
                    f"reasoning_effort must be one of {REASONING_EFFORTS}"
                )
            body["reasoning_effort"] = request.reasoning_effort
        if request.seed is not None:
            body["seed"] = request.seed
        if request.tools:
            body["tools"] = [dict(t) for t in request.tools]
            if request.tool_choice is not None:
                body["tool_choice"] = request.tool_choice
            if request.parallel_tool_calls is not None:
                body["parallel_tool_calls"] = request.parallel_tool_calls
        if request.response_format is not None:
            body["response_format"] = request.response_format.as_response_format()
        if request.prompt_cache_key is not None:
            body["prompt_cache_key"] = request.prompt_cache_key
        if request.prompt_cache_retention is not None:
            if request.prompt_cache_retention not in PROMPT_CACHE_RETENTIONS:
                raise InvalidProviderRequest(
                    f"prompt_cache_retention must be one of {PROMPT_CACHE_RETENTIONS}"
                )
            body["prompt_cache_retention"] = request.prompt_cache_retention
        if request.safety_identifier is not None:
            body["safety_identifier"] = request.safety_identifier
        if request.service_tier is not None:
            body["service_tier"] = request.service_tier
        if request.metadata is not None:
            body["metadata"] = dict(request.metadata)

        # Belt and braces: the allowlist is the contract, so assert it holds
        # rather than trusting that the block above stayed disciplined.
        leaked = set(body) - CHAT_BODY_ALLOWLIST
        if leaked:  # pragma: no cover - a programming error, not an input error
            raise InvalidProviderRequest(
                f"refusing to send non-allowlisted parameters: {sorted(leaked)}"
            )
        return body

    # -- limits, per team -------------------------------------------------- #
    def limits_for(self, model: MetaModel) -> UsageLimits:
        caps = model.capabilities
        return UsageLimits(
            requests_per_minute=(
                self._rpm_override
                if self._rpm_override is not None
                else caps.requests_per_minute
            ),
            tokens_per_minute=(
                self._tpm_override if self._tpm_override is not None else caps.tokens_per_minute
            ),
            max_concurrent=self._max_concurrent,
        )

    # -- the call ---------------------------------------------------------- #
    async def complete(
        self, request: AIRequest, *, user_id: uuid.UUID | None = None
    ) -> AIResponse:
        """Reserve, call, reconcile, record — in that order.

        The reservation is taken *before* the call so two processes cannot both
        start a call the team's budget only has room for one of, and it is
        reconciled from the response because the pre-call token estimate is an
        estimate.
        """
        if self._recorder is None:
            raise RuntimeError(
                "MetaProvider.complete requires an AIRunRecorder: an unaccounted "
                "model call is a cost nobody can attribute"
            )

        model = self.resolve_model(request.required_capabilities(), model=request.model)
        if model.endpoint != "chat.completions":
            raise UnsupportedCapability(
                ("text_out",), f"{model.id} does not serve chat completions"
            )
        body = self._build_body(request, model=model)

        estimated_tokens = request.estimated_prompt_tokens() + body["max_completion_tokens"]
        reservation = await self._usage.reserve(
            team_id=self.team_id,
            model=model.id,
            tokens=estimated_tokens,
            micro_minor=token_cost_micro_minor(
                model.capabilities,
                input_tokens=request.estimated_prompt_tokens(),
                output_tokens=body["max_completion_tokens"],
            ),
            limits=self.limits_for(model),
        )

        run = await self._recorder.start(
            user_id=user_id,
            provider=self.name,
            model=model.id,
            prompt_version=request.prompt_version,
            purpose=request.purpose,
            team_id=self.team_id,
            reservation_id=reservation.id,
            currency=model.capabilities.currency,
        )

        try:
            raw = await self.client().chat.completions.create(**body)
        except Exception as exc:
            await self._usage.release(reservation)
            await self._recorder.fail(run, code=type(exc).__name__, message=str(exc))
            raise

        usage, text, tool_calls, finish_reason, response_id = _parse_chat_response(raw)
        cost = token_cost_micro_minor(
            model.capabilities,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        await self._usage.reconcile(
            reservation, tokens=usage.total_tokens, micro_minor=cost
        )
        await self._recorder.finish(
            run,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cost_micro_minor=cost,
            finish_reason=finish_reason,
            response_id=response_id,
        )
        return AIResponse(
            provider=self.name,
            model=model.id,
            usage=usage,
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            response_id=response_id,
            cost_micro_minor=cost,
        )

    # -- image generation -------------------------------------------------- #
    async def generate_image(
        self, request: AIRequest, *, user_id: uuid.UUID | None = None, count: int = 1
    ) -> AIResponse:
        """Generate at ``POST /v1/images/generations``.

        Separate from :meth:`complete` because it is a different endpoint with a
        different price unit ($0.01 per image, not per token) and a different
        rate limit (150 RPM).
        """
        if self._recorder is None:
            raise RuntimeError("MetaProvider.generate_image requires an AIRunRecorder")

        model = self.resolve_model(
            Capabilities(text_in=True, image_out=True), model=request.model
        )
        if not model.capabilities.image_out:
            raise UnsupportedCapability(("image_out",), f"{model.id} does not emit images")

        reservation = await self._usage.reserve(
            team_id=self.team_id,
            model=model.id,
            tokens=0,
            micro_minor=image_cost_micro_minor(model.capabilities, images=count),
            limits=self.limits_for(model),
        )
        run = await self._recorder.start(
            user_id=user_id,
            provider=self.name,
            model=model.id,
            prompt_version=request.prompt_version,
            purpose=request.purpose or "image.generate",
            team_id=self.team_id,
            reservation_id=reservation.id,
            currency=model.capabilities.currency,
        )
        try:
            await self.client().images.generate(
                model=model.id, prompt=request.prompt or "", n=count
            )
        except Exception as exc:
            await self._usage.release(reservation)
            await self._recorder.fail(run, code=type(exc).__name__, message=str(exc))
            raise

        cost = image_cost_micro_minor(model.capabilities, images=count)
        await self._usage.reconcile(reservation, tokens=0, micro_minor=cost)
        await self._recorder.finish(run, images=count, cost_micro_minor=cost)
        return AIResponse(
            provider=self.name,
            model=model.id,
            usage=TokenUsage(),
            images=count,
            cost_micro_minor=cost,
        )

    # -- transcription: pre-flight only in Phase A ------------------------- #
    def check_transcription(
        self, *, content_type: str, duration_seconds: float, byte_size: int
    ) -> None:
        """Refuse locally what the vendor would refuse with a 400 or 413.

        Verified: audio over ten minutes or in any format but WAV returns 400,
        and a body over 32 MB returns 413. Each of those is an upload we would
        have paid to send.
        """
        model = META_MODELS["muse-voice-transcribe-1.0"]
        caps = model.capabilities
        if content_type.split(";")[0].strip().lower() not in caps.accepted_audio_formats:
            raise InvalidProviderRequest(
                f"{model.id} accepts only WAV audio, got {content_type!r}"
            )
        if duration_seconds > (caps.max_audio_seconds or TRANSCRIBE_MAX_AUDIO_SECONDS):
            raise InvalidProviderRequest(
                f"{model.id} accepts at most {caps.max_audio_seconds} seconds of audio"
            )
        if byte_size > (caps.max_request_bytes or TRANSCRIBE_MAX_REQUEST_BYTES):
            raise InvalidProviderRequest(
                f"{model.id} accepts at most {caps.max_request_bytes} bytes per request"
            )

    def transcription_url(self) -> str:
        return f"{self._base_url.rstrip('/')}{TRANSCRIBE_PATH}"

    # -- segmentation: declared, labelled, not implemented ----------------- #
    def segment(self, *, image_ref: str, prompt: str) -> None:
        """``sam-3.1`` segmentation — **planned**, not implemented.

        The model and its price are declared in :data:`META_MODELS` so the
        router and the cost model know about them, but Phase A has no caller and
        no mask storage. It refuses rather than returning a fabricated mask: a
        fixture must never read as a live integration.
        """
        raise CapabilityUnavailable(
            "Garment segmentation (sam-3.1) is not implemented in this build.",
            code="segmentation_not_implemented",
            detail={"model": "sam-3.1", "status": "planned"},
        )


# --------------------------------------------------------------------------- #
# response parsing
# --------------------------------------------------------------------------- #
def _payload(raw: Any) -> Mapping[str, Any]:
    """Normalise an SDK response object or a plain mapping to a mapping."""
    if isinstance(raw, Mapping):
        return raw
    dump = getattr(raw, "model_dump", None)
    if callable(dump):
        return dump()
    return dict(raw)


def _parse_chat_response(
    raw: Any,
) -> tuple[TokenUsage, str | None, tuple[ToolCall, ...], str | None, str | None]:
    payload = _payload(raw)
    choices = payload.get("choices") or []
    first = choices[0] if choices else {}
    message = first.get("message") or {}

    calls = tuple(
        ToolCall(
            id=str(call.get("id") or ""),
            name=str((call.get("function") or {}).get("name") or ""),
            arguments=str((call.get("function") or {}).get("arguments") or ""),
        )
        for call in (message.get("tool_calls") or [])
    )

    raw_usage = payload.get("usage") or {}
    usage = TokenUsage(
        input_tokens=int(raw_usage.get("prompt_tokens") or 0),
        output_tokens=int(raw_usage.get("completion_tokens") or 0),
        cached_input_tokens=int(
            (raw_usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        ),
        reasoning_tokens=int(
            (raw_usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        ),
    )
    return (
        usage,
        message.get("content"),
        calls,
        first.get("finish_reason"),
        payload.get("id"),
    )


__all__ = [
    "API_KEY_PREFIX",
    "CHAT_BODY_ALLOWLIST",
    "CHAT_MODELS",
    "DEFAULT_MAX_COMPLETION_TOKENS",
    "DEFAULT_MODEL",
    "IMAGE_EDITS_PATH",
    "IMAGE_GENERATIONS_PATH",
    "META_BASE_URL",
    "META_MODELS",
    "META_PROVIDER_CAPABILITIES",
    "REASONING_EFFORTS",
    "REFUSED_PARAMETERS",
    "TRANSCRIBE_ACCEPTED_FORMATS",
    "TRANSCRIBE_MAX_AUDIO_SECONDS",
    "TRANSCRIBE_MAX_REQUEST_BYTES",
    "TRANSCRIBE_PATH",
    "MetaModel",
    "MetaProvider",
]
