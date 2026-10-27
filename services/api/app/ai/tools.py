"""Tool contracts and dispatch for the stylist loop.

§6: "Enforce authentication and authorization outside the model."

The design follows from taking that literally. Two properties hold no matter what the
model emits, and neither depends on the model being well-behaved:

* **A tool the registry does not hold cannot be called.** Dispatch looks the name up;
  an unknown name is an error returned *to the model*, never an attempted call.
* **The model cannot say whose data to read.** No handler accepts a user id. The
  session's user lives on :class:`ToolContext`, which the loop constructs and the
  model never sees. A perfectly-phrased request for another user's wardrobe has
  nowhere to put the id.

So the prompt-injection defence in ``app.ai.untrusted`` reduces the chance the model
is *persuaded*, and this layer makes being persuaded insufficient.

Handlers return plain JSON-serialisable data. Errors come back as structured results
rather than exceptions, because a tool failure is something the model should be able
to react to — "that garment is unavailable, pick another" is a better outcome than a
failed run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

#: A single run may not call tools forever. Eight is enough for retrieve → check →
#: revise → save with room to spare, and bounds both latency and spend.
MAX_TOOL_CALLS = 8

#: Caps what one tool call can pull back, so a model cannot ask for the whole
#: wardrobe and blow the token budget.
MAX_RESULTS = 40


@dataclass(slots=True)
class ToolContext:
    """What a handler is allowed to know.

    Constructed by the loop from the authenticated session. Deliberately carries the
    user id rather than accepting one per call: a handler that cannot be told whose
    data to touch cannot be tricked into touching someone else's.
    """

    session: AsyncSession
    user_id: uuid.UUID
    run_id: uuid.UUID
    #: Hard constraints already resolved from the request and stored preferences.
    excluded: frozenset[str] = frozenset()
    required: frozenset[str] = frozenset()


ToolHandler = Callable[[ToolContext, Mapping[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler
    #: Tools that change state are listed separately in the audit trail and are the
    #: ones worth reviewing when a run does something surprising.
    mutates: bool = False

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


@dataclass(slots=True)
class ToolExecution:
    """One call, recorded. Persisted against the run for the audit trail."""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    ok: bool
    error_code: str | None = None


class ToolRegistry:
    """The set of tools one run may use.

    Built per run rather than globally, so a run can be given a narrower set than the
    full catalogue — a revision turn does not need `save_outfit`, and not offering it
    is stronger than instructing against it.
    """

    def __init__(self, specs: Sequence[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool {spec.name!r} is already registered")
        self._specs[spec.name] = spec

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._specs)

    def as_openai_tools(self) -> list[dict[str, Any]]:
        return [spec.as_openai_tool() for spec in self._specs.values()]

    async def dispatch(
        self, context: ToolContext, name: str, raw_arguments: str | Mapping[str, Any]
    ) -> ToolExecution:
        """Run one tool call.

        Never raises for a model-caused problem: an unknown tool, malformed
        arguments or a refused action all come back as a structured failure the model
        can read and react to. Only a genuine defect propagates.
        """
        spec = self._specs.get(name)
        if spec is None:
            # The decisive check. Being asked for a tool we do not hold is an event
            # worth recording, not an error to the caller.
            return ToolExecution(
                name=name,
                arguments={},
                result={
                    "error": "unknown_tool",
                    "message": f"{name!r} is not available. Available: {sorted(self.names)}.",
                },
                ok=False,
                error_code="unknown_tool",
            )

        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
            except json.JSONDecodeError as error:
                return ToolExecution(
                    name=name,
                    arguments={},
                    result={"error": "invalid_arguments", "message": str(error)},
                    ok=False,
                    error_code="invalid_arguments",
                )
        else:
            arguments = dict(raw_arguments)

        if not isinstance(arguments, dict):
            return ToolExecution(
                name=name,
                arguments={},
                result={
                    "error": "invalid_arguments",
                    "message": "arguments must be a JSON object",
                },
                ok=False,
                error_code="invalid_arguments",
            )

        # A handler is never handed a user id, so there is nothing here to strip or
        # validate on that front — the shape makes it impossible rather than checked.
        try:
            result = await spec.handler(context, arguments)
        except ToolRefused as refusal:
            return ToolExecution(
                name=name,
                arguments=arguments,
                result={"error": refusal.code, "message": str(refusal)},
                ok=False,
                error_code=refusal.code,
            )

        return ToolExecution(name=name, arguments=arguments, result=result, ok=True)


class ToolRefused(Exception):
    """A handler declining, in terms the model can act on.

    Distinct from a crash: "that garment is in the wash" should make the model pick
    something else, not fail the run.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class ToolBudget:
    """Bounds one run. Checked by the loop before each call."""

    max_calls: int = MAX_TOOL_CALLS
    used: int = 0
    #: Names already called with identical arguments, to catch a model looping on
    #: the same query instead of making progress.
    seen: set[str] = field(default_factory=set)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.max_calls

    def charge(self, name: str, arguments: Mapping[str, Any]) -> bool:
        """Record a call. Returns False when it repeats one already made."""
        self.used += 1
        fingerprint = f"{name}:{json.dumps(arguments, sort_keys=True, default=str)}"
        if fingerprint in self.seen:
            return False
        self.seen.add(fingerprint)
        return True


__all__ = [
    "MAX_RESULTS",
    "MAX_TOOL_CALLS",
    "ToolBudget",
    "ToolContext",
    "ToolExecution",
    "ToolRefused",
    "ToolRegistry",
    "ToolSpec",
]
