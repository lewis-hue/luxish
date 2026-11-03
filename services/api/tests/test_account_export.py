"""A copy of everything somebody put in.

**The first test in this file is the one that matters.** Every other
property here is a feature working or not working; that one is the
difference between a privacy control and a data breach. Two populated
accounts, two exports, and neither may contain a trace of the other.
A missing `WHERE user_id` anywhere in the gather does not show up as
wrong data on a screen where somebody would notice - it shows up as a
file, handed to a person, containing a stranger's wardrobe and a
stranger's conversations.

The rest divides into what must be in (it is useless otherwise), what
must never be in (credentials, other people's), and the properties of
the artifact itself (it expires, it is capped, and it says when it
was capped).
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import account_export as domain
from app.models.account_export import AccountExport
from app.models.comment import PostComment
from app.models.consent import Consent
from app.models.direct_message import (
    DirectMessage,
    DirectThread,
    DirectThreadMember,
)
from app.models.garment import Garment
from app.models.media_asset import MediaAsset
from app.models.moodboard import Moodboard
from app.models.posts import Post, PostMedia
from app.models.profile import Profile
from app.workers.account_export import (
    MAX_ARCHIVE_BYTES,
    build_export,
)
from tests.test_garment_media import make_user


class Store:
    """Object storage, in a dict. Records every read."""

    def __init__(self, *, missing: set[str] | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.missing = missing or set()
        self.reads: list[str] = []

    async def read(self, asset: Any) -> bytes:
        from app.errors import CapabilityUnavailable

        key = asset.storage_key
        self.reads.append(key)
        if key in self.missing or key not in self.objects:
            raise CapabilityUnavailable(
                "no such object", detail={"reason": "missing_object"}
            )
        return self.objects[key]

    async def write(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data


class Job:
    def __init__(self, export_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.payload = {"export_id": str(export_id)}


# --------------------------------------------------------------------------- #
# Building an account with something in it
# --------------------------------------------------------------------------- #
async def populate(
    db: AsyncSession, store: Store, *, label: str
) -> dict[str, Any]:
    """One account with a row in every exported table.

    `label` goes into every text field, so a leak between two accounts
    is a substring search rather than an id comparison - a test that
    compares ids passes while the *words* of somebody's bio sit in
    another person's file.
    """
    user_id = await make_user(db)

    db.add(
        Profile(
            user_id=user_id,
            handle=f"handle-{label}",
            bio=f"bio-{label}",
            links=[f"https://{label}.example"],
            private=False,
        )
    )

    asset = MediaAsset(
        user_id=user_id,
        kind="outfit_photo",
        status="ready",
        content_type="image/png",
        max_bytes=1_000_000,
        byte_size=8,
        storage_key=f"originals/{label}-{uuid.uuid4().hex}.png",
        width=600,
        height=800,
    )
    db.add(asset)
    await db.flush()
    store.objects[asset.storage_key] = f"bytes-{label}".encode()

    db.add(
        Garment(
            user_id=user_id,
            media_asset_id=asset.id,
            name=f"garment-{label}",
            category="tshirt",
            confirmed_attributes={"note": f"confirmed-{label}"},
            inferred_attributes={},
        )
    )

    post = Post(
        user_id=user_id,
        caption=f"caption-{label}",
        state="published",
        screen_mode="seed",
    )
    db.add(post)
    await db.flush()
    db.add(PostMedia(post_id=post.id, media_asset_id=asset.id, position=0))
    db.add(
        PostComment(
            post_id=post.id,
            user_id=user_id,
            body=f"comment-{label}",
            state="published",
            screen_mode="seed",
        )
    )
    db.add(Moodboard(user_id=user_id, name=f"board-{label}"))
    db.add(
        Consent(
            user_id=user_id,
            kind="ai_processing",
            granted_at=datetime.now(UTC),
            source="profile",
        )
    )
    await db.commit()
    return {"user_id": user_id, "asset": asset, "post": post, "label": label}


async def thread_between(
    db: AsyncSession, a: uuid.UUID, b: uuid.UUID, *, said: dict[uuid.UUID, str]
) -> DirectThread:
    """A real thread, with both member rows.

    The member rows are not decoration: `hide_for_me` refuses without
    one and `cleared_at` lives on it, so a helper that skipped them
    made both of those silently do nothing - and a test asserting
    something was hidden then passed while nothing was.
    """
    lower, upper = sorted([a, b], key=str)
    thread = DirectThread(lower_id=lower, upper_id=upper)
    db.add(thread)
    await db.flush()
    db.add(DirectThreadMember(thread_id=thread.id, user_id=a))
    db.add(DirectThreadMember(thread_id=thread.id, user_id=b))
    for sender, body in said.items():
        db.add(DirectMessage(thread_id=thread.id, sender_id=sender, body=body))
    await db.commit()
    return thread


def opened(store: Store, row: AccountExport) -> tuple[dict[str, Any], list[str]]:
    """The manifest and the file list out of a built archive."""
    assert row.storage_key is not None
    with zipfile.ZipFile(io.BytesIO(store.objects[row.storage_key])) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("my-data.json"))
    return manifest, names


# --------------------------------------------------------------------------- #
# The test that matters
# --------------------------------------------------------------------------- #
async def test_an_export_contains_nothing_of_anybody_elses(
    db: AsyncSession,
) -> None:
    """**The whole point of the allow-list and every `WHERE user_id`.**

    Two accounts, each with a row in every exported table and its own
    word in every text field. Mine must contain all of my words and
    none of theirs.

    Searched as text over the whole serialised export rather than
    field by field: a field-by-field check only ever finds the leaks
    somebody thought to look for, and the failure mode here is a
    query somebody forgot to scope.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    theirs = await populate(db, store, label="theirs")

    whole = json.dumps(await domain.gather(db, user_id=mine["user_id"]))

    # Everything of mine is there.
    for word in ("bio-mine", "handle-mine", "garment-mine", "caption-mine",
                 "comment-mine", "board-mine", "confirmed-mine"):
        assert word in whole, f"my own {word} is missing from my export"

    # Nothing of theirs is.
    for word in ("bio-theirs", "handle-theirs", "garment-theirs",
                 "caption-theirs", "comment-theirs", "board-theirs",
                 "confirmed-theirs"):
        assert word not in whole, f"LEAK: {word} is in somebody else's export"

    assert str(theirs["user_id"]) not in whole
    assert str(theirs["asset"].id) not in whole


