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
        "these count past the service root and break when the code moves: "
        + ", ".join(offenders)
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


def test_the_seed_scripts_use_the_shared_resolver() -> None:
    """Six of them had the same line. One place to be wrong."""
    for name in (
        "seed_demo_world.py",
        "import_generated_pins.py",
        "generate_seed_pins.py",
        "import_seed_photos.py",
    ):
        text = (API / "scripts" / name).read_text(encoding="utf-8")
        assert "parents[3]" not in text, f"{name} still counts to the repo root"
        assert "seed_photos()" in text, f"{name} does not use the resolver"
