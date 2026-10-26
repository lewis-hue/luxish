"""Task 3 — configuration carries no secret defaults."""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("ATELIER_"):
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
        "keycloak_audience",
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


def test_settings_reads_the_atelier_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("ATELIER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("ATELIER_META_API_KEY", "LLM_abc")
    monkeypatch.setenv("ATELIER_GCS_BUCKET", "bucket")
    monkeypatch.setenv("ATELIER_KEYCLOAK_ISSUER", "https://id.test/realms/a")
    monkeypatch.setenv("ATELIER_KEYCLOAK_AUDIENCE", "atelier-api")
    monkeypatch.setenv("ATELIER_KEYCLOAK_CLIENT_ID", "atelier-mobile")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@h/db"
    assert s.environment == "local"


def test_keycloak_settings_are_required_and_have_no_defaults() -> None:
    for name in ("keycloak_issuer", "keycloak_audience", "keycloak_client_id"):
        assert Settings.model_fields[name].is_required(), name


def test_jwks_url_is_derived_from_the_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("ATELIER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("ATELIER_META_API_KEY", "LLM_abc")
    monkeypatch.setenv("ATELIER_GCS_BUCKET", "bucket")
    monkeypatch.setenv("ATELIER_KEYCLOAK_ISSUER", "https://id.test/realms/atelier/")
    monkeypatch.setenv("ATELIER_KEYCLOAK_AUDIENCE", "atelier-api")
    monkeypatch.setenv("ATELIER_KEYCLOAK_CLIENT_ID", "atelier-mobile")
    s = Settings(_env_file=None)
    assert s.keycloak_jwks_url == "https://id.test/realms/atelier/protocol/openid-connect/certs"


def test_hmac_algorithms_are_not_acceptable() -> None:
    algs = Settings.model_fields["allowed_signing_algorithms"].default
    assert all(not a.startswith("HS") for a in algs)
    assert "none" not in algs
