"""The user record.

A user is keyed on an internal UUID, never on an email address: email is
mutable and, in a brokered-identity world, is also attacker-influenced.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        # One live account per email. Soft-deleted rows are excluded so a
        # deletion does not permanently burn the address.
        sa.Index(
            "uq_users_email_live",
            "email",
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    display_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    locale: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
