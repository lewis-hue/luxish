"""A copy of everything somebody put into this app, on request.

**Its own table rather than a job payload.** The job record says
whether the work ran; this says what exists to download, who may
download it, and when it stops being downloadable. Those are three
questions about an artifact, and an artifact that contains a person's
whole account is not something to leave addressed only by a row in a
queue table.

**It expires, and that is the point of the column.** An export is the
most sensitive object this system ever writes: one file holding
somebody's wardrobe, their conversations and every picture they own.
A download URL that works forever turns a single leaked link into a
permanent breach, so the row carries its own deadline and the route
refuses past it whatever is still on disk. The same reasoning as the
media route refusing a deleted asset rather than trusting a flag.

**One live export per person at a time.** Building one reads every
picture they own out of object storage, so letting a button queue ten
of them is a way to bill a lot of reads from one tap. A request while
one is already running returns the running one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk
from app.db.types import UTCDateTime

#: How long a finished export stays downloadable.
#:
#: Long enough to be useful on a phone that was not at hand when the
#: notification arrived; short enough that a link copied out of a
#: screenshot is not a standing key to somebody's whole account.
EXPORT_LIFETIME_HOURS = 48

#: What `state` may be. `gathering` is the only one that is not final.
EXPORT_STATES = frozenset({"gathering", "ready", "failed", "expired"})


class AccountExport(Base, TimestampMixin):
    __tablename__ = "account_exports"

    id: Mapped[uuid.UUID] = uuid_pk()

    #: Whose account this is a copy of. The only person who may read it.
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The queued work that builds it, so a stuck export can be traced
    #: back to the job that was meant to finish it.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default="gathering"
    )

    #: Where the archive sits, once there is one.
    storage_key: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)

    #: How many photographs went in, and how many were left out for
    #: size. Recorded because an export that silently dropped half
    #: somebody's wardrobe reads as a complete copy, which is worse
    #: than a short one that says so.
    pictures_included: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=0
    )
    pictures_omitted: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, default=0
    )

    #: Why it failed, in the owner's terms. Null unless `state` is
    #: `failed`.
    failure: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)

    #: When it stops being downloadable. Set when it becomes ready.
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


__all__ = ["EXPORT_LIFETIME_HOURS", "EXPORT_STATES", "AccountExport"]
