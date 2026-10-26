# Capacity worksheet

Status date 2026-10-27. **Every number here is an assumption until measured.** Nothing
in this document has been load-tested; it exists to find the constraints that bind
before we spend money discovering them, and to say plainly which ones already do.

Provider limits and prices are **verified** from
`https://dev.meta.ai/docs/pricing-rate-limits` (2026-10-26). Everything else —
engagement rates, request mixes, service times, media sizes — is **assumed**, with the
reasoning stated so each can be replaced by a measurement rather than re-argued.

---

## Headline: two constraints bind before infrastructure does

1. **Meta's published token throughput limit is the first hard ceiling.** At the
   scale-target scenario the stylist alone needs ~4M tokens/minute *at average load*,
   which is exactly the published per-team TPM limit — so peak exceeds it roughly
   fourfold. Infrastructure is nowhere near saturated at that point. This is a
   commercial negotiation and an architecture problem, not a scaling problem.
2. **A genuinely free AI tier is the dominant unit cost.** On standard pricing a
   single stylist run costs roughly 4.6¢, so an unmetered free tier at 18,000 DAU runs
   to about $10,000/month. The capped allowance in §4 of the brief is not a
   nice-to-have; the economics require it.

Both are visible from arithmetic alone, which is why this document exists before the
load tests.

---

## Scenarios

Labelled A–D. Only A is close to observable today.

| | **A Demo** | **B Private alpha** | **C Commercial launch** | **D Scale target** |
|---|---|---|---|---|
| Registered | 50 | 2,000 | 200,000 | 5,000,000 |
| MAU | 45 | 1,200 | 60,000 | 1,500,000 |
| DAU | 30 | 500 | 18,000 | 450,000 |
| DAU/MAU | 0.67 | 0.42 | 0.30 | 0.30 |

**DAU/MAU = 0.30** for C and D: typical for a social app with a utility core, below a
messaging app (0.5+) and above pure commerce (0.1). *Assumed.* The ratio matters more
than it looks — it is the multiplier on every figure below.

---

## Request volume

The brief's formula, used verbatim:

```
average requests per second = DAU × requests per user per day ÷ 86,400
peak requests per second    = average × peak factor
```

**Requests per user per day ≈ 35**, built from the journeys rather than guessed:

| Activity | Requests | Reasoning |
|---|---|---|
| Session bootstrap | 12 | 3 sessions/day × 4 (identity, feed page, wardrobe summary, notifications) |
| Discover browsing | 3 | 3 cursor pages |
| Wardrobe views | 2 | |
| Community feed | 8 | 8 cursor pages while scrolling |
| Engagement writes | 3 | likes, saves, comments |
| Misc + run polling | 7 | settings, profile, stylist run status |
| **Total** | **35** | *Assumed* |

**Peak factor 4.** Fashion engagement concentrates in the evening; a 4× peak-to-average
over a 24-hour mean is a conservative starting point for a single-region audience, and
is the number to replace first with a measurement. *Assumed.*

| | A | B | C | D |
|---|---|---|---|---|
| Requests/day | 1,050 | 17,500 | 630,000 | 15,750,000 |
| **Average RPS** | 0.01 | 0.20 | **7.3** | **182** |
| **Peak RPS** | 0.05 | 0.81 | **29** | **729** |

At **4 database operations per request** (*assumed*: one cached identity check plus one
to three owner-scoped queries):

| | C | D |
|---|---|---|
| Peak DB ops/s | 117 | 2,916 |

**Reading:** 729 peak RPS is unremarkable for stateless Cloud Run replicas, and 2,916
DB ops/s is within a well-indexed Cloud SQL instance with read replicas for feed reads.
Ordinary API traffic is not the problem.

---

## AI work — the binding constraint

In-flight work from Little's law, as the brief specifies:

```
concurrent runs = arrival rate × average service time
```

**Stylist runs per DAU per day = 0.4.** Styling is deliberate, not idle browsing; most
users will not style daily. *Assumed, and the single most important number here* — the
whole AI cost and throughput model scales linearly off it.

**Average service time = 25 s.** A bounded agent loop with up to 8 tool calls, several
model turns, and validation. *Assumed.*

