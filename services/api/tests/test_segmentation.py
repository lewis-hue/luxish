"""Task 11 — ``sam-3.1`` segmentation and cut-out compositing (ADR-005).

Everything asserted here about the vendor is a **verified fact**, fetched from
``https://dev.meta.ai/docs`` on 2026-10-27, not a preference:

* there is no segmentation endpoint — it is ``POST /v1/responses``;
* ``metadata.include_confidence`` is the string ``"true"``, not a boolean;
* an absent concept returns ``completed`` with an empty ``output_text``, which
  is a billed success rather than an error;
* one noun phrase per request — a list returns zero matches;
* $2.50 per 1,000 images, charged per team.

No test here touches the network. The ``no_network`` fixture replaces both httpx
transports, so a real outbound request fails the test that attempted it rather
than quietly succeeding on a laptop and failing in CI. The HTTP double is an
``httpx.MockTransport``, which is a *different class* and therefore still proves
the guard is in force.
"""

from __future__ import annotations

import io
import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_run import AIRun
from app.models.user import User
from app.providers.base import AIRunRecorder, InMemoryUsageStore, minor_units
from app.providers.meta import META_MODELS
from app.providers.segmentation import (
    CUTOUT_BACKGROUND,
    MASK_ENCODINGS,
    RESPONSES_PATH,
    SAM_MODEL,
    SAM_PRICE_MICRO_MINOR_PER_IMAGE,
    SEGMENTATION_BODY_ALLOWLIST,
    BiRefNetProvider,
    Box,
    InMemorySegmentationCache,
    InvalidSegmentationPrompt,
    MalformedSegmentation,
    MaskRecord,
    MetaSamParser,
    MetaSamProvider,
    SegmentationProvider,
    SegmentationUnavailable,
    build_segmentation_body,
    composite_cutout,
    content_key,
    extract_output_text,
    garment_noun_phrase,
    select_records,
    validate_noun_phrase,
)

OFF_WHITE_RGB = (0xF2, 0xED, 0xE5)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any real outbound HTTP, in either direction."""

    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test attempted a real network request")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


# --------------------------------------------------------------------------- #
# doubles
# --------------------------------------------------------------------------- #
def responses_payload(text: str, *, status: str = "completed") -> dict[str, Any]:
    """The verified Responses API envelope, with SAM's text in ``output_text``."""
    return {
        "id": "resp_" + uuid.uuid4().hex[:8],
        "object": "response",
        "status": status,
        "model": SAM_MODEL,
        "output": [
            {
                "id": "msg_" + uuid.uuid4().hex[:8],
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
    }


class FakeTransport:
    """Records each request and replies from a queue. No sockets involved."""

    def __init__(self, *payloads: dict[str, Any], status_code: int = 200) -> None:
        self.payloads = list(payloads)
        self.status_code = status_code
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content.decode()))
        payload = self.payloads.pop(0) if self.payloads else responses_payload("")
        return httpx.Response(self.status_code, json=payload)


class StubParser:
    """Stands in for ``meta-sam-parser``: the one call the provider makes."""

    def __init__(self, *records: MaskRecord) -> None:
        self.records = records
        self.seen: list[str] = []

    def parse(self, text: str) -> tuple[MaskRecord, ...]:
        self.seen.append(text)
        if not text.strip():
            return ()
        return self.records


def mask_record(
    *,
    x1: int = 2,
    y1: int = 2,
    x2: int = 5,
    y2: int = 5,
    frame: tuple[int, int] = (8, 8),
    confidence: float | None = 0.9,
    object_id: int = 1,
    raster: bytes | None = None,
    height: int | None = None,
    width: int | None = None,
) -> MaskRecord:
    box = Box(
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        frame_width=frame[0],
        frame_height=frame[1],
        confidence=confidence,
    )
    h = height if height is not None else box.height
    w = width if width is not None else box.width
    return MaskRecord(
        object_id=object_id,
        box=box,
        height=h,
        width=w,
        raster=raster if raster is not None else b"\x01" * (h * w),
        confidence=confidence,
    )


