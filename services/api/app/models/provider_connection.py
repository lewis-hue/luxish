"""A user's connection to an external model provider.

**Identity and inference are separate rows** (ADR-008). "Signing in and using
your plan are separate permissions", and a valid ID token alone does not
authorise plan usage — so ``kind`` is part of the uniqueness key and a user can
be ``identity_connected`` while inference stays ``unavailable``. Collapsing the
two into one row is exactly the mistake the vendor's own documentation warns
against.

**No bearer material is stored here.** There is no ``access_token`` column and
no ``refresh_token`` column; ``credential_ref`` names a Secret Manager entry.
A table that cannot leak a refresh token is better than one that is careful
with one.

**State is driven by observed errors, not by polling.** There is no
allowance-remaining API and no revocation webhook, so ``state`` is whatever the
last response told us, and ``last_error_code`` records what that was.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

AI_PROVIDERS: tuple[str, ...] = ("meta", "chatgpt_plan")

#: One permission each. Keeping them apart is the whole point of this table.
CONNECTION_KINDS: tuple[str, ...] = ("identity", "inference")

#: The eight states of the ChatGPT-plan eligibility machine (ADR-008). The app
#: ships in ``unavailable``.
CONNECTION_STATES: tuple[str, ...] = (
    "unavailable",
    "approval_pending",
    "disconnected",
    "identity_connected",
    "inference_authorized",
    "allowance_exhausted",
    "revoked",
    "error",
)

ai_provider_enum = named_enum("ai_provider", *AI_PROVIDERS)
connection_kind_enum = named_enum("provider_connection_kind", *CONNECTION_KINDS)
connection_state_enum = named_enum("provider_connection_state", *CONNECTION_STATES)


class ProviderConnection(Base, TimestampMixin):
    __tablename__ = "provider_connections"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "kind",
            name="uq_provider_connections_user_id_provider_kind",
        ),
        sa.CheckConstraint(
            "consecutive_transient_failures >= 0", name="transient_failures_non_negative"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    provider: Mapped[str] = mapped_column(ai_provider_enum, nullable=False)
    kind: Mapped[str] = mapped_column(connection_kind_enum, nullable=False)
    state: Mapped[str] = mapped_column(
        connection_state_enum, nullable=False, default="unavailable", server_default="unavailable"
    )

    #: Granted scopes, as the token endpoint reported them. Plan usage needs
    #: ``offline_access resource.invoke chatgpt.tokens.use.direct``.
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'")
    )
    #: Only Plus and Pro are documented as eligible; anything else is "not
    #: stated", which is not the same as "eligible".
    plan_tier: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    #: A Secret Manager resource name. Never a token.
    credential_ref: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    #: The provider's stable subject for this user, for correlation only.
    external_subject: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    #: True once a state is reached that no retry or re-auth can leave
    #: (``subscription_sharing_user_not_eligible``, a confirmed revocation).
    terminal: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    refresh_required: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    last_error_code: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    last_error_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: ``error.param`` from a 400 ``subscription_sharing_unsupported_capability``.
    #: The same body must not be retried; this names what to change.
    unsupported_param: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    consecutive_transient_failures: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    retry_after_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )

    approval_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: When *we* observed the disconnection. There is no webhook, so this is
    #: always our own inference from a failed call or refresh.
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    @property
    def can_infer(self) -> bool:
        return self.kind == "inference" and self.state == "inference_authorized"
