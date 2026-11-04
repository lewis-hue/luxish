# LUXish

A wardrobe and styling app. You photograph the clothes you own, and
the app builds outfits from them, shows them on a figure, plans what
you will wear, and puts what other people post on a board you can
actually browse.

An Expo mobile app, a FastAPI service, four job-queue workers and a
small amount of infrastructure, in one repository.

---

## Run it on your phone

Three commands, then scan a QR code. The whole stack runs on your
machine; the app runs on your handset.

```bash
git clone https://github.com/lewis-hue/luxish.git
cd luxish
npm install
./scripts/review.sh
```

The script builds the backend image, brings up Postgres, Redis,
Keycloak, the API, four workers, the scheduler and Metro, seeds a
demo world if the database is empty, and then prints a QR code.

**The first run takes a few minutes** while Docker builds the
backend image. Later runs start in seconds.

**On your phone**, install Expo Go:

- iPhone — [apps.apple.com/app/expo-go](https://apps.apple.com/app/expo-go)
- Android — [play.google.com/store/apps/details?id=host.exp.exponent](https://play.google.com/store/apps/details?id=host.exp.exponent)

Open it and scan the QR code from your terminal. On iPhone you can
also scan with the Camera app. The bundle takes a few seconds to
build the first time.

**Sign in with:**

```
me@luxish.local
admin123
```

That account is created by the Keycloak realm import, so it exists
on a fresh clone before you run anything.

> **Your phone and your computer must be on the same Wi-Fi.** The QR
> points at your machine's LAN address. A corporate or guest network
> that isolates clients will block it; a phone hotspot that the
> laptop joins works fine.

When you are done:

```bash
./scripts/review.sh stop
```

### What you need installed first

| | Why |
|---|---|
| **Docker Desktop**, running | Postgres, Redis, Keycloak, the API and the workers |
| **Node 22.13+** | Metro, which has to run on the host so your phone can reach it |
| **A POSIX shell** | `review.sh` is a shell script. macOS and Linux already have one; on Windows use **Git Bash**, which comes with [Git for Windows](https://git-scm.com/download/win), or WSL |

That is the whole list. **Python is not required** — the API and all
four workers run in containers built from
`services/api/Dockerfile`.

On Windows, run the commands in a Git Bash window rather than
PowerShell or `cmd`. In PowerShell `./scripts/review.sh` fails with
"not recognized", which looks like a missing file and is only a
missing interpreter.

Check the machine without starting anything:

```bash
./scripts/review.sh doctor
```

It reports what is missing and how to fix it, and refuses to start a
half-working stack rather than leaving you to diagnose one.

### Working on the API itself

The backend runs in Docker by default. If you want it as a local
process instead — for a debugger, or an editable install — set one
variable:

```bash
python -m venv services/api/.venv
services/api/.venv/bin/pip install -e "services/api[dev]"   # Windows: services/api/.venv/Scripts/pip
LUXISH_LOCAL_BACKEND=1 ./scripts/review.sh
```

Everything else is identical. The seeders follow the backend, so
they always write to the database the API is actually serving.

### If you would rather use an emulator

```bash
./scripts/review.sh up --android
```

Boots an Android emulator alongside the QR, if the Android SDK and a
virtual device are installed.

There is **no iOS simulator option, and that is a platform fact
rather than an omission.** Apple's simulator ships only inside Xcode
and runs only on macOS. On Windows or Linux the honest choices are a
real iPhone with Expo Go, an Android emulator, or a hosted Mac.

### When something is wrong

| Symptom | Cause |
|---|---|
| QR does not render | `npm install` at the repo root, then run the script again |
| Expo Go cannot reach the URL | Phone and laptop are on different networks |
| App opens but is empty | The seed check failed. See `.devlogs/seed.log` |
| Sign-in page never loads | Keycloak is still starting. Wait, then reload |
| A fix you just made has not appeared | Rebuild the image: `docker compose -f infra/docker-compose.yml up -d --build api` |
| Want to see backend logs | `docker compose -f infra/docker-compose.yml logs -f api` |

Every service logs to `.devlogs/`. Start there.

---

## What is in here

| Path | Owns |
|---|---|
| `apps/mobile` | The Expo app, iOS and Android |
| `services/api` | FastAPI: auth, wardrobe, stylist, discovery, shopping, social, billing |
| `services/workers` | Durable jobs: media, AI, moderation, notifications |
| `packages/contracts` | The OpenAPI document and the generated typed client |
| `infra` | docker-compose for local work; Terraform for a deployment |
| `docs` | Architecture decisions, roadmap, integration matrix, runbooks |

### The parts worth looking at

**Discovery** (`services/api/app/domain/discovery/`) is a staged
recommender rather than one ranked query: a random walk over the
graph of which pins people have put on which boards, tag affinity,
trending measured as acceleration rather than volume, and a slice
reserved for pins nobody has seen yet — blended to a target mix and
filtered against what you have already been shown. Its README
records what is implemented and what is deliberately not.

**The stylist** (`app/domain/stylist_ask.py`) answers in words before
it makes anything. It streams a reply, decides from the same model
call whether you own something that works, and only then acts: your
own clothes on a figure, or the gaps and where to buy them.

**Reading pictures** (`app/domain/discovery/subject.py`) is how the
app avoids trusting a caption. A hashtag is a claim typed once by
one person; what the vision model sees in the photograph is not.

**Packshots** (`app/workers/packshot.py`) turn a phone photograph of
a garment into a catalogue shot. Background removal is segmentation,
so on a dark garment it returns a silhouette; this re-stages the
owner's own photograph the way a shop photographs stock, and the
result is reused by the wardrobe tile, the try-on and the stylist.

**Spending deliberately.** Model work is queued, never run in a
request handler, and the expensive version is opt-in. The stylist
composites a look from cut-outs the device already holds — instant
and free — and only buys a photoreal render when somebody asks to
see one. Pictures of garments nobody owns are drawn once per phrase
and shared by every account.

**Waiting is escapable.** A render takes nine to forty seconds, and
one is drawn per person at a time so a second tap cannot pay twice.
That pairing used to mean a picture could not be called off: the
progress card sat over the avatar, and asking again returned the
render already going. The card now carries a Stop, which finishes the
row so the next request starts fresh, and the worker re-reads the row
after drawing so a picture somebody stopped is never the one that
lands (`app/domain/avatar_renders.py`, `app/workers/avatar_jobs.py`).

---

## Tests

```bash
npm test                  # the Expo app  — 778 tests
npm run api:test          # the API       — 1684 tests
npm run typecheck
npm run lint
```

Both suites run offline. No test calls a paid model or the open web;
providers are stubbed at the seam so a suite run costs nothing and
is deterministic.

`api:test` needs no Python either. It uses a local `pytest` when the
machine has one and otherwise builds the `dev` target of
`services/api/Dockerfile` and runs the suite in a throwaway
container. Arguments pass through, so `npm run api:test -- -k taste`
works on both routes. The suite does not talk to a running stack: it
builds its own database, which is why it can run before you have
started anything.

---

## Notes for a reviewer

**The demo world is seeded, not faked.** The repository ships 406
photographs - 106 shot for the seed and 300 generated - which the
seeder turns into published pins across dozens of accounts, with
captions, tags and a follow graph, dated over three weeks so
trending has a baseline to measure against rather than a flat line.
Discover, Search and the boards are populated from the first
launch.

**Your follow graph is empty until you sign in.** Followers and
following live on your profile, behind the counts. The API keys an
account on the identity provider's subject and deliberately refuses
to adopt an existing row by email, so your account does not exist
until you first sign in and nothing can be wired to it before then.
Run `./scripts/review.sh` again afterwards and it will put you in
the graph.

**AI features need a key.** `LUXISH_META_API_KEY` in
`services/api/.env` enables the stylist, try-on, packshots and
visual search. Without it those features report that they are
unavailable rather than failing silently — everything else works.

**What is not finished** is listed in `docs/ROADMAP.md`, and the
capacity model in `docs/performance/capacity.md` says plainly which
of its numbers are measured and which are arithmetic.

---

## Licence

Copyright 2026 Lewis Muguna. All rights reserved.

This repository is public so it can be read, cloned and run for
evaluation. That is not a licence to reuse it. See [LICENSE](LICENSE).

Dependencies keep their own licences.
