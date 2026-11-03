"""The parts of a social tab that are safe to ship without moderation.

**This file draws a line and stays on one side of it.** Everything here
is built from the follow graph (two user ids and a timestamp) and from
fits that have already been through the screen. Nothing a person
authored crosses between accounts except what the screen has passed.

**What somebody kept is private until they say otherwise.** The shelf on
a member page reads only from accounts holding a live `community_sharing`
consent. That is not belt-and-braces: following needs no approval, so
without the grant the page would turn "I tapped Follow" into "I can read
your collection" - which is how this shipped the first time and was
wrong.

**Private is separate from that, and is a switch rather than a consent.**
`community_sharing` is a grant about other people's fits somebody kept;
`Profile.private` is about their own fits and their two follow lists. It
gates the lists and never the counts: a count is not a list, and
withholding one would say only that there is something here worth
hiding.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.moderation import has_blocked, hidden_either_way
from app.models.consent import Consent
from app.models.follow import Follow
from app.models.posts import Post, shown_to_strangers
from app.models.profile import Profile
from app.models.user import User


class CannotFollowSelf(Exception):
    """Following yourself puts your own saves in your own feed."""


class YouBlockedThem(Exception):
    """Following somebody you blocked. Unblocking first is the honest path."""


def _consenting() -> sa.Select:
    """Users holding a live `community_sharing` grant.

    One definition, used by every query that touches somebody else's saves.
    The feed had its own copy of this filter and the suggestion ranking had
    none, which is exactly how the second one came to leak what the first
    was protecting.
    """
    return sa.select(Consent.user_id).where(
        Consent.kind == "community_sharing",
        Consent.granted_at.is_not(None),
        Consent.revoked_at.is_(None),
    )


async def follow(db: AsyncSession, *, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
    """Start following somebody. Idempotent.

    **Blocks shape this in two different ways on purpose.** Following
    somebody you blocked is refused out loud: you know about the block, so
    the refusal discloses nothing and a silent success would contradict a
    choice you made. Following somebody who blocked *you* returns quietly
    without writing: an error would announce the block, and the feed
    filters on blocks anyway, so the missing edge changes nothing you can
    observe.
    """
    if follower_id == followee_id:
        raise CannotFollowSelf
    if await has_blocked(db, blocker_id=follower_id, blocked_id=followee_id):
        raise YouBlockedThem
    if await has_blocked(db, blocker_id=followee_id, blocked_id=follower_id):
        return

    existing = await db.get(Follow, (follower_id, followee_id))
    if existing is not None:
        # Following twice is not an error, it is the same state. Raising here
        # would make a double-tap look like a failure.
        return

    db.add(Follow(follower_id=follower_id, followee_id=followee_id))
    await db.commit()

    # Only on a new edge. The idempotent return above means a double
    # tap cannot send a second banner.
    from app.domain import push

    follower = await db.get(User, follower_id)
    who = (follower.display_name or "Somebody") if follower else "Somebody"
    await push.notify(
        db,
        user_id=followee_id,
        kind="new_follower",
        title="You have a new follower",
        body=f"{who} started following you.",
        subject=str(follower_id),
        deep_link=f"/member/{follower_id}",
    )


async def unfollow(db: AsyncSession, *, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
    """Stop following somebody. Idempotent."""
    await db.execute(
        sa.delete(Follow).where(
            Follow.follower_id == follower_id,
            Follow.followee_id == followee_id,
        )
    )
    await db.commit()


async def following_ids(db: AsyncSession, *, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.scalars(
        sa.select(Follow.followee_id).where(Follow.follower_id == user_id)
    )
    return set(rows)


async def counts(db: AsyncSession, *, user_id: uuid.UUID) -> tuple[int, int]:
    """``(following, followers)`` for one person."""
    following = await db.scalar(
        sa.select(sa.func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )
    followers = await db.scalar(
        sa.select(sa.func.count()).select_from(Follow).where(Follow.followee_id == user_id)
    )
    return int(following or 0), int(followers or 0)


@dataclass(frozen=True, slots=True)
class MemberProfile:
    """One other person, as far as this viewer is allowed to see them."""

    user_id: uuid.UUID
    followed: bool
    follows_you: bool
    follower_count: int
    #: Whether they hold a live `community_sharing` grant.
    shares: bool
    #: The viewer blocked them. The other direction never reaches a client:
    #: a profile whose subject blocked the viewer resolves to nothing.
    blocked: bool
    #: How many people they follow. The other half of a follower count,
    #: and the half that says whether somebody is here to look or to be
    #: looked at.
    following_count: int = 0
    #: Fits they published, newest first, each with the picture to
    #: show for it. Pairs rather than ids: a grid needs the asset to
    #: render and the post to open, and returning only the post id
    #: meant the caller had no picture and drew grey boxes.
    posts: tuple[tuple[uuid.UUID, uuid.UUID | None], ...] = ()
    #: How many they have published in total, which is not the same as
    #: how many this page shows.
    post_count: int = 0
    #: Fits by other people that they kept, same shape. Behind
    #: `community_sharing`, like every other read of somebody's shelf.
    saved_posts: tuple[tuple[uuid.UUID, uuid.UUID | None], ...] = ()
    #: Their handle and approved bio, when they have set them.
    handle: str | None = None
    bio: str | None = None
    links: dict[str, str] | None = None
    #: The banner across the top of their page, if the screen passed it.
    banner_asset_id: uuid.UUID | None = None
    #: They keep their fits and their two follow lists to themselves.
    #: The counts above stay true either way - a count is not a list,
    #: and withholding it would say only that there is something here.
    private: bool = False



async def _first_pictures(
    db: AsyncSession, post_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """The first readable photograph on each of these fits.

    One query for a whole grid. The caller renders from the asset and
    opens by the post, so it needs both and must not have to ask again
    per tile.
    """
    if not post_ids:
        return {}
    from app.models.media_asset import MediaAsset
    from app.models.posts import PostMedia

    rows = (
        await db.execute(
            sa.select(PostMedia.post_id, PostMedia.media_asset_id)
            .join(MediaAsset, MediaAsset.id == PostMedia.media_asset_id)
            .where(
                PostMedia.post_id.in_(post_ids),
                MediaAsset.deleted_at.is_(None),
                MediaAsset.status.in_(("uploaded", "ready")),
            )
            .order_by(PostMedia.post_id, PostMedia.position.asc())
        )
    ).all()
    first: dict[uuid.UUID, uuid.UUID] = {}
    for post_id, asset_id in rows:
        first.setdefault(post_id, asset_id)
    return first


async def member_profile(
    db: AsyncSession,
    *,
    viewer_id: uuid.UUID,
    member_id: uuid.UUID,
    keep_limit: int = 12,
) -> MemberProfile | None:
    """One person's public face, or None when there is nothing to show.

    None covers three cases on purpose: no such account, a deleted one, and
    an account that blocked the viewer. Distinguishing the third would make
    the 404 itself the disclosure.
    """
    if viewer_id == member_id:
        return None
    user = await db.get(User, member_id)
    if user is None or user.deleted_at is not None:
        return None
    if await has_blocked(db, blocker_id=member_id, blocked_id=viewer_id):
        return None

    blocked = await has_blocked(db, blocker_id=viewer_id, blocked_id=member_id)
    followed = await db.get(Follow, (viewer_id, member_id)) is not None
    follows_you = await db.get(Follow, (member_id, viewer_id)) is not None
    follower_count = int(
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(Follow)
            .where(Follow.followee_id == member_id)
        )
        or 0
    )

    shares = (
        await db.scalar(_consenting().where(Consent.user_id == member_id))
    ) is not None

    # A private account, read once and applied to every list below.
    #
    # It gates the *lists*, not the counts: how many people somebody is
    # connected to is a fact about them, where who those people are is a
    # fact about everybody else as well.
    from app.domain import profiles as profile_domain

    private = await profile_domain.is_private(db, user_id=member_id)

    following_count = int(
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(Follow)
            .where(Follow.follower_id == member_id)
        )
        or 0
    )

    # The first picture on each fit, looked up once for both lists.
    # Without it a grid of somebody's work renders as grey boxes,
    # which is what shipped the first time.
    covers: dict[uuid.UUID, uuid.UUID] = {}

    # What they published. Not gated: a fit on the board is already in
    # front of strangers, and hiding it on its author's page would make
    # the page a worse view of information the viewer already has.
    posts: tuple[tuple[uuid.UUID, uuid.UUID | None], ...] = ()
    post_count = 0
    if not blocked:
        from app.models.posts import Post

        published = sa.select(Post.id).where(
            Post.user_id == member_id,
            shown_to_strangers(),
        )
        post_count = int(
            await db.scalar(
                sa.select(sa.func.count()).select_from(published.subquery())
            )
            or 0
        )
        ids = [] if private else list(
            (
                await db.scalars(
                    published.order_by(Post.published_at.desc()).limit(keep_limit * 4)
                )
            ).all()
        )
        covers.update(await _first_pictures(db, ids))
        posts = tuple((post_id, covers.get(post_id)) for post_id in ids)

    # What they kept of other people's, behind the sharing consent.
    saved_posts: tuple[tuple[uuid.UUID, uuid.UUID | None], ...] = ()
    if shares and not blocked and not private:
        from app.models.posts import Post, PostSave

        hidden = await hidden_either_way(db, user_id=viewer_id)
        kept = (
            sa.select(PostSave.post_id)
            .join(Post, Post.id == PostSave.post_id)
            .join(User, User.id == Post.user_id)
            .where(
                PostSave.user_id == member_id,
                shown_to_strangers(),
                User.deleted_at.is_(None),
            )
            .order_by(PostSave.created_at.desc())
            .limit(keep_limit * 4)
        )
        if hidden:
            kept = kept.where(Post.user_id.not_in(hidden))
        kept_ids = list((await db.scalars(kept)).all())
        covers.update(await _first_pictures(db, kept_ids))
        saved_posts = tuple(
            (post_id, covers.get(post_id)) for post_id in kept_ids
        )

    # Their public identity. The approved bio only: this is a stranger's
    # view, and an unscreened one is unscreened text in front of them.
    profile = await profile_domain.get(db, user_id=member_id)
    banner = None
    if profile is not None and profile.banner_state == "published":
        banner = profile.banner_asset_id

    return MemberProfile(
        user_id=member_id,
        followed=followed,
        follows_you=follows_you,
        follower_count=follower_count,
        following_count=following_count,
        shares=shares,
        blocked=blocked,
        posts=posts,
        post_count=post_count,
        saved_posts=saved_posts,
        handle=profile.handle if profile else None,
        bio=profile_domain.public_bio(profile),
        links=dict(profile.links or {}) if profile else None,
        banner_asset_id=banner,
        private=private,
    )


def first_name(user: User) -> str:
    """The shortest safe rendering of somebody else's identity.

    A first name, or the head of the email's local part. Never the full
    display name and never the address: this crosses between accounts, and
    an email on a card is a contact detail published without being asked.
    Lives in the domain because the inbox composes sentences with it too;
    the community router re-exports the same function.
    """
    display = (user.display_name or "").strip()
    if display:
        # Their own casing, untouched: somebody who writes their name in
        # lower case meant to.
        return display.split()[0]
    local = (user.email or "").split("@")[0]
    head = local.split(".")[0].split("_")[0].split("+")[0][:40]
    if not head:
        return "Someone"
    return head[0].upper() + head[1:]


@dataclass(frozen=True)
class FoundPerson:
    """One search hit. Exactly what a stranger's card is allowed to carry."""

    user_id: uuid.UUID
    name: str
    followed: bool
    follower_count: int
    #: Published fits, which is both the reason they are findable and the
    #: only number about them that means anything to somebody deciding
    #: whether to follow.
    fits: int


