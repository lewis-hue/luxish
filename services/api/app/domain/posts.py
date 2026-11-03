"""Creating, screening and reading fits.

**Publication is an explicit act with a gate after it.** Creating a post
is the author saying "show this to strangers" — that is when their
garment ids and media ids are re-validated against their own wardrobe
(the house non-negotiable) — but nothing becomes visible until the
screening job agrees. The job failing, or not existing, holds the post:
review is a precondition, not a decoration.

**Who may read a photograph is derived, never a stored flag.** The first
version of this set `publication_consent` on publish and let the delivery
route serve anything carrying it. That flag is sticky: deleting a fit, a
moderator removing it, or blocking its author all left the bytes readable
forever by anyone who had seen the asset id in a feed payload — so
"delete" did not un-publish. :func:`media_is_published_to` answers the
question live instead, from a post that is published *now*, not deleted,
and whose author is not blocked either way. `publication_consent` is
still written, because it is a true record of the author's act, but it
is no longer sufficient for access and nothing may treat it as such.

**What crosses to strangers is enumerated.** A published post exposes:
the screened caption, the screened photographs, taxonomy facts about
tagged garments (category and colour, never the owner-written name),
curated product cards, a look id, an occasion from the taste vocabulary,
and the author's first name. Nothing else has a field to travel in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import jobs
from app.domain.moderation import hidden_either_way
from app.domain.taste import OCCASIONS
from app.models.follow import Follow
from app.models.garment import Garment
from app.models.media_asset import MediaAsset
from app.models.posts import (
    MAX_CAPTION,
    MAX_POST_ITEMS,
    MAX_POST_MEDIA,
    POST_VISIBILITIES,
    Post,
    PostItem,
    PostMedia,
    PostSave,
    shown_to_strangers,
)
from app.models.shopping import Offer, Retailer, ShopProduct
from app.models.user import User

#: The screening job. One per post, idempotent on the post id.
SCREEN_JOB_KIND = "post.screen"

FEED_LIMIT = 30


#: Media kinds a fit may publish. An avatar is a picture of a person and
#: needs its own thinking; inspiration is somebody else's material.
PUBLISHABLE_KINDS = frozenset({"garment_photo", "garment_render", "outfit_photo"})


class BadPost(Exception):
    """Refused before a row exists. The message says why."""


class NotYours(Exception):
    """A media or garment id that does not belong to the author."""


@dataclass(frozen=True, slots=True)
class ItemOut:
    """One tagged item, as a stranger may see it."""

    kind: str  # "garment" | "product" | "gone"
    category_id: str | None = None
    colour: str | None = None
    title: str | None = None
    brand: str | None = None
    retailer: str | None = None
    price_minor: int | None = None
    currency: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class PostView:
    post: Post
    author_id: uuid.UUID
    media_asset_ids: tuple[uuid.UUID, ...]
    items: tuple[ItemOut, ...] = field(default_factory=tuple)
    #: How many people kept this fit, and whether the reader is one of
    #: them. Counted from the rows rather than stored on the post, for the
    #: same reason every other count here is: a column would be a second
    #: copy of the truth that a retry could double.
    saves: int = 0
    saved_by_me: bool = False


async def create_post(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    caption: str | None,
    occasion: str | None,
    media_asset_ids: list[uuid.UUID],
    garment_ids: list[uuid.UUID],
    product_ids: list[uuid.UUID],
    #: Written alongside anything hashtagged in the caption. The author's
    #: own statement of what this is, which is better evidence than
    #: anything inferred from the picture.
    tags: list[str] | None = None,
) -> Post:
    cleaned_caption = (caption or "").strip()[:MAX_CAPTION] or None

    if occasion is not None and occasion not in OCCASIONS:
        raise BadPost(f"{occasion!r} is not an occasion this app knows.")
    if not media_asset_ids:
        raise BadPost("A fit needs at least one photograph.")
    if len(media_asset_ids) > MAX_POST_MEDIA:
        raise BadPost(f"A fit carries at most {MAX_POST_MEDIA} photographs.")
    if len(garment_ids) + len(product_ids) > MAX_POST_ITEMS:
        raise BadPost(f"A fit carries at most {MAX_POST_ITEMS} tagged items.")

    # Re-validated against the author's own rows, not trusted from the
    # client. The ids arrive from a device; what they must be is theirs.
    for asset_id in media_asset_ids:
        asset = await db.scalar(
            sa.select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.user_id == user_id,
                MediaAsset.deleted_at.is_(None),
                MediaAsset.status.in_(("uploaded", "ready")),
            )
        )
        if asset is None or asset.kind not in PUBLISHABLE_KINDS:
            raise NotYours
    for garment_id in garment_ids:
        owned = await db.scalar(
            sa.select(Garment.id).where(
                Garment.id == garment_id,
                Garment.user_id == user_id,
                Garment.deleted_at.is_(None),
            )
        )
        if owned is None:
            raise NotYours
    for product_id in product_ids:
        exists = await db.scalar(
            sa.select(ShopProduct.id).where(ShopProduct.id == product_id)
        )
        if exists is None:
            raise BadPost("That product is not in the catalogue.")

    # The unambiguous cases, refused before anything is written. A
    # caption carrying a phone number or a shop link is not a fit
    # caption, and the check is deterministic and free.
    from app.domain.guidelines import obvious_violation

    broke = obvious_violation(cleaned_caption or "")
    if broke is not None:
        raise BadPost(broke.held_note)

    post = Post(
        user_id=user_id,
        caption=cleaned_caption,
        occasion=occasion,
        # Live immediately. The screen still runs and can take it
        # down; what changed is which side of it the post sits on.
        state="published",
        published_at=datetime.now(UTC),
    )
    db.add(post)
    await db.flush()
    for position, asset_id in enumerate(media_asset_ids):
        db.add(PostMedia(post_id=post.id, media_asset_id=asset_id, position=position))
    position = 0
    for garment_id in garment_ids:
        db.add(PostItem(post_id=post.id, garment_id=garment_id, position=position))
        position += 1
    for product_id in product_ids:
        db.add(PostItem(post_id=post.id, product_id=product_id, position=position))
        position += 1

    # Hashtags, in the same commit. They are what Discover groups by, so
    # a post that existed without them would be invisible on the board
    # until somebody edited it.
    from app.domain.feed import normalise_tag, tags_in
    from app.models.profile import MAX_TAGS_PER_POST, PostTag

    found: list[str] = tags_in(caption)
    for raw in tags or []:
        tag = normalise_tag(raw)
        if tag and tag not in found:
            found.append(tag)
    for tag in found[:MAX_TAGS_PER_POST]:
        db.add(PostTag(post_id=post.id, tag=tag))

    # Recorded as the author's act, at the moment they published. This
    # used to happen when the screen approved; a fit that is live the
    # instant it is posted needs it then, or its photographs are not
    # readable by the people already looking at them.
    for asset_id in media_asset_ids:
        asset = await db.get(MediaAsset, asset_id)
        if asset is not None and asset.user_id == user_id:
            asset.publication_consent = True

    # The job rides the same commit as the post. It is a check *after*
    # publication now rather than a gate before it, and it can still
    # withdraw a fit.
    await jobs.enqueue(
        db,
        SCREEN_JOB_KIND,
        {"post_id": str(post.id)},
        idempotency_key=f"post-screen:{post.id}",
    )

    # And the cover brought into the shape the app draws it in.
    #
    # **A job rather than part of the upload.** In a deployment the
    # client PUTs straight to object storage and this service never
    # sees the bytes, so there is no request during which a picture
    # could be reshaped - reading it back out is the only place the
    # work can happen, and it is the same place in both
    # environments.
    #
    # Pixels only, so no model call and no cost. A picture already
    # inside the shell is left untouched, which is almost all of
    # them.
    from app.workers.post_shape import SHAPE_JOB_KIND

    await jobs.enqueue(
        db,
        SHAPE_JOB_KIND,
        {"post_id": str(post.id)},
        idempotency_key=f"post-shape:{post.id}",
    )
    # What the picture is OF, read off the picture.
    #
    # Queued on publish rather than on first view, because the window
    # a mislabelled pin does its damage in is its first hours - while
    # nobody has boarded it yet, so there is no crowd opinion to
    # overrule the author's hashtags with.
    from app.workers.post_vision import VISION_JOB_KIND

    await jobs.enqueue(
        db,
        VISION_JOB_KIND,
        {"post_id": str(post.id)},
        idempotency_key=f"post-vision:{post.id}",
    )
    return post


async def apply_screen_verdict(
    db: AsyncSession,
    *,
    post_id: uuid.UUID,
    allowed: bool,
    mode: str,
    note: str | None = None,
    now: datetime | None = None,
) -> Post | None:
    """Record the screen's answer. Publishing flips media consent too."""
    post = await db.get(Post, post_id)
    if post is None or post.deleted_at is not None:
        return None
    # A published fit is the normal case now: the screen runs after
    # publication, so its job is to withdraw one that should not have
    # gone out rather than to release one that was waiting.
    if post.state not in ("pending_review", "held", "published"):
        return post

    moment = now or datetime.now(UTC)
    post.screen_mode = mode
    if allowed:
        post.state = "published"
        post.published_at = moment
        post.screen_note = None
        # Recorded as the author's act, not used as an access grant: see
        # `media_is_published_to` for why a sticky flag was the wrong gate.
        media_ids = list(
            await db.scalars(
                sa.select(PostMedia.media_asset_id).where(
                    PostMedia.post_id == post.id
                )
            )
        )
        if media_ids:
            await db.execute(
                sa.update(MediaAsset)
                .where(MediaAsset.id.in_(media_ids))
                .values(publication_consent=True)
            )
    else:
        post.state = "held"
        post.screen_note = (note or "Held for review.")[:300]
    await db.commit()
    return post


