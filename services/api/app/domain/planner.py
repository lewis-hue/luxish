"""Planning what to wear, by date.

Small on purpose. A planner is mostly a calendar, and the parts worth being
careful about are the ones where a calendar quietly lies:

**A window, bounded.** A client asks for a range and gets exactly that range.
Without a cap, "from 1900 to 2200" is a query that scans a table; with one, a
client that asks for too much is told rather than served slowly.

**A date is a day, not an instant.** Everything here is `date`, never
`datetime`. A plan made for Thursday must still be Thursday after a flight,
and the only way to guarantee that is for no timezone to ever touch it.

**Planning is idempotent; un-planning is a delete.** `PUT` states what is
planned for a day, so tapping a look twice plans it once. Nothing accumulates,
so nothing has to be de-duplicated later.

**"Did you wear it" is three-valued.** Null is not "no". A plan for next
Tuesday has not been declined, it has not happened, and collapsing those two
would make every future plan look rejected.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date as date_type
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.garment import Garment
from app.models.posts import Post, shown_to_strangers
from app.models.outfit_plan import OutfitPlan, OutfitPlanItem

#: The longest range one request may ask for.
#:
#: A year. Long enough for any view a calendar offers, short enough that a
#: malformed range is refused rather than served.
MAX_RANGE_DAYS = 366

#: How long a note may be. Mirrors the column.
MAX_NOTE = 200


class RangeTooLong(ApiError):
    status_code = 422
    code = "range_too_long"
    default_message = "That is a longer stretch than one request may ask for."


async def plans_between(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start: date_type,
    end: date_type,
) -> Sequence[OutfitPlan]:
    """Every plan in a range, earliest first. Inclusive at both ends.

    Inclusive because a week view asks for Monday to Sunday and means it;
    a half-open range here would silently drop Sunday, which is the day
    somebody is most likely to be planning for.
    """
    if end < start:
        start, end = end, start
    if (end - start) > timedelta(days=MAX_RANGE_DAYS):
        raise RangeTooLong(
            f"{(end - start).days} days exceeds the {MAX_RANGE_DAYS} a single "
            "request may cover."
        )

    result = await session.scalars(
        sa.select(OutfitPlan)
        .where(
            OutfitPlan.user_id == user_id,
            OutfitPlan.planned_for >= start,
            OutfitPlan.planned_for <= end,
        )
        .order_by(OutfitPlan.planned_for.asc())
    )
    return result.all()


class NotYourGarment(ApiError):
    """A garment id that is not in this person's wardrobe."""

    def __init__(self) -> None:
        super().__init__(
            "Those are not all your clothes.",
            status_code=404,
            code="not_found",
        )


