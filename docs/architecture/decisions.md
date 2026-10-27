# Decision Record

Companion to [README.md](./README.md). Status date 2026-10-26.

Every claim is labelled. **Verified** = fetched from the vendor's live docs on
2026-10-26, URL recorded. **Assumed** = a default we chose, not yet measured.
**Blocked** = needs a credential or approval we do not hold.

---

## ADR-001: Monorepo with npm workspaces, mobile app at `apps/mobile`

**Decision.** Restructure the SDK 58 scaffold into `apps/mobile`, `services/api`,
`services/workers`, `packages/contracts`, `apps/admin`, `infra/`, `docs/`, `tests/`.

**Why.** §2 requires this separation. Doing it at 20 source files costs one commit;
doing it after Phase B costs a week of import churn.

**Cost.** Python services are not npm workspace members. They are driven from root
`package.json` scripts and own their `pyproject.toml`.

---

## ADR-002: Centralised, configurable branding

**Decision.** One module — `apps/mobile/src/branding/index.ts` — owns display name,
tagline, legal entity, support URLs and store identifiers. No user-facing string
hardcodes a product name. Working name **LUXish**; package scope stays `@fashion/*`.

**Why.** The brand is not final. Separating package identity from brand identity makes
the eventual rename a one-file diff instead of a dependency-graph migration.

---

## ADR-003: Modular API plus independently scalable workers, not microservices

**Decision.** One FastAPI deployable with per-domain routers; a separate worker
deployable per queue class (media, ai, moderation, notifications, reconciliation).
Domain modules never import each other's internals — only shared contracts.

**Why.** §2 asks for exactly this, with boundaries drawn so high-volume parts can be
separated later. Measured evidence, not anticipation, triggers a split.

---

## ADR-004: Defer pgvector — the Meta Model API has no embeddings

**Decision.** Phase B wardrobe retrieval is deterministic SQL over confirmed and
inferred garment attributes (category, colour family, formality, season suitability,
availability), not vector similarity. `pgvector` and an embedding provider are deferred
behind a measured trigger.

**Why.** **Verified**: the Meta Model API publishes no embeddings model and no
embeddings endpoint (`https://dev.meta.ai/docs/models`,
`https://dev.meta.ai/docs/api-reference`). Introducing vectors now means introducing a
*second* paid provider purely for embeddings, before any evidence that attribute filters
are insufficient. §2 already scopes pgvector to "where measured retrieval needs justify
it". A wardrobe holds hundreds of items, not millions; an indexed attribute query is
cheaper, faster and explainable to the user.

**Trigger to revisit.** Recall@10 below 0.8 on the wardrobe-retrieval eval set, or
visual "find similar" being committed as a shipping feature. Candidates at that point:
Vertex AI multimodal embeddings, or a self-hosted open model. Both need a cost review.

