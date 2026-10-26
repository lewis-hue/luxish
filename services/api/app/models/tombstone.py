"""Deletion tombstones (ADR-012).

A tombstone deliberately has **no foreign key to ``media_assets``**: it has to
outlive the row it describes. A cascade would delete the very record whose job
is to say "this asset is gone", and a late worker would then find nothing
denying its write.

It is also the answer for an asset we never knew about: deleting an unknown id
still records a tombstone, so a write that arrives afterwards is refused.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, uuid_pk


class Tombstone(Base, TimestampMixin):
    __tablename__ = "tombstones"
    __table_args__ = (sa.UniqueConstraint("asset_id", name="uq_tombstones_asset_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Intentionally not an FK. See the module docstring.
    asset_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    #: Who owned it, for audit after the asset row is gone.
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    asset_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    #: Set once the bytes are confirmed removed from object storage and CDN.
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
