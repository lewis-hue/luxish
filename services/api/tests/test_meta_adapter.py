"""Task 7 — the Meta Model API adapter (ADR-006, ADR-007).

Everything asserted here is a **verified vendor fact**, not a preference. The
ten refused parameters each return HTTP 400; ``max_tokens`` is deprecated in
favour of ``max_completion_tokens``; there is no embeddings model; rate limits
are per *team*, not per API key; and the maximum output token count is not
documented, so nothing may pretend to know it.

No test here touches the network. The ``no_network`` fixture replaces both
httpx transports, so a real outbound request fails the test that attempted it
rather than quietly succeeding on someone's laptop and failing in CI.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_run import AIRun
from app.models.user import User
from app.providers.base import (
    AIRequest,
    AIRunRecorder,
    Capabilities,
    InMemoryUsageStore,
    InvalidProviderRequest,
    JsonSchemaFormat,
    ProviderRateLimited,
    UnsupportedCapability,
    minor_units,
)
from app.providers.meta import (
    CHAT_BODY_ALLOWLIST,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_MODEL,
    IMAGE_EDITS_PATH,
    IMAGE_GENERATIONS_PATH,
    META_BASE_URL,
    META_MODELS,
    META_PROVIDER_CAPABILITIES,
    REASONING_EFFORTS,
    REFUSED_PARAMETERS,
    TRANSCRIBE_MAX_AUDIO_SECONDS,
    TRANSCRIBE_MAX_REQUEST_BYTES,
    TRANSCRIBE_PATH,
    MetaProvider,
)

BANNED = (
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
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any real outbound HTTP, in either direction."""

    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test attempted a real network request")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


# --------------------------------------------------------------------------- #
# a fake Meta client: the three calls the adapter makes, and nothing else
# --------------------------------------------------------------------------- #
def chat_payload(
    *,
    content: str = "a navy blazer and grey trousers",
    prompt_tokens: int = 1_200,
    completion_tokens: int = 300,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:8],
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, "tool_calls": []},
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


class FakeCompletions:
    def __init__(self, outer: FakeMetaClient) -> None:
        self._outer = outer

    async def create(self, **body: Any) -> Any:
        self._outer.chat_bodies.append(body)
        if self._outer.raise_on_chat is not None:
            raise self._outer.raise_on_chat
        return self._outer.chat_response


class FakeImages:
    def __init__(self, outer: FakeMetaClient) -> None:
        self._outer = outer

    async def generate(self, **body: Any) -> Any:
        self._outer.image_bodies.append(body)
        return {"data": [{"b64_json": "ZmFrZQ=="}], "model": body.get("model")}


