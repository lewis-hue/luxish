# LUXish — External Integration Matrix

Status date **2026-10-26**. Companion to
[architecture/decisions.md](./architecture/decisions.md) and
[ROADMAP.md](./ROADMAP.md).

This is the complete register of every external dependency the product needs, what
credential it requires, **who must personally obtain that credential**, what approval
gates it, how much of the capability is really covered, and what evidence backs each
claim.

---

## Reading rules

### Readiness vocabulary

| Readiness | Meaning |
| --- | --- |
| `live` | Credentialed and calling the real vendor in a deployed environment. **No row uses this value.** Nothing in this repository holds a vendor credential, so nothing is live. |
| `ready-pending-credential` | The vendor's contract is verified from live docs, the adapter design is fixed, and the only thing missing is the credential. Dropping a key in unblocks it. |
| `fixture` | Served by a clearly labelled fixture behind the real interface. No vendor dependency, and the UI must say so. |
| `blocked` | Cannot proceed even with money and effort today — waiting on an approval, a waitlist, or an unmade decision. |
| `not-started` | In scope, no design or verification work done yet. |

### Evidence rules

- **Verified 2026-10-26** — the URL was fetched from the vendor's live documentation on
  2026-10-26 and the specific fact is recorded in `decisions.md`. These are the only
  claims in this document that may be relied on without re-checking.
- **Canonical root, not fetched** — the URL is the vendor's canonical documentation entry
  point, but it was **not** fetched on 2026-10-26 and no specific fact from it is
  verified. Treat every detail about such an integration as an assumption until someone
  reads the page and records what it says.
- **Assumed** — a default we chose. Not measured, not verified.
- No URL in this document was constructed from memory of a deep-linked page. Where only
  the root is known, only the root is cited.

### Who must obtain the credential

| Label | Meaning |
| --- | --- |
| **Founder** | Requires a legal identity, a payment method, a bank account, or acceptance of vendor terms. An engineer cannot do this on someone else's behalf. |
| **Engineering** | Derivable once the founder's account exists — a console-generated client ID, a service-account key, a project-scoped setting. |
| **Both** | The founder must create or pay for the account; engineering then generates the artefact inside it. |

---

## Matrix

