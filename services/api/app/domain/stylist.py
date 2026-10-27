"""The stylist loop: a bounded agent, and the Python that overrules it.

The loop is the uninteresting half. **The model proposes; Python decides** —
that sentence is the task, and everything below :func:`finalise_outfit` exists
to make it true in a way that does not depend on the model having behaved.

Four things are re-done after the model returns, every time, whatever it said:

1. **Every garment id is re-validated** through ``validate_owned_ids``, the one
   chokepoint of ADR-010. An invented id and another user's id come back the
   same way — absent — and both fail the run with a structured error. Neither
   degrades into a plausible outfit with one slot quietly different.
2. **Hard constraints are re-applied** from ``ResolvedGuidance.excluded`` and
   ``.required`` (``regional.apply_precedence``). If the user said "no heels"
   and the model returned a heel, the plan is rejected — retried once or twice
   with the violation named, then failed. It is never shown.
3. **Availability is re-checked.** Nothing ``laundry``, ``unavailable`` or
   ``archived`` survives, even if the model was handed it by a tool call that
   asked for unavailable items.
4. **Locked items are re-imposed.** A swap replaces one slot; the others are
   restored from the previous outfit rather than trusted to have been repeated.

The authorisation story is structural rather than instructional. The loop builds
:class:`~app.ai.tools.ToolContext` from the authenticated user, so no tool can
be told whose wardrobe to read; and the registry holds only the tools this turn
is allowed, so a tool the model is persuaded to call by an imported caption is
refused by name lookup before any handler runs. See ``app.ai.untrusted`` for the
other half.

Bounds, all enforced here rather than hoped for: ``MAX_TOOL_CALLS`` tool calls,
:data:`MAX_PLAN_ATTEMPTS` model turns, one hard wall-clock deadline that
cancels an in-flight provider call, and a cooperative cancellation check
between steps.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.stylist_v1 import VERSION, StylistContext, build_messages
from app.ai.schemas import INFEASIBLE_REASONS, OUTFIT_ROLES, OUTFIT_SCHEMA

# `_garment_view` is reached for deliberately rather than re-implemented: the
# shape the model sees of a garment must be identical whether it arrived through
# a `search_wardrobe` tool call or through the initial wardrobe block, or the
# model ends up with two vocabularies for one thing.
from app.ai.stylist_tools import STYLIST_TOOLS, _garment_view
from app.ai.tools import (
    MAX_RESULTS,
    MAX_TOOL_CALLS,
    ToolBudget,
    ToolContext,
    ToolExecution,
    ToolRegistry,
    ToolSpec,
)
from app.ai.untrusted import Untrusted
from app.db.base import utcnow
from app.domain import regional
from app.domain.jobs import enqueue
from app.domain.regional import ResolvedGuidance, UserDirective
from app.domain.wardrobe import decode_cursor
from app.domain.wardrobe_guard import UnownedGarment, validate_owned_ids
from app.errors import ApiError, NotFound
from app.models.garment import STYLEABLE_AVAILABILITY, Garment
from app.models.stylist import (
    OUTFIT_FEEDBACK_KINDS,
    Conversation,
    Message,
    Outfit,
    OutfitFeedback,
    OutfitItem,
    StylistRun,
)
from app.providers.base import (
    AIMessage,
    AIProvider,
    AIRequest,
    AIResponse,
    Capabilities,
    JsonSchemaFormat,
    ProviderError,
)
from app.providers.registry import ProviderRegistry, RoutingSubject, load_routing_subject

logger = logging.getLogger(__name__)

#: The job kind a queued run is claimed under. All model work is queued
#: (ADR-013); the handler is a one-line call to :func:`execute_run`.
JOB_KIND = "stylist.run"

#: What the stylist needs of a provider. Declared, so an adapter that cannot do
#: one of these is rejected before any network call (ADR-006).
STYLIST_CAPABILITIES = Capabilities(
    text_in=True, text_out=True, tools=True, structured_output=True
)

#: How many times the model may be asked for a plan in one run. Two retries is
#: enough to correct a named constraint violation; a third identical failure is
#: a conflict to report, not a loop to keep paying for. ASSUMED bound.
MAX_PLAN_ATTEMPTS = 3

#: Hard wall clock for one run, including every provider call. ASSUMED; Cloud
#: Run's request timeout is why this is enforced rather than left to the vendor
#: client's own timeout.
RUN_TIMEOUT_SECONDS = 90.0

#: Candidates sent to the model. Retrieval decides relevance; the model decides
#: composition. Sending the whole wardrobe would blow the token budget in
#: docs/performance/capacity.md.
MAX_CANDIDATES = MAX_RESULTS

#: Why a run has no outfit. Closed, because the app branches on it: "you own
#: nothing suitable" suggests shopping, "your constraints conflict" suggests
#: relaxing one, and "an id did not validate" is a bug worth alerting on.
EXPLANATION_CODES: tuple[str, ...] = (
    "no_feasible_outfit",
    "constraints_conflict",
    "invalid_garment_id",
    "unavailable_garment",
    "model_output_unusable",
    "provider_unavailable",
    "timed_out",
    "cancelled",
    "slot_not_in_outfit",
)

#: Reasons the model may give for declining, mapped onto ours. Everything
#: honest collapses to one code; the model's own word is kept in the detail.
_MODEL_REASON_CODES: dict[str, str] = {
    "no_suitable_garments": "no_feasible_outfit",
    "constraints_conflict": "constraints_conflict",
    "everything_unavailable": "no_feasible_outfit",
    "occasion_unclear": "no_feasible_outfit",
}

MAX_REQUEST_TEXT = 2_000
MAX_ATTACHMENTS = 8


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class StylistRunFailed(ApiError):
    """An invariant broke, so there is nothing renderable.

    Carries ``explanation_code`` from :data:`EXPLANATION_CODES` so the caller
    does not have to parse a message, and keeps the underlying rejection as
    ``__cause__`` so the log says which id and why.
    """

    status_code = 409
    code = "stylist_run_failed"
    default_message = "That styling run could not be completed."

    def __init__(
        self,
        explanation_code: str,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        self.explanation_code = explanation_code
        self.error_code = error_code or explanation_code
        super().__init__(message, detail={"explanation_code": explanation_code, **(detail or {})})


class ConstraintRejection(Exception):
    """A plan broke a hard constraint. Internal: triggers a retry, then a fail.

    Not an :class:`ApiError` on purpose — a rejected plan is a normal step of
    the loop, and a model that corrects itself on the second turn produced a
    good outfit, not a failure worth surfacing.
    """

    def __init__(self, violations: Mapping[str, Sequence[str]], reason: str) -> None:
        self.violations = {str(k): tuple(v) for k, v in violations.items()}
        self.reason = reason
        super().__init__(f"{reason}: {self.violations}")


class NoFeasibleOutfit(Exception):
    """The honest answer is "none". Carries the code the client branches on."""

    def __init__(self, explanation_code: str = "no_feasible_outfit", explanation: str = "") -> None:
        self.explanation_code = explanation_code
        self.explanation = explanation
        super().__init__(explanation or explanation_code)


class RunCancelled(Exception):
    """Cancellation was requested between steps."""


# --------------------------------------------------------------------------- #
# bounds: wall clock and cancellation
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class RunControl:
    """The run's bounds, injectable so a test can assert them cheaply.

    ``clock`` is a monotonic source and ``cancelled`` a predicate, both
    parameters rather than module globals: a timeout test that has to sleep for
    the real timeout is a test nobody runs.
    """

    timeout_seconds: float = RUN_TIMEOUT_SECONDS
    clock: Callable[[], float] = time.monotonic
    cancelled: Callable[[], bool] = lambda: False
    started_at: float | None = None

    def start(self) -> None:
        self.started_at = self.clock()

    @property
    def elapsed(self) -> float:
        return 0.0 if self.started_at is None else self.clock() - self.started_at

    @property
    def remaining(self) -> float:
        return self.timeout_seconds - self.elapsed

    def check(self) -> None:
        """Raise if the run must stop. Called between every step."""
        if self.cancelled():
            raise RunCancelled()
        if self.remaining <= 0:
            raise TimeoutError(f"stylist run exceeded {self.timeout_seconds}s")


# --------------------------------------------------------------------------- #
# hard constraints, as a deterministic predicate
# --------------------------------------------------------------------------- #
#: "no heels", "without a tie", "I never wear shorts". Deliberately simple and
#: deliberately *recall*-biased: a term we match too eagerly removes a garment
#: the user probably did not want, while a term we miss shows them the thing
#: they told us not to. Only one of those is a privacy-or-trust failure.
_NEGATION = re.compile(
    r"\b(?:no|not|never|without|avoid|avoiding|skip|excluding|exclude)\b"
    r"[\s:,-]*(?:a|an|any|the|my|more)?\s*"
    r"(?P<term>[a-z][a-z'-]*(?:\s+[a-z][a-z'-]*)?)",
    re.IGNORECASE,
)

#: Words that are never the thing being excluded, so "no heels today" yields
#: "heels" rather than "heels today".
_CONSTRAINT_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "again", "all", "an", "and", "any", "anything", "at", "but", "do",
        "ever", "for", "i", "if", "is", "it", "its", "me", "my", "now", "of",
        "on", "one", "or", "please", "really", "so", "than", "thanks", "that",
        "the", "them", "then", "there", "they", "this", "time", "to", "today",
        "tomorrow", "tonight", "too", "very", "want", "wear", "wearing", "with",
        "would", "you",
    }
)

#: Attribute keys whose values describe the garment well enough to match a
#: constraint against. Everything else (ids, timestamps, confidences) is noise.
_DESCRIPTIVE_KEYS: frozenset[str] = frozenset(
    {
        "colour", "color", "category", "subcategory", "style", "styles",
        "material", "materials", "fabric", "pattern", "patterns", "fit",
        "formality", "heel", "heel_height", "silhouette", "seasons", "season",
        "occasions", "occasion", "features", "tags", "notes", "brand", "type",
    }
)


def parse_text_constraints(text: str | None) -> tuple[UserDirective, ...]:
    """Read hard constraints out of what the user typed.

    "office, no heels" is one occasion and one absolute rule, and the rule has
    to reach :func:`finalise_outfit` as data rather than as a sentence the model
    was asked nicely to respect. Phrases produce both the phrase and its head
    noun ("high heels" → ``{"high heels", "heels"}``) so a garment described
    either way is caught.
    """
    if not text:
        return ()

    terms: list[str] = []
    for match in _NEGATION.finditer(text):
        words = [w for w in re.split(r"[^a-z'-]+", match.group("term").lower()) if w]
        words = [w for w in words if w not in _CONSTRAINT_STOPWORDS and len(w) > 1]
        if not words:
            continue
        phrase = " ".join(words[:2])
        terms.append(phrase)
        if len(words) > 1:
            terms.append(words[1])

    unique = tuple(dict.fromkeys(terms))
    if not unique:
        return ()
    return (
        UserDirective(
            kind="hard_constraint",
            rule="exclude",
            values=unique,
            stated=text[:200],
        ),
    )


def _flatten(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, int | float):
        return [str(value)]
    if isinstance(value, Mapping):
        return [part for item in value.values() for part in _flatten(item)]
    if isinstance(value, Iterable):
        return [part for item in value for part in _flatten(item)]
    return []


def describe(garment: Garment) -> str:
    """Everything about a garment a constraint could reasonably refer to."""
    pieces: list[str] = [garment.name or "", garment.category or ""]
    for key, value in (garment.effective_attributes or {}).items():
        if str(key).lower() in _DESCRIPTIVE_KEYS:
            pieces.extend(_flatten(value))
        # Keys outside the descriptive set still contribute their *key* name,
        # so `{"heeled": true}` is matchable without trusting the value shape.
        pieces.append(str(key).replace("_", " "))
    return " ".join(pieces).lower()


def mentions(blob: str, term: str) -> bool:
    """Whole-word match with light inflection, and no substring surprises.

    ``heels`` matches "heel", "heels" and "heeled"; it does not match "wheels",
    which a naive ``in`` check would.
    """
    cleaned = term.strip().lower()
    if not cleaned:
        return False
    stem = cleaned[:-1] if len(cleaned) > 3 and cleaned.endswith("s") else cleaned
    pattern = re.compile(
        rf"(?<![a-z]){re.escape(stem)}(?:s|es|ed|ing)?(?![a-z])", re.IGNORECASE
    )
    return bool(pattern.search(blob))


def constraint_violations(garment: Garment, excluded: Iterable[str]) -> tuple[str, ...]:
    """Which excluded terms this garment matches. Empty means it is allowed."""
    blob = describe(garment)
    return tuple(term for term in sorted(set(excluded)) if mentions(blob, term))


def satisfies(garment: Garment, term: str) -> bool:
    return mentions(describe(garment), term)


# --------------------------------------------------------------------------- #
# the model's answer, parsed
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ProposedItem:
    garment_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ModelPlan:
    """What the model returned, structurally valid and nothing more.

    "Structurally valid" is the entire claim. Whether the ids exist, belong to
    this user, are available, or satisfy a constraint is decided afterwards by
    :func:`finalise_outfit`.
    """

    feasible: bool
    items: tuple[ProposedItem, ...] = ()
    rationale: str = ""
    infeasible_reason: str | None = None
    missing_slots: tuple[str, ...] = ()


def parse_plan(text: str | None) -> ModelPlan:
    """Parse a structured-output response. Raises on anything unusable."""
    if not (text or "").strip():
        raise StylistRunFailed("model_output_unusable", "The model returned nothing.")
    try:
        payload = json.loads(text or "")
    except json.JSONDecodeError as error:
        raise StylistRunFailed(
            "model_output_unusable", "The model's response was not valid JSON."
        ) from error
    if not isinstance(payload, dict):
        raise StylistRunFailed("model_output_unusable", "The model's response was not an object.")

    raw_items = payload.get("items")
    items: list[ProposedItem] = []
    if isinstance(raw_items, list):
        for entry in raw_items[: len(OUTFIT_ROLES) * 2]:
            if not isinstance(entry, dict):
                continue
            garment_id = entry.get("garment_id")
            role = entry.get("role")
            if not isinstance(garment_id, str) or role not in OUTFIT_ROLES:
                # A malformed entry is dropped rather than guessed at; if that
                # leaves the plan empty it becomes an honest "no outfit".
                continue
            items.append(ProposedItem(garment_id=garment_id, role=str(role)))

    reason = payload.get("infeasible_reason")
    return ModelPlan(
        feasible=bool(payload.get("feasible")),
        items=tuple(items),
        rationale=str(payload.get("rationale") or "")[:600],
        infeasible_reason=str(reason) if reason in INFEASIBLE_REASONS else None,
        missing_slots=tuple(
            str(slot) for slot in (payload.get("missing_slots") or []) if slot in OUTFIT_ROLES
        ),
    )


# --------------------------------------------------------------------------- #
# the decision Python makes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class FinalOutfit:
    """A plan that survived revalidation. The only thing allowed to persist."""

    items: tuple[tuple[Garment, str], ...]
    rationale: str = ""
    missing_slots: tuple[str, ...] = ()

    @property
    def garment_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(garment.id for garment, _ in self.items)

    def role_of(self, garment_id: uuid.UUID) -> str | None:
        for garment, role in self.items:
            if garment.id == garment_id:
                return role
        return None


async def finalise_outfit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    plan: ModelPlan,
    guidance: ResolvedGuidance,
    locked: Mapping[str, uuid.UUID] | None = None,
    forbidden_garment_ids: Iterable[uuid.UUID | str] = (),
    swap_slot: str | None = None,
    candidates: Sequence[Garment] = (),
) -> FinalOutfit:
    """Turn a proposal into an outfit, or refuse. **This is the task.**

    Every check here is a re-check: the prompt asked for all of it and the
    tools offered to verify it, and none of that is relied on. The three
    outcomes are deliberately different kinds of thing:

    * :class:`StylistRunFailed` — an id did not validate. ADR-010: a
      model-invented or cross-user id fails the run with a structured error.
      Not retried, because a model that invented an id will invent another.
    * :class:`ConstraintRejection` — a hard constraint was broken. Retryable:
      the violation is nameable, so the next turn can be told exactly what to
      fix.
    * :class:`NoFeasibleOutfit` — the honest "none". Recorded, never papered
      over with a partial outfit.
    """
    locked_map = {str(role): gid for role, gid in (locked or {}).items()}
    forbidden = {str(value) for value in forbidden_garment_ids}

    if not plan.feasible or not plan.items:
        raise NoFeasibleOutfit(
            _MODEL_REASON_CODES.get(plan.infeasible_reason or "", "no_feasible_outfit"),
            plan.rationale,
        )

    # -- 1. compose the slot map, locked items winning ---------------------- #
    proposed: dict[str, str] = {}
    extras: list[ProposedItem] = []
    for item in plan.items:
        if item.role in locked_map:
            # A revision does not get to re-choose a slot it was told to keep.
            continue
        if item.role in proposed:
            extras.append(item)
            continue
        proposed[item.role] = item.garment_id

    repeated = sorted(
        {gid for gid in [*proposed.values(), *(e.garment_id for e in extras)] if gid in forbidden}
    )
    if repeated:
        # Offering back a garment a previous turn rejected is a constraint
        # failure, not an id failure: the id is real, it is just not allowed.
        raise ConstraintRejection({"repeated": repeated}, "previously_rejected_garment")

    if swap_slot is not None and swap_slot not in proposed:
        raise NoFeasibleOutfit(
            "no_feasible_outfit",
            f"No {swap_slot} in the wardrobe satisfies the constraints for this outfit.",
        )

    ordered: list[tuple[str, str]] = [
        (role, str(locked_map[role])) for role in OUTFIT_ROLES if role in locked_map
    ]
    ordered.extend((role, proposed[role]) for role in OUTFIT_ROLES if role in proposed)
    ordered.extend((item.role, item.garment_id) for item in extras)

    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for role, garment_id in ordered:
        if garment_id in seen:
            continue
        seen.add(garment_id)
        deduped.append((role, garment_id))

    if not deduped:
        raise NoFeasibleOutfit("no_feasible_outfit", plan.rationale)

    # -- 2. ADR-010: re-validate every id, including the locked ones -------- #
    try:
        garments = await validate_owned_ids(session, user_id, [gid for _, gid in deduped])
    except UnownedGarment as rejection:
        code = "unavailable_garment" if rejection.reason == "not_styleable" else "invalid_garment_id"
        raise StylistRunFailed(
            code,
            "An item in that outfit is not available from your wardrobe.",
            detail={"garment_ids": rejection.garment_ids, "reason": rejection.reason},
            error_code="unowned_garment",
        ) from rejection

    by_id = {str(garment.id): garment for garment in garments}

    # -- 3. availability, stated here as well as in the guard ---------------- #
    # Duplicated on purpose: the rule "nothing in the wash survives" should be
    # readable at the place that decides what the user sees, not only inside a
    # helper whose definition could widen.
    unavailable = sorted(
        gid for gid, garment in by_id.items() if garment.availability not in STYLEABLE_AVAILABILITY
    )
    if unavailable:  # pragma: no cover - validate_owned_ids already refuses these
        raise StylistRunFailed(
            "unavailable_garment",
            "An item in that outfit is not available.",
            detail={"garment_ids": unavailable},
            error_code="unowned_garment",
        )

    # -- 4. hard constraints, re-applied ------------------------------------ #
    violations: dict[str, tuple[str, ...]] = {}
    for gid, garment in by_id.items():
        hits = constraint_violations(garment, guidance.excluded)
        if hits:
            violations[gid] = hits
    if violations:
        raise ConstraintRejection(violations, "hard_constraint_violated")

    chosen = [(by_id[gid], role) for role, gid in deduped if gid in by_id]

    # A required term the wardrobe *can* satisfy but this plan did not is a
    # retryable miss. One the wardrobe cannot satisfy is a gap to report, not a
    # failure to blame the model for.
    missing_required = [
        term
        for term in sorted(guidance.required)
        if not any(satisfies(garment, term) for garment, _ in chosen)
        and any(satisfies(candidate, term) for candidate in candidates)
    ]
    if missing_required:
        raise ConstraintRejection(
            {"required": tuple(missing_required)}, "required_item_missing"
        )

    unfillable = tuple(
        term
        for term in sorted(guidance.required)
        if not any(satisfies(garment, term) for garment, _ in chosen)
    )

    return FinalOutfit(
        items=tuple(chosen),
        rationale=plan.rationale,
        missing_slots=tuple(dict.fromkeys([*plan.missing_slots, *unfillable]))[:6],
    )


# --------------------------------------------------------------------------- #
# views — what a caller sees, without a lazy relationship in an async session
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class OutfitItemView:
    role: str
    owned: bool
    garment_id: uuid.UUID | None = None
    product_ref: str | None = None
    name: str | None = None
    category: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OutfitView:
    id: uuid.UUID
    items: tuple[OutfitItemView, ...]
    rationale: str | None = None
    occasion: str | None = None
    place: str | None = None
    styled_for: date_type | None = None
    missing_slots: tuple[str, ...] = ()
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StylistRunView:
    """A run as the client polls it. ``outfit is None`` is a real answer."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    state: str
    progress: float
    outfit: OutfitView | None = None
    explanation: str | None = None
    explanation_code: str | None = None
    prompt_version: str | None = None
    provider: str | None = None
    model: str | None = None
    tool_calls_used: int = 0
    tool_executions: tuple[ToolExecution, ...] = ()
    error_code: str | None = None
    swap_slot: str | None = None
    parent_run_id: uuid.UUID | None = None
    excluded: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def executed_tool_names(self) -> tuple[str, ...]:
        return tuple(execution.name for execution in self.tool_executions if execution.ok)

    @property
    def refused_tool_names(self) -> tuple[str, ...]:
        return tuple(execution.name for execution in self.tool_executions if not execution.ok)


