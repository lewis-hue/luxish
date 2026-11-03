"""Blocks and reports: the two controls a social surface must ship with.

Both store policies make these preconditions for user-generated content
rather than features of it: Apple's guideline 1.2 requires "the ability to
block abusive users" and "a mechanism to report offensive content", and
Google Play's UGC policy requires an in-app system for reporting and
blocking. They land before any composer does, because a publish button
without them is a store rejection, not a backlog item.

**A block is a fact about two people**, like a follow, and gets the same
shape: the pair is the primary key, so blocking twice is a no-op by schema
and "have I blocked them" is a lookup rather than a count.

**A report is a record addressed to a human.** Nothing automated acts on
one; the row holds what was said and about whom, and it waits for the
moderation console (`apps/admin`, planned) to read it. The reasons are a
closed vocabulary so the queue can be sorted by something.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

#: What a report can be about. ``account`` points at a user, ``post`` at a
#: published fit, and ``comment`` at a remark under one.
#:
#: ``look`` is kept here and nowhere else. The catalogue it named is gone
#: and the API no longer accepts it, but reports already filed against one
#: are moderation records - evidence a person may still need to read - and
#: narrowing the stored vocabulary would make those rows unloadable.
REPORT_SUBJECTS: tuple[str, ...] = ("account", "look", "post", "comment")

REPORT_REASONS: tuple[str, ...] = (
    "impersonation",
    "inappropriate",
    "spam",
    "other",
)

#: ``open`` until a person closes it. There is no automated resolution.
REPORT_STATES: tuple[str, ...] = ("open", "resolved")

report_subject_enum = named_enum("report_subject", *REPORT_SUBJECTS)
report_reason_enum = named_enum("report_reason", *REPORT_REASONS)
report_state_enum = named_enum("report_state", *REPORT_STATES)


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (
        # Blocking yourself is not a harmless oddity: it would filter your
        # own saves out of your own surfaces and read as data loss.
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_blocks_not_self"),
        sa.Index("ix_blocks_blocked", "blocked_id"),
    )

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    reporter_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    subject_kind: Mapped[str] = mapped_column(report_subject_enum, nullable=False)
    #: Which community guideline the reporter says was broken.
    #:
    #: Text rather than an enum, and separate from `reason`: the coarse
    #: reason is what the moderation queue sorts by and must stay
    #: stable, while a guideline may be reworded or retired without
    #: invalidating the reports that cited it.
    guideline_id: Mapped[str | None] = mapped_column(
        sa.String(40), nullable=True
    )
    #: ``SET NULL`` so purging a reported account does not erase the record
    #: that it was reported — the report is about the event, not the row.
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The look id for a ``look`` report. A string from the app's own
    #: taxonomy, never free text.
    subject_ref: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    reason: Mapped[str] = mapped_column(report_reason_enum, nullable=False)
    #: The reporter's own words, capped. Read by a human, shown to no one
    #: else, and stored exactly as written.
    note: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    state: Mapped[str] = mapped_column(
        report_state_enum, nullable=False, default="open", server_default="open"
    )