| Integration | Purpose | Credential needed | Who must obtain it | Permission / approval required | Real coverage | Readiness | Verification evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Meta Model API** — platform | All first-party AI: styling, attribute inference, image generation, transcription, segmentation | API key prefixed `LLM_`, sent as `Authorization: Bearer $MODEL_API_KEY`; base URL `https://api.meta.ai/v1` | Founder | **Self-serve** — no waitlist, no partner approval | Text, image-in, image-out, video frames, audio transcription, tools, structured output, streaming. **No embeddings model and no embeddings endpoint.** Rate limits apply **per team, not per API key**, so our concurrency limiter must be team-wide | `ready-pending-credential` | Verified 2026-10-26: `https://dev.meta.ai/docs/models`, `https://dev.meta.ai/docs/api-reference`, `https://dev.meta.ai/docs/protocols/chat-completions`, `https://dev.meta.ai/docs/pricing-rate-limits`, `https://dev.meta.ai/docs/sdks` (ADR-004, ADR-005, ADR-007) |
| **Meta** — `muse-spark-1.3` | Stylist reasoning, attribute inference | Same single key | Founder | Same | Text in/out, tools, structured output. Per-model price **not recorded here** — only `sam-3.1` pricing was captured on 2026-10-26 | `ready-pending-credential` | Verified 2026-10-26: `https://dev.meta.ai/docs/models` |
| **Meta** — `muse-wonder-1.0` | Stylist reasoning (alternate tier) | Same single key | Founder | Same | Text in/out. Per-model price not recorded — re-read the pricing page before any budget claim | `ready-pending-credential` | Verified 2026-10-26: `https://dev.meta.ai/docs/models` |
| **Meta** — `muse-image-1.0` | Lookbook and outfit imagery | Same single key | Founder | Same | Image generation. **Never routed to the ChatGPT-plan path in any state** — that route does not support it | `ready-pending-credential` | Verified 2026-10-26: `https://dev.meta.ai/docs/models` (ADR-006, ADR-008) |
| **Meta** — `muse-voice-transcribe-1.0` | Server-side voice input for the stylist | Same single key | Founder | Same | Audio → transcript. Chosen over the community Expo STT module so one implementation serves both platforms and the transcript is auditable; there is **no first-party Expo speech-to-text module** | `ready-pending-credential` | Verified 2026-10-26: `https://dev.meta.ai/docs/models`; `https://expo.dev/changelog/sdk-58` (ADR-015) |
| **Meta** — `sam-3.1` | "Select the garment inside this image" (§5, §11, §12) | Same single key | Founder | Same | Text prompt over an image **or a video frame**, returning boxes and masks. **$2.50 / 1,000 images**, **$0.20 / 1,000 video frames**. Worker-only, never a request-path call, charged to the requesting user's allowance | `ready-pending-credential` | Verified 2026-10-26: `https://dev.meta.ai/docs/models`, `https://dev.meta.ai/docs/pricing-rate-limits` (ADR-005) |
| **Meta** — embeddings | Visual similarity, "find similar", community visual query | — | — | — | **None. The API publishes no embeddings model and no embeddings endpoint.** Any vector feature needs a *second* paid provider, which has not been selected or costed | `blocked` | Verified 2026-10-26: `https://dev.meta.ai/docs/models`, `https://dev.meta.ai/docs/api-reference` (ADR-004) |
| **Sign in with ChatGPT** (identity) | Optional identity provider | OAuth client registered with OpenAI (PKCE S256) | Founder | **Waitlisted.** Commercial access is "currently offered to a select group of commercial partners"; the self-service token-sharing path is scoped to open-source / locally hosted apps, and "paid or remotely hosted" apps are routed to an **interest form** | Identity assertion only. A valid ID token **does not** authorise plan usage — signing in and using the plan are separate permissions. Endpoints: `https://auth.openai.com/api/accounts/authorize`, `/api/accounts/oauth/token`, `/api/accounts/oauth/revoke`. Code exchange happens **on our backend** against a registered `https://` callback — the docs give no native-mobile guidance and the OSS flow needs a `127.0.0.1` loopback a sandboxed app cannot host | `blocked` | Verified 2026-10-26: `https://developers.openai.com/siwc/quickstart`, `https://developers.openai.com/siwc/token-sharing-open-source`, `https://learn.chatgpt.com/docs/sign-in-with-chatgpt` (ADR-008) |
| **ChatGPT-plan inference** | Let a user spend their own ChatGPT plan instead of our allowance | The identity grant **plus** scopes `offline_access resource.invoke chatgpt.tokens.use.direct` | Founder | Separate approval from identity. Only **Plus and Pro** are named eligible; Free / Business / Enterprise eligibility is **not stated**, so it is not assumed | Text only, via `POST https://api.openai.com/v1/responses` with `store:false` and `stream:true` **mandatory**. **Unsupported: image generation, file search, Code Interpreter, the Files upload API, audio/video input.** There is **no allowance-remaining API** — exhaustion is observable only as a 429 `subscription_sharing_usage_limit_exceeded`, which can arrive **mid-stream** as a `response.failed` event. There is **no revocation webhook**: OpenAI "does not currently notify your tool when a user disconnects the app in ChatGPT settings" | `blocked` | Verified 2026-10-26: `https://developers.openai.com/siwc/quickstart`, `https://developers.openai.com/siwc/token-sharing-open-source` and subpages, `https://learn.chatgpt.com/docs/sign-in-with-chatgpt` (ADR-008) |
| **Vertex AI** | Possible second AI provider (embeddings, fallback inference) | GCP project with billing + a service account with Vertex permissions | Both | GCP project and billing; per-region, per-model quota must be requested and granted | **Unknown until pinned.** Vertex is a **platform, not a model** — nothing can be promised until a specific model, a specific model version, a specific region, and a granted quota are all chosen and recorded. Naming "Vertex AI" as a dependency without those four is not an integration | `blocked` | Canonical root, not fetched: `https://cloud.google.com/vertex-ai/docs`, `https://cloud.google.com/vertex-ai/docs/quotas` (ADR-004 names it only as a candidate requiring a cost review) |
| **Apple Sign In** | Identity provider on iOS (and a store requirement where third-party sign-in is offered) | Apple Service ID + private key for token verification; the capability enabled on the App ID | Both | **Paid Apple Developer Program membership** ($99/yr). Apple requires Sign in with Apple wherever another third-party sign-in is offered | Identity assertion. Apple may return a **private relay email**, and `email_verified` may be false — our identity linking must therefore refuse to merge into an existing account on email alone (409 `identity_link_required`) | `blocked` | Canonical root, not fetched: `https://developer.apple.com/sign-in-with-apple/`, `https://docs.expo.dev/versions/latest/sdk/apple-authentication/` |
| **Google Sign In** | Identity provider on both platforms | OAuth 2.0 client IDs — one each for iOS, Android, and web | Both | A Google Cloud project with the OAuth consent screen configured; the Android client needs the release signing certificate's SHA-1 | Identity assertion. The same unverified-email merge hazard as Apple applies | `blocked` | Canonical root, not fetched: `https://developers.google.com/identity`, `https://docs.expo.dev/guides/google-authentication/` |
| **Apple In-App Purchase** | Subscriptions and gift-credit consumables on iOS | App Store Connect API key + App Store Server Notifications V2 endpoint secret | Founder | Paid Apple Developer Program membership, **plus** the Paid Applications agreement, banking details, and tax forms. Products must be created and submitted for review | Purchases, renewals, refunds, and server notifications. Duplicate and out-of-order notifications are the **normal case**, which is why idempotency is a schema property and not application diligence. IAP-purchased gift credits never expire | `blocked` | Canonical root, not fetched: `https://developer.apple.com/in-app-purchase/`, `https://developer.apple.com/documentation/appstoreservernotifications` (ADR-011) |
| **Google Play Billing** | Subscriptions and gift-credit consumables on Android | Play Console service-account key + a Pub/Sub topic for Real-Time Developer Notifications | Founder | Play Console developer account **plus a linked Google payments merchant account** — the merchant account is a separate approval with its own identity and banking checks | Same scope as Apple IAP; same duplicate/out-of-order guarantees | `blocked` | Canonical root, not fetched: `https://developer.android.com/google/play/billing`, `https://developer.android.com/google/play/billing/rtdn-reference` (ADR-011) |
| **Payout provider** — **UNSELECTED** | Paying creator earnings out | Unknown — depends on the provider | Founder | Business identity verification, KYC/AML, and a payout agreement with whichever provider is chosen | **None, and this is the single hardest blocker in the commercial path.** No provider has been selected, and **support for payouts to Kenya has not been verified for any candidate**. That verification — not engineering effort — is the blocker. Creator earnings, payout tax handling, and live payouts all sit behind it. The ledger is built provider-agnostically so the choice is late-binding, and live payouts stay behind a flag | `blocked` | **No evidence exists.** No provider's documentation has been consulted, because no provider has been chosen. Do not record a URL here until a candidate is evaluated for Kenya payout support |
| **Weather provider** — **UNSELECTED** | Real weather readings for outfit recommendations | API key | Founder | Depends on provider; most require a signed-up account and many restrict commercial or mobile use on free tiers | **None yet.** Phase B ships a labelled fixture behind the `weather` tool contract, or a user-described reading that sets `described_by_user=True` and carries **no fabricated `source`**. The `WeatherReading` shape (`place, observed_at, units, source, is_stale, described_by_user`) is deliberately provider-neutral so selection is late-binding | `fixture` | **No evidence exists** — no provider selected, so no documentation has been consulted. The selection must record licence terms for commercial mobile use, not just price |
| **Retailer / affiliate product feeds** | Grounded shopping with real product evidence | Merchant API keys or affiliate-network credentials | Founder | A merchant agreement or affiliate-network approval per retailer or network; most require a live, reviewable app first — a chicken-and-egg gate worth planning around | **None yet.** Phase B is a **clearly labelled fixture adapter** over a seeded catalogue carrying real source URLs and real retrieval timestamps, behind the exact interface a live feed implements. `classify` is a pure function of evidence: identifier agreement (GTIN / MPN / retailer product ID) → `confirmed_item`; corroborating non-identifying evidence → `likely_match`; resemblance alone → `similar_style`, never `confirmed_item`. A verified-retailer badge requires a completed verification record | `fixture` | **No evidence exists** — no retailer or network has been approached. The fixture's own source URLs are real retailer product pages and are the only external URLs in the shopping path |
| **Instagram** | Inspiration import | None for the link path. An app review would be needed for any API use we are deliberately not making | Founder (only if API use is ever added) | Nothing for reference + embed. Platform terms govern embedding; **a public URL is not permission to download, store, or analyse the media behind it** | **Reference and embed only.** We store canonical URL, platform, author handle when the URL carries one, and a fetch timestamp; we render the official embed where terms allow. **No media download, no storage, no perception over platform-hosted media.** Instagram oEmbed must **not** serve as the garment-analysis data source. Garment analysis runs only on media the user supplies. Six capability booleans are reported per platform (`can_embed`, `can_read_metadata`, `can_access_media`, `can_analyse`, `can_store`, `authorised_now`) and the UI states the limitation truthfully with the working alternative | `ready-pending-credential` (no credential needed — gated only on the Phase B build) | ADR-009 states the policy; brief §11 states the permission limit. Canonical root, not fetched: `https://developers.facebook.com/docs/instagram-platform/` |
| **TikTok** | Inspiration import | None for the link path | Founder (only if API use is ever added) | Same as Instagram | Same reference + embed + user-supplied-media model. No media download or analysis | `ready-pending-credential` (no credential needed) | ADR-009. Canonical root, not fetched: `https://developers.tiktok.com/` |
| **Pinterest** | Inspiration import | None for the link path | Founder (only if API use is ever added) | Same as Instagram | Same reference + embed + user-supplied-media model. No media download or analysis | `ready-pending-credential` (no credential needed) | ADR-009. Canonical root, not fetched: `https://developers.pinterest.com/` |
| **Native share-sheet ingest** (`expo-sharing`) | Receiving a shared link from Instagram / TikTok into the app | None | — | Needs a **development build**; the iOS share extension is documented as **experimental** | `useIncomingShare()` plus a share-extension config plugin, first-party on SDK 58. Shares arrive as a deep link with hostname `expo-sharing`, routed in `+native-intent.ts`. This is a supported path, not a workaround | `ready-pending-credential` (no credential; gated on the dev build) | Verified 2026-10-26: `https://docs.expo.dev/versions/v58.0.0/sdk/sharing/` (ADR-009) |
| **GCP** — Cloud Run (API + workers) | Hosting | GCP project + billing account + a Terraform service-account key | Both | Billing account verification; org policy if under a Workspace | Request/response hosting with a **request timeout that must be measured before trusting it** — which is exactly why all model work is queued rather than awaited inline | `blocked` | Canonical root, not fetched: `https://cloud.google.com/run/docs` (ADR-013) |
| **GCP** — Cloud SQL (Postgres 16) | Primary datastore | Same project + instance credentials | Both | Billing | Managed Postgres. Local development runs Postgres 16 in Docker so schema work is not gated on GCP | `blocked` | Canonical root, not fetched: `https://cloud.google.com/sql/docs/postgres` (ADR-013) |
| **GCP** — Cloud Storage + Cloud CDN | Media storage and delivery | Same project; signed-URL signing key | Both | Billing | Direct device upload via short-lived signed URLs; private and public delivery paths separated | `blocked` | Canonical root, not fetched: `https://cloud.google.com/storage/docs`, `https://cloud.google.com/cdn/docs` (ADR-013) |
| **GCP** — Cloud Tasks / Pub/Sub | Durable job delivery | Same project | Both | Billing | The adapter implements the **same interface** as the local Postgres queue (`SELECT … FOR UPDATE SKIP LOCKED`), so the swap is configuration, not a rewrite | `blocked` | Canonical root, not fetched: `https://cloud.google.com/tasks/docs`, `https://cloud.google.com/pubsub/docs` (ADR-013) |
| **GCP** — Memorystore Redis | Caches, rate limits, allowance reservation | Same project | Both | Billing | Introduced **only once a bounded cache is justified**; local development uses Redis 7 in Docker | `blocked` | Canonical root, not fetched: `https://cloud.google.com/memorystore/docs/redis` (ADR-013) |
| **GCP** — Secret Manager | Holding the Meta key, store keys, OAuth secrets | Same project | Both | Billing; per-secret IAM | Deployed-environment secret storage. Local development uses `pydantic-settings` with **no secret defaults** | `blocked` | Canonical root, not fetched: `https://cloud.google.com/secret-manager/docs` (ADR-013) |
| **GCP** — Cloud Monitoring | Metrics, dashboards, alerting | Same project | Both | Billing | Error-rate, queue-depth, and spend alerting | `blocked` | Canonical root, not fetched: `https://cloud.google.com/monitoring/docs` (ADR-013) |
| **APNs** (iOS push) | Notifications | APNs authentication key (`.p8`) from the Apple Developer account | Founder | **Paid Apple Developer Program membership.** Push notifications also require a **development build** — they do not work in Expo Go | Remote notifications on iOS. Local notifications work in Expo Go without any of this | `blocked` | Verified 2026-10-26 (dev-build requirement): `https://expo.dev/changelog/sdk-58` (ADR-015). Canonical root, not fetched: `https://developer.apple.com/documentation/usernotifications`, `https://docs.expo.dev/push-notifications/overview/` |
| **FCM V1** (Android push) | Notifications | Firebase service-account JSON for the **V1** API (the legacy server key is retired) | Both | A Firebase project linked to the Android app; `google-services.json` in the build | Remote notifications on Android. Also requires a development build | `blocked` | Canonical root, not fetched: `https://firebase.google.com/docs/cloud-messaging/migrate-v1`, `https://docs.expo.dev/push-notifications/overview/` |
| **EAS Build** | **The only way to build iOS from this Windows machine** — Xcode is macOS-only | Expo account + EAS CLI login | Founder (account), Engineering (profiles) | A free Expo account suffices for Android and for iOS **simulator** builds. iOS device builds, internal distribution, and store submission additionally need the paid Apple Developer Program membership for signing credentials | Cloud builds for both platforms, plus `eas submit`. A `development` profile with `developmentClient: true` is required because push, the share extension, and several SDK 58 modules do not work in Expo Go. Android release builds now enable **R8 minification by default** and must be tested with it on | `blocked` | Verified 2026-10-26: `https://expo.dev/changelog/sdk-58` (R8 default, dev-build requirements); ADR-015 records that iOS builds from this machine are only possible via EAS Build. Canonical root, not fetched: `https://docs.expo.dev/build/introduction/` |

