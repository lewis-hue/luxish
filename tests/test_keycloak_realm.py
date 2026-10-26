"""Regression tests for the Keycloak realm as a security control.

The realm JSON carries the account-takeover invariant the brief forbids us to break.
It is configuration, which means it can be edited without a code review — so the two
fields that matter are pinned here, with the reason attached to the assertion.

Cross-cutting tests live at the repository root rather than inside a service because
they span `infra/` and `services/api/`. Run with:

    services/api/.venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REALM_PATH = REPO_ROOT / "infra" / "keycloak" / "import" / "atelier-realm.json"
COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"


@pytest.fixture(scope="module")
def realm() -> dict[str, Any]:
    return json.loads(REALM_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def keycloak_service(compose: dict[str, Any]) -> dict[str, Any]:
    return compose["services"]["keycloak"]


def _client(realm: dict[str, Any], client_id: str) -> dict[str, Any]:
    for client in realm["clients"]:
        if client["clientId"] == client_id:
            return client
    raise AssertionError(f"client {client_id!r} is missing from the realm")


def _provider(realm: dict[str, Any], alias: str) -> dict[str, Any]:
    for provider in realm["identityProviders"]:
        if provider["alias"] == alias:
            return provider
    raise AssertionError(f"identity provider {alias!r} is missing from the realm")


# --- the import has to actually happen ---------------------------------------


def test_realm_file_is_named_so_keycloak_will_import_it() -> None:
    # Keycloak requires `<realm name>-realm.json`. Any other name is skipped
    # silently, which presents as "my realm config did nothing".
    assert REALM_PATH.name == f"{json.loads(REALM_PATH.read_text('utf-8'))['realm']}-realm.json"


def test_realm_json_carries_no_comment_keys() -> None:
    # Unknown properties risk a Jackson deserialisation failure, so rationale lives
    # in the sibling README instead of in the document.
    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert not key.startswith("_"), f"comment key at {path}{key}"
                walk(value, f"{path}{key}.")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(json.loads(REALM_PATH.read_text(encoding="utf-8")))


def test_no_literal_secret_is_committed(realm: dict[str, Any]) -> None:
    secret = _client(realm, "atelier-api")["secret"]
    assert secret.startswith("${") and secret.endswith("}"), (
        "client secrets must be ${ENV_VAR} placeholders resolved at import"
    )


# --- the account-takeover invariant ------------------------------------------


def test_google_does_not_trust_the_idp_asserted_email(realm: dict[str, Any]) -> None:
    # `trustEmail: true` is the documented precondition for CVE-2026-14781, where
    # `email_verified` is read from the id_token while the address comes from
    # userinfo — letting a hostile provider mark an arbitrary address verified.
    assert _provider(realm, "google")["trustEmail"] is False


def test_google_uses_the_stock_first_broker_login_flow(realm: dict[str, Any]) -> None:
    # The stock flow requires the user to confirm the link and then prove control of
    # the existing account by email or password. Swapping in a flow built on
    # `idp-auto-link` sets an existing user "without verification" — the exact
    # email-merge takeover the brief forbids. There is no per-IdP auto-link toggle;
    # the flow alias is the whole control.
    assert _provider(realm, "google")["firstBrokerLoginFlowAlias"] == "first broker login"


def test_duplicate_emails_are_not_allowed(realm: dict[str, Any]) -> None:
    assert realm["duplicateEmailsAllowed"] is False
    assert realm["verifyEmail"] is True


# --- the mobile client -------------------------------------------------------


def test_mobile_client_is_public_and_requires_pkce(realm: dict[str, Any]) -> None:
    mobile = _client(realm, "atelier-mobile")
    assert mobile["publicClient"] is True
    # A phone binary cannot hold a secret, so PKCE S256 is the only protection
    # against an intercepted authorization code.
    assert mobile["attributes"]["pkce.code.challenge.method"] == "S256"
    assert mobile["implicitFlowEnabled"] is False
    assert mobile["directAccessGrantsEnabled"] is False
    assert mobile["serviceAccountsEnabled"] is False


def test_custom_scheme_redirect_is_listed_explicitly(realm: dict[str, Any]) -> None:
    # Keycloak: for non-http(s) schemes the URI "should be an explicit part of the
    # validation pattern… a general pattern like `*` does not cover non http(s)
    # schemes." So a wildcard cannot stand in for this entry.
    assert "atelier://callback" in _client(realm, "atelier-mobile")["redirectUris"]


def test_no_wildcard_redirect_uri(realm: dict[str, Any]) -> None:
    for client in realm["clients"]:
        for uri in client.get("redirectUris", []):
            assert uri != "*", f"{client['clientId']} has a full wildcard redirect"


def test_production_loopback_redirects_are_dev_only(realm: dict[str, Any]) -> None:
    # Documented as removable for production; this test exists so the entry is a
    # deliberate decision rather than something inherited unnoticed.
    loopback = [
        uri
        for uri in _client(realm, "atelier-mobile")["redirectUris"]
        if "127.0.0.1" in uri or "localhost" in uri
    ]
    assert all(":8081" in uri for uri in loopback), (
        "only the Expo dev-server port may be allowed as a loopback redirect"
    )


def test_backchannel_logout_emits_a_session_id(realm: dict[str, Any]) -> None:
    # Keycloak only includes `sid` in a logout token when this is on, and the
    # attribute defaults to false. Without it the API must revoke every session of
    # `sub`, which is coarser than necessary.
    attributes = _client(realm, "atelier-mobile")["attributes"]
    assert attributes["backchannel.logout.session.required"] == "true"
    assert attributes["backchannel.logout.url"].endswith("/v1/auth/backchannel-logout")


def test_audience_mapper_exists_or_token_validation_cannot_check_aud(
    realm: dict[str, Any],
) -> None:
    # Keycloak deliberately omits the requesting client from an access token's
    # audience. This mapper is the only reason `aud` is ever populated, and is why
    # app/security/keycloak.py treats the check as conditional.
    mappers = _client(realm, "atelier-mobile")["protocolMappers"]
    audience = [m for m in mappers if m["protocolMapper"] == "oidc-audience-mapper"]
    assert audience, "no audience mapper: `aud` will never contain the API"
    config = audience[0]["config"]
    assert config["included.client.audience"] == "atelier-api"
    assert config["access.token.claim"] == "true"


def test_access_token_lifespan_keeps_the_revocation_window_small(
    realm: dict[str, Any],
) -> None:
    # Revocation only closes the window until `exp`, so a long-lived access token is
    # a long-lived un-revokable one.
    assert 0 < realm["accessTokenLifespan"] <= 300
    assert realm["revokeRefreshToken"] is True
    assert realm["refreshTokenMaxReuse"] == 0


# --- the compose wiring the realm depends on ---------------------------------


def test_compose_passes_import_realm_as_a_cli_flag(keycloak_service: dict[str, Any]) -> None:
    # There is no KC_IMPORT_REALM environment variable — it is a picocli flag. Put
    # it in `environment:` and the realm is never imported. Inspect the parsed keys
    # rather than grepping the text, so a comment mentioning the variable cannot
    # fail the test.
    assert "--import-realm" in keycloak_service["command"]
    assert "KC_IMPORT_REALM" not in keycloak_service.get("environment", {})


def test_compose_pins_a_keycloak_version_at_or_above_the_cve_floor(
    keycloak_service: dict[str, Any],
) -> None:
    # 26.8.1 fixed 22 CVEs, three of them in identity brokering.
    image = keycloak_service["image"]
    repository, _, tag = image.rpartition(":")
    assert repository == "quay.io/keycloak/keycloak"
    major, minor, patch = (int(part) for part in tag.split("."))
    assert (major, minor, patch) >= (26, 8, 1), f"Keycloak {tag} is below the CVE floor"


def test_compose_mounts_the_import_directory_keycloak_actually_reads(
    keycloak_service: dict[str, Any],
) -> None:
    # Only .json files directly in this directory are read; subdirectories are
    # ignored, so the mount target has to be exactly this path.
    targets = [volume.split(":")[1] for volume in keycloak_service["volumes"]]
    assert "/opt/keycloak/data/import" in targets
