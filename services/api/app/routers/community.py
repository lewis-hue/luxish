"""Community: who dresses like you, and what they are reaching for.

The trending list lives in `discover` and stays there. This router adds the
two things that need a relationship to exist: suggestions drawn from the
wardrobe cohort, and a feed of what the people you follow have kept.

**What identity crosses between accounts is decided here**, not in the
domain, and right now the answer is: a first name and nothing else.

A suggestion shows the cohort facts and the first name only. Somebody being
proposed to a stranger has not agreed to be looked at in full.

**No profile photograph.** An earlier version attached one for accounts the
viewer followed, on the reasoning that following is a relationship the
viewer chose. It is not a relationship the *subject* chose — following needs
no approval — so that reasoning was backwards. It was also dead weight:
`/v1/uploads/local/{id}` serves bytes only to the asset's owner, so the id
was unfetchable by anyone it was sent to, and the app would have rendered a
blank circle for every name. Showing somebody's face to people they have not
agreed to needs its own consent, and until there is one the field is gone
rather than present and broken.

Which saves appear at all is gated on `community_sharing` consent in the
domain. This router decides identity; that one decides visibility.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import community as domain
from app.domain import moderation
from app.errors import ApiError
from app.models.user import User
from app.schemas.community import (
    GuidelineOut,
    MemberFitOut,
    GuidelinesOut,
    BlockedListOut,
    BlockedPersonOut,
    FollowCountsOut,
    FoundPersonOut,
    MemberOut,
    PeopleSearchOut,
    ReportIn,
    ReportOut,
)

router = APIRouter(prefix="/community", tags=["community"])


# One definition, in the domain, because the inbox composes sentences with
# the same rendering. The doctrine it encodes is documented there.
_first_name = domain.first_name


async def _people(db: SessionDep, ids: list[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    rows = await db.scalars(
        sa.select(User).where(User.id.in_(ids), User.deleted_at.is_(None))
    )
    return {user.id: user for user in rows}


def _found(person: domain.FoundPerson) -> FoundPersonOut:
    """One person, as a card a stranger is allowed to see."""
    return FoundPersonOut(
        user_id=person.user_id,
        name=person.name,
        followed=person.followed,
        follower_count=person.follower_count,
        fits=person.fits,
    )


@router.get("/people", response_model=PeopleSearchOut)
async def people(db: SessionDep, ctx: AuthDep, q: str = "") -> PeopleSearchOut:
    """Look somebody up by name.

    Only people who have published a fit can be found this way; see
    `domain.find_people` for why. A query shorter than two characters
    answers empty rather than returning a slice of the whole table.
    """
    found = await domain.find_people(db, user_id=ctx.user_id, query=q)
    return PeopleSearchOut(items=[_found(person) for person in found])


@router.get("/follows", response_model=FollowCountsOut)
async def follow_counts(db: SessionDep, ctx: AuthDep) -> FollowCountsOut:
    following, followers = await domain.counts(db, user_id=ctx.user_id)
    return FollowCountsOut(following=following, followers=followers)


@router.get("/followers", response_model=PeopleSearchOut)
async def followers(db: SessionDep, ctx: AuthDep) -> PeopleSearchOut:
    """The people who follow you.

    Yours only. A follower list is a list of real people, and serving
    somebody else's would be a way to enumerate who is connected to
    whom; a member's page keeps its counts and stops there.
    """
    found = await domain.follow_list(
        db, user_id=ctx.user_id, direction="followers"
    )
    return PeopleSearchOut(items=[_found(person) for person in found])


@router.get("/following", response_model=PeopleSearchOut)
async def following(db: SessionDep, ctx: AuthDep) -> PeopleSearchOut:
    """The people you follow."""
    found = await domain.follow_list(
        db, user_id=ctx.user_id, direction="following"
    )
    return PeopleSearchOut(items=[_found(person) for person in found])


@router.get("/members/{user_id}/followers", response_model=PeopleSearchOut)
async def member_followers(
    user_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> PeopleSearchOut:
    """Who follows them.

    404 for an account that does not exist, was deleted, or blocked the
    viewer - the same indistinguishable answer their page gives, for
    the same reason. A private account answers 200 with nothing in it
    and `private` set, because the account existing is not the secret:
    the list is.
    """
    return await _people_of(db, ctx, member_id=user_id, direction="followers")


@router.get("/members/{user_id}/following", response_model=PeopleSearchOut)
async def member_following(
    user_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> PeopleSearchOut:
    """Who they follow."""
    return await _people_of(db, ctx, member_id=user_id, direction="following")


async def _people_of(
    db: SessionDep, ctx: AuthDep, *, member_id: uuid.UUID, direction: str
) -> PeopleSearchOut:
    """One of somebody else's two lists, through their page's own gate.

    Resolving the member first rather than querying follows directly is
    what makes a blocked account unreadable here as well: the gate lives
    in one place and every read of a person goes through it.
    """
    if member_id == ctx.user_id:
        found = await domain.follow_list(
            db, user_id=ctx.user_id, direction=direction
        )
        return PeopleSearchOut(items=[_found(person) for person in found])

    profile = await domain.member_profile(
        db, viewer_id=ctx.user_id, member_id=member_id
    )
    if profile is None:
        raise ApiError(
            "No such account.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        )
    try:
        found = await domain.follow_list(
            db, user_id=ctx.user_id, subject_id=member_id, direction=direction
        )
    except domain.AccountIsPrivate:
        return PeopleSearchOut(items=[], private=True)
    except domain.NoSuchAccount:
        # Unreachable today - `member_profile` above already answered
        # 404 for every case this covers. Mapped anyway so the domain's
        # own gate cannot turn into a 500 if that order ever changes.
        raise ApiError(
            "No such account.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        ) from None
    return PeopleSearchOut(items=[_found(person) for person in found])


@router.put("/follows/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def start_following(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Follow somebody. Idempotent, so a double tap is not an error."""
    target = await db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise ApiError(
            "No such account.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        )
    try:
        await domain.follow(db, follower_id=ctx.user_id, followee_id=user_id)
    except domain.CannotFollowSelf:
        raise ApiError(
            "You cannot follow yourself.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="cannot_follow_self",
        ) from None
    except domain.YouBlockedThem:
        raise ApiError(
            "You blocked this account. Unblock it first.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="blocked_by_you",
        ) from None


@router.delete("/follows/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_following(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Unfollow. Idempotent: unfollowing somebody you do not follow is fine."""
    await domain.unfollow(db, follower_id=ctx.user_id, followee_id=user_id)


@router.get("/members/{user_id}", response_model=MemberOut)
async def member(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> MemberOut:
    """One other person's page.

    404 covers an account that does not exist, one that was deleted, and
    one that blocked the viewer, indistinguishably: a special status for
    the last case would be the disclosure the block exists to prevent.
    """
    profile = await domain.member_profile(db, viewer_id=ctx.user_id, member_id=user_id)
    if profile is None:
        raise ApiError(
            "No such account.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        )
    user = await db.get(User, user_id)
    assert user is not None  # member_profile just resolved it
    return MemberOut(
        user_id=profile.user_id,
        name=_first_name(user),
        handle=profile.handle,
        bio=profile.bio,
        links=dict(profile.links or {}),
        banner_asset_id=profile.banner_asset_id,
        followed=profile.followed,
        follows_you=profile.follows_you,
        follower_count=profile.follower_count,
        following_count=profile.following_count,
        shares=profile.shares,
        posts=[
            MemberFitOut(post_id=post_id, cover_asset_id=cover)
            for post_id, cover in profile.posts
        ],
        post_count=profile.post_count,
        saved_posts=[
            MemberFitOut(post_id=post_id, cover_asset_id=cover)
            for post_id, cover in profile.saved_posts
        ],
        blocked=profile.blocked,
        private=profile.private,
    )


@router.put("/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def start_block(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Block somebody. Idempotent, and it severs follows both ways."""
    target = await db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise ApiError(
            "No such account.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
        )
    try:
        await moderation.block(db, blocker_id=ctx.user_id, blocked_id=user_id)
    except moderation.CannotBlockSelf:
        raise ApiError(
            "You cannot block yourself.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="cannot_block_self",
        ) from None


@router.delete("/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_block(user_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> None:
    """Lift a block. Follows it severed stay severed."""
    await moderation.unblock(db, blocker_id=ctx.user_id, blocked_id=user_id)


@router.get("/blocks", response_model=BlockedListOut)
async def blocked_list(db: SessionDep, ctx: AuthDep) -> BlockedListOut:
    """Who this user has blocked. The one place a block is visible."""
    ids = await moderation.blocked_ids(db, user_id=ctx.user_id)
    people = await _people(db, list(ids))
    return BlockedListOut(
        items=[
            BlockedPersonOut(user_id=person_id, name=_first_name(people[person_id]))
            for person_id in sorted(ids, key=str)
            if person_id in people
        ]
    )


def _subject_ref(payload: ReportIn) -> str | None:
    """Which id a report is about, by what kind of thing it names."""
    if payload.subject_kind == "post":
        return str(payload.post_id) if payload.post_id else None
    if payload.subject_kind == "comment":
        return str(payload.comment_id) if payload.comment_id else None
    # An account report names its subject in `subject_user_id`, which the
    # handler reads separately.
    return None


@router.get("/guidelines", response_model=GuidelinesOut)
async def guidelines() -> GuidelinesOut:
    """The community guidelines.

    The same list the screen enforces and the report form offers, served
    so the app can show people the rules they are held to. Static, and
    the same for everybody.
    """
    from app.domain.guidelines import GUIDELINES

    return GuidelinesOut(
        items=[
            GuidelineOut(
                id=rule.id,
                title=rule.title,
                body=rule.body,
                reportable=rule.reportable,
            )
            for rule in GUIDELINES
        ]
    )


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def file_report(payload: ReportIn, db: SessionDep, ctx: AuthDep) -> ReportOut:
    """Record a report for the moderation queue.

    Nothing automated acts on it, and the response does not pretend
    otherwise: the row waits for a person. What *is* automatic is the
    screen every piece of text goes through before it is published;
    this is for what that missed.
    """
    try:
        report_id = await moderation.report(
            db,
            reporter_id=ctx.user_id,
            subject_kind=payload.subject_kind,
            subject_user_id=payload.subject_user_id,
            subject_ref=_subject_ref(payload),
            reason=payload.reason,
            guideline_id=payload.guideline_id,
            note=payload.note,
        )
    except moderation.BadReport as refusal:
        raise ApiError(
            str(refusal),
            # The literal: Starlette renamed the constant and deprecation
            # noise in every test run is not worth an alias.
            status_code=422,
            code="bad_report",
        ) from None
    return ReportOut(report_id=report_id)
