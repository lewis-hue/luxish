# Local development

Working name **LUXish**. Repository layout and decisions: [`../architecture/`](../architecture/).

---

## Prerequisites

| Tool | Version | Why this version |
|---|---|---|
| **Node** | **24.3+ LTS, or 26** | React Native 0.88 / Expo SDK 58 require 22.13+, 24.3+ or 26+ and **exclude odd-numbered releases**. Node 25 is unsupported and produces an `EBADENGINE` warning (ADR-014). |
| Python | 3.12 | `services/api` pins `>=3.12,<3.13`. |
| Docker | any current | For Postgres, Redis and Keycloak. |
| Expo account | — | Needed for `eas build`. No Xcode or Android Studio required. |

A `.nvmrc` pins Node; run `nvm use` in the repository root.

> **If you are on Windows**, iOS builds are only possible through EAS Build — Xcode is
> macOS-only. `npx expo prebuild --platform ios` works (it only writes files), but
> compiling does not.

---

## First run

```bash
npm install                 # workspace root — hoists for apps/mobile and packages/*
npm run dev:up              # postgres :55432, redis :55379, keycloak :55080
```

Ports are deliberately in the 55xxx range so this stack cannot collide with another
project's services on the standard ports.

### Backend

The API has its own virtualenv. On this machine that is not optional: the ambient
Python has editable installs from unrelated projects that register a meta-path finder
for a package named `app`, which shadows `services/api/app` regardless of `sys.path`.

```bash
cd services/api
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]'      # Windows
# .venv/bin/python -m pip install -e '.[dev]'        # macOS / Linux

.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python scripts/seed.py          # 9 regional profiles; idempotent
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8010
```

Open http://localhost:8010/docs for the generated OpenAPI UI. **Port 8010, not
8000** — 8000 is commonly already taken, and the failure is a bind error after the
app has already logged "Application startup complete", which reads as a crash.

Verify it: `/healthz` returns 200 unauthenticated, and `/v1/regional/context`
returns a structured 401 with a `code` and `request_id`. The second is the
*correct* response without a token, not a failure.

### Mobile

```bash
npm run mobile              # Expo dev server
```

Expo Go covers the universal `@expo/ui` components, but **a development build is
required** for camera, secure storage, push notifications and in-app purchases —
Expo Go only bundles its own native modules.

```bash
npx eas-cli@latest build --profile development --platform android
npx eas-cli@latest build --profile development --platform ios
```

---

## Environment

Nothing in the repository holds a credential. Copy the example and fill in what you
have; every integration degrades to a labelled unavailable state rather than failing.

```bash
cp .env.example services/api/.env    # then prefix every backend var with LUXISH_
cp .env.example apps/mobile/.env     # only EXPO_PUBLIC_* matters here
```

**The backend reads `services/api/.env`, not the repository root, and its Settings
use `env_prefix = "LUXISH_"`.** So the variable is `LUXISH_DATABASE_URL`, not
`DATABASE_URL`. Getting this wrong presents as a pydantic "Field required" error
listing variables you believe you have already set.

| Variable | Needed for | Without it |
|---|---|---|
| `LUXISH_DATABASE_URL` | everything | API will not start |
| `LUXISH_REDIS_URL` | rate limits, usage reservation | API will not start |
| `LUXISH_META_API_KEY` | the stylist, segmentation, lookbooks | Stylist reports `blocked`; nothing is simulated |
| `LUXISH_GCS_BUCKET` | real uploads | Upload authorization reports `storage_mode: simulated` |
| `LUXISH_KEYCLOAK_ISSUER` | sign-in | Protected routes reject every token |
| `LUXISH_KEYCLOAK_CLIENT_ID` | token `azp` check | API will not start |
| `GOOGLE_CLIENT_ID` / `_SECRET` | Google sign-in (read by Keycloak, unprefixed) | Button appears but cannot complete |
| `EXPO_PUBLIC_API_BASE_URL` | the app reaching the API | Falls back to 10.0.2.2 (Android) or 127.0.0.1 |

Meta keys are prefixed `LLM_`. Get one self-serve at https://dev.meta.ai/api-keys —
note that **rate limits are per team, not per key**, so a second key buys no headroom.

---

## Verification

Run all of this before claiming a change works.

```bash
# Mobile
npm run typecheck                      # tsc --noEmit
npm run lint                           # expo lint
npm run test                           # jest
cd apps/mobile && npx expo-doctor      # dependency and config health

# API
cd services/api
.venv/Scripts/python -m pytest -q                      # unit suite, SQLite-backed
.venv/Scripts/python -m ruff check app tests alembic

# Cross-cutting: Keycloak realm security controls
services/api/.venv/Scripts/python -m pytest tests -q

# Capacity model
python scripts/capacity_model.py
python scripts/check_no_committed_secrets.py
```

