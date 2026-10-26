"""Live smoke tests against the real Meta Model API.

**These cost money and are excluded by default.** Everything else in the suite runs
against a transport that raises on any real request; this module is the one place a
network call is intentional, which is why it is a separate file with its own marker.

    # one real run, a few hundred tokens
    MODEL_API_KEY=LLM_... python -m pytest -m live -q

The unit suite already proves the adapter builds correct bodies. What it cannot prove
is that our idea of "correct" matches the vendor's — that the allowlist is complete,
that strict structured output is accepted as we construct it, and that the response
shape we parse is the shape returned. That is what these assert, with the smallest
number of tokens that can demonstrate it.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa

from app.models.ai_run import AIRun
from app.providers.base import AIRequest, AIRunRecorder, JsonSchemaFormat
from app.providers.meta import MetaProvider

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("MODEL_API_KEY"),
        reason="live Meta tests need MODEL_API_KEY; excluded by default",
    ),
]

#: A deliberately tiny wardrobe. The point is the contract, not the styling.
WARDROBE = [
    {"id": "g-101", "category": "shirt", "colour": "white", "formality": "business"},
    {"id": "g-102", "category": "trousers", "colour": "navy", "formality": "business"},
    {"id": "g-103", "category": "heels", "colour": "black", "formality": "business"},
    {"id": "g-104", "category": "loafers", "colour": "brown", "formality": "smart_casual"},
]

OUTFIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items", "reasoning", "feasible"],
    "properties": {
        "feasible": {"type": "boolean"},
        "reasoning": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["garment_id", "role"],
                "properties": {
                    "garment_id": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["top", "bottom", "outer", "shoes", "accessory"],
                    },
                },
            },
        },
    },
}


@pytest.fixture
async def provider(db) -> AsyncIterator[MetaProvider]:
    """A real provider wired to a real recorder.

    ``complete`` refuses to run without a recorder by design — an unaccounted model
    call is a cost nobody can attribute — so the live call also exercises cost
    accounting, which is the part most likely to be quietly wrong.

    The client is closed inside the running loop; letting it be garbage-collected
    afterwards raises "Event loop is closed" from httpx's teardown and buries the
    real output in a traceback.
    """
    instance = MetaProvider(api_key=os.environ["MODEL_API_KEY"], recorder=AIRunRecorder(db))
    try:
        yield instance
    finally:
        client = instance.client()
        close = getattr(client, "close", None)
        if close is not None:
            await close()


async def test_the_model_catalogue_matches_our_configured_ids(provider: MetaProvider) -> None:
    """Our config hardcodes model ids. A rename upstream must fail loudly here.

    Verified live on 2026-10-27: the API returns exactly the nine ids below.
    """
    client = provider.client()
    listed = {model.id for model in (await client.models.list()).data}

    # Every id we route to must exist upstream.
    for configured in ("muse-spark-1.3", "muse-wonder-1.0", "muse-image-1.0", "sam-3.1"):
        assert configured in listed, f"{configured} is no longer offered; listed: {sorted(listed)}"

    # No embeddings model exists — ADR-004 depends on this staying true.
    assert not [m for m in listed if "embed" in m.lower()], (
        "an embeddings model appeared; ADR-004's deferral of pgvector should be revisited"
    )


async def test_a_stylist_shaped_structured_call_returns_a_usable_outfit(
    provider: MetaProvider,
    db,
) -> None:
    """The Phase B workload, end to end through our adapter.

    Asserts the three properties the product depends on: strict structured output is
    accepted as we build it, the model confines itself to ids we supplied, and a hard
    constraint is respected. The last is checked here as well as in the deterministic
    validator because a model that ignores constraints makes the validator reject
    every plan.
    """
    response = await provider.complete(
        AIRequest(
            system=(
                "You are a stylist. Use ONLY garment_id values from the provided "
                "wardrobe. Respect hard constraints absolutely."
            ),
            prompt=(
                f"Wardrobe: {json.dumps(WARDROBE)}\n"
                "Occasion: office in Nairobi, warm. Hard constraint: no heels."
            ),
            model="muse-spark-1.3",
            max_completion_tokens=700,
            reasoning_effort="low",
            response_format=JsonSchemaFormat(
                name="outfit", json_schema=OUTFIT_SCHEMA, strict=True
            ),
            prompt_version="live-smoke-v1",
            purpose="live_smoke",
        )
    )

    outfit = json.loads(response.text)
    chosen = [item["garment_id"] for item in outfit["items"]]

    assert outfit["feasible"] is True
    assert chosen, "no garments chosen"
    # No invented ids — the deterministic guard would reject the run otherwise.
    assert set(chosen) <= {g["id"] for g in WARDROBE}
    # The hard constraint: g-103 is the heels.
    assert "g-103" not in chosen
    assert outfit["reasoning"].strip()

    # Usage must come back populated, or cost accounting silently records zero.
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0

    # The run was recorded with real token counts and a non-zero cost. A provider
    # that returns text but records nothing is the failure mode that only shows up
    # on an invoice.
    runs = (await db.execute(sa.select(AIRun))).scalars().all()
    assert len(runs) == 1
    run = runs[0]
    assert run.provider == "meta"
    assert run.model == "muse-spark-1.3"
    assert run.prompt_version == "live-smoke-v1"
    assert run.input_tokens == response.usage.input_tokens
    assert run.output_tokens == response.usage.output_tokens
    print(
        f"  recorded: {run.input_tokens} in / {run.output_tokens} out, "
        f"cost {run.cost_micro_minor} micro-minor units ({run.currency})"
    )


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("stop", ["\n"]),
        ("n", 3),
        ("logprobs", True),
        ("logit_bias", {"1": 1}),
        ("modalities", ["text"]),
        ("max_tokens", 50),
    ],
)
async def test_refused_parameters_would_really_fail_if_we_sent_them(
    provider: MetaProvider, parameter: str, value: object
) -> None:
    """Confirms the allowlist guards a real failure, not a hypothetical one.

    Verified live on 2026-10-27: all six return HTTP 400. Several are still present
    in Meta's published OpenAPI schema, inherited from OpenAI's spec, so only the
    prose page and this test distinguish documented from accepted.

    This sends the body the adapter *refuses* to send, deliberately bypassing
    ``_build_body`` — so it is the one test here that asserts an adapter bug would be
    caught rather than tolerated.
    """
    client = provider.client()
    body = {
        "model": "muse-spark-1.3",
        "messages": [{"role": "user", "content": "hi"}],
        "max_completion_tokens": 16,
        parameter: value,
    }

    with pytest.raises(Exception) as caught:
        await client.chat.completions.create(**body)

    status = getattr(caught.value, "status_code", None)
    assert status == 400, f"expected 400 for {parameter!r}, got {status}: {caught.value}"


async def test_our_builder_never_emits_a_refused_parameter(provider: MetaProvider) -> None:
    """The companion to the test above, with no network call and no cost."""
    body = provider._build_body(
        AIRequest(prompt="hi", model="muse-spark-1.3", max_completion_tokens=16)
    )
    for refused in (
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
    ):
        assert refused not in body
    assert "max_completion_tokens" in body
