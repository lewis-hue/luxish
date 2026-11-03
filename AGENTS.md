The mobile app carries its own guide as well: [apps/mobile/AGENTS.md](apps/mobile/AGENTS.md).

# Repository guide

Monorepo (ADR-001). Read `docs/architecture/decisions.md` before changing anything —
it records verified vendor facts with URLs and the constraints they impose.

| Path | Owns |
|---|---|
| `apps/mobile` | Expo SDK 58 app (iOS + Android). Its own AGENTS.md applies. |
| `apps/admin` | Restricted operations and moderation console. |
| `services/api` | FastAPI: auth, wardrobe, stylist, shopping, social, billing. |
| `services/workers` | Durable jobs: media, AI, moderation, notifications, reconcile. |
| `packages/contracts` | OpenAPI document and the generated typed client. |
| `infra` | docker-compose for local dev; Terraform for GCP. |
| `docs` | Architecture, ROADMAP, INTEGRATION-MATRIX, runbooks, plans. |

## Non-negotiables

- Brand copy comes from `apps/mobile/branding.config.js`. No user-facing string
  hardcodes a product name.
- Money is `(amount_minor: int, currency)` on an append-only ledger. Never a float.
- A garment ID returned by a model is re-validated against the requesting user's
  wardrobe before it is persisted or rendered.
- No code downloads third-party platform media. Links are stored as references
  with attribution; analysis runs on user-supplied media only.
- Label every capability as implemented, simulated, blocked, or planned. A fixture must
  never read as a live integration.
- **The stylist is reached by asking; the studio is reached by choosing.** These are
  two surfaces and the rule is different on each, deliberately.

  The **stylist** is one input box, and it now lives on the wardrobe page rather than
  a tab of its own - what it reasons about is the clothes already on that screen.
  Everything it can do is routed from the sentence in `app/domain/assistant.py`, on
  the worker. Adding a capability there means adding an intent and a way to say it,
  never a tile.

  The **studio** is the opposite, on the product owner's instruction (2026-11-01).
  Its four treatments are shown as controls, because they *are* the product - the
  thing this competes with is dedicated product-photography tools, and burying a packshot
  behind a sentence means only somebody who already knows the word "packshot" can
  find it. A prompt box sits on top of the four, not instead of them.

  **A brief never goes last in an image-edit prompt.** There is no mask on the
  vendor's edit endpoint, so the clause protecting the source garment is the only
  thing keeping the product the product, and an edit follows its final instruction
  most closely. `app.workers.garment_studio.with_brief` places somebody's own words
  after the treatment and before that clause; the ordering is asserted in
  `tests/test_garment_studio.py`, including against a brief that tries to talk past
  it.
- **Appearance in a generated picture is chosen from a closed vocabulary.** A cast is
  `CAST_OPTIONS` in `app/workers/brand_studio.py`; an unrecognised value is dropped
  rather than passed into a prompt. Nothing reads appearance off a garment, a
  photograph or a request.
- **A clause protecting the source garment goes last in an image-edit prompt.** There
  is no mask on the vendor's edit endpoint, so the wording is the only thing keeping
  the product the product, and an edit follows its final instruction most closely. A
  user's brief goes before it, never after.
- **A description read off a photograph never overwrites an author's caption.** It is
  stored beside it and shown only where they wrote none
  (`fit_descriptions.shown_caption`).
- **The community guidelines are one list, in `app/domain/guidelines.py`.** The screen
  enforces them, the report form offers them, a held item quotes them, and
  `GET /v1/community/guidelines` serves them. Adding a rule means adding it there,
  never writing it into a prompt: prose in a prompt is how the screen ended up
  enforcing one set while the report form offered a different four.
- **A deterministic pre-screen may refuse, never approve.** `obvious_violation` catches
  what cannot be a remark about clothes - a phone number, an email, a link - in
  microseconds and with no model call. It is allowed to miss things. It is not allowed
  to hold something the model would have passed, because a false positive there is a
  refusal nobody can appeal. Everything it has no opinion about still goes to the screen.
- **Free text in front of strangers is screened, and the screen may always refuse.**
  How long it waits depends on what it is:
  - **A fit and a comment publish on write** and are screened on a worker, which can
    take either down within a queue hop and a model call. Nobody waits on a vendor to
    see their own words appear; this is why the post and comment paths look optimistic.
  - **A bio and a profile banner are held until the screen agrees.** They sit on a
    profile indefinitely rather than scrolling past, so the window an optimistic write
    opens is unbounded for them in a way it is not for a remark under a photograph.
  - **An unavailable screen refuses, on every path.** An absent gate is not consent,
    and "the vendor is down" must never read as "publish everything unchecked". A
    comment already published is taken down and its author told why; nobody else is
    told one existed. This is the one part of the optimistic path that is not
    optimistic, deliberately.
  - **`obvious_violation` runs inline everywhere and only ever refuses.** A phone
    number or a link cannot be a remark about clothes, costs microseconds and no model
    call, and is answered before a row exists. It is allowed to miss things. It is not
    allowed to hold what the model would have passed.
- **A direct message is not screened, and that is deliberate.** Everything
  shown to strangers takes the fail-closed path. A message is shown to one
  person who can block its sender in two taps, and `obvious_violation` would
  be actively wrong on it - it refuses phone numbers and links, which is half
  of what somebody arranging to buy a jacket needs to send. The controls are
  the two that were always the condition for shipping messages at all:
  blocking, which is immediate and closes the thread in both directions, and
  reporting, which a person reads.
