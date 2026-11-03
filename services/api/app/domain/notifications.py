"""The inbox: what happened while you were away.

**Derived, not written.** There is no notifications table and that is the
design, not a shortcut. Every event worth telling somebody about is already
recorded by the feature that produced it — a stylist run has a state and a
finish time, a garment has a creation time, an interaction has a person and a
moment. A second copy written at the same time as the first is a second thing
that can drift, be forgotten by a new code path, or disagree with the screen
it describes. Reading the originals means the inbox cannot be wrong about
something that happened.

The cost is real and worth naming: this cannot notify about something nothing
records, and it cannot carry per-item read state. The read watermark is one
timestamp per person (:data:`READ_KEY`), so "unread" means "after the last
time you looked", which is what an inbox somebody scrolls actually needs.

**Nothing here invents an audience.** The one cross-user item — other people
reaching for a look you kept — reuses the same threshold trending does. Below
:data:`MIN_DISTINCT_USERS` distinct people it is not reported at all, because
"1 person saved this too" is a notification about a stranger's single tap
dressed up as a community.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.moderation import hidden_either_way
from app.domain.ranking import MIN_DISTINCT_USERS, WINDOW_DAYS
from app.models.garment import Garment
from app.models.preference import Preference
from app.models.stylist import StylistRun

#: Where the read watermark lives. A preference because it is a statement by
#: the user — "I have seen up to here" — which is exactly what that table is.
READ_KEY = "notifications_read_at"

#: How far back the inbox looks. The same window every other claim
#: about recent attention uses, so two screens cannot disagree about
#: whether something is recent.
INBOX_DAYS = WINDOW_DAYS

#: The most items one response carries. An inbox is scrolled, not paged
#: through, and anything past this is history rather than news.
MAX_ITEMS = 50

#: Every kind this inbox can produce. Closed, so a client can render each one
#: deliberately rather than falling back to a generic row.
KINDS = ("wardrobe_sorted", "stylist_ready", "fit_reactions")

#: Things that are worth a banner but are not inbox entries.
#:
#: Separate from `KINDS` because these are not built by this module -
#: they are queued by whatever caused them, at the moment it happens.
#: They are listed here so the settings screen offers a switch for
#: each: somebody who wants to know about a message and not about a
#: new follower should be able to say so, and a single "notifications"
#: toggle is how an app gets turned off entirely.
PUSH_ONLY_KINDS: tuple[str, ...] = (
    "fit_saved",
    "new_follower",
    "studio_ready",
    "message",
)

#: Which interaction kinds count as somebody *reacting* to a look.
#:
#: `view` is too weak to mean anything — it includes curiosity and
#: mistaps. `ask_stylist` is excluded for a different reason: it measures
#: use of a feature rather than a response to the clothes, and reporting
#: it as a community reaction would make a tally of button presses look
#: like an opinion. Both are still recorded and both still rank what the
#: person who made them is shown.
PUBLIC_REACTION_KINDS: tuple[str, ...] = ("save", "search_piece")


@dataclass(frozen=True, slots=True)
class Notification:
    kind: str
    occurred_at: datetime
    #: One line, already written. The server composes it because the counts
    #: and thresholds that make it true live here.
    title: str
    body: str
    #: Where tapping it should go, as an app route. Null when there is
    #: nowhere better than the inbox itself.
    #: Where tapping this notice goes, as a path the app can route to.
    #:
    #: **A path, not a file location.** Two of these read
    #: `/(tabs)/wardrobe` and `/(tabs)/stylist`, which are where the
    #: screens live in the project rather than where they are on the
    #: device: `(tabs)` is a route *group* and never appears in a URL,
    #: so both pushes went nowhere and tapping those notices did
    #: nothing at all. The stylist had also moved off the tab bar by
    #: then, so even the corrected group path would have been wrong.
    #:
    #: `tests/test_notification_targets.py` checks every one of these
    #: against the routes the app actually has.
    target: str | None = None
    #: How many distinct people this rests on, for the one item that is a
    #: claim about other people. Null for everything else.
    people: int | None = None


async def read_watermark(
    session: AsyncSession, *, user_id: uuid.UUID
) -> datetime | None:
    """When this person last looked, or nothing if they never have."""
    stored = await session.scalar(
        sa.select(Preference.value).where(
            Preference.user_id == user_id, Preference.key == READ_KEY
        )
    )
    raw = stored.get("at") if isinstance(stored, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def mark_read(
    session: AsyncSession, *, user_id: uuid.UUID, at: datetime | None = None
) -> datetime:
    """Move the watermark forward. Never backwards.

    Two devices open the inbox minutes apart, and the later one must not
    un-read what the earlier one read. Monotonic is the only behaviour that
    makes the unread count agree with itself across devices.
    """
    moment = at or datetime.now(UTC)
    existing = await session.scalar(
        sa.select(Preference).where(
            Preference.user_id == user_id, Preference.key == READ_KEY
        )
    )
    current = await read_watermark(session, user_id=user_id)
    if current is not None and current >= moment:
        return current

    if existing is None:
        session.add(
            Preference(user_id=user_id, key=READ_KEY, value={"at": moment.isoformat()})
        )
    else:
        existing.value = {"at": moment.isoformat()}
    await session.commit()
    return moment


async def _wardrobe_sorted(
    session: AsyncSession, *, user_id: uuid.UUID, cutoff: datetime
) -> list[Notification]:
    """Photographs that finished being sorted, grouped by the day they landed.

    Grouped rather than one per garment, because uploading fifteen things at
    once should be one line in an inbox and not fifteen. The day is the
    grouping somebody actually thinks in.
    """
    rows = (
        await session.execute(
            sa.select(
                sa.func.date(Garment.created_at).label("day"),
                sa.func.count().label("count"),
                sa.func.max(Garment.created_at).label("at"),
            )
            .where(Garment.user_id == user_id, Garment.created_at >= cutoff)
            .group_by(sa.func.date(Garment.created_at))
        )
    ).all()

    out: list[Notification] = []
    for row in rows:
        count = int(row.count)
        at = row.at if isinstance(row.at, datetime) else datetime.now(UTC)
        out.append(
            Notification(
                kind="wardrobe_sorted",
                occurred_at=at if at.tzinfo else at.replace(tzinfo=UTC),
                title=f"{count} {'piece' if count == 1 else 'pieces'} sorted",
                body="Photographed, cut out and categorised. They are in your wardrobe.",
                target="/wardrobe",
            )
        )
    return out


async def _stylist_ready(
    session: AsyncSession, *, user_id: uuid.UUID, cutoff: datetime
) -> list[Notification]:
    """Stylist runs that finished. One line each — each was asked for."""
    rows = (
        await session.scalars(
            sa.select(StylistRun)
            .where(
                StylistRun.user_id == user_id,
                StylistRun.state == "completed",
                StylistRun.finished_at.is_not(None),
                StylistRun.finished_at >= cutoff,
            )
            .order_by(StylistRun.finished_at.desc())
            .limit(MAX_ITEMS)
        )
    ).all()

    out: list[Notification] = []
    for run in rows:
        asked = (run.request_text or "").strip()
        out.append(
            Notification(
                kind="stylist_ready",
                occurred_at=run.finished_at or datetime.now(UTC),
                title="Your outfit is ready",
                # The request back, so a run finished hours ago is
                # recognisable without opening it.
                body=asked[:120] if asked else "The stylist finished putting it together.",
                target="/stylist",
            )
        )
    return out


async def _fit_reactions(
    session: AsyncSession, *, user_id: uuid.UUID, cutoff: datetime
) -> list[Notification]:
    """Other people keeping a fit you kept.

    The only item here that is a claim about anybody else, so it
    carries the shared crowd-size threshold. People are counted
    distinctly and the person asking is excluded: being told that you
    yourself kept something is not news.

    It used to count interactions on curated looks. Those are not
    shown anywhere now, so the notice reported on something nobody
    could see; a fit is the thing people actually keep.
    """
    from app.models.posts import Post, PostSave, shown_to_strangers

    kept = (
        await session.scalars(
            sa.select(PostSave.post_id).where(PostSave.user_id == user_id)
        )
    ).all()
    if not kept:
        return []

    hidden = await hidden_either_way(session, user_id=user_id)
    query = (
        sa.select(
            PostSave.post_id,
            sa.func.count(sa.distinct(PostSave.user_id)).label("people"),
            sa.func.max(PostSave.created_at).label("at"),
        )
        .join(Post, Post.id == PostSave.post_id)
        .where(
            PostSave.post_id.in_(list(kept)),
            PostSave.user_id != user_id,
            PostSave.created_at >= cutoff,
            shown_to_strangers(),
        )
        .group_by(PostSave.post_id)
        .having(
            sa.func.count(sa.distinct(PostSave.user_id)) >= MIN_DISTINCT_USERS
        )
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    rows = (await session.execute(query)).all()

    out: list[Notification] = []
    for row in rows:
        people = int(row.people)
        at = row.at if isinstance(row.at, datetime) else datetime.now(UTC)
        out.append(
            Notification(
                kind="fit_reactions",
                occurred_at=at if at.tzinfo else at.replace(tzinfo=UTC),
                title=f"{people} people kept this too",
                body="A fit you saved is getting attention this fortnight.",
                target=f"/fit/{row.post_id}",
                people=people,
            )
        )
    return out


async def inbox(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> tuple[Sequence[Notification], int]:
    """Everything worth telling this person, newest first, and the unread count.

    Returns an empty list freely. An inbox with nothing in it is a real
    answer, and filling it with "welcome" or "tip of the day" to avoid an
    empty screen is how a notification list stops being worth opening.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(days=INBOX_DAYS)

    # Imported here rather than at the top: the prefs module imports KINDS
    # from this one, and a module-level import back the other way is a cycle.
    from app.domain.notification_prefs import muted_kinds

    muted = await muted_kinds(session, user_id=user_id)

    items = [
        *(
            []
            if "wardrobe_sorted" in muted
            else await _wardrobe_sorted(session, user_id=user_id, cutoff=cutoff)
        ),
        *(
            []
            if "stylist_ready" in muted
            else await _stylist_ready(session, user_id=user_id, cutoff=cutoff)
        ),
        *(
            []
            if "fit_reactions" in muted
            else await _fit_reactions(session, user_id=user_id, cutoff=cutoff)
        ),
    ]
    items.sort(key=lambda item: item.occurred_at, reverse=True)
    items = items[:MAX_ITEMS]

    watermark = await read_watermark(session, user_id=user_id)
    unread = (
        len(items)
        if watermark is None
        else sum(1 for item in items if item.occurred_at > watermark)
    )
    return items, unread


__all__ = [
    "INBOX_DAYS",
    "KINDS",
    "MAX_ITEMS",
    "READ_KEY",
    "Notification",
    "inbox",
    "mark_read",
    "read_watermark",
]
