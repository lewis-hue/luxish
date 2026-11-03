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
#
# Two classes of variable, and the difference matters.
#
# These are **pinned**, not defaulted. The suite signs its own tokens against
# this issuer and audience, so a developer with a real deployment exported in
# their shell was not configuring the tests, they were breaking them: every
# token the suite minted was rejected by the real issuer's rules and 93 tests
# failed with a 401 that looked like an application bug. The API key is pinned
# for a sharper reason — a real one in the environment lets the suite make
# billed model calls.
os.environ["LUXISH_META_API_KEY"] = "LLM_test-key-not-a-real-credential"
os.environ["LUXISH_ENVIRONMENT"] = "test"
os.environ["LUXISH_KEYCLOAK_ISSUER"] = "https://id.luxish.test/realms/luxish"
os.environ["LUXISH_KEYCLOAK_AUDIENCE"] = "luxish-api"
os.environ["LUXISH_KEYCLOAK_CLIENT_ID"] = "luxish-mobile"
# Storage mode is pinned for the same reason: tests assert which backend the
# service reports and refuses, and a developer running against local files
# would otherwise see those assertions fail as though the code were wrong.
# The one fixture that genuinely needs filesystem media overrides the
# dependency explicitly rather than relying on the ambient environment.
os.environ["LUXISH_UPLOAD_STORAGE_MODE"] = "simulated"
# A deep-link scheme, so the link a shared fit carries is exercised
# rather than left empty. The unconfigured case has its own test.
os.environ["LUXISH_APP_LINK_SCHEME"] = "luxish"
# Pinned for the same reason: a developer pointing the API at a local
# Keycloak while the issuer stays a public tunnel would otherwise have
# that override decide what the suite thinks the default behaviour is.
os.environ.pop("LUXISH_KEYCLOAK_JWKS_URL_OVERRIDE", None)

# ...and the dotenv file, which that pop does not cover.
#
# `Settings` declares `env_file=".env"`, and pydantic-settings reads that file
# itself rather than through `os.environ` — so clearing the variable above
# left the developer's local `.env` still deciding the answer. The moment one
# genuinely needed that override (issuer on a public tunnel, keys next door),
# `test_the_jwks_source_follows_the_issuer_by_default` started failing on
# their machine and nowhere else, which reads as a code fault and is not one.
#
# The suite sets every value it depends on explicitly above, so it has no use
# for the file at all. Switching it off makes the result the same on a laptop
# mid-debugging as in CI, which is the only way a config assertion means
# anything.
# **Every import below the settings block is late on purpose.**
# The application reads its configuration at import time, so the
# environment has to be set before any of it is imported - which
# is exactly what a linter cannot distinguish from sloppiness.
from app.config import Settings as _Settings  # noqa: E402

_Settings.model_config["env_file"] = None

# These stay overridable, deliberately: the Postgres-marked tests are pointed
# at a real database through the environment, and nothing about a bucket name
# or a Redis index can make a passing test lie.
os.environ.setdefault("LUXISH_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LUXISH_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("LUXISH_GCS_BUCKET", "luxish-test")

import base64  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app import models as _models  # noqa: F401, E402  (registers tables)
from app.config import Settings, get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import build_engine, session_factory  # noqa: E402
from app.security.keycloak import JwksCache, TokenVerifier  # noqa: E402


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
def local_media_root(tmp_path: Any) -> Any:
    """Where `local_media_client` keeps its bytes.

    Its own fixture so a test can reach the files behind the rows — deleting
    an object out from under a row is the only way to exercise what happens
    when storage and the database disagree.
    """
    return tmp_path / "media"


@pytest.fixture
async def local_media_client(
    engine: Any, verifier: TokenVerifier, local_media_root: Any
) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose app may read and write media on a real filesystem.

    ``build_local_store`` refuses to run outside a local environment, which is
    deliberate: a deployment writing user media to a container's disk loses it
    on the next revision, and that refusal is asserted elsewhere. The receiver
    and the reader still need somewhere real to put bytes, so this fixture
    grants exactly that, rooted in a directory pytest throws away.
    """
    from app.config import get_settings
    from app.db.session import get_session
    from app.deps import get_token_verifier
    from app.main import create_app

    app = create_app()
    maker = session_factory(engine)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    base = get_settings()
    local = base.model_copy(
        update={"environment": "local", "local_media_root": str(local_media_root)}
    )

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    app.dependency_overrides[get_settings] = lambda: local

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth(tokens: TokenFactory):
    """Build an ``Authorization`` header for a set of claim overrides."""

    def _auth(**overrides: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.token(**overrides)}"}

    return _auth
