"""Task 7 — declared capabilities and the routing decision (ADR-006).

The router never guesses. Every adapter publishes a ``ProviderCapabilities``
record and the registry selects on four independent questions:

1. does the provider declare the capability the request needs,
2. has the user consented to AI processing,
3. is there an active entitlement,
4. does the provider accept the user's billing source?

A request for an unsupported modality fails **before any network call** — which
is why ``select`` is a pure function and this module needs no transport at all.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_run import AI_RUN_OUTCOMES, AIRun
from app.models.consent import Consent
from app.models.provider_connection import ProviderConnection
from app.models.usage import UsageReservation
from app.models.user import User
from app.providers import (
    AIProvider,
    AIRequest,
    Capabilities,
    NoEligibleProvider,
    ProviderCapabilities,
)
from app.providers.base import (
    AIRunRecorder,
    InMemoryUsageStore,
    ProviderRateLimited,
    UsageLimits,
    minor_units,
    token_cost_micro_minor,
    union_capabilities,
)
from app.providers.chatgpt_plan import (
    CHATGPT_PLAN_CAPABILITIES,
    ChatGPTConnection,
    ChatGPTPlanProvider,
)
from app.providers.meta import META_PROVIDER_CAPABILITIES, MetaProvider
from app.providers.registry import (
    ProviderRegistry,
    RoutingSubject,
    default_registry,
    load_routing_subject,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test attempted a real network request")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


def user_with(**overrides: Any) -> RoutingSubject:
    """A routing subject: the four inputs ``select`` is allowed to look at."""
    base: dict[str, Any] = {
        "user_id": uuid.uuid4(),
        "team_id": "team-1",
        "ai_processing_consent": True,
        "entitlement_active": True,
        "billing_source": "subscription_allowance",
        "chatgpt_inference": "unavailable",
    }
    base.update(overrides)
    return RoutingSubject(**base)


def registry_of(*, chatgpt_state: str = "unavailable") -> ProviderRegistry:
    return default_registry(
        meta=MetaProvider(client=object(), usage=InMemoryUsageStore()),
        chatgpt_plan=ChatGPTPlanProvider(connection=ChatGPTConnection(state=chatgpt_state)),
    )


async def make_user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# --------------------------------------------------------------------------- #
# the plan's named test
# --------------------------------------------------------------------------- #
def test_image_generation_never_routes_to_chatgpt_plan() -> None:
    registry = registry_of(chatgpt_state="inference_authorized")
    user = user_with(chatgpt_inference="inference_authorized")
    p = registry.select(Capabilities(image_out=True), user)
    assert p.name == "meta"  # plan route does not support image generation


def test_image_generation_is_refused_when_meta_is_not_registered() -> None:
    """Without a provider that declares ``image_out`` the answer is a refusal,
    never a silent downgrade to a text model."""
    registry = ProviderRegistry()
    registry.register(
        ChatGPTPlanProvider(connection=ChatGPTConnection(state="inference_authorized")),
        priority=10,
        billing_sources=("chatgpt_plan",),
    )
    with pytest.raises(NoEligibleProvider) as exc:
        registry.select(Capabilities(image_out=True), user_with(billing_source="chatgpt_plan"))
    assert exc.value.reasons["chatgpt_plan"] == "capability"


# --------------------------------------------------------------------------- #
# the capability record
# --------------------------------------------------------------------------- #
def test_the_capability_record_declares_every_field_adr_006_requires() -> None:
    fields = {f.name for f in dataclasses.fields(ProviderCapabilities)}
    assert {
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
    } <= fields
    # "plus limits and unit price"
    assert {
        "max_context_tokens",
        "max_output_tokens",
        "requests_per_minute",
        "tokens_per_minute",
        "input_price_minor_per_million_tokens",
        "output_price_minor_per_million_tokens",
        "currency",
    } <= fields


def test_capability_defaults_are_all_false_so_silence_is_never_a_yes() -> None:
    caps = ProviderCapabilities()
    for field in dataclasses.fields(caps):
        if field.type == "bool" or isinstance(getattr(caps, field.name), bool):
            assert getattr(caps, field.name) is False, field.name


def test_no_registered_provider_declares_embeddings() -> None:
    """ADR-004: there is no embeddings provider in this build, by design."""
    assert META_PROVIDER_CAPABILITIES.embeddings is False
    assert CHATGPT_PLAN_CAPABILITIES.embeddings is False


def test_a_need_reports_exactly_what_is_missing() -> None:
    need = Capabilities(text_out=True, image_out=True, audio_in=True)
    # Reported in declaration order, so the message is stable across runs.
    assert need.missing(CHATGPT_PLAN_CAPABILITIES) == ("audio_in", "image_out")
    assert need.satisfied_by(CHATGPT_PLAN_CAPABILITIES) is False
    assert Capabilities(text_out=True).satisfied_by(CHATGPT_PLAN_CAPABILITIES) is True


def test_unioning_capabilities_keeps_prices_out_of_the_provider_level_record() -> None:
    a = ProviderCapabilities(text_in=True, max_context_tokens=100)
    b = ProviderCapabilities(image_out=True, max_context_tokens=400)
    merged = union_capabilities(a, b)
    assert merged.text_in is True
    assert merged.image_out is True
    assert merged.max_context_tokens == 400
    # Price is a property of one model, so the union carries none.
    assert merged.input_price_minor_per_million_tokens is None
    assert merged.price_micro_minor_per_image is None


def test_both_adapters_satisfy_the_provider_protocol() -> None:
    meta = MetaProvider(client=object(), usage=InMemoryUsageStore())
    plan = ChatGPTPlanProvider(connection=ChatGPTConnection())
    for p in (meta, plan):
        assert isinstance(p, AIProvider)
        assert isinstance(p.name, str)
        assert isinstance(p.capabilities, ProviderCapabilities)


# --------------------------------------------------------------------------- #
# the four selection questions
# --------------------------------------------------------------------------- #
def test_a_text_request_selects_meta_by_default() -> None:
    assert registry_of().select(Capabilities(text_out=True), user_with()).name == "meta"


def test_the_plan_route_is_chosen_only_when_authorised_and_billed_to_the_plan() -> None:
    registry = registry_of(chatgpt_state="inference_authorized")
    subject = user_with(
        chatgpt_inference="inference_authorized", billing_source="chatgpt_plan"
    )
    assert registry.select(Capabilities(text_out=True), subject).name == "chatgpt_plan"


@pytest.mark.parametrize(
    "state",
    [
        "unavailable",
        "approval_pending",
        "disconnected",
        "identity_connected",
        "allowance_exhausted",
        "revoked",
        "error",
    ],
)
def test_the_plan_route_is_ineligible_in_every_state_but_authorised(state: str) -> None:
    registry = registry_of(chatgpt_state=state)
    subject = user_with(chatgpt_inference=state, billing_source="chatgpt_plan")
    with pytest.raises(NoEligibleProvider) as exc:
        registry.select(Capabilities(text_out=True), subject)
    assert exc.value.reasons["chatgpt_plan"] == "provider_state"


def test_without_ai_processing_consent_nothing_is_eligible() -> None:
    with pytest.raises(NoEligibleProvider) as exc:
        registry_of().select(
            Capabilities(text_out=True), user_with(ai_processing_consent=False)
        )
    assert exc.value.reasons["meta"] == "consent"


def test_without_an_active_entitlement_nothing_is_eligible() -> None:
    with pytest.raises(NoEligibleProvider) as exc:
        registry_of().select(Capabilities(text_out=True), user_with(entitlement_active=False))
    assert exc.value.reasons["meta"] == "entitlement"


def test_a_billing_source_a_provider_does_not_accept_is_ineligible() -> None:
    with pytest.raises(NoEligibleProvider) as exc:
        registry_of().select(Capabilities(text_out=True), user_with(billing_source="chatgpt_plan"))
    assert exc.value.reasons["meta"] == "billing_source"


def test_an_unsupported_modality_is_refused_without_touching_the_network() -> None:
    """``select`` is pure: there is nothing in it that could make a request."""
    with pytest.raises(NoEligibleProvider) as exc:
        registry_of().select(Capabilities(embeddings=True), user_with())
    assert set(exc.value.reasons.values()) == {"capability"}
    assert exc.value.status_code == 503
    assert exc.value.to_payload()["code"] == "no_eligible_provider"


def test_the_refusal_explains_every_candidate_not_just_the_first() -> None:
    registry = registry_of(chatgpt_state="inference_authorized")
    with pytest.raises(NoEligibleProvider) as exc:
        registry.select(Capabilities(embeddings=True), user_with())
    assert set(exc.value.reasons) == {"meta", "chatgpt_plan"}


def test_explain_reports_the_same_reasons_without_raising() -> None:
    registry = registry_of()
    assert registry.explain(Capabilities(embeddings=True), user_with()) == {
        "meta": "capability",
        "chatgpt_plan": "capability",
    }


def test_an_empty_registry_refuses_rather_than_returning_none() -> None:
    with pytest.raises(NoEligibleProvider):
        ProviderRegistry().select(Capabilities(text_out=True), user_with())


def test_a_provider_can_be_fetched_by_name() -> None:
    registry = registry_of()
    assert registry.get("meta").name == "meta"
    assert registry.names() == ("meta", "chatgpt_plan")
    with pytest.raises(KeyError):
        registry.get("anthropic")


def test_registering_the_same_name_twice_is_refused() -> None:
    registry = registry_of()
    with pytest.raises(ValueError, match="meta"):
        registry.register(
            MetaProvider(client=object(), usage=InMemoryUsageStore()),
            priority=1,
            billing_sources=("subscription_allowance",),
        )


# --------------------------------------------------------------------------- #
# the routing subject, read from the database
# --------------------------------------------------------------------------- #
async def test_the_routing_subject_reads_consent_and_connection_state(
    db: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    user = await make_user(db)
    db.add(Consent(user_id=user.id, kind="ai_processing", granted_at=datetime.now(UTC)))
    db.add(
        ProviderConnection(
            user_id=user.id,
            provider="chatgpt_plan",
            kind="inference",
            state="inference_authorized",
            scopes=["offline_access", "resource.invoke", "chatgpt.tokens.use.direct"],
        )
    )
    await db.commit()

    subject = await load_routing_subject(db, user.id, team_id="team-9")

    assert subject.ai_processing_consent is True
    assert subject.chatgpt_inference == "inference_authorized"
    assert subject.team_id == "team-9"


async def test_a_user_who_never_consented_has_no_consent(db: AsyncSession) -> None:
    user = await make_user(db)
    subject = await load_routing_subject(db, user.id)
    assert subject.ai_processing_consent is False
    assert subject.chatgpt_inference == "unavailable"


async def test_a_revoked_consent_is_not_a_grant(db: AsyncSession) -> None:
    from datetime import UTC, datetime

    user = await make_user(db)
    now = datetime.now(UTC)
    db.add(Consent(user_id=user.id, kind="ai_processing", granted_at=now, revoked_at=now))
    await db.commit()
    assert (await load_routing_subject(db, user.id)).ai_processing_consent is False


# --------------------------------------------------------------------------- #
# the usage reservation
# --------------------------------------------------------------------------- #
async def test_a_reservation_is_taken_then_reconciled_to_the_real_number() -> None:
    store = InMemoryUsageStore()
    limits = UsageLimits(requests_per_minute=10, tokens_per_minute=10_000, max_concurrent=4)

    reservation = await store.reserve(
        team_id="t", model="muse-spark-1.3", tokens=5_000, micro_minor=600_000, limits=limits
    )
    assert (await store.snapshot("t"))["tokens"] == 5_000
    assert (await store.snapshot("t"))["in_flight"] == 1

    await store.reconcile(reservation, tokens=1_200, micro_minor=150_000)
    snapshot = await store.snapshot("t")
    assert snapshot["tokens"] == 1_200
    assert snapshot["in_flight"] == 0
    assert snapshot["micro_minor"] == 150_000


async def test_reconciling_twice_does_not_double_count() -> None:
    store = InMemoryUsageStore()
    limits = UsageLimits(requests_per_minute=10, tokens_per_minute=10_000)
    r = await store.reserve(
        team_id="t", model="m", tokens=100, micro_minor=1_000, limits=limits
    )
    await store.reconcile(r, tokens=10, micro_minor=100)
    await store.reconcile(r, tokens=10, micro_minor=100)
    assert (await store.snapshot("t"))["tokens"] == 10


async def test_the_token_budget_is_enforced_not_just_the_request_count() -> None:
    store = InMemoryUsageStore()
    limits = UsageLimits(requests_per_minute=100, tokens_per_minute=1_000)
    await store.reserve(team_id="t", model="m", tokens=900, micro_minor=0, limits=limits)
    with pytest.raises(ProviderRateLimited) as exc:
        await store.reserve(team_id="t", model="m", tokens=200, micro_minor=0, limits=limits)
    assert exc.value.detail["limit"] == "tokens_per_minute"
    # The refused reservation left nothing behind.
    assert (await store.snapshot("t"))["tokens"] == 900


async def test_the_concurrency_cap_is_enforced_per_team() -> None:
    store = InMemoryUsageStore()
    limits = UsageLimits(max_concurrent=1)
    first = await store.reserve(team_id="t", model="m", tokens=1, micro_minor=0, limits=limits)
    with pytest.raises(ProviderRateLimited):
        await store.reserve(team_id="t", model="m", tokens=1, micro_minor=0, limits=limits)
    # Another team is unaffected: the budget is team-wide, not global.
    await store.reserve(team_id="other", model="m", tokens=1, micro_minor=0, limits=limits)
    await store.release(first)
    await store.reserve(team_id="t", model="m", tokens=1, micro_minor=0, limits=limits)


async def test_a_released_reservation_leaves_no_usage_behind() -> None:
    store = InMemoryUsageStore()
    limits = UsageLimits(requests_per_minute=10, tokens_per_minute=10_000)
    r = await store.reserve(
        team_id="t", model="m", tokens=500, micro_minor=5_000, limits=limits
    )
    await store.release(r)
    snapshot = await store.snapshot("t")
    assert snapshot["tokens"] == 0
    assert snapshot["micro_minor"] == 0
    assert snapshot["in_flight"] == 0


async def test_no_live_redis_is_required_anywhere_in_this_suite() -> None:
    """The reservation store is an interface; Redis is one implementation."""
    from app.providers.base import UsageStore

    assert isinstance(InMemoryUsageStore(), UsageStore)


# --------------------------------------------------------------------------- #
# the durable records
# --------------------------------------------------------------------------- #
async def test_an_ai_run_records_everything_a_cost_review_needs(
    db: AsyncSession,
) -> None:
    user = await make_user(db)
    recorder = AIRunRecorder(db)
    run = await recorder.start(
        user_id=user.id,
        provider="meta",
        model="muse-spark-1.3",
        prompt_version="stylist_v1",
        purpose="stylist.run",
        team_id="team-1",
    )
    assert run.outcome == "pending"

    await recorder.finish(
        run,
        input_tokens=1_000,
        output_tokens=400,
        images=0,
        cost_micro_minor=token_cost_micro_minor(
            META_PROVIDER_CAPABILITIES, input_tokens=0, output_tokens=0
        ),
        finish_reason="stop",
    )

    stored = (await db.scalars(sa.select(AIRun))).one()
    assert stored.prompt_version == "stylist_v1"
    assert stored.provider == "meta"
    assert stored.model == "muse-spark-1.3"
    assert stored.input_tokens == 1_000
    assert stored.output_tokens == 400
    assert stored.outcome == "succeeded"
    assert stored.cost_minor == 0
    assert stored.latency_ms is not None


def test_the_run_outcomes_cover_refusal_as_well_as_failure() -> None:
    assert set(AI_RUN_OUTCOMES) >= {"pending", "succeeded", "failed", "refused"}


async def test_a_provider_connection_is_unique_per_user_provider_and_kind(
    db: AsyncSession,
) -> None:
    from sqlalchemy.exc import IntegrityError

    user = await make_user(db)
    db.add(
        ProviderConnection(
            user_id=user.id, provider="chatgpt_plan", kind="identity", state="disconnected"
        )
    )
    await db.commit()
    db.add(
        ProviderConnection(
            user_id=user.id, provider="chatgpt_plan", kind="identity", state="disconnected"
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_a_provider_connection_stores_no_bearer_material(
    db: AsyncSession,
) -> None:
    """Refresh tokens live in Secret Manager; this table holds a reference."""
    columns = {c.name for c in ProviderConnection.__table__.columns}
    assert "refresh_token" not in columns
    assert "access_token" not in columns
    assert "credential_ref" in columns


async def test_a_usage_reservation_row_is_idempotent_on_its_key(
    db: AsyncSession,
) -> None:
    from sqlalchemy.exc import IntegrityError

    user = await make_user(db)
    db.add(
        UsageReservation(
            key="res-1",
            user_id=user.id,
            team_id="team-1",
            provider="meta",
            model="muse-spark-1.3",
            estimated_tokens=100,
            estimated_micro_minor=1_000,
            state="reserved",
        )
    )
    await db.commit()
    db.add(
        UsageReservation(
            key="res-1",
            user_id=user.id,
            team_id="team-1",
            provider="meta",
            model="muse-spark-1.3",
            estimated_tokens=100,
            estimated_micro_minor=1_000,
            state="reserved",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


def test_money_is_integer_minor_units_everywhere_in_this_module() -> None:
    for column in ("cost_minor", "cost_micro_minor"):
        assert isinstance(AIRun.__table__.columns[column].type, sa.BigInteger)
    assert isinstance(
        UsageReservation.__table__.columns["estimated_micro_minor"].type, sa.BigInteger
    )
    assert minor_units(1) == 1  # a sub-minor-unit cost still costs something


# --------------------------------------------------------------------------- #
# the guard on the guard
# --------------------------------------------------------------------------- #
async def test_a_real_http_request_fails_this_suite() -> None:
    async with httpx.AsyncClient() as c:
        with pytest.raises(AssertionError):
            await c.post("https://api.openai.com/v1/responses", json={})


def test_a_request_can_be_built_without_importing_a_vendor_sdk() -> None:
    """The SDK is imported lazily, so unit tests and ``_build_body`` need no
    network stack and no installed vendor package."""
    assert AIRequest(prompt="x").as_messages() == ({"role": "user", "content": "x"},)