#: Below this the query is a letter, and a letter matches most of the table.
MIN_PEOPLE_QUERY = 2
MAX_PEOPLE_RESULTS = 20



class NoSuchAccount(Exception):
    """This account cannot be read, and why is not said.

    Deleted, never existed, or blocked the reader: one answer for all
    three, because telling them apart is how somebody confirms that
    an account exists and has blocked them.
    """


class AccountIsPrivate(Exception):
    """Their lists are theirs. Distinct from an empty list, which is a fact."""


async def follow_list(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_id: uuid.UUID | None = None,
    direction: str = "followers",
    limit: int = 200,
) -> list[FoundPerson]:
    """The people following somebody, or the ones they follow.

    Returned in the same shape as a search hit, because it is the same
    card: a name, whether this viewer follows them, and how many fits
    they have posted. Nothing a stranger could not already see.

    **Somebody else's list, unless they went private.** This used to
    answer for the caller only, on the reasoning that a follower list
    enumerates real people. That is true, and it is also what every
    follower list anywhere does - the list is made of accounts that
    chose to be public, and refusing it left the app unable to answer
    the most ordinary question somebody asks about a person they just
    found. The switch for not wanting that is the account being
    private, which is a choice its owner makes rather than one made for
    them, and it raises :class:`AccountIsPrivate` rather than returning
    nothing, so the caller can say which it was.

    Whose blocks apply: the *viewer's*, both ways. A list read through
    somebody else's account is still shown to this reader, so it is
    this reader's hidden set that filters it - using the subject's
    would leak who they blocked.
    """
    from app.domain import profiles as profile_domain

    subject = subject_id or user_id
    if subject != user_id:
        # The same gate the member's page applies, applied here too.
        #
        # **Not a hole that was open.** The only route that passes a
        # `subject_id` resolves `member_profile` first, which already
        # 404s a deleted account and one that blocked this viewer, so
        # nothing could reach this list around it. What it was is a
        # rule enforced one layer up from the function that needs it,
        # on an exported function that takes the subject as an
        # argument - so the next caller written against it inherits
        # nothing. The rule still lives in `has_blocked`; only the
        # call is repeated.
        subject_user = await db.get(User, subject)
        if subject_user is None or subject_user.deleted_at is not None:
            raise NoSuchAccount(subject)
        if await has_blocked(db, blocker_id=subject, blocked_id=user_id):
            raise NoSuchAccount(subject)
        if await profile_domain.is_private(db, user_id=subject):
            raise AccountIsPrivate(subject)

    hidden = await hidden_either_way(db, user_id=user_id)

    if direction == "following":
        ids_query = sa.select(Follow.followee_id).where(
            Follow.follower_id == subject
        )
    else:
        ids_query = sa.select(Follow.follower_id).where(
            Follow.followee_id == subject
        )

    published = (
        sa.select(Post.user_id, sa.func.count().label("fits"))
        .where(shown_to_strangers())
        .group_by(Post.user_id)
        .subquery()
    )

    rows = (
        await db.execute(
            # Outer join on the fit count: somebody who follows you and
            # has never posted is still a follower, and an inner join
            # would quietly drop them.
            sa.select(User, published.c.fits)
            .outerjoin(published, published.c.user_id == User.id)
            .where(
                User.id.in_(ids_query),
                User.deleted_at.is_(None),
                User.id.not_in(hidden) if hidden else sa.true(),
            )
            .order_by(User.display_name)
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    ids = [user.id for user, _ in rows]
    following = set(
        (
            await db.scalars(
                sa.select(Follow.followee_id).where(
                    Follow.follower_id == user_id, Follow.followee_id.in_(ids)
                )
            )
        ).all()
    )
    counts = dict(
        (
            await db.execute(
                sa.select(Follow.followee_id, sa.func.count())
                .where(Follow.followee_id.in_(ids))
                .group_by(Follow.followee_id)
            )
        ).all()
    )
    return [
        FoundPerson(
            user_id=user.id,
            name=first_name(user),
            followed=user.id in following,
            follower_count=int(counts.get(user.id, 0)),
            fits=int(fits or 0),
        )
        for user, fits in rows
    ]


async def find_people(
    db: AsyncSession, *, user_id: uuid.UUID, query: str
) -> list[FoundPerson]:
    """People you can look up by name.

    **Naming yourself is what makes you findable; private takes it
    back.** Until 2026-11-02 the gate was having published a fit, on
    the reasoning that a name search over every account would make
    the whole table addressable by anybody guessing a first name.
    That reasoning still holds - the gate just moved to a control the
    person actually operates, because the old one made the app unable
    to answer "is my friend on here yet", which is the first thing
    anybody does with a new account.

    The two conditions now:

    * **A display name.** Setting one is an affirmative act, and an
      account that has not been named is not addressable by name
      anyway. This is also what keeps a fresh sign-up out of search
      until its owner has decided to be somebody here.
    * **Not private.** `Profile.private` already means "my own things
      are not for strangers", and being listed by name to strangers
      is the same question. One switch, one meaning, and it is
      reversible in one tap.

    Publishing still *ranks* - somebody with fits sorts above somebody
    without - but it no longer gates.

    Blocks apply in both directions, and the search never confirms that a
    blocked account exists by any other route.

    **Your own account is a result like any other.** It is subject to
    the same two gates, so looking yourself up answers "can anybody
    find me" honestly.
    """
    cleaned = query.strip()
    if len(cleaned) < MIN_PEOPLE_QUERY:
        return []

    hidden = await hidden_either_way(db, user_id=user_id)
    published = (
        sa.select(Post.user_id, sa.func.count().label("fits"))
        .where(shown_to_strangers())
        .group_by(Post.user_id)
        .subquery()
    )
    rows = (
        await db.execute(
            # Outer, not inner: publishing ranks now rather than gates,
            # so somebody with no fits still appears - below those who
            # have some.
            sa.select(User, sa.func.coalesce(published.c.fits, 0))
            .outerjoin(published, published.c.user_id == User.id)
            .outerjoin(Profile, Profile.user_id == User.id)
            .where(
                User.deleted_at.is_(None),
                # Yourself included, on the product owner's
                # instruction (2026-11-02). Looking yourself up is how
                # somebody checks what strangers can see of them, and
                # an app that cannot find an account it is signed into
                # reads as a broken search rather than a considered
                # omission. Opening the result is handled on the
                # client: `/member/<you>` redirects to the profile
                # tab, so you get the owner's view with Edit profile
                # rather than a visitor's view offering to follow and
                # message yourself.
                #
                # The two gates above still apply to you as they do to
                # anybody: an unnamed or private account does not
                # appear, including in its owner's own results, which
                # is precisely what makes this useful as a check on
                # your own visibility.
                User.id.not_in(hidden) if hidden else sa.true(),
                # Named yourself. An unnamed account is not findable by
                # name in any case, and leaving it out keeps a fresh
                # sign-up out of search until its owner has decided to
                # be somebody here.
                sa.func.coalesce(User.display_name, "") != "",
                # And has not said otherwise. No profile row at all is
                # not private: it is somebody who has never opened the
                # setting.
                sa.or_(Profile.private.is_(None), Profile.private.is_(False)),
                # Matched on the name a stranger would actually see, so a
                # hit is always explicable by what is on the card.
                sa.func.lower(sa.func.coalesce(User.display_name, "")).contains(
                    cleaned.lower()
                ),
            )
            .order_by(
                sa.func.coalesce(published.c.fits, 0).desc(), User.display_name
            )
            .limit(MAX_PEOPLE_RESULTS)
        )
    ).all()
    if not rows:
        return []

    ids = [user.id for user, _ in rows]
    following = set(
        (
            await db.scalars(
                sa.select(Follow.followee_id).where(
                    Follow.follower_id == user_id, Follow.followee_id.in_(ids)
                )
            )
        ).all()
    )
    counts = dict(
        (
            await db.execute(
                sa.select(Follow.followee_id, sa.func.count())
                .where(Follow.followee_id.in_(ids))
                .group_by(Follow.followee_id)
            )
        ).all()
    )
    return [
        FoundPerson(
            user_id=user.id,
            name=first_name(user),
            followed=user.id in following,
            follower_count=int(counts.get(user.id, 0)),
            fits=int(fits),
        )
        for user, fits in rows
    ]