async def test_a_conversation_i_am_not_in_is_not_in_my_export(
    db: AsyncSession,
) -> None:
    """Threads are scoped by membership, which is the security boundary.

    Three people: a thread I am in and a thread between the other two.
    Mine shows one conversation.
    """
    me = await make_user(db)
    them = await make_user(db)
    stranger = await make_user(db)

    await thread_between(db, me, them, said={me: "mine-to-them"})
    await thread_between(db, them, stranger, said={them: "none-of-my-business"})

    whole = json.dumps(await domain.gather(db, user_id=me))
    assert "mine-to-them" in whole
    assert "none-of-my-business" not in whole

    out = await domain.gather(db, user_id=me)
    assert len(out["conversations"]) == 1


async def test_both_sides_of_my_own_conversation_are_included(
    db: AsyncSession,
) -> None:
    """Deliberate: half a conversation is not a record of anything.

    Their words are already on my screen in the app and have been
    since they were sent, so withholding them from the file changes
    nothing about who can read them.
    """
    me = await make_user(db)
    them = await make_user(db)
    await thread_between(
        db, me, them, said={me: "what-i-said", them: "what-they-said"}
    )

    out = await domain.gather(db, user_id=me)
    bodies = {m["body"]: m["sent_by_me"] for m in out["conversations"][0]["messages"]}
    assert bodies == {"what-i-said": True, "what-they-said": False}


async def test_a_message_i_deleted_for_myself_stays_deleted(
    db: AsyncSession,
) -> None:
    """The export must not contradict the app.

    Deletion here is two-sided: a row can be gone for one reader and
    present for the other. Without the hidden-for-me join, an export
    would hand somebody back every message they had removed from
    their own view.
    """
    from app.domain.messages import hide_for_me

    me = await make_user(db)
    them = await make_user(db)
    thread = await thread_between(
        db, me, them, said={them: "regret-reading-this", me: "still-here"}
    )

    doomed = await db.scalar(
        sa.select(DirectMessage).where(
            DirectMessage.thread_id == thread.id,
            DirectMessage.body == "regret-reading-this",
        )
    )
    assert doomed is not None
    took = await hide_for_me(db, user_id=me, message_id=doomed.id)
    assert took is True, "the hide did not happen, so this test proves nothing"
    await db.commit()

    whole = json.dumps(await domain.gather(db, user_id=me))
    assert "regret-reading-this" not in whole
    assert "still-here" in whole

    # And it is still there for the other person, who did not delete it.
    assert "regret-reading-this" in json.dumps(
        await domain.gather(db, user_id=them)
    )