@dataclass(frozen=True, slots=True)
class OutfitPage:
    items: tuple[OutfitView, ...]
    next_cursor: str | None = None


# --------------------------------------------------------------------------- #
# starting a run
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Attachment:
    """Imported text offered alongside a request. Data, never policy."""

    source: str
    text: str
    origin_url: str | None = None

    def as_untrusted(self) -> Untrusted:
        return Untrusted.of(self.source, self.text, origin_url=self.origin_url)


async def start_run(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    text: str | None = None,
    occasion: str | None = None,
    place: str | None = None,
    date: date_type | None = None,
    attachments: Sequence[Attachment] = (),
    conversation_id: uuid.UUID | None = None,
    queue: bool = True,
) -> StylistRun:
    """Record the request and queue the work. Returns immediately.

    Nothing here calls a model: ADR-013 forbids awaiting model work in a
    request handler, so this writes a row, enqueues a job and answers 202. The
    loop runs in :func:`execute_run`.
    """
    conversation = await _resolve_conversation(
        session, user_id=user_id, conversation_id=conversation_id, title=text
    )

    run = StylistRun(
        conversation_id=conversation.id,
        user_id=user_id,
        state="queued",
        progress=0.0,
        request_text=(text or "")[:MAX_REQUEST_TEXT] or None,
        occasion=(occasion or "").strip()[:64] or None,
        # A NAME. There is no coordinate path into this column.
        place=(place or "").strip()[:160] or None,
        styled_for=date,
        excluded=[],
        required=[],
        locked_items={},
        forbidden_garment_ids=[],
        prompt_version=VERSION,
    )
    session.add(run)
    await session.flush()

    position = await _next_message_position(session, conversation.id)
    if text:
        session.add(
            Message(
                conversation_id=conversation.id,
                run_id=run.id,
                role="user",
                content=text[:MAX_REQUEST_TEXT],
                untrusted=False,
                position=position,
            )
        )
        position += 1
    for attachment in list(attachments)[:MAX_ATTACHMENTS]:
        quoted = attachment.as_untrusted()
        session.add(
            Message(
                conversation_id=conversation.id,
                run_id=run.id,
                role="user",
                # Stored sanitised, flagged untrusted, and never re-read as an
                # instruction: the flag is what keeps a replay honest.
                content=quoted.text,
                untrusted=True,
                source=quoted.source,
                origin_url=quoted.origin_url,
                position=position,
            )
        )
        position += 1

    conversation.last_run_at = utcnow()
    await session.commit()
    await session.refresh(run)

    if queue:
        job = await enqueue(
            session,
            JOB_KIND,
            {"run_id": str(run.id), "user_id": str(user_id)},
            idempotency_key=f"{JOB_KIND}:{run.id}",
        )
        run.job_id = job.id
        await session.commit()
        await session.refresh(run)
    return run