async def items_for(db: AsyncSession, *, post_id: uuid.UUID) -> list[ItemOut]:
    """What a fit is made of, as the pieces a stranger may be shown.

    **Extracted so one answer serves both screens.** The profile's own
    list built this and the fit's page did not, which is why "Shop the
    look" on a pin had nothing to point at and fell through to generic
    recommendations under a label promising that look.

    Taxonomy facts only for a garment: the free-text name an owner
    typed is not screened and never travels. A piece whose garment or
    product has since gone is reported as `gone` rather than dropped,
    so a look does not quietly lose a slot.
    """
    rows = (
        await db.scalars(
            sa.select(PostItem)
            .where(PostItem.post_id == post_id)
            .order_by(PostItem.position)
        )
    ).all()
    items: list[ItemOut] = []
    for row in rows:
        if row.garment_id is not None:
            garment = await db.get(Garment, row.garment_id)
            if garment is None or garment.deleted_at is not None:
                items.append(ItemOut(kind="gone"))
            else:
                confirmed = garment.confirmed_attributes or {}
                inferred = garment.inferred_attributes or {}
                items.append(
                    ItemOut(
                        kind="garment",
                        category_id=garment.category,
                        # Taxonomy facts only: the free-text name an
                        # owner typed is not screened and not sent.
                        colour=str(
                            confirmed.get("colour")
                            or inferred.get("colour")
                            or ""
                        )
                        or None,
                    )
                )
        elif row.product_id is not None:
            product = await db.get(ShopProduct, row.product_id)
            if product is None:
                items.append(ItemOut(kind="gone"))
            else:
                offer = await db.scalar(
                    sa.select(Offer).where(Offer.product_id == product.id)
                )
                retailer = await db.scalar(
                    sa.select(Retailer).where(Retailer.id == product.retailer_id)
                )
                items.append(
                    ItemOut(
                        kind="product",
                        category_id=product.category_id,
                        colour=product.colour,
                        title=product.title,
                        brand=product.brand,
                        retailer=retailer.name if retailer else None,
                        price_minor=offer.price_minor if offer else None,
                        currency=offer.currency if offer else None,
                        source_url=offer.source_url if offer else None,
                    )
                )
        else:
            items.append(ItemOut(kind="gone"))
    return items