# --------------------------------------------------------------------------- #
# What must never be in it
# --------------------------------------------------------------------------- #
async def test_no_credential_is_ever_exported(db: AsyncSession) -> None:
    """A session token in a file somebody emails themselves is a key.

    Asserted against the real rows rather than against the allow-list,
    because the allow-list is the thing that could be wrong.
    """
    from app.models.push import DeviceToken

    store = Store()
    mine = await populate(db, store, label="mine")

    db.add(
        DeviceToken(
            user_id=mine["user_id"],
            token="ExponentPushToken[SECRET-DO-NOT-EXPORT]",
            platform="expo",
        )
    )
    await db.commit()

    whole = json.dumps(await domain.gather(db, user_id=mine["user_id"]))
    assert "SECRET-DO-NOT-EXPORT" not in whole


async def test_it_says_what_it_leaves_out(db: AsyncSession) -> None:
    """A list of what is included cannot say what was refused.

    The file carries the reasons, so somebody reading it can tell a
    deliberate omission from a gap.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    out = await domain.gather(db, user_id=mine["user_id"])

    assert out["not_included"] == domain.NEVER_EXPORTED
    assert "push_tokens" in out["not_included"]
    assert "moderation_reports_about_them" in out["not_included"]
    # Every entry says why, not just that.
    assert all(len(why) > 10 for why in out["not_included"].values())


# --------------------------------------------------------------------------- #
# The artifact
# --------------------------------------------------------------------------- #
async def test_the_archive_carries_the_pictures_themselves(
    db: AsyncSession,
) -> None:
    """**Not a file of links.** Those die with the account.

    An export taken on the way out would otherwise be a manifest of
    dead URLs - useless at exactly the moment it is for.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()

    outcome = await build_export(db, Job(row.id), store=store)
    assert outcome["state"] == "ready"

    await db.refresh(row)
    manifest, names = opened(store, row)
    assert "my-data.json" in names
    assert manifest["pictures"], "the manifest names no pictures"
    for entry in manifest["pictures"]:
        assert entry["file"] in names, f"{entry['file']} is named but not in the zip"
    assert row.pictures_included == len(manifest["pictures"])


async def test_a_picture_whose_file_has_gone_does_not_sink_the_export(
    db: AsyncSession,
) -> None:
    """The textual data is the part nobody can reconstruct.

    Losing one photograph must not cost somebody their whole account
    history, so a missing object is recorded and the archive carries
    on.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    store.missing.add(mine["asset"].storage_key)

    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    outcome = await build_export(db, Job(row.id), store=store)

    assert outcome["state"] == "ready"
    await db.refresh(row)
    manifest, _ = opened(store, row)
    assert row.pictures_omitted == 1
    assert manifest["pictures_omitted"][0]["reason"] == "file_missing"
    # And the data is all still there.
    assert "caption-mine" in json.dumps(manifest)


async def test_a_cap_is_reported_rather_than_silent(db: AsyncSession) -> None:
    """A truncated archive that says nothing reads as a complete one.

    Somebody would find out it was not at the worst possible time.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    # One picture larger than the whole budget.
    big = MediaAsset(
        user_id=mine["user_id"],
        kind="outfit_photo",
        status="ready",
        content_type="image/png",
        max_bytes=1,
        byte_size=1,
        storage_key=f"originals/huge-{uuid.uuid4().hex}.png",
    )
    db.add(big)
    await db.commit()
    store.objects[big.storage_key] = b"x" * (MAX_ARCHIVE_BYTES + 1)

    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    await build_export(db, Job(row.id), store=store)

    await db.refresh(row)
    manifest, names = opened(store, row)
    assert row.pictures_omitted >= 1
    reasons = {o["reason"] for o in manifest["pictures_omitted"]}
    assert "archive_full" in reasons
    assert "about_omitted_pictures" in manifest, "capped without saying so"


