"""Application settings.

No secret carries a default — a missing credential must fail loudly at startup
rather than silently fall back to something that looks like a credential.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LUXISH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- links out ----------------------------------------------------------
    #: The app's deep-link scheme, matching the mobile `brand.scheme`.
    #:
    #: Read from the environment rather than written here, because the
    #: product name lives in `apps/mobile/branding.config.js` and nothing
    #: in this service may hardcode it. Empty disables deep links in
    #: shared content rather than emitting a scheme nobody registered.
    app_link_scheme: str = Field(
        default="",
        description="Deep-link scheme for shared content, e.g. the brand slug",
    )
    #: A public web surface for shared content, when one exists. Preferred
    #: over the scheme: a link anybody can open beats one that only works
    #: for people who already have the app.
    public_web_base_url: str = Field(
        default="",
        description="Public base URL for shareable pages, if there is one",
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
    #: Where to fetch the realm's signing keys, when that is not the issuer.
    #:
    #: Issuer and key source are the same host in a deployment, and this stays
    #: unset there. They diverge in local development, where the issuer has to
    #: be a public https URL so a phone and Google can both reach it, while the
    #: API sits next to Keycloak on the LAN. Routing key fetches through the
    #: public tunnel then makes every request depend on a third party staying
    #: up, and when it blinks the API rejects perfectly good tokens with
    #: `jwks_unavailable`.
    #:
    #: This does not weaken validation: the `iss` claim is still checked
    #: against `keycloak_issuer`. It only says where the keys for that issuer
    #: are read from, which is operator configuration rather than user input.
    keycloak_jwks_url_override: str | None = None

    # Token verification (Task 4).
    #
    # The realm SHOULD issue 5-minute access tokens: a revoked `jti` is only
    # enforceable until its own `exp`, so the access-token TTL is the width of
    # the revocation window. ASSUMED here; set on the realm, not by this service.
    assumed_access_token_ttl_seconds: int = 300

    # -- model latency ----------------------------------------------------- #
    #
    #: How hard the model thinks before answering, per class of call.
    #:
    #: Measured on muse-spark-1.3 with an identical screening prompt:
    #: unset 6.72s (380 reasoning tokens), "low" 2.17s (229), "minimal"
    #: 1.93s (129). Left unset the model reasons at full effort on every
    #: call, which is both the slow path and the expensive one, and for
    #: structured extraction it buys nothing a schema was not already
    #: going to enforce.
    #:
    #: Two values rather than one because the two jobs are different. A
    #: classification or a safety verdict is a judgement against a closed
    #: list, and "low" answers those in about two seconds. Composing an
    #: outfit across a wardrobe with tool calls is reasoning that earns
    #: its keep, so the stylist gets its own dial and a higher default.
    model_reasoning_effort: str = "low"
    stylist_reasoning_effort: str = "medium"

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
    #: "local_file" stores bytes on this machine's disk and is refused
    #: outside the local environment; "gcs_signed_url" is the real backend and
    #: is not implemented yet (it refuses rather than faking).
    upload_storage_mode: Literal["simulated", "local_file", "gcs_signed_url"] = (
        "simulated"
    )
    #: Where "local_file" puts objects. Local development only.
    local_media_root: str = "./.media"
    #: Origin the local upload URL is built from. Must be the address a phone
    #: on the LAN can reach, not 127.0.0.1, or the device cannot upload.
    public_base_url: str = "http://127.0.0.1:8010"
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

    #: How long a claimed job may hold its lease before the sweeper assumes
    #: the worker died. MUST exceed the slowest job's runtime: the reclaim
    #: cannot tell "worker died" from "worker still working", so too low a
    #: value re-dispatches healthy long jobs while they run.
    job_lease_seconds: int = 30 * 60

    # --- Celery (ADR-018) -------------------------------------------------- #
    #: Defaults to `redis_url` so local dev needs no extra variable.
    celery_broker_url: str = ""
    #: Deliberately longer than any task can run, so Redis never redelivers
    #: and PostgreSQL stays the only re-drive authority. The shortest value
    #: across *all* broker consumers wins, so anything else connecting to this
    #: Redis must use the same number or it silently reimposes its own.
    celery_visibility_timeout_seconds: int = 24 * 60 * 60
    #: Must stay under the platform's SIGTERM-to-SIGKILL window (10s on Cloud
    #: Run, not configurable). This is the time a worker has to hand unacked
    #: messages back instead of stranding them until the visibility timeout.
    celery_soft_shutdown_seconds: float = 8.0
    #: Soft limit raises a catchable exception; hard limit kills the child.
    celery_task_soft_time_limit_seconds: int = 10 * 60
    celery_task_time_limit_seconds: int = 12 * 60
    #: How often the sweeper re-drives the queue from PostgreSQL.
    #:
    #: This is the upper bound on how long a job waits when its dispatch is
    #: lost, so it is a user-visible number, not a housekeeping one: someone
    #: who has just photographed a garment is watching a spinner for exactly
    #: this long in the worst case. Thirty seconds is short enough to read as
    #: a slow reply rather than a hang, and long enough that the two queries
    #: it runs are irrelevant next to the model calls on the same database.
    celery_sweep_interval_seconds: float = 30.0
    #: How often the push outbox is drained.
    #:
    #: Nothing in this service opens a socket to the gateway except the
    #: task on this schedule, so this is the whole latency of a
    #: notification: the gap between somebody following you and your
    #: phone saying so. A minute reads as prompt for a follow or a
    #: finished shot, and it is the floor rather than the typical wait
    #: for anything held by quiet hours, which leaves when its
    #: `send_after` arrives.
    #:
    #: Shorter is not better. The drain is also the throttle - a large
    #: fan-out deliberately leaves over several passes so the gateway
    #: is not handed a flood, and so everybody does not open the app in
    #: the same second.
    push_drain_interval_seconds: float = 60.0

    job_max_attempts: int = 5

    # SSRF-guarded fetcher (Task 10).
    urlfetch_max_redirects: int = 3
    urlfetch_max_bytes: int = 1 * 1024 * 1024
    urlfetch_timeout_seconds: float = 5.0

    @model_validator(mode="before")
    @classmethod
    def _default_celery_broker_to_redis(cls, data: Any) -> Any:
        """Point Celery at ``redis_url`` unless a broker is named explicitly.

        Local dev and CI then need no extra variable, while production can
        still split the broker onto its own instance. Done here rather than in
        a property because Celery reads the value once at import.
        """
        if isinstance(data, dict) and not data.get("celery_broker_url"):
            redis = data.get("redis_url") or cls.model_fields["redis_url"].default
            data = {**data, "celery_broker_url": redis}
        return data

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

        ``keycloak_jwks_url_override`` wins where it is set, for the local
        case where the issuer is a public tunnel and the keys are next door.
        The issuer claim is validated either way.
        """
        if self.keycloak_jwks_url_override:
            return self.keycloak_jwks_url_override
        return f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