- **Private is a switch on the profile, never a consent.** `community_sharing`
  is a grant about the shelf of *other people's* looks somebody kept;
  `Profile.private` is about their own fits and the two lists of who they are
  connected to. One control answering both questions would mean neither. It
  gates lists and never counts: a count is not a list, and withholding one
  says only that there is something here worth hiding.
- **A media kind is a boundary, not a label.** `avatar_source` is a photograph of a
  person, `profile_banner` is decoration, `garment_photo` is evidence of what somebody
  owns. Nothing that scans for clothes may pick up the first two, and an id in a
  request is re-validated against both its owner *and* its kind - without the kind
  check, any asset somebody owns could be routed through a prompt meant for another.

## Model calls

**A vision call needs room to think before it can answer.** Reasoning tokens
come out of `max_completion_tokens` *before* any content is emitted, so too
tight a budget returns an empty response rather than a short one. 600 gave
`text: None` on every call and read as a broken endpoint; 2048 is what the
categoriser already used and what works. If a structured-output call comes
back with no text, check the budget before anything else.

**Every adapter call needs an `AIRunRecorder`.** `MetaProvider.complete`
refuses without one, by design: an unaccounted model call is a cost nobody
can attribute. In a script, build the provider per session rather than once,
so the run is written against the session that made it.

**Measure latency through the real path before tuning it.** A comment took
30 seconds to screen in a standalone script and 3 in the app: `install_dispatcher`
runs at API startup, so anything invoked outside the API waits for the 30-second
sweeper instead of being dispatched. A number measured from a script is a number
about the script.

**Deciding what a request means is itself a model call**, so it happens on a
worker and never in a handler (ADR-013). It is also skipped entirely when the
answer is already determined: with nothing attached, no intent other than
styling is possible, so `assistant.classify` returns without asking anybody.
Before adding a classification step, check whether the inputs already settle
it - the first version of this one billed a call on every ordinary
"what should I wear" request.

## Running the stack

**Start it with `./scripts/dev-stack.sh`, never by hand.** It owns the tunnel,
the migrations, the API and all four workers, and it rewires the Keycloak
hostname when the tunnel rotates. Starting pieces individually is how the
stack ends up in a state nobody can reproduce.

**Metro runs from `apps/mobile`, never from the repo root.** The root has no
`App.tsx` and no `expo-router` entry, so a Metro started there serves
`expo/AppEntry.js` and the app dies on
`Unable to resolve module ../../App`. It looks like a broken app and is a
wrong working directory. Always:

```bash
cd apps/mobile && npx expo start --clear
```

**Verify a Metro restart actually took effect.** An orphaned Metro keeps
port 8081, so a "restart" silently starts a second one that never binds and
the phone goes on talking to the stale bundle. Kill every matching process,
then check the served bundle rather than trusting the restart:

```bash
curl -s "http://127.0.0.1:8081/node_modules/expo-router/entry.bundle?platform=ios&dev=true"   | grep -o 'PUBLIC_KEYCLOAK_ISSUER[^,]*'
```

If that prints the old address, Metro did not restart.

**Keycloak is on the LAN address, not a tunnel.** `dev-stack.sh` reads this
machine's IP and pins `http://<ip>:55080` into the three files that carry it
— `apps/mobile/.env`, `services/api/.env`, `infra/.env` — restarting Keycloak
and the API when it changes. All three must agree or sign-in breaks with no
error that names the cause.

It used to be a Cloudflare quick tunnel, and that was the bug: the hostname
is random on every start and the edge expires it after a few hours, so
sign-in broke repeatedly. A LAN address does not rotate. Email-and-password
sign-in needs no TLS — PKCE with an `exp://` redirect is fine over http on a
trusted network.

**The tunnel is opt-in, for one reason:** Google will not register a
non-https redirect URI unless the host is localhost, and a phone is not
localhost. Use `LUXISH_TUNNEL=1 ./scripts/dev-stack.sh` when testing Google
sign-in; the script then manages the tunnel, checks it by *making a request*
rather than by counting processes, and replaces it when the edge has dropped
it. Either way, a changed address still needs Metro restarted by hand,
because `EXPO_PUBLIC_*` is bundled at build time.

The dev realm's `luxish-mobile` client carries wildcard redirect URIs
(`exp://*:*/--/callback`, `luxish://*`, `http://localhost:*/*`) so a new IP
or Expo port cannot invalidate the callback. Dev only — a wildcard redirect
on a public client is an open redirector in production.

**Never delete a bundled asset while Metro is running.** Metro resolves
`require('@/assets/...')` at bundle time and caches the failure, so a file
that is missing for even a second takes the app down with
`Unable to resolve module` and stays down until Metro restarts. Regenerate
images in place or stop Metro first — do not delete-then-write. The guard is
`src/features/discover/__tests__/imagery-assets.test.ts`, which stats every
referenced file; typecheck and lint cannot see this.

**After changing a route or a schema: restart the API before regenerating the
contract.** `get_settings` and the token verifier are `lru_cache`d, so a
running process serves the old spec and the old issuer. The order is restart
→ `node scripts/fetch-spec.mjs` → `npm run generate`.
