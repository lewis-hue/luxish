"""Every taste answer lands on a shelf that has pins on it.

**Measured against the 633 published pins and it did not.** Three
vocabularies, none agreeing: onboarding asks in one language, the
board groups in a second, authors tag in a third.

* three aesthetics reached no group - `downtown-romantic`,
  `dark-academia`, `blokecore` - because the bridge was a string
  edit (strip the hyphen, hope it matches a tag) and those three
  happened not to match;
* ten occasions reached no group;
* and occasions were read by nothing at all. The most specific
  question in onboarding changed nothing about what anybody saw.

These tests are the reason the map can be trusted: they fail when a
vocabulary grows a word nobody gave a home to, which is exactly how
the first three went missing.
"""

from __future__ import annotations

import pytest

from app.domain.feed import GROUPS
from app.domain.taste import AESTHETICS, OCCASIONS
from app.domain.taste_bridge import (
    AESTHETIC_GROUPS,
    OCCASION_GROUPS,
    groups_for,
    unmapped,
)


def test_every_aesthetic_reaches_a_group() -> None:
    dead_aesthetics, _ = unmapped()
    assert dead_aesthetics == (), (
        f"{dead_aesthetics} lead nowhere: somebody picks one and sees "
        "an empty shelf"
    )


def test_every_occasion_reaches_a_group() -> None:
    _, dead_occasions = unmapped()
    assert dead_occasions == (), (
        f"{dead_occasions} lead nowhere: an answer that changes nothing"
    )


def test_no_mapping_points_at_a_group_that_does_not_exist() -> None:
    """A typo here is an answer that silently leads nowhere, which is
    the failure this whole module exists to stop."""
    named = {
        group
        for groups in (*AESTHETIC_GROUPS.values(), *OCCASION_GROUPS.values())
        for group in groups
    }
    assert named <= set(GROUPS), f"{sorted(named - set(GROUPS))} are not groups"


def test_the_map_covers_the_vocabularies_and_nothing_else() -> None:
    """Both directions. An entry for a word that is not offered is
    dead weight that reads as coverage."""
    assert set(AESTHETIC_GROUPS) == set(AESTHETICS)
    assert set(OCCASION_GROUPS) == set(OCCASIONS)


def test_two_answers_for_one_shelf_are_one_shelf() -> None:
    """Somebody who picked `minimalist` and `monochrome` has
    described one taste twice, not expressed a stronger preference
    for it."""
    assert groups_for(aesthetics=("minimalist", "monochrome")) == {"minimal"}


def test_occasions_reach_retrieval_on_their_own() -> None:
    """They were stored and read by nothing. Somebody who answered
    only this question saw the default board."""
    assert groups_for(occasions=("gym",)) == {"workout"}
    assert groups_for(occasions=("office", "funeral")) == {"office"}


def test_the_three_that_used_to_lead_nowhere_now_land(
) -> None:
    """Named individually because the string-edit bridge made them
    look covered."""
    assert groups_for(aesthetics=("downtown-romantic",)) == {"romantic"}
    assert groups_for(aesthetics=("blokecore",)) == {"streetwear", "denim"}
    assert groups_for(aesthetics=("dark-academia",)) == {"vintage", "office"}


def test_place_of_worship_goes_to_modest() -> None:
    """The one mapping in the occasion table that is not a
    compromise, and worth keeping honest."""
    assert groups_for(occasions=("place-of-worship",)) == {"modest"}


def test_an_unknown_answer_is_ignored_rather_than_raised_on() -> None:
    """A vocabulary entry retired in a later release must not make
    somebody's stored profile unreadable - the same rule
    `Taste.from_stored` follows."""
    assert groups_for(aesthetics=("a-look-we-retired",)) == set()
    assert groups_for(occasions=("", "nonsense")) == set()


def test_saying_nothing_points_at_nothing() -> None:
    """Declining the questions is an answer, and it must not quietly
    pin somebody to a shelf."""
    assert groups_for() == set()


@pytest.mark.anyio
async def test_every_group_the_map_points_at_has_pins(db) -> None:
    """**The point of the whole exercise.**

    A mapping to a group with nothing in it is the same empty shelf
    wearing a different name. This is the test that would have
    caught the original problem, and it runs against whatever the
    seeded board actually holds.
    """
    import collections

    import sqlalchemy as sa

    from app.domain.feed import categorise
    from app.models.posts import Post
    from app.models.profile import PostTag

    rows = (
        await db.execute(
            sa.select(PostTag.post_id, PostTag.tag)
            .join(Post, Post.id == PostTag.post_id)
            .where(Post.state == "published", Post.deleted_at.is_(None))
        )
    ).all()
    if not rows:
        pytest.skip("no seeded board in this database")

    by_post: dict = collections.defaultdict(list)
    for post_id, tag in rows:
        by_post[post_id].append(tag)

    have = collections.Counter()
    for tags in by_post.values():
        for group in categorise(tags):
            have[group] += 1

    named = {
        group
        for groups in (*AESTHETIC_GROUPS.values(), *OCCASION_GROUPS.values())
        for group in groups
    }
    empty = sorted(group for group in named if not have.get(group))
    assert not empty, f"these groups have no pins: {empty}"
