# Demonstration script

What can actually be shown, in order, with the state of each step stated before it is
shown. Status date 2026-10-27.

**The rule for this document:** every step is marked `WORKS`, `WORKS WITH KEY`,
`BLOCKED`, or `NOT BUILT`. A demo that quietly skips the blocked parts is how a
reviewer forms a false impression, so the blocked parts are listed in place rather
than omitted.

---

## Before you start

```bash
nvm use                      # Node 24 — 25 is unsupported (ADR-014)
npm install
npm run dev:up               # postgres, redis, keycloak
cd services/api && .venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
npm run mobile               # separate terminal
```

Set `MODEL_API_KEY` (self-serve at https://dev.meta.ai/api-keys) to unlock the
stylist. Everything else runs without any credential.

---

## 1. The app opens and the design system is real — `WORKS`

Launch on a device or simulator. Five native destinations: Discover, Wardrobe,
Stylist, Community, Profile — a real platform tab bar, not a drawn one.

**Point out:** switch the device between light and dark. The palette is warm neutral
with a single burgundy accent, and every pair is contrast-asserted at WCAG AA by a
test, so this is a checked property rather than a designer's intention.

**Then turn on Reduce Motion** in system settings and reopen. Durations collapse to
zero rather than being merely shortened.

```bash
npm run test -w @fashion/mobile    # 39 passing, including the contrast assertions
```

## 2. Discover — `WORKS`

Twelve style collections: streetwear through to heritage and print, plus
regionally-relevant ones (warm weather, rainy season, modest). Filter by formality.

**Be straight about the covers.** They are typographic, not photographic, because
licensing is unresolved — and that is a deliberate decision, not an unfinished one.
Unsplash and Pexels both *prohibit* an app whose content is their library, and
Unsplash additionally mandates hotlinking as a material-breach term. See
[architecture/image-sourcing.md](architecture/image-sourcing.md). The grid is
complete and usable today, and gains photography when a licensed source is wired.

**Worth showing in the code:** `InspirationAsset` cannot be constructed without a
`SourceRecord`, so an unattributed image cannot reach the grid, and the record
carries `hotlinkOnly` for providers that forbid re-hosting.

## 3. A social link, answered honestly — `WORKS`

Profile → or share a post into the app from Instagram. Paste
`https://www.instagram.com/p/ABC123/`.

The screen names the platform and says what we may actually do: save the link, open
the original — and that garment identification is **not** available, with the reason
and the path that does work (add a screenshot or your own photo).

**This is the point to make deliberately.** A pasted link is enough to make the flow
work, which is what was asked for. What a public URL does not convey is permission to
download and analyse the media behind it, so each platform reports six independent
capability booleans and the UI never implies more. A backend test greps the whole
service for platform-CDN, oEmbed and downloader markers to assert no module fetches
platform media.

Try `https://evil-instagram.com/p/x/` too — host matching is on a label boundary, so
it does not pass as Instagram.

## 4. Uploads survive a dropped network — `WORKS`

```bash
npm run test -w @fashion/mobile -- src/storage
```

16 tests. The one that matters: an upload interrupted mid-transfer and retried
replays **one** idempotency key, so the server collapses the attempts into a single
garment. The key is minted at enqueue and persisted before the first attempt — a key
minted per attempt would duplicate on exactly this case.

Also demonstrated there: two concurrent drains never upload the same item twice
(tested against real SQL, not a fake), a missing local file fails terminally rather
than burning six retries, and an uploaded item can never be cancelled.

## 5. Sign-in — `WORKS WITH KEY`

Keycloak at http://localhost:55080, realm `luxish`, Google brokered.

Google sign-in needs `GOOGLE_CLIENT_ID` / `_SECRET`; without them the button appears
and cannot complete, which is the honest state rather than a hidden one.

**What to show regardless of credentials:**

```bash
services/api/.venv/Scripts/python -m pytest tests -q            # 16 realm invariants
cd services/api && .venv/Scripts/python -m pytest tests/test_auth.py -q
```

The account-takeover invariant is enforced twice, deliberately. In the realm:
`trustEmail: false` and the stock `first broker login` flow — swapping in
`idp-auto-link` would adopt an existing account without verification. And in the API:
a token with `email_verified: false` never adopts a pre-existing account, returning
`409 identity_link_required`. Even a *verified* email requires the owner to
authenticate a link challenge. The redundancy is because realm config can be changed
in a console without a code review.

Also show that algorithm confusion is refused *before* a key is loaded, and that the
verifier will not even accept being configured with a symmetric algorithm.

## 6. Wardrobe corrections outrank the model — `WORKS WITH KEY`

```bash
cd services/api && .venv/Scripts/python -m pytest tests/test_wardrobe.py -q
```

`Garment` keeps `confirmed_attributes` separate from `inferred_attributes` with a
confidence score, and `effective_attributes` resolves per key with the user winning.
The test applies a *later, higher-confidence* model inference after a user
correction and asserts the correction survives.

Then: another user's garment returns **404, not 403** — a missing id and a stranger's
id are indistinguishable, so existence is never confirmed.

## 7. A delete cannot be undone by a late job — `WORKS`

```bash
cd services/api && .venv/Scripts/python -m pytest tests/test_tombstone.py -q
```

Delete an asset while a media job is in flight; the worker's write raises `AssetGone`
and leaves zero derivatives. `guard_write` re-checks ownership, tombstone,
publication consent and asset version **inside the same transaction as the write** —
checking at job start would be too early, because deletion can land mid-job.

## 8. The stylist — `BLOCKED` without a Meta key

With `MODEL_API_KEY` set this is the centrepiece: a garment photo anchors a complete
outfit from owned, available clothes, with regional and weather context, and a
tool-driven revision when an item becomes unavailable.

Without the key the Stylist tab says **"Styling needs an AI key"** and explains that
nothing is simulated in its place. That wording is deliberate: the agent loop,
prompts, tool contracts and provider adapter exist, so "not built yet" would be
inaccurate — and a fake outfit would be worse than an honest gap.

**Show in the code either way:** every garment id the model returns is re-validated
against the requesting user's current wardrobe at one chokepoint before anything is
persisted or rendered, and an imported caption cannot authorise a tool call.

## 9. What the numbers say — `WORKS`

```bash
python scripts/capacity_model.py
```

Two ceilings arrive before infrastructure does. Meta's token limit is **per team, not
per key**, and the scale-target scenario needs 4.19M tokens/minute at *average* load
against a 4M limit. And a stylist run costs 4.6¢, so an unmetered free tier is $0.56
per daily user per month — which is why the capped allowance is required by the
economics rather than chosen.

**Say this plainly:** none of those figures is a measurement. No load profile has
been written. The script exists because writing the tables by hand applied the peak
factor twice and produced a wrong conclusion.

---

## Not built — say so if asked

| Area | State |
|---|---|
| Community feed, posts, creator profiles | `NOT BUILT` — Phase C. Moderation has to ship with it, not after. |
| Subscriptions, gifts, creator payouts | `NOT BUILT` — Phase D. The payout provider's Kenya support is unverified and is the blocker. |
| Sign in with ChatGPT | `BLOCKED` — commercial access is waitlist-gated. Ships `unavailable`. Note it could never carry image generation anyway. |
| Visual similarity search | `BLOCKED` — Meta publishes no embeddings endpoint (ADR-004). Attribute retrieval does not provide it, and the UI does not imply it does. |
| Live product search | `NOT BUILT` as live — the shopping interface is real, the Phase B provider is a labelled fixture. Affiliate networks require per-advertiser approval. |
| Real uploads to cloud storage | `BLOCKED` — signed-URL authorization raises `CapabilityUnavailable` and reports `storage_mode: "simulated"`. |
| Typed API client | `NOT BUILT` — `packages/contracts` is empty, so no screen makes a live API call yet. |
| Job-queue concurrency under real Postgres | `UNVERIFIED` locally — `docker run` hangs on the authoring machine. The two tests covering `SKIP LOCKED` run in CI only. |
| Terraform | `UNVALIDATED` — no terraform CLI on the authoring machine; CI validates it. |

---

## One thing not to claim

There is no production build, no TestFlight or Play upload, and no live payment of any
kind. A gift animation, if one is ever shown, is an animation. The brief is explicit
about this and it is worth being the one to say it before anyone asks.
