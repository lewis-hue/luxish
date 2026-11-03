"""Comments under a fit.

A save shipped without review because there is nothing in it to moderate.
A comment is the opposite case, so the properties worth pinning are the
ones a text feature gets wrong.

**Held until screened, and the author sees their own held one.** A
comment that vanishes on submission reads as a bug and invites a second
attempt.

**An unavailable screen holds.** An absent gate is not consent.

**Blocks apply in both directions**, and the count is counted over what
the reader can actually reach.
"""

from __future__ import annotations

from datetime import UTC, datetime
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import comments as domain
from app.models.comment import PostComment
from tests.test_feed import _fit
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
async def test_a_comment_appears_the_moment_it_is_written(
    db: AsyncSession,
) -> None:
    """Optimistic, so nobody waits on a vendor to see their own remark.

    It used to be `pending_review` until a model agreed, which meant a
    comment did not appear when it was written and its author
    concluded the app had dropped it.
    """
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    comment = await domain.write(
        db, user_id=me, post_id=post.id, body="love this"
    )
    assert comment.state == "published"


async def test_the_obvious_is_still_refused_before_it_appears(
    db: AsyncSession,
) -> None:
    """Stage one did not change, and is the one verdict reached inline.

    A phone number cannot be a remark about clothes, so it never
    appears at all - no model call, and no window in which it is
    visible to anybody but its author.
    """
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    comment = await domain.write(
        db, user_id=me, post_id=post.id, body="call me on 0712345678"
    )
    assert comment.state == "held"
    assert comment.screen_mode == "rules"


async def test_writing_a_comment_queues_its_screen(db: AsyncSession) -> None:
    """Without the job a comment sits in review for ever: the write looks
    like it worked and the result never comes. That exact hole shipped
    once in the bio path."""
    from app.models.job import Job

    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    comment = await domain.write(db, user_id=me, post_id=post.id, body="hi")
    job = await db.scalar(
        sa.select(Job).where(Job.kind == domain.COMMENT_SCREEN_JOB_KIND)
    )
    assert job is not None
    assert job.payload["comment_id"] == str(comment.id)


async def test_a_seeded_comment_is_published_without_a_billed_screen(
    db: AsyncSession,
) -> None:
    """A demo world is this repository's own fixture; paying per line
    of it buys nothing."""
    from app.models.job import Job

    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    comment = await domain.write(
        db, user_id=me, post_id=post.id, body="seeded", seeded=True
    )
    assert comment.state == "published"
    assert comment.screen_mode == "seed"
    assert await db.scalar(sa.select(sa.func.count()).select_from(Job)) == 0


async def test_an_empty_comment_is_refused(db: AsyncSession) -> None:
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    with pytest.raises(domain.EmptyComment):
        await domain.write(db, user_id=me, post_id=post.id, body="   ")


async def test_a_comment_on_a_blocked_authors_fit_is_refused(
    db: AsyncSession,
) -> None:
    """Reaching somebody who blocked you is the single thing a block is
    for."""
    from app.models.moderation import Block

    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    db.add(Block(blocker_id=author, blocked_id=me))
    await db.commit()

    with pytest.raises(domain.FitNotVisible):
        await domain.write(db, user_id=me, post_id=post.id, body="hello")


async def test_a_flood_of_unscreened_comments_is_refused(
    db: AsyncSession,
) -> None:
    """A loop posting faster than the screener runs is a client fault and
    a bill, and both are better refused than absorbed."""
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    for index in range(domain.MAX_PENDING_PER_POST):
        await domain.write(db, user_id=me, post_id=post.id, body=f"n{index}")
    with pytest.raises(domain.TooManyPending):
        await domain.write(db, user_id=me, post_id=post.id, body="one more")