---

## Credential acquisition order

Dependencies, cheapest and least gated first. Each line states what it unblocks.

1. **Meta Model API key** — self-serve, no approval. Unblocks every AI capability in
   Phase B: the real styling run, attribute inference, the lookbook, transcription, and
   `sam-3.1` segmentation. This single key is the highest-leverage credential in the
   programme and the only one with no gatekeeper.
2. **Expo / EAS account** — free. Unblocks the iOS development build, which is a hard
   prerequisite for push, the share extension, and several SDK 58 modules, and which
   cannot be produced any other way from Windows.
3. **Google Cloud project with billing** — unblocks Google Sign In client IDs, all of
   §19's infrastructure, Secret Manager, and any Vertex AI evaluation.
4. **Paid Apple Developer Program membership** — unblocks Apple Sign In, APNs, iOS device
   and store builds, and (with the Paid Applications agreement) Apple IAP.
5. **Play Console developer account, then the linked merchant account** — unblocks Android
   store release, then Play Billing. The merchant account is a second, separate approval.
6. **Weather provider selection** — a decision, not a purchase. Record the licence terms
   for commercial mobile use alongside the price.
7. **Payout provider evaluation for Kenya support** — start this earliest of all the
   commercial items, because it is a verification exercise with an unknown answer rather
   than a form to fill in. Until it resolves, creator earnings and payouts stay `blocked`.
