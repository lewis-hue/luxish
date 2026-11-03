"""Direct messages.

Addressed by the other person rather than by a thread id: a client
always knows who it is writing to and never has to resolve an id
first, and "the thread with them" is a single row either way.

404 is the answer for every reason a thread cannot exist - no such
account, they blocked you, you blocked them. A distinct status for the
middle case would be the disclosure the block exists to prevent.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import messages as domain
from app.domain.community import first_name
from app.errors import ApiError
from app.models.follow import Follow
from app.schemas.messages import (
    ContactOut,
    MessageIn,
    MessageOut,
    MessagesOut,
    ThreadOut,
    ThreadSettingsIn,
    ThreadSummaryOut,
)

router = APIRouter(prefix="/messages", tags=["messages"])


def _line(line: domain.Line) -> MessageOut:
    return MessageOut(
        id=line.id,
        sender_id=line.sender_id,
        body=line.body,
        sent_at=line.sent_at,
        mine=line.mine,
        asset_id=line.asset_id,
        media_kind=line.media_kind,
        read=line.read,
    )


@router.get("", response_model=MessagesOut)
async def inbox(db: SessionDep, ctx: AuthDep) -> MessagesOut:
    """Conversations, and the people there is a reason to start one with."""
    found = await domain.threads(db, user_id=ctx.user_id)
    people = await domain.contacts(db, user_id=ctx.user_id)
    return MessagesOut(
        threads=[
            ThreadSummaryOut(
                user_id=item.user_id,
                name=item.name,
                handle=item.handle,
                last=item.last,
                last_at=item.last_at,
                unread=item.unread,
            )
            for item in found
        ],
        contacts=[
            ContactOut(user_id=person.user_id, name=person.name, handle=person.handle)
            for person in people
        ],
    )


@router.get("/{user_id}", response_model=ThreadOut)
async def thread(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> ThreadOut:
    """The conversation with one person, oldest first.

    An empty list is a normal answer: a conversation nobody has started
    is a perfectly good screen, and opening it must not put a row on
    the other person's list.
    """
    found = await domain.thread_with(
        db, viewer_id=ctx.user_id, other_id=user_id
    )
    if found is None:
        raise ApiError(
            "No such account.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        )
    other, lines = found
    notifies, hidden = await domain.settings_for(
        db, viewer_id=ctx.user_id, other_id=user_id
    )
    from app.domain import profiles as profile_domain

    profile = await profile_domain.get(db, user_id=user_id)
    followed = (
        await db.get(Follow, (ctx.user_id, user_id))
    ) is not None
    return ThreadOut(
        user_id=other.id,
        name=first_name(other),
        handle=profile.handle if profile else None,
        followed=followed,
        items=[_line(line) for line in lines],
        notifies=notifies,
        hidden=hidden,
    )


@router.post(
    "/{user_id}", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
async def write(
    user_id: uuid.UUID, payload: MessageIn, db: SessionDep, ctx: AuthDep
) -> MessageOut:
    """Send one message. The thread is created here if there was none."""
    try:
        line = await domain.send(
            db,
            sender_id=ctx.user_id,
            to_id=user_id,
            body=payload.body,
            asset_id=payload.asset_id,
        )
    except domain.EmptyMessage:
        raise ApiError(
            "There is nothing to send.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="empty_message",
        ) from None
    except domain.BadAttachment:
        # The same answer as "no such account": a different one would
        # confirm somebody else's asset id exists.
        raise ApiError(
            "No such picture.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    except domain.CannotMessage:
        raise ApiError(
            "No such account.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        ) from None
    return _line(line)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_thread(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Delete this conversation, for the caller only. 204 either way.

    Their copy is theirs: this draws a line under what you have seen
    rather than reaching into somebody else's phone. 204 whether or
    not a thread exists, so the refusal confirms nothing.
    """
    await domain.clear(db, viewer_id=ctx.user_id, other_id=user_id)


@router.delete(
    "/{user_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unsend(
    user_id: uuid.UUID, message_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> None:
    """Take back one message you sent. 404 when it is not yours.

    Both copies: a message is its sender's, and a delete that left it
    standing in the other person's conversation would be a button that
    lies.
    """
    if not await domain.unsend(db, user_id=ctx.user_id, message_id=message_id):
        raise ApiError(
            "No such message.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )


@router.put(
    "/{user_id}/messages/{message_id}/hide",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def hide(
    user_id: uuid.UUID, message_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> None:
    """Take one message out of your own copy. 404 if it is not yours to see.

    **The other half of unsending, for the person who received it.**
    Unsending is the sender's and removes the message from both
    conversations. This is the reader's and removes it from theirs:
    the sender's copy is untouched, and they are not told, because
    somebody choosing not to look at something is not an event in
    their conversation.

    `PUT`, not `DELETE`: nothing is deleted. It is idempotent, which
    is the other reason - hiding a message twice is the same state.
    """
    if not await domain.hide_for_me(
        db, user_id=ctx.user_id, message_id=message_id
    ):
        raise ApiError(
            "No such message.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )


@router.put("/{user_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Everything up to now is read. 204 whether or not there is a thread."""
    await domain.mark_read(db, viewer_id=ctx.user_id, other_id=user_id)


@router.patch("/{user_id}/settings", response_model=ThreadOut)
async def settings(
    user_id: uuid.UUID,
    payload: ThreadSettingsIn,
    db: SessionDep,
    ctx: AuthDep,
) -> ThreadOut:
    """Notifications and hiding, which are facts about one participant.

    Hiding is not deleting: the other person's copy is theirs, and a
    new message brings this one back rather than being swallowed.
    """
    if payload.notifies is not None:
        await domain.set_notifies(
            db, viewer_id=ctx.user_id, other_id=user_id, notifies=payload.notifies
        )
    if payload.hidden is not None:
        await domain.set_hidden(
            db, viewer_id=ctx.user_id, other_id=user_id, hidden=payload.hidden
        )
    return await thread(user_id, db, ctx)
