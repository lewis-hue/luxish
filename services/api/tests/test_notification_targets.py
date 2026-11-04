"""Where a notification goes when somebody taps it.

**This file exists because two of three targets were dead.** They read
`/(tabs)/wardrobe` and `/(tabs)/stylist` - where those screens sit in
the mobile project, not where they are on the device. `(tabs)` is an
Expo Router *group*: it organises files and never appears in a URL, so
both pushes resolved to nothing and tapping either notice did nothing
at all. Nobody noticed because a push that goes nowhere looks exactly
like a push that was ignored.

The check is deliberately crude - a path is read out of this module's
source and matched against the app's route files - because the
alternative is this drifting again the next time a screen moves, which
is precisely what happened to the stylist.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._repo import repo_root

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
APP_ROUTES = repo_root() / "apps" / "mobile" / "src" / "app"

#: Targets that name a record rather than a screen. The segment after
#: the prefix is an id, so only the prefix is checked.
DYNAMIC = {
    "/fit/": "fit/[id].tsx",
    "/member/": "member/[id].tsx",
    # The id here is the other person, not the thread: the screen
    # loads a conversation by who it is with.
    "/messages/": "messages/[id].tsx",
}


def declared_targets() -> list[str]:
    """Every destination a notification can carry, from anywhere.

    Two kinds of notice, two field names, and originally only one of
    them was checked here. An inbox row names a `target` and they all
    live in `notifications.py`; a push row names a `deep_link` and
    those are written by whatever caused the event - a follow in
    `community.py`, a save in `posts.py`, a message, a finished shot.
    Scanning only the first module meant the four newest destinations
    in the app had never been checked against a route at all, which is
    the exact oversight that left `/(tabs)/wardrobe` in place.

    So this reads the whole domain package. A new notification cannot
    be added anywhere without its destination being checked.
    """
    found: list[str] = []
    for path in sorted((API_ROOT / "app" / "domain").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        # Plain strings and f-strings. Requiring the `=` at a call
        # keeps the prose that documents these fields out of it.
        found += re.findall(r'(?:target|deep_link)=f?"([^"]+)"', source)
    # An id substituted into an f-string is a placeholder here; the
    # prefix is what gets checked.
    return sorted({t for t in found if t.startswith("/")})


def test_there_are_targets_to_check() -> None:
    """A regex that silently matches nothing would pass every test
    below without looking at anything."""
    # Three inbox targets and four push destinations.
    found = declared_targets()
    assert len(found) >= 7, found


@pytest.mark.parametrize("target", declared_targets())
def test_a_target_never_names_a_route_group(target: str) -> None:
    """`(tabs)` is a folder, not a path segment.

    This is the whole bug: a target carrying it routes to nowhere.
    """
    assert "(" not in target, target


@pytest.mark.parametrize("target", declared_targets())
def test_a_target_points_at_a_screen_that_exists(target: str) -> None:
    """The app has to have somewhere to go.

    Checked against the route files rather than a list kept here,
    because a list kept here is the thing that went stale.
    """
    if not APP_ROUTES.is_dir():  # pragma: no cover - API checked alone
        pytest.skip("mobile app not present in this checkout")

    for prefix, route in DYNAMIC.items():
        if target.startswith(prefix):
            assert (APP_ROUTES / route).exists(), f"{target} -> {route}"
            return

    name = target.strip("/")
    # A screen is either a file at the root of the routes, or one
    # inside any group folder - the group is invisible in the URL,
    # which is the point.
    candidates = [
        APP_ROUTES / f"{name}.tsx",
        *APP_ROUTES.glob(f"(*)/{name}.tsx"),
    ]
    assert any(path.exists() for path in candidates), (
        f"{target} has no screen; looked for {[str(c) for c in candidates]}"
    )
