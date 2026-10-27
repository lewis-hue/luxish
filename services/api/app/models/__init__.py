"""Model registry.

Importing this package registers every table on ``Base.metadata`` — which is
what makes ``create_all`` (tests) and Alembic autogenerate see a complete
schema. One module per domain (ADR-003).
"""

from __future__ import annotations

from app.models.ai_run import AIRun
from app.models.consent import Consent
from app.models.external_reference import ExternalReference
from app.models.garment import Collection, CollectionGarment, Garment
from app.models.identity import ExternalIdentity, IdentityLinkChallenge
from app.models.job import Job
from app.models.media_asset import MediaAsset, MediaDerivative
from app.models.preference import Preference
from app.models.provider_connection import ProviderConnection
from app.models.regional_profile import RegionalStyleProfile
from app.models.session import RevokedToken, Session
from app.models.stylist import (
    Conversation,
    Message,
    Outfit,
    OutfitFeedback,
    OutfitItem,
    StylistRun,
)
from app.models.tombstone import Tombstone
from app.models.usage import UsageReservation
from app.models.user import User

__all__ = [
    "AIRun",
    "Collection",
    "CollectionGarment",
    "Consent",
    "Conversation",
    "ExternalIdentity",
    "ExternalReference",
    "Garment",
    "IdentityLinkChallenge",
    "Job",
    "MediaAsset",
    "MediaDerivative",
    "Message",
    "Outfit",
    "OutfitFeedback",
    "OutfitItem",
    "Preference",
    "ProviderConnection",
    "RegionalStyleProfile",
    "RevokedToken",
    "Session",
    "StylistRun",
    "Tombstone",
    "UsageReservation",
    "User",
]
