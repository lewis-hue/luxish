# ADR-017: Where fashion imagery comes from

Status date 2026-10-27. Verified against the providers' live licence, API-terms and
guideline pages on 2026-10-26/27. Not legal advice — the clauses quoted are the ones a
reviewer will hold us to, and two of them should be confirmed in writing before launch.

---

## The decision

Four layers, each with a different source and a different legal basis:

| Layer | Source | Basis | Status |
|---|---|---|---|
| **Product imagery** (shopping, offers) | Affiliate product feeds — **Impact** first, then CJ, then Rakuten | Per-advertiser programme terms | `blocked` — network + per-brand approval |
| **Editorial imagery** (Discover, style tiles) | **Generated** with `muse-image-1.0`; Shutterstock paid API only if a real photographic look is required | Our own output / Platform Licence | `planned` |
| **Wardrobe imagery** | The user's own camera and library | The user owns it | `planned` — Task 5 |
| **Creator imagery** (community) | Contributed under a recorded consent grant | Creator agreement | `planned` — Phase C |

**Free stock (Unsplash, Pexels) is rejected as the primary source.** It may later appear
as a secondary moodboard feature, under the constraints below.

---

## Why free stock is rejected — the clause that decides it

This was the surprise, and it is not the caching question everyone expects. Both
providers prohibit *the shape of app we are building*, independently of attribution or
hosting:

- **Unsplash** API Guidelines: "You cannot replicate the core user experience of
  Unsplash (unofficial clients, wallpaper applications, etc.)." Their own published
  test is whether the app "offers more value than simply the Unsplash integration",
  with the rejected example being "a wallpaper app returns Unsplash images for
  downloading. Without the integration, the app has no content and no value to users."
  A discovery grid whose tiles *are* Unsplash fashion photos is that example.
- **Pexels** has a help article titled almost exactly our use case, answered:
  "Copying the core functionality of Pexels is strictly forbidden under our Terms of
  Service and will result in having your API key revoked… wallpaper apps and creating
  your own free image/video library is not supported within our eligibility
  requirements."

Two further Unsplash clauses compound it: the guidelines list "displaying advertising
near to the API content", "charging for access to the API" and "training AI models"
among things to avoid — and we have paid AI subscriptions and affiliate monetisation in
the same product. Unsplash API Terms §4 also forbids aggregating their content with
third-party content "such that users… cannot attribute the Content to Unsplash", which
is precisely a mixed grid of inspiration photos and affiliate products.

**And the hosting constraint, which would have forced an architecture change on its
own.** Unsplash API Terms §6 requires hotlinking their URLs and states that failure
"will constitute a material breach". So no CDN derivative, no resizing, no
`expo-image` disk cache of our own copy — the opposite of every performance practice
we would otherwise apply. Pexels is friendlier: caching *responses* for ~24h is
explicitly endorsed, while ToS §8 prohibits "bulk, large-scale or systematic copying of
Content". Pexels also requires propagating takedowns into our own storage, which means
a cache purge path we would have to build.

If free stock is ever added as a secondary feature, these are the non-negotiables:
hotlink Unsplash (never re-host), fire the `photo.links.download_location` endpoint on
use, attribute with `?utm_source=…&utm_medium=referral`, cache only Pexels *metadata*,
and keep it visibly a side feature rather than the content of the app.

---

## Why affiliate feeds are the real content layer

They solve two problems at once: the imagery is licensed by the brand that owns the
product, and the feed carries the identifiers our match classifier needs. `MatchLabel`
(plan Task 11) can only return `confirmed_item` on identifier agreement — GTIN, MPN or
retailer product id — and these feeds are where those come from.

Ranked by fit:

1. **Impact** — best identifier coverage (`Gtin` plus an explicit `GtinType`, `Mpn`,
   `Asin`, `ParentSku`, `CatalogItemId`) and the only network supplying both `Url` and
   a prebuilt `MobileUrl`. iOS and Android need separate channels. Catalog REST API,
   3,000 req/hour.
2. **CJ** — best API ergonomics (GraphQL plus a streaming catalogue subscription),
   `gtin`/`mpn`/`brand`, 500 calls per 5 minutes.
3. **Rakuten** — SFTP feed delivery only, no catalogue API; `SKU` required, UPC
   optional. Strictest disclosure rules of the three.

**Three things to settle in writing before building against them:**

- **Image display rights are per-advertiser, not per-network.** None of the three
  networks grants the right to display product images; that lives in each advertiser's
  programme terms. So the schema needs a **per-brand image permission register**, and
  the offer renderer must consult it rather than assuming a feed URL implies a display
  right. This is a data-model consequence, recorded in Task 11.
- **Rakuten may classify us as a "Dynamic Shopping Ad" application.** Their network
  policies define DSA to include "AI-powered shopping assistants and recommendation
  tools, and other downloadable or installable technology (including mobile
  applications)", and require approval plus compliance testing "prior to launching".
  That is us, described almost exactly.
- **CJ's API terms prohibit deriving income without written permission** — "derive
  income from the use or provision of the CJ APIs… without CJ's prior, express, written
  permission". A paid-subscription app on CJ data needs that permission explicitly.

Affiliate disclosure is required by FTC 16 CFR Part 255 regardless of any contract, and
Rakuten's own rules are more prescriptive still (on every page, above the fold,
beginning with the word "Disclosure:", not black or grey).

---

## Generated imagery

