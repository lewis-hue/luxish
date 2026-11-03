"""Public identity: claiming a handle, writing a bio, linking off the app.

**The bio is screened before strangers read it.** Same doctrine as a
post caption, and for the same reason: it is free text going in front of
people who did not choose to receive it. The owner always sees what they
typed; everyone else sees `bio_public`, which only moves when the screen
approves. A screen that is unavailable holds, never publishes.

**A link is a platform and a handle, never a URL.** Somebody who can
paste a URL into their profile can paste any URL, which is an open
redirect wearing a profile field. The address is built from a table at
render time, so a link can only point where it says it does.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import (
    HANDLE_PATTERN,
    MAX_BIO,
    SOCIAL_PLATFORMS,
    Profile,
)


class BadHandle(Exception):
    """Wrong shape. The message names the rule."""


class HandleTaken(Exception):
    """Somebody already has it."""


class BadLink(Exception):
    """A platform we do not build addresses for, or a malformed handle."""


#: Reserved so a profile cannot impersonate a route or a role.
RESERVED_HANDLES: frozenset[str] = frozenset(
    {
        "admin", "support", "help", "about", "settings", "search", "explore",
        "discover", "stylist", "wardrobe", "community", "profile", "shop",
        "official", "staff", "team", "moderator", "mod", "system", "root",
    }
)


def clean_handle(raw: str) -> str:
    cleaned = raw.strip().lstrip("@").lower()
    if not HANDLE_PATTERN.match(cleaned):
        raise BadHandle(
            "A handle is 3 to 30 characters: letters, digits, dots and underscores."
        )
    if cleaned in RESERVED_HANDLES:
        raise BadHandle("That handle is reserved.")
    return cleaned


def clean_links(raw: dict[str, str]) -> dict[str, str]:
    """Keep the platforms we can build an address for, drop the rest."""
    out: dict[str, str] = {}
    for platform, handle in (raw or {}).items():
        key = str(platform).strip().lower()
        if key not in SOCIAL_PLATFORMS:
            raise BadLink(
                f"Links can point at: {', '.join(sorted(SOCIAL_PLATFORMS))}."
            )
        value = str(handle).strip().lstrip("@")
        if not value:
            continue
        if len(value) > 64 or any(c in value for c in "/?#&: "):
            raise BadLink(f"That does not look like a {key} handle.")
        out[key] = value
    return out


def address_for(platform: str, handle: str) -> str | None:
    """The URL for a stored link. Built here, never stored."""
    template = SOCIAL_PLATFORMS.get(platform)
    return template.format(handle=handle) if template else None


async def get(db: AsyncSession, *, user_id: uuid.UUID) -> Profile | None:
    return await db.scalar(
        sa.select(Profile).where(
            Profile.user_id == user_id, Profile.deleted_at.is_(None)
        )
    )


async def ensure(db: AsyncSession, *, user_id: uuid.UUID) -> Profile:
    """The row, made on first use. Nothing is set until somebody sets it."""
    found = await get(db, user_id=user_id)
    if found is not None:
        return found
    profile = Profile(user_id=user_id, links={})
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def by_handle(db: AsyncSession, *, handle: str) -> Profile | None:
    return await db.scalar(
        sa.select(Profile).where(
            Profile.handle == handle.strip().lstrip("@").lower(),
            Profile.deleted_at.is_(None),
        )
    )


async def set_handle(
    db: AsyncSession, *, user_id: uuid.UUID, handle: str
) -> Profile:
    cleaned = clean_handle(handle)
    profile = await ensure(db, user_id=user_id)
    if profile.handle == cleaned:
        return profile
    clash = await db.scalar(
        sa.select(Profile.id).where(
            Profile.handle == cleaned,
            Profile.user_id != user_id,
            Profile.deleted_at.is_(None),
        )
    )
    if clash is not None:
        raise HandleTaken()
    profile.handle = cleaned
    await db.commit()
    await db.refresh(profile)
    return profile


async def set_links(
    db: AsyncSession, *, user_id: uuid.UUID, links: dict[str, str]
) -> Profile:
    cleaned = clean_links(links)
    profile = await ensure(db, user_id=user_id)
    profile.links = cleaned
    await db.commit()
    await db.refresh(profile)
    return profile


async def set_private(
    db: AsyncSession, *, user_id: uuid.UUID, private: bool
) -> Profile:
    """Make an account private, or public again.

    Nothing is deleted and nothing is unpublished. A fit stays where it
    was; what changes is who the reads return it to. Going public again
    is therefore immediate and needs no screen - the screen already
    passed everything the first time.
    """
    profile = await ensure(db, user_id=user_id)
    profile.private = bool(private)
    await db.commit()
    await db.refresh(profile)
    return profile


async def is_private(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """Whether this account keeps its fits and its lists to itself."""
    found = await db.scalar(
        sa.select(Profile.private).where(
            Profile.user_id == user_id, Profile.deleted_at.is_(None)
        )
    )
    return bool(found)


async def set_bio(
    db: AsyncSession, *, user_id: uuid.UUID, bio: str | None
) -> Profile:
    """Write a bio. It is held until the screen agrees.

    Clearing it is immediate and needs no screen: an empty bio cannot
    say anything objectionable, and making somebody wait to *remove*
    something would be the wrong way round.
    """
    profile = await ensure(db, user_id=user_id)
    text = (bio or "").strip()[:MAX_BIO]

    if not text:
        profile.bio = None
        profile.bio_public = None
        profile.bio_state = "published"
        profile.bio_note = None
        await db.commit()
        await db.refresh(profile)
        return profile

    if text == profile.bio and profile.bio_state == "published":
        return profile

    profile.bio = text
    profile.bio_state = "pending_review"
    profile.bio_note = None
    # `bio_public` is deliberately left alone: the previously approved
    # text keeps showing while the new one is checked, rather than the
    # profile going blank for the length of a round trip.

    # The job rides the same commit. Without it a bio sits in review for
    # ever: the write looks like it worked and the result never comes.
    # Keyed on the person rather than the text, so editing twice before
    # the first run is screened once, on the latest version.
    from app.domain.jobs import enqueue
    from app.workers.screen import BIO_SCREEN_JOB_KIND

    await enqueue(
        db,
        BIO_SCREEN_JOB_KIND,
        {"user_id": str(user_id)},
        idempotency_key=f"{BIO_SCREEN_JOB_KIND}:{user_id}:{hash(text) & 0xFFFFFFFF}",
    )
    await db.commit()
    await db.refresh(profile)
    return profile


async def apply_bio_verdict(
    db: AsyncSession, *, user_id: uuid.UUID, allowed: bool, note: str
) -> Profile | None:
    """Record what the screen decided."""
    profile = await get(db, user_id=user_id)
    if profile is None or profile.bio_state != "pending_review":
        return profile
    if allowed:
        profile.bio_public = profile.bio
        profile.bio_state = "published"
        profile.bio_note = None
    else:
        profile.bio_state = "held"
        profile.bio_note = note[:300] or "Held for review."
    await db.commit()
    await db.refresh(profile)
    return profile


#: What a banner may be, and what it may not.
BANNER_MEDIA_KIND = "profile_banner"


class BadBanner(Exception):
    """Not this person's picture, or not a banner."""