8. **OpenAI SIWC interest form** — submit early and treat the result as out of our
   control. Nothing in the product may depend on it: ChatGPT-plan inference ships
   `unavailable`.
9. **Retailer or affiliate network approval** — typically requires a live, reviewable app,
   so it naturally follows the store release. The fixture adapter exists so that this
   ordering costs nothing.

---

## Verified versus assumed — the honest split

### Verified from live vendor docs on 2026-10-26

Every fact below was fetched on 2026-10-26 with the URL recorded in `decisions.md`. These
are the facts the architecture is allowed to rely on.

**Meta Model API**

- No embeddings model and no embeddings endpoint exists
  (`https://dev.meta.ai/docs/models`, `https://dev.meta.ai/docs/api-reference`).
- `sam-3.1` accepts "Text prompt, image, video" and returns "Boxes and masks", priced at
  $2.50/1,000 images and $0.20/1,000 video frames
  (`https://dev.meta.ai/docs/pricing-rate-limits`).
- `stop`, `n`, `verbosity`, `logit_bias`, `prediction`, `web_search_options`,
  `modalities`, `audio`, `logprobs`, `top_logprobs` return **HTTP 400**, even though the
  published OpenAPI schema still lists several of them — the prose page is authoritative
  (`https://dev.meta.ai/docs/protocols/chat-completions`).