async def garments_in(
    session: AsyncSession, *, plan_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """The garments on each plan, in the order they were added.

    One query for a whole month. A planner asking per day is thirty
    round trips to draw one screen.
    """
    if not plan_ids:
        return {}
    rows = (
        await session.execute(
            sa.select(OutfitPlanItem.plan_id, OutfitPlanItem.garment_id)
            .join(Garment, Garment.id == OutfitPlanItem.garment_id)
            # Still owned, and not tombstoned. The foreign key cascade
            # covers a row that is actually deleted; a garment here is
            # soft-deleted, so the cascade never fires and a plan would
            # go on naming clothes somebody has thrown out.
            .where(
                OutfitPlanItem.plan_id.in_(list(plan_ids)),
                Garment.deleted_at.is_(None),
            )
            .order_by(OutfitPlanItem.plan_id, OutfitPlanItem.position)
        )
    ).all()
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for plan_id, garment_id in rows:
        out.setdefault(plan_id, []).append(garment_id)
    return out


async def _theirs(
    session: AsyncSession, *, user_id: uuid.UUID, garment_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """The ids, checked against the wardrobe they claim to come from.

    The house rule, and the reason it exists: an id in a request is
    re-validated against the requesting user before it is persisted or
    rendered. Order is the caller's, because a plan is a composition.
    """
    wanted = list(dict.fromkeys(garment_ids))
    if not wanted:
        return []
    found = set(
        (
            await session.scalars(
                sa.select(Garment.id).where(
                    Garment.id.in_(wanted),
                    Garment.user_id == user_id,
                    Garment.deleted_at.is_(None),
                )
            )
        ).all()
    )
    if len(found) != len(wanted):
        raise NotYourGarment()
    return wanted


async def _referenceable(
    session: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The post id, checked against what this person may actually see.

    **The house rule, and it was missed once here.** An id in a
    request is re-validated against the requesting user before it is
    persisted or rendered - which `_theirs` does for the garments,
    directly above. `reference_post_id` arrived later and was written
    straight through, so a plan could name any post in the database:
    somebody else's private fit, a removed one, an id guessed
    outright. The media gate meant the picture itself stayed
    unreadable, but the plan still carried the id and its cover id
    back out, and an unvalidated foreign key sitting beside a
    validated one is how the next convenience join becomes a leak.

    `shown_to_strangers` is the same predicate the feed, search,
    boards and profiles use, so a fit that is taken private is
    unreferenceable everywhere at once. The author is let through to
    their own, for the reason that rule names: a fit their profile
    still lists has to be usable by the person who posted it.
    """
    if post_id is None:
        return None
    found = await session.scalar(
        sa.select(Post.id).where(
            Post.id == post_id,
            Post.deleted_at.is_(None),
            sa.or_(shown_to_strangers(), Post.user_id == user_id),
        )
    )
    return found

async def covers_for(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    post_ids: Sequence[uuid.UUID | None],
) -> dict[uuid.UUID, uuid.UUID]:
    """The cover photograph of each referenced fit, by post id.

    One query for a whole range, mirroring `garments_in`: a month of
    plans asking per day is thirty round trips to draw one screen.

    **Checked on every read, not only when the plan was written.**
    Validating at write time is not enough on its own: a fit that was
    public when somebody planned a day from it can be taken private,
    removed by a moderator or deleted afterwards, and a reference
    stored months ago would go on handing out its cover. The
    predicate is the one the feed and the profiles use, so the three
    agree by construction.

    A fit that is no longer visible simply has no entry, and the day
    keeps its clothes and loses the picture - the same outcome
    `ondelete="SET NULL"` gives when the post is deleted outright.
    """
    wanted = [post_id for post_id in post_ids if post_id is not None]
    if not wanted:
        return {}

    from app.models.posts import PostMedia

    rows = (
        await session.execute(
            sa.select(PostMedia.post_id, PostMedia.media_asset_id)
            .join(Post, Post.id == PostMedia.post_id)
            .where(
                PostMedia.post_id.in_(wanted),
                PostMedia.position == 0,
                Post.deleted_at.is_(None),
                # The author still sees their own, for the reason
                # `shown_to_strangers` names: a fit their profile
                # lists has to be usable by the person who posted it.
                sa.or_(shown_to_strangers(), Post.user_id == user_id),
            )
        )
    ).all()
    return {post_id: asset_id for post_id, asset_id in rows}

async def plan_day(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    day: date_type,
    garment_ids: Sequence[uuid.UUID],
    note: str | None = None,
    worn: bool | None = None,
    reference_post_id: uuid.UUID | None = None,
) -> OutfitPlan:
    """Plan one day. Idempotent, and never silently loses a note.

    A second `PUT` without a note must not blank one somebody wrote, for the
    same reason a re-save must not blank a saved look's note: omitting a
    field means "I am not talking about it". An empty string clears it, which
    is a thing somebody does rather than a side effect.

    Changing the clothes keeps the note, because the note is usually about
    the occasion - "Dad's birthday" - and the occasion does not change when
    somebody picks a different outfit for it.

    The garments replace what was there rather than adding to it: the
    request describes the day, and a client that had to diff would have
    to know what was already planned before it could change anything.
    """
    checked = await _theirs(session, user_id=user_id, garment_ids=garment_ids)
    # The same rule the garments go through, for the same reason.
    # Silently dropped rather than refused: the reference is context
    # for a day, and a plan somebody made should not fail because the
    # fit that prompted it has since come down.
    reference = await _referenceable(
        session, user_id=user_id, post_id=reference_post_id
    )

    existing = await session.scalar(
        sa.select(OutfitPlan).where(
            OutfitPlan.user_id == user_id, OutfitPlan.planned_for == day
        )
    )
    cleaned = (note.strip()[:MAX_NOTE] or None) if note is not None else None

    if existing is None:
        existing = OutfitPlan(
            user_id=user_id,
            planned_for=day,
            note=cleaned,
            worn=worn,
            reference_post_id=reference,
        )
        session.add(existing)
        await session.flush()
    else:
        if note is not None:
            existing.note = cleaned
        if worn is not None:
            existing.worn = worn
        # Omitting it means "not talking about it", the same rule the
        # note follows: re-saving a day's clothes must not quietly
        # drop the picture it was planned from.
        if reference is not None:
            existing.reference_post_id = reference
        await session.execute(
            sa.delete(OutfitPlanItem).where(OutfitPlanItem.plan_id == existing.id)
        )

    for position, garment_id in enumerate(checked):
        session.add(
            OutfitPlanItem(
                plan_id=existing.id, garment_id=garment_id, position=position
            )
        )
    await session.commit()
    await session.refresh(existing)
    return existing


async def unplan_day(
    session: AsyncSession, *, user_id: uuid.UUID, day: date_type
) -> bool:
    """Clear one day. Returns whether anything was there to clear."""
    result = await session.execute(
        sa.delete(OutfitPlan).where(
            OutfitPlan.user_id == user_id, OutfitPlan.planned_for == day
        )
    )
    await session.commit()
    return bool(result.rowcount)


async def mark_worn(
    session: AsyncSession, *, user_id: uuid.UUID, day: date_type, worn: bool
) -> OutfitPlan | None:
    """Answer "did you wear it". Returns None when nothing was planned."""
    existing = await session.scalar(
        sa.select(OutfitPlan).where(
            OutfitPlan.user_id == user_id, OutfitPlan.planned_for == day
        )
    )
    if existing is None:
        return None
    existing.worn = worn
    await session.commit()
    await session.refresh(existing)
    return existing


__all__ = [
    "MAX_NOTE",
    "MAX_RANGE_DAYS",
    "RangeTooLong",
    "mark_worn",
    "plan_day",
    "plans_between",
    "unplan_day",
]
