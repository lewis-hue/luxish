"""Where the bundled assets are, whichever layout this is running in.

**Every script computed `Path(__file__).parents[3]`.** That is the
repository root when the tree is `<repo>/services/api/scripts/x.py`,
and it is an `IndexError` the moment it is not - which is exactly
what happened when the backend moved into a container, where the
same script sits at `/srv/scripts/x.py` and has only two parents:

    IndexError: 3
      BUNDLED_PHOTOS = Path(__file__).resolve().parents[3] / "assets" ...

Six scripts carried that line. One place to be wrong is better than
six, and this one checks rather than counts.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Set by docker-compose, which mounts the repository's `assets`
#: directory read-only. Honoured first so a container never has to
#: guess.
ENV_VAR = "LUXISH_ASSETS_DIR"


def assets_dir() -> Path:
    """The `assets` directory, found rather than assumed.

    Looked for in order: the environment variable, then every parent
    of this file. Returns the first that exists; raises with the
    places it looked when there is none, because a seeder that
    silently finds nothing produces an empty app and no explanation.
    """
    named = os.environ.get(ENV_VAR)
    if named:
        found = Path(named)
        if found.is_dir():
            return found

    here = Path(__file__).resolve()
    tried: list[Path] = []
    for parent in here.parents:
        candidate = parent / "assets"
        tried.append(candidate)
        if candidate.is_dir():
            return candidate

    raise FileNotFoundError(
        "No `assets` directory. Looked at "
        + ", ".join(str(path) for path in tried)
        + f" and ${ENV_VAR}."
    )


def seed_photos() -> Path:
    """The bundled seed photographs."""
    return assets_dir() / "seed-photos"


__all__ = ["ENV_VAR", "REPO_ENV_VAR", "assets_dir", "repo_root", "seed_photos"]


#: Set by docker-compose, which mounts the repository read-only for
#: the scripts that need files outside this service.
REPO_ENV_VAR = "LUXISH_REPO_DIR"


def repo_root() -> Path:
    """The repository root, found rather than counted.

    **The seventh script with the same bug found this.**
    `seed_demo.py` is what gives a reviewer a wardrobe, and in a
    container it died before doing anything:

        IndexError: 3
          REPO = Path(__file__).resolve().parents[3]

    `assets_dir` already fixed this for the seeders that read
    photographs. This is for the ones that reach for files outside
    `assets` - the wardrobe pictures under the mobile app, the
    mannequin figures - and it is here rather than in each of them
    for the same reason: one place to be wrong.
    """
    named = os.environ.get(REPO_ENV_VAR)
    if named:
        candidate = Path(named)
        if (candidate / "package.json").is_file():
            return candidate

    here = Path(__file__).resolve()
    tried: list[Path] = []
    for parent in here.parents:
        tried.append(parent)
        if (parent / "package.json").is_file() and (parent / "infra").is_dir():
            return parent

    raise FileNotFoundError(
        "No repository root above "
        + str(here)
        + f" and no ${REPO_ENV_VAR}. In a container, mount the repository "
        "and set that variable."
    )