**Model calls per run = 4**, at **~8,000 input tokens** each (system prompt, versioned
template, retrieved wardrobe, regional context, tool results) and **~1,500 output
tokens** total. The agent loop re-sends accumulated context each turn, so input
dominates — that is the mechanism behind the ceiling below.

| | A | B | C | D |
|---|---|---|---|---|
| Runs/day | 12 | 200 | 7,200 | 180,000 |
| Average runs/s | 0.0001 | 0.0023 | 0.083 | 2.08 |
| Peak runs/s (×4) | 0.0006 | 0.009 | 0.33 | 8.33 |
| **Concurrent runs at peak** | <1 | <1 | **8.3** | **208** |
| Peak model calls/min | 0 | 2 | 80 | **2,000** |
| Average tokens/min | 279 | 4,653 | 167,500 | **4,187,500** |
| Peak tokens/min | 1,117 | 18,611 | 670,000 | **16,750,000** |

### Against the verified published limits

Meta's limits are **per team, not per API key** — so adding keys does not help.

| Limit (verified) | `muse-spark-1.3` | Scenario C peak | Scenario D average | Scenario D peak |
|---|---|---|---|---|
| Requests/min | 3,000 | 80 ✅ 3% | 500 ✅ 17% | 2,000 ⚠️ 67% |
| **Tokens/min** | **4,000,000** | 670k ✅ 17% | **4.19M 🔴 over limit** | **16.75M 🔴 4.2× over** |

**This is the finding.** Scenario D exceeds the published TPM ceiling at *average*
load, before any peak is applied, and overruns it 4.2× at peak. Scenario C is
comfortable at 17% of the limit — so the ceiling arrives somewhere between 18,000 and
450,000 DAU, and finding where is a measurement worth doing early. Options, in the
order they should be tried:

1. **Prompt caching.** Verified pricing: cached input is $0.20/1M against $4.00/1M for
   `muse-wonder-1.0` — a 20× cost reduction, via `prompt_cache_key` and
   `prompt_cache_retention`. Whether cached tokens also count against TPM is **not
   stated in the docs and must be confirmed**; if they are discounted, this alone moves
   the ceiling materially.
2. **Shrink the retrieved context.** 8,000 input tokens per call is a design choice,
   not a given. Sending 15 candidate garments instead of a whole wardrobe is the
   single largest lever we control, and ADR-004's attribute retrieval already makes
   that selection cheap.
3. **Fewer turns.** 4 calls per run assumes the loop iterates. Validating
   deterministically in Python after one good turn — which ADR-010 already requires —
   should bring the common case to 2.
4. **Negotiate the team limit**, and treat a quota increase as a launch dependency
   rather than an afterthought.

Note `muse-image-1.0` is limited to **150 RPM**, so lookbook generation needs its own
queue and its own backpressure — it cannot share the stylist's concurrency budget.

---

## AI cost — why the free tier must be capped

Per run at standard `muse-spark-1.3` pricing (verified: $1.25/1M input, $4.25/1M
output):

```
input   32,000 tokens × $1.25/1M = $0.0400
output   1,500 tokens × $4.25/1M = $0.0064
                                   ───────
per run                            $0.0464
```

| | C (7,200 runs/day) | D (180,000 runs/day) |
|---|---|---|
| Standard pricing | **$334/day ≈ $10,017/mo** | **$8,348/day ≈ $250,425/mo** |
| With contributor-mode pricing¹ | $25/day ≈ $756/mo | $630/day ≈ $18,900/mo |
| Per DAU per month | $0.56 | $0.56 |

¹ Contributor mode is verified at $0.10/1M input and $0.20/1M output — 13× cheaper
per run ($0.0035 against $0.0464) — but it is a different product posture (rate-limited to 150 RPM, which caps it
at scenario C) and its terms need reading before it is assumed.

**$0.56 per DAU per month on AI alone** is the number that decides the business model.
It is why §4's capped app-funded allowance, paid tiers, and the per-request billing
source are structural rather than optional — and why a user's own ChatGPT plan, where
approved, is commercially interesting despite being unable to carry image generation.

