"""Paths that work wherever the code is running.

**The same counting bug broke seven modules.**
`Path(__file__).resolve().parents[N]` is the repository root only when
the file sits exactly where the author assumed. Move the code into a
container, where `services/api/app/domain/x.py` becomes
`/srv/app/domain/x.py`, and the count runs off the end of the tree:

    IndexError: 4
      MANNEQUIN_DIR = Path(__file__).resolve().parents[4] / "apps" ...

That one took `/v1/avatar` down with a 500 on every request, because
it raised at import time. Six seed scripts had the same line and
failed the same way.

These pin the two rules that fixed it: find the directory rather than
count to it, and let an operator name it outright.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

API = Path(__file__).resolve().parents[1]

#: Modules whose path arithmetic is relative to their own package and
#: therefore survives being moved as a unit.
ALLOWED = {
    # `parents[2]` from app/domain/ is the service root, which travels
    # with the code in every layout including the image.
    "app/domain/regional.py",
}


def _code_only(path: Path) -> str:
    """The file with comments and strings removed.

    A comment explaining the bug is not the bug. The first version of
    this test flagged the very note that documents the fix, which is
    the kind of false positive that gets a guard deleted.
    """
    kept: list[str] = []
    try:
        for tok in tokenize.generate_tokens(
            io.StringIO(path.read_text(encoding="utf-8", errors="ignore")).readline
        ):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                kept.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return ""
    return " ".join(kept)


def test_no_module_counts_its_way_to_the_repository_root() -> None:
    offenders: list[str] = []
    for path in (API / "app").rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel in ALLOWED:
            continue
        for match in re.finditer(r"parents\s*\[\s*(\d+)\s*\]", _code_only(path)):
            if int(match.group(1)) >= 3:
                offenders.append(f"{rel}: parents[{match.group(1)}]")
    assert not offenders, (
        "these count past the service root and break when the code moves: " + ", ".join(offenders)
    )


def test_the_mannequin_directory_is_searched_for() -> None:
    """It is outside this service's tree, so it cannot be counted to
    and cannot be copied into the image. It is found or named."""
    from app.domain import mannequin

    source = Path(mannequin.__file__)
    assert "LUXISH_MANNEQUIN_DIR" in source.read_text(encoding="utf-8"), (
        "an operator must be able to name it"
    )
    assert "parents [ 4 ]" not in _code_only(source).replace("parents[4]", "parents [ 4 ]")


def test_a_missing_mannequin_directory_does_not_break_the_import() -> None:
    """**It used to raise at import time**, which took every avatar
    request down with a 500. A figure nobody can draw is a feature
    degraded, not a service down."""
    import importlib
    import os

    from app.domain import mannequin

    before = os.environ.get("LUXISH_MANNEQUIN_DIR")
    os.environ["LUXISH_MANNEQUIN_DIR"] = "/definitely/not/here"
    try:
        reloaded = importlib.reload(mannequin)
        assert not reloaded.MANNEQUIN_DIR.is_dir()
    finally:
        if before is None:
            os.environ.pop("LUXISH_MANNEQUIN_DIR", None)
        else:
            os.environ["LUXISH_MANNEQUIN_DIR"] = before
        importlib.reload(mannequin)


def test_no_script_counts_its_way_to_the_repository_root() -> None:
    """**Every script, not a list of four.**

    This named the four seeders that had been fixed, so the fifth,
    sixth and seventh went unnoticed - and the seventh was
    `seed_demo.py`, which is what gives a reviewer a wardrobe. In a
    container it died before doing anything:

        IndexError: 3
          REPO = Path(__file__).resolve().parents[3]

    A guard that lists its subjects only ever guards the bugs already
    found. This one scans the directory, so a new script arrives
    already covered.

    `_assets.py` is exempt because the quoted lines in its docstring
    are the explanation, and `_code_only` cannot strip a docstring
    that is the module's own.
    """
    offenders: list[str] = []
    for path in sorted((API / "scripts").glob("*.py")):
        if path.name == "_assets.py":
            continue
        for match in re.finditer(r"parents\s*\[\s*(\d+)\s*\]", _code_only(path)):
            if int(match.group(1)) >= 2:
                offenders.append(f"scripts/{path.name}: parents[{match.group(1)}]")

    assert not offenders, (
        "these break the moment the tree is not a full checkout, which is "
        "every container: use `from _assets import repo_root, seed_photos`. " + ", ".join(offenders)
    )


def test_the_shared_resolver_offers_both_roots() -> None:
    """`assets_dir` was not enough on its own.

    It covers the seeders that read photographs. The scripts that
    reach for the wardrobe pictures or the figures under the mobile
    app need the repository itself, and without somewhere to get it
    they each counted.
    """
    import sys

    sys.path.insert(0, str(API / "scripts"))
    import _assets

    assert hasattr(_assets, "repo_root"), "nowhere to get the repository root"
    assert hasattr(_assets, "assets_dir")
    assert _assets.REPO_ENV_VAR == "LUXISH_REPO_DIR"
    assert _assets.repo_root().is_dir()


def test_no_test_counts_its_way_to_the_repository_root() -> None:
    """The suite itself had the bug, and it broke the documented command.

    `npm run api:test` runs in a container where the service sits at
    `/srv`, so `parents[3]` from `/srv/tests/x.py` raises during
    collection. Three files did it, pytest reported three errors and
    collected nothing, and a reviewer following the README saw a
    broken suite.

    `tests/_repo.py` finds the root by its markers instead. Reaching
    for a file above `services/api` is fine; counting your way there
    is not.
    """
    offenders: list[str] = []
    for path in sorted((API / "tests").glob("*.py")):
        if path.name == "_repo.py":
            continue
        code = _code_only(path)
        for match in re.finditer(r"parents\s*\[\s*(\d+)\s*\]", code):
            if int(match.group(1)) >= 2:
                offenders.append(f"tests/{path.name}: parents[{match.group(1)}]")
        # `API.parents[1]` counts as one by the rule above and is still
        # an IndexError in the image, because `API` is already the
        # service root there. Climbing from a name that is itself a
        # resolved path is the same bug wearing a variable.
        for match in re.finditer(r"([A-Za-z_]\w*)\s+\.\s+parents\s*\[", code):
            offenders.append(f"tests/{path.name}: {match.group(1)}.parents[...]")

    assert not offenders, (
        "these break when the suite runs anywhere but a full checkout; "
        "use `from tests._repo import repo_root`: " + ", ".join(offenders)
    )


def test_the_repo_resolver_can_be_pointed_at_a_mount() -> None:
    """`scripts/api-test.sh` names the mount rather than hoping.

    Without the override the container would have to contain a whole
    checkout for the repository-level guards to run, and they would
    silently skip instead.
    """
    from tests import _repo
    from tests._repo import repo_root

    assert _repo.ENV_VAR == "LUXISH_REPO_DIR"
    assert _repo.find_repo() is not None, "cannot find the repository from the suite"

    script = (repo_root() / "scripts" / "api-test.sh").read_text(encoding="utf-8")
    assert f"-e {_repo.ENV_VAR}=/repo" in script, (
        "the containerised route does not tell the suite where the repository is"
    )
    assert ":/repo:ro" in script, "the repository mount is missing or writable"
