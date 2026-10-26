# Local development

Working name **Atelier**. Repository layout and decisions: [`../architecture/`](../architecture/).

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
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the generated OpenAPI UI.

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
cp .env.example .env
```

| Variable | Needed for | Without it |
|---|---|---|
| `DATABASE_URL` | everything | API will not start |
| `REDIS_URL` | rate limits, usage reservation | API will not start |
| `MODEL_API_KEY` | the stylist, segmentation, lookbooks | Stylist reports `blocked`; nothing is simulated |
| `KEYCLOAK_ISSUER` | sign-in | Protected routes reject every token |
| `GOOGLE_CLIENT_ID` / `_SECRET` | Google sign-in | Button appears but cannot complete |
| `GCS_BUCKET` | real uploads | Upload authorization reports `storage_mode: simulated` |

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
ATELIER_TEST_PG_URL=postgresql+asyncpg://atelier:atelier@localhost:55432/atelier \
  .venv/Scripts/python -m pytest -m postgres
```

These cover native enums, JSONB, and real `SELECT … FOR UPDATE SKIP LOCKED`
concurrency — none of which SQLite can exercise. They are excluded by default and run
in CI. **On this machine they have never run:** `docker run` hangs indefinitely even
though the daemon answers `docker version` and `docker ps`, so no Postgres container
could be started. Treat the job-queue concurrency guarantee as **unverified locally**
until CI runs or Docker is repaired.

---

## Migrations

```bash
cd services/api
.venv/Scripts/python -m alembic revision -m "what it does"   # hand-write it
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic downgrade -1                 # must work
```

Every migration must reverse cleanly — CI runs up, down, then up again. A migration
that cannot be rolled back cannot be deployed safely. Numbers 0004–0006 are reserved
for the AI, stylist and regional tasks so the chain stays readable.

---

## Keycloak

Admin console at http://localhost:55080 (`admin` / `admin`). The realm imports from
`infra/keycloak/import/atelier-realm.json` on first start only — **if the realm
already exists the import is skipped**, deliberately, so restarts do not wipe state.
To re-apply realm changes, delete the realm through the Admin API and restart.

Two fields in that file are security controls, not configuration preferences:
`trustEmail: false` and `firstBrokerLoginFlowAlias: "first broker login"`. Read
[`../../infra/keycloak/README.md`](../../infra/keycloak/README.md) before touching
either; both are pinned by tests in `tests/test_keycloak_realm.py`.

Discovery: `http://localhost:55080/realms/atelier/.well-known/openid-configuration`
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

**`docker compose up` hangs** — known on this machine. The daemon responds to
`version` and `ps` but hangs on `run`/`start`. Nothing in the repository works around
it; the unit suites deliberately need no server so development continues regardless.

---

## What is not wired yet

Stated here so nobody hunts for it:

- **`packages/contracts`** is empty. The typed client is generated from the API's
  OpenAPI document; the generator is not yet configured, so the mobile app has no
  live API calls and every screen renders from local data or a labelled empty state.
- **`apps/admin`** is empty (Phase C).
- **`infra/terraform`** is empty. Local development does not need it; deployment does.
- **`tests/load/locustfile.py`** does not exist, so no figure in
  [`../performance/capacity.md`](../performance/capacity.md) is a measurement.
- **GCS signed uploads** raise `CapabilityUnavailable` and report
  `storage_mode: "simulated"`. Derivative generation is likewise absent — the media
  worker only persists, behind the deletion guard.