async def test_asking_twice_does_not_queue_two(db: AsyncSession) -> None:
    """Building one reads every picture somebody owns.

    A button that queues one per tap bills that from an impatient
    finger.
    """
    from app.models.job import Job as JobRow

    store = Store()
    mine = await populate(db, store, label="mine")

    first = await domain.request(db, user_id=mine["user_id"])
    second = await domain.request(db, user_id=mine["user_id"])
    await db.commit()

    assert first.id == second.id
    queued = (
        await db.scalars(
            sa.select(JobRow).where(JobRow.kind == "account.export")
        )
    ).all()
    assert len(queued) == 1


async def test_a_finished_export_can_be_asked_for_again(
    db: AsyncSession,
) -> None:
    """The one-at-a-time rule is about work in flight, not a lockout.

    Somebody whose export expired must be able to get another.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    first = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    await build_export(db, Job(first.id), store=store)

    second = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    assert second.id != first.id


async def test_rebuilding_a_finished_export_does_no_work(
    db: AsyncSession,
) -> None:
    """A re-dispatched job must not bill every picture read twice."""
    store = Store()
    mine = await populate(db, store, label="mine")
    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()

    await build_export(db, Job(row.id), store=store)
    reads = len(store.reads)

    again = await build_export(db, Job(row.id), store=store)
    assert again["state"] == "ready"
    assert len(store.reads) == reads


# --------------------------------------------------------------------------- #
# Who may download it, and for how long
# --------------------------------------------------------------------------- #
async def test_only_its_owner_can_read_it(db: AsyncSession) -> None:
    store = Store()
    mine = await populate(db, store, label="mine")
    other = await make_user(db)

    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    await build_export(db, Job(row.id), store=store)

    assert await domain.readable(
        db, user_id=mine["user_id"], export_id=row.id
    ) is not None
    assert await domain.readable(db, user_id=other, export_id=row.id) is None


async def test_it_stops_being_downloadable(db: AsyncSession) -> None:
    """**An export is the most sensitive object this system writes.**

    One file holding a wardrobe, a set of conversations and every
    picture somebody owns. A link that works forever makes one leaked
    URL a permanent breach.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    await build_export(db, Job(row.id), store=store)

    await db.refresh(row)
    assert row.expires_at is not None

    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    assert await domain.readable(
        db, user_id=mine["user_id"], export_id=row.id
    ) is None
    await db.refresh(row)
    assert row.state == "expired"


async def test_an_expiry_without_a_timezone_still_refuses(
    db: AsyncSession,
) -> None:
    """SQLite hands back a naive datetime.

    Comparing it to an aware one raises, which would turn the expiry
    check into a 500 - and a 500 from `readable` would leave the
    download working. This is the one check that must fail closed, so
    the naive case is pinned rather than left to the driver.
    """
    store = Store()
    mine = await populate(db, store, label="mine")
    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    await build_export(db, Job(row.id), store=store)
    await db.refresh(row)

    row.expires_at = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None)
    assert domain._has_expired(row) is True


async def test_the_latest_one_is_what_the_screen_sees(
    db: AsyncSession,
) -> None:
    store = Store()
    mine = await populate(db, store, label="mine")
    assert await domain.latest_for(db, user_id=mine["user_id"]) is None

    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()
    seen = await domain.latest_for(db, user_id=mine["user_id"])
    assert seen is not None and seen.id == row.id
    assert seen.state == "gathering"


async def test_a_deleted_account_cannot_be_gathered(db: AsyncSession) -> None:
    """There is nothing to hand over, and the job should say so."""
    store = Store()
    mine = await populate(db, store, label="mine")
    from app.models.user import User

    user = await db.get(User, mine["user_id"])
    assert user is not None
    user.deleted_at = datetime.now(UTC)
    await db.commit()

    with pytest.raises(domain.NothingToExport):
        await domain.gather(db, user_id=mine["user_id"])


async def test_a_job_for_a_deleted_account_fails_in_the_owners_terms(
    db: AsyncSession,
) -> None:
    store = Store()
    mine = await populate(db, store, label="mine")
    row = await domain.request(db, user_id=mine["user_id"])
    await db.commit()

    from app.models.user import User

    user = await db.get(User, mine["user_id"])
    assert user is not None
    user.deleted_at = datetime.now(UTC)
    await db.commit()

    outcome = await build_export(db, Job(row.id), store=store)
    assert outcome["state"] == "failed"
    await db.refresh(row)
    # Readable by the person, not a stack trace.
    assert row.failure is not None
    assert "exist" in row.failure.lower()


