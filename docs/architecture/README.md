# Architecture & Decision Record

Working name: **LUXish** (placeholder — see [Branding](#adr-002-centralised-configurable-branding)).
Status date: 2026-10-26. Target build window closes 2026-11-04 21:00 US Eastern / 2026-11-05 05:00 Nairobi.

> Every claim in this document is labelled. **Verified** = fetched from the vendor's
> live docs on 2026-10-26 with the URL recorded. **Assumed** = a reasonable default we
> chose, not yet measured. **Blocked** = needs a credential or an approval we do not have.

---

## 1. System shape

```
                     ┌──────────────────────────────┐
   iOS / Android      │  apps/mobile (Expo SDK 58)   │
   dev-client build   │  Expo Router · TanStack Query │
                     └───────────┬──────────────────┘
                                 │ HTTPS, bearer session JWT
                                 │ typed client generated from OpenAPI
                     ┌───────────▼──────────────────┐
                     │  services/api (FastAPI)      │  ← stateless replicas
                     │  auth · wardrobe · stylist   │
                     │  shopping · social · billing │
                     └──┬────────┬─────────┬────────┘
                        │        │         │
          ┌─────────────▼──┐  ┌──▼─────┐ ┌─▼──────────────┐
          │ PostgreSQL     │  │ Redis  │ │ Object storage │
          │ (Cloud SQL)    │  │ caches │ │ + CDN          │
          │ owner-scoped   │  │ limits │ │ private/public │
          └────────────────┘  └────────┘ └─▲──────────────┘
                        │                  │ direct device upload
          ┌─────────────▼──────────────┐   │ (short-lived signed URL)
          │ services/workers           │───┘
          │ media · ai · moderation    │
          │ notifications · reconcile  │
          └─────────────┬──────────────┘
                        │ capability-aware adapters
        ┌───────────────┼────────────────┬──────────────┐
        ▼               ▼                ▼              ▼
   Meta Model API   Vertex AI       Weather        Retailer
   (verified)       (assumed)       (assumed)      adapters

---

Full decision record with verified sources: [decisions.md](./decisions.md)
