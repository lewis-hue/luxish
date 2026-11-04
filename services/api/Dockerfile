# The API and the workers, in one image.
#
# **Why this exists: a reviewer should need Docker and Node, nothing
# else.** The API and the four workers used to run as local Python
# processes, so reviewing the app meant installing Python 3.12,
# creating a virtualenv and resolving fourteen dependencies before
# anything started - and getting the version wrong failed in ways
# that looked like the app was broken. Everything the backend needs
# is in here now; Metro stays on the host because the phone connects
# to it over the LAN.
#
# One image for both roles. The API and the workers import the same
# modules and must run the same code - a worker lagging the API by a
# rebuild is the stale-process bug this project has already paid
# for twice. The command decides which it is.

FROM python:3.12-slim AS base

# Pillow needs libjpeg and zlib at runtime; the rest of the stack is
# pure Python wheels. `--no-install-recommends` keeps the layer small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libjpeg62-turbo \
      zlib1g \
      curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# **Metadata and package together, then one install.**
#
# The usual trick is to copy `pyproject.toml` alone so a source edit
# does not re-resolve every wheel. That does not work here: this is
# a real package (`[tool.setuptools] packages = ["app"]`), so `pip
# install .` reads the metadata and then fails with "package
# directory 'app' does not exist" when the source is absent.
#
# Copying `app` alongside it keeps most of the benefit: the wheel
# resolution is still one layer, and everything outside `app` -
# scripts, alembic, the seed manifests - lands after it.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip \
 && pip install "."

COPY . .

# **The test stage, which is not the default.**
#
# The README promises a reviewer needs Docker and Node and nothing
# else, and `npm run api:test` broke that promise: there is no Python
# on the host to run `pytest` with, and the runtime image installs
# `.` rather than `.[dev]`, so pytest was absent there too. The
# documented command worked on no clean machine at all.
#
# So the suite gets a stage of its own. The runtime image stays lean -
# it does not ship a test runner - and the tests still run with only
# Docker installed.
#
# `tests/` is in `.dockerignore` and stays there: the suite is
# bind-mounted at run time instead of copied, so editing a test does
# not invalidate a layer. `scripts/api-test.sh` does the mounting.
FROM base AS dev

RUN pip install ".[dev]"

# Root here on purpose. This stage exists to run a suite in a
# throwaway container, and the suite writes caches and SQLite files
# wherever pytest points it.
CMD ["python", "-m", "pytest", "-q"]

# **The runtime stage must stay last in this file.** docker-compose
# declares no `target`, so it builds whatever the final stage is. Put
# `dev` below this line and every container in the stack would ship a
# test runner.
FROM base AS runtime

# Not root. The container writes only to `.media` and the SQLite
# file, both of which it owns.
# **`/data` is created here so the named volume inherits its owner.**
#
# Docker seeds an empty named volume from whatever is at that path
# in the image, ownership included - and creates the directory as
# root when the image has nothing there. The container runs as
# `luxish`, so the first migration failed with "unable to open
# database file" against a directory it could not write to.
RUN useradd --create-home --uid 10001 luxish \
 && mkdir -p /srv/.media /data \
 && chown -R luxish:luxish /srv /data
USER luxish

EXPOSE 8010

# Overridden by the worker services in docker-compose. The default is
# the API, because that is what somebody running this image alone
# almost certainly wants.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
