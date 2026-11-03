# LUXish

A wardrobe and styling app. You photograph the clothes you own, and
the app builds outfits from them, shows them on a figure, plans what
you will wear, and puts what other people post on a board you can
actually browse.

An Expo mobile app, a FastAPI service, four job-queue workers and a
small amount of infrastructure, in one repository.

---

## Run it

```bash
./scripts/review.sh
```

That brings up the data stores, the API, every worker, the scheduler
and Metro, seeds a demo world if the database is empty, and then
opens the app — in an Android emulator if this machine has one, and
otherwise as a QR code to scan with Expo Go on a phone.

```bash
./scripts/review.sh doctor   # check the machine, start nothing
./scripts/review.sh stop     # shut down everything it started
```

Sign in with `demo.review@luxish.local` / `ReviewMe!2026`.

**On iOS.** Apple's simulator ships inside Xcode and runs only on
macOS, so there is no local iOS simulator on Windows or Linux — the
script says so rather than pretending. Scanning the QR with Expo Go
on a real iPhone gives you the genuine article, and is a better
review than any simulator.

### What you need first

- Docker, running
- Node 24.3+ or 26 (not an odd-numbered release — Expo SDK 58 excludes them)
- Python 3.12 with a virtualenv at `services/api/.venv`
- `npm install` at the repository root

`./scripts/review.sh doctor` checks all of it and tells you what is
missing.

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

---

## Tests

```bash
cd services/api && python -m pytest tests/ -q     # ~1500 tests
cd apps/mobile  && npx jest                        # ~745 tests
cd apps/mobile  && npx tsc --noEmit && npx expo lint
```

---

## Notes for a reviewer

**Credentials.** Nothing real is committed. `.env.example` files show
the shape; the app runs locally without an AI provider key, with the
model-backed features reporting that they are unavailable rather than
failing quietly.

**Seed imagery.** `assets/seed-photos/` holds reference photographs
used to make the demo feel real. They are for demonstration and are
not licensed for production use.

**What is not finished** is listed honestly in `docs/ROADMAP.md`,
which marks every capability as implemented, planned or blocked, and
says what each blocked one is waiting on. A few features are gated on
third-party credentials this project does not have; the UI says so
rather than showing an empty screen.
