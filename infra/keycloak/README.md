# Keycloak realm — annotations and security controls

The realm is config-as-code in [`import/luxish-realm.json`](import/luxish-realm.json).
That file is kept **strictly schema-valid** — no comment keys — because an unknown
property risks the import failing or being silently skipped, which is an expensive
thing to debug. The rationale therefore lives here, keyed by JSON path.

Verified against Keycloak **26.8.1** docs and source on 2026-10-26. See ADR-016.

---

## Hard requirements that are easy to get wrong

| Thing | Requirement | Why it bites |
|---|---|---|
| Filename | **must** be `luxish-realm.json` | Keycloak requires `<realm name>-realm.json`. Any other name and the realm is not imported, with no obvious error. |
| Import directory | `/opt/keycloak/data/import` | Only `.json` files directly in it are read — **subdirectories are ignored**. |
| Import flag | `--import-realm` as a **CLI argument** | There is **no `KC_IMPORT_REALM` environment variable**. It is a plain picocli flag, so it must go in `command:`, not `environment:`. |
| Version floor | **≥ 26.8.1** | 26.8.1 fixed 22 CVEs, three in our blast radius: CVE-2026-82968 (persistent wrong-account linking), CVE-2026-15943 (masked client-secret reuse), CVE-2026-18569 (forged unsigned backchannel logout tokens). |
| Endpoint paths | **no `/auth` prefix** | Removed in Keycloak 17 when Quarkus became the default distribution. Discovery is `/realms/luxish/.well-known/openid-configuration`. |
| Secrets | only `${ENV_VAR}` placeholders | Keycloak resolves these at import. Note that **Admin Console exports mask secrets with asterisks** and are therefore unusable as config-as-code — only CLI exports round-trip. |
| Re-import | safe to leave on | If the realm exists, import is skipped — deliberately, to avoid losing state across restarts. To re-apply changes, delete the realm via the Admin API first. |

---

## `identityProviders[alias=google]` — this block is a security control

Two fields carry the account-takeover invariant the brief forbids us to break
("Prevent account takeover through unsafe email-based merging"). Neither is obvious
from reading the file.

### `trustEmail: false` — must stay false

Keycloak's own description: when on, "Keycloak trusts email addresses from the
identity provider… users that log in from this identity provider do not need to
perform the email verification process." Critically: "**If the claim is absent, the
Trust Email setting provides the default verification status.**"

Turning it on is the documented precondition for **CVE-2026-14781**, in which
`email_verified` is read from the IdP's `id_token` while the address itself is read
from the `userinfo` response — letting a hostile upstream provider get an arbitrary
address marked verified. The CVE notes `trustEmail=true` is explicitly *not* the
default; leaving it alone is the safe state.

### `firstBrokerLoginFlowAlias: "first broker login"` — must stay the stock flow

**The good news:** the default flow is already safe. A Google login whose email
matches an existing local account does **not** auto-link. It goes
`Create User If Unique` → `Handle Existing Account` → `Confirm Link Existing Account`
(the user must confirm) → then **`Verify Existing Account By Email`** or
**re-authentication with the existing password**. Proof of control is required.
Keycloak states the reasoning plainly: "Automatically linking the existing local
account to the external identity provider is a potential security hole. You cannot
always trust the information you get from the external identity provider."

**The hole is opt-in, and it is this:** replacing the flow with one built on the
`Automatically set existing user` authenticator (`idp-auto-link`), which "sets an
existing user to the authentication context **without verification**". Keycloak's
warning: "The AutoLink authenticator is dangerous in a generic environment where users
can register themselves using arbitrary usernames or email addresses."

There is **no per-IdP toggle for email auto-linking** — auto-linking is purely a
property of the selected First Login Flow. So this one field is the whole control.

Optional hardening: set `Create User If Unique` to **REQUIRED**, which makes a
duplicate-email brokered login fail outright and forces linking through the Account
Console.

**Defence in depth.** `services/api/app/security/keycloak.py` enforces the same
invariant independently: a token with `email_verified: false` never adopts a
pre-existing account, returning `409 identity_link_required`. That redundancy is
deliberate — this file is configuration, and configuration can be changed in a console
without a code review.

---

## `clients[luxish-mobile]`

- **Public client, PKCE required.** A phone binary cannot keep a secret, so there is
  none. The attribute is `pkce.code.challenge.method: "S256"` — in the admin console
  this surfaces as a **`Require PKCE`** toggle plus a **`PKCE Method`** select, not the
  older "Proof Key for Code Exchange Code Challenge Method" label. Keycloak's help
  text: "Public clients (client authentication disabled) should always require PKCE as
  they cannot securely store client secrets."