def solid_png(size: tuple[int, int] = (8, 8), colour: tuple[int, int, int] = (10, 20, 200)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


async def make_user(db: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", email_verified=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


def provider(
    db: AsyncSession,
    transport: FakeTransport,
    parser: Any,
    **kwargs: Any,
) -> MetaSamProvider:
    return MetaSamProvider(
        api_key="LLM_test-key-not-a-real-credential",
        http=transport.client(),
        usage=kwargs.pop("usage", None) or InMemoryUsageStore(),
        recorder=AIRunRecorder(db),
        parser=parser,
        cache=kwargs.pop("cache", None) or InMemorySegmentationCache(),
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# the verified request shape
# --------------------------------------------------------------------------- #
def test_the_endpoint_is_the_generic_responses_api_not_a_segment_path() -> None:
    """Verified: sam-3.1 has no dedicated endpoint."""
    assert RESPONSES_PATH == "/responses"
    sam = MetaSamProvider(api_key="LLM_x")
    assert sam.segmentation_url() == "https://api.meta.ai/v1/responses"


def test_the_request_body_is_the_documented_shape() -> None:
    body = build_segmentation_body(prompt="dress", image_url="https://example.test/a.png")

    assert body["model"] == SAM_MODEL
    message = body["input"][0]
    assert message["type"] == "message"
    assert message["role"] == "user"
    assert message["content"][0] == {"type": "input_text", "text": "dress"}
    assert message["content"][1] == {
        "type": "input_image",
        "image_url": "https://example.test/a.png",
    }


def test_include_confidence_is_the_string_true_not_a_boolean() -> None:
    """Verified: a boolean here returns HTTP 400."""
    metadata = build_segmentation_body(prompt="coat", image_url="https://x.test/a.png")[
        "metadata"
    ]
    assert metadata["include_confidence"] == "true"
    assert metadata["include_confidence"] is not True
    assert metadata["mask_encoding"] in MASK_ENCODINGS


def test_the_body_carries_only_allowlisted_keys() -> None:
    body = build_segmentation_body(
        prompt="jacket", image_url="data:image/png;base64,AA", stream=True
    )
    assert set(body) <= SEGMENTATION_BODY_ALLOWLIST
    # Never left to a default that could change: a user's garment photograph is
    # not ours to leave on a vendor's disk.
    assert body["store"] is False


def test_an_unknown_mask_encoding_is_refused_locally() -> None:
    with pytest.raises(Exception, match="mask_encoding"):
        build_segmentation_body(
            prompt="coat", image_url="https://x.test/a.png", mask_encoding="rle"
        )


def test_a_data_uri_is_accepted_so_private_originals_stay_private() -> None:
    body = build_segmentation_body(
        prompt="shoes", image_url="data:image/png;base64,QUJD"
    )
    assert body["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")


# --------------------------------------------------------------------------- #
# one noun phrase per request
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "prompt",
    [
        "dress, shoes",
        "dress; shoes",
        "dress + shoes",
        "dress and shoes",
        "dress or coat",
        "what is this garment?",
        "remove the background!",
        "coat\nshoes",
    ],
)
def test_a_list_or_question_prompt_is_refused_before_any_network_call(prompt: str) -> None:
    """Verified: a list returns ZERO matches and a question is unreliable.

    Refused locally because each such call is $0.0025 and a round trip spent
    learning something the docs already said.
    """
    with pytest.raises(InvalidSegmentationPrompt):
        validate_noun_phrase(prompt)


def test_an_empty_or_overlong_prompt_is_refused() -> None:
    with pytest.raises(InvalidSegmentationPrompt):
        validate_noun_phrase("   ")
    with pytest.raises(InvalidSegmentationPrompt):
        validate_noun_phrase("navy " * 40)


def test_every_closed_category_maps_to_an_acceptable_noun_phrase() -> None:
    from app.domain.garment_media import CATEGORIES, SLOTS

    for category in CATEGORIES:
        assert validate_noun_phrase(garment_noun_phrase(category=category))
    for slot in SLOTS:
        assert validate_noun_phrase(garment_noun_phrase(slot=slot))
    # No category and no slot still yields something sendable.
    assert validate_noun_phrase(garment_noun_phrase()) == "garment"


# --------------------------------------------------------------------------- #
# reading the response
# --------------------------------------------------------------------------- #
def test_output_text_is_read_from_the_output_array() -> None:
    assert extract_output_text(responses_payload("<0f>1<|box|><|mask|>")) == (
        "<0f>1<|box|><|mask|>"
    )
    assert extract_output_text({"output": []}) == ""


async def test_a_missing_concept_is_a_billed_success_not_an_error(
    db: AsyncSession,
) -> None:
    """Verified: ``completed`` with an empty ``output_text``.

    A white garment on a white background returns exactly this. Treating it as a
    failure would retry a $0.0025 call to receive the same nothing, so it is a
    first-class outcome and the AIRun records it as succeeded — the image *was*
    billed.
    """
    user_id = await make_user(db)
    transport = FakeTransport(responses_payload("", status="completed"))
    sam = provider(db, transport, StubParser())

    result = await sam.segment(image=solid_png(), prompt="dress", user_id=user_id)

    assert result.found is False
    assert result.records == ()

    run = (await db.scalars(select(AIRun))).one()
    assert run.outcome == "succeeded"
    assert run.model == SAM_MODEL
    assert run.images == 1
    assert run.cost_micro_minor == SAM_PRICE_MICRO_MINOR_PER_IMAGE


async def test_a_malformed_response_is_a_502_not_a_fabricated_mask(
    db: AsyncSession,
) -> None:
    class Broken:
        def parse(self, text: str) -> tuple[MaskRecord, ...]:
            raise MalformedSegmentation("torn grammar")

    user_id = await make_user(db)
    transport = FakeTransport(responses_payload("<0f>garbage"))
    sam = provider(db, transport, Broken())

    with pytest.raises(MalformedSegmentation):
        await sam.segment(image=solid_png(), prompt="coat", user_id=user_id)

    run = (await db.scalars(select(AIRun))).one()
    assert run.outcome == "failed"


def test_a_raster_of_the_wrong_length_is_refused() -> None:
    """The decoder promises exactly ``H * W`` bytes; a short one is a bug."""
    with pytest.raises(MalformedSegmentation):
        MaskRecord(
            object_id=1,
            box=Box(x1=0, y1=0, x2=3, y2=3, frame_width=8, frame_height=8),
            height=4,
            width=4,
            raster=b"\x01" * 3,
        )


def test_the_mask_decoder_is_metas_own_and_degrades_when_absent() -> None:
    """We do not hand-roll base85 + compression the docs never specify.

    ``meta-sam-parser`` is not installed in this build, so the import failure
    must degrade to a labelled capability gap rather than a guessed decoder.
    """
    parser = MetaSamParser()
    assert "meta-sam-parser>=0.0.6" in parser.REQUIREMENT
    with pytest.raises(SegmentationUnavailable):
        parser.parse("<0f>1<|box;x1=0;y1=0;x2=1;y2=1;w=2;h=2|><|mask;x=0;y=0;data=2,2,~AA|>")


def test_an_empty_line_needs_no_parser_at_all() -> None:
    """The commonest answer must not require an optional dependency."""
    assert MetaSamParser().parse("   ") == ()


# --------------------------------------------------------------------------- #
# cost
# --------------------------------------------------------------------------- #
def test_the_price_is_the_published_two_dollars_fifty_per_thousand() -> None:
    assert SAM_PRICE_MICRO_MINOR_PER_IMAGE == 250_000
    assert (
        META_MODELS[SAM_MODEL].capabilities.price_micro_minor_per_image
        == SAM_PRICE_MICRO_MINOR_PER_IMAGE
    )
    # 1,000 images = 250,000,000 micro-minor = 250 minor units = $2.50.
    assert minor_units(1_000 * SAM_PRICE_MICRO_MINOR_PER_IMAGE) == 250


async def test_the_cost_is_charged_against_the_requesting_user_and_the_team(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    usage = InMemoryUsageStore()
    transport = FakeTransport(responses_payload("<0f>1<|box|><|mask|>"))
    sam = provider(db, transport, StubParser(mask_record()), usage=usage, team_id="team-7")

    result = await sam.segment(image=solid_png(), prompt="dress", user_id=user_id)

    assert result.cost_micro_minor == SAM_PRICE_MICRO_MINOR_PER_IMAGE
    run = (await db.scalars(select(AIRun))).one()
    assert run.user_id == user_id
    assert run.team_id == "team-7"
    assert run.purpose == "wardrobe.background_removal"
    assert run.cost_minor == minor_units(SAM_PRICE_MICRO_MINOR_PER_IMAGE)
    # Verified: rate limits are per team, so the counters are keyed on the team.
    assert any("team-7" in key for key in usage.tracked_keys())
    assert not any("LLM_" in key for key in usage.tracked_keys())


async def test_a_transport_failure_releases_the_reservation_and_records_it(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    usage = InMemoryUsageStore()
    transport = FakeTransport(responses_payload(""), status_code=503)
    sam = provider(db, transport, StubParser(), usage=usage)

    with pytest.raises(httpx.HTTPStatusError):
        await sam.segment(image=solid_png(), prompt="coat", user_id=user_id)

    run = (await db.scalars(select(AIRun))).one()
    assert run.outcome == "failed"
    assert ("release", "default") in usage.events
    snapshot = await usage.snapshot("default")
    assert snapshot["in_flight"] == 0


async def test_an_unaccounted_call_is_impossible(db: AsyncSession) -> None:
    """No recorder, no call. A cost nobody can attribute is a cost nobody can
    explain."""
    transport = FakeTransport(responses_payload(""))
    sam = MetaSamProvider(
        api_key="LLM_x", http=transport.client(), parser=StubParser(), recorder=None
    )
    with pytest.raises(RuntimeError, match="AIRunRecorder"):
        await sam.segment(image=solid_png(), prompt="coat")
    assert transport.requests == []


# --------------------------------------------------------------------------- #
# non-determinism
# --------------------------------------------------------------------------- #
async def test_a_retry_reuses_the_cached_cut_out_rather_than_calling_again(
    db: AsyncSession,
) -> None:
    """Verified: results are non-deterministic between runs.

    An unguarded retry would silently replace a cut-out the user already saw
    with a differently-cropped one, and bill again for the privilege.
    """
    user_id = await make_user(db)
    cache = InMemorySegmentationCache()
    transport = FakeTransport(
        responses_payload("<0f>1<|box|><|mask|>"),
        responses_payload("<0f>1<|box|><|mask|>"),
    )
    sam = provider(db, transport, StubParser(mask_record()), cache=cache)
    image = solid_png()

    first = await sam.segment(image=image, prompt="dress", user_id=user_id)
    second = await sam.segment(image=image, prompt="dress", user_id=user_id)

    assert len(transport.requests) == 1
    assert second.cached is True
    assert second.records == first.records
    assert second.cost_micro_minor == 0
    assert len((await db.scalars(select(AIRun))).all()) == 1


def test_the_cache_key_covers_the_image_the_prompt_and_the_encoding() -> None:
    a, b = solid_png(), solid_png(colour=(1, 2, 3))
    assert content_key(a, prompt="dress", mask_encoding="one_bit") == content_key(
        a, prompt="dress", mask_encoding="one_bit"
    )
    assert content_key(a, prompt="dress", mask_encoding="one_bit") != content_key(
        b, prompt="dress", mask_encoding="one_bit"
    )
    assert content_key(a, prompt="dress", mask_encoding="one_bit") != content_key(
        a, prompt="coat", mask_encoding="one_bit"
    )
    assert content_key(a, prompt="dress", mask_encoding="one_bit") != content_key(
        a, prompt="dress", mask_encoding="lossless"
    )


# --------------------------------------------------------------------------- #
# choosing records
# --------------------------------------------------------------------------- #
def test_the_best_record_wins_and_an_overlapping_fragment_joins_it() -> None:
    """A garment split by an occlusion is one garment; the room is not.

    Both are documented: a hanger merges into the subject, and a garment behind
    a belt comes back as two records.
    """
    best = mask_record(x1=10, y1=10, x2=40, y2=60, confidence=0.95, object_id=1)
    fragment = mask_record(x1=12, y1=55, x2=38, y2=90, confidence=0.6, object_id=2)
    elsewhere = mask_record(x1=200, y1=200, x2=230, y2=240, confidence=0.8, object_id=3)

    chosen = select_records([fragment, elsewhere, best])

    assert [r.object_id for r in chosen] == [1, 2]


def test_no_records_selects_nothing_rather_than_guessing() -> None:
    assert select_records([]) == ()


# --------------------------------------------------------------------------- #
# compositing
# --------------------------------------------------------------------------- #
def test_the_cut_out_lands_on_the_warm_off_white_ground() -> None:
    from PIL import Image

    original = solid_png((8, 8), (10, 20, 200))
    cutout = composite_cutout(original=original, records=[mask_record()])

    with Image.open(io.BytesIO(cutout)) as image:
        assert image.size == (8, 8)
        rgb = image.convert("RGB")
        # Outside the box: the theme ground.
        assert rgb.getpixel((0, 0)) == OFF_WHITE_RGB
        # Inside the box: the original pixels, untouched.
        assert rgb.getpixel((3, 3)) == (10, 20, 200)
    assert CUTOUT_BACKGROUND == "#F2EDE5"


def test_the_original_bytes_are_not_mutated_by_compositing() -> None:
    """§5: the original must survive. It is read, never written."""
    original = solid_png()
    before = bytes(original)
    composite_cutout(original=original, records=[mask_record()])
    assert original == before


def test_a_raster_that_disagrees_with_its_box_is_resized_not_assumed() -> None:
    """The docs describe the two as independent. We reconcile rather than assume.

    A half-resolution raster for a 4x4 box must still fill the box, which is
    what a hardcoded ``H == y2-y1+1`` would get wrong on the first response that
    did not match the published examples.
    """
    from PIL import Image

    record = mask_record(x1=2, y1=2, x2=5, y2=5, height=2, width=2, raster=b"\x01" * 4)
    cutout = composite_cutout(original=solid_png((8, 8), (10, 20, 200)), records=[record])

    with Image.open(io.BytesIO(cutout)) as image:
        rgb = image.convert("RGB")
        for x, y in ((2, 2), (5, 5), (3, 4)):
            assert rgb.getpixel((x, y)) == (10, 20, 200)
        assert rgb.getpixel((7, 7)) == OFF_WHITE_RGB


def test_box_coordinates_are_scaled_when_the_frame_size_differs() -> None:
    """``w=``/``h=`` exist precisely so coordinates can be remapped."""
    box = Box(x1=10, y1=20, x2=30, y2=40, frame_width=100, frame_height=200)
    scaled = box.scaled_to(50, 100)
    assert (scaled.x1, scaled.y1, scaled.x2, scaled.y2) == (5, 10, 15, 20)
    # Same frame: the identical object, no arithmetic.
    assert box.scaled_to(100, 200) is box


def test_an_all_zero_mask_is_a_capability_gap_not_a_blank_image() -> None:
    """Saving a blank cut-out would read as a working integration."""
    record = mask_record(raster=b"\x00" * 16)
    with pytest.raises(SegmentationUnavailable):
        composite_cutout(original=solid_png(), records=[record])


def test_compositing_with_no_records_refuses() -> None:
    with pytest.raises(SegmentationUnavailable):
        composite_cutout(original=solid_png(), records=[])


async def test_cutout_returns_none_with_a_reason_when_nothing_matched(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    transport = FakeTransport(responses_payload(""))
    sam = provider(db, transport, StubParser())

    result = await sam.cutout(image=solid_png(), prompt="dress", user_id=user_id)

    assert result.image is None
    assert result.found is False
    assert result.reason == "no_subject_found"
    assert result.provider == "meta"
    assert result.model == SAM_MODEL


async def test_cutout_returns_png_bytes_when_a_garment_is_found(
    db: AsyncSession,
) -> None:
    user_id = await make_user(db)
    transport = FakeTransport(responses_payload("<0f>1<|box|><|mask|>"))
    sam = provider(db, transport, StubParser(mask_record()))

    result = await sam.cutout(image=solid_png(), prompt="dress", user_id=user_id)

    assert result.image is not None
    assert result.image.startswith(b"\x89PNG")
    assert result.reason is None
    assert result.cost_micro_minor == SAM_PRICE_MICRO_MINOR_PER_IMAGE


# --------------------------------------------------------------------------- #
# the pluggable interface
# --------------------------------------------------------------------------- #
def test_both_backends_satisfy_one_interface() -> None:
    """The swap is config, not a rewrite: $22/day at scenario C, $562/day at D."""
    assert isinstance(MetaSamProvider(api_key="LLM_x"), SegmentationProvider)
    assert isinstance(BiRefNetProvider(), SegmentationProvider)


async def test_birefnet_is_a_labelled_stub_and_never_a_fake_mask() -> None:
    """A fixture must never read as a live integration."""
    with pytest.raises(SegmentationUnavailable) as caught:
        await BiRefNetProvider().cutout(image=solid_png(), prompt="dress")
    assert caught.value.detail["status"] == "planned"
    # MIT, recorded next to the name. The alternatives in this field are not.
    assert caught.value.detail["licence"] == "MIT"


def test_no_commercially_unsafe_background_remover_is_imported() -> None:
    """``rembg``'s default model is now ``bria-rmbg``, which is non-commercial.

    RMBG-1.4's licence specifically prohibits "hosting the Foundation Model for
    access or use by others" — exactly what this app would be doing — and
    RMBG-2.0 is CC BY-NC behind a non-commercial attestation. So nothing in this
    service imports ``rembg`` at all, and the stub records the rule for whoever
    reaches for it next.
    """
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[1]
    for module in ("app/providers/segmentation.py", "app/workers/categorise.py"):
        source = (api_root / module).read_text(encoding="utf-8")
        assert "import rembg" not in source
        assert "from rembg" not in source


def test_the_image_generation_model_is_not_used_for_background_removal() -> None:
    """``muse-image-1.0`` is disqualified: ``mask`` 400s, ``background`` is
    always ``opaque`` so it cannot emit alpha, and it may redraw the garment at
    its own resolution. A re-synthesised garment is a different garment."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "providers" / "segmentation.py"
    ).read_text(encoding="utf-8")
    # Named only in the docstring that explains the disqualification.
    assert source.count("muse-image-1.0") == 1
    assert "disqualified" in source


def test_the_declared_capabilities_match_what_sam_actually_does() -> None:
    caps = META_MODELS[SAM_MODEL].capabilities
    assert caps.text_in and caps.image_in and caps.video_in
    # No embeddings anywhere on this provider (ADR-004).
    assert caps.embeddings is False
    # Billed per image, so there is no documented tokens-per-minute limit.
    assert caps.tokens_per_minute is None
