"""External identities and the explicit link challenge.

``(provider, subject)`` is unique, and ``subject`` is the identity provider's
immutable key — Keycloak's ``sub``. Nothing is ever keyed on email.

The link challenge exists because Keycloak's first-broker-login flow will
happily link a brokered account to an existing local account by email address.
We refuse that: a second identity joins an existing user only after the owner
of that user authenticates and confirms.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

IDENTITY_PROVIDERS = ("keycloak", "apple", "google", "chatgpt")

identity_provider_enum = named_enum("identity_provider", *IDENTITY_PROVIDERS)


class ExternalIdentity(Base, TimestampMixin):
    __tablename__ = "external_identities"
    __table_args__ = (
        sa.UniqueConstraint("provider", "subject", name="uq_external_identities_provider_subject"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(identity_provider_enum, nullable=False)
    subject: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")

    #: What the provider asserted at link time, kept for audit. Authorisation
    #: never reads these — it reads the claims on the presented token.
    email_at_link: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    email_verified_at_link: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    linked_by_confirmation: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class IdentityLinkChallenge(Base, TimestampMixin):
    """A pending request to attach ``(provider, subject)`` to an existing user.

    Created when a token's email matches a live account. It is confirmable only
    by someone holding a valid session for that account.
    """

    __tablename__ = "identity_link_challenges"
    __table_args__ = (
        sa.Index("ix_identity_link_challenges_provider_subject", "provider", "subject"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(identity_provider_enum, nullable=False)
    subject: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    claimed_email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    claimed_email_verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
