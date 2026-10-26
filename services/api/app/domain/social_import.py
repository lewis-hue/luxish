"""Social link import (ADR-009).

A pasted link is stored as a reference with attribution. We render the
platform's official embed where its terms allow, and we do **not** download,
store, or analyse platform-hosted media. Garment analysis runs on media the
user supplies.

Each platform is a *declarative capability record* — six independent booleans.
Nothing in this module fetches anything: the module never imports the fetcher,
which is the cheapest way to keep that true. The URL is still validated against
the same scheme and address rules so a pasted ``http://169.254.169.254/`` is
refused rather than stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, NotFound
from app.models.external_reference import SOCIAL_PLATFORMS, ExternalReference
from app.security.urlfetch import ALLOWED_SCHEMES, UnsafeUrl, assert_public_ip

#: The alternative we offer whenever analysis is not available.
USER_SUPPLIED_MEDIA = "user_supplied_media"

#: Query parameters that carry no meaning for the reference itself.
TRACKING_PARAMS = frozenset(
    {
        "igshid",
        "igsh",
        "hl",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "ref",
        "ref_src",
        "share_id",
        "si",
        "feature",
        "is_from_webapp",
        "sender_device",
        "_r",
        "_t",
    }
)


class InvalidReferenceUrl(ApiError):
    status_code = 400
    code = "invalid_reference_url"
    default_message = "That link cannot be stored as a reference."


class PlatformCapability(BaseModel):
    """What we can honestly do with a link to this platform.

    Six independent booleans — not a tier, not a score. The UI states the
    limitation and offers the working alternative (ADR-009).
    """

    model_config = ConfigDict(frozen=True)

    #: Render the platform's official embed.
    can_embed: bool
    #: Read what the URL itself carries (handle, post id).
    can_read_metadata: bool
    #: Fetch the media bytes behind the link. Always false.
    can_access_media: bool
    #: Run perception over that media. Always false.
    can_analyse: bool
    #: Store the media. Always false; the reference is stored, the media is not.
    can_store: bool
    #: Whether the above holds under our current authorisation.
    authorised_now: bool


#: A public URL conveys no permission to fetch or analyse the media behind it
#: (brief §11), so `can_access_media`, `can_analyse` and `can_store` are false
#: everywhere. They exist as separate fields because they are separate
#: questions, and because an authorised integration could change one of them.
CAPABILITIES: dict[str, PlatformCapability] = {
    "instagram": PlatformCapability(
        can_embed=True,
        can_read_metadata=True,
        can_access_media=False,
        can_analyse=False,
        can_store=False,
        authorised_now=True,
    ),
    "tiktok": PlatformCapability(
        can_embed=True,
        can_read_metadata=True,
        can_access_media=False,
        can_analyse=False,
        can_store=False,
        authorised_now=True,
    ),
    "pinterest": PlatformCapability(
        can_embed=True,
        can_read_metadata=True,
        can_access_media=False,
        can_analyse=False,
        can_store=False,
        authorised_now=True,
    ),
    "youtube": PlatformCapability(
        can_embed=True,
        can_read_metadata=True,
        can_access_media=False,
        can_analyse=False,
        can_store=False,
        authorised_now=True,
    ),
    "other": PlatformCapability(
        can_embed=False,
        can_read_metadata=True,
        can_access_media=False,
        can_analyse=False,
        can_store=False,
        authorised_now=True,
    ),
}

_HOST_PLATFORMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("instagram.com", "instagr.am"), "instagram"),
    (("tiktok.com",), "tiktok"),
    (("pinterest.com", "pinterest.co.uk", "pin.it"), "pinterest"),
    (("youtube.com", "youtu.be"), "youtube"),
)


def _host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def classify_platform(url: str) -> str:
    host = _host_of(url)
    for suffixes, platform in _HOST_PLATFORMS:
        for suffix in suffixes:
            if host == suffix or host.endswith("." + suffix):
                return platform
    return "other"


def canonicalise(url: str) -> str:
    """Drop tracking parameters and fragments; keep everything meaningful."""
    parts = urlsplit(url.strip())
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and pair.split("=", 1)[0].lower() not in TRACKING_PARAMS
    ]
    host = (parts.hostname or "").lower()
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, "&".join(kept), ""))


def extract_author_handle(url: str) -> str | None:
    """Only what the URL itself carries — no lookup, no fetch."""
    platform = classify_platform(url)
    segments = [segment for segment in urlsplit(url).path.split("/") if segment]
    if platform == "tiktok":
        for segment in segments:
            if segment.startswith("@"):
                return segment[1:] or None
        return None
    if platform == "instagram":
        if segments and segments[0] not in {"p", "reel", "reels", "tv", "stories"}:
            return segments[0]
        return None
    return None


def validate_reference_url(url: str) -> str:
    """Scheme and address checks, without connecting to anything.

    The same rules the fetcher applies, so a reference can never be a stored
    pointer at the cloud metadata service.
    """
    raw = (url or "").strip()
    if not raw:
        raise InvalidReferenceUrl("A URL is required.")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise InvalidReferenceUrl(f"Scheme {parts.scheme!r} is not supported.")
    if parts.username or parts.password:
        raise InvalidReferenceUrl("A URL with credentials cannot be stored.")
    host = (parts.hostname or "").strip()
    if not host:
        raise InvalidReferenceUrl("That URL has no host.")
    if _is_ip_literal(host):
        # A link to a bare address is never a social reference, and may be an
        # attempt to store a pointer at an internal service.
        try:
            assert_public_ip(host)
        except UnsafeUrl as exc:
            raise InvalidReferenceUrl("That address cannot be referenced.") from exc
    return canonicalise(raw)


def _is_ip_literal(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def store_reference(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    url: str,
    note: str | None = None,
) -> tuple[ExternalReference, PlatformCapability, str | None]:
    """Store (or return) the reference for this user and link.

    Returns the reference, the capability record in force, and the alternative
    to offer when analysis is unavailable.
    """
    canonical = validate_reference_url(url)
    platform = classify_platform(canonical)
    if platform not in SOCIAL_PLATFORMS:  # pragma: no cover - classification is closed
        platform = "other"
    capability = CAPABILITIES[platform]

    existing = await session.scalar(
        sa.select(ExternalReference).where(
            ExternalReference.user_id == user_id,
            ExternalReference.canonical_url == canonical,
            ExternalReference.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing, capability, alternative_for(capability)

    reference = ExternalReference(
        user_id=user_id,
        platform=platform,
        canonical_url=canonical,
        submitted_url=url.strip()[:2048],
        author_handle=extract_author_handle(canonical),
        note=note,
        observed_at=datetime.now(UTC),
        capability_snapshot=capability.model_dump(),
        media_downloaded=False,
    )
    session.add(reference)
    await session.commit()
    await session.refresh(reference)
    return reference, capability, alternative_for(capability)


def alternative_for(capability: PlatformCapability) -> str | None:
    """What the user can do instead when we cannot analyse the link."""
    return None if capability.can_analyse else USER_SUPPLIED_MEDIA


async def get_reference(
    session: AsyncSession, *, user_id: uuid.UUID, reference_id: uuid.UUID
) -> ExternalReference:
    reference = await session.scalar(
        sa.select(ExternalReference).where(
            ExternalReference.id == reference_id,
            ExternalReference.user_id == user_id,
            ExternalReference.deleted_at.is_(None),
        )
    )
    if reference is None:
        raise NotFound("No such reference.")
    return reference


__all__ = [
    "CAPABILITIES",
    "USER_SUPPLIED_MEDIA",
    "InvalidReferenceUrl",
    "PlatformCapability",
    "alternative_for",
    "canonicalise",
    "classify_platform",
    "extract_author_handle",
    "get_reference",
    "store_reference",
    "validate_reference_url",
]
