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
        sa.Index("ix_garments_user_id_is_favourite", "user_id", "is_favourite"),
        sa.CheckConstraint(
            "inference_confidence IS NULL OR "
            "(inference_confidence >= 0 AND inference_confidence <= 1)",
            name="inference_confidence_range",
        ),
        sa.CheckConstraint(
            "categorisation_confidence IS NULL OR "
            "(categorisation_confidence >= 0 AND categorisation_confidence <= 1)",
            name="categorisation_confidence_range",
        ),
        # One garment per photograph, so a double-tap on "add" or a retried
        # bulk upload cannot produce two rows for the same image. Partial,
        # because rows with no asset and deleted rows must still be allowed to
        # collide — a user may re-add something they removed.
        sa.Index(
            "uq_garments_user_id_media_asset_id",
            "user_id",
            "media_asset_id",
            unique=True,
            postgresql_where=sa.text(
                "media_asset_id IS NOT NULL AND deleted_at IS NULL"
            ),
            sqlite_where=sa.text("media_asset_id IS NOT NULL AND deleted_at IS NULL"),
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

    #: Confidence in the *slot* the auto-categoriser chose, separate from
    #: ``inference_confidence`` (which covers the attribute payload). Kept apart
    #: because the UI acts on them differently: a low slot confidence asks the
    #: user which group it belongs in, a low attribute confidence just hides a
    #: detail.
    categorisation_confidence: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )

    #: Weighted up when the stylist builds an outfit. The user's own signal, so
    #: it lives beside the garment rather than in a separate preference blob.
    is_favourite: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    #: The cut-out. SET NULL rather than CASCADE: losing the cut-out must never
    #: take the garment with it — the original photograph is still perfectly
    #: usable, and a wardrobe that deletes clothes because a mask expired is
    #: worse than one that shows an untidy background.
    background_removed_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: True when the picture above is a rendering rather than a photograph.
    #:
    #: A garment can be plainly visible in a photo and still impossible to cut
    #: out of it, because something overlaps it. Those are drawn from what was
    #: read off them, and this says so. ``media_assets.kind`` is the authority;
    #: this is denormalised onto the garment so a wardrobe grid can badge every
    #: tile without a join or a request per tile.
    image_is_rendered: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

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
