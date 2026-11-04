"""Every screen that shows a render being drawn has to offer a way out.

The endpoint is only half of it. A cancel nobody can reach is the same
feature gap as no cancel at all, and the gap was reported from two
places at once: "avatar generation in both wardrobe and profile tabs
are taking forever to show results... there is no way to cancel a
running process and then retry."

Two screens watch a render in flight - the avatar screen and the
photoreal try-on the stylist and wardrobe use - and a third will be
added eventually. This finds them by what they do rather than by a
list kept by hand: anything that calls `isWorking` is reporting
progress to somebody, and anybody being shown progress should be able
to stop it.

Scanning the app's source from the API suite follows
`test_notification_targets.py`, which checks the same way that every
notification has a screen to open.
"""

from __future__ import annotations

from pathlib import Path

from tests._repo import repo_root

MOBILE = repo_root() / "apps" / "mobile" / "src"

#: Where the hooks live, so the definitions are not mistaken for uses.
HOOKS = MOBILE / "api" / "queries" / "avatar.ts"

#: The mutation a screen calls to stop one.
CANCEL_HOOK = "useCancelRender"


def _watchers() -> dict[Path, str]:
    """Files that report a render in flight, with their source."""
    found: dict[Path, str] = {}
    for path in MOBILE.rglob("*.ts*"):
        if "__tests__" in path.parts or ".test." in path.name:
            continue
        if path == HOOKS:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "isWorking(" in text:
            found[path] = text
    return found


def test_the_cancel_hook_exists() -> None:
    body = HOOKS.read_text(encoding="utf-8")
    assert f"export function {CANCEL_HOOK}" in body, (
        f"{CANCEL_HOOK} is gone; the screens below call it"
    )
    assert "/v1/avatar/renders/{render_id}/cancel" in body


def test_some_screen_actually_watches_a_render() -> None:
    """Guards against the scan silently matching nothing.

    A test that passes because it found no files to check is the kind
    that gets trusted for years while the thing it guards rots.
    """
    assert _watchers(), "no file reports a render in flight; this scan is broken"


def test_every_screen_that_shows_a_render_can_stop_it() -> None:
    missing = sorted(
        path.relative_to(MOBILE).as_posix()
        for path, text in _watchers().items()
        if CANCEL_HOOK not in text
    )
    assert not missing, (
        "these show a render being drawn with no way to stop it, which is "
        f"the gap cancelling exists to close: {missing}"
    )
