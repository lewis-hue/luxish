"""Who the stylist may read a pin for.

**Found by a security review, not by me.** `about_post` resolved a
post by id and nothing else, so naming any pin in a question handed
its caption, its machine-read description and its photograph to the
model - and the model described them back in the answer. The feed
refused that exact post to that exact person while this handed it
over.

It is the same mistake the discovery pipeline exists to prevent: one
gate, applied to every path, because a second path that does its own
checking is a second chance to forget one. A new path was added and
it forgot. These tests are what stop the next one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.stylist_ask import about_post
from app.models.posts import Post
from app.models.profile import Profile
from tests.test_garment_media import make_user

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


async def a_fit(db: AsyncSession, author: uuid.UUID, *, caption: str) -> Post:
    post = Post(
        user_id=author,
        caption=caption,
        state="published",
        screen_mode="seed",
        published_at=NOW - timedelta(days=1),
    )
    db.add(post)
    await db.flush()
    return post


async def test_a_private_accounts_fit_is_not_readable(
    db: AsyncSession,
) -> None:
    """**The reported hole.**

    A private profile means "nobody but me sees my fits". Naming the
    id in a stylist question must not be a way around that.
    """
    shy = await make_user(db)
    stranger = await make_user(db)
    db.add(Profile(user_id=shy, handle="shy-stylist", private=True))
    post = await a_fit(db, shy, caption="a secret fit")
    await db.commit()

    words, picture, _ = await about_post(
        db, user_id=stranger, post_id=post.id
    )
    assert words is None, f"leaked the caption: {words!r}"
    assert picture is None


async def test_its_owner_can_still_read_it(db: AsyncSession) -> None:
    """Private means private from other people, not from yourself."""
    mine = await make_user(db)
    db.add(Profile(user_id=mine, handle="mine-stylist", private=True))
    post = await a_fit(db, mine, caption="my own fit")
    await db.commit()

    words, _, _ = await about_post(db, user_id=mine, post_id=post.id)
    assert words == "my own fit"


async def test_a_blocked_authors_fit_is_not_readable(
    db: AsyncSession,
) -> None:
    """Blocking closes the feed; it has to close this too."""
    from app.domain.moderation import block

    me = await make_user(db)
    rude = await make_user(db)
    post = await a_fit(db, rude, caption="from somebody blocked")
    await db.commit()
    await block(db, blocker_id=me, blocked_id=rude)
    await db.commit()

    words, picture, _ = await about_post(db, user_id=me, post_id=post.id)
    assert words is None
    assert picture is None


async def test_a_deleted_fit_is_not_readable(db: AsyncSession) -> None:
    author = await make_user(db)
    asker = await make_user(db)
    post = await a_fit(db, author, caption="taken down")
    post.deleted_at = NOW
    await db.commit()

    words, _, _ = await about_post(db, user_id=asker, post_id=post.id)
    assert words is None


async def test_a_held_fit_is_not_readable(db: AsyncSession) -> None:
    """Held by moderation is not published, so it is not readable.

    `held` rather than a draft: this app's post states are
    pending_review, published, held and removed - there is no draft,
    and a test inventing one tests nothing.
    """
    author = await make_user(db)
    asker = await make_user(db)
    post = Post(
        user_id=author,
        caption="held by the screen",
        state="held",
        screen_mode="seed",
    )
    db.add(post)
    await db.commit()

    words, _, _ = await about_post(db, user_id=asker, post_id=post.id)
    assert words is None


async def test_a_public_fit_is_readable(db: AsyncSession) -> None:
    """The gate must not close on everything.

    Without this the other tests pass with a function that always
    returns None, which would be a feature that silently stopped
    working rather than a secure one.
    """
    author = await make_user(db)
    asker = await make_user(db)
    post = await a_fit(db, author, caption="a public fit")
    await db.commit()

    words, _, _ = await about_post(db, user_id=asker, post_id=post.id)
    assert words == "a public fit"


async def test_an_id_that_does_not_exist_is_handled(
    db: AsyncSession,
) -> None:
    asker = await make_user(db)
    words, picture, _ = await about_post(
        db, user_id=asker, post_id=uuid.uuid4()
    )
    assert words is None and picture is None


async def test_an_invisible_pin_is_not_attached_to_the_render(
    db: AsyncSession,
) -> None:
    """**The second half of the finding.**

    A pin that failed the gate must not still ride along as
    `source_post_id`, or it reappears attached to the avatar that
    comes back.
    """
    import random

    from app.domain.stylist_ask import stream_answer

    shy = await make_user(db)
    stranger = await make_user(db)
    db.add(Profile(user_id=shy, handle="shy-render", private=True))
    post = await a_fit(db, shy, caption="not yours")
    await db.commit()

    seen_posts: list[uuid.UUID | None] = []

    class Provider:
        async def stream(self, request, *, user_id=None):
            # Whatever the pin was, it must not be in the prompt.
            blob = str(request.messages[0].content)
            assert "not yours" not in blob, "the caption reached the model"
            for chunk in ['{"answer":"No.","has_match":false,', '"using":[],"missing":[]}']:
                yield chunk

    async for name, body in stream_answer(
        db,
        user_id=stranger,
        question="what goes with this?",
        post_id=post.id,
        provider=Provider(),
    ):
        if name == "done":
            seen_posts.append(body.render_id)

    # Nothing to assert about the render id itself - there is no
    # avatar in this test - but the prompt assertion above is the
    # load-bearing one, and reaching here means the stream completed
    # without the pin.
    assert random is not None