async def swap_item(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    slot: str,
    queue: bool = True,
) -> StylistRun:
    """Queue a revision that replaces one slot and keeps the rest.

    The new run re-derives its hard constraints from the *original* request
    text and the user's stored preferences rather than inheriting a copy, which
    is why "no heels" cannot erode across swaps: every turn resolves the same
    directives again. What it does inherit is the growing set of garments
    earlier turns already rejected, so a swap cannot return the item it
    replaced.
    """
    if slot not in OUTFIT_ROLES:
        raise ApiError(
            f"Unknown slot {slot!r}.", status_code=422, code="invalid_request"
        )

    previous = await _require_run(session, user_id=user_id, run_id=run_id)
    outfit = await _outfit_of(session, previous.id)
    if outfit is None:
        raise ApiError(
            "That run has no outfit to revise.", status_code=409, code="no_outfit_to_swap"
        )

    items = list(
        (
            await session.scalars(
                sa.select(OutfitItem)
                .where(OutfitItem.outfit_id == outfit.id)
                .order_by(OutfitItem.position)
            )
        ).all()
    )
    target = next((item for item in items if item.role == slot), None)
    if target is None or target.garment_id is None:
        raise StylistRunFailed(
            "slot_not_in_outfit", f"This outfit has no {slot} to swap."
        )

    locked = {
        item.role: str(item.garment_id)
        for item in items
        if item.role != slot and item.garment_id is not None
    }
    forbidden = [
        *(previous.forbidden_garment_ids or []),
        str(target.garment_id),
    ]

    run = StylistRun(
        conversation_id=previous.conversation_id,
        user_id=user_id,
        parent_run_id=previous.id,
        state="queued",
        progress=0.0,
        request_text=previous.request_text,
        occasion=previous.occasion,
        place=previous.place,
        styled_for=previous.styled_for,
        excluded=[],
        required=[],
        swap_slot=slot,
        locked_items=locked,
        forbidden_garment_ids=list(dict.fromkeys(forbidden)),
        prompt_version=VERSION,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    if queue:
        job = await enqueue(
            session,
            JOB_KIND,
            {"run_id": str(run.id), "user_id": str(user_id), "swap_slot": slot},
            idempotency_key=f"{JOB_KIND}:{run.id}",
        )
        run.job_id = job.id
        await session.commit()
        await session.refresh(run)
    return run


async def request_cancellation(
    session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID
) -> StylistRun:
    """Mark a run for cancellation. The loop notices between steps."""
    run = await _require_run(session, user_id=user_id, run_id=run_id)
    if run.is_terminal:
        return run
    run.cancel_requested_at = utcnow()
    await session.commit()
    await session.refresh(run)
    return run


# --------------------------------------------------------------------------- #
# the loop
# --------------------------------------------------------------------------- #
async def resolve_guidance(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    text: str | None,
    occasion: str | None,
    place: str | None,
    date: date_type | None,
) -> tuple[ResolvedGuidance, regional.GeographicStyleContext]:
    """Hard constraints for this turn, resolved deterministically.

    ``apply_precedence`` is pure and re-runnable, so calling it again on a swap
    cannot let a regional suggestion creep back past a user directive — which
    is exactly the property the three-swap criterion needs.
    """
    context = await regional.regional_context(
        session,
        place=place,
        date=date,
        occasion=occasion,
        place_source="user_manual" if place else "declined",
    )
    directives = (
        *await regional.load_user_directives(session, user_id=user_id),
        *parse_text_constraints(text),
    )
    return (
        regional.apply_precedence(context=context, directives=directives, occasion=occasion),
        context,
    )


async def candidate_garments(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    guidance: ResolvedGuidance,
    forbidden_garment_ids: Iterable[uuid.UUID | str] = (),
    limit: int = MAX_CANDIDATES,
) -> list[Garment]:
    """Available, owned, constraint-clean garments — and nothing else.

    Filtering here is defence in depth, not the defence. A model that cannot
    see the heel cannot suggest it, which is more reliable than asking it not
    to; but :func:`finalise_outfit` still re-checks, because a model can name
    an id it was never shown.
    """
    rows = list(
        (
            await session.scalars(
                sa.select(Garment)
                .where(
                    Garment.user_id == user_id,
                    Garment.deleted_at.is_(None),
                    Garment.availability.in_(STYLEABLE_AVAILABILITY),
                )
                .order_by(Garment.created_at.asc(), Garment.id.asc())
            )
        ).all()
    )
    forbidden = {str(value) for value in forbidden_garment_ids}
    return [
        row
        for row in rows
        if str(row.id) not in forbidden and not constraint_violations(row, guidance.excluded)
    ][:limit]


def _nudge(reason: str, detail: str) -> AIMessage:
    """A correction turn. Names the violation; never shows another user's data."""
    return AIMessage(
        role="user",
        content=(
            f"That plan was rejected by the server: {reason}. {detail}\n"
            "Build a different outfit that satisfies every rule. If no outfit in "
            "the wardrobe can, return feasible: false with the reason."
        ),
    )


async def execute_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    registry: ProviderRegistry,
    subject: RoutingSubject | None = None,
    control: RunControl | None = None,
    weather: dict[str, Any] | None = None,
    tools: Sequence[ToolSpec] = STYLIST_TOOLS,
) -> StylistRunView:
    """Run one bounded styling turn to a recorded outcome.

    Ordering is the design. Constraints are resolved before the model is
    called, candidates are filtered before they are shown, the loop is bounded
    before it starts, and the answer is re-validated before it is persisted.
    No step trusts the one before it.
    """
    run = await session.get(StylistRun, run_id)
    if run is None:
        raise NotFound("No such styling run.")
    if run.is_terminal:
        return await load_run_view(session, user_id=run.user_id, run_id=run.id)

    bounds = control or RunControl(
        cancelled=lambda: _cancel_requested(run),
    )
    bounds.start()

    run.state = "running"
    run.started_at = utcnow()
    run.progress = 0.05
    run.prompt_version = VERSION
    await session.commit()

    budget = ToolBudget(max_calls=MAX_TOOL_CALLS)
    executions: list[ToolExecution] = []
    ai_run_ids: list[str] = []
    rejections: list[dict[str, Any]] = []

    try:
        await _guard(session, run, bounds)
        guidance, geo = await resolve_guidance(
            session,
            user_id=run.user_id,
            text=run.request_text,
            occasion=run.occasion,
            place=run.place,
            date=run.styled_for,
        )
        run.excluded = sorted(guidance.excluded)
        run.required = sorted(guidance.required)
        run.progress = 0.15
        await session.commit()

        locked = {
            role: uuid.UUID(str(value)) for role, value in (run.locked_items or {}).items()
        }
        candidates = await candidate_garments(
            session,
            user_id=run.user_id,
            guidance=guidance,
            forbidden_garment_ids=run.forbidden_garment_ids or [],
        )
        # Locked garments must be visible to the model even if the swap filter
        # would otherwise have removed them from the candidate list.
        try:
            locked_rows = (
                await validate_owned_ids(session, run.user_id, list(locked.values()))
                if locked
                else []
            )
        except UnownedGarment as rejection:
            # A garment the revision was told to keep went into the wash (or
            # was deleted) between turns. Failing is right: silently dropping
            # the slot would present a different outfit as the same one.
            raise StylistRunFailed(
                "unavailable_garment"
                if rejection.reason == "not_styleable"
                else "invalid_garment_id",
                "An item you asked to keep is no longer available.",
                detail={"garment_ids": rejection.garment_ids, "reason": rejection.reason},
                error_code="unowned_garment",
            ) from rejection
        visible = list({str(g.id): g for g in [*candidates, *locked_rows]}.values())

        if not candidates:
            # Nothing to style from. Honest, free, and no model call: the
            # answer cannot depend on what a model would have said.
            raise NoFeasibleOutfit(
                "no_feasible_outfit",
                "Nothing in your wardrobe is available to style right now.",
            )

        provider = registry.select(
            STYLIST_CAPABILITIES,
            subject
            or await load_routing_subject(session, run.user_id),
        )
        run.provider = provider.name
        await session.commit()

        untrusted = await _untrusted_for(session, run)
        base_context = StylistContext(
            occasion=run.occasion,
            place=run.place,
            date=run.styled_for.isoformat() if run.styled_for else None,
            garments=[_garment_view(g) for g in visible],
            required=tuple(sorted(guidance.required)),
            excluded=tuple(sorted(guidance.excluded)),
            regional_notes=tuple(geo.notes),
            regional_confidence=geo.confidence or None,
            weather=weather,
            user_constraints=_stated_constraints(run, guidance),
            untrusted=untrusted,
        )
        # Instructions, then data, then fenced untrusted content last — the
        # ordering `build_messages` is responsible for, carried across intact.
        messages = [
            AIMessage(role=part["role"], content=part["content"])  # type: ignore[arg-type]
            for part in build_messages(base_context)
        ]
        if locked or run.swap_slot:
            messages.append(
                AIMessage(role="user", content=_swap_instruction(run, locked, visible))
            )

        registry_of_tools = ToolRegistry(tools)
        tool_context = ToolContext(
            session=session,
            # The model never supplies this. There is no parameter for it.
            user_id=run.user_id,
            run_id=run.id,
            excluded=frozenset(guidance.excluded),
            required=frozenset(guidance.required),
        )

        final: FinalOutfit | None = None
        last_rejection: ConstraintRejection | None = None

        for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
            await _guard(session, run, bounds)
            run.model_attempts = attempt
            run.progress = min(0.85, 0.2 + 0.2 * attempt)
            await session.commit()

            response = await _call_model(
                provider,
                messages=messages,
                tools=registry_of_tools,
                user_id=run.user_id,
                bounds=bounds,
            )
            if response.response_id:
                ai_run_ids.append(response.response_id)
            run.model = response.model

            # -- tool phase, bounded by construction ------------------------- #
            # The loop counter, not the model's cooperation, is what ends this.
            # One extra iteration past the budget exists only to ask for a
            # final answer with the tools withdrawn.
            for _ in range(budget.max_calls + 1):
                if not response.tool_calls:
                    break
                bounds.check()

                if budget.exhausted:
                    messages.append(
                        AIMessage(
                            role="user",
                            content=(
                                f"You have used the maximum of {budget.max_calls} tool "
                                "calls. Answer now from what you already have, or "
                                "return feasible: false with the reason."
                            ),
                        )
                    )
                    # Withdrawing the tools is stronger than instructing
                    # against using them.
                    response = await _call_model(
                        provider,
                        messages=messages,
                        tools=ToolRegistry(),
                        user_id=run.user_id,
                        bounds=bounds,
                    )
                    if response.response_id:
                        ai_run_ids.append(response.response_id)
                    break

                for call in response.tool_calls:
                    if budget.exhausted:
                        break
                    if not budget.charge(call.name, _arguments_of(call.arguments)):
                        # A repeated identical call is a model looping rather
                        # than working. Nudge it; do not re-run the query, and
                        # do not spin.
                        messages.append(
                            AIMessage(
                                role="user",
                                content=(
                                    f"You already called {call.name} with those exact "
                                    "arguments and have the result. Use it, or try a "
                                    "different query."
                                ),
                            )
                        )
                        continue
                    execution = await registry_of_tools.dispatch(
                        tool_context, call.name, call.arguments
                    )
                    executions.append(execution)
                    # Carried back as a labelled user turn rather than a
                    # `tool` role: `AIMessage` has no `tool_call_id`, and
                    # sending a `tool` role without one is an HTTP 400.
                    messages.append(
                        AIMessage(
                            role="user",
                            content=(
                                f"Result of {execution.name}: "
                                f"{json.dumps(execution.result, default=str)[:4000]}"
                            ),
                        )
                    )

                run.tool_calls_used = budget.used
                run.tool_executions = [_execution_row(e) for e in executions]
                await session.commit()

                await _guard(session, run, bounds)
                response = await _call_model(
                    provider,
                    messages=messages,
                    tools=registry_of_tools,
                    user_id=run.user_id,
                    bounds=bounds,
                )
                if response.response_id:
                    ai_run_ids.append(response.response_id)

            # -- the model has proposed; Python decides ---------------------- #
            plan = parse_plan(response.text)
            try:
                final = await finalise_outfit(
                    session,
                    user_id=run.user_id,
                    plan=plan,
                    guidance=guidance,
                    locked=locked,
                    forbidden_garment_ids=run.forbidden_garment_ids or [],
                    swap_slot=run.swap_slot,
                    candidates=candidates,
                )
            except ConstraintRejection as rejection:
                last_rejection = rejection
                rejections.append(
                    {
                        "attempt": attempt,
                        "reason": rejection.reason,
                        "violations": rejection.violations,
                    }
                )
                logger.info(
                    "stylist plan rejected deterministically",
                    extra={
                        "run_id": str(run.id),
                        "attempt": attempt,
                        "reason": rejection.reason,
                    },
                )
                messages.append(
                    _nudge(
                        rejection.reason,
                        _rejection_detail(rejection, guidance),
                    )
                )
                continue
            break

        if final is None:
            # Retries exhausted with the same violation. Reporting a conflict
            # is the correct end: the alternative is showing the thing the user
            # told us not to show.
            raise StylistRunFailed(
                "constraints_conflict",
                "No outfit could be built that respects every constraint you set.",
                detail={
                    "rejections": rejections,
                    "excluded": sorted(guidance.excluded),
                    "violations": last_rejection.violations if last_rejection else {},
                },
                error_code="hard_constraint_violated",
            )

        outfit = await _persist_outfit(session, run=run, final=final)
        run.state = "completed"
        run.progress = 1.0
        run.explanation = final.rationale or None
        run.explanation_code = None
        run.tool_calls_used = budget.used
        run.tool_executions = [_execution_row(e) for e in executions]
        run.ai_run_ids = ai_run_ids
        run.detail = {"rejections": rejections, "outfit_id": str(outfit.id)}
        run.finished_at = utcnow()
        session.add(
            Message(
                conversation_id=run.conversation_id,
                run_id=run.id,
                role="assistant",
                content=final.rationale or None,
                untrusted=False,
                position=await _next_message_position(session, run.conversation_id),
            )
        )
        await session.commit()

    except NoFeasibleOutfit as answer:
        await _record_no_outfit(
            session,
            run,
            explanation_code=answer.explanation_code,
            explanation=answer.explanation
            or "No outfit in your wardrobe satisfies this request.",
            executions=executions,
            ai_run_ids=ai_run_ids,
            rejections=rejections,
            budget=budget,
        )
    except RunCancelled:
        await _record_failure(
            session,
            run,
            state="cancelled",
            explanation_code="cancelled",
            explanation="This styling run was cancelled.",
            error_code="cancelled",
            executions=executions,
            ai_run_ids=ai_run_ids,
            rejections=rejections,
            budget=budget,
        )
    except TimeoutError as expiry:
        await _record_failure(
            session,
            run,
            state="failed",
            explanation_code="timed_out",
            explanation="This styling run took too long and was stopped.",
            error_code="timed_out",
            error_message=str(expiry),
            executions=executions,
            ai_run_ids=ai_run_ids,
            rejections=rejections,
            budget=budget,
        )
    except StylistRunFailed as failure:
        await _record_failure(
            session,
            run,
            state="failed",
            explanation_code=failure.explanation_code,
            explanation=failure.message,
            error_code=failure.error_code,
            error_message=json.dumps(failure.detail, default=str)[:2000],
            executions=executions,
            ai_run_ids=ai_run_ids,
            rejections=rejections,
            budget=budget,
        )
    except ProviderError as failure:
        await _record_failure(
            session,
            run,
            state="failed",
            explanation_code="provider_unavailable",
            explanation="The styling service is unavailable. Please try again.",
            error_code=failure.code,
            error_message=str(failure),
            executions=executions,
            ai_run_ids=ai_run_ids,
            rejections=rejections,
            budget=budget,
        )

    return await load_run_view(session, user_id=run.user_id, run_id=run.id)