- `max_tokens` is deprecated in favour of `max_completion_tokens`.
- Auth is a static API key as `Authorization: Bearer $MODEL_API_KEY`; keys are prefixed
  `LLM_`.
- **Rate limits apply per team, not per API key.**
- `reasoning_effort` accepts `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
- Strict structured output requires a root object with `additionalProperties: false`.
- There is **no first-party Meta SDK**; the `openai` SDK with
  `base_url="https://api.meta.ai/v1"` is the documented path
  (`https://dev.meta.ai/docs/sdks`).

**Sign in with ChatGPT and plan inference**
(`https://developers.openai.com/siwc/quickstart`,
`https://developers.openai.com/siwc/token-sharing-open-source` and subpages,
`https://learn.chatgpt.com/docs/sign-in-with-chatgpt`)

- "Signing in and using your plan are separate permissions."
- Plan usage requires `offline_access resource.invoke chatgpt.tokens.use.direct`, and "a
  valid ID token alone does not authorize ChatGPT plan usage."
- Commercial access is waitlisted — "currently offered to a select group of commercial
  partners"; the self-service token-sharing path is scoped to open-source / locally hosted
  apps, and "paid or remotely hosted" apps are routed to an interest form.
- Unsupported on the plan route: **image generation, file search, Code Interpreter, the
  Files upload API, audio/video input.**
