"""Who follows whom.

The only cross-user relationship this app has, and deliberately the only one
it has for now: a follow carries no text, no image and nothing a person
wrote, so it needs no moderation to be safe to show. Everything else a social
tab usually does — posting, comments, messages — is user-generated content
and waits on a moderation pipeline that does not exist yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (
        # Mirrors the database constraint. Following yourself would put your
        # own saves in your own feed, which makes an empty feed look busy.
        sa.CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
        sa.Index("ix_follows_followee", "followee_id"),
    )

    #: The pair *is* the identity. A surrogate key would allow the same
    #: follow twice and turn "do I follow them" into a count.
    follower_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )
