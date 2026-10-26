"""The garment.

The separation of ``confirmed_attributes`` from ``inferred_attributes`` is the
whole point of this module. They are different kinds of claim:

* ``confirmed_attributes`` is what the user told us. It is authoritative.
* ``inferred_attributes`` is what a model guessed, with a confidence and the
  prompt/model version that produced it.

Merging happens on *read* (``effective_attributes``), so a worker writing a
later, more confident inference can never overwrite a user's correction — there
is no column for it to overwrite. Retrieval over these attributes is
deterministic SQL, not vector similarity (ADR-004).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, named_enum, uuid_pk

AVAILABILITY_VALUES: tuple[str, ...] = ("available", "laundry", "unavailable", "archived")

availability_enum = named_enum("garment_availability", *AVAILABILITY_VALUES)

#: Availability states a garment can be styled from. Task 7's owned-id guard
#: rejects everything else.
STYLEABLE_AVAILABILITY: frozenset[str] = frozenset({"available"})


class Garment(Base, TimestampMixin):
    __tablename__ = "garments"
    __table_args__ = (
        sa.Index("ix_garments_user_id_created_at", "user_id", "created_at"),
        sa.Index("ix_garments_user_id_category", "user_id", "category"),
        sa.Index("ix_garments_user_id_availability", "user_id", "availability"),
        sa.CheckConstraint(
            "inference_confidence IS NULL OR "
            "(inference_confidence >= 0 AND inference_confidence <= 1)",
            name="inference_confidence_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    category: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    availability: Mapped[str] = mapped_column(
        availability_enum, nullable=False, default="available", server_default="available"
    )

    #: User-stated truth. Wins on every key it defines.
    confirmed_attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa.text("'{}'")
    )
    #: Model output. Never merged into the column above.
    inferred_attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa.text("'{}'")
    )
    inference_confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    inference_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    inferred_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    @property
    def effective_attributes(self) -> dict[str, Any]:
        """Inferred attributes, with every confirmed key overriding them."""
        merged: dict[str, Any] = dict(self.inferred_attributes or {})
        merged.update(self.confirmed_attributes or {})
        return merged

    @property
    def is_styleable(self) -> bool:
        return self.deleted_at is None and self.availability in STYLEABLE_AVAILABILITY


class Collection(Base, TimestampMixin):
    """A user-made grouping of garments (capsule, trip, season)."""

    __tablename__ = "collections"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "name", name="uq_collections_user_id_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class CollectionGarment(Base):
    __tablename__ = "collection_garments"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    garment_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("garments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
