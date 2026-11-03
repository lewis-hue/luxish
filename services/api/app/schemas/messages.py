"""Direct message shapes."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.direct_message import MAX_MESSAGE


class MessageIn(BaseModel):
    #: Empty is allowed only with a picture: a message has to be one or
    #: the other, and the domain is what decides that.
    body: str = Field(default="", max_length=MAX_MESSAGE)
    #: A picture uploaded under `message_media`. Re-validated against
    #: its owner and its kind before it is attached.
    asset_id: uuid.UUID | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    sent_at: datetime
    #: Written by the reader. Saves every client the same comparison.
    mine: bool
    #: A picture sent with it, if there was one.
    asset_id: uuid.UUID | None = None
    #: `image`, `video` or `audio`: what to draw for `asset_id`.
    #: Null when there is no attachment, or its type is one this app
    #: cannot present.
    media_kind: str | None = None
    #: Whether the other person has seen it. Only ever set on a
    #: message this reader sent; see `domain.messages.Line`.
    read: bool = False


class ThreadOut(BaseModel):
    """One conversation, as its reader sees it."""

    user_id: uuid.UUID
    #: First name only, the same rule as everywhere identity crosses.
    name: str
    handle: str | None = None
    #: Whether this reader follows them, so the empty thread can offer it.
    followed: bool = False
    items: list[MessageOut] = Field(default_factory=list)
    #: This reader's own view of the thread.
    notifies: bool = True
    hidden: bool = False


class ThreadSummaryOut(BaseModel):
    user_id: uuid.UUID
    name: str
    handle: str | None = None
    #: The last thing said, by either of them.
    last: str | None = None
    last_at: datetime | None = None
    unread: int = 0


class ContactOut(BaseModel):
    user_id: uuid.UUID
    name: str
    handle: str | None = None


class MessagesOut(BaseModel):
    """The messages screen in one request.

    Conversations and contacts together: the screen shows both, and two
    round trips to draw one list is one more chance to show it half
    built.
    """

    threads: list[ThreadSummaryOut] = Field(default_factory=list)
    contacts: list[ContactOut] = Field(default_factory=list)


class ThreadSettingsIn(BaseModel):
    notifies: bool | None = None
    hidden: bool | None = None
