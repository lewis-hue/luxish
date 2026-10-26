"""Declarative base and shared mixins.

The naming convention is explicit so that every constraint has a predictable
name — which is what makes a hand-written Alembic ``downgrade`` able to drop it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import JSONB, UTCDateTime, named_enum

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def uuid_fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[uuid.UUID]:
    return mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=sa.func.now(),
    )


__all__ = [
    "JSONB",
    "Base",
    "TimestampMixin",
    "UTCDateTime",
    "named_enum",
    "utcnow",
    "uuid_fk",
    "uuid_pk",
]
