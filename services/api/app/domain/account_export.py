"""Everything somebody put into this app, gathered up to hand back.

**An allow-list, never a dump.** The obvious way to write this is to
walk every table with a `user_id` and serialise it, and that way is
wrong in two directions at once. It would hand somebody their own push
tokens, session tokens and OAuth refresh tokens - credentials, in a
file they are about to email themselves - and it would hand them the
moderation reports *other people* filed about them, which names the
reporters. So what goes in is listed here, by name, and anything new
has to be added deliberately. `NEVER_EXPORTED` records the other half
of that decision, because a list of what is included does not say
whether something was considered and refused or simply forgotten.

**It is their data, which is not the same as every row mentioning
them.** A taste cohort is computed *about* somebody by this service;
an AI run is cost accounting; usage counters are metering. None of
those are things a person provided, so none of them are things they
can take elsewhere, and padding an export with derived internals makes
the file harder to read without making it more complete.

**Both sides of a conversation go in, deliberately.** A thread with
one side removed is unreadable - half a conversation is not a record
of anything. The other person's words are already on this person's
screen in the app and have been since they were sent, so withholding
them from a file changes nothing about who can read them and costs the
export its usefulness. What is *not* included is anything about the
other person beyond what the thread itself shows: no email, no
settings, no other threads.

**Owner-scoped at every query, with no exceptions.** This is the one
module in the service where a missing `WHERE user_id` is not a bug
that shows up as wrong data on a screen - it is a file, handed to
somebody, containing a stranger's account. Every function here takes
`user_id` and every statement filters on it, and
`tests/test_account_export.py` builds two populated accounts and
asserts that neither appears in the other's export.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account_export import (
    EXPORT_LIFETIME_HOURS,
    AccountExport,
)

#: What this export deliberately leaves out, and why.
#:
#: Written down because "it is not in the file" cannot distinguish a
#: decision from an oversight, and the next person to extend this
#: needs to know which it was. Three kinds:
#:
#: - **Credentials.** Handing somebody their own session token or a
#:   provider refresh token in a downloadable file is a vulnerability
#:   whoever ends up holding the file can use. They are not data about
#:   a person, they are keys to acting as them.
#: - **Other people's.** A report filed about this account identifies
#:   its reporter. Including it would make the export a tool for
#:   finding out who reported you.
#: - **Derived or internal.** Computed about somebody rather than
#:   provided by them, so there is nothing to port.
NEVER_EXPORTED: dict[str, str] = {
    "push_tokens": "credential: a key to sending notifications as this device",
    "sessions": "credential: a live session token",
    "provider_connections": "credential: third-party OAuth tokens",
    # Both sides named, because naming only one is how the first
    # version of this file implied the other was included when it was
    # not. What somebody *did* is theirs and is exported; what was
    # done to them by other people is those people's.
    "moderation_reports_about_them": "identifies the people who reported them",
    "blocks_made_by_other_people": (
        "telling somebody who blocked them is a harm to the person who "
        "blocked them, and blocking is meant to be quiet"
    ),
    "user_cohorts": "derived by this service, not provided by the person",
    "cohort_inspirations": "derived by this service",
    "ai_runs": "cost accounting, internal",
    "usage_counters": "metering, internal",
    "tombstones": "deletion bookkeeping, internal",
}


class NothingToExport(Exception):
    """No such user, so there is nothing to gather."""


async def gather(db: AsyncSession, *, user_id: uuid.UUID) -> dict[str, Any]:
    """Everything on the allow-list, for one person.

    Returns a plain dict, JSON-ready. Reads only; building the archive
    and writing it is the worker's job, so this can be called from a
    test without a store.

    Soft-deleted rows are left out throughout. Somebody who deleted a
    fit, a garment or a message deleted it; handing it back in a file
    would make deletion look like hiding.
    """
    from app.models.comment import PostComment
    from app.models.consent import Consent
    from app.models.direct_message import (
        DirectMessage,
        DirectMessageHidden,
        DirectThread,
        DirectThreadMember,
    )
    from app.models.external_reference import ExternalReference
    from app.models.garment import Collection, CollectionGarment, Garment
    from app.models.garment_studio import GarmentShot
    from app.models.media_asset import MediaAsset
    from app.models.moderation import Block, Report
    from app.models.moodboard import Moodboard, MoodboardPin
    from app.models.outfit_plan import OutfitPlan, OutfitPlanItem
    from app.models.posts import Post, PostMedia, PostSave
    from app.models.profile import Profile
    from app.models.user import User

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NothingToExport(f"no live user {user_id}")

    profile = await db.scalar(
        sa.select(Profile).where(
            Profile.user_id == user_id, Profile.deleted_at.is_(None)
        )
    )

    account = {
        "email": user.email,
        "display_name": user.display_name,
        "locale": user.locale,
        "joined_at": _when(user.created_at),
        # Their handle and bio live on the profile, which a fresh
        # account may not have yet. An empty profile is not an error.
        "handle": profile.handle if profile else None,
        "bio": profile.bio if profile else None,
        "links": profile.links if profile else None,
        "private": profile.private if profile else None,
    }

    garments = (
        await db.scalars(
            sa.select(Garment)
            .where(Garment.user_id == user_id, Garment.deleted_at.is_(None))
            .order_by(Garment.created_at)
        )
    ).all()

    collections = (
        await db.scalars(
            sa.select(Collection).where(
                Collection.user_id == user_id, Collection.deleted_at.is_(None)
            )
        )
    ).all()
    collection_items: dict[uuid.UUID, list[str]] = {}
    if collections:
        for link in (
            await db.scalars(
                sa.select(CollectionGarment)
                .where(
                    CollectionGarment.collection_id.in_(
                        [c.id for c in collections]
                    )
                )
                .order_by(CollectionGarment.position)
            )
        ).all():
            collection_items.setdefault(link.collection_id, []).append(
                str(link.garment_id)
            )

    posts = (
        await db.scalars(
            sa.select(Post)
            .where(Post.user_id == user_id, Post.deleted_at.is_(None))
            .order_by(Post.created_at)
        )
    ).all()

    # One statement rather than a query per post: a prolific account
    # would otherwise make this N+1 over its whole history.
    media_by_post: dict[uuid.UUID, list[str]] = {}
    if posts:
        for link in (
            await db.scalars(
                sa.select(PostMedia)
                .where(PostMedia.post_id.in_([p.id for p in posts]))
                .order_by(PostMedia.position)
            )
        ).all():
            media_by_post.setdefault(link.post_id, []).append(
                str(link.media_asset_id)
            )

    comments = (
        await db.scalars(
            sa.select(PostComment)
            .where(
                PostComment.user_id == user_id,
                PostComment.deleted_at.is_(None),
            )
            .order_by(PostComment.created_at)
        )
    ).all()

    boards = (
        await db.scalars(
            sa.select(Moodboard)
            .where(Moodboard.user_id == user_id)
            .order_by(Moodboard.created_at)
        )
    ).all()
    board_pins: dict[uuid.UUID, list[str]] = {}
    if boards:
        for pin in (
            await db.scalars(
                sa.select(MoodboardPin)
                .where(MoodboardPin.moodboard_id.in_([b.id for b in boards]))
                .order_by(MoodboardPin.position)
            )
        ).all():
            board_pins.setdefault(pin.moodboard_id, []).append(str(pin.post_id))

    # Fits of other people's they kept. The ids only: somebody else's
    # photograph is not this person's to take a copy of, and the shelf
    # is a record of what they chose rather than of the pictures.
    kept = (
        await db.scalars(
            sa.select(PostSave)
            .where(PostSave.user_id == user_id)
            .order_by(PostSave.created_at)
        )
    ).all()

    plans = (
        await db.scalars(
            sa.select(OutfitPlan)
            .where(OutfitPlan.user_id == user_id)
            .order_by(OutfitPlan.planned_for)
        )
    ).all()
    plan_items: dict[uuid.UUID, list[str]] = {}
    if plans:
        for item in (
            await db.scalars(
                sa.select(OutfitPlanItem)
                .where(OutfitPlanItem.plan_id.in_([pl.id for pl in plans]))
                .order_by(OutfitPlanItem.position)
            )
        ).all():
            plan_items.setdefault(item.plan_id, []).append(str(item.garment_id))

    shots = (
        await db.scalars(
            sa.select(GarmentShot)
            .where(
                GarmentShot.user_id == user_id,
                GarmentShot.deleted_at.is_(None),
            )
            .order_by(GarmentShot.created_at)
        )
    ).all()

    consents = (
        await db.scalars(
            sa.select(Consent)
            .where(Consent.user_id == user_id)
            .order_by(Consent.created_at)
        )
    ).all()

    references = (
        await db.scalars(
            sa.select(ExternalReference).where(
                ExternalReference.user_id == user_id,
                ExternalReference.deleted_at.is_(None),
            )
        )
    ).all()

    # Threads this person is in, then the messages in those threads.
    #
    # Scoped by thread membership rather than by message author, which
    # is what includes the other side. The membership query is the
    # security boundary: a thread this person is not in must not
    # contribute a single row, so the ids come from their own
    # membership and the message query is restricted to those ids.
    threads = (
        await db.scalars(
            sa.select(DirectThread)
            .where(
                sa.or_(
                    DirectThread.lower_id == user_id,
                    DirectThread.upper_id == user_id,
                )
            )
            .order_by(DirectThread.created_at)
        )
    ).all()
    thread_ids = [t.id for t in threads]

    # **Everything this person removed from their own view stays
    # removed.** Two independent mechanisms, and the export has to
    # honour both or it contradicts the app - handing somebody back
    # the messages they deleted, in a file, is the export telling them
    # the delete did not work.
    #
    # `DirectMessageHidden` is one message taken out of one reader's
    # copy. `DirectThreadMember.cleared_at` is a whole history cleared,
    # which the thread view applies as `created_at > cleared_at`; the
    # same cut-off is applied here, per thread, because clearing one
    # conversation says nothing about another.
    hidden: set[uuid.UUID] = set()
    cleared: dict[uuid.UUID, Any] = {}
    messages: list[Any] = []
    if thread_ids:
        hidden = set(
            (
                await db.scalars(
                    sa.select(DirectMessageHidden.message_id).where(
                        DirectMessageHidden.user_id == user_id
                    )
                )
            ).all()
        )
        for member in (
            await db.scalars(
                sa.select(DirectThreadMember).where(
                    DirectThreadMember.user_id == user_id,
                    DirectThreadMember.thread_id.in_(thread_ids),
                    DirectThreadMember.cleared_at.is_not(None),
                )
            )
        ).all():
            cleared[member.thread_id] = member.cleared_at
        messages = list(
            (
                await db.scalars(
                    sa.select(DirectMessage)
                    .where(
                        DirectMessage.thread_id.in_(thread_ids),
                        DirectMessage.deleted_at.is_(None),
                    )
                    .order_by(DirectMessage.created_at)
                )
            ).all()
        )

    def _still_mine(message: Any) -> bool:
        """Whether this message is still in this person's own copy."""
        if message.id in hidden:
            return False
        cut = cleared.get(message.thread_id)
        return cut is None or message.created_at > cut

    # What they reported, and who they blocked.
    #
    # **Scoped to what they did, never to what was done to them.** A
    # report filed *about* this account identifies its reporter, and a
    # block *of* this account is the other person's business - telling
    # somebody who blocked them is a harm to the blocker, and blocking
    # is meant to be quiet. So: `reporter_id`, not `subject_user_id`;
    # `blocker_id`, not `blocked_id`.
    reports = (
        await db.scalars(
            sa.select(Report)
            .where(Report.reporter_id == user_id)
            .order_by(Report.created_at)
        )
    ).all()
    blocks = (
        await db.scalars(
            sa.select(Block)
            .where(Block.blocker_id == user_id)
            .order_by(Block.created_at)
        )
    ).all()

    # Every picture of theirs, so the archive can carry the files and
    # the manifest can name them. Their own assets only.
    assets = (
        await db.scalars(
            sa.select(MediaAsset)
            .where(
                MediaAsset.user_id == user_id,
                MediaAsset.deleted_at.is_(None),
                MediaAsset.storage_key.is_not(None),
            )
            .order_by(MediaAsset.created_at)
        )
    ).all()

    return {
        "export_version": 1,
        "generated_at": _when(datetime.now(UTC)),
        "about_this_file": (
            "Everything you put into this app. Your pictures are in "
            "the pictures folder beside this file, named by the ids "
            "used below. Some things are deliberately left out, "
            "listed under not_included."
        ),
        "not_included": NEVER_EXPORTED,
        "account": account,
        "wardrobe": [
            {
                "id": str(g.id),
                "name": g.name,
                "category": g.category,
                "availability": g.availability,
                "favourite": g.is_favourite,
                # What somebody confirmed about a garment is theirs.
                # What a model guessed is kept separate and labelled,
                # because a guess presented as a fact in a file they
                # keep is a guess they cannot correct.
                "you_said": g.confirmed_attributes,
                "we_guessed": g.inferred_attributes,
                "picture": _maybe(g.media_asset_id),
                "added_at": _when(g.created_at),
            }
            for g in garments
        ],
        "wardrobe_collections": [
            {
                "id": str(c.id),
                "name": c.name,
                "description": c.description,
                "garments": collection_items.get(c.id, []),
            }
            for c in collections
        ],
        "fits": [
            {
                "id": str(p.id),
                "caption": p.caption,
                "occasion": p.occasion,
                "state": p.state,
                "visibility": p.visibility,
                "pictures": media_by_post.get(p.id, []),
                "posted_at": _when(p.published_at),
                "created_at": _when(p.created_at),
            }
            for p in posts
        ],
        "comments": [
            {
                "id": str(c.id),
                "on_fit": str(c.post_id),
                "replying_to": _maybe(c.parent_id),
                "body": c.body,
                "written_at": _when(c.created_at),
            }
            for c in comments
        ],
        "boards": [
            {
                "id": str(b.id),
                "name": b.name,
                "note": b.note,
                "fits": board_pins.get(b.id, []),
                "created_at": _when(b.created_at),
            }
            for b in boards
        ],
        "fits_you_kept": [
            {"fit_id": str(k.post_id), "kept_at": _when(k.created_at)}
            for k in kept
        ],
        "plans": [
            {
                "id": str(pl.id),
                "planned_for": _when(pl.planned_for),
                "note": pl.note,
                "worn": pl.worn,
                "garments": plan_items.get(pl.id, []),
            }
            for pl in plans
        ],
        "studio_shots": [
            {
                "id": str(sh.id),
                "treatment": sh.treatment,
                "state": sh.state,
                "landscape": sh.landscape,
                "your_direction": sh.brief,
                "picture": _maybe(sh.media_asset_id),
                "from_picture": _maybe(sh.source_asset_id),
                "created_at": _when(sh.created_at),
            }
            for sh in shots
        ],
        "links_you_saved": [
            {
                "id": str(r.id),
                "url": r.canonical_url or r.submitted_url,
                "platform": r.platform,
                "title": r.title,
                "note": r.note,
                "saved_at": _when(r.created_at),
            }
            for r in references
        ],
        "what_you_agreed_to": [
            {
                "kind": c.kind,
                # The two timestamps rather than a boolean: when
                # somebody granted something and when they took it
                # back is the record, and flattening it to "off" loses
                # the half that matters.
                "granted_at": _when(c.granted_at),
                "revoked_at": _when(c.revoked_at),
                "asked_on": c.source,
            }
            for c in consents
        ],
        "conversations": [
            {
                "id": str(t.id),
                # Who the other person is, by id only. Their email and
                # their settings are not this person's to take.
                "with_user_id": str(
                    t.upper_id if t.lower_id == user_id else t.lower_id
                ),
                "messages": [
                    {
                        "id": str(m.id),
                        "sent_by_me": m.sender_id == user_id,
                        "body": m.body,
                        "picture": _maybe(m.media_asset_id),
                        "sent_at": _when(m.created_at),
                    }
                    for m in messages
                    if m.thread_id == t.id and _still_mine(m)
                ],
            }
            for t in threads
        ],
        "things_you_reported": [
            {
                "id": str(r.id),
                "what": r.subject_kind,
                "guideline": r.guideline_id,
                "reason": r.reason,
                "your_note": r.note,
                "outcome": r.state,
                "reported_at": _when(r.created_at),
            }
            for r in reports
        ],
        "people_you_blocked": [
            {"user_id": str(b.blocked_id), "blocked_at": _when(b.created_at)}
            for b in blocks
        ],
        "pictures": [
            {
                "id": str(a.id),
                "file": f"pictures/{a.id}{_suffix(a.content_type)}",
                "kind": a.kind,
                "content_type": a.content_type,
                "width": a.width,
                "height": a.height,
                "created_at": _when(a.created_at),
            }
            for a in assets
        ],
    }


