"""Shared fixtures.

The unit suite runs with **no live Postgres and no live Keycloak**: portable DDL
is created on aiosqlite and test tokens are signed by a keypair generated here.
Tests whose SQL is Postgres-only carry the ``postgres`` marker and are excluded
by default (see ``addopts`` in pyproject.toml).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

# Settings carries no secret defaults (Task 3), so the suite supplies them
# before anything imports app.config.
os.environ.setdefault("LUXISH_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LUXISH_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("LUXISH_META_API_KEY", "LLM_test-key-not-a-real-credential")
os.environ.setdefault("LUXISH_GCS_BUCKET", "luxish-test")
os.environ.setdefault("LUXISH_ENVIRONMENT", "test")
os.environ.setdefault("LUXISH_KEYCLOAK_ISSUER", "https://id.luxish.test/realms/luxish")
os.environ.setdefault("LUXISH_KEYCLOAK_AUDIENCE", "luxish-api")
os.environ.setdefault("LUXISH_KEYCLOAK_CLIENT_ID", "luxish-mobile")

import base64
import hashlib
import hmac
import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as _models  # noqa: F401  (registers tables)
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_engine, session_factory
from app.security.keycloak import JwksCache, TokenVerifier


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _hmac_jws(claims: dict[str, Any], *, secret: bytes, alg: str, kid: str) -> str:
    """Build a token signed with ``secret`` as an HMAC key.

    This is the algorithm-confusion attack: the verifier is handed a token whose
    header says HS256 and whose signature was computed with the JWKS *public*
    key as the shared secret.
    """
    digest = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}[alg]
    header = _b64(json.dumps({"alg": alg, "typ": "JWT", "kid": kid}).encode())
    payload = _b64(json.dumps(claims).encode())
    signing_input = header + b"." + payload
    signature = _b64(hmac.new(secret, signing_input, digest).digest())
    return (signing_input + b"." + signature).decode()


ISSUER = "https://id.luxish.test/realms/luxish"
AUDIENCE = "luxish-api"
CLIENT_ID = "luxish-mobile"
KID = "test-key-1"
OTHER_KID = "attacker-key"


# --------------------------------------------------------------------------- #
# database
# --------------------------------------------------------------------------- #
@pytest.fixture
async def engine() -> AsyncIterator[Any]:
    eng = build_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: Any) -> AsyncIterator[AsyncSession]:
    maker = session_factory(engine)
    async with maker() as session:
        yield session


# --------------------------------------------------------------------------- #
# signing keys and tokens
# --------------------------------------------------------------------------- #
class TokenFactory:
    """Mints Keycloak-shaped tokens signed by a locally generated keypair."""

    def __init__(self) -> None:
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # -- JWKS ------------------------------------------------------------- #
    def jwks(self) -> dict[str, Any]:
        algo = jwt.algorithms.RSAAlgorithm
        keys = []
        for kid, key in ((KID, self.private),):
            jwk = algo.to_jwk(key.public_key(), as_dict=True)
            jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
            keys.append(jwk)
        return {"keys": keys}

    def public_pem(self) -> bytes:
        return self.private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    # -- access tokens ----------------------------------------------------- #
    def claims(self, **overrides: Any) -> dict[str, Any]:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": [AUDIENCE, "account"],
            "azp": CLIENT_ID,
            "sub": "kc-sub-" + uuid.uuid4().hex[:8],
            "sid": uuid.uuid4().hex,
            "jti": uuid.uuid4().hex,
            "typ": "Bearer",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()) - 1,
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "email": None,
            "email_verified": False,
            "preferred_username": "tester",
        }
        claims.update(overrides)
        return {k: v for k, v in claims.items() if v is not None}

    def token(self, *, kid: str = KID, alg: str = "RS256", **overrides: Any) -> str:
        claims = self.claims(**overrides)
        if alg == "none":
            return jwt.encode(claims, key="", algorithm="none", headers={"kid": kid})
        if alg.startswith("HS"):
            # Algorithm confusion, assembled by hand: PyJWT refuses to HMAC with
            # a PEM key, but an attacker has no such scruples.
            return _hmac_jws(claims, secret=self.public_pem(), alg=alg, kid=kid)
        key = self.other_private if kid == OTHER_KID else self.private
        return jwt.encode(claims, key=key, algorithm=alg, headers={"kid": kid})

    def logout_token(
        self,
        *,
        sid: str | None = None,
        alg: str = "RS256",
        lifetime_minutes: int = 2,
        **overrides: Any,
    ) -> str:
        """A Keycloak back-channel logout token.

        ``aud`` is the client id, which is what the server actually sends, and
        ``sid`` is optional because Keycloak only includes it when the client
        has "Backchannel logout session required" switched on.
        """
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": overrides.pop("sub", "kc-sub-logout"),
            "sid": sid,
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=lifetime_minutes)).timestamp()),
            "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        if alg == "none":
            return jwt.encode(claims, key="", algorithm="none", headers={"kid": KID})
        if alg.startswith("HS"):
            return _hmac_jws(claims, secret=self.public_pem(), alg=alg, kid=KID)
        return jwt.encode(claims, key=self.private, algorithm=alg, headers={"kid": KID})


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def verifier(tokens: TokenFactory, settings: Settings) -> TokenVerifier:
    calls: list[int] = []

    async def fetch_jwks() -> dict[str, Any]:
        calls.append(1)
        return tokens.jwks()

    cache = JwksCache(
        settings.keycloak_jwks_url,
        ttl_seconds=settings.jwks_cache_ttl_seconds,
        fetcher=fetch_jwks,
    )
    v = TokenVerifier(
        issuer=settings.keycloak_issuer,
        audience=settings.keycloak_audience,
        client_id=settings.keycloak_client_id,
        jwks=cache,
        leeway_seconds=settings.jwt_leeway_seconds,
        allowed_algorithms=settings.allowed_signing_algorithms,
    )
    v.test_fetch_calls = calls  # type: ignore[attr-defined]
    return v


@pytest.fixture
def verifier_without_audience(tokens: TokenFactory, settings: Settings) -> TokenVerifier:
    """Keycloak populates `aud` only with an Audience mapper, so an unset
    expected audience is the default deployment, not an edge case."""

    async def fetch_jwks() -> dict[str, Any]:
        return tokens.jwks()

    return TokenVerifier(
        issuer=settings.keycloak_issuer,
        audience=None,
        client_id=settings.keycloak_client_id,
        jwks=JwksCache(settings.keycloak_jwks_url, ttl_seconds=300, fetcher=fetch_jwks),
        leeway_seconds=settings.jwt_leeway_seconds,
        allowed_algorithms=settings.allowed_signing_algorithms,
    )


# --------------------------------------------------------------------------- #
# HTTP client wired to the in-memory database and the local verifier
# --------------------------------------------------------------------------- #
@pytest.fixture
async def client(engine: Any, verifier: TokenVerifier) -> AsyncIterator[httpx.AsyncClient]:
    from app.db.session import get_session
    from app.deps import get_token_verifier
    from app.main import create_app

    app = create_app()
    maker = session_factory(engine)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth(tokens: TokenFactory):
    """Build an ``Authorization`` header for a set of claim overrides."""

    def _auth(**overrides: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.token(**overrides)}"}

    return _auth
