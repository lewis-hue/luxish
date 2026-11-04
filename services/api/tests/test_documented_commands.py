"""Every command the README gives a reviewer has to work on their machine.

**`npm run api:test` was `cd services/api && pytest -q`, which ran
nowhere on a clean machine.** The README promises Docker and Node and
nothing else, so there was no host `pytest`; and the image installs
`.` rather than `.[dev]`, so there was no `pytest` in the container
either. A reviewer following the README got `pytest: not found` and
reasonably read it as a broken suite.

The repository is public for a hackathon, so a documented command
that cannot run is worse than a missing one: the reviewer has no way
to tell the difference between a broken command and a broken project.
These tests fail the build rather than let that ship again.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests._repo import repo_root

API = Path(__file__).resolve().parents[1]
REPO = repo_root()

DOCKERFILE = API / "Dockerfile"
PACKAGE_JSON = REPO / "package.json"
README = REPO / "README.md"
TEST_SCRIPT = REPO / "scripts" / "api-test.sh"


def _scripts() -> dict[str, str]:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]


def _stages() -> list[str]:
    """The build stages, in file order."""
    return re.findall(
        r"^FROM\s+\S+\s+AS\s+(\S+)",
        DOCKERFILE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )


def test_the_image_has_a_stage_that_can_run_the_suite() -> None:
    assert "dev" in _stages(), "no `dev` stage: there is nowhere to run the suite with only Docker"
    body = DOCKERFILE.read_text(encoding="utf-8")
    assert '".[dev]"' in body or "'.[dev]'" in body, (
        "the dev stage must install the `dev` extra, which is where pytest is"
    )


def test_the_runtime_stage_is_last_so_compose_does_not_build_the_dev_one() -> None:
    """docker-compose declares no `target`, so the final stage is what it builds.

    Move `dev` below `runtime` and every container in the stack ships
    a test runner, which is a bigger image and a wider attack surface
    for no benefit at all.
    """
    stages = _stages()
    assert stages, "no named build stages"
    assert stages[-1] != "dev", (
        f"the `dev` stage is last, so docker-compose would build it: stage order is {stages}"
    )
    assert stages[-1] == "runtime", f"expected `runtime` last, found {stages}"

    compose = (REPO / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "target:" not in compose, (
        "docker-compose now sets a build `target`; this test's reasoning "
        "about stage order no longer holds and needs rewriting"
    )


def test_the_runtime_image_does_not_ship_the_test_runner() -> None:
    """`pip install "."` in the shared base, `.[dev]` only in `dev`."""
    body = DOCKERFILE.read_text(encoding="utf-8")
    runtime = body[body.index("FROM base AS runtime") :]
    assert "[dev]" not in runtime, "the runtime stage installs dev dependencies; keep them in `dev`"


def test_api_test_dispatches_rather_than_assuming_a_host_python() -> None:
    command = _scripts()["api:test"]
    assert "pytest" not in command, (
        "`api:test` calls pytest directly, which needs a Python the README "
        f"says is not required: {command!r}"
    )
    assert "api-test.sh" in command, f"expected the dispatcher, found {command!r}"
    assert TEST_SCRIPT.is_file(), f"{TEST_SCRIPT} is missing"


def test_the_dispatcher_protects_container_paths_from_git_bash() -> None:
    """Git Bash rewrites anything shaped like a Unix path.

    `docker run -w /srv` became `-w 'C:/Program Files/Git/srv'` and
    Docker refused it. Windows reviewers run this in Git Bash, so the
    guard belongs in the suite, not in a comment.
    """
    body = TEST_SCRIPT.read_text(encoding="utf-8")
    assert "MSYS_NO_PATHCONV" in body, "nothing stops MSYS rewriting the container-side paths"
    assert "pwd -W" in body, (
        "with path conversion off, the host path must be given in a form Docker Desktop understands"
    )


def test_every_npm_script_the_readme_names_exists() -> None:
    named = set(re.findall(r"npm run ([a-z0-9:_-]+)", README.read_text(encoding="utf-8")))
    missing = sorted(named - set(_scripts()))
    assert not missing, f"the README names scripts that do not exist: {missing}"


def test_the_readme_tells_windows_reviewers_which_shell_to_use() -> None:
    """`./scripts/review.sh` in PowerShell fails as though the file were missing.

    It is the first command in the README, so getting this wrong
    stops a reviewer before they see anything at all.
    """
    body = README.read_text(encoding="utf-8")
    assert "Git Bash" in body, (
        "the README never says which shell to use on Windows, where "
        "`./scripts/review.sh` fails in PowerShell"
    )
