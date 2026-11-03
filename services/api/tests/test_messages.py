"""Direct messages.

They were gated on blocking and reporting shipping first. Both exist,
so these are the properties that keep that gate meaningful: a block
has to make the thread unreachable in both directions, hiding has to
be about one person's list rather than the other person's copy, and
opening somebody must not create anything.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import messages
from app.domain.moderation import block
from app.models.direct_message import DirectThread
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def test_a_message_creates_the_thread_and_both_sides_read_it(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    them = await make_user(db)

    await messages.send(db, sender_id=me, to_id=them, body="that jacket, where?")

    mine = await messages.thread_with(db, viewer_id=me, other_id=them)
    theirs = await messages.thread_with(db, viewer_id=them, other_id=me)
    assert mine is not None and theirs is not None
    assert [line.body for line in mine[1]] == ["that jacket, where?"]
    assert [line.body for line in theirs[1]] == ["that jacket, where?"]
    # `mine` is a fact about the reader, not about the row.
    assert mine[1][0].mine is True
    assert theirs[1][0].mine is False


async def test_one_thread_whichever_way_round_it_is_opened(
    db: AsyncSession,
) -> None:
    """Both writing at once must not make two threads, each holding
    half the conversation."""
    me = await make_user(db)
    them = await make_user(db)

    await messages.send(db, sender_id=me, to_id=them, body="hello")
    await messages.send(db, sender_id=them, to_id=me, body="hello back")

    rows = list(await db.scalars(DirectThread.__table__.select()))
    assert len(rows) == 1
    found = await messages.thread_with(db, viewer_id=me, other_id=them)
    assert found is not None
    assert [line.body for line in found[1]] == ["hello", "hello back"]


async def test_opening_somebody_creates_nothing(db: AsyncSession) -> None:
    me = await make_user(db)
    them = await make_user(db)

    found = await messages.thread_with(db, viewer_id=me, other_id=them)
    assert found is not None and found[1] == []
    assert list(await db.scalars(DirectThread.__table__.select())) == []
    # And nothing lands on either list.
    assert await messages.threads(db, user_id=them) == []


async def test_a_block_closes_the_thread_in_both_directions(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    them = await make_user(db)
    await messages.send(db, sender_id=me, to_id=them, body="hello")

    await block(db, blocker_id=them, blocked_id=me)

    assert await messages.thread_with(db, viewer_id=me, other_id=them) is None
    assert await messages.thread_with(db, viewer_id=them, other_id=me) is None
    with pytest.raises(messages.CannotMessage):
        await messages.send(db, sender_id=me, to_id=them, body="again")
    # And it is off both lists, rather than sitting there unopenable.
    assert await messages.threads(db, user_id=me) == []
    assert await messages.threads(db, user_id=them) == []


async def test_nobody_can_message_themselves(db: AsyncSession) -> None:
    me = await make_user(db)
    with pytest.raises(messages.CannotMessage):
        await messages.send(db, sender_id=me, to_id=me, body="note to self")


async def test_whitespace_is_not_a_message(db: AsyncSession) -> None:
    me = await make_user(db)
    them = await make_user(db)
    with pytest.raises(messages.EmptyMessage):
        await messages.send(db, sender_id=me, to_id=them, body="   \n ")


async def test_unread_counts_what_they_said_after_you_last_looked(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    them = await make_user(db)

    await messages.send(db, sender_id=them, to_id=me, body="one")
    await messages.send(db, sender_id=them, to_id=me, body="two")
    assert [row.unread for row in await messages.threads(db, user_id=me)] == [2]
    # Your own messages are never unread to you.
    assert [row.unread for row in await messages.threads(db, user_id=them)] == [0]

    await messages.mark_read(db, viewer_id=me, other_id=them)
    assert [row.unread for row in await messages.threads(db, user_id=me)] == [0]


async def test_hiding_is_one_persons_list_and_a_new_message_brings_it_back(
    db: AsyncSession,
) -> None:
    """Hiding is a preference about a list. If it swallowed messages it
    would be a delivery failure wearing one."""
    me = await make_user(db)
    them = await make_user(db)
    await messages.send(db, sender_id=them, to_id=me, body="hello")

    await messages.set_hidden(db, viewer_id=me, other_id=them, hidden=True)
    assert await messages.threads(db, user_id=me) == []
    # Theirs is untouched: it is their copy.
    assert len(await messages.threads(db, user_id=them)) == 1
    # And the conversation itself is still there when opened directly.
    found = await messages.thread_with(db, viewer_id=me, other_id=them)
    assert found is not None and len(found[1]) == 1

    await messages.send(db, sender_id=them, to_id=me, body="still there?")
    assert len(await messages.threads(db, user_id=me)) == 1


async def test_notifications_are_per_person_and_default_on(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    them = await make_user(db)
    await messages.send(db, sender_id=me, to_id=them, body="hello")

    assert await messages.settings_for(db, viewer_id=me, other_id=them) == (
        True,
        False,
    )
    await messages.set_notifies(db, viewer_id=me, other_id=them, notifies=False)
    assert await messages.settings_for(db, viewer_id=me, other_id=them) == (
        False,
        False,
    )
    # Turning yours off says nothing about theirs.
    assert await messages.settings_for(db, viewer_id=them, other_id=me) == (
        True,
        False,
    )


async def test_contacts_are_people_connected_either_way(
    db: AsyncSession,
) -> None:
    from app.models.follow import Follow

    me = await make_user(db)
    followed = await make_user(db)
    follower = await make_user(db)
    stranger = await make_user(db)
    db.add(Follow(follower_id=me, followee_id=followed))
    db.add(Follow(follower_id=follower, followee_id=me))
    await db.commit()

    found = {person.user_id for person in await messages.contacts(db, user_id=me)}
    assert found == {followed, follower}
    assert stranger not in found


async def test_a_blocked_person_is_not_a_contact(db: AsyncSession) -> None:
    from app.models.follow import Follow

    me = await make_user(db)
    them = await make_user(db)
    db.add(Follow(follower_id=me, followee_id=them))
    await db.commit()
    await block(db, blocker_id=me, blocked_id=them)

    assert await messages.contacts(db, user_id=me) == []


async def _picture(db: AsyncSession, *, user_id, kind: str = "message_media"):
    from tests.test_garment_media import make_asset

    asset = await make_asset(db, user_id=user_id)
    asset.kind = kind
    await db.commit()
    return asset


async def test_a_message_can_be_a_picture_with_no_words(db: AsyncSession) -> None:
    me = await make_user(db)
    them = await make_user(db)
    asset = await _picture(db, user_id=me)

    line = await messages.send(
        db, sender_id=me, to_id=them, body="", asset_id=asset.id
    )
    assert line.asset_id == asset.id

    seen = await messages.thread_with(db, viewer_id=them, other_id=me)
    assert seen is not None and seen[1][0].asset_id == asset.id
    # And the list has something to say for it.
    assert [row.last for row in await messages.threads(db, user_id=them)] == ["Photo"]


async def test_an_attachment_is_checked_against_its_owner_and_its_kind(
    db: AsyncSession,
) -> None:
    """A kind is a boundary here, not a label.

    Checking the owner alone would let anybody route one of their own
    garment photographs or avatar sources through a thread.
    """
    me = await make_user(db)
    them = await make_user(db)
    theirs = await _picture(db, user_id=them)
    wrong_kind = await _picture(db, user_id=me, kind="avatar_source")

    for asset_id in (theirs.id, wrong_kind.id):
        with pytest.raises(messages.BadAttachment):
            await messages.send(
                db, sender_id=me, to_id=them, body="look", asset_id=asset_id
            )


async def test_the_recipient_can_fetch_a_picture_sent_to_them(
    db: AsyncSession,
) -> None:
    """The gate that makes an attachment readable without making it
    readable by anybody holding the id."""
    me = await make_user(db)
    them = await make_user(db)
    stranger = await make_user(db)
    asset = await _picture(db, user_id=me)
    await messages.send(db, sender_id=me, to_id=them, body="", asset_id=asset.id)

    assert await messages.attachment_is_in_a_thread_with(
        db, viewer_id=them, asset_id=asset.id
    )
    assert not await messages.attachment_is_in_a_thread_with(
        db, viewer_id=stranger, asset_id=asset.id
    )

    # And a block closes it again, without deleting anything.
    await block(db, blocker_id=them, blocked_id=me)
    assert not await messages.attachment_is_in_a_thread_with(
        db, viewer_id=them, asset_id=asset.id
    )


async def test_unsending_takes_a_message_out_of_both_copies(
    db: AsyncSession,
) -> None:
    """A delete that left it standing in their conversation would be a
    button that lies."""
    me = await make_user(db)
    them = await make_user(db)
    line = await messages.send(db, sender_id=me, to_id=them, body="oops")

    assert await messages.unsend(db, user_id=me, message_id=line.id)

    mine = await messages.thread_with(db, viewer_id=me, other_id=them)
    theirs = await messages.thread_with(db, viewer_id=them, other_id=me)
    assert mine is not None and mine[1] == []
    assert theirs is not None and theirs[1] == []


async def test_only_the_sender_can_unsend(db: AsyncSession) -> None:
    me = await make_user(db)
    them = await make_user(db)
    line = await messages.send(db, sender_id=me, to_id=them, body="mine")

    assert not await messages.unsend(db, user_id=them, message_id=line.id)
    seen = await messages.thread_with(db, viewer_id=them, other_id=me)
    assert seen is not None and [row.body for row in seen[1]] == ["mine"]


async def test_clearing_a_conversation_is_one_persons_copy(
    db: AsyncSession,
) -> None:
    me = await make_user(db)
    them = await make_user(db)
    await messages.send(db, sender_id=them, to_id=me, body="one")
    await messages.send(db, sender_id=me, to_id=them, body="two")

    await messages.clear(db, viewer_id=me, other_id=them)

    mine = await messages.thread_with(db, viewer_id=me, other_id=them)
    theirs = await messages.thread_with(db, viewer_id=them, other_id=me)
    assert mine is not None and mine[1] == []
    assert theirs is not None and [row.body for row in theirs[1]] == ["one", "two"]
    # Off my list, still on theirs.
    assert await messages.threads(db, user_id=me) == []
    assert len(await messages.threads(db, user_id=them)) == 1


async def test_what_arrives_after_a_clear_arrives_normally(
    db: AsyncSession,
) -> None:
    """Clearing is not a way to stop hearing from somebody. Blocking is."""
    me = await make_user(db)
    them = await make_user(db)
    await messages.send(db, sender_id=them, to_id=me, body="before")
    await messages.clear(db, viewer_id=me, other_id=them)
    await messages.send(db, sender_id=them, to_id=me, body="after")

    mine = await messages.thread_with(db, viewer_id=me, other_id=them)
    assert mine is not None and [row.body for row in mine[1]] == ["after"]
    assert [row.unread for row in await messages.threads(db, user_id=me)] == [1]


# --------------------------------------------------------------------------- #
# read receipts, and the two different deletes
# --------------------------------------------------------------------------- #
async def test_a_sent_message_says_when_they_have_read_it(
    db: AsyncSession,
) -> None:
    a = await make_user(db)
    b = await make_user(db)
    await messages.send(db, sender_id=a, to_id=b, body="Is this still up?")

    before = await messages.thread_with(db, viewer_id=a, other_id=b)
    assert before is not None
    assert [line.read for line in before[1]] == [False]

    await messages.mark_read(db, viewer_id=b, other_id=a)

    after = await messages.thread_with(db, viewer_id=a, other_id=b)
    assert after is not None
    assert [line.read for line in after[1]] == [True]


async def test_nobody_is_told_whether_you_have_read_theirs(
    db: AsyncSession,
) -> None:
    """A receipt is about your own message arriving.

    Reporting on somebody's reading to them is a different thing, and
    their own thread already shows it.
    """
    a = await make_user(db)
    b = await make_user(db)
    await messages.send(db, sender_id=a, to_id=b, body="Morning")
    await messages.mark_read(db, viewer_id=b, other_id=a)

    theirs = await messages.thread_with(db, viewer_id=b, other_id=a)
    assert theirs is not None
    # The message is theirs to read, not theirs to have read.
    assert [line.read for line in theirs[1]] == [False]


async def test_hiding_a_message_changes_only_my_copy(db: AsyncSession) -> None:
    """The half that was missing.

    `unsend` belongs to the sender and leaves both conversations. A
    person who received something they would rather not scroll past
    could only clear the whole thread, which takes everything else
    with it.
    """
    a = await make_user(db)
    b = await make_user(db)
    line = await messages.send(db, sender_id=a, to_id=b, body="Forget I said that")

    assert await messages.hide_for_me(db, user_id=b, message_id=line.id) is True

    mine = await messages.thread_with(db, viewer_id=b, other_id=a)
    assert mine is not None and mine[1] == []

    # Untouched for the person who wrote it.
    theirs = await messages.thread_with(db, viewer_id=a, other_id=b)
    assert theirs is not None
    assert [row.body for row in theirs[1]] == ["Forget I said that"]


async def test_hiding_the_same_message_twice_is_the_same_state(
    db: AsyncSession,
) -> None:
    a = await make_user(db)
    b = await make_user(db)
    line = await messages.send(db, sender_id=a, to_id=b, body="Twice")

    assert await messages.hide_for_me(db, user_id=b, message_id=line.id) is True
    assert await messages.hide_for_me(db, user_id=b, message_id=line.id) is True


async def test_you_cannot_hide_a_message_from_a_thread_you_are_not_in(
    db: AsyncSession,
) -> None:
    """The same answer as "no such message".

    A different one would confirm that somebody else's message
    exists.
    """
    a = await make_user(db)
    b = await make_user(db)
    stranger = await make_user(db)
    line = await messages.send(db, sender_id=a, to_id=b, body="Private")

    assert await messages.hide_for_me(db, user_id=stranger, message_id=line.id) is False

    # And it is still there for both of the people who are in it.
    theirs = await messages.thread_with(db, viewer_id=b, other_id=a)
    assert theirs is not None and len(theirs[1]) == 1


async def test_a_sender_can_still_take_their_own_message_back(
    db: AsyncSession,
) -> None:
    """Hiding did not replace unsending; they are different acts."""
    a = await make_user(db)
    b = await make_user(db)
    line = await messages.send(db, sender_id=a, to_id=b, body="Oops")

    assert await messages.unsend(db, user_id=a, message_id=line.id) is True

    for viewer, other in ((a, b), (b, a)):
        seen = await messages.thread_with(db, viewer_id=viewer, other_id=other)
        assert seen is not None and seen[1] == []


async def test_a_client_is_told_what_kind_of_attachment_it_is(
    db: AsyncSession,
) -> None:
    """Otherwise it has to guess, and draws a video as a broken image."""
    from app.models.media_asset import MediaAsset

    a = await make_user(db)
    b = await make_user(db)

    sent = []
    for content_type in ("image/jpeg", "video/mp4", "audio/m4a"):
        asset = MediaAsset(
            user_id=a,
            kind="message_media",
            status="ready",
            content_type=content_type,
            max_bytes=1,
            byte_size=1,
            version=1,
            publication_consent=False,
        )
        db.add(asset)
        await db.flush()
        sent.append(
            await messages.send(db, sender_id=a, to_id=b, body="", asset_id=asset.id)
        )

    seen = await messages.thread_with(db, viewer_id=b, other_id=a)
    assert seen is not None
    assert [line.media_kind for line in seen[1]] == ['image', 'video', 'audio']


async def test_a_message_with_no_attachment_has_no_kind(db: AsyncSession) -> None:
    a = await make_user(db)
    b = await make_user(db)
    await messages.send(db, sender_id=a, to_id=b, body="Just words")

    seen = await messages.thread_with(db, viewer_id=b, other_id=a)
    assert seen is not None
    assert [line.media_kind for line in seen[1]] == [None]


def test_something_this_app_cannot_present_is_reported_as_nothing() -> None:
    # Better a bubble with no attachment drawn than a broken one, and
    # the server already refuses anything not uploaded as
    # `message_media` - this is about what a client can render.
    assert messages.media_kind_of("application/pdf") is None
    assert messages.media_kind_of(None) is None
    assert messages.media_kind_of("") is None
    assert messages.media_kind_of("IMAGE/PNG") == "image"


# --------------------------------------------------------------------------- #
# nobody reads a conversation they are not in
# --------------------------------------------------------------------------- #
async def _asset_for(db: AsyncSession, owner: uuid.UUID):
    from app.models.media_asset import MediaAsset

    asset = MediaAsset(
        user_id=owner,
        kind="message_media",
        status="ready",
        content_type="image/jpeg",
        max_bytes=1,
        byte_size=1,
        version=1,
        publication_consent=False,
    )
    db.add(asset)
    await db.flush()
    return asset


async def test_a_stranger_cannot_read_a_picture_sent_in_a_thread(
    db: AsyncSession,
) -> None:
    """The boundary the whole feature rests on.

    An asset id travels in a payload; it is not a secret. If holding
    one were enough, every picture anybody ever sent would be
    readable by anybody who saw the id.
    """
    a = await make_user(db)
    b = await make_user(db)
    stranger = await make_user(db)
    asset = await _asset_for(db, a)
    await messages.send(db, sender_id=a, to_id=b, body="", asset_id=asset.id)

    for viewer, allowed in ((a, True), (b, True), (stranger, False)):
        assert (
            await messages.attachment_is_in_a_thread_with(
                db, viewer_id=viewer, asset_id=asset.id
            )
            is allowed
        )


async def test_a_picture_stops_being_readable_when_the_message_goes(
    db: AsyncSession,
) -> None:
    """Asked per request, not flagged on the asset.

    A flag set on send would have to be cleared on every way a
    message stops being reachable, and the one that is forgotten is
    the one that leaks.
    """
    a = await make_user(db)
    b = await make_user(db)
    asset = await _asset_for(db, a)
    line = await messages.send(db, sender_id=a, to_id=b, body="", asset_id=asset.id)

    assert await messages.attachment_is_in_a_thread_with(
        db, viewer_id=b, asset_id=asset.id
    )
    await messages.unsend(db, user_id=a, message_id=line.id)
    assert not await messages.attachment_is_in_a_thread_with(
        db, viewer_id=b, asset_id=asset.id
    )


async def test_blocking_closes_the_picture_too(db: AsyncSession) -> None:
    a = await make_user(db)
    b = await make_user(db)
    asset = await _asset_for(db, a)
    await messages.send(db, sender_id=a, to_id=b, body="", asset_id=asset.id)

    await block(db, blocker_id=b, blocked_id=a)
    assert not await messages.attachment_is_in_a_thread_with(
        db, viewer_id=b, asset_id=asset.id
    )


async def test_a_stranger_cannot_read_or_touch_a_thread(db: AsyncSession) -> None:
    """Every door, not only the one that was being looked at."""
    a = await make_user(db)
    b = await make_user(db)
    stranger = await make_user(db)
    line = await messages.send(db, sender_id=a, to_id=b, body="Between us")

    # Cannot read it.
    seen = await messages.thread_with(db, viewer_id=stranger, other_id=a)
    assert seen is not None and seen[1] == [], "a stranger sees an empty thread"

    # Cannot take it back.
    assert await messages.unsend(db, user_id=stranger, message_id=line.id) is False
    # Cannot hide it.
    assert await messages.hide_for_me(db, user_id=stranger, message_id=line.id) is False
    # Cannot mark it read on somebody's behalf.
    await messages.mark_read(db, viewer_id=stranger, other_id=a)

    still = await messages.thread_with(db, viewer_id=b, other_id=a)
    assert still is not None
    assert [row.body for row in still[1]] == ["Between us"]
    assert [row.read for row in still[1]] == [False]