class FakeMetaClient:
    """Stands in for ``openai.AsyncOpenAI`` — same three call sites."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.chat_bodies: list[dict[str, Any]] = []
        self.image_bodies: list[dict[str, Any]] = []
        self.chat_response: dict[str, Any] = response or chat_payload()
        self.raise_on_chat: Exception | None = None
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions(self)  # type: ignore[attr-defined]
        self.images = FakeImages(self)


async def make_user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def provider(**kwargs: Any) -> MetaProvider:
    kwargs.setdefault("client", FakeMetaClient())
    kwargs.setdefault("usage", InMemoryUsageStore())
    return MetaProvider(**kwargs)


# --------------------------------------------------------------------------- #
# the plan's named test
# --------------------------------------------------------------------------- #
def test_meta_adapter_strips_parameters_that_return_400() -> None:
    body = MetaProvider()._build_body(AIRequest(prompt="x", stop=["\n"], n=3))
    for banned in BANNED:
        assert banned not in body
    assert "max_completion_tokens" in body


# --------------------------------------------------------------------------- #
# the allowlist is an allowlist, not a filtered dict
# --------------------------------------------------------------------------- #
def test_every_refused_parameter_is_named_in_one_constant() -> None:
    assert set(BANNED) == set(REFUSED_PARAMETERS)


def test_no_refused_parameter_is_in_the_allowlist() -> None:
    assert REFUSED_PARAMETERS.isdisjoint(CHAT_BODY_ALLOWLIST)


def test_the_body_contains_only_allowlisted_keys() -> None:
    request = AIRequest(
        prompt="style me",
        temperature=0.4,
        top_p=0.9,
        frequency_penalty=0.1,
        presence_penalty=0.2,
        seed=7,
        reasoning_effort="low",
        max_completion_tokens=512,
        prompt_cache_key="stylist_v1",
        prompt_cache_retention="24h",
        safety_identifier="user-42",
        service_tier="default",
        metadata={"run": "abc"},
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=({"type": "function", "function": {"name": "wardrobe_search"}},),
        stream=True,
        stream_options={"include_usage": True},
        # every refused parameter, supplied at once
        stop=["\n"],
        n=4,
        verbosity="high",
        logit_bias={"1": 1},
        prediction={"type": "content"},
        web_search_options={"x": 1},
        modalities=["text"],
        audio={"voice": "x"},
        logprobs=True,
        top_logprobs=3,
        max_tokens=99,
    )
    body = MetaProvider()._build_body(request)

    assert set(body) <= CHAT_BODY_ALLOWLIST
    assert body["max_completion_tokens"] == 512
    assert body["temperature"] == 0.4
    assert body["reasoning_effort"] == "low"
    assert body["prompt_cache_retention"] == "24h"
    assert body["safety_identifier"] == "user-42"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["parallel_tool_calls"] is False


def test_an_attribute_bolted_onto_the_request_cannot_reach_the_body() -> None:
    """The adapter reads named fields; it does not iterate the request."""
    request = AIRequest(prompt="x")
    body = MetaProvider()._build_body(request)
    assert "logit_bias" not in body
    assert set(body) <= CHAT_BODY_ALLOWLIST


def test_store_defaults_to_false_and_is_always_explicit() -> None:
    body = MetaProvider()._build_body(AIRequest(prompt="x"))
    assert body["store"] is False


def test_max_completion_tokens_falls_back_to_our_budget_not_a_model_ceiling() -> None:
    body = MetaProvider()._build_body(AIRequest(prompt="x"))
    assert body["max_completion_tokens"] == DEFAULT_MAX_COMPLETION_TOKENS


def test_the_model_output_ceiling_is_not_hardcoded() -> None:
    """Max output tokens is undocumented. ``None`` says that; a number lies."""
    for model in META_MODELS.values():
        assert model.capabilities.max_output_tokens is None
    assert META_PROVIDER_CAPABILITIES.max_output_tokens is None


# --------------------------------------------------------------------------- #
# verified endpoint, auth and limits
# --------------------------------------------------------------------------- #
def test_the_base_url_is_the_verified_one() -> None:
    assert META_BASE_URL == "https://api.meta.ai/v1"


def test_the_auth_header_is_a_static_bearer_key() -> None:
    p = MetaProvider(api_key="LLM_abc")
    assert p.auth_headers() == {"Authorization": "Bearer LLM_abc"}


def test_the_image_and_transcription_paths_are_the_verified_ones() -> None:
    assert IMAGE_GENERATIONS_PATH == "/images/generations"
    assert IMAGE_EDITS_PATH == "/images/edits"
    assert TRANSCRIBE_PATH == "/asr/transcribe"


def test_the_published_rate_limits_are_recorded_per_model() -> None:
    assert META_MODELS["muse-spark-1.3"].capabilities.requests_per_minute == 3000
    assert META_MODELS["muse-spark-1.3"].capabilities.tokens_per_minute == 4_000_000
    assert META_MODELS["muse-wonder-1.0"].capabilities.requests_per_minute == 3000
    assert META_MODELS["muse-wonder-1.0"].capabilities.tokens_per_minute == 4_000_000
    assert META_MODELS["muse-image-1.0"].capabilities.requests_per_minute == 150


def test_the_context_window_is_the_published_one() -> None:
    assert META_MODELS["muse-spark-1.3"].capabilities.max_context_tokens == 1_048_576
    assert META_MODELS["muse-wonder-1.0"].capabilities.max_context_tokens == 1_048_576


def test_reasoning_effort_accepts_exactly_the_documented_values() -> None:
    assert REASONING_EFFORTS == ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def test_an_undocumented_reasoning_effort_is_refused_locally() -> None:
    with pytest.raises(InvalidProviderRequest):
        AIRequest(prompt="x", reasoning_effort="extreme")


def test_an_undocumented_cache_retention_is_refused_locally() -> None:
    with pytest.raises(InvalidProviderRequest):
        AIRequest(prompt="x", prompt_cache_retention="forever")


def test_a_safety_identifier_over_64_characters_is_refused() -> None:
    with pytest.raises(InvalidProviderRequest):
        AIRequest(prompt="x", safety_identifier="u" * 65)
    AIRequest(prompt="x", safety_identifier="u" * 64)  # the boundary is allowed


# --------------------------------------------------------------------------- #
# there is no embeddings model, and no code may call one
# --------------------------------------------------------------------------- #
def test_meta_declares_no_embeddings() -> None:
    assert META_PROVIDER_CAPABILITIES.embeddings is False
    for model in META_MODELS.values():
        assert model.capabilities.embeddings is False


def test_no_provider_code_references_an_embeddings_endpoint() -> None:
    """ADR-004: the Meta Model API publishes no embeddings endpoint. The cheapest
    way to keep a call site from appearing is to assert none exists."""
    import pathlib
    import re

    providers = pathlib.Path(__file__).resolve().parents[1] / "app" / "providers"
    offending: list[str] = []
    for path in providers.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(/embeddings|\.embeddings\.|embeddings\.create)", line):
                offending.append(f"{path.name}:{number}")
    assert offending == []


def test_an_embeddings_request_is_refused_before_any_network_call() -> None:
    p = provider()
    with pytest.raises(UnsupportedCapability):
        p.resolve_model(Capabilities(embeddings=True))


# --------------------------------------------------------------------------- #
# structured output
# --------------------------------------------------------------------------- #
OUTFIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"garment_ids": {"type": "array", "items": {"type": "string"}}},
    "required": ["garment_ids"],
}


def test_strict_structured_output_requires_a_root_object() -> None:
    with pytest.raises(InvalidProviderRequest):
        JsonSchemaFormat(name="outfit", json_schema={"type": "array"}, strict=True)


def test_strict_structured_output_requires_additional_properties_false() -> None:
    with pytest.raises(InvalidProviderRequest):
        JsonSchemaFormat(
            name="outfit",
            json_schema={"type": "object", "properties": {}},
            strict=True,
        )


def test_a_valid_strict_schema_renders_the_documented_body_shape() -> None:
    fmt = JsonSchemaFormat(name="outfit", json_schema=OUTFIT_SCHEMA, strict=True)
    body = MetaProvider()._build_body(AIRequest(prompt="x", response_format=fmt))
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "outfit", "schema": OUTFIT_SCHEMA, "strict": True},
    }


def test_a_non_strict_schema_is_not_held_to_the_strict_rules() -> None:
    fmt = JsonSchemaFormat(name="loose", json_schema={"type": "array"}, strict=False)
    assert fmt.strict is False


# --------------------------------------------------------------------------- #
# capability refusal happens before the network
# --------------------------------------------------------------------------- #
async def test_an_unsupported_modality_fails_before_any_network_call(
    db: AsyncSession,
) -> None:
    user = await make_user(db)
    client = FakeMetaClient()
    p = provider(client=client, recorder=AIRunRecorder(db))

    with pytest.raises(UnsupportedCapability):
        await p.complete(
            AIRequest(
                prompt="transcribe this",
                needs=Capabilities(audio_in=True, text_out=True),
                model="muse-image-1.0",
            ),
            user_id=user.id,
        )

    assert client.chat_bodies == []


async def test_a_text_request_cannot_be_routed_to_the_image_model(
    db: AsyncSession,
) -> None:
    user = await make_user(db)
    client = FakeMetaClient()
    p = provider(client=client, recorder=AIRunRecorder(db))
    with pytest.raises(UnsupportedCapability):
        await p.complete(
            AIRequest(prompt="x", model="muse-image-1.0", needs=Capabilities(text_out=True)),
            user_id=user.id,
        )
    assert client.chat_bodies == []


def test_an_unknown_model_id_is_refused() -> None:
    with pytest.raises(InvalidProviderRequest):
        MetaProvider()._build_body(AIRequest(prompt="x", model="muse-does-not-exist"))


# --------------------------------------------------------------------------- #
# price, in integer minor units
# --------------------------------------------------------------------------- #
def test_the_published_prices_are_recorded_as_integer_minor_units() -> None:
    spark = META_MODELS["muse-spark-1.3"].capabilities
    wonder = META_MODELS["muse-wonder-1.0"].capabilities
    image = META_MODELS["muse-image-1.0"].capabilities
    sam = META_MODELS["sam-3.1"].capabilities

    # $1.25 / 1M in, $4.25 / 1M out
    assert spark.input_price_minor_per_million_tokens == 125
    assert spark.output_price_minor_per_million_tokens == 425
    # $4.00 / 1M in, $20.00 / 1M out
    assert wonder.input_price_minor_per_million_tokens == 400
    assert wonder.output_price_minor_per_million_tokens == 2000
    # $0.01 per image
    assert image.price_micro_minor_per_image == 1_000_000
    # $2.50 / 1000 images
    assert sam.price_micro_minor_per_image == 250_000
    for caps in (spark, wonder, image, sam):
        assert caps.currency == "USD"


def test_cost_is_exact_integer_arithmetic_with_no_float_anywhere() -> None:
    spark = META_MODELS["muse-spark-1.3"].capabilities
    from app.providers.base import token_cost_micro_minor

    micro = token_cost_micro_minor(spark, input_tokens=1_000_000, output_tokens=1_000_000)
    assert micro == (125 + 425) * 1_000_000
    assert isinstance(micro, int)
    assert minor_units(micro) == 550

    # A tiny call rounds up rather than down: never under-charge the ledger.
    assert minor_units(token_cost_micro_minor(spark, input_tokens=1, output_tokens=0)) == 1


# --------------------------------------------------------------------------- #
# usage reservation and reconciliation
# --------------------------------------------------------------------------- #
async def test_usage_is_reserved_before_the_call_and_reconciled_after(
    db: AsyncSession,
) -> None:
    user = await make_user(db)
    usage = InMemoryUsageStore()
    client = FakeMetaClient(chat_payload(prompt_tokens=1_000, completion_tokens=200))
    p = provider(client=client, usage=usage, recorder=AIRunRecorder(db), team_id="team-1")

    response = await p.complete(AIRequest(prompt="style me"), user_id=user.id)

    assert usage.events[0][0] == "reserve"
    assert usage.events[-1][0] == "reconcile"
    assert response.usage.input_tokens == 1_000
    assert response.usage.output_tokens == 200
    snapshot = await usage.snapshot("team-1")
    assert snapshot["tokens"] == 1_200
    assert snapshot["in_flight"] == 0


async def test_a_failing_call_releases_the_reservation(db: AsyncSession) -> None:
    user = await make_user(db)
    usage = InMemoryUsageStore()
    client = FakeMetaClient()
    client.raise_on_chat = RuntimeError("upstream exploded")
    p = provider(client=client, usage=usage, recorder=AIRunRecorder(db), team_id="team-2")

    with pytest.raises(RuntimeError):
        await p.complete(AIRequest(prompt="style me"), user_id=user.id)

    snapshot = await usage.snapshot("team-2")
    assert snapshot["in_flight"] == 0
    assert snapshot["tokens"] == 0
    assert usage.events[-1][0] == "release"


async def test_the_reservation_is_keyed_on_the_team_not_the_api_key(
    db: AsyncSession,
) -> None:
    """Verified: Meta's rate limits are per team, so two keys on one team share
    one budget. A key-wide limiter would let the team sail past 3000 RPM."""
    user = await make_user(db)
    usage = InMemoryUsageStore()
    recorder = AIRunRecorder(db)
    first = provider(
        client=FakeMetaClient(), usage=usage, recorder=recorder, team_id="t", api_key="LLM_one"
    )
    second = provider(
        client=FakeMetaClient(), usage=usage, recorder=recorder, team_id="t", api_key="LLM_two"
    )

    await first.complete(AIRequest(prompt="a"), user_id=user.id)
    await second.complete(AIRequest(prompt="b"), user_id=user.id)

    assert (await usage.snapshot("t"))["requests"] == 2
    assert all("LLM_" not in key for key in usage.tracked_keys())


async def test_the_team_limiter_refuses_once_the_published_rpm_is_reached(
    db: AsyncSession,
) -> None:
    user = await make_user(db)
    usage = InMemoryUsageStore()
    p = provider(
        client=FakeMetaClient(),
        usage=usage,
        recorder=AIRunRecorder(db),
        team_id="t3",
        max_requests_per_minute=2,
    )

    await p.complete(AIRequest(prompt="a"), user_id=user.id)
    await p.complete(AIRequest(prompt="b"), user_id=user.id)
    with pytest.raises(ProviderRateLimited):
        await p.complete(AIRequest(prompt="c"), user_id=user.id)


async def test_the_redis_reservation_is_a_single_atomic_call() -> None:
    """Reserve-then-check in two round trips is a race. One EVAL is not."""
    from app.providers.base import RedisUsageStore, UsageLimits

    class RecordingRedis:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        async def eval(self, script: str, numkeys: int, *args: Any) -> list[Any]:
            self.calls.append((script, numkeys, *args))
            return [1, b"ok"]

    redis = RecordingRedis()
    store = RedisUsageStore(redis)
    await store.reserve(
        team_id="team-1",
        model=DEFAULT_MODEL,
        tokens=100,
        micro_minor=1_000,
        limits=UsageLimits(requests_per_minute=3000, tokens_per_minute=4_000_000),
    )
    assert len(redis.calls) == 1
    keys = [a for a in redis.calls[0][2:5]]
    assert all("team-1" in str(k) for k in keys)


# --------------------------------------------------------------------------- #
# every call is accounted for
# --------------------------------------------------------------------------- #
async def test_every_model_call_records_an_ai_run(db: AsyncSession) -> None:
    import sqlalchemy as sa

    user = await make_user(db)
    client = FakeMetaClient(chat_payload(prompt_tokens=2_000, completion_tokens=500))
    p = provider(client=client, recorder=AIRunRecorder(db))

    await p.complete(
        AIRequest(prompt="style me", prompt_version="stylist_v1", purpose="stylist.run"),
        user_id=user.id,
    )

    run = (await db.scalars(sa.select(AIRun))).one()
    assert run.provider == "meta"
    assert run.model == DEFAULT_MODEL
    assert run.prompt_version == "stylist_v1"
    assert run.input_tokens == 2_000
    assert run.output_tokens == 500
    assert run.outcome == "succeeded"
    assert run.cost_micro_minor == 2_000 * 125 + 500 * 425
    assert run.cost_minor == minor_units(run.cost_micro_minor)
    assert isinstance(run.cost_minor, int)
    assert run.currency == "USD"


async def test_a_failed_call_still_records_a_run_with_the_failure(
    db: AsyncSession,
) -> None:
    import sqlalchemy as sa

    user = await make_user(db)
    client = FakeMetaClient()
    client.raise_on_chat = RuntimeError("upstream exploded")
    p = provider(client=client, recorder=AIRunRecorder(db))

    with pytest.raises(RuntimeError):
        await p.complete(AIRequest(prompt="x", prompt_version="stylist_v1"), user_id=user.id)

    run = (await db.scalars(sa.select(AIRun))).one()
    assert run.outcome == "failed"
    assert run.error_code is not None


async def test_complete_refuses_without_a_run_recorder(db: AsyncSession) -> None:
    """Unaccounted model spend is not a thing this service does."""
    user = await make_user(db)
    p = provider()
    with pytest.raises(RuntimeError, match="AIRun"):
        await p.complete(AIRequest(prompt="x"), user_id=user.id)


# --------------------------------------------------------------------------- #
# the other endpoints: pre-flight refusals that save a paid round trip
# --------------------------------------------------------------------------- #
def test_transcription_refuses_audio_longer_than_ten_minutes() -> None:
    """Verified: >10 minutes returns 400. Refusing locally costs nothing."""
    assert TRANSCRIBE_MAX_AUDIO_SECONDS == 600
    with pytest.raises(InvalidProviderRequest):
        MetaProvider().check_transcription(
            content_type="audio/wav", duration_seconds=601, byte_size=1_000
        )


def test_transcription_refuses_anything_that_is_not_wav() -> None:
    with pytest.raises(InvalidProviderRequest):
        MetaProvider().check_transcription(
            content_type="audio/mpeg", duration_seconds=10, byte_size=1_000
        )


def test_transcription_refuses_a_body_over_thirty_two_megabytes() -> None:
    assert TRANSCRIBE_MAX_REQUEST_BYTES == 32 * 1024 * 1024
    with pytest.raises(InvalidProviderRequest):
        MetaProvider().check_transcription(
            content_type="audio/wav",
            duration_seconds=10,
            byte_size=TRANSCRIBE_MAX_REQUEST_BYTES + 1,
        )


def test_a_well_formed_transcription_request_passes_pre_flight() -> None:
    MetaProvider().check_transcription(
        content_type="audio/wav", duration_seconds=600, byte_size=1_024
    )


def test_segmentation_is_declared_but_labelled_not_implemented() -> None:
    """``sam-3.1`` is the chosen segmenter (ADR-005). Phase A declares it and
    refuses rather than faking a mask."""
    from app.errors import CapabilityUnavailable

    sam = META_MODELS["sam-3.1"].capabilities
    assert sam.image_in is True
    assert sam.video_in is True
    assert sam.text_in is True
    with pytest.raises(CapabilityUnavailable):
        MetaProvider().segment(image_ref="gs://x", prompt="the blazer")


async def test_image_generation_uses_the_images_endpoint(db: AsyncSession) -> None:
    user = await make_user(db)
    client = FakeMetaClient()
    p = provider(client=client, recorder=AIRunRecorder(db))

    await p.generate_image(
        AIRequest(prompt="a studio shot of a navy blazer", model="muse-image-1.0"),
        user_id=user.id,
    )

    assert client.image_bodies[0]["model"] == "muse-image-1.0"
    assert client.chat_bodies == []


# --------------------------------------------------------------------------- #
# the guard on the guard
# --------------------------------------------------------------------------- #
async def test_a_real_http_request_fails_this_suite() -> None:
    async with httpx.AsyncClient() as c:
        with pytest.raises(AssertionError):
            await c.get("https://api.meta.ai/v1/models")