async def test_a_conversation_i_cleared_stays_cleared(db: AsyncSession) -> None:
    """The second way a message leaves somebody's own copy.

    Hiding one message and clearing a whole history are separate
    mechanisms, and an export honouring only the first would hand back
    every message in a conversation somebody had cleared. Found by
    writing the hidden-message test and then checking what else the
    thread view filters that this did not.

    Per thread, deliberately: clearing one conversation says nothing
    about another.
    """
    from app.domain.messages import clear

    me = await make_user(db)
    them = await make_user(db)
    other = await make_user(db)

    await thread_between(db, me, them, said={them: "before-the-clear"})
    await thread_between(db, me, other, said={other: "untouched-thread"})

    await clear(db, viewer_id=me, other_id=them)
    await db.commit()

    whole = json.dumps(await domain.gather(db, user_id=me))
    assert "before-the-clear" not in whole
    # The other conversation is not collateral.
    assert "untouched-thread" in whole

    # And the person who did not clear it still has it.
    assert "before-the-clear" in json.dumps(await domain.gather(db, user_id=them))


async def test_every_state_the_code_can_set_is_a_declared_one(
    db: AsyncSession,
) -> None:
    """`EXPORT_STATES` is a claim, so something has to hold it to it.

    There is no CHECK on the column, so a typo in a state string
    would persist happily and the screen would fall through every
    branch of its switch and say nothing at all. Collected from the
    source rather than listed again here, because a list copied into
    a test is a list that agrees with itself.
    """
    import re
    from pathlib import Path

    from app.models.account_export import EXPORT_STATES

    assigned: set[str] = set()
    for path in (
        Path("app/domain/account_export.py"),
        Path("app/workers/account_export.py"),
    ):
        for found in re.finditer(
            r'(?:row|export)\.state\s*=\s*"([a-z_]+)"', path.read_text(encoding="utf-8")
        ):
            assigned.add(found.group(1))

    assert assigned, "found no state assignments, so this test proves nothing"
    assert assigned <= EXPORT_STATES, (
        f"undeclared state(s): {sorted(assigned - EXPORT_STATES)}"
    )
    # And the default the row is created with.
    row = AccountExport(user_id=uuid.uuid4())
    db.add(row)
    assert (row.state or "gathering") in EXPORT_STATES
    db.expunge(row)


async def test_what_you_did_is_yours_and_what_was_done_to_you_is_not(
    db: AsyncSession,
) -> None:
    """**The asymmetry, in both directions.**

    A report I filed is my own words and my own action, so it is in. A
    report filed about me names its reporter, so it is out. A block I
    made is my choice, so it is in. A block *of* me is the other
    person's, and telling somebody who blocked them is a harm to the
    blocker - blocking is meant to be quiet.

    Written because the first version of `NEVER_EXPORTED` named only
    one side of each, which read as though the other was included
    when it was not.
    """
    from app.models.moderation import Block, Report

    me = await make_user(db)
    them = await make_user(db)

    db.add(
        Report(
            reporter_id=me,
            subject_kind="post",
            subject_user_id=them,
            subject_ref=str(uuid.uuid4()),
            guideline_id="no-harassment",
            reason="inappropriate",
            note="my-own-words",
            state="open",
        )
    )
    db.add(
        Report(
            reporter_id=them,
            subject_kind="post",
            subject_user_id=me,
            subject_ref=str(uuid.uuid4()),
            guideline_id="no-harassment",
            reason="inappropriate",
            note="somebody-reported-me",
            state="open",
        )
    )
    db.add(Block(blocker_id=me, blocked_id=them))
    db.add(Block(blocker_id=them, blocked_id=me))
    await db.commit()

    out = await domain.gather(db, user_id=me)
    whole = json.dumps(out)

    # Mine.
    assert "my-own-words" in whole
    assert [b["user_id"] for b in out["people_you_blocked"]] == [str(them)]

    # Not mine.
    assert "somebody-reported-me" not in whole, (
        "LEAK: a report filed about this person is in their export, "
        "which identifies whoever filed it"
    )
    assert len(out["things_you_reported"]) == 1
    # And nothing anywhere says they were blocked.
    assert "blocked_by" not in whole
