"""The composition root.

Every other test module mounts only what it needs, which is what makes them
fast and independent — and is exactly why none of them would notice a router
that was written but never registered, or a job kind that is enqueued but has
no handler. Both of those look like working code right up until production.

The third thing checked here is subtler: two routers share the ``/wardrobe``
prefix. That is safe only while their path spaces stay disjoint, so it is
asserted rather than assumed.

A note on how this inspects the app. FastAPI 0.162 stopped flattening included
routers into ``app.routes`` — an included router is now a single opaque
``_IncludedRouter`` entry, and walking ``app.routes`` for ``APIRoute`` finds
only the routes declared directly on the app. So this module reads the two
surfaces that are public API instead: the generated OpenAPI document (what is
reachable) and each ``APIRouter``'s own ``routes`` (what each module declares).
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.main import API_PREFIX, create_app

#: Every router the service is supposed to expose, by the prefix it claims.
#: Writing a router and forgetting to register it is the mistake this prevents.
EXPECTED_PREFIXES: tuple[str, ...] = (
    "/v1/auth",
    "/v1/uploads",
    "/v1/wardrobe",
    "/v1/social",
    "/v1/regional",
    "/v1/stylist",
)


def _router_modules() -> tuple:
    from app.routers import (
        auth,
        regional,
        social_import,
        stylist,
        uploads,
        wardrobe,
        wardrobe_media,
    )

    return (auth, uploads, wardrobe, wardrobe_media, social_import, regional, stylist)


def _declared() -> list[tuple[str, str, str]]:
    """``(method, full path, owning module)`` for every route every router declares."""
    declared: list[tuple[str, str, str]] = []
    for module in _router_modules():
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            # A route hidden from the schema on purpose is not part of the
            # product's contract and cannot be checked against the OpenAPI
            # document. The local upload receiver is the only one: in a
            # deployment the client PUTs straight to object storage and the
            # service never sees the bytes, so publishing it would invite a
            # client to depend on it.
            if not route.include_in_schema:
                continue
            # ``route.path`` already carries the router's own prefix; only the
            # app-level API prefix is added at include time.
            full = f"{API_PREFIX}{route.path}"
            for method in route.methods:
                declared.append((method, full, module.__name__))
    return declared


@pytest.fixture(scope="module")
def reachable() -> dict[str, set[str]]:
    """Path → upper-cased methods, as the served OpenAPI document reports them."""
    paths = create_app().openapi()["paths"]
    return {path: {method.upper() for method in ops} for path, ops in paths.items()}


def test_every_router_is_actually_mounted(reachable: dict[str, set[str]]) -> None:
    for prefix in EXPECTED_PREFIXES:
        assert any(path.startswith(prefix) for path in reachable), (
            f"nothing is served under {prefix}: the router module exists but "
            f"_install_routers never registers it"
        )


def test_account_deletion_is_reachable_outside_the_auth_prefix(
    reachable: dict[str, set[str]],
) -> None:
    # Mounted separately from the auth router, so it is the one most easily
    # dropped in a refactor of _install_routers.
    assert "DELETE" in reachable.get("/v1/account", set())


def test_every_declared_route_is_served(reachable: dict[str, set[str]]) -> None:
    """A route a module declares but the app never serves is dead code."""
    missing = [
        f"{method} {path} (declared in {owner})"
        for method, path, owner in _declared()
        if method not in reachable.get(path, set())
    ]
    assert missing == [], f"declared but not served: {missing}"


def test_no_two_routers_claim_the_same_path_and_method() -> None:
    """The wardrobe/wardrobe_media prefix overlap is safe only while this holds.

    FastAPI resolves a collision by registration order and reports nothing, so
    the loser is simply unreachable — and because the two share a prefix, a new
    path on either side could start shadowing the other silently. Asserting
    disjointness is what lets them keep sharing the prefix.
    """
    seen: dict[tuple[str, str], str] = {}
    collisions: list[str] = []
    for method, path, owner in _declared():
        key = (method, path)
        if key in seen:
            collisions.append(f"{method} {path}: {seen[key]} and {owner}")
        else:
            seen[key] = owner
    assert collisions == [], f"two handlers claim the same route: {collisions}"


def test_both_wardrobe_routers_contribute(reachable: dict[str, set[str]]) -> None:
    """Both halves of /wardrobe are served, not just the one registered first."""
    assert "/v1/wardrobe/garments" in reachable
    assert any(
        path.startswith("/v1/wardrobe/garments/") and "media" in path
        for path in reachable
    ), "wardrobe_media's routes are not being served"


def test_every_enqueued_job_kind_has_a_handler() -> None:
    """A kind that can be enqueued but not handled accumulates silently.

    The job row is written, the queue never drains, and nothing errors — the
    user just watches a spinner forever. Much cheaper to catch here.
    """
    from app.domain import garment_media, stylist
    from app.workers import runner

    handlers = runner.all_handlers()
    enqueued = {
        stylist.JOB_KIND,
        garment_media.CATEGORISE_JOB_KIND,
        garment_media.BACKGROUND_REMOVAL_JOB_KIND,
    }
    missing = enqueued - set(handlers)
    assert missing == set(), f"these kinds are enqueued with no handler: {missing}"


def test_asking_for_an_unhandled_queue_fails_loudly() -> None:
    """A deployable pointed at a queue nobody serves must not look healthy."""
    from app.workers.runner import UnknownJobKind, all_handlers

    with pytest.raises(UnknownJobKind) as excinfo:
        all_handlers(["media.derive", "nonsense.kind"])

    assert excinfo.value.unknown == ("nonsense.kind",)
    # The message must name what the service *does* handle, or an operator has
    # no way to spot the typo.
    assert "media.derive" in str(excinfo.value)


def test_selecting_a_subset_gives_exactly_that_subset() -> None:
    from app.workers.runner import all_handlers

    assert set(all_handlers(["media.derive"])) == {"media.derive"}
