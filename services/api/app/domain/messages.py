"""Direct messages: threads, what is in them, and who may open one.

**Blocking is the gate, in both directions and at every read.** A
thread with somebody who blocked you resolves to nothing rather than to
an error, for the same reason their page 404s: a distinct answer would
be the disclosure the block exists to prevent.

**A thread is made by sending, not by opening.** Looking at somebody's
empty thread must not put a row on their list; the screen for a
conversation that does not exist yet is a perfectly good screen, and
the first message is what makes it real.

**Hiding is per person and it is not deleting.** Somebody clearing a
conversation off their own list cannot take the other person's copy
with it. A new message brings it back, because the alternative is
messages that silently never arrive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.moderation import has_blocked
from app.models.direct_message import (
    DirectMessageHidden,
    MAX_MESSAGE,
    DirectMessage,
    DirectThread,
    DirectThreadMember,
    pair,
)
from app.models.follow import Follow
from app.models.user import User


class CannotMessage(Exception):
    """No thread with this person, and nothing that says why."""


class EmptyMessage(Exception):
    """Whitespace is not a message."""


@dataclass(frozen=True)
class Line:
    """One message, as a reader sees it."""

    id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    sent_at: datetime
    mine: bool
    #: A picture sent with it, if there was one.
    asset_id: uuid.UUID | None = None
    #: `image`, `video` or `audio` - what to draw for `asset_id`.
    #:
    #: Null when there is no attachment, or when its type is one this
    #: app has no way to present. A client that had only the id had to
    #: guess, and guessing wrong draws a video as a broken picture.
    media_kind: str | None = None
    #: Whether the other person has seen it.
    #:
    #: **Only ever true on a message the reader sent.** Telling
    #: somebody whether the other person has read *their own*
    #: messages is not a receipt, it is reporting on somebody's
    #: reading to them, and the thread already shows them their own.
    read: bool = False


#: What a client has to know to draw an attachment at all.
#:
#: **The kind is a boundary and this is not it.** `message_media`
#: says whose the file is and what it may be used for; this says
#: whether to draw a picture, a player with a scrubber, or a
#: waveform with a play button. A client that knows only the asset id
#: has to guess, and guessing wrong means a video rendered as a
#: broken image.
def media_kind_of(content_type: str | None) -> str | None:
    """`image`, `video`, `audio`, or None when there is nothing to draw."""
    if not content_type:
        return None
    major = content_type.split("/", 1)[0].strip().lower()
    return major if major in {"image", "video", "audio"} else None

@dataclass(frozen=True)
class ThreadSummary:
    """One row on the messages list."""

    user_id: uuid.UUID
    name: str
    handle: str | None
    last: str | None
    last_at: datetime | None
    unread: int


@dataclass(frozen=True)
class Contact:
    """Somebody there is already a reason to write to."""

    user_id: uuid.UUID
    name: str
    handle: str | None


async def _reachable(
    db: AsyncSession, *, viewer_id: uuid.UUID, other_id: uuid.UUID
) -> User | None:
    """The other person, if a thread with them is allowed to exist."""
    if viewer_id == other_id:
        return None
    other = await db.get(User, other_id)
    if other is None or other.deleted_at is not None:
        return None
    if await has_blocked(db, blocker_id=other_id, blocked_id=viewer_id):
        return None
    if await has_blocked(db, blocker_id=viewer_id, blocked_id=other_id):
        return None
    return other


async def _thread(
    db: AsyncSession, *, a: uuid.UUID, b: uuid.UUID
) -> DirectThread | None:
    lower, upper = pair(a, b)
    return await db.scalar(
        sa.select(DirectThread).where(
            DirectThread.lower_id == lower, DirectThread.upper_id == upper
        )
    )


async def _member(
    db: AsyncSession, *, thread_id: uuid.UUID, user_id: uuid.UUID
) -> DirectThreadMember:
    found = await db.get(DirectThreadMember, (thread_id, user_id))
    if found is None:
        found = DirectThreadMember(thread_id=thread_id, user_id=user_id)
        db.add(found)
        await db.flush()
    return found


def _name(user: User) -> str:
    """First name only, the same rule as everywhere identity crosses."""
    from app.domain.community import first_name

    return first_name(user)


async def _handle(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    from app.models.profile import Profile

    return await db.scalar(
        sa.select(Profile.handle).where(
            Profile.user_id == user_id, Profile.deleted_at.is_(None)
        )
    )


class BadAttachment(Exception):
    """Not their picture, or not a picture meant for a message."""


async def send(
    db: AsyncSession,
    *,
    sender_id: uuid.UUID,
    to_id: uuid.UUID,
    body: str,
    asset_id: uuid.UUID | None = None,
) -> Line:
    """Write to somebody. The thread is made here if there was none.

    Not screened, deliberately. Everything shown to strangers takes the
    fail-closed path; this is shown to one person who can block the
    sender in two taps. The deterministic pre-screen would also be
    wrong here - it refuses phone numbers and links, which is half of
    what people arranging to buy a jacket need to send.
    """
    text = (body or "").strip()[:MAX_MESSAGE]
    if not text and asset_id is None:
        raise EmptyMessage()

    other = await _reachable(db, viewer_id=sender_id, other_id=to_id)
    if other is None:
        raise CannotMessage()

    if asset_id is not None:
        # Theirs, and the right kind. Checking the owner alone would let
        # anybody route one of their own garment photographs or avatar
        # sources through a thread, which is the boundary the kind
        # exists to draw.
        from app.models.media_asset import MediaAsset

        picture = await db.get(MediaAsset, asset_id)
        if (
            picture is None
            or picture.user_id != sender_id
            or picture.kind != "message_media"
            or picture.deleted_at is not None
        ):
            raise BadAttachment()

    thread = await _thread(db, a=sender_id, b=to_id)
    if thread is None:
        lower, upper = pair(sender_id, to_id)
        thread = DirectThread(lower_id=lower, upper_id=upper)
        db.add(thread)
        await db.flush()

    now = datetime.now(UTC)
    message = DirectMessage(
        thread_id=thread.id,
        sender_id=sender_id,
        body=text,
        media_asset_id=asset_id,
    )
    db.add(message)
    thread.last_message_at = now

    # The sender has read their own message by definition, and a thread
    # the recipient hid comes back - a hidden conversation that silently
    # swallowed new messages would be a delivery failure wearing a
    # preference.
    mine = await _member(db, thread_id=thread.id, user_id=sender_id)
    mine.last_read_at = now
    mine.hidden_at = None
    theirs = await _member(db, thread_id=thread.id, user_id=to_id)
    theirs.hidden_at = None

    await db.commit()
    await db.refresh(message)

    # Muting the thread wins over the global switch.
    #
    # `notifies` is a choice about this conversation and the toggle is
    # a choice about messages in general; the specific one is the one
    # somebody made about this person, so it is checked first and is
    # allowed to say no on its own.
    if theirs.notifies:
        from app.domain import push

        sender = await db.get(User, sender_id)
        who = (sender.display_name or "Somebody") if sender else "Somebody"
        await push.notify(
            db,
            user_id=to_id,
            kind="message",
            title=who,
            # The message itself, which is what a person wants on a
            # lock screen - and already visible to whoever holds this
            # phone, since the thread is one tap away.
            body=text or "Sent you a picture.",
            # The thread, so a flurry is one notification per
            # conversation rather than one per line.
            subject=str(thread.id),
            deep_link=f"/messages/{sender_id}",
        )

    return Line(
        id=message.id,
        sender_id=sender_id,
        body=message.body,
        sent_at=message.created_at,
        mine=True,
        asset_id=message.media_asset_id,
    )


async def thread_with(
    db: AsyncSession,
    *,
    viewer_id: uuid.UUID,
    other_id: uuid.UUID,
    limit: int = 200,
) -> tuple[User, list[Line]] | None:
    """The conversation with one person, oldest first.

    None covers "no such account", "they blocked you" and "you blocked
    them" indistinguishably. An empty list is a different thing and a
    normal one: it is a conversation nobody has started.
    """
    other = await _reachable(db, viewer_id=viewer_id, other_id=other_id)
    if other is None:
        return None
    thread = await _thread(db, a=viewer_id, b=other_id)
    if thread is None:
        return other, []

    member = await db.get(DirectThreadMember, (thread.id, viewer_id))
    query = sa.select(DirectMessage).where(
        DirectMessage.thread_id == thread.id,
        DirectMessage.deleted_at.is_(None),
    )
    # Everything this reader cleared stays cleared. Their copy only:
    # the same rows are still in the other person's conversation.
    if member is not None and member.cleared_at is not None:
        query = query.where(DirectMessage.created_at > member.cleared_at)
    rows = list(
        await db.scalars(query.order_by(DirectMessage.created_at.asc()).limit(limit))
    )
    # Anything this reader has taken out of their own copy. The same
    # rows are still in the other person's conversation: hiding a
    # message is a choice about looking, not an edit to what was said.
    hidden = set(
        (
            await db.scalars(
                sa.select(DirectMessageHidden.message_id).where(
                    DirectMessageHidden.user_id == viewer_id,
                    DirectMessageHidden.message_id.in_([row.id for row in rows]),
                )
            )
        ).all()
    ) if rows else set()
    rows = [row for row in rows if row.id not in hidden]
    # **When they last looked, so a sent message can say it arrived.**
    #
    # Only ever applied to messages the viewer sent. Telling somebody
    # whether the *other* person has read their own messages is not a
    # receipt, it is surveillance of somebody else's reading, and the
    # thread already shows them their own.
    theirs = await db.get(DirectThreadMember, (thread.id, other_id))
    seen_until = theirs.last_read_at if theirs is not None else None

    # One query for every attachment in the thread, never one per
    # bubble. Without the type a client cannot tell a video from a
    # photograph and draws the first frame of one as a broken image.
    from app.models.media_asset import MediaAsset

    attached = [row.media_asset_id for row in rows if row.media_asset_id]
    types: dict[uuid.UUID, str | None] = (
        {
            asset_id: content_type
            for asset_id, content_type in (
                await db.execute(
                    sa.select(MediaAsset.id, MediaAsset.content_type).where(
                        MediaAsset.id.in_(attached)
                    )
                )
            ).all()
        }
        if attached
        else {}
    )

    return other, [
        Line(
            id=row.id,
            sender_id=row.sender_id,
            body=row.body,
            sent_at=row.created_at,
            mine=row.sender_id == viewer_id,
            asset_id=row.media_asset_id,
            media_kind=media_kind_of(types.get(row.media_asset_id))
            if row.media_asset_id
            else None,
            read=(
                row.sender_id == viewer_id
                and seen_until is not None
                and row.created_at <= seen_until
            ),
        )
        for row in rows
    ]


async def hide_for_me(
    db: AsyncSession, *, user_id: uuid.UUID, message_id: uuid.UUID
) -> bool:
    """Take one message out of your own copy. Idempotent.

    **The other half of `unsend`, and deliberately a different act.**
    Unsending belongs to whoever wrote the message and removes it
    from both conversations - which is right for taking back
    something you said, and is the only delete a sender should have.
    A person who *received* something they would rather not scroll
    past again had nothing: the whole thread could be cleared and one
    message could not.

    Changes one reader's view and nothing else. The sender's copy is
    untouched, the row is untouched, and a report still finds it. The
    other person is not told, because there is nothing for them to
    know: somebody choosing not to look at something is not an event
    in their conversation.

    False when the message is not in a thread they are in - the same
    answer as "no such message", because a different one would
    confirm that somebody else's message exists.
    """
    message = await db.get(DirectMessage, message_id)
    if message is None:
        return False
    member = await db.get(DirectThreadMember, (message.thread_id, user_id))
    if member is None:
        return False
    if await db.get(DirectMessageHidden, (message_id, user_id)) is not None:
        return True
    db.add(DirectMessageHidden(message_id=message_id, user_id=user_id))
    await db.commit()
    return True

async def mark_read(
    db: AsyncSession, *, viewer_id: uuid.UUID, other_id: uuid.UUID
) -> None:
    thread = await _thread(db, a=viewer_id, b=other_id)
    if thread is None:
        return
    member = await _member(db, thread_id=thread.id, user_id=viewer_id)
    member.last_read_at = datetime.now(UTC)
    await db.commit()


async def set_hidden(
    db: AsyncSession, *, viewer_id: uuid.UUID, other_id: uuid.UUID, hidden: bool
) -> None:
    thread = await _thread(db, a=viewer_id, b=other_id)
    if thread is None:
        return
    member = await _member(db, thread_id=thread.id, user_id=viewer_id)
    member.hidden_at = datetime.now(UTC) if hidden else None
    await db.commit()


async def set_notifies(
    db: AsyncSession, *, viewer_id: uuid.UUID, other_id: uuid.UUID, notifies: bool
) -> None:
    thread = await _thread(db, a=viewer_id, b=other_id)
    if thread is None:
        return
    member = await _member(db, thread_id=thread.id, user_id=viewer_id)
    member.notifies = bool(notifies)
    await db.commit()


async def settings_for(
    db: AsyncSession, *, viewer_id: uuid.UUID, other_id: uuid.UUID
) -> tuple[bool, bool]:
    """`(notifies, hidden)` for this reader. Defaults for no thread."""
    thread = await _thread(db, a=viewer_id, b=other_id)
    if thread is None:
        return True, False
    member = await db.get(DirectThreadMember, (thread.id, viewer_id))
    if member is None:
        return True, False
    return bool(member.notifies), member.hidden_at is not None


async def threads(
    db: AsyncSession, *, user_id: uuid.UUID, limit: int = 100
) -> list[ThreadSummary]:
    """Every conversation this person has, most recent first.

    Blocks apply at read time rather than by deleting rows: a block is
    reversible, and a thread that came back empty afterwards would have
    thrown away what both people wrote.
    """
    from app.domain.moderation import hidden_either_way

    hidden_people = await hidden_either_way(db, user_id=user_id)

    rows = list(
        await db.scalars(
            sa.select(DirectThread)
            .where(
                sa.or_(
                    DirectThread.lower_id == user_id,
                    DirectThread.upper_id == user_id,
                ),
                DirectThread.last_message_at.is_not(None),
            )
            .order_by(DirectThread.last_message_at.desc())
            .limit(limit)
        )
    )
    if not rows:
        return []

    members = {
        (member.thread_id, member.user_id): member
        for member in await db.scalars(
            sa.select(DirectThreadMember).where(
                DirectThreadMember.thread_id.in_([row.id for row in rows])
            )
        )
    }

    out: list[ThreadSummary] = []
    for thread in rows:
        other_id = (
            thread.upper_id if thread.lower_id == user_id else thread.lower_id
        )
        if other_id in hidden_people:
            continue
        mine = members.get((thread.id, user_id))
        if mine is not None and mine.hidden_at is not None:
            # Hidden, and nothing has arrived since to bring it back.
            if (
                thread.last_message_at is not None
                and thread.last_message_at <= mine.hidden_at
            ):
                continue
        other = await db.get(User, other_id)
        if other is None or other.deleted_at is not None:
            continue

        cleared = mine.cleared_at if mine is not None else None
        latest = sa.select(DirectMessage.body, DirectMessage.media_asset_id).where(
            DirectMessage.thread_id == thread.id,
            DirectMessage.deleted_at.is_(None),
        )
        if cleared is not None:
            latest = latest.where(DirectMessage.created_at > cleared)
        newest = (
            await db.execute(latest.order_by(DirectMessage.created_at.desc()).limit(1))
        ).first()
        # Cleared and nothing since: the row is gone from this list
        # rather than standing there empty.
        if newest is None:
            continue
        # A picture with no words still has to say something on the
        # list, or the row reads as an empty conversation.
        last = None
        if newest is not None:
            last = newest[0] or ("Photo" if newest[1] else None)
        since = mine.last_read_at if mine is not None else None
        unread_query = sa.select(sa.func.count()).where(
            DirectMessage.thread_id == thread.id,
            DirectMessage.deleted_at.is_(None),
            DirectMessage.sender_id != user_id,
        )
        if since is not None:
            unread_query = unread_query.where(DirectMessage.created_at > since)
        if cleared is not None:
            unread_query = unread_query.where(DirectMessage.created_at > cleared)
        unread = int(await db.scalar(unread_query) or 0)

        out.append(
            ThreadSummary(
                user_id=other_id,
                name=_name(other),
                handle=await _handle(db, other_id),
                last=last,
                last_at=thread.last_message_at,
                unread=unread,
            )
        )
    return out


async def contacts(
    db: AsyncSession, *, user_id: uuid.UUID, limit: int = 50
) -> list[Contact]:
    """People there is already a reason to write to.

    Everyone connected to this account in either direction: following
    somebody is a reason to ask them something, and being followed by
    somebody is a reason to answer. Ordered by name, because a contact
    list is scanned for one person rather than read.
    """
    from app.domain.moderation import hidden_either_way

    hidden = await hidden_either_way(db, user_id=user_id)
    connected = sa.union(
        sa.select(Follow.followee_id.label("id")).where(
            Follow.follower_id == user_id
        ),
        sa.select(Follow.follower_id.label("id")).where(
            Follow.followee_id == user_id
        ),
    )
    people = list(
        await db.scalars(
            sa.select(User)
            .where(
                User.id.in_(sa.select(connected.subquery().c.id)),
                User.deleted_at.is_(None),
                User.id.not_in(hidden) if hidden else sa.true(),
            )
            .order_by(User.display_name)
            .limit(limit)
        )
    )
    return [
        Contact(
            user_id=person.id,
            name=_name(person),
            handle=await _handle(db, person.id),
        )
        for person in people
    ]


async def unsend(
    db: AsyncSession, *, user_id: uuid.UUID, message_id: uuid.UUID
) -> bool:
    """Take back a message you sent. False when it is not yours to take.

    **Both copies, because the message is yours.** A delete that left
    it standing in their conversation would be a button that lies.
    Tombstoned rather than erased, like every other user-owned row
    here: a thread that silently rewrites itself is worse than one
    with a gap, and a moderation record has to survive the delete.
    """
    message = await db.get(DirectMessage, message_id)
    if message is None or message.deleted_at is not None:
        return False
    if message.sender_id != user_id:
        return False
    message.deleted_at = datetime.now(UTC)
    await db.commit()
    return True


async def clear(
    db: AsyncSession, *, viewer_id: uuid.UUID, other_id: uuid.UUID
) -> None:
    """Delete this conversation, for this person only.

    **Their copy is theirs.** Clearing yours draws a line under what
    you have seen; it does not reach into somebody else's phone and
    take back what they were sent. Anything that arrives afterwards
    arrives normally, because clearing a thread is not a way to stop
    hearing from somebody - blocking is.
    """
    thread = await _thread(db, a=viewer_id, b=other_id)
    if thread is None:
        return
    member = await _member(db, thread_id=thread.id, user_id=viewer_id)
    now = datetime.now(UTC)
    member.cleared_at = now
    member.hidden_at = now
    member.last_read_at = now
    await db.commit()


async def attachment_is_in_a_thread_with(
    db: AsyncSession, *, viewer_id: uuid.UUID, asset_id: uuid.UUID
) -> bool:
    """Whether this reader is in the conversation a picture was sent in.

    What makes a message attachment readable by its recipient without
    making it readable by anybody holding the id. Asked per request
    rather than flagged on the asset, for the same reason a published
    fit's media is: every way a picture stops being reachable - the
    message deleted, the thread blocked away - is a change somewhere
    else, and a flag would have to be reset on all of them.
    """
    thread_id = await db.scalar(
        sa.select(DirectMessage.thread_id).where(
            DirectMessage.media_asset_id == asset_id,
            DirectMessage.deleted_at.is_(None),
        )
    )
    if thread_id is None:
        return False
    thread = await db.get(DirectThread, thread_id)
    if thread is None:
        return False
    if viewer_id not in (thread.lower_id, thread.upper_id):
        return False
    other = thread.upper_id if thread.lower_id == viewer_id else thread.lower_id
    return await _reachable(db, viewer_id=viewer_id, other_id=other) is not None


__all__ = [
    "BadAttachment",
    "CannotMessage",
    "Contact",
    "EmptyMessage",
    "Line",
    "ThreadSummary",
    "attachment_is_in_a_thread_with",
    "clear",
    "contacts",
    "mark_read",
    "send",
    "set_hidden",
    "set_notifies",
    "settings_for",
    "thread_with",
    "threads",
    "unsend",
]