`muse-image-1.0` is already a verified provider with both generation and editing
(ADR-005/007), so editorial covers and lookbook imagery cost no new vendor. Every
generated image carries `isGenerated: true` and renders a visible disclosure badge,
which Google Play's AI-generated content policy requires. It is never presented as a
real product, proof of fit, or proof of ownership (§8).

One alternative worth noting for later: **Black Forest Labs FLUX** has a hosted API
granting commercial use of outputs, and ships a **Virtual Try-On** tool that is
directly on-point for this product. Its open `[dev]` weights are *non-commercial* —
and the trap there is that the licence says "You may use Output for any purpose
(including for commercial purposes)" while a separate clause forbids running the model
commercially at all, so output rights do not rescue a commercial deployment.
`[schnell]` is Apache-2.0 and safe.

**Midjourney is unusable programmatically.** It has no official API, and its terms
prohibit automation outright: "Midjourney does not provide an API… automating
interactions with Midjourney service is strictly prohibited." Every commercial
"Midjourney API" is an unofficial wrapper operating in breach, with ban risk falling on
the account holder.

---

## Training data — DeepFashion is off the table

This corrects a common assumption, and it matters because §7 plans a training pipeline.

- **DeepFashion** is "available for non-commercial research purposes only", and the
  prohibition explicitly reaches "any portion of derived data" — which plausibly
  includes trained weights. The licence never uses the word "model", so weight
  inheritance is *not stated*; but clause 1 confines all use to non-commercial
  research, so silence here is dangerous, not permissive. Unusable for a paid app.
- **DeepFashion2 is worse**, not better: it has **no licence at all** (no LICENSE file,
  no statement in the paper), over third-party retailer photographs. No licence means
  no permission granted.
- A real trap: **the same images can carry different terms depending on which copy you
  download.** Fashionpedia from its own CVDF mirror has no non-commercial clause; the
  same imagery redistributed as iMaterialist Fashion on Kaggle adds "non-commercial
  research and educational purposes" only.

**Use instead**, in order of usefulness:

| Dataset | Licence | Why |
|---|---|---|
| **Amazon Berkeley Objects (ABO)** | CC BY 4.0 | 147k products / 398k catalogue images; Amazon is the actual rights holder |
| **FEIDEGGER** (Zalando) | MIT | 8,732 dresses with descriptive captions; licensor owns the images |
| **Fashion-MNIST** | MIT | Legally spotless, but 28×28 greyscale — weak in practice |

The discipline worth keeping: prefer datasets where **the licensor demonstrably owns
the photographs**. Many popular fashion datasets carry a permissive tag applied by an
uploader who does not own the imagery, which grants nothing.

---

## A useful consequence: this partly answers ADR-004's embeddings gap

ADR-004 deferred vector retrieval because the Meta Model API has no embeddings
endpoint, and named Vertex AI multimodal embeddings as the eventual candidate. There is
a better option for a fashion product: **`Marqo/marqo-fashionSigLIP` and
`Marqo/marqo-fashionCLIP` are Apache-2.0**, and `patrickjohncyh/fashion-clip` is MIT —
fashion-domain image+text embedding models with commercial-use weight licences,
self-hostable, no per-call vendor cost.

That makes the eventual "find visually similar" feature cheaper and domain-specific
rather than generic. It does **not** change ADR-004's decision to defer: the trigger is
still measured retrieval failure, and self-hosting a model adds its own operational
cost. It changes the *answer* we reach for when the trigger fires. Caveat: the
Apache-2.0 grant is the publisher's representation about their weights, not independent
provenance verification of what those weights were trained on.

---

## Delivery, and one correction to the brief's suggestion

- **Use `expo-image`, not `react-native-fast-image`.** `expo-image` is already a
  dependency, is the current Expo-recommended module, and provides disk and memory
  caching, blurhash/thumbhash placeholders, and prefetch. `react-native-fast-image`
  would add a native dependency and a development build for capability we already have.
  `StyleTile` sets `cachePolicy="memory-disk"` for exactly this reason.
- **Do not add Cloudinary or Imgix yet.** Derivative generation is already a media
  worker job (plan Task 6) writing to GCS behind Cloud CDN, and the derivative set is
  small and known because we control the aspect ratios. A transformation CDN is a third
  vendor and a recurring cost to solve a problem we do not have; revisit only if we
  need arbitrary on-the-fly transforms. Note that for any Unsplash-sourced image a
  transformation CDN would be *prohibited* anyway.
- **Aspect-ratio consistency is already enforced** in tokens — `AspectRatio.editorial`
  (3:4), `garment` (1:1), `reel` (9:16) — so tiles cannot reflow as images load. This
  matches the brief's recommendation; it is in `constants/theme.ts` rather than left to
  each screen.

---

## Could not verify — do not treat as settled

- Shutterstock's **current** API terms of service: live page is bot-blocked and the
  Internet Archive has been 403 since Dec 2023. The 2019 archived text contains "your
  Platform must have a business purpose separate and apart from distributing Content",
  which would matter to us. Obtain the current terms in writing before building.
- Shutterstock caching/CDN rights: not stated publicly.
- CJ's Publisher Service Agreement (login-walled) — the likely home of its disclosure
  obligation.
- Whether building an embedding index counts as a prohibited "dataset" under
  Shutterstock's AI clause: not stated.
- Getty/iStock: their standard Web Services Addendum prohibits third-party access to
  the API, so a consumer app needs a negotiated agreement. No self-serve path exists.
