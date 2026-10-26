@apps/mobile/AGENTS.md

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
- No code downloads Instagram/TikTok/Pinterest media. Links are stored as references
  with attribution; analysis runs on user-supplied media only.
- Label every capability as implemented, simulated, blocked, or planned. A fixture must
  never read as a live integration.
