"""Keycloak token verification (Keycloak >= 26.8.1).

This service **verifies** tokens; it never issues them. Keycloak is the identity
provider and brokers the social providers (Google now, Apple later), so the only
credential this service ever sees is a realm-signed JWT.

Four properties are load-bearing:

1. **Algorithm confusion is refused before any key is loaded.** ``alg: none`` and
   every HMAC algorithm are rejected outright — otherwise a public key fetched
   from the JWKS could be replayed as an HMAC secret.
2. **The issuer is compared exactly**, and ``azp`` must equal our client id, so a
   token minted for a different client in the same realm is not accepted.
3. **Nothing is trusted from an unverified signature.** Claims are read only from
   ``jwt.decode``'s verified output, never from the unverified payload. Only the
   header's ``alg``/``kid`` are read first, and they are used solely to *reject*
   or to select a key.
4. **A back-channel logout token is verified exactly as strictly** - signature,
   issuer, audience, freshness, and the required logout event. CVE-2026-18569
   was precisely this check being skippable; it is not optional here.

Two Keycloak facts shape the audience and session handling:

* ``aud`` is **not** populated by default. Keycloak does not add the requesting
  client to an access token audience; that needs an Audience protocol mapper on
  the realm. So ``aud`` is verified only when the claim is present *and* an
  expected audience is configured. ``azp`` - always present - is the primary
  client binding.
* ``sid`` is **not** always present on a logout token. The server sets it only
  when the client has "Backchannel logout session required" switched on, and
  that defaults to false, so revocation falls back to ``sub``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt

BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"

#: A logout token is minted for immediate delivery (Keycloak gives it about two
#: minutes). Anything long-lived is not a fresh logout notification.
MAX_LOGOUT_TOKEN_LIFETIME_SECONDS = 600

#: Only asymmetric algorithms whose public half lives in the JWKS.
DEFAULT_ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256", "ES256")

JwksFetcher = Callable[[], Awaitable[Mapping[str, Any]]]


class TokenRejected(Exception):
    """A token was not accepted. ``reason`` is for logs, never for the client."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason)


class LogoutTokenIncomplete(TokenRejected):
    """A validly signed logout token that names no session and no subject.

    Distinct from a rejection: the sender is authentic and the signature is
    good, but the message is unusable - so the caller answers 400, not 401.
    """


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """The subset of a verified access token this service acts on."""

    subject: str
    email: str | None
    email_verified: bool
    jti: str | None
    sid: str | None
    expires_at: datetime
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @property
    def has_usable_email(self) -> bool:
        return bool(self.email) and self.email_verified


@dataclass(frozen=True, slots=True)
class LogoutClaims:
    """A verified OIDC back-channel logout token."""

    subject: str | None
    sid: str | None
    jti: str | None
    expires_at: datetime


