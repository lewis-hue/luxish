"""Model registry.

Importing this package registers every table on ``Base.metadata`` — which is
what makes ``create_all`` (tests) and Alembic autogenerate see a complete
schema. One module per domain (ADR-003).
"""

from __future__ import annotations

from app.models.consent import Consent
from app.models.external_reference import ExternalReference
from app.models.garment import Collection, CollectionGarment, Garment
from app.models.identity import ExternalIdentity, IdentityLinkChallenge
from app.models.job import Job
from app.models.media_asset import MediaAsset, MediaDerivative
from app.models.preference import Preference
from app.models.session import RevokedToken, Session
from app.models.tombstone import Tombstone
from app.models.user import User

__all__ = [
    "Collection",
    "CollectionGarment",
    "Consent",
    "ExternalIdentity",
    "ExternalReference",
    "Garment",
    "IdentityLinkChallenge",
    "Job",
    "MediaAsset",
    "MediaDerivative",
    "Preference",
    "RevokedToken",
    "Session",
    "Tombstone",
    "User",
]