async def _call_model(
    provider: AIProvider,
    *,
    messages: Sequence[AIMessage],
    tools: ToolRegistry,
    user_id: uuid.UUID,
    bounds: RunControl,
) -> AIResponse:
    """One provider call, inside the run's remaining wall clock.

    ``wait_for`` rather than a vendor timeout: the budget being enforced is the
    *run's*, and a provider that hangs must not be able to outlive it. The
    in-flight task is cancelled, which is what "cancels cleanly" means here.
    """
    request = AIRequest(
        messages=tuple(messages),
        # Recorded on every AIRun by the adapter (§6: versioned prompts).
        prompt_version=VERSION,
        purpose="stylist.run",
        needs=STYLIST_CAPABILITIES,
        tools=tuple(tools.as_openai_tools()),
        response_format=JsonSchemaFormat(name="outfit_plan", json_schema=OUTFIT_SCHEMA),
        temperature=0.4,
        max_completion_tokens=1200,
    )
    remaining = bounds.remaining
    if remaining <= 0:
        raise TimeoutError(f"stylist run exceeded {bounds.timeout_seconds}s")
    try:
        return await asyncio.wait_for(
            provider.complete(request, user_id=user_id), timeout=remaining
        )
    except TimeoutError as expiry:
        # `asyncio.wait_for` raises the builtin on 3.11+. The in-flight task is
        # already cancelled by the time this runs — that is the clean stop.
        raise TimeoutError(
            f"the provider did not answer within the run's remaining {remaining:.1f}s"
        ) from expiry


