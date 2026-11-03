"""Public identity: what crosses to a stranger, and what must not.

A profile is the one surface that is *about* a person rather than about
clothes, so the visibility rules that apply everywhere else have to
apply here too — and the easiest way for that to be wrong is for this
endpoint to be written without them.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import profiles as domain
from app.models.user import User
from tests.test_garment_media import make_user

pytestmark = pytest.mark.anyio


async def test_a_handle_is_claimed_once_and_validated(db: AsyncSession) -> None:
    owner = await make_user(db)
    other = await make_user(db)

    profile = await domain.set_handle(db, user_id=owner, handle="@StoleHerKsubiii")
    assert profile.handle == "stoleherksubiii", "stored lowercase, without the @"

    with pytest.raises(domain.HandleTaken):
        await domain.set_handle(db, user_id=other, handle="stoleherksubiii")

    for bad in ("ab", "x" * 31, "has space", "admin", "stylist"):
        with pytest.raises(domain.BadHandle):
            await domain.set_handle(db, user_id=other, handle=bad)

    # Setting your own handle to itself is a no-op, not a clash.
    assert (
        await domain.set_handle(db, user_id=owner, handle="stoleherksubiii")
    ).handle == "stoleherksubiii"


async def test_a_link_can_only_point_at_the_platform_it_names(
    db: AsyncSession,
) -> None:
    """A URL in a profile field is an open redirect wearing a costume."""
    owner = await make_user(db)
    profile = await domain.set_links(
        db, user_id=owner, links={"tiktok": "@iillegalsaac"}
    )
    assert profile.links == {"tiktok": "iillegalsaac"}
    assert (
        domain.address_for("tiktok", "iillegalsaac")
        == "https://www.tiktok.com/@iillegalsaac"
    )

    for hostile in ("http://evil.example/x", "a/../../b", "x?next=evil", "a b"):
        with pytest.raises(domain.BadLink):
            await domain.set_links(db, user_id=owner, links={"tiktok": hostile})
    with pytest.raises(domain.BadLink):
        await domain.set_links(db, user_id=owner, links={"myspace": "someone"})


async def test_a_bio_does_not_cross_until_the_screen_agrees(
    db: AsyncSession,
) -> None:
    owner = await make_user(db)
    profile = await domain.set_bio(db, user_id=owner, bio="Nairobi. Mostly denim.")

    assert profile.bio == "Nairobi. Mostly denim."
    assert profile.bio_state == "pending_review"
    assert domain.public_bio(profile) is None, "unscreened text must not be public"

    await domain.apply_bio_verdict(db, user_id=owner, allowed=True, note="")
    approved = await domain.get(db, user_id=owner)
    assert domain.public_bio(approved) == "Nairobi. Mostly denim."

    # An edit keeps the old approved text showing rather than blanking.
    await domain.set_bio(db, user_id=owner, bio="Call me on 0712345678")
    mid = await domain.get(db, user_id=owner)
    assert domain.public_bio(mid) == "Nairobi. Mostly denim."

    await domain.apply_bio_verdict(
        db, user_id=owner, allowed=False, note="Contains contact details."
    )
    held = await domain.get(db, user_id=owner)
    assert held.bio_state == "held"
    assert held.bio_note == "Contains contact details."
    assert domain.public_bio(held) == "Nairobi. Mostly denim.", (
        "a refused edit must not replace what was already approved"
    )

    # Clearing needs no screen: an empty bio cannot say anything.
    cleared = await domain.set_bio(db, user_id=owner, bio="")
    assert cleared.bio_state == "published"
    assert domain.public_bio(cleared) is None


async def test_a_blocked_persons_profile_is_not_readable(
    client, auth, db: AsyncSession
) -> None:
    """The leak this endpoint shipped with.

    Every other surface applies `hidden_either_way`; this one was
    written without it, so blocking somebody still left their handle,
    bio and links readable by name — in both directions.
    """
    reader_headers = auth(sub="kc-profile-reader")
    (await client.post("/v1/auth/session", headers=reader_headers)).json()[
        "user_id"
    ]
    author_headers = auth(sub="kc-profile-author")
    author_id = (await client.post("/v1/auth/session", headers=author_headers)).json()[
        "user_id"
    ]

    await client.patch(
        "/v1/profiles/me",
        headers=author_headers,
        json={"handle": "blockedperson", "bio": "Hello."},
    )
    assert (
        await client.get("/v1/profiles/blockedperson", headers=reader_headers)
    ).status_code == 200

    await client.put(f"/v1/community/blocks/{author_id}", headers=reader_headers)
    after = await client.get("/v1/profiles/blockedperson", headers=reader_headers)
    assert after.status_code == 404, "a blocked person's profile must not be readable"
    assert after.json()["code"] == "not_found"


async def test_a_block_hides_the_blocker_too(client, auth, db: AsyncSession) -> None:
    """Both directions, like every other visibility rule here."""
    one = auth(sub="kc-profile-one")
    one_id = (await client.post("/v1/auth/session", headers=one)).json()["user_id"]
    two = auth(sub="kc-profile-two")
    await client.post("/v1/auth/session", headers=two)

    await client.patch(
        "/v1/profiles/me", headers=one, json={"handle": "theblocker"}
    )
    # Two blocks one; one must also stop seeing two, and two must stop
    # seeing one.
    await client.put(f"/v1/community/blocks/{one_id}", headers=two)
    assert (
        await client.get("/v1/profiles/theblocker", headers=two)
    ).status_code == 404


async def test_a_deleted_accounts_profile_is_gone(
    client, auth, db: AsyncSession
) -> None:
    reader = auth(sub="kc-profile-r2")
    await client.post("/v1/auth/session", headers=reader)
    leaver = auth(sub="kc-profile-leaver")
    leaver_id = (await client.post("/v1/auth/session", headers=leaver)).json()[
        "user_id"
    ]
    await client.patch("/v1/profiles/me", headers=leaver, json={"handle": "goneaway"})
    assert (
        await client.get("/v1/profiles/goneaway", headers=reader)
    ).status_code == 200

    user = await db.get(User, __import__("uuid").UUID(leaver_id))
    user.deleted_at = sa.func.now()
    await db.commit()

    assert (
        await client.get("/v1/profiles/goneaway", headers=reader)
    ).status_code == 404


async def _run_bio_job(engine, user_id, screener):
    """Run the queued screen the way the worker would."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.workers.screen import screen_bio

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        return await screen_bio(session, user_id=user_id, screener=screener)


