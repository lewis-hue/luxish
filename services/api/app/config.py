"""Application settings.

No secret carries a default — a missing credential must fail loudly at startup
rather than silently fall back to something that looks like a credential.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATELIER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- required: no defaults, secret or otherwise -------------------------
    database_url: str = Field(description="SQLAlchemy async DSN, e.g. postgresql+asyncpg://…")
    meta_api_key: SecretStr = Field(description="Meta Model API key (prefixed LLM_), ADR-007")
    gcs_bucket: str = Field(description="Object storage bucket for user media")

    # Keycloak (>= 26.8.1) is the identity provider; this service verifies,
    # never issues.
    keycloak_issuer: str = Field(
        description="Realm issuer URL, matched against the token `iss` exactly"
    )
    keycloak_client_id: str = Field(description="Expected token `azp` (authorised party)")

    # --- infrastructure with safe, non-credential local defaults -----------
    redis_url: str = "redis://localhost:6379/0"
    environment: Environment = "local"
    log_level: str = "INFO"

    # Bounded connection pool. ASSUMED (Task 3); revisited by Task 15 capacity work.
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800

    # Keycloak does not add the requesting client to an access token's `aud` by
    # default — that needs an Audience protocol mapper on the realm. So this is
    # optional: when set, a token carrying `aud` must include it; when unset or
    # when the claim is absent, the check is skipped. `azp` is always present
    # and is the primary client binding.
    keycloak_audience: str | None = None

    # Token verification (Task 4).
    #
    # The realm SHOULD issue 5-minute access tokens: a revoked `jti` is only
    # enforceable until its own `exp`, so the access-token TTL is the width of
    # the revocation window. ASSUMED here; set on the realm, not by this service.
    assumed_access_token_ttl_seconds: int = 300
    jwks_cache_ttl_seconds: int = 300
    jwt_leeway_seconds: int = 10
    allowed_signing_algorithms: tuple[str, ...] = ("RS256", "ES256")

    # Sessions (Task 4) are keyed on the Keycloak `sid`; we store no bearer
    # material of our own.
    session_ttl_days: int = 30
    identity_link_challenge_ttl_minutes: int = 15

    # Upload authorisation (Task 5).
    upload_authorization_ttl_seconds: int = 900
    upload_max_bytes: int = 25 * 1024 * 1024
    #: "simulated" returns a labelled stub URL; "gcs_signed_url" is the real
    #: backend and is not implemented in Phase A (it refuses rather than faking).
    upload_storage_mode: Literal["simulated", "gcs_signed_url"] = "simulated"
    upload_allowed_content_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
    )

    # Durable jobs (Task 6).
    #: Which background-removal backend runs. Keys match
    #: ``app.providers.segmentation.SEGMENTATION_PROVIDERS``. "meta_sam" is the
    #: default because at current volume it is cheaper than keeping a GPU warm;
    #: "birefnet" is the self-hosted path and currently refuses rather than
    #: faking (ADR-017).
    segmentation_provider: Literal["meta_sam", "birefnet"] = "meta_sam"

    job_max_attempts: int = 5

    # SSRF-guarded fetcher (Task 10).
    urlfetch_max_redirects: int = 3
    urlfetch_max_bytes: int = 1 * 1024 * 1024
    urlfetch_timeout_seconds: float = 5.0

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def keycloak_jwks_url(self) -> str:
        """Realm JWKS endpoint.

        Built from the issuer with no ``/auth`` prefix — that prefix was removed
        in Keycloak 17, and the issuer already ends in ``/realms/<realm>``.

        Deliberately *not* routed through ``app.security.urlfetch.safe_fetch``:
        that guard refuses private addresses, and Keycloak is expected to be
        reachable on a private in-cluster address. This URL is operator
        configuration, never user input.
        """
        return f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
