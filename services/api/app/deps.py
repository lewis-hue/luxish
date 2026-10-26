"""FastAPI dependencies.

The verifier is a dependency (not a module global) so tests can supply one
backed by a locally generated keypair instead of a live Keycloak.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.domain.auth import AuthContext, authenticate
from app.errors import Unauthenticated
from app.security.keycloak import JwksCache, TokenRejected, TokenVerifier

logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@lru_cache(maxsize=1)
def _verifier() -> TokenVerifier:
    cfg = get_settings()
    return TokenVerifier(
        issuer=cfg.keycloak_issuer,
        audience=cfg.keycloak_audience,
        client_id=cfg.keycloak_client_id,
        jwks=JwksCache(cfg.keycloak_jwks_url, ttl_seconds=cfg.jwks_cache_ttl_seconds),
        leeway_seconds=cfg.jwt_leeway_seconds,
        allowed_algorithms=cfg.allowed_signing_algorithms,
    )


def get_token_verifier() -> TokenVerifier:
    return _verifier()


VerifierDep = Annotated[TokenVerifier, Depends(get_token_verifier)]


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated("A bearer token is required.")
    return token.strip()


async def current_auth(
    request: Request,
    db: SessionDep,
    verifier: VerifierDep,
    settings: SettingsDep,
) -> AuthContext:
    """Verify the bearer token and resolve it to a local user.

    Every rejection is reported to the client as a flat 401: the reason is
    logged, never returned, so a prober learns nothing about which check failed.
    """
    token = bearer_token(request)
    try:
        claims = await verifier.verify(token)
    except TokenRejected as exc:
        logger.info("token rejected", extra={"reason": exc.reason})
        raise Unauthenticated("The access token was not accepted.") from exc

    return await authenticate(
        db,
        claims,
        session_ttl_days=settings.session_ttl_days,
        link_challenge_ttl_minutes=settings.identity_link_challenge_ttl_minutes,
        user_agent=request.headers.get("User-Agent"),
    )


AuthDep = Annotated[AuthContext, Depends(current_auth)]
