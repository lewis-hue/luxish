"""Where a notification is sent, and what is waiting to be sent.

**Two tables, because they answer two different questions.** A device
token is "where this account can be reached right now"; an outbox row
is "this person is owed this message, and not before then". Keeping
them apart is what lets a message survive a phone being replaced, and
lets a phone be forgotten without losing anything anybody is owed.

**Nothing is sent from the request that caused it.** A like, a finished
stylist run or a batch of fresh fits writes an outbox row and returns;
a worker drains it. That is the whole reason a burst of activity
cannot slow the app down, and the reason a vendor being unreachable
delays a notification rather than failing the action behind it.

**The outbox is where throttling and quiet hours live.** `send_after`
holds a row until the device's own small hours have passed, and the
sender takes a bounded number per run, so a fan-out to everybody goes
out over minutes rather than as one spike that the push gateway would
refuse and the app's own servers would then be hit by all at once.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

#: What a queued message is doing.
#:
#: `dropped` is kept rather than deleted so "why did I not get that"
#: has an answer: a muted kind, no device, or a gateway that refused it.
OUTBOX_STATES: tuple[str, ...] = ("queued", "sent", "dropped")

outbox_state_enum = named_enum("push_outbox_state", *OUTBOX_STATES)

#: Which push network a token belongs to. `expo` fronts both APNs and
#: FCM, which is what this app registers through; the other two are
#: here so a direct integration later does not need a migration.
PUSH_PLATFORMS: tuple[str, ...] = ("expo", "apns", "fcm")

push_platform_enum = named_enum("push_platform", *PUSH_PLATFORMS)


class DeviceToken(Base, TimestampMixin):
    """One phone this account can be reached on.

    **The token is the primary key, not a surrogate.** A push token
    addresses one installation, and the same token arriving again is
    the same device - usually the same person signing back in, but
    sometimes a different one on a shared handset. Either way the row
    is updated rather than duplicated, which is also what stops a
    stale row delivering somebody else's notifications to a phone they
    no longer use.
    """

    __tablename__ = "device_tokens"
    __table_args__ = (
        # "Everywhere this account can be reached", which is the only
        # direction the sender reads it in.
        sa.Index("ix_device_tokens_user", "user_id"),
    )

    token: Mapped[str] = mapped_column(sa.String(255), primary_key=True)
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    platform: Mapped[str] = mapped_column(
        push_platform_enum, nullable=False, server_default="expo"
    )
    #: The phone's own IANA zone, sent at registration.
    #:
    #: Stored per device rather than per account because that is where
    #: the fact lives: somebody who travels changes zone without
    #: changing anything about their account, and a second phone left
    #: at home is genuinely in a different one. Null means "unknown",
    #: and a row with no zone is sent without a quiet-hours hold rather
    #: than held for ever.
    timezone: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    #: When this device last said it was still here. A token nothing
    #: has refreshed in months is a reinstall nobody told us about.
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )
    #: Set when the gateway says the token is dead, or on sign-out.
    #: Soft, so a device signing back in is one row again.
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PushOutbox(Base, TimestampMixin):
    """One message somebody is owed.

    Addressed to a *person*, not to a device: which phones they have is
    resolved when it is sent, so a notification queued before a new
    phone was registered still reaches it.
    """

    __tablename__ = "push_outbox"
    __table_args__ = (
        # "What is due now", which is the sender's only query.
        sa.Index("ix_push_outbox_due", "state", "send_after"),
        # "Is this person already owed one of these about this thing",
        # which is how twenty likes become one notification.
        sa.Index("ix_push_outbox_batch", "user_id", "kind", "subject", "state"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: One of `app.domain.notifications.KINDS`, so a muted kind is
    #: never queued and the vocabulary cannot drift from the switches.
    kind: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    #: What this is about - a post id, a run id. Null for a message
    #: about nothing in particular, which therefore never batches.
    subject: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    title: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    body: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    #: Where tapping it should land, as an in-app path.
    deep_link: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    #: How many events this row stands for. Two or more is what turns
    #: "Ada saved your fit" into "Ada and 19 others saved your fit".
    people: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    #: Not before this. Set to the next civil hour this person is
    #: likely to be awake in, in their device's own zone.
    send_after: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )
    state: Mapped[str] = mapped_column(
        outbox_state_enum, nullable=False, default="queued", server_default="queued"
    )
    #: How many times the sender has tried, so a row cannot spin for ever.
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: Why it was dropped, for the same reason a held comment carries one.
    note: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


__all__ = [
    "OUTBOX_STATES",
    "PUSH_PLATFORMS",
    "DeviceToken",
    "PushOutbox",
]
