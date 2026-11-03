"""Inbox routes.

Two endpoints and no writes anywhere else in the service, because the inbox is
derived from what already happened rather than written alongside it. See
:mod:`app.domain.notifications` for why that trade was made and what it costs.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthDep, SessionDep
from app.domain import notification_prefs
from app.domain import notifications as domain
from app.schemas.notifications import (
    InboxResponse,
    MarkReadOut,
    NotificationOut,
    NotificationPrefsOut,
    NotificationPrefsPatch,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=InboxResponse)
async def read_inbox(db: SessionDep, ctx: AuthDep) -> InboxResponse:
    """What happened while you were away, newest first.

    An empty list is a real answer. Nothing here manufactures an item to
    avoid an empty screen.
    """
    items, unread = await domain.inbox(db, user_id=ctx.user_id)
    return InboxResponse(
        items=[
            NotificationOut(
                kind=item.kind,  # type: ignore[arg-type]
                occurred_at=item.occurred_at,
                title=item.title,
                body=item.body,
                target=item.target,
                people=item.people,
            )
            for item in items
        ],
        unread=unread,
        window_days=domain.INBOX_DAYS,
    )


@router.post("/read", response_model=MarkReadOut)
async def mark_read(db: SessionDep, ctx: AuthDep) -> MarkReadOut:
    """Move the read watermark to now.

    Monotonic: a device that opens the inbox after another one cannot
    un-read what the first already saw.
    """
    at = await domain.mark_read(db, user_id=ctx.user_id)
    return MarkReadOut(read_at=at)


@router.get("/preferences", response_model=NotificationPrefsOut)
async def read_preferences(db: SessionDep, ctx: AuthDep) -> NotificationPrefsOut:
    """Every notification toggle, with defaults resolved.

    A fresh account gets all-on without a row existing, so the settings
    screen never has to invent a default of its own.
    """
    prefs = await notification_prefs.read_prefs(db, user_id=ctx.user_id)
    return NotificationPrefsOut(**prefs)


@router.patch("/preferences", response_model=NotificationPrefsOut)
async def write_preferences(
    payload: NotificationPrefsPatch, db: SessionDep, ctx: AuthDep
) -> NotificationPrefsOut:
    """Flip the toggles present in the body and return the full set.

    Partial like the profile PATCH: absent means untouched. A muted inbox
    kind stops appearing in `GET /v1/notifications` from the next read.
    """
    changes = payload.model_dump(exclude_none=True)
    prefs = await notification_prefs.write_prefs(
        db, user_id=ctx.user_id, changes=changes
    )
    return NotificationPrefsOut(**prefs)