**Consequence — stated plainly.** Visual similarity search (§12 "supported visual
query"; §9 "find similar or confirmed products from an inspiration image") is **not**
delivered by attribute retrieval. It is tracked as blocked-on-embeddings and the UI must
not imply it works.

---

## ADR-005: Garment segmentation uses `sam-3.1`

**Decision.** "Select a garment inside this image" (§5, §11, §12) is served by Meta's
`sam-3.1` — text-prompted boxes and masks over an image or a video frame.

**Why.** **Verified**: `sam-3.1` accepts "Text prompt, image, video" and returns "Boxes
and masks", priced at $2.50/1,000 images and $0.20/1,000 video frames
(`https://dev.meta.ai/docs/models`, `https://dev.meta.ai/docs/pricing-rate-limits`).
This removes the largest piece of custom perception work from the critical path.

**Cost control.** Segmentation is a worker job, never a request-path call, and is
charged against the requesting user's AI allowance.

---

## ADR-006: Adapters declare capabilities; the router never guesses

**Decision.** Every adapter publishes a `ProviderCapabilities` record — text, image-in,
image-out, video-in, audio-in, tools, structured output, streaming, embeddings — plus
limits and unit price. The router selects on declared capability + entitlement + consent
+ billing source. A request for an unsupported modality fails before any network call.

**Why.** §8, and forced by two verified asymmetries: Meta has image generation but no
embeddings; the ChatGPT-plan route has neither image generation nor file/audio upload. A
router assuming parity would fail silently and bill for it.

---

## ADR-007: The Meta adapter whitelists request parameters

**Decision.** The Meta adapter builds requests from an explicit allowlist and drops
`stop`, `n`, `verbosity`, `logit_bias`, `prediction`, `web_search_options`, `modalities`,
`audio`, `logprobs`, `top_logprobs`. It sends `max_completion_tokens`, never
`max_tokens`.

**Why.** **Verified**: those fields return HTTP 400, even though Meta's published OpenAPI
schema still lists several of them — the prose page is authoritative
(`https://dev.meta.ai/docs/protocols/chat-completions`). `max_tokens` is deprecated in
favour of `max_completion_tokens`. We call it through the `openai` SDK with
`base_url="https://api.meta.ai/v1"`; there is no first-party Meta SDK
(`https://dev.meta.ai/docs/sdks`).

**Also verified and encoded.** Auth is a static API key as
`Authorization: Bearer $MODEL_API_KEY` (keys are prefixed `LLM_`). Rate limits apply
**per team, not per API key** — so our global concurrency limiter is team-wide, not
key-wide. `reasoning_effort` accepts `none|minimal|low|medium|high|xhigh|max`. Strict
structured output requires a root object with `additionalProperties: false`.

---

## ADR-008: ChatGPT identity and ChatGPT-plan inference are separate state machines

**Decision.** Two independent records: an identity link, and an inference entitlement.
The app ships with inference `unavailable`. Image generation is **never** routed to the
ChatGPT-plan path, in any state.

**Why.** **Verified** at `https://developers.openai.com/siwc/quickstart`,
`https://developers.openai.com/siwc/token-sharing-open-source` and its subpages, and
`https://learn.chatgpt.com/docs/sign-in-with-chatgpt`:

- "Signing in and using your plan are **separate permissions**."
- Plan usage requires scopes `offline_access resource.invoke
  chatgpt.tokens.use.direct`, and "A valid ID token alone does not authorize ChatGPT
  plan usage."
- Commercial access is waitlisted ("currently offered to a select group of commercial
  partners"). The self-service token-sharing path is scoped to open-source / locally
  hosted apps; "paid or remotely hosted" apps are routed to an interest form.
- **Unsupported on the plan route**: image generation, file search, Code Interpreter,
  the Files upload API, audio/video input. Inference is `POST
  https://api.openai.com/v1/responses` with `store:false` and `stream:true` mandatory.
- Only **Plus and Pro** are named eligible. Free / Business / Enterprise: not stated.
- There is **no allowance-remaining API**. Exhaustion is observable only as
  `subscription_sharing_usage_limit_exceeded` (429), which can also arrive *mid-stream*
  as a `response.failed` event.
- OpenAI "does not currently notify your tool when a user disconnects the app in
  ChatGPT settings" — there is no revocation webhook.
- PKCE S256 is required; endpoints are `https://auth.openai.com/api/accounts/authorize`,
  `/api/accounts/oauth/token`, `/api/accounts/oauth/revoke`.

**Consequence.** The eligibility state machine is driven by error codes, not polling.
`allowance_exhausted` is entered from a 429, including a mid-stream one.
`revoked` is entered when a request or refresh confirms disconnection — never from a
transient network failure.

**Mobile redirect.** **Verified as not stated**: the SIWC docs contain no native-mobile
guidance; custom URI schemes are neither permitted nor forbidden, and the documented OSS
flow requires a `127.0.0.1` loopback that a sandboxed mobile app cannot host. We
therefore do the code exchange **on our backend** against a registered `https://`
callback and hand our own session to the app — the documented website shape — rather
than inventing a native redirect.

---

## ADR-009: Social import is link + attribution + user-supplied media

**Decision.** A pasted or shared Instagram / TikTok / Pinterest URL is stored as an
**external content reference**: canonical URL, platform, author handle when the URL
carries one, fetch timestamp. We render the platform's official embed where its terms
allow, and we do **not** download, store, or run perception over platform-hosted media.
Garment analysis runs on media the user supplies: a photo, a screenshot, or a short clip
they are entitled to provide.

**Why.** You directed that a link is sufficient and that the companies' official
endpoints are not needed — and that is what this delivers: the user pastes a link and
the flow works end to end. What a public URL does not convey is permission to fetch and
analyse the media behind it, and §11 of the brief states this directly ("Access to a
public URL or embed does not establish permission to download, store, or analyse its
media"; "Instagram oEmbed must not serve as the garment-analysis data source"). A
downloader would put App Store / Play review and the platforms' terms at risk to obtain
a capability the user-supplied path already provides. Each adapter therefore reports six
independent booleans — can embed, can read metadata, can access media, can analyse, can
store, can operate under current authorisation — and the UI states the limitation
truthfully and offers the working alternative.

**Ingest path.** **Verified**: `expo-sharing` on SDK 58 is first-party and supports
*receiving* shares via `useIncomingShare()` plus a share-extension config plugin. Shares
arrive as a deep link with hostname `expo-sharing`, routed in `+native-intent.ts`
(`https://docs.expo.dev/versions/v58.0.0/sdk/sharing/`). The native share sheet from
Instagram or TikTok into LUXish is therefore a supported path, not a workaround. The
docs do note the iOS share extension is experimental.

**Hardening.** Every server-side URL touch goes through one SSRF-guarded fetcher:
scheme allowlist, DNS resolution pinned and re-checked after each redirect, private /
link-local / cloud-metadata ranges denied, redirect cap, byte cap, timeout, and
content-type verified against sniffed bytes rather than the declared header.

---

## ADR-010: Owned-garment identity is re-validated outside the model

**Decision.** Every garment ID a model returns is re-checked against the requesting
user's current wardrobe — exists, owned by this user, not archived, not marked
unavailable — before an outfit is persisted or rendered. A model-invented or
cross-user ID fails the run with a structured error; it never degrades into a
plausible-looking outfit.

**Why.** §6, §15, and acceptance criteria 2 and 9. This is the one invariant whose
failure is simultaneously invisible to the user and a privacy breach, so it is enforced
at a single chokepoint with its own test rather than at each call site.

---

## ADR-011: Financial state is server-side integer minor units on an append-only ledger

**Decision.** Money is `(amount_minor: int, currency: char(3))`. Gifts, entitlements and
payouts move through append-only double-entry ledger rows keyed by an idempotency key,
with a database constraint forbidding a negative spendable balance. Purchased consumable
balances and subscription-period allowances are distinct account types. IAP-purchased
gift credits never expire.

**Why.** §14 and acceptance criterion 13. Duplicate and out-of-order store webhooks are
the normal case, not the exception, so idempotency is a schema property rather than a
matter of application diligence.

---

## ADR-012: Deletion uses tombstones that outlive in-flight jobs

**Decision.** Deleting an asset writes a tombstone row that survives the asset itself.
Every worker re-checks ownership, deletion state, publication consent and asset version
immediately before persisting or publishing, in the same transaction as the write.

**Why.** §16 and acceptance criterion 12 — a late job must not resurrect deleted
content. Checking at job start is insufficient because deletion can land mid-job.

---

## ADR-013: GCP — Cloud Run, Cloud SQL, Terraform

**Decision.** Cloud Run for API and workers; Cloud SQL Postgres; GCS plus Cloud CDN;
Memorystore Redis once a bounded cache is justified; Cloud Tasks / Pub/Sub for durable
jobs; Secret Manager; Cloud Monitoring. All Terraform. Three environments.

**Why.** §19 and the founder's stated GCP experience. Cloud Run request timeouts are the
constraint to verify before putting long-running AI work in a request handler — which is
precisely why all model work is queued rather than awaited inline.

---

## ADR-014: Pin Node 24.3 LTS or 26 — not 25

**Decision.** Pin the toolchain to Node 24.3+ LTS (or 26) via `.nvmrc` and `engines`.

**Why.** **Verified**: React Native 0.88 / Expo SDK 58 require Node 22.13+, 24.3+ or
26+, and explicitly exclude odd-numbered releases
(`https://expo.dev/changelog/sdk-58`). This machine runs **Node 25.2.1**, which is the
cause of the `EBADENGINE` warning from `expo-doctor`. Installs succeed today, but this is
an unsupported configuration and must be corrected before any release build.

---

## ADR-015: SDK 58 router and module corrections encoded up front

**Verified** breaking changes from `https://docs.expo.dev/router/migrate/sdk-57-to-58/`
and `https://expo.dev/changelog/sdk-58`, each of which would otherwise cost a debugging
cycle:

- `expo-av` is **removed**. Audio is `expo-audio`, video is `expo-video`.
- Every route must be **explicitly declared** in tabs/drawer/native-tabs layouts.
- `withLayoutContext` is deprecated in favour of `integrateWithRouter`;
  `initialRouteName` is replaced by `unstable_settings.anchor`.
- `useNavigation` throws outside a navigator; the module-level `router` throws before
  first render.
- `web.output` now defaults to `server`.
- `expo-file-system` exposes a new OO API (`File`, `Directory`, `Paths`); the flat
  functions moved to `expo-file-system/legacy`. `File.write()` is now async.
  Background upload uses `file.createUploadTask(...)` with
  `sessionType: 'background'` (iOS).
- `expo-image-manipulator`'s `manipulateAsync` is deprecated in favour of
  `useImageManipulator` / `manipulate()`.
- Coarse location needs **both** entry points: `expo-location/next` for
  `RequestPermissionsAccuracyOption.REDUCED`, and classic `expo-location` for
  `reverseGeocodeAsync` (absent from `/next`). `/next` is beta.
- Push notifications require a development build on both platforms; local notifications
  still work in Expo Go.
- Android release builds now enable **R8 minification by default**.
- Strict TS API is default — deep imports from `react-native/Libraries/*` are type
  errors.
- `@expo/ui` universal components are included in Expo Go; import from
  `@expo/ui/universal`.
- There is **no first-party speech-to-text module**. Transcription is either the
  community `expo-speech-recognition` (v58.0.0, needs a dev build) or server-side
  `muse-voice-transcribe-1.0`. We choose **server-side** so one implementation serves
  both platforms and the transcript is auditable — `expo-speech` covers text-to-speech.
- iOS builds from this Windows machine are only possible via **EAS Build**; Xcode is
  macOS-only.

---

## ADR-016: Keycloak is the identity provider; Google is brokered through it

**Decision (user directive, 2026-10-26).** Authentication is delegated to a
self-hosted Keycloak realm. Account creation offers Google as a brokered social
identity provider. The app and API do **not** implement email/password, Apple, or
Google sign-in directly. This supersedes the per-provider auth design in ADR/Task 4.

**What each side owns.**
- *Keycloak* owns credentials, social brokering, the login and consent UI, password
  reset, MFA if enabled, and session lifetime.
- *Our API* owns nothing about credentials. It **verifies** Keycloak-issued RS256
  tokens against the realm JWKS and maps the token `sub` to an internal `User`.
- *Our mobile app* runs the authorization-code + PKCE flow against the realm in a
  platform browser session (`expo-auth-session` + `expo-web-browser`, which default
  `usePKCE` to true on SDK 58).

**Internal identity is still ours.** `User` plus `ExternalIdentity(provider, subject)`
with a unique constraint on `(provider, subject)` is retained from the original design.
The Keycloak `sub` is the stable key. We never key a user on email, which is mutable
and, when unverified, attacker-controllable.

**The account-takeover invariant did not go away — it moved into realm config.**
This is the part that matters. Keycloak's first-broker-login flow can link a brokered
Google account to an existing local account **by email address**. If that linking does
not require a verified email, an attacker who creates a Google account carrying a
victim's email address can be merged into the victim's account. The brief forbids this
("Prevent account takeover through unsafe email-based merging"), so the control is
enforced in two places, deliberately redundant:
1. *Realm config*: the identity provider's `Trust Email` stays **off**, and the
   first-broker-login flow requires an explicit account-link confirmation rather than
   automatically adopting an existing user.
2. *Our API*: a token presenting `email_verified: false` is never attached to a
   pre-existing `User` with that email. It provisions a distinct user or returns
   `409 identity_link_required`.
Defence in depth is justified here because the realm is configuration — it can be
changed by an operator in a console, without a code review, and silently.

**Revocation.** Keycloak tokens are JWTs, which cannot be un-issued. We therefore keep
a `revoked_tokens` table keyed on `jti` and a `sessions` table keyed on the token `sid`,
reject revoked presentations until `exp`, and expose an OIDC **backchannel logout**
endpoint so a Keycloak-side logout propagates to us. Access-token lifetime is kept
short (target 5 minutes) so the revocation window is small; refresh happens against
Keycloak, not against us.

**Algorithm-confusion guard.** Token verification accepts only RS256/ES256 keys fetched
from the realm JWKS. `alg: none` and every HMAC algorithm are rejected outright, so a
token signed with the public key as an HMAC secret cannot validate.

**Why this is a good trade.** It removes credential storage, password reset, social SDK
integration and MFA from our codebase and our breach surface, and it gives the admin
console and audit log the brief asks for in §18 for free. The costs are real and
accepted: one more stateful service to run and upgrade, an availability dependency on
it for every new session, and a security invariant that now lives in configuration
rather than in code — which is exactly why it is also asserted in our own tests.

**Consequences to settle before release.**
- **Apple Sign In is likely required on iOS.** App Store Review Guideline 4.8 requires
  an equivalent privacy-preserving login option when an app offers third-party social
  login. Offering Google without Apple is a plausible rejection. Keycloak must therefore
  broker Apple as well before iOS submission. Keycloak's Apple support and its handling
  of Apple's expiring signed-JWT client secret are being verified; if rotation is not
  handled, that becomes an operational task.
- **Hosting.** Keycloak needs a database (our Cloud SQL Postgres) and correct
  proxy/hostname configuration behind a load balancer. Whether scale-to-zero serverless
  hosting is appropriate is being verified; if it is not, Keycloak gets a
  minimum-one-instance deployment, which changes the cost floor.
- **Realm as code.** The realm is defined in a version-controlled JSON export and
  imported at startup, so the first-broker-login flow and `Trust Email` setting are
  reviewable in a pull request rather than being console state.
- `docs/ROADMAP.md` §4 rows written before this decision still describe the
  per-provider design and need reconciling.

---

## ADR-018: Celery + Redis for execution; PostgreSQL stays the durable record

**Decision (user directive, 2026-10-27).** Adopt Celery with Redis for task dispatch,
concurrency and fan-out. The existing PostgreSQL `jobs` table remains the **source of
truth** for job state — status, attempts, idempotency key, tombstone guard — and a
periodic sweeper re-enqueues anything Redis lost. Celery becomes the executor, not the
system of record.

**Why both, rather than Celery alone.** Four independent paths to a silently lost job,
each verified from Celery and Kombu's own documentation and source on 2026-10-27:

1. **`task_acks_late` defaults to `Disabled`.** Out of the box Celery+Redis is
   *at-most-once*: the message is acknowledged on delivery, so a killed worker loses
   the task with no trace.
2. **Redis is a Kombu *virtual* transport with emulated acks** — `ack_emulation = True`.
   In-flight messages live in a plain Redis hash (`unacked`) and zset
   (`unacked_index`). Durability is therefore bounded entirely by Redis: Memorystore
   offers AOF **or** RDB but not both, replication is asynchronous, and a wrong
   `maxmemory-policy` evicts queue keys silently.
3. **Recovery requires a live worker.** Abandoned messages are restored only by
   `restore_visible`, which runs inside a worker on a throttled ~100-second sweep.
   With no worker alive on a queue there is no sweep, so Celery's own recovery path is
   *structurally unable to run*.
4. **Cloud Run allows 10 seconds between SIGTERM and SIGKILL**, and that window is not
   configurable outside a private preview. Celery's warm shutdown waits for running
   tasks to finish. For our media and AI jobs, which take minutes, those two
   behaviours are irreconcilable — tasks will be killed mid-flight on every scale-down
   and every deploy, as routine rather than as an edge case.

The Postgres table closes all four. This is the **Transactional Outbox** plus
**Polling Publisher** pattern; the tombstone guard (ADR-012) is a fencing guard
against resurrect-after-delete.

**The settings that make it safe**, with defaults named because the defaults are wrong
for us:

| Setting | Default | Ours | Why |
|---|---|---|---|
| `task_acks_late` | Disabled | `True` | Otherwise a SIGKILL loses the task outright |
| `worker_prefetch_multiplier` | 4 | `1` | Limits blast radius to one message per process |
| `visibility_timeout` | 3600 | **very high** | See the triple-dispatch note below |
| `task_reject_on_worker_lost` | Disabled | **leave off** | Celery warns it "can cause message loops"; our bounded `attempts` is the safer re-drive |
| `result_backend` | none | **leave unset** | Postgres already stores status; a Redis result backend would add a second durability problem for data we already hold durably |
| `task_ignore_result` | Disabled | `True` | Same reason |

**The triple-dispatch trap, and the one rule that avoids it.** Two redelivery
mechanisms now exist: Redis's `visibility_timeout` and our sweeper. If the visibility
timeout is shorter than the sweeper's staleness threshold, Redis redelivers first and
the sweeper later adds a *third* copy. So `visibility_timeout` is set deliberately
**longer than any task could possibly run**, making Postgres the sole re-drive
authority. This is the single most consequential setting in the configuration.

**Correction, added after implementation.** `visibility_timeout` is a **per-consumer**
setting, and where several consumers share a broker **the shortest value wins** —
including the Kombu default of 3600 from a consumer that never sets it. So the
"very high" value above is not a property of the queue; it is a property of every
process that connects to it. A Flower instance, a metrics exporter, or a second
service on the same Redis would silently reimpose a one-hour timeout and
reintroduce exactly the double-dispatch this setting exists to prevent. The code
comment in `app/queue/celery_app.py` records this; anything that connects to this
broker must set the same number.

**What actually makes duplicate delivery safe.** The setting above is belt and
braces. The real guarantee is that a Celery message carries **nothing but a job
id**, and `claim_job_by_id` is a single conditional `UPDATE … WHERE state =
'queued'`. Of two workers handed the same message, exactly one row matches; the
other sees no row and declines. Idempotency is therefore structural rather than
configured, which matters because no Redis setting can provide it.

**Two further corrections to the reasoning above.** First, the scale-to-zero
argument is weaker than stated: Cloud Run worker pools do **not** autoscale at
all, so an instance count is pinned and a live worker normally exists. The
durability argument does not depend on it — a deploy, an eviction or an OOM kill
still strands in-flight work, and `reclaim_stalled_jobs` is what recovers it.
Second, the CPU-throttling concern applies to Cloud Run **services**, not worker
pools, which are billed for the instance lifecycle and keep CPU allocated
throughout.

**Empirical status.** No published report of Celery running on Cloud Run worker
pools could be found, successful or otherwise, in the six months since GA. The
one worker-pools-specific Celery thread is an unresolved failure. The path is
sound on the documented contracts and **undocumented in practice**, so treat the
first deploy as a validation exercise rather than a routine one.

**The surveyed alternatives, and why none of them removes this work.** Five
libraries were examined against this stack. `dramatiq` has native async actors
on a persistent per-worker loop, but its Redis broker recovers abandoned
messages via a sweep with a **0.1% chance per command**, scoped to one queue, and
with no upper bound at all when no worker is alive on that queue. `procrastinate`
and `chancy` are Postgres-native but **psycopg-only**, so in-transaction enqueue
is unavailable on our asyncpg session — which was the main reason to want them.
`taskiq`'s Redis stream broker does not reclaim at all on Cluster or Sentinel,
and ships Alpha metadata. `pgqueuer` is the only option supporting asyncpg
transactional enqueue, and is 96% one author. Every one of them is at-least-once
at best and requires an idempotent handler plus an external re-drive. The
conclusion is that the Postgres-owned queue in this ADR is **not a workaround for
Celery specifically**; it is the work any of these choices would require, which
also means the dispatch layer can be swapped later without touching it.

**Deployment.** Cloud Run **worker pools** (GA 2026-04-14), not services. Worker pools
require no `$PORT` listener and never throttle CPU between requests — both of which
make a Celery worker on a Cloud Run *service* a fight against the product. They have
no built-in queue-depth autoscaling, so scaling is manual or via Google's CREMA
autoscaler. `celery beat` is **not** used: it requires exactly one scheduler and keeps
state in a local file, both wrong on Cloud Run. The sweeper is driven by Cloud
Scheduler against an HTTP endpoint instead.

**The honest cost, recorded rather than glossed.** Celery has **no native async
support** and no official guidance for calling async code from a task — the
maintainers cite time and funding, not design. Our stack is async FastAPI with async
SQLAlchemy and asyncpg, so the bridge is community practice we own and must test:
either `asyncio.run()` per task with `NullPool`, or one persistent loop per worker
process. The failure mode when it is wrong is `Task got Future attached to a different
loop`, because asyncpg connections outlive the loop that created them. All three
third-party async pools for Celery are abandoned or pre-release.

**What we are not choosing, and why it was close.** `dramatiq` has native async actors
on a persistent per-worker loop — exactly the thing Celery lacks — and returns
in-flight messages on shutdown by design. `procrastinate` is Postgres-backed and
async-native, needs no extension on Cloud SQL, and supports enqueueing inside the same
transaction as the business write, which would remove the dual-write window, the
sweeper, the Redis durability question and the async glue at once. Either would match
this architecture's intent more closely than Celery does. Celery is adopted because it
was specified, its ecosystem and operational familiarity are real, and the design above
makes it safe. If the async bridge proves troublesome in practice, `dramatiq` is the
smallest migration and `procrastinate` the most aligned.

**Verified facts** (2026-10-27): Celery 5.6.3 released 2026-03-26; Celery 6 is not
released; Redis and RabbitMQ are rated identically in Celery's current broker table,
which no longer has a durability column — the gap comes from the virtual-transport
mechanism, not from a documented preference.

## ADR-019: Visual direction, measured against what premium retail ships

**Status.** Accepted. Implemented in `apps/mobile/src/constants/theme.ts`,
`components/ui/skeleton.tsx`, `components/ui/motion.tsx`, and enforced by
`constants/__tests__/theme.test.ts` and `components/ui/__tests__/copy.test.ts`.

**Context.** The brief is warm, clean, professional and visually appealing, with
no "AI slop" tells. That is a judgement, and judgements drift. Four of the
decisions below are also counterintuitive enough that someone will reasonably
try to undo them, so each records the evidence rather than the preference.

Sources were the products themselves: CDN transform strings, shipped i18n
dictionaries, App Store screenshots, Apple's HIG specification data, Material 3,
WCAG Understanding documents and Nielsen Norman Group. The four design galleries
originally named in the brief (appshots.design, mobbin.com, scrnshts.club,
uxarchive.com) turned out to be unusable: one has a broken certificate, one
returns 403 to any non-browser client, one has been acquired and redirected, and
one is defunct. Reading the real products was better evidence anyway.

### Garment cells are 3:4 and padded, never cropped

Zero of eight measured fashion retailers ship a 1:1 garment grid tile. The split
is 2:3 for SSENSE, Zara, COS and Alo Yoga; 3:4 for NET-A-PORTER, Farfetch and
Uniqlo; 4:5 for Everlane. A square cell crops a coat or dress around the knee,
and the wardrobe is the user's own clothes, where a wrong crop reads as a bug.

3:4 rather than the taller 2:3 because our photographs come from a phone, and a
phone shoots 3:4 portrait, so the common case needs no crop at all. Studio
retail can force 2:3 because its masters are arbitrarily tall: SSENSE stores at
1:2.045. Poshmark moved its grid from 1:1 to 3:4 in March 2026 and gave exactly
this reason, that sellers' cameras already default to portrait.

Pad rather than crop, after SSENSE. Across a full category page its Cloudinary
transforms are 1865 `c_lpad` (letterbox pad) and zero `c_fill` or `c_crop`. It
also anchors the pad to the bottom (`g_south`), which keeps shoulders and
necklines at a consistent height across tiles. Uniqlo is the only measured
retailer that crops, and only because it shoots a 1:1 master with roughly 11%
flat grey margin each side specifically so the crop is throwaway.

### Background removal must ship with a contact shadow

Recorded because it is the most expensive thing to get wrong here. Depop A/B
tested background removal alone and got 9% adoption with flat metrics. The
published diagnosis was that "without a shadow, products looked like they were
floating in space, unnatural and unconvincing. An image that looks too
artificially edited can undermine the trust that peer-to-peer selling depends
on." The same feature with generated drop shadows returned +1.5% items listed,
about 6,000 more per day.

So a hard cut-out on flat white is the version that failed. The cut-out is the
enabling primitive, not the feature.

### Semantic colours are warm, and there is no `info` token

`success` is olive and `warning` is ochre, both in the same half of the wheel as
the burgundy accent, each tuned just past AA on both grounds. A stock `#00C853`
green or `#2196F3` blue would be the one cold thing on a warm page and reads
immediately as a dropped-in component library. Every blue computed against this
palette was tonally foreign, so `info` does not exist; informational text uses
`textSecondary`.

Two related rules. No tinted banner backgrounds: the washes compute to 1.02 to
1.12 contrast against warm paper, so they add markup and no signal. No coloured
left-border strip, which is independently one of the most reliable AI tells.
Semantics are carried on text and a glyph, which also satisfies WCAG 1.4.1.

`borderStrong` exists because the existing `border` is 1.32:1 against the page.
That is fine for a divider and fails WCAG 1.4.11's 3:1 for anything bounding a
control, so inputs and outlined buttons had no conforming boundary at all.

### Skeletons do not shimmer

Not a stylistic preference. WCAG 2.2.2's loading-animation exemption is
conditioned on the animation being the only content on the page: "Because the
moving content is not presented in parallel with other content, no mechanism to
pause, stop or hide it needs to be provided." A shimmering grid under our live
tab bar is by construction not the only content, so the criterion is met rather
than escaped. The "essential" exception also fails, since it requires that
interaction cannot occur during the phase.

A static placeholder conveys loading perfectly well, so nothing was traded away.
Honouring `prefers-reduced-motion` would not have been sufficient, because 2.2.2
asks for a mechanism regardless of OS preference.

Placeholders are also withheld for 400ms, because NN/g's guidance is that under
one second no indicator should be shown, since "the quick flashing page can
cause users to feel like they can't keep up."

One caution for anyone revisiting this. A widely-circulated statistic
attributing "400 milliseconds to 3 seconds" and "9 to 20% bounce reduction" to a
2026 NN/g report is fabricated. It appears in no NN/g publication and only on
undated content farms. The thresholds used here are quoted from the real
article.

### Type has an 11pt floor

Apple publishes 11pt as the iOS minimum text size, stated independently of
Caption 2 also being 11pt at the default setting. Four places rendered 9px,
9.5px and 10px labels before this was enforced. `FontSize` mirrors the iOS scale
(11/12/13/15/17/20/22/28/34) so a screen never picks a number.

### Copy rules are tested, not documented

Read out of SSENSE, NET-A-PORTER, MR PORTER, COS, Everlane, Arc'teryx, Aesop,
Zara and Farfetch. They converge on a flat statement of fact plus at most one
line saying what will fill the space or what to do next. Two patterns worth
naming. Nobody apologises for an empty container: "Sorry" appears on
no-search-results and nowhere else. And counts live in the label rather than in
a coloured badge, as in `BAG 03`, `548 Results`, `ITEMS (558)`. That second one
is both the terseness mechanism and a way to avoid the semantic-colour problem
entirely.

The mechanical rules live in `copy.test.ts` rather than in prose, because a
guide nobody enforces drifts back one string at a time. It catches em and en
dashes, type below 11pt, apology on an empty screen, exclamation marks in
failure copy, "invalid" where Polaris asks for "not valid", "please" in a button
label, and anything opening with "Let's". Three of those caught real defects on
first run.

One convention is deliberately not adopted. Polaris and Mailchimp both mandate
sentence case for buttons, and every premium fashion retailer measured does the
opposite. Those are admin and SaaS conventions; fashion retail is a separate
tradition, and this app follows the latter.

### Motion does one of three jobs

Confirm a touch, explain where content came from, or mark a state the user
caused. Anything else is decoration, and decoration competes with the
photographs, which are the content.

Presses compress to 0.975 rather than fading, because fading a photograph reads
as "loading" rather than "pressed". The grid stagger is capped at 8 cells:
uncapped, cell 30 would wait 1.2s and the grid would appear to load slowly when
it had already loaded. Every primitive collapses to nothing under Reduce Motion
rather than running faster, because a shortened version of an unwanted animation
is still unwanted.

### What was rejected

Text overlaid on grid images. Every premium reference puts product text below
the image on paper, and Material 3 states outright: "It isn't recommended to
place text or icons on images. If it's necessary, ensure the background image
provides sufficient contrast... Add a translucent scrim or bounding shape." The
gradient scrim is retained only for the full-bleed editorial hero, where it is
the single largest element and the contrast can be guaranteed.

Fast-fashion urgency devices. Shein encodes cheapness as named card-level design
tokens, including `--product-card_color-discount: #F93A00` against
`--color_flashsale_primary: #FACF19`, plus sold counters and "{0} less than when
added". The defence is simply to have no such tokens, so there is nothing to
reach for.
