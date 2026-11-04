"""Where the repository root is, for the tests that read it.

Some guards are about the repository rather than the service: that the
README's commands exist, that `.env.example` covers every variable,
that the login theme has no leftover PatternFly overlay, that the demo
credentials appear nowhere but local files. Those files live above
`services/api`, so the tests have to reach up for them.

**Every one of them counted parents, and three broke the documented
test command.** `npm run api:test` runs the suite in a container where
the service sits at `/srv`, and `parents[3]` from `/srv/tests/x.py`
has nowhere to go:

    ERROR tests/test_local_only_credentials.py - IndexError: 3
    ERROR tests/test_login_theme.py           - IndexError: 3
    ERROR tests/test_notification_targets.py  - IndexError: 1

Collection was interrupted, so a reviewer running the one command the
README gives them saw three errors and no suite. This is the same
counting bug already fixed in `scripts/_assets.py` and
`app/domain/mannequin.py`, which is why it is a helper now rather than
a fourth correction.

The root is found by its markers, not by its depth, and can be named
outright with `LUXISH_REPO_DIR` - which is how `scripts/api-test.sh`
points at the read-only mount it gives the container.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

#: Set by `scripts/api-test.sh` for the containerised route.
ENV_VAR = "LUXISH_REPO_DIR"

#: Both must be present. `package.json` alone also matches any
#: workspace that has one, and `infra/` alone matches nothing useful.
MARKERS = ("package.json", "infra/docker-compose.yml")


def _is_root(candidate: Path) -> bool:
    return all((candidate / marker).exists() for marker in MARKERS)


def find_repo() -> Path | None:
    """The repository root, or `None` when it is not reachable.

    Not an exception: a container that mounts only the service is a
    legitimate place to run most of this suite, and the tests that
    need the repository skip rather than fail there.
    """
    named = os.environ.get(ENV_VAR)
    if named:
        candidate = Path(named)
        if _is_root(candidate):
            return candidate

    for parent in Path(__file__).resolve().parents:
        if _is_root(parent):
            return parent
    return None


def repo_root() -> Path:
    """The repository root, skipping the calling module without one.

    Call at module scope. A skip is the honest result: the guard has
    not passed, it simply had nothing to read.
    """
    found = find_repo()
    if found is None:
        pytest.skip(
            "no repository root above this file and no "
            f"${ENV_VAR}; these guards read files outside services/api",
            allow_module_level=True,
        )
    return found


__all__ = ["ENV_VAR", "MARKERS", "find_repo", "repo_root"]