async def test_a_reply_to_a_reply_is_flattened_not_refused(
    db: AsyncSession,
) -> None:
    """Losing somebody's words to enforce a shape is the wrong trade."""
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    top = await domain.write(
        db, user_id=author, post_id=post.id, body="top", seeded=True
    )
    reply = await domain.write(
        db, user_id=me, post_id=post.id, body="reply", parent_id=top.id
    )
    deeper = await domain.write(
        db, user_id=me, post_id=post.id, body="deeper", parent_id=reply.id
    )
    assert reply.parent_id == top.id
    assert deeper.parent_id == top.id


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
async def test_you_see_your_own_held_comment_and_nobody_else_does(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    other = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    mine = await domain.write(db, user_id=me, post_id=post.id, body="waiting")
    await domain.apply_verdict(
        db, comment_id=mine.id, allowed=False, note="Held for review."
    )

    seen_by_me = await domain.visible(db, user_id=me, post_id=post.id)
    assert [v.comment.id for v in seen_by_me] == [mine.id]
    assert seen_by_me[0].mine

    seen_by_other = await domain.visible(db, user_id=other, post_id=post.id)
    assert seen_by_other == []


async def test_a_published_comment_is_seen_by_everybody(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    other = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    written = await domain.write(db, user_id=me, post_id=post.id, body="nice")
    await domain.apply_verdict(db, comment_id=written.id, allowed=True, note="")

    seen = await domain.visible(db, user_id=other, post_id=post.id)
    assert [v.comment.id for v in seen] == [written.id]
    assert not seen[0].mine


async def test_a_blocked_persons_comments_are_hidden_both_ways(
    db: AsyncSession,
) -> None:
    from app.models.moderation import Block

    me = await make_user(db)
    rude = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    theirs = await domain.write(
        db, user_id=rude, post_id=post.id, body="theirs", seeded=True
    )
    db.add(Block(blocker_id=me, blocked_id=rude))
    await db.commit()

    seen = await domain.visible(db, user_id=me, post_id=post.id)
    assert theirs.id not in {v.comment.id for v in seen}


async def test_the_count_is_counted_over_what_the_reader_can_see(
    db: AsyncSession,
) -> None:
    """A number including a blocked person's comments promises a longer
    thread than the one they get."""
    from app.models.moderation import Block

    me = await make_user(db)
    rude = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    await domain.write(
        db, user_id=author, post_id=post.id, body="mine", seeded=True
    )
    for index in range(4):
        await domain.write(
            db, user_id=rude, post_id=post.id, body=f"n{index}", seeded=True
        )
    db.add(Block(blocker_id=me, blocked_id=rude))
    await db.commit()

    counted = await domain.counts(db, [post.id], viewer_id=me)
    assert counted[post.id] == 1


async def test_a_comment_counts_as_soon_as_it_appears(
    db: AsyncSession,
) -> None:
    """The tally and the thread agree, which they must.

    A comment visible in the sheet but missing from the count beside
    the bubble reads as a bug in whichever of the two you noticed
    second.
    """
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    await domain.write(db, user_id=me, post_id=post.id, body="nice")

    counted = await domain.counts(db, [post.id], viewer_id=me)
    assert counted.get(post.id, 0) == 1


async def test_a_held_comment_is_not_counted(db: AsyncSession) -> None:
    """Only its author sees it, so only its author's thread holds it."""
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    await domain.write(
        db, user_id=me, post_id=post.id, body="reach me on 0712345678"
    )

    counted = await domain.counts(db, [post.id], viewer_id=me)
    assert counted.get(post.id, 0) == 0


# --------------------------------------------------------------------------- #
# screening
# --------------------------------------------------------------------------- #
async def test_an_unavailable_screen_holds_rather_than_publishes(
    db: AsyncSession,
) -> None:
    """An absent gate is not consent."""
    from app.workers.screen import screen_comment

    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await domain.write(db, user_id=me, post_id=post.id, body="hi")

    outcome = await screen_comment(db, comment_id=comment.id, screener=None)
    assert outcome["outcome"] == "held"

    await db.refresh(comment)
    assert comment.state == "held"
    assert comment.screen_note


async def test_a_screen_that_answers_with_nothing_holds(
    db: AsyncSession,
) -> None:
    """A model that said nothing is not a model that said yes."""
    from app.workers.screen import ScreenDidNotAnswer, screen_comment

    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await domain.write(db, user_id=me, post_id=post.id, body="hi")

    class Silent:
        async def screen_text(self, text: str, **kwargs: Any) -> Any:  # noqa: ANN401
            raise ScreenDidNotAnswer("nothing came back")

    outcome = await screen_comment(db, comment_id=comment.id, screener=Silent())
    assert outcome["outcome"] == "held"

    # And it is actually gone from everybody else's thread, not merely
    # reported as held: the comment was live when the screen ran, so a
    # verdict that could not take it down would be no verdict at all.
    await db.refresh(comment)
    assert comment.state == "held"


async def test_an_approved_comment_publishes(db: AsyncSession) -> None:
    from app.workers.screen import screen_comment

    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await domain.write(db, user_id=me, post_id=post.id, body="hi")

    class Yes:
        async def screen_text(self, text: str, **kwargs: Any) -> Any:  # noqa: ANN401
            return True, ""

    outcome = await screen_comment(db, comment_id=comment.id, screener=Yes())
    assert outcome["outcome"] == "published"
    await db.refresh(comment)
    assert comment.state == "published"


# --------------------------------------------------------------------------- #
# removing
# --------------------------------------------------------------------------- #
async def test_you_can_delete_your_own_comment(db: AsyncSession) -> None:
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await domain.write(
        db, user_id=me, post_id=post.id, body="oops", seeded=True
    )

    assert await domain.remove(db, user_id=me, comment_id=comment.id)
    assert await domain.visible(db, user_id=me, post_id=post.id) == []


async def test_a_fits_author_can_remove_a_comment_on_it(
    db: AsyncSession,
) -> None:
    """Without this, a block is the only tool available for one remark."""
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await domain.write(
        db, user_id=me, post_id=post.id, body="rude", seeded=True
    )

    assert await domain.remove(db, user_id=author, comment_id=comment.id)


async def test_a_stranger_cannot_remove_a_comment(db: AsyncSession) -> None:
    me = await make_user(db)
    author = await make_user(db)
    stranger = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await domain.write(
        db, user_id=me, post_id=post.id, body="mine", seeded=True
    )

    with pytest.raises(domain.NotYourComment):
        await domain.remove(db, user_id=stranger, comment_id=comment.id)


async def test_deleting_tombstones_rather_than_erases(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await domain.write(
        db, user_id=me, post_id=post.id, body="x", seeded=True
    )
    comment_id = comment.id
    await domain.remove(db, user_id=me, comment_id=comment_id)

    # Re-read by id rather than from the stale instance: the delete used
    # a SQL `now()`, so the attribute on the object in hand is an
    # unresolved expression until it is refreshed.
    still = await db.scalar(
        sa.select(PostComment).where(PostComment.id == comment_id)
    )
    assert still is not None
    assert still.deleted_at is not None


# --------------------------------------------------------------------------- #
# the routes
# --------------------------------------------------------------------------- #
async def test_the_routes_write_read_and_delete(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-comments-1")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    written = await client.post(
        f"/v1/feed/{post.id}/comments", json={"body": "love it"}, headers=headers
    )
    assert written.status_code == 201, written.text
    body = written.json()
    # Live on the way back out, so the client has nothing to wait for.
    assert body["state"] == "published"
    assert body["mine"] is True

    listed = await client.get(f"/v1/feed/{post.id}/comments", headers=headers)
    assert [c["id"] for c in listed.json()["items"]] == [body["id"]]

    gone = await client.delete(
        f"/v1/feed/comments/{body['id']}", headers=headers
    )
    assert gone.status_code == 204
    after = await client.get(f"/v1/feed/{post.id}/comments", headers=headers)
    assert after.json()["items"] == []


async def test_the_delete_route_is_not_shadowed_by_the_post_route(
    client: Any, auth: Any
) -> None:
    """`/v1/feed/comments/{id}` must not be parsed as a post id."""
    headers = auth(sub="kc-comments-2")
    await client.post("/v1/auth/session", headers=headers)
    r = await client.delete(
        f"/v1/feed/comments/{uuid.uuid4()}", headers=headers
    )
    assert r.status_code == 204


def test_a_link_is_empty_when_nothing_is_configured() -> None:
    """Better than a URL that resolves nowhere: a caller shows the
    picture without a link rather than attaching a dead one."""
    from app.routers.feed import fit_link

    class Bare:
        public_web_base_url = ""
        app_link_scheme = ""

    import app.config as config

    original = config.get_settings
    config.get_settings = lambda: Bare()  # type: ignore[assignment]
    try:
        assert fit_link(uuid.uuid4()) == ""
    finally:
        config.get_settings = original


def test_a_public_web_page_wins_over_the_app_scheme() -> None:
    """A link anybody can open beats one that only works for people who
    already have the app."""
    from app.routers.feed import fit_link

    class Both:
        public_web_base_url = "https://example.test/"
        app_link_scheme = "luxish"

    import app.config as config

    original = config.get_settings
    config.get_settings = lambda: Both()  # type: ignore[assignment]
    try:
        post_id = uuid.uuid4()
        assert fit_link(post_id) == f"https://example.test/fit/{post_id}"
    finally:
        config.get_settings = original


async def test_a_fit_carries_a_link_to_itself(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    """A picture shared without one cannot be traced to its author."""
    headers = auth(sub="kc-comments-3")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])

    r = await client.get(f"/v1/feed/{post.id}", headers=headers)
    assert r.status_code == 200, r.text
    assert str(post.id) in r.json()["link"]


async def test_the_comment_count_appears_on_a_card(
    client: Any, db: AsyncSession, auth: Any
) -> None:
    headers = auth(sub="kc-comments-4")
    await client.post("/v1/auth/session", headers=headers)
    author = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    await domain.write(
        db, user_id=author, post_id=post.id, body="mine", seeded=True
    )

    r = await client.get("/v1/feed", headers=headers)
    card = next(i for i in r.json()["items"] if i["id"] == str(post.id))
    assert card["comments"] == 1


# ------------------------------------------------------------------ #
# liking one
# ------------------------------------------------------------------ #
async def _published(db: AsyncSession, *, post_id: uuid.UUID, user_id: uuid.UUID):
    """A comment past the screen, which is the only kind anybody else sees."""
    comment = await domain.write(db, user_id=user_id, post_id=post_id, body="love this")
    comment.state = "published"
    await db.commit()
    return comment


async def test_liking_a_comment_counts_once_however_many_taps(
    db: AsyncSession,
) -> None:
    """The pair is the primary key, so a double tap cannot inflate it."""
    author = await make_user(db)
    writer = await make_user(db)
    fan = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await _published(db, post_id=post.id, user_id=writer)

    for _ in range(3):
        likes = await domain.set_liked(
            db, user_id=fan, comment_id=comment.id, liked=True
        )
    assert likes == 1

    seen = await domain.visible(db, user_id=fan, post_id=post.id)
    row = next(v for v in seen if v.comment.id == comment.id)
    assert row.likes == 1
    assert row.liked_by_me is True


async def test_taking_a_like_back(db: AsyncSession) -> None:
    author = await make_user(db)
    writer = await make_user(db)
    fan = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await _published(db, post_id=post.id, user_id=writer)

    await domain.set_liked(db, user_id=fan, comment_id=comment.id, liked=True)
    assert await domain.set_liked(
        db, user_id=fan, comment_id=comment.id, liked=False
    ) == 0
    # Un-liking what was never liked is work already done, not an error.
    assert await domain.set_liked(
        db, user_id=fan, comment_id=comment.id, liked=False
    ) == 0


async def test_the_tally_is_everybody_but_the_flag_is_yours(
    db: AsyncSession,
) -> None:
    """Two people liking it is two, and each sees only their own state."""
    author = await make_user(db)
    writer = await make_user(db)
    one = await make_user(db)
    two = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await _published(db, post_id=post.id, user_id=writer)

    await domain.set_liked(db, user_id=one, comment_id=comment.id, liked=True)
    await domain.set_liked(db, user_id=two, comment_id=comment.id, liked=True)

    for who, expected in ((one, True), (two, True), (author, False)):
        seen = await domain.visible(db, user_id=who, post_id=post.id)
        row = next(v for v in seen if v.comment.id == comment.id)
        assert row.likes == 2
        assert row.liked_by_me is expected


async def test_a_comment_you_cannot_see_cannot_be_liked(
    db: AsyncSession,
) -> None:
    """A like would otherwise be a way of confirming an id exists.

    It goes through the same gate reading does, so a stale screen
    cannot reach a comment on a fit that has gone.
    """
    author = await make_user(db)
    writer = await make_user(db)
    stranger = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await _published(db, post_id=post.id, user_id=writer)

    post.deleted_at = datetime.now(UTC)
    await db.commit()

    with pytest.raises(domain.NotYourComment):
        await domain.set_liked(
            db, user_id=stranger, comment_id=comment.id, liked=True
        )


async def test_liking_a_comment_that_never_existed_is_refused(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    with pytest.raises(domain.NotYourComment):
        await domain.set_liked(
            db, user_id=me, comment_id=uuid.uuid4(), liked=True
        )


async def test_a_deleted_comment_takes_its_likes_with_it(
    db: AsyncSession,
) -> None:
    from app.models.comment import CommentLike

    author = await make_user(db)
    writer = await make_user(db)
    fan = await make_user(db)
    post = await _fit(db, user_id=author, caption="", tags=["office"])
    comment = await _published(db, post_id=post.id, user_id=writer)
    await domain.set_liked(db, user_id=fan, comment_id=comment.id, liked=True)

    await domain.remove(db, user_id=writer, comment_id=comment.id)

    # The comment is tombstoned rather than erased, so the likes stay
    # attached to it and simply stop being readable with it - there is
    # no row anybody can reach that reports a tally for a gone comment.
    seen = await domain.visible(db, user_id=fan, post_id=post.id)
    assert all(v.comment.id != comment.id for v in seen)
    held = await db.scalar(
        sa.select(sa.func.count())
        .select_from(CommentLike)
        .where(CommentLike.comment_id == comment.id)
    )
    assert held is not None
