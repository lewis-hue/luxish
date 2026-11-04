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


__all__ = ["ENV_VAR", "assets_dir", "seed_photos"]
