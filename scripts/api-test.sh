#!/usr/bin/env bash
#
# Run the API suite with whatever the machine actually has.
#
# **`npm run api:test` used to be `cd services/api && pytest -q`,
# which worked on no clean machine.** The README promises a reviewer
# needs Docker and Node and nothing else, so there is no Python on the
# host to run pytest with - and the runtime image installs `.` rather
# than `.[dev]`, so pytest was not in the container either. A
# documented command that cannot run anywhere is worse than no
# command, because the reviewer reads the failure as a broken suite.
#
# So this picks a route instead of assuming one:
#
#   a local pytest, if there is one   - fastest, and what a developer
#                                       with the venv already wants
#   the `dev` image, otherwise        - needs only Docker
#
# Arguments pass straight through, so `npm run api:test -- -k taste`
# and `npm run api:test -- tests/test_avatar.py -x` both work on
# either route.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO/services/api"
IMAGE="luxish-api:test"

say() { printf '%s\n' "$*" >&2; }

# A pytest that can actually import the app. A bare `command -v
# pytest` is not enough: a pytest from some other environment fails
# on the first import and looks like a broken suite.
local_pytest() {
  for py in "$API_DIR/.venv/bin/python" "$API_DIR/.venv/Scripts/python.exe" python python3; do
    if command -v "$py" >/dev/null 2>&1 || [ -x "$py" ]; then
      if "$py" -c 'import pytest, app.main' >/dev/null 2>&1; then
        printf '%s' "$py"
        return 0
      fi
    fi
  done
  return 1
}

if PY="$(local_pytest)"; then
  say "Running the suite with $PY"
  cd "$API_DIR"
  exec "$PY" -m pytest -q "$@"
fi

if ! docker info >/dev/null 2>&1; then
  say "No local pytest, and Docker is not running."
  say ""
  say "Start Docker Desktop, or install the suite's dependencies:"
  say "  python -m venv services/api/.venv"
  say "  services/api/.venv/bin/pip install -e \"services/api[dev]\""
  exit 1
fi

say "No local pytest. Running the suite in Docker."

# Built on demand and cached by Docker, so this is slow once and
# quick afterwards. Only the `dev` target carries a test runner.
docker build --quiet --target dev -t "$IMAGE" "$API_DIR" >/dev/null

# **Git Bash rewrites container paths, so they need protecting.**
#
# MSYS treats any argument that looks like a Unix path as a host path
# and converts it. The first version of this ran
# `docker run -w /srv ...` and Docker answered:
#
#   the working directory 'C:/Program Files/Git/srv' is invalid
#
# `/srv` is inside the container, where Git Bash has no business
# looking. `MSYS_NO_PATHCONV=1` turns the rewriting off - and once it
# is off the host path has to be given in a form Docker Desktop
# understands, which `pwd -W` produces (`C:/Users/...`).
#
# The container-side working directory is `WORKDIR /srv` in the image,
# so it is not repeated here: one less path to be rewritten.
TESTS="$API_DIR/tests"
MOUNT_REPO="$REPO"
case "$(uname -s 2>/dev/null)" in
  MINGW* | MSYS* | CYGWIN*)
    TESTS="$(cd "$API_DIR/tests" && pwd -W)"
    MOUNT_REPO="$(cd "$REPO" && pwd -W)"
    export MSYS_NO_PATHCONV=1
    export MSYS2_ARG_CONV_EXCL='*'
    ;;
esac

# **The repository is mounted too, because some guards read it.**
#
# A handful of tests check things above `services/api`: that the
# README's commands exist, that `.env.example` covers every setting,
# that the demo credentials appear in no deployable file. Without the
# repository they skip - and a suite that quietly skips its own
# guards is the failure mode this project keeps meeting, so they get
# what they need instead.
#
# `tests/` is in `.dockerignore` and mounted rather than baked, so
# editing a test does not invalidate a build layer.
#
# Read-only, both of them: a suite run must not be able to change the
# working tree. `--rm` because this container is one suite run and
# nothing else.
#
# `LUXISH_*` settings are deliberately absent apart from the repository
# path: the suite must not reach the running stack. It builds its own
# database and stubs every provider at the seam, which is what makes
# it deterministic and free.
exec docker run --rm \
  -v "$TESTS:/srv/tests:ro" \
  -v "$MOUNT_REPO:/repo:ro" \
  -e LUXISH_REPO_DIR=/repo \
  "$IMAGE" \
  python -m pytest -q "$@"