- Inference is `POST https://api.openai.com/v1/responses` with `store:false` and
  `stream:true` mandatory.
- Only **Plus and Pro** are named eligible. Free / Business / Enterprise: not stated.
- There is **no allowance-remaining API**; exhaustion appears only as a 429
  `subscription_sharing_usage_limit_exceeded`, possibly **mid-stream** as a
  `response.failed` event.
- There is **no revocation webhook** — OpenAI "does not currently notify your tool when a
  user disconnects the app in ChatGPT settings."
- PKCE S256 is required; endpoints are
  `https://auth.openai.com/api/accounts/authorize`, `/api/accounts/oauth/token`,
  `/api/accounts/oauth/revoke`.
- **Verified as not stated**: there is no native-mobile guidance. Custom URI schemes are
  neither permitted nor forbidden, and the documented OSS flow requires a `127.0.0.1`
  loopback a sandboxed mobile app cannot host. Hence the backend code exchange.

**Expo SDK 58** (`https://expo.dev/changelog/sdk-58`,
`https://docs.expo.dev/router/migrate/sdk-57-to-58/`,
`https://docs.expo.dev/versions/v58.0.0/sdk/sharing/`)

- `expo-sharing` supports *receiving* shares via `useIncomingShare()` plus a
  share-extension config plugin; shares arrive as a deep link with hostname
  `expo-sharing`, routed in `+native-intent.ts`. The iOS share extension is documented as
  experimental.
