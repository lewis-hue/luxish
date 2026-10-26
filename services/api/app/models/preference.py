"""User style preferences.

Free-form per-key values (``never_wears: ["shorts"]``, ``formality_bias``, …).
Task 9 reads these as deterministic constraints that override regional
defaults; a preference is a user statement and always wins over an inference.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, uuid_fk, uuid_pk


class Preference(Base, TimestampMixin):
    __tablename__ = "preferences"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "key", name="uq_preferences_user_id_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    key: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict)
