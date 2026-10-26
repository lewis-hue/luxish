"""Authentication domain rules.

The one rule worth stating twice: **a token's email never adopts an existing
account.** Keycloak's first-broker-login flow can auto-link a brokered Google
account to a local account that shares an email address; if we mirrored that, a
Google account with an unverified address would be a login to someone else's
wardrobe. So:

* ``(provider, subject)`` is the only key that resolves to a user.
* An email collision with a live account produces 409 ``identity_link_required``
  and a challenge row — never a silent merge, not even for a verified email.
* The challenge is confirmable only by someone already authenticated as the
  owner of that account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, Conflict, NotFound, Unauthenticated
from app.models.identity import ExternalIdentity, IdentityLinkChallenge
from app.models.session import RevokedToken, Session
from app.models.user import User
from app.security.keycloak import LogoutClaims, TokenClaims

KEYCLOAK_PROVIDER = "keycloak"


class IdentityLinkRequired(Conflict):
    """The identity matches an existing account; the owner must confirm."""

    code = "identity_link_required"
    default_message = (
        "This identity's email matches an existing account. "
        "Sign in to that account and confirm the link."
    )


@dataclass(slots=True)
class AuthContext:
    """Everything a request handler should need about the caller."""

    user: User
    claims: TokenClaims
    session: Session | None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


def _now() -> datetime:
    return datetime.now(UTC)


async def authenticate(
    db: AsyncSession,
    claims: TokenClaims,
    *,
    session_ttl_days: int = 30,
    link_challenge_ttl_minutes: int = 15,
    user_agent: str | None = None,
    provision: bool = True,
) -> AuthContext:
    """Resolve verified claims to a local user, provisioning on first sight."""
    await _assert_not_revoked(db, claims)

    identity = await db.scalar(
        sa.select(ExternalIdentity).where(
            ExternalIdentity.provider == KEYCLOAK_PROVIDER,
            ExternalIdentity.subject == claims.subject,
        )
    )

    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None or user.is_deleted:
            raise Unauthenticated("This account has been deleted.")
        identity.last_seen_at = _now()
        _refresh_email(user, claims)
    else:
        if not provision:
            raise Unauthenticated("Unknown identity.")
        user = await _provision(db, claims, link_challenge_ttl_minutes)

    session = await _touch_session(db, user, claims, session_ttl_days, user_agent)
    await db.commit()
    return AuthContext(user=user, claims=claims, session=session)


async def _provision(
    db: AsyncSession, claims: TokenClaims, link_challenge_ttl_minutes: int
) -> User:
    """First sight of a ``sub``: create a user, or refuse to merge."""
    if claims.email:
        existing = await db.scalar(
            sa.select(User).where(
                sa.func.lower(User.email) == claims.email,
                User.deleted_at.is_(None),
            )
        )
        if existing is not None:
            # Both branches refuse. An unverified email is not evidence of
            # anything; a verified one is evidence of the address, not consent
            # to merge accounts. The only difference is whether a challenge is
            # offered at all.
            challenge = IdentityLinkChallenge(
                provider=KEYCLOAK_PROVIDER,
                subject=claims.subject,
                user_id=existing.id,
                claimed_email=claims.email,
                claimed_email_verified=claims.email_verified,
                expires_at=_now() + timedelta(minutes=link_challenge_ttl_minutes),
            )
            db.add(challenge)
            await db.commit()
            raise IdentityLinkRequired(
                detail={
                    "link_challenge_id": str(challenge.id),
                    "email_verified": claims.email_verified,
                }
            )

    user = User(
        email=claims.email,
        email_verified=claims.email_verified and claims.email is not None,
    )
    db.add(user)
    await db.flush()
    db.add(
        ExternalIdentity(
            provider=KEYCLOAK_PROVIDER,
            subject=claims.subject,
            user_id=user.id,
            email_at_link=claims.email,
            email_verified_at_link=claims.email_verified,
            linked_by_confirmation=False,
            last_seen_at=_now(),
        )
    )
    await db.flush()
    return user


def _refresh_email(user: User, claims: TokenClaims) -> None:
    """Email is mutable at the IdP; mirror it, never key on it."""
    if claims.email and claims.email != (user.email or "").lower():
        user.email = claims.email
        user.email_verified = claims.email_verified
    elif claims.email and claims.email_verified and not user.email_verified:
        user.email_verified = True


async def confirm_identity_link(
    db: AsyncSession, *, actor: AuthContext, challenge_id: uuid.UUID
) -> ExternalIdentity:
    """Attach a pending identity to the authenticated owner's account.

    A challenge belonging to another user is reported as 404: the caller has no
    business learning that it exists.
    """
    challenge = await db.get(IdentityLinkChallenge, challenge_id)
    if (
        challenge is None
        or challenge.user_id != actor.user_id
        or challenge.consumed_at is not None
        or challenge.expires_at <= _now()
    ):
        raise NotFound("No such link challenge.")

    existing = await db.scalar(
        sa.select(ExternalIdentity).where(
            ExternalIdentity.provider == challenge.provider,
            ExternalIdentity.subject == challenge.subject,
        )
    )
    if existing is not None:
        challenge.consumed_at = _now()
        await db.commit()
        if existing.user_id != actor.user_id:
            raise Conflict("That identity is already linked elsewhere.")
        return existing

    identity = ExternalIdentity(
        provider=challenge.provider,
        subject=challenge.subject,
        user_id=actor.user_id,
        email_at_link=challenge.claimed_email,
        email_verified_at_link=challenge.claimed_email_verified,
        linked_by_confirmation=True,
    )
    db.add(identity)
    challenge.consumed_at = _now()
    await db.commit()
    return identity


# --------------------------------------------------------------------------- #
# revocation
# --------------------------------------------------------------------------- #
async def _assert_not_revoked(db: AsyncSession, claims: TokenClaims) -> None:
    if claims.jti:
        revoked = await db.get(RevokedToken, claims.jti)
        if revoked is not None:
            raise Unauthenticated("This token has been revoked.")
    if claims.sid:
        session = await db.scalar(
            sa.select(Session).where(
                Session.keycloak_sid == claims.sid, Session.revoked_at.is_not(None)
            )
        )
        if session is not None:
            raise Unauthenticated("This session has been signed out.")


async def _touch_session(
    db: AsyncSession,
    user: User,
    claims: TokenClaims,
    session_ttl_days: int,
    user_agent: str | None,
) -> Session | None:
    if not claims.sid:
        return None
    session = await db.scalar(sa.select(Session).where(Session.keycloak_sid == claims.sid))
    if session is None:
        session = Session(
            user_id=user.id,
            keycloak_sid=claims.sid,
            user_agent=(user_agent or None),
            expires_at=_now() + timedelta(days=session_ttl_days),
        )
        db.add(session)
    session.last_seen_at = _now()
    await db.flush()
    return session


async def revoke_current_session(db: AsyncSession, ctx: AuthContext) -> None:
    """Sign out this device: deny the presented ``jti`` and the ``sid``."""
    now = _now()
    if ctx.claims.jti:
        await record_revoked_token(
            db, jti=ctx.claims.jti, user_id=ctx.user_id, expires_at=ctx.claims.expires_at
        )
    if ctx.session is not None and ctx.session.revoked_at is None:
        ctx.session.revoked_at = now
    await db.commit()


async def revoke_session_by_sid(db: AsyncSession, sid: str, *, reason: str) -> int:
    """Revoke a session the IdP told us about. Idempotent; returns rows hit."""
    result = await db.execute(
        sa.update(Session)
        .where(Session.keycloak_sid == sid, Session.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
    return int(result.rowcount or 0)


async def apply_backchannel_logout(db: AsyncSession, claims: LogoutClaims) -> int:
    if claims.sid:
        return await revoke_session_by_sid(db, claims.sid, reason="backchannel_logout")
    if claims.subject:
        identity = await db.scalar(
            sa.select(ExternalIdentity).where(
                ExternalIdentity.provider == KEYCLOAK_PROVIDER,
                ExternalIdentity.subject == claims.subject,
            )
        )
        if identity is not None:
            return await _revoke_all_sessions(db, identity.user_id, commit=True)
    return 0


async def _revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID, *, commit: bool) -> int:
    result = await db.execute(
        sa.update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    if commit:
        await db.commit()
    return int(result.rowcount or 0)


async def record_revoked_token(
    db: AsyncSession,
    *,
    jti: str,
    user_id: uuid.UUID | None,
    expires_at: datetime,
    reason: str = "session_revoked",
) -> None:
    existing = await db.get(RevokedToken, jti)
    if existing is not None:
        return
    db.add(
        RevokedToken(
            jti=jti,
            user_id=user_id,
            revoked_at=_now(),
            expires_at=expires_at,
            reason=reason,
        )
    )
    await db.flush()


# --------------------------------------------------------------------------- #
# account deletion
# --------------------------------------------------------------------------- #
async def delete_account(db: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Soft-delete the account and revoke every session. Idempotent.

    Media deletion is Task 6's tombstone path; this marks the account and shuts
    the door. Calling it twice is not an error — a client retrying a delete must
    not see a failure.
    """
    user = await db.get(User, user_id)
    if user is None:
        return
    now = _now()
    if user.deleted_at is None:
        user.deleted_at = now
        # Release the email address for a future signup without storing it in a
        # live, searchable form.
        user.email = None
        user.email_verified = False
    await _revoke_all_sessions(db, user_id, commit=False)
    await db.flush()


__all__ = [
    "AuthContext",
    "IdentityLinkRequired",
    "KEYCLOAK_PROVIDER",
    "ApiError",
    "apply_backchannel_logout",
    "record_revoked_token",
    "authenticate",
    "confirm_identity_link",
    "delete_account",
    "revoke_current_session",
    "revoke_session_by_sid",
]