def _when(value: Any) -> str | None:
    """A timestamp as ISO-8601, or None. Never a bare `repr`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _maybe(value: Any) -> str | None:
    return None if value is None else str(value)


def _suffix(content_type: str | None) -> str:
    """The extension a picture should carry inside the archive.

    Named rather than guessed from the storage key: a key is an
    internal path and may carry no extension at all, and a file called
    `a1b2c3` is one nobody's photo viewer will open.
    """
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
    }.get((content_type or "").lower(), ".bin")


# --------------------------------------------------------------------------- #
# Requesting one, and reading the one you have
# --------------------------------------------------------------------------- #
async def request(db: AsyncSession, *, user_id: uuid.UUID) -> AccountExport:
    """Start an export, or hand back the one already running.

    **Not a second job.** Building an export reads every picture
    somebody owns out of object storage, so a button that queues one
    per tap is a way to bill a lot of reads from an impatient finger.
    A request while one is gathering returns that one, so the screen
    shows progress rather than starting again.
    """
    from app.domain.jobs import enqueue
    from app.workers.account_export import EXPORT_JOB_KIND

    running = await db.scalar(
        sa.select(AccountExport)
        .where(
            AccountExport.user_id == user_id,
            AccountExport.state == "gathering",
        )
        .order_by(AccountExport.created_at.desc())
        .limit(1)
    )
    if running is not None:
        return running

    row = AccountExport(user_id=user_id, state="gathering")
    db.add(row)
    await db.flush()

    job = await enqueue(
        db,
        EXPORT_JOB_KIND,
        {"export_id": str(row.id), "user_id": str(user_id)},
        # One in flight per export row, so a retried request cannot
        # stack duplicate work against the same artifact.
        idempotency_key=f"account-export:{row.id}",
    )
    row.job_id = job.id
    await db.flush()
    return row


async def latest_for(
    db: AsyncSession, *, user_id: uuid.UUID
) -> AccountExport | None:
    """The most recent export for this person, expiry already applied.

    Expiry is resolved on read rather than by a sweeper. A sweeper
    that has not run yet would leave a stale row reading `ready`, and
    this is the one place where "ready" must never be shown for
    something that is no longer downloadable.
    """
    row = await db.scalar(
        sa.select(AccountExport)
        .where(AccountExport.user_id == user_id)
        .order_by(AccountExport.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    if row.state == "ready" and _has_expired(row):
        row.state = "expired"
        await db.flush()
    return row


async def readable(
    db: AsyncSession, *, user_id: uuid.UUID, export_id: uuid.UUID
) -> AccountExport | None:
    """This export, if this person may download it. Otherwise None.

    Owner *and* state *and* deadline, all three, in one place. The
    caller turns a None into a 404 rather than a 403: a 403 would
    confirm the id exists, which is the same reasoning the media route
    uses and matters more here, because the object is somebody's whole
    account.
    """
    row = await db.get(AccountExport, export_id)
    if row is None or row.user_id != user_id:
        return None
    if row.state != "ready" or not row.storage_key:
        return None
    if _has_expired(row):
        row.state = "expired"
        await db.flush()
        return None
    return row


def _has_expired(row: AccountExport) -> bool:
    if row.expires_at is None:
        return False
    deadline = row.expires_at
    if deadline.tzinfo is None:
        # SQLite hands back a naive datetime. Comparing it to an aware
        # one raises, which would turn an expiry check into a 500 and
        # leave the download working - failing open on exactly the
        # check that must fail closed.
        deadline = deadline.replace(tzinfo=UTC)
    return deadline <= datetime.now(UTC)


def deadline_from(moment: datetime) -> datetime:
    """When an export finished at `moment` stops being downloadable."""
    return moment + timedelta(hours=EXPORT_LIFETIME_HOURS)


__all__ = [
    "NEVER_EXPORTED",
    "NothingToExport",
    "deadline_from",
    "gather",
    "latest_for",
    "readable",
    "request",
]
