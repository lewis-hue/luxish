"""Messages between two people.

**Named for what they are, beside the stylist's own `Conversation`.** The
assistant already owns `conversations` and `messages`; a thread between
two people is a different thing with different rules, so it is
`direct_threads` and `direct_messages` rather than a flag on the other.

**Two people, in a fixed order.** A thread is addressed by the pair, so
the pair is stored sorted and made unique. Without that, two people
opening each other at the same moment create two threads and each sees
half the conversation.

**Not screened, and that is the considered position.** Everything this
app shows to strangers goes through a fail-closed screen; a direct
message is not shown to strangers. The deterministic pre-screen would
be actively wrong here - it refuses phone numbers and links, which is
exactly what somebody arranging to buy a jacket needs to send. The
controls for a message are the ones that were always the condition for
shipping messages at all: blocking, which is immediate and severs the
thread, and reporting, which a person reads.

**Each side has its own view of the thread.** Read position, whether
it is hidden, and whether it notifies are facts about one participant,
so they live in a per-member row rather than as two columns of each
kind on the thread.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, uuid_fk, uuid_pk

#: The longest a single message may be.
#:
#: Generous next to a comment, which is a remark under a photograph.
#: This is a conversation, and a limit that cuts people off mid-sentence
#: makes them send three messages instead of one.
MAX_MESSAGE = 2000


def pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """The two people in the order a thread stores them.

    Sorted, so "me and them" and "them and me" address one row. The
    uniqueness constraint is what this exists to satisfy.
    """
    return (a, b) if str(a) < str(b) else (b, a)


class DirectThread(Base, TimestampMixin):
    __tablename__ = "direct_threads"
    __table_args__ = (
        sa.UniqueConstraint("lower_id", "upper_id", name="uq_direct_threads_pair"),
        # "Their threads, most recent first" - the list screen's only query.
        sa.Index("ix_direct_threads_lower_active", "lower_id", "last_message_at"),
        sa.Index("ix_direct_threads_upper_active", "upper_id", "last_message_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: The pair, sorted. See :func:`pair`.
    lower_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    upper_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: Denormalised so the list can order without touching every message.
    last_message_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )


class DirectMessage(Base, TimestampMixin):
    __tablename__ = "direct_messages"
    __table_args__ = (
        # "This thread, oldest first" - the only order a conversation reads in.
        sa.Index("ix_direct_messages_thread_created", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    thread_id: Mapped[uuid.UUID] = uuid_fk("direct_threads.id")
    sender_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    body: Mapped[str] = mapped_column(sa.String(MAX_MESSAGE), nullable=False)
    #: A picture sent with it, uploaded under `message_media`.
    #:
    #: `SET NULL` rather than cascade: deleting the photograph must
    #: not delete the message that was sent with it, any more than
    #: deleting a profile picture deletes the profile.
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Tombstoned rather than erased, like every other user-owned row
    #: here: a thread that silently rewrites itself is worse than one
    #: with a gap in it, and a moderation record has to survive a delete.
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DirectThreadMember(Base, TimestampMixin):
    """One participant's own view of a thread."""

    __tablename__ = "direct_thread_members"
    __table_args__ = (
        sa.PrimaryKeyConstraint("thread_id", "user_id"),
        sa.Index("ix_direct_thread_members_user", "user_id"),
    )

    thread_id: Mapped[uuid.UUID] = uuid_fk("direct_threads.id")
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: Everything before this is read. A watermark rather than a flag
    #: per message: the question is only ever "anything new?".
    last_read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Off their list until something new arrives. Hiding is not
    #: deleting: the other person's copy is theirs.
    hidden_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Everything before this is gone, for this person only.
    #:
    #: A watermark rather than a delete, because the other half of the
    #: conversation is the other person's and clearing yours cannot
    #: reach into theirs. Anything sent afterwards arrives normally -
    #: clearing a thread is not a way to stop hearing from somebody,
    #: which is what blocking is for.
    cleared_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Whether a new message here notifies them.
    notifies: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )


class DirectMessageHidden(Base):
    """One person has taken one message out of their own copy.

    **Not an unsend.** Unsending belongs to whoever wrote the message
    and removes it from both conversations; this belongs to whoever
    is reading and removes it from theirs. The row stays, the other
    person's thread is unchanged, and a moderation report still finds
    it - what changes is one reader's view.

    The pair is the fact, so it is the primary key: hiding the same
    message twice is a no-op rather than a second row.
    """

    __tablename__ = "direct_message_hidden"

    message_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("direct_messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )
