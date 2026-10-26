"""Column types that behave identically on PostgreSQL 16 and on SQLite.

The production database is PostgreSQL. SQLite (aiosqlite) exists only so the
unit suite can run without a server; these variants keep one schema definition
honest on both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

#: JSONB on PostgreSQL, JSON on SQLite.
JSONB = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


class UTCDateTime(sa.types.TypeDecorator):
    """Timezone-aware timestamps that stay timezone-aware after a round trip.

    SQLite has no ``timestamptz``, so values come back naive; this re-attaches
    UTC rather than letting a naive value leak into comparison logic.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            raise ValueError("naive datetime refused; pass an aware UTC datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def named_enum(name: str, *values: str) -> sa.Enum:
    """A named enum: native type on PostgreSQL, VARCHAR + CHECK on SQLite."""
    return sa.Enum(*values, name=name, validate_strings=True)