### The two tests that do not run locally

```bash
LUXISH_TEST_PG_URL=postgresql+asyncpg://luxish:luxish@localhost:55432/luxish \
  .venv/Scripts/python -m pytest -m postgres
```

These cover native enums, JSONB, and real `SELECT … FOR UPDATE SKIP LOCKED`
concurrency — none of which SQLite can exercise. They are excluded by default and run
in CI. **On this machine they have never run** — see *Containers never start* below.
Treat the job-queue concurrency guarantee as **unverified locally** until CI runs or
Docker is repaired.

---

## Migrations

```bash
cd services/api
.venv/Scripts/python -m alembic revision -m "what it does"   # hand-write it
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic downgrade -1                 # must work
```

Every migration must reverse cleanly — CI runs up, down, then up again. A migration
that cannot be rolled back cannot be deployed safely. The chain is currently
`0001_core → 0002_wardrobe → 0003_jobs → 0004_ai → 0006_regional → 0007_external`;
`0005` is reserved for the stylist task and intentionally unused. It must stay linear
with a single head — three revisions sharing a parent produces
`CommandError: Multiple head revisions`.

---

## Keycloak

Admin console at http://localhost:55080 (`admin` / `admin`). The realm imports from
`infra/keycloak/import/luxish-realm.json` on first start only — **if the realm
already exists the import is skipped**, deliberately, so restarts do not wipe state.
To re-apply realm changes, delete the realm through the Admin API and restart.

Two fields in that file are security controls, not configuration preferences:
`trustEmail: false` and `firstBrokerLoginFlowAlias: "first broker login"`. Read
[`../../infra/keycloak/README.md`](../../infra/keycloak/README.md) before touching
either; both are pinned by tests in `tests/test_keycloak_realm.py`.

Discovery: `http://localhost:55080/realms/luxish/.well-known/openid-configuration`
(note: **no `/auth` prefix** — removed in Keycloak 17).
Readiness lives on the **management port**: `http://localhost:55000/health/ready`.

---

## Troubleshooting

**`EBADENGINE` on install** — Node is on an unsupported version. See the table above;
use 24.3+ LTS.

**`ModuleNotFoundError: app`, or the wrong `app` is imported** — you are not in the
service's virtualenv. See the note under *Backend*.

**Expo Go crashes on a screen using camera or secure storage** — expected. Those need
a development build.

**Keycloak returns 403 on proxied requests** — `proxy-headers` is unset. Only affects
non-local deployments; see the production notes in the Keycloak README.

**A realm change appears to do nothing** — the realm already existed, so the import
was skipped. Delete it and restart.

**Containers never start** — observed on the authoring machine on 2026-10-27, and
not fixed by restarting Docker Desktop. The daemon answers `docker version`,
`docker ps` and `docker images` instantly, and image pulls succeed, but every new
container stays in `Created` and never reaches `Running` — including
`docker run hello-world`. Existing containers report `Up` while their published
ports refuse connections. `docker info` showed 258 accumulated containers.

What to try, in order: `wsl --shutdown`, restart Docker Desktop, then
`docker container prune`. If it persists, Docker Desktop → Troubleshoot → Reset to
factory defaults. WSL itself was healthy (`wsl -l -v` showed both distributions
Running), so this is Docker Desktop's container runtime rather than WSL.

**Nothing in the repository depends on Docker to develop.** The unit suites need no
server, and the API runs against SQLite — set
`LUXISH_DATABASE_URL=sqlite+aiosqlite:///C:/tmp/luxish_dev.sqlite3`. What you lose
is Keycloak (so no real sign-in, and no authenticated endpoint can be exercised by
hand) and the two Postgres-only tests.

---

## What is not wired yet

Stated here so nobody hunts for it:

- **Authenticated screens** cannot be exercised by hand without Keycloak, which
  needs Docker. The typed client, the queries and the error states are all in place
  and tested; what is missing is a token. Profile shows backend reachability, which
  works unauthenticated.
- **`apps/admin`** is empty (Phase C).
- **`infra/terraform`** is empty. Local development does not need it; deployment does.
- **`tests/load/locustfile.py`** does not exist, so no figure in
  [`../performance/capacity.md`](../performance/capacity.md) is a measurement.
- **GCS signed uploads** raise `CapabilityUnavailable` and report
  `storage_mode: "simulated"`. Derivative generation is likewise absent — the media
  worker only persists, behind the deletion guard.
