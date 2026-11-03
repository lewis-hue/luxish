"""Fit routes: create, the feed, and the author's own ledger.

Creation answers with the truth in a 201: the post exists, in review,
and the response says so. The feed only ever serves `published`.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import posts as domain
from app.domain.community import first_name
from app.errors import ApiError
from app.models.media_asset import MediaAsset
from app.models.user import User
from app.schemas.posts import (
    PostCreatedOut,
    PostCreateIn,
    PostFeedOut,
    PostItemOut,
    PostMineListOut,
    PostMineOut,
    PostOut,
    PostReactIn,
    PostReactionsOut,
    PostSaveOut,
    PostVisibilityIn,
    PostVisibilityOut,
)

router = APIRouter(prefix="/posts", tags=["posts"])


def _items(view: domain.PostView) -> list[PostItemOut]:
    return [
        PostItemOut(
            kind=item.kind,  # type: ignore[arg-type]
            category_id=item.category_id,
            colour=item.colour,
            title=item.title,
            brand=item.brand,
            retailer=item.retailer,
            price_minor=item.price_minor,
            currency=item.currency,
            source_url=item.source_url,
        )
        for item in view.items
    ]


@router.post("", response_model=PostCreatedOut, status_code=status.HTTP_201_CREATED)
async def create(payload: PostCreateIn, db: SessionDep, ctx: AuthDep) -> PostCreatedOut:
    """Publish a fit, into review.

    Media and garment ids are re-validated against the caller's own rows;
    an id belonging to anybody else is a 404, not a 403, so the refusal
    confirms nothing.
    """
    try:
        post = await domain.create_post(
            db,
            user_id=ctx.user_id,
            caption=payload.caption,
            occasion=payload.occasion,
            media_asset_ids=list(payload.media_asset_ids),
            garment_ids=list(payload.garment_ids),
            product_ids=list(payload.product_ids),
        )
    except domain.BadPost as refusal:
        raise ApiError(str(refusal), status_code=422, code="bad_post") from None
    except domain.NotYours:
        raise ApiError(
            "No such item.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    # The real state, not a literal. A fit is live the moment it is
    # posted; hardcoding "pending_review" here meant the response said
    # one thing while the row said another.
    return PostCreatedOut(
        id=post.id,
        state=post.state,  # type: ignore[arg-type]
        note=(
            "Posted. It is on Discover now."
            if post.state == "published"
            else "In review. It appears to others once the screen approves it."
        ),
    )


async def _names(db: SessionDep, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.scalars(sa.select(User).where(User.id.in_(ids)))
    return {user.id: first_name(user) for user in rows}


@router.get("/feed", response_model=PostFeedOut)
async def feed(db: SessionDep, ctx: AuthDep) -> PostFeedOut:
    """Published fits from the people you follow, newest first."""
    views = await domain.feed(db, user_id=ctx.user_id)
    names = await _names(db, {view.author_id for view in views})
    return PostFeedOut(
        items=[
            PostOut(
                id=view.post.id,
                author_id=view.author_id,
                author_name=names.get(view.author_id, "Someone"),
                caption=view.post.caption,
                occasion=view.post.occasion,
                media_asset_ids=list(view.media_asset_ids),
                items=_items(view),
                published_at=view.post.published_at,
                saves=view.saves,
                saved_by_me=view.saved_by_me,
            )
            for view in views
        ]
    )


@router.get("/mine", response_model=PostMineListOut)
async def mine(db: SessionDep, ctx: AuthDep) -> PostMineListOut:
    """Your own fits, with their states and any held note."""
    views = await domain.mine(db, user_id=ctx.user_id)

    # Every cover on the profile in one query, never one per tile.
    first = [view.media_asset_ids[0] for view in views if view.media_asset_ids]
    covers: dict[uuid.UUID, tuple[int | None, int | None]] = {}
    if first:
        covers = {
            asset_id: (width, height)
            for asset_id, width, height in (
                await db.execute(
                    sa.select(
                        MediaAsset.id, MediaAsset.width, MediaAsset.height
                    ).where(MediaAsset.id.in_(first))
                )
            ).all()
        }

    def ratio(view: domain.PostView) -> float | None:
        """Width over height, when both are known and neither is zero."""
        if not view.media_asset_ids:
            return None
        size = covers.get(view.media_asset_ids[0])
        if size is None:
            return None
        width, height = size
        if not width or not height:
            return None
        return round(width / height, 4)

    return PostMineListOut(
        items=[
            PostMineOut(
                id=view.post.id,
                author_id=view.author_id,
                author_name="You",
                caption=view.post.caption,
                occasion=view.post.occasion,
                media_asset_ids=list(view.media_asset_ids),
                items=_items(view),
                published_at=view.post.published_at,
                saves=view.saves,
                saved_by_me=view.saved_by_me,
                state=view.post.state,  # type: ignore[arg-type]
                visibility=view.post.visibility,  # type: ignore[arg-type]
                cover_ratio=ratio(view),
                screen_mode=view.post.screen_mode,
                screen_note=view.post.screen_note,
                created_at=view.post.created_at,
            )
            for view in views
        ]
    )


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(post_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Take a fit down. Only the author can, and only theirs."""
    removed = await domain.remove(db, user_id=ctx.user_id, post_id=post_id)
    if not removed:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )


@router.put("/{post_id}/visibility", response_model=PostVisibilityOut)
async def visibility(
    post_id: uuid.UUID, payload: PostVisibilityIn, db: SessionDep, ctx: AuthDep
) -> PostVisibilityOut:
    """Show this fit to people, or stop. Only the author can.

    Separate from deleting, because they are different decisions: a
    private fit is still the author's and still theirs to put back,
    and somebody who only wanted it off the board should not have to
    destroy it to get that.

    404 for a fit that is not theirs, the same answer as for one that
    does not exist - otherwise this would report whether a given id is
    somebody's post.
    """
    post = await domain.set_visibility(
        db, user_id=ctx.user_id, post_id=post_id, visibility=payload.visibility
    )
    if post is None:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    return PostVisibilityOut(
        id=post.id,
        visibility=post.visibility,  # type: ignore[arg-type]
    )


@router.put("/{post_id}/save", response_model=PostSaveOut)
async def save(post_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> PostSaveOut:
    """Keep a fit. Idempotent, so a double tap is not an error."""
    count = await domain.set_saved(
        db, user_id=ctx.user_id, post_id=post_id, saved=True
    )
    if count is None:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    return PostSaveOut(saves=count, saved_by_me=True)


@router.delete("/{post_id}/save", response_model=PostSaveOut)
async def unsave(post_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> PostSaveOut:
    """Forget a fit. Idempotent in the same way."""
    count = await domain.set_saved(
        db, user_id=ctx.user_id, post_id=post_id, saved=False
    )
    if count is None:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    return PostSaveOut(saves=count, saved_by_me=False)


@router.put("/{post_id}/reaction", response_model=PostReactionsOut)
async def react(
    post_id: uuid.UUID, payload: PostReactIn, db: SessionDep, ctx: AuthDep
) -> PostReactionsOut:
    """React to a fit, change the reaction, or take it back with `null`.

    One per person, replaced rather than added to: a tally one
    enthusiast can run up by pressing five buttons measures nothing.
    """
    try:
        counts = await domain.set_reaction(
            db, user_id=ctx.user_id, post_id=post_id, kind=payload.kind
        )
    except domain.BadPost as refusal:
        raise ApiError(str(refusal), status_code=422, code="bad_reaction") from None
    if counts is None:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    return PostReactionsOut(
        counts=counts, total=sum(counts.values()), mine=payload.kind
    )