Segmentation is also implied: if 10% of users do 80% of styling, a flat free allowance
is strictly worse than a small one plus a cheap paid tier.

---

## Media, storage and delivery

**Assumed** per user: 40 garments, each a ~1.5 MB original plus four derivatives
(thumb, grid, detail, lookbook) totalling ~400 KB → **~1.9 MB per garment**.

| | C (200k registered) | D (5M registered) |
|---|---|---|
| Stored media | 14.5 TB | 362 TB |
| GCS standard at $0.020/GB/mo | ~$297/mo | ~$7,422/mo |

**CDN egress**, at 60 image loads per DAU per day and 120 KB per responsive derivative:

| | C | D |
|---|---|---|
| Egress/day | 124 GB | 3.0 TB |
| Egress/month | 3.6 TB | 90.5 TB |
| At $0.08/GB | ~$297/mo | ~$7,416/mo |

**Upload volume** at 0.5 new garments per DAU per day: C → 9,000 uploads/day
(~0.1/s average, 0.4/s peak); D → 225,000/day (2.6/s average, 10.4/s peak). Media
workers are the elastic component here, and because uploads go device→GCS directly the
API never carries the bytes.

Derivative generation at D is ~225,000 × 4 = 900,000 renders/day. At 1.5 s of CPU each
that is ~16 CPU-hours/day — trivially parallel, and the reason derivative work is a
queued job rather than a request-path operation.

**Segmentation cost**, if `sam-3.1` runs on every upload (verified $2.50/1,000
images): C → $22/day; D → $562/day. Worth gating behind an explicit user action
("select the garment in this photo") rather than running it unconditionally.

---

## Feed fan-out, notifications, financial writes

- **Feed distribution.** Read-time fan-out (query who you follow, then their recent
  posts) is correct until a creator has a very large following. A single creator with
  500,000 followers makes write-time fan-out 500,000 rows per post. The plan is
  read-time with a cached timeline for high-follower accounts — the crossover point is
  a measurement, not a guess, and it is tracked rather than pre-optimised.
- **Notifications.** At 3 per DAU per day: C → 54,000/day; D → 1.35M/day (~16/s
  average). Well within FCM and APNs, but it needs its own queue so a notification
  storm cannot starve media work.
- **Financial writes.** Ledger entries are low-volume and high-consequence. Even at D,
  subscriptions plus gifts are unlikely to exceed a few writes per second. They get a
  separate connection budget precisely because they must never be starved by feed
  reads.

---

## Targets to measure against

From the brief, to be measured on named hardware rather than asserted:

| Target | Condition |
|---|---|
| p95 non-AI API latency < 500 ms | At scenario C peak (29 RPS), Cloud Run with a warm pool |
| First useful feed < 2 s | Reference device on a throttled 4G profile, cold cache |
| Smooth scroll (no dropped frames) | Reference mid-range Android, 60-item virtualised feed |
| AI time-to-first-result | Measured **separately** from completion — a 25 s run with a 2 s first token is a different product from one that shows nothing for 25 s |

**Reference devices** must be named before any of these is claimed. Proposal: a
mid-range Android (approximately a Pixel 6a / Galaxy A54 class device) and a current
baseline iPhone, on a throttled connection. Not yet fixed.

---

## Checking the arithmetic

Every figure above is reproduced by `scripts/capacity_model.py`, so a changed
assumption propagates rather than being hand-edited in a table. Run it with:

```bash
python scripts/capacity_model.py
```

Writing this document by hand first produced a real error — the peak factor applied
twice — which overstated scenario C's token usage fourfold and led to the wrong
conclusion that C had no headroom. Hence the script.

## How these numbers get replaced

The load profile belongs in `tests/load/locustfile.py` and is **not yet written**.
When it is, it must report actual throughput, concurrency, duration, latency
percentiles, error rates, saturation and cost — and it must keep two things apart:

- **mocked-provider runs**, which measure *our* capacity and can be run freely; and
- **small budgeted live-AI runs**, which measure the provider and cost real money.

Presenting one as the other would make every number above worthless. Until that
profile runs, this document contains no measurements — only arithmetic and the
constraints it reveals.
