"""Consent records.

Private by default: wardrobes and conversations are private, and publication to
the community is always a separate, explicit, revocable act. Task 6's
``guard_write`` reads ``publication`` consent in the same transaction as the
write, so a consent withdrawn mid-job stops the publish.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

CONSENT_KINDS = (
    "publication",
    "ai_processing",
    "location_precise",
    "location_coarse",
    "analytics",
    #: Letting other people see what you have saved.
    #:
    #: Saving a look is a private act — the Saved screen is a personal shelf
    #: and nothing ever said otherwise. Two things read it across accounts
    #: and both wait on this grant: the community feed, and the count of
    #: shared saves on a suggestion card. The second is the subtler one,
    #: because it is an aggregate rather than a list and still enumerates a
    #: collection exactly when the caller controls one side of the
    #: comparison. Absent means no.
    "community_sharing",
    #: Sending a photograph of yourself to a model, to build an avatar
    #: that looks like you.
    #:
    #: Separate from `ai_processing`, which covers reading a wardrobe and
    #: writing an outfit. A face is not a jumper: somebody can reasonably
    #: want the stylist and not want their likeness generated, and one
    #: grant standing in for the other would make that impossible to say.
    #: Absent means no, and withdrawing it stops further generation.
    "likeness",
)

consent_kind_enum = named_enum("consent_kind", *CONSENT_KINDS)


class Consent(Base, TimestampMixin):
    __tablename__ = "consents"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "kind", name="uq_consents_user_id_kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    kind: Mapped[str] = mapped_column(consent_kind_enum, nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: How the grant was obtained, so a UI can explain it later.
    source: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    @property
    def is_granted(self) -> bool:
        return self.granted_at is not None and self.revoked_at is None