- Push notifications require a **development build** on both platforms; local
  notifications still work in Expo Go.
- Android release builds enable **R8 minification by default**.
- `expo-av` is removed; audio is `expo-audio`, video is `expo-video`.
- There is **no first-party speech-to-text module**.
- RN 0.88 / SDK 58 require Node 22.13+, 24.3+, or 26+ and **explicitly exclude
  odd-numbered releases**. This machine runs **25.2.1** — unsupported, and the cause of
  the `EBADENGINE` warning. It must be corrected before any release build.
- iOS builds from this Windows machine are only possible via **EAS Build**; Xcode is
  macOS-only.

### Assumed — not verified, must be checked before anyone relies on it

| Assumption | Why it matters | How to resolve it |
| --- | --- | --- |
| Per-model pricing for `muse-spark-1.3`, `muse-wonder-1.0`, `muse-image-1.0`, and `muse-voice-transcribe-1.0` | Every cost projection and the free tier's ceiling depend on it. Only `sam-3.1` pricing was captured on 2026-10-26 | Re-read `https://dev.meta.ai/docs/pricing-rate-limits` and record each figure with its date before publishing a budget |
| The numeric value of Meta's per-team rate limits | The team-wide concurrency limiter needs a number, not a shape | Re-read the pricing/rate-limit page and record the figures |
| Apple's and Google's exact store, billing, and review requirements | They gate the entire monetisation path and the store release | Read the canonical pages and record what they say; none of these were fetched on 2026-10-26 |
| third-party embed terms | They govern what we may render, and the policy in ADR-009 is deliberately more conservative than any of them | Read each platform's embed terms before shipping embeds, and record the date |
| Cloud Run's request timeout ceiling | It is the stated constraint behind queueing all model work | Measure it; ADR-013 names this as the thing to verify |
| `pool_size=10, max_overflow=5` for the database pool | A first guess, explicitly labelled an assumption in the plan | Revisit with the Task 15 load profile |
| That any payout provider supports payouts to Kenya on acceptable terms | The whole creator-earnings path rests on it | Evaluate candidates and record the finding — this is the programme's most consequential unverified assumption |
| That a weather provider's free or low tier permits commercial mobile use | A licence problem, not a technical one, and it is easy to discover too late | Read the licence terms during selection and record them |

---

## Standing invariants that no credential changes

These hold regardless of which credentials arrive, and no integration may be configured
around them.

1. **No integration is `live`.** This document contains no `live` row, and none may be
   added until a credential is in Secret Manager and a deployed environment is calling the
   real vendor.
2. **A fixture never reads as a live integration** — in the UI, in logs, or in a demo.
   `fixture` here and `simulated` in `ROADMAP.md` must agree before any screen claims a
   live integration.
3. **Capabilities are declared, never guessed.** Each adapter publishes a
   `ProviderCapabilities` record, and a request for an unsupported modality fails **before
   any network call**. Two verified asymmetries force this: Meta has image generation but
   no embeddings, and the ChatGPT-plan route has neither image generation nor file/audio
   upload.
4. **Image generation never routes to the ChatGPT-plan path, in any state.**
5. **No platform media is downloaded, stored, or analysed.** Instagram, TikTok, and
   Third-party content is a reference plus attribution; analysis runs only on user-supplied
   media.
6. **Every server-side URL touch goes through one SSRF-guarded fetcher** — scheme
   allowlist, DNS pinned and re-checked after each redirect, private / link-local /
   cloud-metadata ranges denied, redirect cap, byte cap, timeout, and content type verified
   against sniffed bytes rather than the declared header.
7. **No secret has a default.** `Settings` raises rather than falling back, and
   `meta_api_key` has no default value anywhere.
8. **Logs are redacted** of `authorization`, `access_token`, `refresh_token`, `latitude`,
   `longitude`, and image bytes.
