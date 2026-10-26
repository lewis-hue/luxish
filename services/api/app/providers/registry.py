"""Capability + entitlement + consent + billing-source routing (ADR-006).

``select`` asks four independent questions, in this order, and the order is the
interesting part:

1. **Capability.** Does the provider *declare* what the request needs? Asked
   first because it is the only question whose answer is a vendor fact rather
   than a fact about this user, and because getting it wrong is what ADR-006
   exists to prevent: Meta has image generation but no embeddings, the
   ChatGPT-plan route has neither image generation nor file upload, and a router
   assuming parity would fail silently and bill for it.
2. **Consent.** Has the user granted ``ai_processing``? Private by default.
3. **Entitlement.** Is there an active allowance to spend?
4. **Billing source.** Does this provider accept the account the spend would be
   billed to? The ChatGPT-plan route is paid for by the *user's own* plan, so it
   is only ever selected when that is the declared source.

Nothing here opens a socket. A request for an unsupported modality therefore
fails before any network call, which is the requirement stated in ADR-006 and
the reason this module has no transport import at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import Consent
from app.models.provider_connection import ProviderConnection
from app.providers.base import (
    AIProvider,
    Capabilities,
    NoEligibleProvider,
    ProviderCapabilities,
)
from app.providers.chatgpt_plan import INITIAL_STATE, ChatGPTPlanProvider

#: Where the spend lands. ``chatgpt_plan`` is the user's own ChatGPT allowance;
#: the others are accounts on our ledger (Task 12).
BILLING_SOURCES: tuple[str, ...] = (
    "subscription_allowance",
    "gift_credits",
    "chatgpt_plan",
    "internal",
)

#: Billing sources the Meta adapter can be charged against. Not
#: ``chatgpt_plan``: we cannot bill Meta usage to someone's ChatGPT plan.
META_BILLING_SOURCES: tuple[str, ...] = (
    "subscription_allowance",
    "gift_credits",
    "internal",
)

#: The only state the plan route may be selected in (ADR-008).
PLAN_READY_STATE = "inference_authorized"

#: The four questions, as the reason strings a refusal reports.
REJECTION_REASONS: tuple[str, ...] = (
    "capability",
    "consent",
    "entitlement",
    "billing_source",
    "provider_state",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RoutingSubject:
    """Everything ``select`` is allowed to look at.

    Deliberately not a ``User`` row: routing must not be able to reach for a
    field nobody reviewed, and a frozen record of four answers is reviewable at
    a glance. Build it with :func:`load_routing_subject`.
    """

    user_id: uuid.UUID | None = None
    #: Meta's limits are per team, so the team is part of routing, not an
    #: afterthought at call time.
    team_id: str = "default"
    ai_processing_consent: bool = False
    entitlement_active: bool = False
    billing_source: str = "subscription_allowance"
    #: The eight-state ChatGPT-plan inference state for this user.
    chatgpt_inference: str = INITIAL_STATE


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """One registered provider, with the rules for choosing it."""

    provider: AIProvider
    #: Lower is preferred. Ties are broken by registration order.
    priority: int
    billing_sources: frozenset[str]
    requires_consent: bool = True
    requires_entitlement: bool = True
    #: Per-user readiness beyond capability — the plan route's state machine.
    ready: Callable[[RoutingSubject], bool] | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.provider.capabilities

    def reject_reason(self, need: Capabilities, subject: RoutingSubject) -> str | None:
        """The first failing question, or ``None`` when the candidate is eligible."""
        if not need.satisfied_by(self.capabilities):
            return "capability"
        if self.requires_consent and not subject.ai_processing_consent:
            return "consent"
        if self.requires_entitlement and not subject.entitlement_active:
            return "entitlement"
        if subject.billing_source not in self.billing_sources:
            return "billing_source"
        if self.ready is not None and not self.ready(subject):
            return "provider_state"
        return None


@dataclass
class ProviderRegistry:
    """The routing table. Pure: it reads declarations, never a network."""

    candidates: list[Candidate] = field(default_factory=list)

    def register(
        self,
        provider: AIProvider,
        *,
        priority: int,
        billing_sources: Iterable[str],
        requires_consent: bool = True,
        requires_entitlement: bool = True,
        ready: Callable[[RoutingSubject], bool] | None = None,
    ) -> None:
        if any(c.name == provider.name for c in self.candidates):
            raise ValueError(f"a provider named {provider.name!r} is already registered")
        unknown = set(billing_sources) - set(BILLING_SOURCES)
        if unknown:
            raise ValueError(f"unknown billing sources: {sorted(unknown)}")
        self.candidates.append(
            Candidate(
                provider=provider,
                priority=priority,
                billing_sources=frozenset(billing_sources),
                requires_consent=requires_consent,
                requires_entitlement=requires_entitlement,
                ready=ready,
            )
        )
        self.candidates.sort(key=lambda c: c.priority)

    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.candidates)

    def get(self, name: str) -> AIProvider:
        for candidate in self.candidates:
            if candidate.name == name:
                return candidate.provider
        raise KeyError(name)

    def explain(self, need: Capabilities, subject: RoutingSubject) -> dict[str, str]:
        """Why each candidate was rejected. Eligible candidates are omitted."""
        reasons: dict[str, str] = {}
        for candidate in self.candidates:
            reason = candidate.reject_reason(need, subject)
            if reason is not None:
                reasons[candidate.name] = reason
        return reasons

    def select(self, need: Capabilities, subject: RoutingSubject) -> AIProvider:
        """The highest-priority provider that answers all four questions.

        Raises :class:`NoEligibleProvider` carrying a per-candidate reason, so
        the log says *which* of the four to fix rather than "no provider".
        """
        reasons: dict[str, str] = {}
        for candidate in self.candidates:
            reason = candidate.reject_reason(need, subject)
            if reason is None:
                return candidate.provider
            reasons[candidate.name] = reason
        raise NoEligibleProvider(reasons)


def default_registry(
    *,
    meta: AIProvider | None = None,
    chatgpt_plan: AIProvider | None = None,
) -> ProviderRegistry:
    """The shipping routing table: Meta first, the plan route behind it.

    Meta is preferred because it is the only route with image generation, the
    only one we can bill, and the only one that is actually available in this
    build. The plan route is registered anyway so it is rejected on a *declared*
    capability rather than by a special case somewhere else.
    """
    from app.providers.meta import MetaProvider

    registry = ProviderRegistry()
    registry.register(
        meta if meta is not None else MetaProvider(),
        priority=10,
        billing_sources=META_BILLING_SOURCES,
    )
    registry.register(
        chatgpt_plan if chatgpt_plan is not None else ChatGPTPlanProvider(),
        priority=20,
        billing_sources=("chatgpt_plan",),
        # The user's own plan pays, so there is nothing of ours to entitle.
        requires_entitlement=False,
        ready=lambda subject: subject.chatgpt_inference == PLAN_READY_STATE,
    )
    return registry


async def load_routing_subject(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    team_id: str = "default",
    billing_source: str = "subscription_allowance",
    entitlement_active: bool = True,
) -> RoutingSubject:
    """Read the routing inputs for one user.

    ``entitlement_active`` defaults to true and is a **parameter, not a query**:
    entitlements are Task 12's table and do not exist yet. Passing it in keeps
    the seam visible instead of hiding an assumption inside a function that
    looks like it checked.
    """
    granted = await session.scalar(
        sa.select(Consent.id).where(
            Consent.user_id == user_id,
            Consent.kind == "ai_processing",
            Consent.granted_at.is_not(None),
            Consent.revoked_at.is_(None),
        )
    )
    state = await session.scalar(
        sa.select(ProviderConnection.state).where(
            ProviderConnection.user_id == user_id,
            ProviderConnection.provider == "chatgpt_plan",
            ProviderConnection.kind == "inference",
        )
    )
    return RoutingSubject(
        user_id=user_id,
        team_id=team_id,
        ai_processing_consent=granted is not None,
        entitlement_active=entitlement_active,
        billing_source=billing_source,
        chatgpt_inference=state or INITIAL_STATE,
    )


__all__ = [
    "BILLING_SOURCES",
    "META_BILLING_SOURCES",
    "PLAN_READY_STATE",
    "REJECTION_REASONS",
    "Candidate",
    "ProviderRegistry",
    "RoutingSubject",
    "default_registry",
    "load_routing_subject",
]
