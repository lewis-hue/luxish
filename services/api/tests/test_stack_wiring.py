"""The start-up script has to leave the stack in a state that works.

Four faults, all found in one sitting, all of the same kind: a layer
reported success while the thing it was responsible for was wrong.
None of them is visible in a unit test of the application, and every
one of them made the app look broken on a phone.

  * **The workers ran a different build from the API.** They share one
    image deliberately, so a worker can never lag by a rebuild - and
    `docker compose up -d` recreates only what it thinks is stale, which
    undid exactly that. The API accepted a cancellation and wrote the
    row; the workers had no idea what the row meant, drew the picture
    anyway and marked it ready a minute later.

  * **A dead process kept the port.** A leaked socket listened on
    `0.0.0.0:8010`, Docker took `[::]:8010` instead and called the
    publish a success, and every IPv4 client - the phone over the LAN -
    reached a months-old build with no workers behind it. `/healthz`
    answered fine, from the wrong process.

  * **Nothing pinned the app's API address.** `apps/mobile/.env.example`
    states that dev-stack rewrites both bundled addresses on every
    start. It rewrote one, so a clone kept `127.0.0.1:8010` - which on
    a phone is the phone. Sign-in worked and every screen was empty.

  * **The port was hardcoded in the compose file**, so there was no way
    out of a port somebody else was holding.
"""

from __future__ import annotations

import re

from tests._repo import repo_root

REPO = repo_root()

DEV_STACK = (REPO / "scripts" / "dev-stack.sh").read_text(encoding="utf-8")
REVIEW = (REPO / "scripts" / "review.sh").read_text(encoding="utf-8")
COMPOSE = (REPO / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
MOBILE_EXAMPLE = (REPO / "apps" / "mobile" / ".env.example").read_text(encoding="utf-8")


def test_every_role_is_recreated_so_no_worker_lags_the_api() -> None:
    """`up -d` alone leaves old containers on the old image."""
    assert "--force-recreate" in DEV_STACK, (
        "docker compose is started without --force-recreate, so a rebuilt "
        "image reaches the API and not the workers"
    )


def test_the_api_and_the_workers_share_one_image() -> None:
    """The reason the recreate matters: one image, five containers.

    If the workers ever get a build of their own, they can drift from
    the API by a rebuild and the guard above stops being the fix.
    """
    roles = re.findall(r"^  (worker-\w+|beat|api):\s*$", COMPOSE, re.MULTILINE)
    assert {"api", "beat"} <= set(roles), f"expected the api and beat services, got {roles}"
    assert COMPOSE.count("build:") == 1, (
        "more than one service builds its own image; the workers must share "
        "the API's so they cannot run different code"
    )


def test_the_published_api_port_can_be_changed() -> None:
    """A port can be held by a process that no longer exists."""
    assert "${LUXISH_API_PORT:-8010}:8010" in COMPOSE, (
        "the API port is hardcoded, so a leaked socket on 8010 cannot be "
        "worked around without editing the compose file"
    )


def test_startup_checks_that_the_port_serves_this_build() -> None:
    """`/healthz` cannot tell: the dead listener answered it."""
    assert "verify-api.mjs" in DEV_STACK, (
        "nothing checks that what answers on the API port is this checkout"
    )
    assert (REPO / "scripts" / "verify-api.mjs").is_file()


def test_the_verifier_looks_over_ipv4() -> None:
    """The whole point. `localhost` resolves to `::1` first on Windows.

    Checking only that would have reached the container and reported
    everything well, while the phone - IPv4, over the LAN - was talking
    to the leaked socket.
    """
    verifier = (REPO / "scripts" / "verify-api.mjs").read_text(encoding="utf-8")
    assert "127.0.0.1" in verifier, "the verifier never looks over IPv4"
    assert "[::1]" in verifier, "the verifier never looks over IPv6"


def test_both_bundled_addresses_are_pinned_on_every_start() -> None:
    """Because `.env.example` promises it, and one of them was not.

    `EXPO_PUBLIC_*` values are compiled into the bundle, so a wrong one
    is not something the app can recover from at runtime.
    """
    assert "pin_api_url" in DEV_STACK, (
        "EXPO_PUBLIC_API_BASE_URL is never rewritten, so a clone keeps "
        "127.0.0.1 - which on a phone is the phone"
    )
    assert "EXPO_PUBLIC_API_BASE_URL" in DEV_STACK
    assert "EXPO_PUBLIC_KEYCLOAK_ISSUER" in DEV_STACK


def test_the_pinned_api_address_carries_the_configured_port() -> None:
    """Pinning the address and not the port would fix half of it."""
    body = DEV_STACK[DEV_STACK.index("pin_api_url() {") :]
    body = body[: body.index("\n}\n")]
    assert "$port" in body, "pin_api_url ignores the port it was given"


def test_the_example_does_not_promise_more_than_the_script_does() -> None:
    """The documentation was the only thing that knew about this.

    `.env.example` said both lines were rewritten on every start. That
    sentence is what made the bug hard to see: the file looked wrong
    and was documented as self-correcting.
    """
    claims_rewrite = "rewrites both lines" in MOBILE_EXAMPLE
    if claims_rewrite:
        assert "pin_api_url" in DEV_STACK, (
            "the example claims both lines are rewritten; make it true or change the sentence"
        )


def test_the_reported_api_url_is_the_one_in_use() -> None:
    """A summary that prints the wrong port sends a reviewer nowhere."""
    assert "http://$host:8010" not in REVIEW, (
        "review.sh prints a hardcoded port, which is wrong whenever LUXISH_API_PORT is set"
    )
    assert "LUXISH_API_PORT" in REVIEW
