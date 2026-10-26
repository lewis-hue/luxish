"""Model provider adapters and the capability-aware router (ADR-006).

Each adapter declares a :class:`~app.providers.base.ProviderCapabilities`
record; :func:`~app.providers.registry.ProviderRegistry.select` chooses on
declared capability + entitlement + consent + billing source and refuses before
any network call. Vendor SDKs are imported lazily inside the adapters, so
importing this package costs nothing and needs no credential.
"""

from __future__ import annotations

from app.providers.base import (
    AIMessage,
    AIProvider,
    AIRequest,
    AIResponse,
    AIRunRecorder,
    Capabilities,
    InMemoryUsageStore,
    InvalidProviderRequest,
    JsonSchemaFormat,
    NoEligibleProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
    RedisUsageStore,
    Reservation,
    TokenUsage,
    ToolCall,
    UnsupportedCapability,
    UsageLimits,
    UsageStore,
    minor_units,
)
from app.providers.chatgpt_plan import (
    CHATGPT_PLAN_CAPABILITIES,
    CHATGPT_PLAN_STATES,
    ChatGPTConnection,
    ChatGPTPlanProvider,
)
from app.providers.meta import (
    META_MODELS,
    META_PROVIDER_CAPABILITIES,
    MetaModel,
    MetaProvider,
)
from app.providers.registry import (
    ProviderRegistry,
    RoutingSubject,
    default_registry,
    load_routing_subject,
)

__all__ = [
    "CHATGPT_PLAN_CAPABILITIES",
    "CHATGPT_PLAN_STATES",
    "META_MODELS",
    "META_PROVIDER_CAPABILITIES",
    "AIMessage",
    "AIProvider",
    "AIRequest",
    "AIResponse",
    "AIRunRecorder",
    "Capabilities",
    "ChatGPTConnection",
    "ChatGPTPlanProvider",
    "InMemoryUsageStore",
    "InvalidProviderRequest",
    "JsonSchemaFormat",
    "MetaModel",
    "MetaProvider",
    "NoEligibleProvider",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderRegistry",
    "ProviderUnavailable",
    "RedisUsageStore",
    "Reservation",
    "RoutingSubject",
    "TokenUsage",
    "ToolCall",
    "UnsupportedCapability",
    "UsageLimits",
    "UsageStore",
    "default_registry",
    "load_routing_subject",
    "minor_units",
]
