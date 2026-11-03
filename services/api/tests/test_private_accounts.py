"""A private account.

The switch covers two disclosures and nothing else: the fits somebody
published, and the two lists of who they are connected to. Counts
survive it on purpose - a count is not a list, and withholding one
would say only that there is something here worth hiding.

Going private is not an unpublish: the fit stays where it was and the
reads stop returning it, so going public again needs no screen.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import community, profiles
from app.models.follow import Follow
from tests.test_feed import _fit
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def _follow(db: AsyncSession, *, follower, followee) -> None:
    db.add(Follow(follower_id=follower, followee_id=followee))
    await db.commit()


async def test_a_public_members_followers_are_readable_by_a_stranger(
    db: AsyncSession,
) -> None:
    """The ordinary case, and the one that did not work at all before.

    Finding somebody and asking who else follows them is the most
    common question there is about a person, and the list is made of
    accounts that chose to be public.
    """
    subject = await make_user(db)
    fan = await make_user(db)
    stranger = await make_user(db)
    await _follow(db, follower=fan, followee=subject)

    found = await community.follow_list(
        db, user_id=stranger, subject_id=subject, direction="followers"
    )
    assert [person.user_id for person in found] == [fan]


async def test_following_reads_whether_the_viewer_follows_them_not_the_subject(
    db: AsyncSession,
) -> None:
    """The `followed` flag is a fact about the reader.

    Read against the subject it would render a Follow button that was
    already pressed for somebody else, which is the kind of wrong that
    only shows up after a tap.
    """
    subject = await make_user(db)
    shared = await make_user(db)
    viewer = await make_user(db)
    await _follow(db, follower=subject, followee=shared)

    found = await community.follow_list(
        db, user_id=viewer, subject_id=subject, direction="following"
    )
    assert [(p.user_id, p.followed) for p in found] == [(shared, False)]

    await _follow(db, follower=viewer, followee=shared)
    found = await community.follow_list(
        db, user_id=viewer, subject_id=subject, direction="following"
    )
    assert [(p.user_id, p.followed) for p in found] == [(shared, True)]


async def test_a_private_account_refuses_both_lists(db: AsyncSession) -> None:
    subject = await make_user(db)
    fan = await make_user(db)
    stranger = await make_user(db)
    await _follow(db, follower=fan, followee=subject)
    await profiles.set_private(db, user_id=subject, private=True)

    for direction in ("followers", "following"):
        with pytest.raises(community.AccountIsPrivate):
            await community.follow_list(
                db, user_id=stranger, subject_id=subject, direction=direction
            )


async def test_a_private_account_still_reads_its_own_lists(
    db: AsyncSession,
) -> None:
    """Privacy is about strangers. Going private must not blind you."""
    subject = await make_user(db)
    fan = await make_user(db)
    await _follow(db, follower=fan, followee=subject)
    await profiles.set_private(db, user_id=subject, private=True)

    found = await community.follow_list(db, user_id=subject, direction="followers")
    assert [person.user_id for person in found] == [fan]


async def test_a_private_members_page_keeps_the_counts_and_drops_the_grid(
    db: AsyncSession,
) -> None:
    subject = await make_user(db)
    viewer = await make_user(db)
    fan = await make_user(db)
    await _follow(db, follower=fan, followee=subject)
    await _fit(db, user_id=subject, caption="a fit", tags=["linen"])

    page = await community.member_profile(
        db, viewer_id=viewer, member_id=subject
    )
    assert page is not None and page.private is False
    assert len(page.posts) == 1 and page.post_count == 1

    await profiles.set_private(db, user_id=subject, private=True)
    page = await community.member_profile(
        db, viewer_id=viewer, member_id=subject
    )
    assert page is not None
    assert page.private is True
    assert page.posts == ()
    # The counts are facts about them, not lists of other people.
    assert page.post_count == 1
    assert page.follower_count == 1


async def test_going_public_again_restores_everything_at_once(
    db: AsyncSession,
) -> None:
    """Nothing was unpublished, so nothing needs re-screening."""
    subject = await make_user(db)
    viewer = await make_user(db)
    await _fit(db, user_id=subject, caption="a fit", tags=["linen"])
    await profiles.set_private(db, user_id=subject, private=True)
    await profiles.set_private(db, user_id=subject, private=False)

    page = await community.member_profile(db, viewer_id=viewer, member_id=subject)
    assert page is not None and page.private is False and len(page.posts) == 1


async def test_a_private_accounts_fits_leave_every_stranger_facing_read(
    db: AsyncSession,
) -> None:
    """The switch says nobody but you sees your fits.

    It gated the page and the two lists first, and left the
    photographs on Discover, under every tag their author used, on the
    face of a category tile and behind a direct link. Hiding somebody
    from their own profile while their work stayed on the front page
    is a settings screen with an opinion rather than a privacy control.
    """
    from app.domain import feed

    author = await make_user(db)
    reader = await make_user(db)
    post = await _fit(db, user_id=author, caption="a fit", tags=["linen"])

    assert post.id in {e.post.id for e in await feed.board(db, user_id=reader)}
    assert post.id in {
        e.post.id for e in await feed.by_tag(db, user_id=reader, tag="linen")
    }
    assert await feed.one(db, user_id=reader, post_id=post.id) is not None
    assert "linen" in {t for t, _ in await feed.popular_tags(db, user_id=reader)}

    await profiles.set_private(db, user_id=author, private=True)

    assert post.id not in {e.post.id for e in await feed.board(db, user_id=reader)}
    assert await feed.by_tag(db, user_id=reader, tag="linen") == []
    assert await feed.one(db, user_id=reader, post_id=post.id) is None
    assert await feed.doors(db, user_id=reader, tags=["linen"]) == []
    assert "linen" not in {t for t, _ in await feed.popular_tags(db, user_id=reader)}


async def test_a_private_account_still_sees_its_own_work(
    db: AsyncSession,
) -> None:
    """Privacy is about strangers. It must not blind its owner."""
    from app.domain import feed

    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="a fit", tags=["linen"])
    await profiles.set_private(db, user_id=author, private=True)

    assert post.id in {e.post.id for e in await feed.board(db, user_id=author)}
    assert await feed.one(db, user_id=author, post_id=post.id) is not None
    assert [e.post.id for e in await feed.by_tag(db, user_id=author, tag="linen")] == [
        post.id
    ]


async def test_a_private_accounts_pictures_stop_coming_down(
    db: AsyncSession,
) -> None:
    """The leak one layer below the one you can see.

    A reader who kept an asset id could fetch the bytes even once the
    feed declined to show the fit.
    """
    from app.domain.posts import media_is_published_to
    from app.models.posts import PostMedia
    from tests.test_garment_media import make_asset

    author = await make_user(db)
    reader = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["linen"])
    asset = await make_asset(db, user_id=author)
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    await db.commit()

    assert await media_is_published_to(db, viewer_id=reader, asset_id=asset.id)

    await profiles.set_private(db, user_id=author, private=True)
    assert not await media_is_published_to(db, viewer_id=reader, asset_id=asset.id)
    # Its owner still reaches their own picture.
    assert await media_is_published_to(db, viewer_id=author, asset_id=asset.id)


async def test_a_private_accounts_fits_leave_their_followers_feed(
    db: AsyncSession,
) -> None:
    """Following is instant here, with no request to approve.

    "Their followers can still see it" would therefore mean "anybody
    who taps Follow can still see it", which is not a privacy setting.
    """
    from app.domain import posts as posts_domain

    author = await make_user(db)
    fan = await make_user(db)
    await _follow(db, follower=fan, followee=author)
    post = await _fit(db, user_id=author, caption="a fit", tags=["linen"])

    assert [v.post.id for v in await posts_domain.feed(db, user_id=fan)] == [post.id]

    await profiles.set_private(db, user_id=author, private=True)
    assert await posts_domain.feed(db, user_id=fan) == []


async def test_a_private_accounts_fit_cannot_be_saved_or_reacted_to(
    db: AsyncSession,
) -> None:
    """The writes took a weaker gate than the reads.

    Both looked the post up directly and checked only blocks, so an id
    was enough to run the counts up on a fit the same reader could not
    see.
    """
    from app.domain import posts as posts_domain

    author = await make_user(db)
    reader = await make_user(db)
    post = await _fit(db, user_id=author, caption="a fit", tags=["linen"])

    assert await posts_domain.set_saved(
        db, user_id=reader, post_id=post.id, saved=True
    ) == 1
    assert await posts_domain.set_reaction(
        db, user_id=reader, post_id=post.id, kind="love"
    ) == {"love": 1}

    await profiles.set_private(db, user_id=author, private=True)

    assert (
        await posts_domain.set_saved(
            db, user_id=reader, post_id=post.id, saved=True
        )
        is None
    )
    assert (
        await posts_domain.set_reaction(
            db, user_id=reader, post_id=post.id, kind="fire"
        )
        is None
    )
    # And its author still can, on their own fit.
    assert await posts_domain.set_reaction(
        db, user_id=author, post_id=post.id, kind="love"
    ) is not None
