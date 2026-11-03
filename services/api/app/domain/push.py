"""Fanning a notification out to the people it is for.

**Nothing here talks to a phone.** This decides *who* is owed *what*
and *when*; `app.workers.push` is the only thing that opens a socket.
Keeping the two apart is what makes a burst of activity cheap - the
request that caused a notification writes rows and returns - and what
makes a gateway outage a delay rather than a failed action.

The pipeline, in the order it runs:

1. **Fan out.** An event names an audience. The audience is resolved
   in chunks, so one popular fit does not become one enormous
   transaction, and each chunk writes outbox rows.
2. **Filter.** A row is only written for somebody whose switches let
   that kind through. The preference is read once per chunk, not once
   per person.
3. **Batch.** If that person is already owed an unsent message about
   the same thing, the existing row's tally goes up instead of a
   second row appearing. Twenty people saving your fit is one
   notification that says twenty.
4. **Hold.** `send_after` is the next hour the device's own clock says
   is a civil one. Nobody is woken at three in the morning to be told
   about a cardigan.
5. **Drain.** The sender takes a bounded number per run, so a fan-out
   to everybody leaves over minutes instead of as one spike.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notification_prefs import read_prefs
from app.models.push import DeviceToken, PushOutbox

logger = logging.getLogger(__name__)

#: How many people one fan-out chunk resolves at a time.
#:
#: A thousand rather than everybody: the work is the same either way,
#: but a chunk commits on its own, so a fan-out that fails part-way
#: has delivered what it already wrote rather than rolling back the
#: lot. It also keeps one transaction off a table every request reads.
CHUNK = 1_000

#: The most the sender moves in one pass.
#:
#: This is the throttle. A push gateway treats a sudden flood as an
#: attack, and a million people opening the app in the same second
#: because they were all notified at once is a worse outage than the
#: delay this causes. The sender runs often and takes this many each
#: time, which spreads a large fan-out over minutes.
BATCH = 200

#: The hours a non-urgent notification may arrive in, local to the
#: device. Anything queued outside them waits for the next one.
QUIET_UNTIL = time(hour=8)
QUIET_FROM = time(hour=22)

#: How long a registration keeps its claim on a token after the last
#: time the device said it was still there.
#:
#: The ordinary way a handset changes hands is a sign-out, which
#: revokes the row and leaves the token free for the next account.
#: This is the fallback for when that never happened - an app deleted,
#: a phone wiped, a sign-out that failed offline. Past this, a row
#: nothing has refreshed is not evidence that anybody still holds the
#: device, and the next account may claim it.
STALE = timedelta(days=60)


class DeviceClaimed(Exception):
    """This token is already registered, live, to somebody else.

    Raised rather than silently reassigning. Possession of a push
    token is not proof of holding the phone: tokens reach logs, crash
    reports and analytics, and the whole reason `forget_device` checks
    ownership is that one which leaked must not let its holder silence
    somebody else. Reassigning on possession alone would hand that
    straight back - claim the token, then forget it - so the same rule
    applies on the way in.
    """


def civil_time(now: datetime, zone: str | None) -> datetime:
    """The next moment it is reasonable to interrupt somebody.

    `now` when the device is already in its waking hours, otherwise
    the following eight o'clock where that device is.

    **An unknown zone sends immediately rather than waiting.** Holding
    a notification for a clock nobody knows would mean a device that
    never reported one never hears anything at all, which is a worse
    failure than one badly-timed banner.
    """
    if not zone:
        return now
    try:
        here = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        # A zone this machine does not recognise is the same as none.
        return now

    local = now.astimezone(here)
    if QUIET_UNTIL <= local.time() < QUIET_FROM:
        return now

    # Before the morning, wait for it; after the evening, wait for
    # tomorrow's.
    day = local.date() if local.time() < QUIET_UNTIL else local.date() + timedelta(days=1)
    wake = datetime.combine(day, QUIET_UNTIL, tzinfo=here)
    return wake.astimezone(UTC)


def _live(device: DeviceToken, now: datetime) -> bool:
    """Is somebody still reachable on this device, as far as we know.

    Revoked is a definite no - that is what signing out writes. Beyond
    that it is the last time the device checked in: the real owner's
    app refreshes the row on every launch, so an account in use is
    never stale, and one nothing has touched in `STALE` is a handset
    nobody told us about.
    """
    if device.revoked_at is not None:
        return False
    seen = device.last_seen_at
    if seen.tzinfo is None:
        # SQLite hands back naive datetimes; they are written in UTC.
        seen = seen.replace(tzinfo=UTC)
    return now - seen < STALE


async def register_device(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    token: str,
    platform: str = "expo",
    timezone: str | None = None,
) -> DeviceToken:
    """Record where this account can be reached, or refresh it.

    The same token arriving again is the same device, so the row is
    updated rather than duplicated. Re-registering also clears a
    revocation, which is what signing back in means.

    **A token live under another account is refused.** A handset does
    change hands, and that still works: signing out revokes the row,
    and a revoked row is free for whoever signs in next. What is
    refused is taking a token that somebody is *currently* reachable
    on, because the only thing offered in support of the claim is the
    token itself - and a token is secret, not authorizing. Without
    this, anyone who came across one could point it at their own
    account, which both stops its owner's notifications and walks
    straight around `forget_device`'s ownership check.

    There is no race to lose here: a token does not exist until the
    device asks Expo for one, and the device registers it immediately,
    so the first registration is always the real handset.

    Raises `DeviceClaimed` when the token is live under somebody else.
    """
    found = await db.get(DeviceToken, token)
    now = datetime.now(UTC)
    if found is not None and found.user_id != user_id and _live(found, now):
        raise DeviceClaimed(token)
    if found is None:
        found = DeviceToken(
            token=token,
            user_id=user_id,
            platform=platform,
            timezone=timezone,
            last_seen_at=now,
        )
        db.add(found)
    else:
        found.user_id = user_id
        found.platform = platform
        if timezone:
            found.timezone = timezone
        found.last_seen_at = now
        found.revoked_at = None
    await db.commit()
    await db.refresh(found)
    return found


async def forget_device(
    db: AsyncSession, *, token: str, user_id: uuid.UUID
) -> bool:
    """Stop sending to this phone. Idempotent.

    **Only your own.** A token is opaque and long, but that is secrecy
    rather than authorization: anything that leaks one - a log, a
    client bug, a handset passed around - would otherwise let its
    holder silence somebody else's notifications. The row is only
    revoked when it belongs to the person asking.

    Revoked rather than deleted: the same device signing back in
    should be one row, not a second one beside a tombstone. That is
    also why re-registering under a different account reassigns the
    row rather than being refused - the handset changed hands, and
    the new owner is then the one who may forget it.
    """
    found = await db.get(DeviceToken, token)
    if found is None or found.user_id != user_id or found.revoked_at is not None:
        return False
    found.revoked_at = datetime.now(UTC)
    await db.commit()
    return True


async def devices_for(
    db: AsyncSession, *, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[DeviceToken]]:
    """Every live token for these people, by person."""
    if not user_ids:
        return {}
    rows = await db.scalars(
        sa.select(DeviceToken).where(
            DeviceToken.user_id.in_(list(user_ids)),
            DeviceToken.revoked_at.is_(None),
        )
    )
    out: dict[uuid.UUID, list[DeviceToken]] = {}
    for row in rows:
        out.setdefault(row.user_id, []).append(row)
    return out


async def _wants(
    db: AsyncSession, *, user_ids: Sequence[uuid.UUID], kind: str
) -> set[uuid.UUID]:
    """Which of these people have left this kind switched on.

    Read per person because that is how the preference is stored, but
    only once per chunk rather than once per row written.
    """
    allowed: set[uuid.UUID] = set()
    for user_id in user_ids:
        prefs = await read_prefs(db, user_id=user_id)
        if prefs.get(kind, True):
            allowed.add(user_id)
    return allowed


def _chunks(items: Sequence[uuid.UUID], size: int = CHUNK) -> Iterable[Sequence[uuid.UUID]]:
    for at in range(0, len(items), size):
        yield items[at : at + size]


async def fan_out(
    db: AsyncSession,
    *,
    kind: str,
    audience: Sequence[uuid.UUID],
    title: str,
    body: str,
    subject: str | None = None,
    deep_link: str | None = None,
    now: datetime | None = None,
) -> int:
    """Queue one message for everybody it is for. Returns how many.

    Safe to call again with the same `subject`: a person already owed
    an unsent message about it has their tally raised rather than
    gaining a second one. That is both the batching rule and what
    makes a retried job harmless.
    """
    moment = now or datetime.now(UTC)
    written = 0

    for chunk in _chunks(list(dict.fromkeys(audience))):
        wanted = await _wants(db, user_ids=chunk, kind=kind)
        if not wanted:
            continue

        # What each of them is already owed about this, so twenty
        # events become one row that says twenty.
        existing: dict[uuid.UUID, PushOutbox] = {}
        if subject is not None:
            rows = await db.scalars(
                sa.select(PushOutbox).where(
                    PushOutbox.user_id.in_(list(wanted)),
                    PushOutbox.kind == kind,
                    PushOutbox.subject == subject,
                    PushOutbox.state == "queued",
                )
            )
            existing = {row.user_id: row for row in rows}

        zones = await devices_for(db, user_ids=list(wanted))
        for user_id in wanted:
            held = existing.get(user_id)
            if held is not None:
                held.people += 1
                held.title = title
                held.body = body
                continue
            devices = zones.get(user_id, [])
            zone = next((d.timezone for d in devices if d.timezone), None)
            db.add(
                PushOutbox(
                    user_id=user_id,
                    kind=kind,
                    subject=subject,
                    title=title[:120],
                    body=body[:300],
                    deep_link=deep_link,
                    send_after=civil_time(moment, zone),
                )
            )
            written += 1
        await db.commit()

    return written



async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str,
    subject: str | None = None,
    deep_link: str | None = None,
) -> None:
    """Queue one notification for one person, and never fail the thing
    that caused it.

    **The event is the point; the banner is not.** Somebody saving a
    fit must not get a 500 because the notification table was busy,
    and a follow that half-happened is worse than a follow nobody was
    told about. Every error here is swallowed on purpose, which is
    the opposite of how the rest of this module behaves and the whole
    reason this wrapper exists rather than callers using `fan_out`
    directly.

    Nothing is sent from here: this writes a row. `app.workers.push`
    is the only thing that opens a socket.
    """
    if user_id is None:
        return
    try:
        await fan_out(
            db,
            kind=kind,
            audience=[user_id],
            title=title,
            body=body,
            subject=subject,
            deep_link=deep_link,
        )
    except Exception:  # pragma: no cover - defensive by design
        logger.exception("could not queue a %s notification", kind)

async def due(
    db: AsyncSession, *, limit: int = BATCH, now: datetime | None = None
) -> list[PushOutbox]:
    """The next few messages that are ready to go.

    Bounded, oldest first. The bound is the throttle; the order is so
    a large fan-out drains in the order it was written rather than
    starving its own tail.
    """
    moment = now or datetime.now(UTC)
    rows = await db.scalars(
        sa.select(PushOutbox)
        .where(PushOutbox.state == "queued", PushOutbox.send_after <= moment)
        .order_by(PushOutbox.send_after.asc(), PushOutbox.created_at.asc())
        .limit(max(1, limit))
    )
    return list(rows)


async def mark_sent(db: AsyncSession, *, ids: Sequence[uuid.UUID]) -> None:
    if not ids:
        return
    await db.execute(
        sa.update(PushOutbox)
        .where(PushOutbox.id.in_(list(ids)))
        .values(state="sent", sent_at=datetime.now(UTC))
    )
    await db.commit()


async def mark_dropped(
    db: AsyncSession, *, ids: Sequence[uuid.UUID], note: str
) -> None:
    """Give up on these, and say why.

    Kept rather than deleted, so "why did I not get that" has an
    answer: no device, a muted kind, or a gateway that refused it.
    """
    if not ids:
        return
    await db.execute(
        sa.update(PushOutbox)
        .where(PushOutbox.id.in_(list(ids)))
        .values(state="dropped", note=note[:200])
    )
    await db.commit()


__all__ = [
    "BATCH",
    "notify",
    "CHUNK",
    "DeviceClaimed",
    "civil_time",
    "devices_for",
    "due",
    "fan_out",
    "forget_device",
    "mark_dropped",
    "STALE",
    "mark_sent",
    "register_device",
]