async def set_banner(
    db: AsyncSession, *, user_id: uuid.UUID, asset_id: uuid.UUID | None
) -> Profile:
    """Put a picture across the top of a profile, or take it down.

    **Held until the image screen agrees**, like a bio and for the same
    reason: it is shown to everybody who opens the page, so an
    unscreened one is unscreened content in front of strangers. The
    owner sees their choice immediately; a stranger sees it when the
    screen has passed it.

    Clearing is immediate and needs no screen. An absent picture cannot
    say anything objectionable, and making somebody wait to *remove*
    one would be the wrong way round.
    """
    from app.models.media_asset import MediaAsset

    profile = await ensure(db, user_id=user_id)

    if asset_id is None:
        profile.banner_asset_id = None
        profile.banner_state = "published"
        profile.banner_note = None
        await db.commit()
        await db.refresh(profile)
        return profile

    # Re-validated against this account and this kind. An asset id in a
    # request is a claim, and without the kind check any picture
    # somebody owns - a garment, a photograph of themselves - could be
    # published across the top of their page by naming its id.
    asset = await db.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.user_id == user_id,
            MediaAsset.kind == BANNER_MEDIA_KIND,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status.in_(("uploaded", "ready")),
        )
    )
    if asset is None or not asset.storage_key:
        raise BadBanner()

    if profile.banner_asset_id == asset.id and profile.banner_state == "published":
        return profile

    profile.banner_asset_id = asset.id
    profile.banner_state = "pending_review"
    profile.banner_note = None

    # Rides the same commit. Without it the banner sits in review for
    # ever: the write looks like it worked and the result never comes,
    # which is the exact hole a bio had before its job was wired.
    from app.domain.jobs import enqueue
    from app.workers.screen import BANNER_SCREEN_JOB_KIND

    await enqueue(
        db,
        BANNER_SCREEN_JOB_KIND,
        {"user_id": str(user_id)},
        idempotency_key=f"{BANNER_SCREEN_JOB_KIND}:{user_id}:{asset.id}",
    )
    await db.commit()
    await db.refresh(profile)
    return profile


async def apply_banner_verdict(
    db: AsyncSession, *, user_id: uuid.UUID, allowed: bool, note: str
) -> Profile | None:
    """Record what the image screen decided."""
    profile = await get(db, user_id=user_id)
    if profile is None or profile.banner_state != "pending_review":
        return profile
    if allowed:
        profile.banner_state = "published"
        profile.banner_note = None
    else:
        profile.banner_state = "held"
        profile.banner_note = note[:300] or "Held for review."
    await db.commit()
    await db.refresh(profile)
    return profile


def public_banner(profile: Profile | None) -> uuid.UUID | None:
    """What a stranger sees across the top: the approved one, or none."""
    if profile is None or profile.banner_state != "published":
        return None
    return profile.banner_asset_id


def public_bio(profile: Profile | None) -> str | None:
    """What a stranger sees: the approved text, or nothing."""
    return profile.bio_public if profile is not None else None


__all__ = [
    "RESERVED_HANDLES",
    "BadHandle",
    "BadBanner",
    "BadLink",
    "HandleTaken",
    "address_for",
    "apply_bio_verdict",
    "by_handle",
    "clean_handle",
    "clean_links",
    "ensure",
    "get",
    "apply_banner_verdict",
    "public_banner",
    "public_bio",
    "set_banner",
    "set_bio",
    "set_handle",
    "set_links",
    "set_private",
    "is_private",
]
