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
hardcodes a product name. Working name **Atelier**; package scope stays `@fashion/*`.

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
Instagram or TikTok into Atelier is therefore a supported path, not a workaround. The
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
