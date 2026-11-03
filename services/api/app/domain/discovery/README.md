# Discovery

A staged recommender a staged retrieval and ranking design.

```
[ everything published ]
          |
   candidate retrieval        graph walk · looks-like · affinity · trending · fresh
          |                   ~2000 ids, five sources, none of them trusted
          v
   visibility gate            one read, all sources, private/blocked/hidden/deleted
          |
          v
   seen filter                what this person was already shown
          |
          v
   scoring                    per-source normalisation
          |
          v
   blending                   quotas · author and tag diversity · exploration
          |                   35 / 15 / 15 / 20 / 15
          |
          v
      [ one grid ]
```

## What is actually implemented

| The published design | Here | Where |
|---|---|---|
| Bipartite pin↔board graph | Yes. `moodboard_pins` is the edge table. | `graph.py` |
| random walk from a user's pins | Yes. Weighted starts, 2 hops, early stopping. | `graph.walk` |
| multi-hit booster | Yes. `(Σ√visits)²` per starting pin. | `graph.Visits.boosted` |
| Graph held in RAM, not queried per hop | Yes, in-process with a 5-minute deadline. | `store.cached_graph` |
| Trending by velocity, not volume | Yes. 24h against a 7-day baseline, with a floor. | `trending.rising` |
| Trending reserved per vertical | Yes, via `scope_tag`. | `trending.rising` |
| Seen-filter against recent impressions | Yes. Redis sorted set, 3-day window, capped. | `seen.RedisSeen` |
| Blending to target ratios | Yes. 35/15/15/20/15, largest-remainder. | `blend.quotas` |
| Epsilon-greedy exploration | Yes. The `fresh` slice, shuffled not ranked. | `blend.blend` |
| Diversity / de-duplication | Yes. Author runs and tag runs. | `blend.fits` |
| Why-am-I-seeing-this provenance | Yes. Every pin carries its source. | `pipeline.Explained` |
| Content signal independent of the uploader | Yes, via vision rather than embeddings. | `subject.py`, `workers/post_vision.py` |
| Visual-similarity retrieval (the embedding retriever slot) | Partly. Cosine over vocabulary vectors, not dense embeddings. | `pipeline._looks_like` |
| Topics derived from boards, not captions | Yes. Contradicted tags are discounted. | `annotate.py` |

## What is deliberately not implemented

**Kafka and Flink.** A platform at scale streams billions of events a day through
Kafka topics into stateful Flink jobs. This deployment has a few dozen accounts and 400
pins. The *shape* of that pipeline — an append-only event record, a
stateful aggregation over it, results written to a low-latency store —
is what `PostReaction`/`PostSave` (the log), `trending.rising` (the
aggregation) and `seen.RedisSeen` (the store) already do, synchronously,
because at this volume a synchronous aggregate is a few milliseconds.
Standing up Kafka and Flink for this would add two distributed systems
to operate and would not make a single answer better. The point at which
it stops being true is when `trending.rising` can no longer run inside a
request; the honest fix then is to precompute it on the existing Celery
beat, and only after *that* stops working does a streaming engine earn
its operational cost.

**Dense visual embeddings.** There is now a visual-similarity source,
but its vectors are not CLIP. The vendor has no embeddings model and no
embeddings endpoint — `POST /v1/embeddings` is a 404 on every model,
re-verified 2026-11-03 — so the content signal is a closed vocabulary
the vision model fills in (`subject.py`), turned into a unit vector.

Against real dense embeddings this is coarser in one specific way: two
pins that pick the same words are indistinguishable, where CLIP would
still separate them. It is better in two: every dimension has a name,
so provenance is explainable; and `subject` is a hard category that can
*gate*, which a distance cannot. That gate is what the whole thing was
built for — a cream boucle sofa and a cream knit dress are genuinely
close in any visual space and must still never sit under one another.

`subject.Embedder` is the seam. A CLIP or Vertex implementation drops in
without touching storage, retrieval or the pipeline; `post_vision.model`
records which embedder produced each row, so the table can be migrated
a post at a time. ADR-004's amendment of 2026-11-03 records the
reasoning and what is still open.

**Ads.** No ad system, so the slice usually reserved for ads is given to
the graph walk and exploration instead.

**A separate serving cluster.** A production graph service holds the graph
across many machines. This is a dict in the API process.

## Why the sources do not filter

Four retrieval paths each applying their own visibility rules is four
chances to forget one, and the thing being forgotten is a private
account's fit in a stranger's grid. So retrieval returns bare ids and is
not trusted: `pipeline._visible` re-reads every candidate through the
same predicates `feed.board` uses (`shown_to_strangers`,
`visible_author`, the deleted-author join), and anything that does not
come back is dropped. A source cannot leak by failing to filter, because
no source filters.

`tests/test_discovery_pipeline.py` holds that design in place — each of
the first five tests makes a pin *reachable* by a source and then asserts
it does not come out.

## Tuning

Everything adjustable is a module-level constant with the reasoning
beside it. The ones most likely to need moving:

- `blend.SHARES` — the mix. Starting point, not a finding.
- `subject.GOES_UNDER` — which subjects may be recommended under which.
  Every pair is a product decision, not a derivation; argue with it.
- `subject.SUBJECT_WEIGHT` — how hard subject dominates the facets
  inside the cosine. The gate is the real protection; this is belt and
  braces.
- `trending.BASELINE_FLOOR` — raise if new pins trend too easily.
- `seen.REMEMBER_SECONDS` — lower if a heavy user runs out of corpus.
- `graph.HOPS` — 2. At 3 this graph's boards overlap enough that the
  walk returns the general population.

## Reproducibility

Every stage takes an optional `random.Random`. Given a seed, the same
inputs produce the same grid. A recommender nobody can reproduce is one
nobody can debug, and "it looked wrong on my phone" is not actionable
without it.
