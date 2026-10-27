"""Task 4 — Keycloak token verification, provisioning, and revocation.

This service never issues tokens. It verifies Keycloak-issued RS256/ES256 JWTs
against the realm JWKS, provisions a local user keyed on the immutable ``sub``,
and maintains its own revocation state because a JWT cannot be un-issued.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import ExternalIdentity
from app.models.session import RevokedToken, Session
from app.models.user import User
from app.security.keycloak import TokenRejected


async def make_user(db: AsyncSession, *, email: str, email_verified: bool = True) -> User:
    user = User(email=email, email_verified=email_verified)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def count_identities(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(ExternalIdentity).where(
                ExternalIdentity.user_id == user_id
            )
        )
    ) or 0


async def count_users(db: AsyncSession) -> int:
    return (await db.scalar(select(func.count()).select_from(User))) or 0


# --------------------------------------------------------------------------- #
# the load-bearing invariant: an unverified email never adopts an account
# --------------------------------------------------------------------------- #
async def test_unverified_email_does_not_merge_into_existing_account(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """A brokered identity with an unverified email must NOT adopt an existing
    user — that is the account-takeover path the brief forbids, and Keycloak's
    first-broker-login flow will attempt exactly this link by email."""
    existing = await make_user(db, email="a@example.com", email_verified=True)

    r = await client.post(
        "/v1/auth/session",
        headers=auth(sub="kc-sub-1", email="a@example.com", email_verified=False),
    )

    assert r.status_code == 409
    assert r.json()["code"] == "identity_link_required"
    assert await count_identities(db, existing.id) == 0


async def test_verified_email_still_requires_explicit_link_confirmation(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    """Even a verified email is not consent to merge; the owner must confirm."""
    existing = await make_user(db, email="b@example.com", email_verified=True)

    r = await client.post(
        "/v1/auth/session",
        headers=auth(sub="kc-sub-2", email="b@example.com", email_verified=True),
    )

    assert r.status_code == 409
    assert r.json()["code"] == "identity_link_required"
    assert r.json()["detail"]["link_challenge_id"]
    assert await count_identities(db, existing.id) == 0


async def test_owner_can_confirm_a_link_challenge(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any, tokens: Any
) -> None:
    # The existing account signs in with its own (already linked) identity.
    first = await client.post("/v1/auth/session", headers=auth(sub="kc-owner", email=None))
    assert first.status_code == 200
    owner_id = uuid.UUID(first.json()["user_id"])
    owner_headers = {"Authorization": f"Bearer {tokens.token(sub='kc-owner')}"}
    await db.execute(
        User.__table__.update().where(User.id == owner_id).values(
            email="c@example.com", email_verified=True
        )
    )
    await db.commit()

    challenge = await client.post(
        "/v1/auth/session",
        headers=auth(sub="kc-second-device", email="c@example.com", email_verified=True),
    )
    assert challenge.status_code == 409
    challenge_id = challenge.json()["detail"]["link_challenge_id"]

    confirmed = await client.post(
        "/v1/auth/identity/link",
        headers=owner_headers,
        json={"link_challenge_id": challenge_id},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert await count_identities(db, owner_id) == 2

    # The newly linked identity now resolves to the same user, not a new one.
    again = await client.post(
        "/v1/auth/session",
        headers=auth(sub="kc-second-device", email="c@example.com", email_verified=True),
    )
    assert again.status_code == 200
    assert again.json()["user_id"] == str(owner_id)


async def test_a_challenge_cannot_be_confirmed_by_a_stranger(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    await make_user(db, email="d@example.com", email_verified=True)
    challenge = await client.post(
        "/v1/auth/session",
        headers=auth(sub="kc-stranger-target", email="d@example.com", email_verified=True),
    )
    challenge_id = challenge.json()["detail"]["link_challenge_id"]

    stranger = await client.post("/v1/auth/session", headers=auth(sub="kc-stranger"))
    assert stranger.status_code == 200

    r = await client.post(
        "/v1/auth/identity/link",
        headers=auth(sub="kc-stranger"),
        json={"link_challenge_id": challenge_id},
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# provisioning
# --------------------------------------------------------------------------- #
async def test_valid_token_provisions_exactly_one_user(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    header = {"Authorization": f"Bearer {tokens.token(sub='kc-stable', email='e@example.com')}"}

    first = await client.post("/v1/auth/session", headers=header)
    second = await client.post("/v1/auth/session", headers=header)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["user_id"] == second.json()["user_id"]
    assert await count_users(db) == 1
    assert await count_identities(db, uuid.UUID(first.json()["user_id"])) == 1


async def test_second_sub_does_not_reuse_the_first_users_row(
    client: httpx.AsyncClient, db: AsyncSession, auth: Any
) -> None:
    a = await client.post("/v1/auth/session", headers=auth(sub="kc-a"))
    b = await client.post("/v1/auth/session", headers=auth(sub="kc-b"))
    assert a.json()["user_id"] != b.json()["user_id"]
    assert await count_users(db) == 2


async def test_identity_is_keyed_on_sub_not_on_mutable_email(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    first = await client.post(
        "/v1/auth/session",
        headers={"Authorization": f"Bearer {tokens.token(sub='kc-moves', email='old@x.test')}"},
    )
    second = await client.post(
        "/v1/auth/session",
        headers={"Authorization": f"Bearer {tokens.token(sub='kc-moves', email='new@x.test')}"},
    )
    assert first.json()["user_id"] == second.json()["user_id"]
    assert await count_users(db) == 1


async def test_me_returns_the_authenticated_user(client: httpx.AsyncClient, auth: Any) -> None:
    created = await client.post("/v1/auth/session", headers=auth(sub="kc-me"))
    me = await client.get("/v1/auth/me", headers=auth(sub="kc-me"))
    assert me.status_code == 200
    assert me.json()["user_id"] == created.json()["user_id"]


# --------------------------------------------------------------------------- #
# token verification failures — each is a 401, never a 500
# --------------------------------------------------------------------------- #
async def test_missing_authorization_is_401(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"


async def test_token_signed_by_the_wrong_key_is_rejected(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    bad = tokens.token(kid="attacker-key")
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


async def test_hs256_signed_with_the_public_key_is_rejected(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    """Algorithm confusion: the public key is not an HMAC secret."""
    forged = tokens.token(alg="HS256")
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_alg_none_is_rejected(client: httpx.AsyncClient, tokens: Any) -> None:
    r = await client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {tokens.token(alg='none')}"}
    )
    assert r.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://id.evil.test/realms/luxish"},
        {"aud": ["someone-else"]},  # wrong, as opposed to absent
        {"azp": "another-client"},
        {"exp": int((datetime.now(UTC) - timedelta(minutes=10)).timestamp())},
        {"nbf": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp())},
        {"sub": None},
    ],
)
async def test_bad_claims_are_rejected(
    client: httpx.AsyncClient, tokens: Any, overrides: dict[str, Any]
) -> None:
    token = tokens.token(**overrides)
    r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, overrides


async def test_verifier_rejects_hmac_before_touching_the_key(verifier: Any, tokens: Any) -> None:
    with pytest.raises(TokenRejected) as exc:
        await verifier.verify(tokens.token(alg="HS256"))
    assert exc.value.reason == "algorithm_not_allowed"


async def test_jwks_is_cached_between_verifications(verifier: Any, tokens: Any) -> None:
    await verifier.verify(tokens.token(sub="kc-cache-1"))
    await verifier.verify(tokens.token(sub="kc-cache-2"))
    assert len(verifier.test_fetch_calls) == 1


# --------------------------------------------------------------------------- #
# revocation — a JWT cannot be un-issued, so we keep our own denial state
# --------------------------------------------------------------------------- #
async def test_delete_session_revokes_the_presented_token_immediately(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    token = tokens.token(sub="kc-revoke", jti="jti-revoke-1", sid="sid-revoke-1")
    header = {"Authorization": f"Bearer {token}"}

    assert (await client.post("/v1/auth/session", headers=header)).status_code == 200
    assert (await client.delete("/v1/auth/session", headers=header)).status_code == 204

    after = await client.get("/v1/auth/me", headers=header)
    assert after.status_code == 401
    assert after.json()["code"] == "unauthenticated"

    revoked = await db.scalar(select(RevokedToken).where(RevokedToken.jti == "jti-revoke-1"))
    assert revoked is not None
    assert revoked.expires_at > datetime.now(UTC)


async def test_delete_session_is_idempotent(client: httpx.AsyncClient, tokens: Any) -> None:
    header = {"Authorization": f"Bearer {tokens.token(sub='kc-idem', jti='jti-idem', sid='sid-idem')}"}
    await client.post("/v1/auth/session", headers=header)
    first = await client.delete("/v1/auth/session", headers=header)
    second = await client.delete("/v1/auth/session", headers=header)
    assert first.status_code == 204
    assert second.status_code in (204, 401)


async def test_revoking_one_sid_does_not_revoke_another_device(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    phone = {"Authorization": f"Bearer {tokens.token(sub='kc-two', jti='j1', sid='s1')}"}
    tablet = {"Authorization": f"Bearer {tokens.token(sub='kc-two', jti='j2', sid='s2')}"}
    await client.post("/v1/auth/session", headers=phone)
    await client.post("/v1/auth/session", headers=tablet)

    await client.delete("/v1/auth/session", headers=phone)

    assert (await client.get("/v1/auth/me", headers=phone)).status_code == 401
    assert (await client.get("/v1/auth/me", headers=tablet)).status_code == 200


async def test_backchannel_logout_revokes_the_session_id(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    header = {"Authorization": f"Bearer {tokens.token(sub='kc-bcl', jti='j-bcl', sid='sid-bcl')}"}
    assert (await client.post("/v1/auth/session", headers=header)).status_code == 200

    logout = await client.post(
        "/v1/auth/backchannel-logout",
        content=tokens.logout_token(sid="sid-bcl", sub="kc-bcl"),
        headers={"Content-Type": "application/jwt"},
    )
    assert logout.status_code == 204, logout.text

    assert (await client.get("/v1/auth/me", headers=header)).status_code == 401
    session = await db.scalar(select(Session).where(Session.keycloak_sid == "sid-bcl"))
    assert session is not None and session.revoked_at is not None


async def test_backchannel_logout_requires_the_logout_event_claim(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    not_a_logout_token = tokens.logout_token(sid="sid-x", events=None)
    r = await client.post(
        "/v1/auth/backchannel-logout",
        content=not_a_logout_token,
        headers={"Content-Type": "application/jwt"},
    )
    assert r.status_code == 401


async def test_backchannel_logout_rejects_an_unsigned_token(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/v1/auth/backchannel-logout",
        content="not.a.jwt",
        headers={"Content-Type": "application/jwt"},
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# account deletion
# --------------------------------------------------------------------------- #
async def test_account_deletion_revokes_sessions_and_is_idempotent(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    from app.domain.auth import delete_account

    header = {"Authorization": f"Bearer {tokens.token(sub='kc-del', jti='j-del', sid='sid-del')}"}
    created = await client.post("/v1/auth/session", headers=header)
    user_id = uuid.UUID(created.json()["user_id"])

    assert (await client.delete("/v1/account", headers=header)).status_code == 204

    user = await db.get(User, user_id)
    await db.refresh(user)
    assert user.deleted_at is not None
    sessions = (await db.scalars(select(Session).where(Session.user_id == user_id))).all()
    assert sessions and all(s.revoked_at is not None for s in sessions)

    # Idempotent at the domain level: deleting twice is not an error.
    await delete_account(db, user_id=user_id)
    await delete_account(db, user_id=user_id)
    await db.commit()
    assert (await db.get(User, user_id)).deleted_at is not None

    # And the token no longer authenticates anything.
    assert (await client.get("/v1/auth/me", headers=header)).status_code == 401


async def test_deleted_account_does_not_reanimate_on_the_next_token(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    header = {"Authorization": f"Bearer {tokens.token(sub='kc-gone', jti='j-gone', sid='s-gone')}"}
    await client.post("/v1/auth/session", headers=header)
    await client.delete("/v1/account", headers=header)

    fresh = {"Authorization": f"Bearer {tokens.token(sub='kc-gone', jti='j-new', sid='s-new')}"}
    r = await client.get("/v1/auth/me", headers=fresh)
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"


# --------------------------------------------------------------------------- #
# schema invariants
# --------------------------------------------------------------------------- #
def test_provider_subject_is_unique() -> None:
    constraints = {
        tuple(sorted(c.columns.keys()))
        for c in ExternalIdentity.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    } | {
        tuple(sorted(i.columns.keys())) for i in ExternalIdentity.__table__.indexes if i.unique
    }
    assert ("provider", "subject") in constraints


def test_no_bearer_material_is_stored_in_the_sessions_table() -> None:
    """We store a `sid`, never a token. There is nothing here to steal."""
    columns = set(Session.__table__.columns.keys())
    assert "token" not in columns
    assert "token_hash" not in columns
    assert "keycloak_sid" in columns


# --------------------------------------------------------------------------- #
# `aud` is optional (Keycloak omits it without an Audience mapper)
# --------------------------------------------------------------------------- #
async def test_a_token_without_an_aud_claim_is_accepted(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    """Keycloak does not add the requesting client to `aud` by default, so an
    absent claim must not be a rejection."""
    token = tokens.token(sub="kc-no-aud", aud=None)
    r = await client.post("/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


async def test_aud_is_checked_when_present_and_configured(verifier: Any, tokens: Any) -> None:
    with pytest.raises(TokenRejected) as exc:
        await verifier.verify(tokens.token(sub="kc-aud-bad", aud=["someone-else"]))
    assert exc.value.reason == "bad_audience"


async def test_aud_is_ignored_when_no_audience_is_configured(
    verifier_without_audience: Any, tokens: Any
) -> None:
    claims = await verifier_without_audience.verify(
        tokens.token(sub="kc-aud-skip", aud=["whatever", "account"])
    )
    assert claims.subject == "kc-aud-skip"


async def test_a_missing_aud_is_fine_when_no_audience_is_configured(
    verifier_without_audience: Any, tokens: Any
) -> None:
    claims = await verifier_without_audience.verify(tokens.token(sub="kc-aud-none", aud=None))
    assert claims.subject == "kc-aud-none"


async def test_azp_remains_the_primary_client_binding(verifier: Any, tokens: Any) -> None:
    """`azp` is always present, so it — not `aud` — is what binds the client."""
    with pytest.raises(TokenRejected) as exc:
        await verifier.verify(tokens.token(sub="kc-azp", aud=None, azp="another-client"))
    assert exc.value.reason == "unexpected_authorised_party"


# --------------------------------------------------------------------------- #
# email claims are optional (a realm can drop the `email` client scope)
# --------------------------------------------------------------------------- #
async def test_a_token_without_email_claims_provisions_an_unverified_user(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    token = tokens.token(sub="kc-no-email", email=None, email_verified=None)
    r = await client.post("/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] is None
    assert r.json()["email_verified"] is False


async def test_a_missing_email_verified_claim_is_treated_as_unverified(
    verifier: Any, tokens: Any
) -> None:
    claims = await verifier.verify(
        tokens.token(sub="kc-ev-absent", email="x@example.com", email_verified=None)
    )
    assert claims.email_verified is False
    assert claims.has_usable_email is False


async def test_an_unverified_email_claim_cannot_adopt_an_account_even_without_aud(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    existing = await make_user(db, email="noaud@example.com", email_verified=True)
    token = tokens.token(
        sub="kc-noaud-merge", aud=None, email="noaud@example.com", email_verified=False
    )
    r = await client.post("/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 409
    assert r.json()["code"] == "identity_link_required"
    assert await count_identities(db, existing.id) == 0


# --------------------------------------------------------------------------- #
# back-channel logout: signature mandatory, sid optional, sub fallback
# --------------------------------------------------------------------------- #
async def _post_logout(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(
        "/v1/auth/backchannel-logout",
        content=token,
        headers={"Content-Type": "application/jwt"},
    )


async def test_backchannel_logout_rejects_alg_none(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    """CVE-2026-18569: an unsigned forged logout token must never be accepted."""
    r = await _post_logout(client, tokens.logout_token(sid="sid-none", alg="none"))
    assert r.status_code == 401


async def test_backchannel_logout_rejects_hs256_signed_with_the_public_key(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    r = await _post_logout(client, tokens.logout_token(sid="sid-hs", alg="HS256"))
    assert r.status_code == 401


async def test_backchannel_logout_rejects_a_wrong_audience(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    """Keycloak addresses the logout token to our client id."""
    r = await _post_logout(client, tokens.logout_token(sid="sid-aud", aud="another-client"))
    assert r.status_code == 401


async def test_backchannel_logout_rejects_a_token_without_aud(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    r = await _post_logout(client, tokens.logout_token(sid="sid-noaud", aud=None))
    assert r.status_code == 401


async def test_backchannel_logout_rejects_a_stale_long_lived_token(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    """A logout notification lives about two minutes, not a day."""
    r = await _post_logout(client, tokens.logout_token(sid="sid-old", lifetime_minutes=600))
    assert r.status_code == 401


async def test_backchannel_logout_without_sid_revokes_every_session_of_the_sub(
    client: httpx.AsyncClient, db: AsyncSession, tokens: Any
) -> None:
    """`sid` is only present when the client requires it, so `sub` is the
    fallback — and it must revoke every device."""
    phone = {"Authorization": f"Bearer {tokens.token(sub='kc-subonly', jti='j-p', sid='s-p')}"}
    tablet = {"Authorization": f"Bearer {tokens.token(sub='kc-subonly', jti='j-t', sid='s-t')}"}
    assert (await client.post("/v1/auth/session", headers=phone)).status_code == 200
    assert (await client.post("/v1/auth/session", headers=tablet)).status_code == 200

    logout = await _post_logout(client, tokens.logout_token(sid=None, sub="kc-subonly"))
    assert logout.status_code == 204, logout.text

    assert (await client.get("/v1/auth/me", headers=phone)).status_code == 401
    assert (await client.get("/v1/auth/me", headers=tablet)).status_code == 401
    sessions = (
        await db.scalars(select(Session).where(Session.keycloak_sid.in_(["s-p", "s-t"])))
    ).all()
    assert sessions and all(s.revoked_at is not None for s in sessions)


async def test_backchannel_logout_with_neither_sid_nor_sub_is_a_400(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    r = await _post_logout(client, tokens.logout_token(sid=None, sub=None))
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_logout_token"


async def test_backchannel_logout_for_an_unknown_subject_is_a_noop_204(
    client: httpx.AsyncClient, tokens: Any
) -> None:
    r = await _post_logout(client, tokens.logout_token(sid=None, sub="kc-never-seen"))
    assert r.status_code == 204
