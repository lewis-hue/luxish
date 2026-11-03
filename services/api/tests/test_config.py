"""Task 3 — configuration carries no secret defaults."""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("LUXISH_"):
            monkeypatch.delenv(key, raising=False)


def test_settings_raises_on_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "database_url" in str(exc.value)


def test_meta_api_key_has_no_default() -> None:
    field = Settings.model_fields["meta_api_key"]
    assert field.is_required(), "meta_api_key must never carry a default (no secret defaults)"


CREDENTIAL_HINTS = ("key", "secret", "password", "token", "credential")


def test_every_required_input_is_supplied_by_the_environment() -> None:
    for name in (
        "database_url",
        "meta_api_key",
        "gcs_bucket",
        "keycloak_issuer",
        "keycloak_client_id",
    ):
        assert Settings.model_fields[name].is_required(), name


def test_no_credential_shaped_field_carries_a_literal_default() -> None:
    """A numeric knob may have a default; anything string-shaped may not."""
    for name, field in Settings.model_fields.items():
        if not any(hint in name for hint in CREDENTIAL_HINTS) or field.is_required():
            continue
        assert not isinstance(field.default, (str, SecretStr)), (
            f"{name} defaults to a literal value that could be mistaken for a credential"
        )


def test_settings_reads_the_luxish_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("LUXISH_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("LUXISH_META_API_KEY", "LLM_abc")
    monkeypatch.setenv("LUXISH_GCS_BUCKET", "bucket")
    monkeypatch.setenv("LUXISH_KEYCLOAK_ISSUER", "https://id.test/realms/a")
    monkeypatch.setenv("LUXISH_KEYCLOAK_AUDIENCE", "luxish-api")
    monkeypatch.setenv("LUXISH_KEYCLOAK_CLIENT_ID", "luxish-mobile")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@h/db"
    assert s.environment == "local"


def test_keycloak_settings_are_required_and_have_no_defaults() -> None:
    for name in ("keycloak_issuer", "keycloak_client_id"):
        assert Settings.model_fields[name].is_required(), name


def test_keycloak_audience_is_optional_because_keycloak_omits_aud() -> None:
    """Keycloak does not add the requesting client to `aud` without an Audience
    protocol mapper, so requiring it here would 401 every real token."""
    field = Settings.model_fields["keycloak_audience"]
    assert not field.is_required()
    assert field.default is None


def test_jwks_url_is_derived_from_the_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("LUXISH_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("LUXISH_META_API_KEY", "LLM_abc")
    monkeypatch.setenv("LUXISH_GCS_BUCKET", "bucket")
    monkeypatch.setenv("LUXISH_KEYCLOAK_ISSUER", "https://id.test/realms/luxish/")
    monkeypatch.setenv("LUXISH_KEYCLOAK_AUDIENCE", "luxish-api")
    monkeypatch.setenv("LUXISH_KEYCLOAK_CLIENT_ID", "luxish-mobile")
    s = Settings(_env_file=None)
    assert s.keycloak_jwks_url == "https://id.test/realms/luxish/protocol/openid-connect/certs"


def test_hmac_algorithms_are_not_acceptable() -> None:
    algs = Settings.model_fields["allowed_signing_algorithms"].default
    assert all(not a.startswith("HS") for a in algs)
    assert "none" not in algs


def test_the_jwks_url_has_no_auth_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `/auth` path prefix was removed in Keycloak 17."""
    _clear(monkeypatch)
    monkeypatch.setenv("LUXISH_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("LUXISH_META_API_KEY", "LLM_abc")
    monkeypatch.setenv("LUXISH_GCS_BUCKET", "bucket")
    monkeypatch.setenv("LUXISH_KEYCLOAK_ISSUER", "https://id.test/realms/luxish")
    monkeypatch.setenv("LUXISH_KEYCLOAK_CLIENT_ID", "luxish-mobile")
    url = Settings(_env_file=None).keycloak_jwks_url
    assert "/auth/" not in url
    assert url.endswith("/realms/luxish/protocol/openid-connect/certs")


def test_the_jwks_source_follows_the_issuer_by_default() -> None:
    cfg = Settings(
        keycloak_issuer="https://id.example/realms/luxish",
        keycloak_client_id="luxish-mobile",
    )
    assert cfg.keycloak_jwks_url == (
        "https://id.example/realms/luxish/protocol/openid-connect/certs"
    )


def test_the_jwks_source_can_be_set_apart_from_the_issuer() -> None:
    """Local development needs these to differ, and only these.

    The issuer must be a public https URL so a phone and Google can both reach
    it; the API sits next to Keycloak. Fetching keys through the public tunnel
    made every request depend on a third party staying up, and when it blinked
    the API rejected good tokens with `jwks_unavailable`. The issuer claim is
    still validated against `keycloak_issuer` either way.
    """
    cfg = Settings(
        keycloak_issuer="https://luxish-kc.loca.lt/realms/luxish",
        keycloak_client_id="luxish-mobile",
        keycloak_jwks_url_override=(
            "http://localhost:55080/realms/luxish/protocol/openid-connect/certs"
        ),
    )
    assert cfg.keycloak_jwks_url.startswith("http://localhost:55080/")
    # The thing that must not change.
    assert cfg.keycloak_issuer == "https://luxish-kc.loca.lt/realms/luxish"