- **`luxish://callback` must be listed explicitly.** Keycloak is specific that for
  non-http(s) custom schemes, "it should be an explicit part of the validation pattern…
  For security reasons a general pattern like `*` does not cover non http(s) schemes."
  Redirect matching is exact and case-sensitive. The `127.0.0.1:8081` entries exist
  only for the Expo dev client in a browser and should be removed from the production
  realm.
- **`backchannel.logout.session.required: "true"`.** Keycloak only puts `sid` into a
  backchannel logout token when this is on; the attribute defaults to **false**, and
  the getter is a plain `Boolean.parseBoolean`, so unset means false. With it off, the
  API has to fall back to revoking every session belonging to `sub` — which works, but
  is coarser than necessary. `sub` is always present; `sid` is not.

### The `luxish-api-audience` protocol mapper is not optional

Without it, **token validation fails on every real request.** Keycloak deliberately
omits the requesting client from an access token's audience: "the frontend client
itself is **not automatically added to the access token audience**, therefore allowing
easy differentiation between the access token and the ID token."

This single `oidc-audience-mapper` is why `app/security/keycloak.py` can check `aud` at
all — and why that check is written to be **conditional**, so the service still works
against a realm where someone removed the mapper.

Related, for anyone tempted to use introspection instead: since **26.6.2** the
introspection endpoint validates that the authenticated client appears in the token's
`aud` and returns `{"active": false}` otherwise. Both opt-outs are already deprecated.
We validate JWTs locally against JWKS and do not introspect.

---

## Apple is deliberately absent

Keycloak ships **no Apple identity provider**, and the request to add one
([keycloak#15132](https://github.com/keycloak/keycloak/issues/15132)) is **closed as
`not_planned`**. Apple must be configured as a *generic OIDC provider*.

The real obstacle is the client secret. Apple requires an **ES256 JWT** signed with a
downloaded `.p8` key, with `iss` = Team ID and the `kid` header = Key ID, valid for at
most 6 months. Keycloak's generic OIDC provider, when set to private-key JWT
authentication, "uses the realm private key" with its own claim layout — so **Keycloak
will not mint or rotate an Apple-format secret.** Options:

1. Mint the ES256 assertion externally, write it into the IdP's `Client Secret` field,
   and rotate it on a schedule (≤6 months) with an alert before expiry.
2. Use the community Apple IdP extension, which builds the secret from the
   `.p8`/Team ID/Key ID.

This matters commercially, not just technically: **App Store Review Guideline 4.8**
expects an equivalent privacy-preserving login option once an app offers third-party
social login. Shipping Google without Apple on iOS is a plausible rejection. Tracked in
`docs/ROADMAP.md`.

*(Keycloak's docs never discuss Apple's secret format or its expiry, so the
incompatibility above is inferred from Keycloak's documented behaviour versus Apple's
published requirements — not from a Keycloak statement.)*

---

## Production differs from this file

`infra/docker-compose.yml` runs `start-dev`, which forces **local caches only** and is
documented as "intended only for development and testing purposes". Production needs:

- `start` (not `start-dev`), with `KC_HOSTNAME` set and `hostname-strict` left `true`.
- **`proxy-headers`** set to `forwarded` or `xforwarded` behind a load balancer. Omit it
  and you get **403 Forbidden** on proxied requests from origin checking — the old
  `proxy` option was removed in 26.0.
- A distinct `--cache-embedded-cluster-name`. The default `jdbc-ping` stack discovers
  nodes **via the database**, so two clusters sharing a database but intended to stay
  separate will silently merge.
- **Not scale-to-zero.** Keycloak's docs discourage a single instance ("susceptible to
  availability issues… full outage"), warn that embedded Infinispan "does not gracefully
  handle multiple members joining or leaving concurrently" with members leaving
  simultaneously able to cause **data loss**, and require serial pod handling — "using a
  deployment is not supported or recommended". So Cloud Run with scale-to-zero is the
  wrong host; use a min-one-instance deployment and accept the cost floor. Note GKE is
  supported only "in a best-effort manner"; OpenShift is the tested platform.
- Health probes on the **management port 9000**, not 8080: `/health/ready`,
  `/health/live`, `/health/started`, gated behind `KC_HEALTH_ENABLED`.
- Remove the `127.0.0.1` redirect URIs and the dev bootstrap admin.

---

## Local use

```bash
npm run dev:up                       # postgres + redis + keycloak
# Admin console: http://localhost:55080  (admin / admin)
# Discovery:     http://localhost:55080/realms/luxish/.well-known/openid-configuration
# Readiness:     http://localhost:55000/health/ready
```

Google sign-in stays inert locally until `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
are set — the placeholders import as the literal string `unset`, so the button appears
but cannot complete. That is intentional: it keeps the realm importable with no
credentials.
