"""The only place in this service that talks to a push gateway.

**Expo's push service, which fronts APNs and FCM.** The app is an Expo
app, so its tokens are Expo tokens and this is the gateway that
understands them; Expo holds the persistent HTTP/2 connections to
Apple and Google so this service does not have to. Swapping to a
direct APNs/FCM integration later means changing `_deliver` and
nothing above it - which is why `platform` is on the token rather than
assumed here.

**Bounded on purpose, in two places.** `push.due` hands over at most
`BATCH` rows per run, and this sends them in slices the gateway
accepts. A gateway treats a sudden flood as an attack, and everybody
opening the app at once because they were all notified in the same
second is a worse outage than the delay. A large fan-out therefore
leaves over minutes.

**A row is never lost, only resolved.** Sent, or dropped with a reason
anybody can read later. A row nobody can deliver - no device, a dead
token - is dropped rather than retried for ever.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import push as domain

PUSH_SEND_JOB_KIND = "push.send"

#: Expo's endpoint. One request carries many messages.
EXPO_ENDPOINT = "https://exp.host/--/api/v2/push/send"

#: The most messages in one request to the gateway.
#:
#: A hundred is Expo's documented ceiling. Slicing here as well as in
#: `push.due` is not redundant: `due` is the throttle over time, this
#: is what one HTTP request may carry.
PER_REQUEST = 100

#: How many times a row may fail before it is given up on.
MAX_ATTEMPTS = 5


def _message(row: Any, token: str) -> dict[str, Any]:
    """One message, in the shape the gateway wants.

    `people` is why the body is rewritten here rather than at fan-out:
    the tally is still rising while the row waits, so the sentence is
    built from whatever it reached by the time it leaves.
    """
    body = row.body
    if row.people > 1:
        body = f"{body} and {row.people - 1} others"
    return {
        "to": token,
        "title": row.title,
        "body": body,
        "sound": "default",
        # Where tapping it lands. The app reads this rather than
        # guessing from the text.
        #
        # `kind` travels with it because the app's rule has two steps:
        # go where the row said, and fall back to that kind's home
        # screen when it did not say or said something unroutable. It
        # read `data.kind` from the first version and nothing ever put
        # one there, so the fallback could only ever reach Discover -
        # a studio notice with a missing link landed on the feed
        # rather than the studio.
        "data": {"kind": row.kind, "deep_link": row.deep_link}
        if row.deep_link
        else {"kind": row.kind},
    }


async def _deliver(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Hand a slice to the gateway. The tickets it gave back, or None.

    **A 200 does not mean anything was delivered**, and reading it
    that way was a real bug here. The gateway answers one *ticket*
    per message, each with its own `status`, and a request full of
    messages to dead tokens comes back 200 with an error in every
    ticket. Returning a bool off the status code therefore marked
    those rows sent: somebody who reinstalled the app absorbed every
    notification they were ever sent, for ever, and the outbox
    recorded each one as delivered.

    None is the one answer that means *try again*: the request itself
    did not land. A blip and an outage are indistinguishable from
    here and both want the same thing.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            answer = await http.post(
                EXPO_ENDPOINT,
                json=messages,
                headers={"accept": "application/json"},
            )
        if answer.status_code >= 400:
            return None
        body = answer.json()
    except (httpx.HTTPError, ValueError):
        return None

    tickets = body.get("data") if isinstance(body, dict) else None
    if not isinstance(tickets, list):
        # It took the request and said something this does not
        # understand. Treating that as delivered is the mistake above;
        # treating it as a transport failure would retry for ever
        # against a gateway that is answering. An empty list means no
        # ticket says otherwise, so the slice is accepted as sent.
        return []
    return tickets


#: Gateway ticket errors that mean this token is finished.
#:
#: `DeviceNotRegistered` is the gateway telling us the app was
#: uninstalled, or the token reissued. It is not a delivery failure to
#: retry - it is a row to revoke, or the same message is re-sent to
#: the same dead token until it exhausts its attempts, and every
#: notification after it goes the same way.
DEAD_TOKEN_ERRORS = frozenset({"DeviceNotRegistered", "InvalidCredentials"})


async def send_due(
    db: AsyncSession,
    *,
    deliver: Any = None,
    limit: int | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Drain what is due. Returns what happened, for the job record.

    `deliver` is injected so a test can run the whole pipeline without
    a network, and `now` so one can run it against a fixed clock: the
    defaults are the real gateway and the real time.
    """
    send = deliver or _deliver
    rows = await domain.due(db, limit=limit or domain.BATCH, now=now)
    if not rows:
        return {"outcome": "nothing due", "sent": 0, "dropped": 0}

    reachable = await domain.devices_for(
        db, user_ids=[row.user_id for row in rows]
    )

    # A row with nowhere to go is resolved, not retried. Somebody who
    # never granted the permission would otherwise accumulate a queue
    # that can never drain.
    homeless = [row.id for row in rows if not reachable.get(row.user_id)]
    await domain.mark_dropped(
        db, ids=homeless, note="No device registered for this account."
    )

    pending = [row for row in rows if reachable.get(row.user_id)]

    # One message per row per device, and a parallel note of who each
    # one was addressed to. The gateway answers one ticket per message
    # in the order they were sent, and without this there is no way
    # back from "ticket 7 failed" to the row and the token it was for.
    messages: list[dict[str, Any]] = []
    addressed: list[tuple[Any, str]] = []
    for row in pending:
        for device in reachable[row.user_id]:
            messages.append(_message(row, device.token))
            addressed.append((row, device.token))

    #: Per message: True delivered, False refused and worth retrying,
    #: None refused because the token is finished.
    landed: list[bool | None] = []
    deferred = False
    for at in range(0, len(messages), PER_REQUEST):
        slice_ = messages[at : at + PER_REQUEST]
        answer = await send(slice_)

        if answer is None or answer is False:
            # The request did not land. Nothing in this slice has an
            # outcome, so the rows behind it stay queued.
            deferred = True
            break

        if answer is True or not isinstance(answer, list):
            # A gateway, or a test, that reports acceptance without
            # per-message detail. Taken at its word.
            landed += [True] * len(slice_)
            continue

        for at_in_slice in range(len(slice_)):
            ticket = (
                answer[at_in_slice] if at_in_slice < len(answer) else None
            )
            if not isinstance(ticket, dict) or ticket.get("status") == "ok":
                # A missing ticket is not evidence of failure, and
                # retrying a message the gateway may have taken would
                # send it twice.
                landed.append(True)
                continue
            error = (ticket.get("details") or {}).get("error")
            landed.append(None if error in DEAD_TOKEN_ERRORS else False)

    # Tokens the gateway says are finished. Revoked before the rows are
    # resolved, so the next drain does not address them again.
    dead = {
        token
        for (row, token), outcome in zip(addressed, landed)
        if outcome is None
    }
    for token in dead:
        owner = next(r.user_id for (r, t) in addressed if t == token)
        await domain.forget_device(db, token=token, user_id=owner)

    # Now per row, because a row with two phones is delivered if either
    # of them took it.
    outcomes: dict[uuid.UUID, list[bool | None]] = {}
    for (row, _token), outcome in zip(addressed, landed):
        outcomes.setdefault(row.id, []).append(outcome)

    sent: list[uuid.UUID] = []
    gone: list[uuid.UUID] = []
    retry: list[Any] = []
    for row in pending:
        got = outcomes.get(row.id)
        if not got:
            # In a slice that never left, or after one that failed.
            retry.append(row)
        elif any(outcome is True for outcome in got):
            sent.append(row.id)
        elif all(outcome is None for outcome in got):
            gone.append(row.id)
        else:
            retry.append(row)

    await domain.mark_sent(db, ids=sent)
    await domain.mark_dropped(
        db,
        ids=gone,
        note="Every device for this account has been uninstalled or reset.",
    )

    # What is left stays queued and counted. A row that has failed too
    # many times is given up on, so one undeliverable message cannot
    # block the queue behind it for ever.
    exhausted: list[uuid.UUID] = []
    for row in retry:
        row.attempts += 1
        if row.attempts >= MAX_ATTEMPTS:
            exhausted.append(row.id)
    if retry:
        await db.commit()
    await domain.mark_dropped(
        db, ids=exhausted, note="The push gateway would not take this."
    )

    return {
        "outcome": "deferred" if deferred else "sent",
        "sent": len(sent),
        "dropped": len(homeless) + len(gone) + len(exhausted),
        "revoked": len(dead),
    }


def push_handlers(*, deliver: Any = None) -> dict[str, Any]:
    async def _handle(session: AsyncSession, job: Any) -> dict | None:
        return await send_due(session, deliver=deliver)

    return {PUSH_SEND_JOB_KIND: _handle}


__all__ = [
    "DEAD_TOKEN_ERRORS",
    "EXPO_ENDPOINT",
    "MAX_ATTEMPTS",
    "PER_REQUEST",
    "PUSH_SEND_JOB_KIND",
    "push_handlers",
    "send_due",
]
