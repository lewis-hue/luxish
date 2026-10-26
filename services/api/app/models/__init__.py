"""Model registry.

Importing this package registers every table on ``Base.metadata`` — which is
what makes ``create_all`` (tests) and Alembic autogenerate see a complete
schema. One module per domain (ADR-003).
"""

from __future__ import annotations

from app.models.consent import Consent
from app.models.identity import ExternalIdentity, IdentityLinkChallenge
from app.models.preference import Preference
from app.models.session import RevokedToken, Session
from app.models.user import User

__all__ = [
    "Consent",
    "ExternalIdentity",
    "IdentityLinkChallenge",
    "Preference",
    "RevokedToken",
    "Session",
    "User",
]