class _Screener:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.seen: list[str] = []

    async def screen_text(
        self, text: str, *, user_id, surface: str = "post"
    ) -> tuple[bool, str]:
        # Recorded so a test can assert a bio is screened as a bio
        # rather than as a caption.
        self.surface = surface
        self.seen.append(text)
        return self.ok, "" if self.ok else "Contains contact details."

    async def screen_image(self, data, content_type, *, user_id):
        return True, ""


async def test_writing_a_bio_queues_the_screen_that_publishes_it(
    engine, db: AsyncSession
) -> None:
    """The hole this covers was worse than a missing feature.

    `set_bio` moved a bio to `pending_review` and nothing moved it out,
    so the write looked like it worked and the result never arrived.
    """
    import sqlalchemy as sa

    from app.models.job import Job
    from app.workers.screen import BIO_SCREEN_JOB_KIND

    owner = await make_user(db)
    await domain.set_bio(db, user_id=owner, bio="Nairobi. Mostly denim.")

    queued = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Job)
        .where(Job.kind == BIO_SCREEN_JOB_KIND)
    )
    assert queued == 1, "a bio in review with no job is a bio nobody will ever see"

    screener = _Screener()
    assert (await _run_bio_job(engine, owner, screener))["outcome"] == "published"
    assert screener.seen == ["Nairobi. Mostly denim."]

    after = await domain.get(db, user_id=owner)
    await db.refresh(after)
    assert after.bio_state == "published"
    assert domain.public_bio(after) == "Nairobi. Mostly denim."


async def test_a_refused_bio_is_held_with_its_reason(engine, db: AsyncSession) -> None:
    owner = await make_user(db)
    await domain.set_bio(db, user_id=owner, bio="Call me on 0712345678")
    assert (await _run_bio_job(engine, owner, _Screener(ok=False)))["outcome"] == "held"

    held = await domain.get(db, user_id=owner)
    await db.refresh(held)
    assert held.bio_state == "held"
    assert held.bio_note == "Contains contact details."
    assert domain.public_bio(held) is None


async def test_an_unavailable_screen_holds_rather_than_publishes(
    engine, db: AsyncSession
) -> None:
    """An absent gate is not consent, same as the post path."""
    owner = await make_user(db)
    await domain.set_bio(db, user_id=owner, bio="Anything at all.")
    assert (await _run_bio_job(engine, owner, None))["outcome"] == "held"

    held = await domain.get(db, user_id=owner)
    await db.refresh(held)
    assert held.bio_state == "held"
    assert domain.public_bio(held) is None


async def test_editing_twice_screens_only_the_latest(engine, db: AsyncSession) -> None:
    owner = await make_user(db)
    await domain.set_bio(db, user_id=owner, bio="First draft.")
    await domain.set_bio(db, user_id=owner, bio="Second draft.")

    screener = _Screener()
    await _run_bio_job(engine, owner, screener)
    assert screener.seen == ["Second draft."], "the later edit is the one that counts"

    after = await domain.get(db, user_id=owner)
    await db.refresh(after)
    assert domain.public_bio(after) == "Second draft."

    # A second run finds nothing in review and does not pay for a call.
    assert (await _run_bio_job(engine, owner, screener))["outcome"] == "gone"
    assert len(screener.seen) == 1


def test_a_website_link_is_built_not_stored() -> None:
    """The Visit button on a fit can only go where the field says.

    The stored value is a bare host - `clean_links` refuses anything
    with a slash or a colon in it - and this is the only thing that
    turns one into a URL. A profile field holding a raw URL would be an
    open redirect wearing a profile field.
    """
    from app.routers.feed import _website

    class _Profile:
        links = {"website": "lewis.studio"}

    assert _website(_Profile()) == "https://lewis.studio"
    # Nothing set is nothing offered, rather than a dead button.
    class _Bare:
        links = {}

    assert _website(_Bare()) is None
    assert _website(None) is None