async def _views(
    db: AsyncSession, posts: list[Post], *, viewer_id: uuid.UUID
) -> list[PostView]:
    out: list[PostView] = []
    for post in posts:
        media = list(
            await db.scalars(
                sa.select(PostMedia.media_asset_id)
                .where(PostMedia.post_id == post.id)
                .order_by(PostMedia.position)
            )
        )
        items = await items_for(db, post_id=post.id)
        saves = int(
            await db.scalar(
                sa.select(sa.func.count())
                .select_from(PostSave)
                .where(PostSave.post_id == post.id)
            )
            or 0
        )
        mine = (
            await db.get(PostSave, (viewer_id, post.id))
        ) is not None
        out.append(
            PostView(
                post=post,
                author_id=post.user_id,
                media_asset_ids=tuple(media),
                items=tuple(items),
                saves=saves,
                saved_by_me=mine,
            )
        )
    return out


async def media_is_published_to(
    db: AsyncSession, *, viewer_id: uuid.UUID, asset_id: uuid.UUID
) -> bool:
    """Whether a fit that is published **right now** carries this asset.

    Asked per request rather than cached on the asset, because every way
    a photograph stops being public is a change to a post rather than to
    the asset: the author deletes the fit, a moderator removes it, the
    screen holds it again, or the viewer blocks the author. A flag would
    have to be reset on all four paths and would eventually miss one.
    This cannot miss one, because there is nothing to reset.
    """
    from app.domain import feed as feed_domain

    hidden = await hidden_either_way(db, user_id=viewer_id)
    query = (
        sa.select(Post.id)
        .join(PostMedia, PostMedia.post_id == Post.id)
        .join(User, User.id == Post.user_id)
        .where(
            PostMedia.media_asset_id == asset_id,
            Post.state == "published",
            Post.deleted_at.is_(None),
            # Taking a fit private has to reach the bytes too, or the
            # photograph goes on downloading for anybody who noted the
            # asset id while it was public - the same leak one layer
            # down that the author clause below was written for.
            #
            # The author is the exception, and has to be: their own
            # private fits are still shown to them on their profile,
            # and a picture that would not load there would make the
            # setting look like a deletion.
            sa.or_(Post.visibility == "public", Post.user_id == viewer_id),
            User.deleted_at.is_(None),
            # The same clause the feed reads through. Without it, a
            # private account's photographs stayed downloadable by
            # anybody holding an asset id - the feed would decline to
            # show the fit and the bytes would come down anyway, which
            # is the leak one layer below the one you can see.
            feed_domain.visible_author(viewer_id),
        )
        .limit(1)
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    return await db.scalar(query) is not None


async def piece_is_published_to(
    db: AsyncSession, *, viewer_id: uuid.UUID, asset_id: uuid.UUID
) -> bool:
    """Whether a fit published **right now** was the source of this cut-out.

    **The same question as `media_is_published_to`, one join further
    out.** A piece is a garment cut from a post's photograph and kept
    so the stylised figure can wear the real thing rather than a
    redrawing of it. It is not in `post_media` - it is not one of the
    pictures the fit shows - so the gate above answers no for it, and
    without this nobody could read one, including the author.

    Every clause is the one above, deliberately: published now, not
    deleted, public or the author's own, author not deleted, author
    visible, neither party blocked. A piece must become unreadable at
    exactly the moment its fit does, and the only way to be sure of
    that is to ask the same question of the same row.
    """
    from app.domain import feed as feed_domain
    from app.models.fit_description import FitPieceRow

    hidden = await hidden_either_way(db, user_id=viewer_id)
    query = (
        sa.select(Post.id)
        .join(FitPieceRow, FitPieceRow.post_id == Post.id)
        .join(User, User.id == Post.user_id)
        .where(
            FitPieceRow.media_asset_id == asset_id,
            Post.state == "published",
            Post.deleted_at.is_(None),
            sa.or_(Post.visibility == "public", Post.user_id == viewer_id),
            User.deleted_at.is_(None),
            feed_domain.visible_author(viewer_id),
        )
        .limit(1)
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    return await db.scalar(query) is not None


async def feed(db: AsyncSession, *, user_id: uuid.UUID) -> list[PostView]:
    """Published fits from the people this user follows, newest first.

    A published post is its author's explicit act, so no further consent
    gates it; blocks still remove the pair in both directions.

    **A private account's fits are not here either.** Following is
    instant in this app - there is no request to approve - so "their
    followers can still see it" would mean "anybody who taps Follow can
    still see it", which is not a privacy setting. If follow requests
    ever exist, this is the line that gets to change.
    """
    from app.domain import feed as feed_domain
    follows = set(
        await db.scalars(
            sa.select(Follow.followee_id).where(Follow.follower_id == user_id)
        )
    )
    follows -= await hidden_either_way(db, user_id=user_id)
    if not follows:
        return []
    posts = (
        await db.scalars(
            sa.select(Post)
            .join(User, User.id == Post.user_id)
            .where(
                Post.user_id.in_(follows),
                shown_to_strangers(),
                User.deleted_at.is_(None),
                feed_domain.visible_author(user_id),
            )
            .order_by(Post.published_at.desc())
            .limit(FEED_LIMIT)
        )
    ).all()
    return await _views(db, list(posts), viewer_id=user_id)


async def mine(db: AsyncSession, *, user_id: uuid.UUID) -> list[PostView]:
    """The author's own fits, every state, newest first."""
    posts = (
        await db.scalars(
            sa.select(Post)
            .where(Post.user_id == user_id, Post.deleted_at.is_(None))
            .order_by(Post.created_at.desc())
            .limit(FEED_LIMIT)
        )
    ).all()
    return await _views(db, list(posts), viewer_id=user_id)


async def _reachable(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID
) -> Post | None:
    """The fit, if this reader may act on it at all.

    **Writes take the same gate as reads.** Keeping a fit and reacting
    to one both looked the post up directly and checked only blocks, so
    an id was enough to run up the counts on a withdrawn post, a
    deleted author's post, or a private account's - none of which the
    same reader could see. A refusal is `None`, the shape every post
    action uses, so it confirms nothing about what exists.
    """
    from app.domain import feed as feed_domain

    post = await db.scalar(
        sa.select(Post)
        .join(User, User.id == Post.user_id)
        .where(
            Post.id == post_id,
            Post.deleted_at.is_(None),
            # The author reaches their own fit whatever state it is
            # in; everybody else sees only what is published and
            # public.
            #
            # **Both halves were dead ends.** Their profile lists
            # every fit they have posted, held ones included and
            # badged as held - and tapping one answered "This fit is
            # not here", about their own photograph. Private was the
            # same: the setting made the fit unopenable from the page
            # still listing it. Somebody has to be able to open a fit
            # to read why it was held, or to put it back.
            sa.or_(
                sa.and_(
                    Post.state == "published",
                    Post.visibility == "public",
                ),
                Post.user_id == user_id,
            ),
            User.deleted_at.is_(None),
            feed_domain.visible_author(user_id),
        )
    )
    if post is None:
        return None
    if post.user_id in await hidden_either_way(db, user_id=user_id):
        return None
    return post


async def set_saved(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID, saved: bool
) -> int | None:
    """Keep or forget a fit. Returns the new count, or None if unreachable.

    Only a fit the reader can actually see may be kept: an unpublished or
    blocked-away post answers the same `None` a missing one does, so the
    refusal confirms nothing.
    """
    if await _reachable(db, user_id=user_id, post_id=post_id) is None:
        return None

    existing = await db.get(PostSave, (user_id, post_id))
    newly_saved = saved and existing is None
    if newly_saved:
        db.add(PostSave(user_id=user_id, post_id=post_id))
    elif not saved and existing is not None:
        await db.delete(existing)
    await db.commit()

    if newly_saved:
        # Only on the way in, and never to yourself. Keyed on the post
        # so twenty people keeping it is one notification that says
        # twenty, rather than twenty banners.
        post = await db.get(Post, post_id)
        if post is not None and post.user_id != user_id:
            from app.domain import push

            keeper = await db.get(User, user_id)
            who = (keeper.display_name or "Somebody") if keeper else "Somebody"
            await push.notify(
                db,
                user_id=post.user_id,
                kind="fit_saved",
                title="Somebody kept your fit",
                body=f"{who} saved it.",
                subject=str(post_id),
                deep_link=f"/fit/{post_id}",
            )
    return int(
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(PostSave)
            .where(PostSave.post_id == post_id)
        )
        or 0
    )


async def remove(db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user_id or post.deleted_at is not None:
        return False
    post.deleted_at = datetime.now(UTC)
    await db.commit()
    return True


async def set_visibility(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID, visibility: str
) -> Post | None:
    """Show this fit to people, or stop. Only the author may.

    **Not a moderation state, and it must never become one.** Taking a
    fit private is the author saying who it is for; `state` is our
    verdict on whether it may be shown at all. A held fit that is
    switched to public stays held, and a private fit that a moderator
    clears stays private - which is only true because the two live in
    different columns.

    Returns the post, or `None` when there is no such fit of theirs -
    the same answer for somebody else's as for one that never existed,
    so this cannot be used to find out what anybody has posted.
    """
    if visibility not in POST_VISIBILITIES:
        raise BadPost(f"Unknown visibility: {visibility}.")
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user_id or post.deleted_at is not None:
        return None
    post.visibility = visibility
    await db.commit()
    await db.refresh(post)
    return post


__all__ = [
    "BadPost",
    "FEED_LIMIT",
    "ItemOut",
    "NotYours",
    "PUBLISHABLE_KINDS",
    "PostView",
    "SCREEN_JOB_KIND",
    "apply_screen_verdict",
    "create_post",
    "feed",
    "media_is_published_to",
    "mine",
    "remove",
    "set_saved",
    "set_visibility",
]


# --------------------------------------------------------------------------- #
# reactions and hashtags
# --------------------------------------------------------------------------- #


async def set_reaction(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID, kind: str | None
) -> dict[str, int] | None:
    """React to a fit, change the reaction, or take it back.

    **One reaction per person**, replaced rather than added to: a tally
    one enthusiast can run up by pressing five buttons measures nothing.
    Passing `None` removes it.

    Returns the counts per kind, or `None` when the fit is not visible to
    this reader — the same refusal shape as every other post action, so a
    404 confirms nothing.
    """
    from app.models.profile import REACTIONS, PostReaction

    if kind is not None and kind not in REACTIONS:
        raise BadPost(f"Pick one of: {', '.join(REACTIONS)}.")

    if await _reachable(db, user_id=user_id, post_id=post_id) is None:
        return None

    existing = await db.get(PostReaction, (user_id, post_id))
    if kind is None:
        if existing is not None:
            await db.delete(existing)
    elif existing is None:
        db.add(PostReaction(user_id=user_id, post_id=post_id, kind=kind))
    else:
        existing.kind = kind
    await db.commit()

    rows = (
        await db.execute(
            sa.select(PostReaction.kind, sa.func.count())
            .where(PostReaction.post_id == post_id)
            .group_by(PostReaction.kind)
        )
    ).all()
    return {str(name): int(count) for name, count in rows}


async def set_tags(
    db: AsyncSession, *, post_id: uuid.UUID, caption: str | None, extra: list[str]
) -> list[str]:
    """Record a fit's hashtags, from its caption and anything passed.

    Written as rows rather than re-parsed per read: this is the join
    Discover groups by, and deriving it per query would make the feed's
    cost a function of how much people write.
    """
    from app.domain.feed import normalise_tag, tags_in
    from app.models.profile import MAX_TAGS_PER_POST, PostTag

    tags: list[str] = tags_in(caption)
    for raw in extra:
        tag = normalise_tag(raw)
        if tag and tag not in tags:
            tags.append(tag)
    tags = tags[:MAX_TAGS_PER_POST]

    await db.execute(sa.delete(PostTag).where(PostTag.post_id == post_id))
    for tag in tags:
        db.add(PostTag(post_id=post_id, tag=tag))
    await db.commit()
    return tags
