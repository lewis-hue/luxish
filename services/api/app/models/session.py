"""Sessions and token revocation.

Keycloak issues the bearer tokens, so there is **no bearer material in this
schema** — nothing here is worth stealing. What we do keep is denial state,
because a JWT cannot be un-issued:

* ``sessions`` is keyed on the Keycloak ``sid`` (the device/session identifier
  carried by the token), so one device can be signed out without touching
  another, and so back-channel logout has something to revoke.
* ``revoked_tokens`` is keyed on the token ``jti``, which closes the window
  between ``DELETE /v1/auth/session`` and the token's own ``exp``.

Both rows are only useful until ``expires_at``; a reaper can delete them after
that, which is why the column exists.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, uuid_fk, uuid_pk


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"
    __table_args__ = (
        sa.UniqueConstraint("keycloak_sid", name="uq_sessions_keycloak_sid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: Keycloak's session id. Null only for tokens issued without `sid`.
    keycloak_sid: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class RevokedToken(Base, TimestampMixin):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(sa.String(255), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    #: The presented token's own `exp`; after this the row is dead weight.
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
