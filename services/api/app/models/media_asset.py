"""Media assets and their derivatives.

``version`` is the concurrency token Task 6's ``guard_write`` compares against:
a worker that computed derivatives from version 3 must not write them after the
user has replaced the original and moved it to version 4.

``publication_consent`` is per-asset and defaults to false — private by
default, publication is always a separate explicit act.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

#: ``garment_render`` is a picture of a garment that is not a photograph of it.
#: It exists because a garment can be plainly visible and still impossible to
#: cut out — something overlaps it and the mask comes back as a fragment — so
#: the alternative is showing the user a shirt with a bag-shaped hole in it.
#: Kept as its own kind rather than passed off as a photo: a render is not
#: evidence of what somebody owns, and nothing downstream should treat it as
#: though it were.
#: ``avatar_source`` is a photograph somebody uploaded **of themselves**,
#: so an avatar can be built that actually looks like them. Its own kind
#: for three reasons, each of which would otherwise be a quiet mistake:
#: it is a picture of a person and must never be mistaken for evidence of
#: a garment; nothing that scans for clothes should pick it up; and
#: deleting it has to be findable, because "remove the photo of my face"
#: is a request somebody will make and it must not require knowing an id.
#: ``profile_banner`` is the picture across the top of somebody's page.
#: Decoration, shown to everybody who opens the profile, and therefore
#: screened like a caption. Its own kind so nothing that reads clothes
#: or faces picks it up: a skyline is neither.
#: ``garment_studio`` is an edit of the owner's own garment photograph —
#: the same garment, placed on a model, cut out, or set in a scene. Distinct
#: from ``garment_render``, which is drawn from a description when a cut-out
#: fails, and distinct from ``garment_photo``, which is the evidence of what
#: somebody owns. A studio shot is neither: it is a derivative, and nothing
#: downstream should feed it back in as a source.
MEDIA_KINDS = (
    "garment_photo",
    "outfit_photo",
    "inspiration",
    "avatar",
    "avatar_source",
    "profile_banner",
    "garment_render",
    "garment_studio",
    #: A picture somebody attached to a message. Private to the two
    #: people in that thread, and never read for clothes: a photograph
    #: sent to one person is not evidence of anything they own.
    "message_media",
)
MEDIA_STATUSES = ("pending_upload", "uploaded", "processing", "ready", "failed")
DERIVATIVE_KINDS = ("thumbnail", "display", "mask", "preview")

media_kind_enum = named_enum("media_kind", *MEDIA_KINDS)
media_status_enum = named_enum("media_asset_status", *MEDIA_STATUSES)
derivative_kind_enum = named_enum("media_derivative_kind", *DERIVATIVE_KINDS)


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    kind: Mapped[str] = mapped_column(media_kind_enum, nullable=False)
    status: Mapped[str] = mapped_column(
        media_status_enum, nullable=False, default="pending_upload", server_default="pending_upload"
    )
    content_type: Mapped[str] = mapped_column(sa.String(127), nullable=False)
    #: What the client declared, and what we authorised it to send.
    max_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    byte_size: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Bumped whenever the underlying bytes change; see Task 6's guard_write.
    version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=1, server_default=sa.text("1")
    )
    publication_consent: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    upload_authorized_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    derivatives: Mapped[list[MediaDerivative]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class MediaDerivative(Base, TimestampMixin):
    """A worker-produced rendition. Written only through Task 6's guard."""

    __tablename__ = "media_derivatives"
    __table_args__ = (
        sa.UniqueConstraint(
            "asset_id", "kind", "source_version", name="uq_media_derivatives_asset_id_kind_source_version"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    asset_id: Mapped[uuid.UUID] = uuid_fk("media_assets.id")
    kind: Mapped[str] = mapped_column(derivative_kind_enum, nullable=False)
    storage_key: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(sa.String(127), nullable=False)
    byte_size: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: The asset version these bytes were derived from.
    source_version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)

    asset: Mapped[MediaAsset] = relationship(back_populates="derivatives")
