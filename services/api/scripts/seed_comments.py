"""Put conversation under the seeded fits.

A board of photographs with no comments under any of them does not look
like a quiet app; it looks like a broken one. This writes remarks from
the seeded people onto each other's fits, weighted the way attention
actually falls: a fit a lot of people reacted to gets more of them.

**Seeded, and marked as such.** Every comment carries
``screen_mode = "seed"`` and publishes without a billed screening call,
which is the same bargain the seeded posts already take. A comment
somebody actually types goes through the screen.

**Nobody comments on their own fit.** It reads as a bug, and the
sentences below are all written as one person talking to another.

Usage::

    python scripts/seed_comments.py           # fill in what is missing
    python scripts/seed_comments.py --wipe    # start the threads over
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402

from app.db.session import session_scope  # noqa: E402
from app.domain import comments as domain  # noqa: E402
from app.models.comment import PostComment  # noqa: E402
from app.models.posts import Post  # noqa: E402
from app.models.profile import PostReaction  # noqa: E402
from app.models.user import User  # noqa: E402

#: Said about a fit, not about a person. Short, specific to clothes, and
#: none of them a compliment on somebody's body: these sit under
#: photographs of real people and the tone is the product.
REMARKS: tuple[str, ...] = (
    "the colour on this is so good",
    "where are the trousers from",
    "this is exactly the silhouette I keep trying to get right",
    "the layering here is doing a lot of work",
    "ok the shoes though",
    "saving this for autumn",
    "how is it this put together",
    "the proportions are perfect",
    "need the jacket",
    "this fit eats",
    "the texture on that knit",
    "stealing this for next week",
    "clean. nothing wasted",
    "that colour combination should not work and it does",
    "the fit of those trousers is unreal",
    "this is the one",
    "what size is the top",
    "so good for a weekday",
    "the styling here is quiet and expensive",
    "been looking for a coat like that for months",
)

#: Answers, which are what make a thread read like one rather than like
#: a list of first impressions.
REPLIES: tuple[str, ...] = (
    "thank you",
    "thrifted, ages ago",
    "honestly it was a lucky find",
    "they run big, size down",
    "got it on sale last year",
    "same, took me three tries",
    "you should, it goes with everything",
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wipe", action="store_true", help="remove seeded ones first")
    args = parser.parse_args()

    # Deterministic, so re-running produces the same world rather than a
    # different one every time somebody demonstrates the app.
    shuffle = random.Random(20261031)

    async with session_scope() as db:
        if args.wipe:
            removed = await db.execute(
                sa.delete(PostComment).where(PostComment.screen_mode == "seed")
            )
            await db.commit()
            print(f"removed {removed.rowcount} seeded comments")

        people = list(
            (
                await db.scalars(
                    sa.select(User.id).where(User.deleted_at.is_(None))
                )
            ).all()
        )
        posts = list(
            (
                await db.scalars(
                    sa.select(Post).where(
                        Post.state == "published", Post.deleted_at.is_(None)
                    )
                )
            ).all()
        )
        # How much attention each fit already has, so the threads land
        # where the reactions did rather than evenly.
        reactions = dict(
            (
                await db.execute(
                    sa.select(PostReaction.post_id, sa.func.count())
                    .group_by(PostReaction.post_id)
                )
            ).all()
        )

    print(f"{len(posts)} fits, {len(people)} people.")
    written = 0
    threads = 0

    for post in posts:
        async with session_scope() as db:
            already = await db.scalar(
                sa.select(sa.func.count())
                .select_from(PostComment)
                .where(
                    PostComment.post_id == post.id,
                    PostComment.deleted_at.is_(None),
                )
            )
            if int(already or 0) > 0:
                continue

            # Busier fits get busier threads. A fit nobody reacted to
            # usually gets nothing, which is also true.
            heat = int(reactions.get(post.id, 0))
            wanted = min(5, shuffle.randint(0, 1) + heat // 3)
            if wanted == 0:
                continue

            speakers = [p for p in people if p != post.user_id]
            if not speakers:
                continue
            shuffle.shuffle(speakers)

            top = None
            for index in range(wanted):
                author = speakers[index % len(speakers)]
                try:
                    comment = await domain.write(
                        db,
                        user_id=author,
                        post_id=post.id,
                        body=shuffle.choice(REMARKS),
                        seeded=True,
                    )
                except domain.FitNotVisible:
                    break
                except Exception as caught:  # noqa: BLE001 - one fit is not a run
                    print(f"  {post.id}: {caught}")
                    break
                top = top or comment
                written += 1

            # The author answers one of them, which is what turns a list
            # of remarks into a conversation.
            if top is not None and shuffle.random() < 0.55:
                try:
                    await domain.write(
                        db,
                        user_id=post.user_id,
                        post_id=post.id,
                        body=shuffle.choice(REPLIES),
                        parent_id=top.id,
                        seeded=True,
                    )
                    written += 1
                except Exception:  # noqa: BLE001
                    pass
            threads += 1

    print(f"\nWrote {written} comments across {threads} fits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
