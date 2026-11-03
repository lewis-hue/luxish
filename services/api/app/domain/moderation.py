"""Blocking and reporting, and what a block actually severs.

**A block cuts the relationship both ways, immediately.** The follow edges
in either direction are deleted in the same transaction that writes the
block: "blocked but still following" is a state no one who pressed the
button would recognise, and an edge left behind would put the blocked
person's saves back on screen the moment the block lifted.

**A block is not disclosed to its subject.** Every read that filters on
blocks removes the pair in both directions, so the blocked person simply
sees less, with nothing labelled. The one place a block is visible is the
blocker's own list.

**Reports store and wait.** Nothing here hides content or suspends anyone:
acting on a report is a human decision for the moderation console, and an
automated verdict dressed as one is the kind of lie the capability-label
rule exists to prevent.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow import Follow
from app.models.moderation import (
    REPORT_REASONS,
    REPORT_SUBJECTS,
    Block,
    Report,
)


class CannotBlockSelf(Exception):
    """Blocking yourself would filter your own saves out of your own app."""


class BadReport(Exception):
    """A report missing its subject, or naming a reason off the list."""


async def block(
    db: AsyncSession, *, blocker_id: uuid.UUID, blocked_id: uuid.UUID
) -> None:
    """Block, idempotently, severing any follow in either direction."""
    if blocker_id == blocked_id:
        raise CannotBlockSelf

    existing = await db.get(Block, (blocker_id, blocked_id))
    if existing is None:
        db.add(Block(blocker_id=blocker_id, blocked_id=blocked_id))

    await db.execute(
        sa.delete(Follow).where(
            sa.or_(
                sa.and_(
                    Follow.follower_id == blocker_id,
                    Follow.followee_id == blocked_id,
                ),
                sa.and_(
                    Follow.follower_id == blocked_id,
                    Follow.followee_id == blocker_id,
                ),
            )
        )
    )
    await db.commit()


async def unblock(
    db: AsyncSession, *, blocker_id: uuid.UUID, blocked_id: uuid.UUID
) -> None:
    """Lift a block. Follows severed by it stay severed: the relationship
    was ended, not suspended, and rebuilding it is a new choice."""
    await db.execute(
        sa.delete(Block).where(
            Block.blocker_id == blocker_id, Block.blocked_id == blocked_id
        )
    )
    await db.commit()


async def blocked_ids(db: AsyncSession, *, user_id: uuid.UUID) -> set[uuid.UUID]:
    """People this user has blocked. The blocker's own list."""
    return set(
        await db.scalars(sa.select(Block.blocked_id).where(Block.blocker_id == user_id))
    )


async def hidden_either_way(
    db: AsyncSession, *, user_id: uuid.UUID
) -> set[uuid.UUID]:
    """Everyone a block connects to this user, in either direction.

    The set every cross-user read subtracts. Both directions, because a
    one-way filter would show the blocked person the blocker's saves and
    make the asymmetry itself the disclosure.
    """
    rows = await db.execute(
        sa.select(Block.blocker_id, Block.blocked_id).where(
            sa.or_(Block.blocker_id == user_id, Block.blocked_id == user_id)
        )
    )
    out: set[uuid.UUID] = set()
    for blocker, blocked in rows:
        out.add(blocked if blocker == user_id else blocker)
    return out


async def has_blocked(
    db: AsyncSession, *, blocker_id: uuid.UUID, blocked_id: uuid.UUID
) -> bool:
    return await db.get(Block, (blocker_id, blocked_id)) is not None


async def report(
    db: AsyncSession,
    *,
    reporter_id: uuid.UUID,
    subject_kind: str,
    subject_user_id: uuid.UUID | None,
    subject_ref: str | None,
    reason: str,
    note: str | None,
    guideline_id: str | None = None,
) -> uuid.UUID:
    """Record a report for the moderation queue. Returns its id.

    `guideline_id` is the specific rule the reporter says was broken,
    validated against the one list in `app.domain.guidelines`. Optional,
    because a report with only a coarse reason is still a report worth
    having and refusing it would lose it.
    """
    if subject_kind not in REPORT_SUBJECTS:
        raise BadReport(f"{subject_kind!r} is not something that can be reported.")
    if reason not in REPORT_REASONS:
        raise BadReport(f"{reason!r} is not a reason on the list.")
    if subject_kind == "account" and subject_user_id is None:
        raise BadReport("An account report must name the account.")
    if subject_kind in ("look", "post", "comment") and not (subject_ref or "").strip():
        raise BadReport("A content report must name its subject.")

    cited = (guideline_id or "").strip() or None
    if cited is not None:
        from app.domain.guidelines import by_id

        rule = by_id(cited)
        if rule is None or not rule.reportable:
            raise BadReport(f"{cited!r} is not a guideline that can be reported.")

    row = Report(
        guideline_id=cited,
        reporter_id=reporter_id,
        subject_kind=subject_kind,
        subject_user_id=subject_user_id,
        subject_ref=(subject_ref or "").strip()[:64] or None,
        reason=reason,
        note=(note or "").strip()[:500] or None,
    )
    db.add(row)
    await db.commit()
    return row.id


__all__ = [
    "BadReport",
    "CannotBlockSelf",
    "block",
    "blocked_ids",
    "has_blocked",
    "hidden_either_way",
    "report",
    "unblock",
]
