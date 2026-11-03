"""Which kinds of updates a person wants to hear about.

One preference row, same table and same reasoning as the read watermark: a
choice about notifications is a statement by the user, and the preferences
table is where those live. Stored per account rather than per device, so
muting something on a phone keeps it muted after a reinstall and on every
other device the account signs into.

**The server enforces the three inbox kinds; the client enforces the rest.**
``plan_reminders`` is a toggle for notifications the phone schedules locally
out of the planner, which this service never sends and cannot cancel. It is
stored here anyway so the choice survives the device, and the schema keeps
it in the same closed vocabulary so a typo cannot create a phantom setting
that nothing reads.

Defaults are all on. A fresh account hears about everything, and the row is
only written once somebody turns something off — absence of the row means
"never touched", which costs nothing to store.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications import KINDS, PUSH_ONLY_KINDS
from app.errors import ApiError
from app.models.preference import Preference

#: Where the choices live, beside ``notifications_read_at``.
PREFS_KEY = "notification_prefs"

#: Everything that can be switched. The inbox kinds, plus the one local
#: notification the app schedules itself.
TOGGLES: tuple[str, ...] = (*KINDS, *PUSH_ONLY_KINDS, "plan_reminders")


class UnknownNotificationToggle(ApiError):
    status_code = 422
    code = "unknown_notification_toggle"
    default_message = "That is not a notification setting this service knows."


async def read_prefs(session: AsyncSession, *, user_id: uuid.UUID) -> dict[str, bool]:
    """This person's choices, with defaults filled in.

    Merged over the defaults rather than returned raw, so a toggle added
    after the row was written still appears, on, instead of silently missing
    from the response until the user touches something.
    """
    stored = await session.scalar(
        sa.select(Preference.value).where(
            Preference.user_id == user_id, Preference.key == PREFS_KEY
        )
    )
    prefs = {toggle: True for toggle in TOGGLES}
    if isinstance(stored, dict):
        for toggle in TOGGLES:
            value = stored.get(toggle)
            if isinstance(value, bool):
                prefs[toggle] = value
    return prefs


async def write_prefs(
    session: AsyncSession, *, user_id: uuid.UUID, changes: Mapping[str, object]
) -> dict[str, bool]:
    """Apply the toggles present in ``changes`` and return the full set.

    Partial on purpose, like the profile PATCH: a client that flips one
    switch sends one key, and the request cannot quietly reset the switches
    it did not mention.
    """
    for key, value in changes.items():
        if key not in TOGGLES:
            raise UnknownNotificationToggle(
                f"{key!r} is not a notification setting.",
                detail={"allowed": list(TOGGLES)},
            )
        if not isinstance(value, bool):
            raise UnknownNotificationToggle(
                f"{key!r} must be true or false.", detail={"received": value}
            )

    prefs = await read_prefs(session, user_id=user_id)
    prefs.update({key: bool(value) for key, value in changes.items()})

    existing = await session.scalar(
        sa.select(Preference).where(
            Preference.user_id == user_id, Preference.key == PREFS_KEY
        )
    )
    if existing is None:
        session.add(Preference(user_id=user_id, key=PREFS_KEY, value=dict(prefs)))
    else:
        existing.value = dict(prefs)
    # Committed, not merely flushed: nothing in this app commits on the way
    # out of a request, and a flushed-only write is rolled back with the
    # session. The profile PATCH shipped that bug once already.
    await session.commit()
    return prefs


async def muted_kinds(session: AsyncSession, *, user_id: uuid.UUID) -> frozenset[str]:
    """The inbox kinds this person has switched off.

    Only the kinds the server builds. ``plan_reminders`` is the phone's to
    honour and deliberately absent here, so the inbox cannot be emptied by a
    toggle that was never about it.
    """
    prefs = await read_prefs(session, user_id=user_id)
    return frozenset(kind for kind in KINDS if not prefs.get(kind, True))


__all__ = [
    "PREFS_KEY",
    "TOGGLES",
    "UnknownNotificationToggle",
    "muted_kinds",
    "read_prefs",
    "write_prefs",
]
