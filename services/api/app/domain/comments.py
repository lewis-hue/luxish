"""Writing and reading comments under a fit.

**The fit has to be visible before anything is written.** Same gate as
every other thing that touches a post: `feed.one`. Without it, a comment
is a way to reach somebody who blocked you, which is the single thing a
block is for.

**A comment is held until the screen agrees.** Its author always sees
their own, in whatever state it is in, because a comment that vanishes on
submission reads as a bug and invites a second attempt. Everyone else sees
it once it is published. An unavailable screen holds.

**An unambiguous breach is refused instantly, with no model call.** A
phone number or a shop link cannot be a remark about clothes, so there
is nothing to weigh and no reason to make somebody wait to be told. The
check is deliberately narrow (`guidelines.obvious_violation`): it never
holds something a model would have passed, and everything it has no
opinion about still goes to the screen.

**Blocks hide a thread in both directions.** Somebody you blocked does not
see your comments and you do not see theirs, which is the same rule the
board already applies to fits.

**One level of replies.** A reply to a reply is flattened onto the parent
rather than refused: the person was answering a conversation, and losing
their words to enforce a shape would be the wrong trade.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import feed
from app.domain.jobs import enqueue
from app.domain.moderation import hidden_either_way
from app.models.comment import MAX_COMMENT, CommentLike, PostComment
from app.models.user import User

#: Routed to the AI queue by prefix, like every other screened text.
COMMENT_SCREEN_JOB_KIND = "comment.screen"

#: The most comments one read returns.
PAGE = 100

#: The most comments one person may leave on one fit in a breath.
#:
#: This used to count comments sitting in `pending_review`, which was a
#: good proxy while every comment waited there. Nothing waits there now
#: - they publish on write - so the guard watches a window instead. The
#: thing it is for is unchanged: a loop that posts faster than the
#: screener runs is a client fault and a bill, and both are better
#: refused than absorbed.
MAX_PENDING_PER_POST = 5

#: How long that allowance is counted over.
BURST_WINDOW_SECONDS = 60


class FitNotVisible(Exception):
    """No such fit, as far as this writer is concerned."""


class EmptyComment(Exception):
    """Nothing but whitespace."""


class TooManyPending(Exception):
    """This person already has comments waiting on this fit."""


class NotYourComment(Exception):
    """Not theirs to delete."""


@dataclass(frozen=True)
class CommentView:
    comment: PostComment
    author_id: uuid.UUID
    author_name: str
    #: True when this reader wrote it, which decides whether they see a
    #: held one and whether they may delete it.
    mine: bool
    #: How many people liked it, and whether this reader is one.
    likes: int = 0
    liked_by_me: bool = False


async def visible(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID
) -> list[CommentView]:
    """A fit's comments, oldest first, as this reader may see them.

    Published ones from everybody, plus this reader's own whatever state
    they are in. Their own held comment showing with its reason is the
    difference between "we are checking this" and silent deletion.
    """
    if await feed.one(db, user_id=user_id, post_id=post_id) is None:
        raise FitNotVisible()

    hidden = await hidden_either_way(db, user_id=user_id)

    query = (
        sa.select(PostComment, User)
        .join(User, User.id == PostComment.user_id)
        .where(
            PostComment.post_id == post_id,
            PostComment.deleted_at.is_(None),
            User.deleted_at.is_(None),
            sa.or_(
                PostComment.state == "published",
                PostComment.user_id == user_id,
            ),
        )
        .order_by(PostComment.created_at.asc())
        .limit(PAGE)
    )
    if hidden:
        query = query.where(PostComment.user_id.not_in(hidden))

    from app.domain.community import first_name

    rows = (await db.execute(query)).all()
    ids = [comment.id for comment, _ in rows]
    # Two queries for the whole thread rather than two per comment: a
    # page of twenty would otherwise be forty round trips to draw one
    # sheet.
    tally: dict[uuid.UUID, int] = {}
    mine_liked: set[uuid.UUID] = set()
    if ids:
        tally = {
            row.comment_id: int(row.likes)
            for row in await db.execute(
                sa.select(
                    CommentLike.comment_id,
                    sa.func.count().label("likes"),
                )
                .where(CommentLike.comment_id.in_(ids))
                .group_by(CommentLike.comment_id)
            )
        }
        mine_liked = set(
            await db.scalars(
                sa.select(CommentLike.comment_id).where(
                    CommentLike.comment_id.in_(ids),
                    CommentLike.user_id == user_id,
                )
            )
        )

    return [
        CommentView(
            comment=comment,
            author_id=comment.user_id,
            author_name=first_name(author),
            mine=comment.user_id == user_id,
            likes=tally.get(comment.id, 0),
            liked_by_me=comment.id in mine_liked,
        )
        for comment, author in rows
    ]


async def set_liked(
    db: AsyncSession, *, user_id: uuid.UUID, comment_id: uuid.UUID, liked: bool
) -> int:
    """Like a comment, or take it back. Returns the new tally.

    Refused for a comment this reader cannot see, by the same rule that
    governs reading one: a like is a way of confirming an id exists, so
    it goes through the same gate rather than trusting the id.

    Idempotent in both directions. Liking twice is liking once, and
    un-liking something never liked is work that is already done.
    """
    comment = await db.scalar(
        sa.select(PostComment).where(
            PostComment.id == comment_id,
            PostComment.deleted_at.is_(None),
        )
    )
    if comment is None:
        raise NotYourComment()
    # The gate the thread itself reads through, so a comment on a fit
    # that is gone or whose author is blocked cannot be liked from a
    # stale screen.
    #
    # A fit nobody may see and a comment nobody may see are one answer
    # here, not two: the caller turns `NotYourComment` into a 404, and
    # letting `FitNotVisible` past would be a 500 on a case that is
    # simply refused.
    try:
        seen = await visible(db, user_id=user_id, post_id=comment.post_id)
    except FitNotVisible:
        raise NotYourComment() from None
    if not any(view.comment.id == comment_id for view in seen):
        raise NotYourComment()

    if liked:
        exists = await db.scalar(
            sa.select(CommentLike).where(
                CommentLike.comment_id == comment_id,
                CommentLike.user_id == user_id,
            )
        )
        if exists is None:
            db.add(CommentLike(user_id=user_id, comment_id=comment_id))
    else:
        await db.execute(
            sa.delete(CommentLike).where(
                CommentLike.comment_id == comment_id,
                CommentLike.user_id == user_id,
            )
        )
    await db.commit()

    return int(
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(CommentLike)
            .where(CommentLike.comment_id == comment_id)
        )
        or 0
    )


async def counts(
    db: AsyncSession, post_ids: list[uuid.UUID], *, viewer_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    """How many published comments each fit has, for this reader.

    Counted over what they can see: a number that includes a blocked
    person's comments promises a thread longer than the one they get.
    """
    if not post_ids:
        return {}
    hidden = await hidden_either_way(db, user_id=viewer_id)
    query = (
        sa.select(PostComment.post_id, sa.func.count())
        .join(User, User.id == PostComment.user_id)
        .where(
            PostComment.post_id.in_(post_ids),
            PostComment.state == "published",
            PostComment.deleted_at.is_(None),
            User.deleted_at.is_(None),
        )
        .group_by(PostComment.post_id)
    )
    if hidden:
        query = query.where(PostComment.user_id.not_in(hidden))
    return {row[0]: int(row[1]) for row in (await db.execute(query)).all()}


async def write(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    post_id: uuid.UUID,
    body: str,
    parent_id: uuid.UUID | None = None,
    seeded: bool = False,
) -> PostComment:
    """Leave a comment. Published at once, and scanned after.

    **Optimistic, the way the platforms people are used to behave.** It
    used to be held until a model agreed, so a remark under a
    photograph waited on a vendor round trip and its author watched it
    not appear. The screen still runs, on a worker, and can take the
    comment down - see `app.workers.screen.screen_comment`.

    The one verdict reached before a row exists is
    `obvious_violation`: a phone number or a shop link cannot be a
    remark about clothes, and answering that costs microseconds and no
    model call. It may refuse and may never approve, which is the rule
    it has always had.

    A reply to a reply is attached to the top-level parent rather than
    refused: the person was answering a conversation, and throwing their
    words away to enforce a shape would be the wrong trade.
    """
    if await feed.one(db, user_id=user_id, post_id=post_id) is None:
        raise FitNotVisible()

    text = (body or "").strip()[:MAX_COMMENT]
    if not text:
        raise EmptyComment()

    if not seeded:
        since = datetime.now(UTC) - timedelta(seconds=BURST_WINDOW_SECONDS)
        recent = await db.scalar(
            sa.select(sa.func.count())
            .select_from(PostComment)
            .where(
                PostComment.post_id == post_id,
                PostComment.user_id == user_id,
                PostComment.created_at >= since,
                PostComment.deleted_at.is_(None),
            )
        )
        if int(recent or 0) >= MAX_PENDING_PER_POST:
            raise TooManyPending()

    # The unambiguous cases, answered before anything is queued.
    #
    # A phone number or a shop link cannot be a remark about clothes, so
    # there is nothing for a model to weigh and no reason to make
    # somebody wait three seconds to be told. This is not the screen: a
    # detector with no opinion means only that, and the model still runs
    # on everything it does not catch.
    from app.domain.guidelines import obvious_violation

    broke = None if seeded else obvious_violation(text)

    parent = None
    if parent_id is not None:
        found = await db.scalar(
            sa.select(PostComment).where(
                PostComment.id == parent_id,
                PostComment.post_id == post_id,
                PostComment.deleted_at.is_(None),
            )
        )
        # Flattened to one level, and silently: the alternative is
        # refusing a reply for a reason the person did not ask about.
        parent = found.parent_id or found.id if found is not None else None

    if seeded:
        state, mode, note = "published", "seed", None
    elif broke is not None:
        # Stage one said no, which is the one verdict reached before a
        # row exists. `held` means its author sees it and nobody else.
        state, mode, note = "held", "rules", broke.held_note
    else:
        # Live immediately. The screen still runs on a worker and can
        # take it down; what changed is which side of it a comment sits
        # on while that happens.
        state, mode, note = "published", None, None

    comment = PostComment(
        post_id=post_id,
        user_id=user_id,
        body=text,
        parent_id=parent,
        state=state,
        screen_mode=mode,
        screen_note=note,
    )
    db.add(comment)
    await db.flush()

    if not seeded and broke is None:
        # Rides the same commit. Without it a comment sits in review for
        # ever: the write looks like it worked and the result never
        # comes - the exact failure a bio had before this was wired.
        await enqueue(
            db,
            COMMENT_SCREEN_JOB_KIND,
            {"comment_id": str(comment.id)},
            idempotency_key=f"{COMMENT_SCREEN_JOB_KIND}:{comment.id}",
        )

    await db.commit()
    await db.refresh(comment)
    return comment


async def apply_verdict(
    db: AsyncSession, *, comment_id: uuid.UUID, allowed: bool, note: str
) -> PostComment | None:
    """Record what the screen decided, and take the comment down if no.

    **It acts on a published comment now, not only a waiting one.** The
    comment went up when it was written, so the verdict arrives after
    people may already have seen it. A screen that could only confirm
    what was already visible would be a screen that cannot do anything.

    A comment already `held` is left alone: stage one refused it before
    the model ran, and a model agreeing later must not put it back.
    """
    comment = await db.get(PostComment, comment_id)
    if comment is None or comment.state not in {"pending_review", "published"}:
        return comment
    if allowed:
        comment.state = "published"
        comment.screen_note = None
    else:
        comment.state = "held"
        comment.screen_note = note[:300] or "Held for review."
    comment.screen_mode = "model"
    await db.commit()
    await db.refresh(comment)
    return comment


async def remove(
    db: AsyncSession, *, user_id: uuid.UUID, comment_id: uuid.UUID
) -> bool:
    """Delete your own comment, or one on your own fit.

    Both, because both are true owners of the thing: the person who
    wrote it, and the person whose photograph it sits under. A fit's
    author being unable to remove a comment from their own post would
    make the block the only tool available for a single remark.
    """
    comment = await db.scalar(
        sa.select(PostComment).where(
            PostComment.id == comment_id, PostComment.deleted_at.is_(None)
        )
    )
    if comment is None:
        return False

    if comment.user_id != user_id:
        from app.models.posts import Post

        post = await db.get(Post, comment.post_id)
        if post is None or post.user_id != user_id:
            raise NotYourComment()

    comment.deleted_at = sa.func.now()
    await db.commit()
    return True


__all__ = [
    "COMMENT_SCREEN_JOB_KIND",
    "MAX_PENDING_PER_POST",
    "PAGE",
    "CommentView",
    "EmptyComment",
    "FitNotVisible",
    "NotYourComment",
    "TooManyPending",
    "apply_verdict",
    "counts",
    "remove",
    "visible",
    "write",
]
