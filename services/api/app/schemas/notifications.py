"""Inbox request and response shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.notifications import KINDS

#: Every kind the inbox can produce, taken from the one place that
#: decides it.
#:
#: **It was a hand-copied literal and it drifted, with a 500 at the
#: end of it.** `studio_ready` and `render_ready` were added to
#: `domain.notifications.KINDS` when background work started telling
#: people it had finished; this list was not touched, so the moment
#: either kind reached a real inbox the response failed to serialise:
#:
#:     ValidationError: 1 validation error for NotificationOut
#:     kind: Input should be 'wardrobe_sorted', 'stylist_ready' or
#:     'fit_reactions' [input_value='render_ready']
#:
#: Which is to say the feature that tells somebody their picture is
#: ready took their inbox down instead. Derived now, so adding a kind
#: in one place cannot leave the other behind.
Kind = Literal[KINDS]  # type: ignore[valid-type]


class NotificationOut(BaseModel):
    kind: Kind
    occurred_at: datetime
    title: str
    body: str
    #: An app route, or null when the inbox itself is the destination.
    target: str | None = None
    #: How many distinct people a cross-user item rests on. Null otherwise,
    #: so a client cannot accidentally render a count that means nothing.
    people: int | None = None


class InboxResponse(BaseModel):
    items: list[NotificationOut]
    #: Since the last time this person looked.
    unread: int
    #: How far back the inbox reaches, so a client can say so rather than
    #: implying the list is everything that ever happened.
    window_days: int


class MarkReadOut(BaseModel):
    read_at: datetime


class NotificationPrefsOut(BaseModel):
    """Every toggle, resolved. Defaults are filled in server-side, so the
    client renders what is true rather than re-deriving it."""

    wardrobe_sorted: bool
    stylist_ready: bool
    fit_reactions: bool
    #: Honoured by the device, stored here so it survives a reinstall. The
    #: server never sends a plan reminder and cannot cancel one.
    plan_reminders: bool


class NotificationPrefsPatch(BaseModel):
    """A partial update. Absent means untouched, so one flipped switch
    cannot quietly reset the others."""

    wardrobe_sorted: bool | None = None
    stylist_ready: bool | None = None
    fit_reactions: bool | None = None
    plan_reminders: bool | None = None