# --------------------------------------------------------------------------- #
# feedback and saved outfits
# --------------------------------------------------------------------------- #
async def record_feedback(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    outfit_id: uuid.UUID,
    kind: str,
    note: str | None = None,
) -> OutfitFeedback:
    """Record what the user said. Idempotent per (outfit, user, kind)."""
    if kind not in OUTFIT_FEEDBACK_KINDS:
        raise ApiError(
            f"Unknown feedback kind {kind!r}.", status_code=422, code="invalid_request"
        )
    outfit = await session.scalar(
        sa.select(Outfit).where(
            Outfit.id == outfit_id,
            Outfit.user_id == user_id,
            Outfit.deleted_at.is_(None),
        )
    )
    if outfit is None:
        # Not yours and not existing are the same answer.
        raise NotFound("No such outfit.")

    existing = await session.scalar(
        sa.select(OutfitFeedback).where(
            OutfitFeedback.outfit_id == outfit_id,
            OutfitFeedback.user_id == user_id,
            OutfitFeedback.kind == kind,
        )
    )
    if existing is not None:
        existing.note = (note or "")[:500] or existing.note
        await session.commit()
        await session.refresh(existing)
        return existing

    feedback = OutfitFeedback(
        outfit_id=outfit_id, user_id=user_id, kind=kind, note=(note or "")[:500] or None
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    return feedback


async def list_outfits(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 20,
) -> OutfitPage:
    """Saved outfits, newest first, keyset-paginated like the wardrobe."""
    limit = max(1, min(limit, 100))
    query = sa.select(Outfit).where(
        Outfit.user_id == user_id,
        Outfit.deleted_at.is_(None),
        Outfit.saved.is_(True),
    )
    if cursor:
        created_at, last_id = decode_cursor(cursor)
        query = query.where(
            sa.tuple_(Outfit.created_at, Outfit.id) < sa.tuple_(created_at, last_id)
        )
    rows = list(
        (
            await session.scalars(
                query.order_by(Outfit.created_at.desc(), Outfit.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    page = rows[:limit]
    next_cursor = _encode_outfit_cursor(rows[limit - 1]) if len(rows) > limit else None
    views = [await _outfit_view(session, outfit) for outfit in page]
    return OutfitPage(items=tuple(views), next_cursor=next_cursor)


async def load_run_view(
    session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID
) -> StylistRunView:
    run = await _require_run(session, user_id=user_id, run_id=run_id)
    outfit = await _outfit_of(session, run.id)
    return StylistRunView(
        id=run.id,
        conversation_id=run.conversation_id,
        state=run.state,
        progress=run.progress,
        outfit=await _outfit_view(session, outfit) if outfit is not None else None,
        explanation=run.explanation,
        explanation_code=run.explanation_code,
        prompt_version=run.prompt_version,
        provider=run.provider,
        model=run.model,
        tool_calls_used=run.tool_calls_used,
        tool_executions=tuple(
            ToolExecution(
                name=str(entry.get("name")),
                arguments=dict(entry.get("arguments") or {}),
                result=dict(entry.get("result") or {}),
                ok=bool(entry.get("ok")),
                error_code=entry.get("error_code"),
            )
            for entry in (run.tool_executions or [])
        ),
        error_code=run.error_code,
        swap_slot=run.swap_slot,
        parent_run_id=run.parent_run_id,
        excluded=tuple(run.excluded or ()),
        required=tuple(run.required or ()),
        detail=dict(run.detail or {}),
    )


# --------------------------------------------------------------------------- #
# internals
# --------------------------------------------------------------------------- #
def _cancel_requested(run: StylistRun) -> bool:
    return run.cancel_requested_at is not None


async def _guard(session: AsyncSession, run: StylistRun, bounds: RunControl) -> None:
    """Deadline and cancellation, checked together between steps.

    The cancellation read hits the database rather than the in-memory row:
    ``POST /runs/{id}/cancel`` is served by a web process and the loop runs in
    a worker, so an in-process predicate would never see it. One indexed
    primary-key read per step is a fair price for a cancel button that works.
    """
    bounds.check()
    requested = await session.scalar(
        sa.select(StylistRun.cancel_requested_at).where(StylistRun.id == run.id)
    )
    if requested is not None:
        raise RunCancelled()


def _arguments_of(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if (raw or "").strip() else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _execution_row(execution: ToolExecution) -> dict[str, Any]:
    return {
        "name": execution.name,
        "arguments": execution.arguments,
        "ok": execution.ok,
        "error_code": execution.error_code,
        # The result is kept because "what did the model actually see" is the
        # first question asked about a surprising run.
        "result": execution.result,
    }


def _stated_constraints(run: StylistRun, guidance: ResolvedGuidance) -> tuple[str, ...]:
    stated = [f"must not include: {term}" for term in sorted(guidance.excluded)]
    stated.extend(f"must include: {term}" for term in sorted(guidance.required))
    if run.swap_slot:
        stated.append(f"replace the {run.swap_slot} with a different garment")
    return tuple(stated)


def _swap_instruction(
    run: StylistRun, locked: Mapping[str, uuid.UUID], visible: Sequence[Garment]
) -> str:
    known = {str(g.id) for g in visible}
    kept = ", ".join(
        f"{role}={gid}" for role, gid in sorted(locked.items()) if str(gid) in known
    )
    lines = [
        f"This is a revision. Keep every one of these exactly as they are: {kept or 'none'}."
    ]
    if run.swap_slot:
        lines.append(
            f"Choose a different {run.swap_slot} from the wardrobe. Do not reuse a "
            "garment an earlier turn rejected."
        )
    lines.append("Every other rule still applies.")
    return "\n".join(lines)


def _rejection_detail(rejection: ConstraintRejection, guidance: ResolvedGuidance) -> str:
    if rejection.reason == "hard_constraint_violated":
        terms = sorted({term for hits in rejection.violations.values() for term in hits})
        return (
            f"These garments break an absolute rule ({', '.join(terms)}): "
            f"{', '.join(sorted(rejection.violations))}. They are not usable in any outfit."
        )
    if rejection.reason == "previously_rejected_garment":
        return (
            "You returned a garment an earlier turn already rejected: "
            f"{', '.join(rejection.violations.get('repeated', ()))}."
        )
    if rejection.reason == "required_item_missing":
        return (
            "The outfit must include: "
            f"{', '.join(rejection.violations.get('required', ()))}."
        )
    return f"Constraints in force: must not include {sorted(guidance.excluded)}."


async def _resolve_conversation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    title: str | None,
) -> Conversation:
    if conversation_id is not None:
        conversation = await session.scalar(
            sa.select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        if conversation is None:
            raise NotFound("No such conversation.")
        return conversation
    conversation = Conversation(user_id=user_id, title=(title or "")[:200] or None)
    session.add(conversation)
    await session.flush()
    return conversation


async def _next_message_position(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    highest = await session.scalar(
        sa.select(sa.func.max(Message.position)).where(
            Message.conversation_id == conversation_id
        )
    )
    return int(highest or 0) + 1


async def _untrusted_for(session: AsyncSession, run: StylistRun) -> list[Untrusted]:
    """The imported text for this turn, re-wrapped so it is fenced again.

    Round-tripping through :class:`Untrusted` rather than splicing the stored
    string means the only path from the database into a prompt is the one that
    fences and sanitises.
    """
    rows = list(
        (
            await session.scalars(
                sa.select(Message)
                .where(
                    Message.conversation_id == run.conversation_id,
                    Message.untrusted.is_(True),
                )
                .order_by(Message.position)
            )
        ).all()
    )
    return [
        Untrusted.of(row.source or "imported", row.content or "", origin_url=row.origin_url)
        for row in rows
        if (row.content or "").strip()
    ]


async def _persist_outfit(
    session: AsyncSession, *, run: StylistRun, final: FinalOutfit
) -> Outfit:
    """Write the outfit. Reached only from a validated :class:`FinalOutfit`."""
    if run.parent_run_id is not None:
        # A swap supersedes the plan it revised rather than deleting it.
        await session.execute(
            sa.update(Outfit)
            .where(Outfit.run_id == run.parent_run_id, Outfit.user_id == run.user_id)
            .values(saved=False)
        )

    outfit = Outfit(
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        rationale=(final.rationale or None),
        occasion=run.occasion,
        place=run.place,
        styled_for=run.styled_for,
        missing_slots=list(final.missing_slots),
        saved=True,
    )
    session.add(outfit)
    await session.flush()
    for position, (garment, role) in enumerate(final.items):
        session.add(
            OutfitItem(
                outfit_id=outfit.id,
                garment_id=garment.id,
                role=role,
                owned=True,
                position=position,
            )
        )
    await session.flush()
    return outfit


async def _recover_session(session: AsyncSession, run: StylistRun) -> None:
    """Make the session usable again after an aborted step.

    Cancelling a provider call unwinds the task wherever it happened to be,
    and the adapter writes its ``AIRun`` through *this* session — so a timeout
    can land mid-flush and leave the transaction deactivated. Recording the
    outcome then fails with ``PendingRollbackError``, which would turn "the run
    timed out" into "the run vanished". Discarding the broken transaction and
    re-reading the row is what makes the outcome recordable from any step.

    Guarded on ``is_active`` so the healthy paths are untouched: an
    unconditional rollback would expire every object the caller still holds,
    which is a surprising thing for "record this outcome" to do.
    """
    if session.is_active:
        return
    try:
        await session.rollback()
    except Exception:
        # Nothing better exists to do: the outcome still has to be recorded.
        logger.exception("could not roll back after an aborted stylist step")
    try:
        await session.refresh(run)
    except Exception:
        # The row is re-read by load_run_view afterwards if this failed.
        logger.exception("could not re-read run %s after an aborted step", run.id)


async def _record_no_outfit(
    session: AsyncSession,
    run: StylistRun,
    *,
    explanation_code: str,
    explanation: str,
    executions: Sequence[ToolExecution],
    ai_run_ids: Sequence[str],
    rejections: Sequence[dict[str, Any]],
    budget: ToolBudget,
) -> None:
    """A completed run with no outfit. Explained, not invented."""
    await _recover_session(session, run)
    run.state = "completed"
    run.progress = 1.0
    run.explanation_code = explanation_code
    run.explanation = explanation
    run.tool_calls_used = budget.used
    run.tool_executions = [_execution_row(e) for e in executions]
    run.ai_run_ids = list(ai_run_ids)
    run.detail = {"rejections": list(rejections)}
    run.finished_at = utcnow()
    session.add(
        Message(
            conversation_id=run.conversation_id,
            run_id=run.id,
            role="assistant",
            content=explanation,
            untrusted=False,
            position=await _next_message_position(session, run.conversation_id),
        )
    )
    await session.commit()


async def _record_failure(
    session: AsyncSession,
    run: StylistRun,
    *,
    state: str,
    explanation_code: str,
    explanation: str,
    error_code: str,
    executions: Sequence[ToolExecution],
    ai_run_ids: Sequence[str],
    rejections: Sequence[dict[str, Any]],
    budget: ToolBudget,
    error_message: str | None = None,
) -> None:
    await _recover_session(session, run)
    run.state = state
    run.progress = 1.0
    run.explanation_code = explanation_code
    run.explanation = explanation
    run.error_code = error_code[:96]
    run.error_message = (error_message or "")[:2000] or None
    run.tool_calls_used = budget.used
    run.tool_executions = [_execution_row(e) for e in executions]
    run.ai_run_ids = list(ai_run_ids)
    run.detail = {"rejections": list(rejections)}
    run.finished_at = utcnow()
    await session.commit()
    logger.warning(
        "stylist run did not produce an outfit",
        extra={"run_id": str(run.id), "state": state, "code": explanation_code},
    )


async def _require_run(
    session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID
) -> StylistRun:
    run = await session.scalar(
        sa.select(StylistRun).where(StylistRun.id == run_id, StylistRun.user_id == user_id)
    )
    if run is None:
        raise NotFound("No such styling run.")
    return run


async def _outfit_of(session: AsyncSession, run_id: uuid.UUID) -> Outfit | None:
    return await session.scalar(
        sa.select(Outfit).where(Outfit.run_id == run_id, Outfit.deleted_at.is_(None))
    )


async def _outfit_view(session: AsyncSession, outfit: Outfit) -> OutfitView:
    rows = list(
        (
            await session.scalars(
                sa.select(OutfitItem)
                .where(OutfitItem.outfit_id == outfit.id)
                .order_by(OutfitItem.position)
            )
        ).all()
    )
    garment_ids = [row.garment_id for row in rows if row.garment_id is not None]
    garments: dict[uuid.UUID, Garment] = {}
    if garment_ids:
        garments = {
            g.id: g
            for g in (
                await session.scalars(sa.select(Garment).where(Garment.id.in_(garment_ids)))
            ).all()
        }
    items = []
    for row in rows:
        garment = garments.get(row.garment_id) if row.garment_id else None
        items.append(
            OutfitItemView(
                role=row.role,
                owned=row.owned,
                garment_id=row.garment_id,
                product_ref=row.product_ref,
                name=garment.name if garment else None,
                category=garment.category if garment else None,
                attributes=dict(garment.effective_attributes) if garment else {},
            )
        )
    return OutfitView(
        id=outfit.id,
        items=tuple(items),
        rationale=outfit.rationale,
        occasion=outfit.occasion,
        place=outfit.place,
        styled_for=outfit.styled_for,
        missing_slots=tuple(outfit.missing_slots or ()),
        created_at=outfit.created_at,
    )


def _encode_outfit_cursor(outfit: Outfit) -> str:
    raw = json.dumps(
        {"created_at": outfit.created_at.astimezone(UTC).isoformat(), "id": str(outfit.id)}
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def handle_job(session: AsyncSession, job: Any) -> dict[str, Any]:
    """Worker entry point for :data:`JOB_KIND`.

    Thin on purpose: the queue decides *when*, this module decides *what*.
    """
    from app.providers.base import AIRunRecorder
    from app.providers.registry import default_registry

    raw = (job.payload or {}).get("run_id")
    if not raw:
        raise ValueError(f"job {job.id} carries no run_id")
    from app.providers.meta import MetaProvider

    registry = default_registry(meta=MetaProvider(recorder=AIRunRecorder(session)))
    view = await execute_run(session, uuid.UUID(str(raw)), registry=registry)
    return {
        "run_id": str(view.id),
        "state": view.state,
        "explanation_code": view.explanation_code,
    }


__all__ = [
    "EXPLANATION_CODES",
    "JOB_KIND",
    "MAX_PLAN_ATTEMPTS",
    "RUN_TIMEOUT_SECONDS",
    "STYLIST_CAPABILITIES",
    "Attachment",
    "ConstraintRejection",
    "FinalOutfit",
    "ModelPlan",
    "NoFeasibleOutfit",
    "OutfitItemView",
    "OutfitPage",
    "OutfitView",
    "ProposedItem",
    "RunCancelled",
    "RunControl",
    "StylistRunFailed",
    "StylistRunView",
    "candidate_garments",
    "constraint_violations",
    "describe",
    "execute_run",
    "finalise_outfit",
    "handle_job",
    "list_outfits",
    "load_run_view",
    "mentions",
    "parse_plan",
    "parse_text_constraints",
    "record_feedback",
    "request_cancellation",
    "resolve_guidance",
    "start_run",
    "swap_item",
]
