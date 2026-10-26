# Terraform — GCP infrastructure

**Status: written, not validated.** The authoring machine has no `terraform` CLI, so
`terraform fmt` and `terraform validate` have never run against these files. A CI job
(`terraform` in `.github/workflows/ci.yml`) runs both with `-backend=false`, and that
job is the first real check this configuration gets. Expect to fix syntax on the first
CI run; do not treat `terraform apply` as safe until that job is green.

## Layout

A single flat configuration, not a module hierarchy — three near-identical
environments and one team, so modules would add indirection without removing
duplication (ADR-013).

| File | Contents |
|---|---|
| `main.tf` | APIs, VPC, Cloud SQL, buckets, Cloud Tasks queues, secrets, service accounts, Artifact Registry |
| `run.tf` | Cloud Run services: API, five worker classes, Keycloak |
| `variables.tf` | Inputs, with the reasoning for each default |
| `outputs.tf` | URLs, bucket names, secret ids |
| `example.tfvars` | Template — copy per environment, never commit a filled copy |

## Usage

```bash
cd infra/terraform
terraform init -backend-config="bucket=YOUR_STATE_BUCKET" -backend-config="prefix=dev"
terraform plan  -var-file=dev.tfvars
terraform apply -var-file=dev.tfvars
```

Secrets are created **empty** on purpose, so no credential enters Terraform state:

```bash
printf '%s' "$MODEL_API_KEY" | gcloud secrets versions add atelier-dev-model-api-key --data-file=-
```

## Decisions worth knowing before you change something

**Two media buckets, not one.** Private originals enforce
`public_access_prevention`; derivatives are separate. A single bucket with mixed
access is exactly how a private wardrobe photo ends up in a shared public cache,
which §16 forbids.

**No public database IP.** Cloud SQL is private-only and reached through a VPC
connector, because Cloud Run has no VPC presence of its own.

**Separate databases for the app and Keycloak** on one instance. Never a shared
schema: a realm import must not be able to reach application tables.

**One queue per work class.** So a notification storm cannot starve media
processing, and so each can be paused independently during an incident. `reconcile`
is deliberately capped at 2 instances — financial writes must be serialised, not
parallelised.

**Distinct service accounts per deployable.** Only the API holds
`serviceAccountTokenCreator`, because only the API mints signed upload URLs. Workers
read and write objects but never sign on a user's behalf.

**Worker concurrency is 1.** Concurrency per instance would let one slow job delay
unrelated ones and make progress reporting inaccurate.

**API request timeout is 60s.** All model work is queued, so no request should need
longer. This is the constraint ADR-013 routes around rather than raises.

### Keycloak on Cloud Run is a compromise

`min = max = 1`. Pinning to exactly one instance avoids Infinispan clustering
entirely, which removes the documented data-loss risk when members leave
concurrently — at the cost of a brief gap during deploys and no redundancy.

Keycloak's own docs discourage what scale-to-zero implies: a single instance is
"susceptible to availability issues", startup "will not be instantaneous", and on
Kubernetes it needs a StatefulSet's serial handling because "using a deployment is
not supported or recommended".

This is acceptable while sign-in volume is low and **not** acceptable at the
scale-target scenario in `docs/performance/capacity.md`. The production answer is a
GKE StatefulSet with `jdbc-ping` discovery and a distinct cache cluster name. Also
note GKE is supported only "in a best-effort manner"; OpenShift is the tested
platform.

Three settings here are load-bearing and easy to get wrong:
- `KC_PROXY_HEADERS=xforwarded` — without it, origin checking returns **403** on
  every proxied request. The old `proxy` option was removed in 26.0.
- `KC_CACHE_EMBEDDED_CLUSTER_NAME` — `jdbc-ping` discovers peers through the
  database, so two clusters sharing this instance would silently merge.
- Health probes target **port 9000**, not the HTTP port.

## Not covered yet

Tracked in `docs/ROADMAP.md`, absent here so nobody assumes otherwise: Cloud CDN and
custom domains, Cloud Armor, per-service IAM beyond these service accounts,
Memorystore (not yet justified), monitoring alert policies, and backup schedules
beyond Cloud SQL's built-in retention.