class JwksCache:
    """Caches the realm JWKS with a TTL and a bounded refresh rate.

    An unknown ``kid`` triggers at most one refresh per ``min_refresh_seconds``,
    so a stream of forged tokens cannot turn into a stream of outbound requests.
    """

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int = 300,
        fetcher: JwksFetcher | None = None,
        timeout_seconds: float = 5.0,
        min_refresh_seconds: float = 30.0,
    ) -> None:
        self._url = url
        self._ttl = ttl_seconds
        self._fetcher = fetcher or self._http_fetch
        self._timeout = timeout_seconds
        self._min_refresh = min_refresh_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _http_fetch(self) -> Mapping[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(self._url, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise TokenRejected("jwks_malformed", "JWKS document was not an object")
        return payload

    @property
    def _is_stale(self) -> bool:
        return (time.monotonic() - self._fetched_at) > self._ttl

    async def _refresh(self) -> None:
        try:
            document = await self._fetcher()
            key_set = jwt.PyJWKSet.from_dict(dict(document))
        except TokenRejected:
            raise
        except Exception as exc:  # network, JSON, or malformed JWK
            raise TokenRejected("jwks_unavailable", str(exc)) from exc
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id}
        self._fetched_at = time.monotonic()

    async def get_key(self, kid: str | None) -> jwt.PyJWK:
        async with self._lock:
            if not self._keys or self._is_stale:
                await self._refresh()
            key = self._keys.get(kid) if kid else self._single_key()
            if key is not None:
                return key
            # Unknown kid: the realm may have rotated. Refresh at most this often.
            if (time.monotonic() - self._fetched_at) >= self._min_refresh:
                await self._refresh()
                key = self._keys.get(kid) if kid else self._single_key()
            if key is None:
                raise TokenRejected("unknown_key", f"no JWKS key for kid={kid!r}")
            return key

    def _single_key(self) -> jwt.PyJWK | None:
        if len(self._keys) == 1:
            return next(iter(self._keys.values()))
        return None


class TokenVerifier:
    """Verifies realm-issued access tokens and back-channel logout tokens."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str | None,
        client_id: str,
        jwks: JwksCache,
        leeway_seconds: int = 10,
        allowed_algorithms: Sequence[str] = DEFAULT_ALLOWED_ALGORITHMS,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.client_id = client_id
        self.jwks = jwks
        self.leeway = leeway_seconds
        self.allowed_algorithms = tuple(allowed_algorithms)
        for algorithm in self.allowed_algorithms:
            if algorithm.upper().startswith("HS") or algorithm.lower() == "none":
                raise ValueError(f"refusing to configure symmetric/none algorithm {algorithm!r}")

    # -- helpers ----------------------------------------------------------- #
    def _header(self, token: str) -> dict[str, Any]:
        if not token or token.count(".") != 2:
            raise TokenRejected("malformed", "token is not a three-part JWS")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise TokenRejected("malformed", str(exc)) from exc
        algorithm = str(header.get("alg", ""))
        if algorithm not in self.allowed_algorithms:
            # Covers `none` and every HMAC algorithm, including the confusion
            # attack that signs with the JWKS public key as a shared secret.
            raise TokenRejected("algorithm_not_allowed", f"alg={algorithm!r} is not accepted")
        return header

    @staticmethod
    def _audience_values(payload: Mapping[str, Any]) -> list[str]:
        raw = payload.get("aud")
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, (list, tuple)):
            return [value for value in raw if isinstance(value, str)]
        raise TokenRejected("invalid", "aud must be a string or a list of strings")

    def _check_audience(
        self,
        payload: Mapping[str, Any],
        *,
        accepted: Sequence[str],
        require_claim: bool,
    ) -> None:
        """Verify ``aud`` when there is something to verify it against.

        Keycloak omits the requesting client from ``aud`` unless an Audience
        mapper is configured, so on an access token an absent claim is normal
        and is not a failure. A logout token does carry ``aud``, and there the
        claim is required.
        """
        present = self._audience_values(payload)
        if not accepted:
            return
        if not present:
            if require_claim:
                raise TokenRejected("missing_claim", "aud is required on this token")
            return
        if not set(present) & set(accepted):
            raise TokenRejected(
                "bad_audience",
                f"aud={present!r} includes none of {list(accepted)!r}",
            )

    async def _decode(
        self,
        token: str,
        *,
        required: Sequence[str],
    ) -> dict[str, Any]:
        header = self._header(token)
        key = await self.jwks.get_key(header.get("kid"))
        try:
            return jwt.decode(
                token,
                key=key,
                algorithms=list(self.allowed_algorithms),
                issuer=self.issuer,
                leeway=self.leeway,
                options={
                    "require": list(required),
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    # Checked by _check_audience instead: an absent claim is
                    # normal on a Keycloak access token, which PyJWT's own
                    # audience handling cannot express.
                    "verify_aud": False,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenRejected("expired", str(exc)) from exc
        except jwt.ImmatureSignatureError as exc:
            raise TokenRejected("not_yet_valid", str(exc)) from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenRejected("bad_audience", str(exc)) from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenRejected("bad_issuer", str(exc)) from exc
        except jwt.MissingRequiredClaimError as exc:
            raise TokenRejected("missing_claim", str(exc)) from exc
        except jwt.InvalidSignatureError as exc:
            raise TokenRejected("bad_signature", str(exc)) from exc
        except jwt.InvalidTokenError as exc:
            raise TokenRejected("invalid", str(exc)) from exc

    # -- access tokens ------------------------------------------------------ #
    async def verify(self, token: str) -> TokenClaims:
        payload = await self._decode(
            token,
            # `aud` is deliberately absent from the required set - see the module
            # docstring. `sub` comes from the default `basic` client scope.
            required=("exp", "iat", "iss", "sub"),
        )
        self._check_audience(
            payload,
            accepted=[self.audience] if self.audience else [],
            require_claim=False,
        )
        if payload.get("azp") != self.client_id:
            raise TokenRejected(
                "unexpected_authorised_party",
                f"azp={payload.get('azp')!r} is not {self.client_id!r}",
            )
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise TokenRejected("missing_claim", "sub must be a non-empty string")
        email = payload.get("email")
        if email is not None and not isinstance(email, str):
            raise TokenRejected("invalid", "email claim must be a string")
        return TokenClaims(
            subject=subject,
            email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
            email_verified=payload.get("email_verified") is True,
            jti=payload.get("jti") if isinstance(payload.get("jti"), str) else None,
            sid=payload.get("sid") if isinstance(payload.get("sid"), str) else None,
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
            raw=payload,
        )

    # -- back-channel logout ------------------------------------------------ #
    async def verify_logout_token(self, token: str) -> LogoutClaims:
        """Verify an OIDC back-channel logout token (RFC-style, OIDC BCL 1.0).

        Keycloak addresses the logout token to the client that receives it, so
        our client id - or a configured audience - is what ``aud`` must contain.
        The signature is mandatory: CVE-2026-18569 was exactly this check being
        skippable.
        """
        payload = await self._decode(
            token, required=("exp", "iat", "iss", "aud", "events")
        )
        accepted = [self.client_id] + ([self.audience] if self.audience else [])
        self._check_audience(payload, accepted=accepted, require_claim=True)
        lifetime = int(payload["exp"]) - int(payload["iat"])
        if lifetime > MAX_LOGOUT_TOKEN_LIFETIME_SECONDS:
            raise TokenRejected(
                "logout_token_not_fresh",
                f"logout token lifetime {lifetime}s exceeds "
                f"{MAX_LOGOUT_TOKEN_LIFETIME_SECONDS}s",
            )
        events = payload.get("events")
        if not isinstance(events, dict) or BACKCHANNEL_LOGOUT_EVENT not in events:
            raise TokenRejected("not_a_logout_token", "events lacks the backchannel-logout member")
        if "nonce" in payload:
            # OIDC back-channel logout forbids `nonce`; its presence means this
            # is an ID token being replayed as a logout token.
            raise TokenRejected("not_a_logout_token", "logout tokens must not carry a nonce")
        sid = payload.get("sid") if isinstance(payload.get("sid"), str) else None
        subject = payload.get("sub") if isinstance(payload.get("sub"), str) else None
        if not sid and not subject:
            # Authentic but unusable. `sub` is always present on a real Keycloak
            # logout token; `sid` only when the client requires it.
            raise LogoutTokenIncomplete(
                "no_sid_or_sub", "a logout token must name a session or a subject"
            )
        return LogoutClaims(
            subject=subject,
            sid=sid,
            jti=payload.get("jti") if isinstance(payload.get("jti"), str) else None,
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
        )


__all__ = [
    "BACKCHANNEL_LOGOUT_EVENT",
    "DEFAULT_ALLOWED_ALGORITHMS",
    "MAX_LOGOUT_TOKEN_LIFETIME_SECONDS",
    "JwksCache",
    "LogoutClaims",
    "LogoutTokenIncomplete",
    "TokenClaims",
    "TokenRejected",
    "TokenVerifier",
]
