#!/usr/bin/env bash
# Register one Expo Go redirect URI against the *running* local realm.
#
# Expo Go has no custom scheme, so `makeRedirectUri` returns
# `exp://<host>/--/callback`, and the host changes every time a tunnel
# restarts. A wildcard would cover that and is deliberately NOT in the
# committed realm: an imported `exp://*` would let any application that
# registers the `exp` scheme receive an authorisation code, and it would be
# inherited by every environment built from this file.
#
# So the exact URI is added at runtime instead, to a realm that only ever
# runs on a developer's machine. Nothing is committed and no other
# environment can pick it up.
#
#   ./add-expo-redirect.sh exp://c-xxxx.on.expo.app/--/callback
#
# The cleaner answer, once there is one, is a development build: it carries
# the `luxish` scheme, so `luxish://callback` already in the realm is all it
# needs and this script becomes unnecessary.
set -euo pipefail

URI="${1:-}"

# `--from-logs` reads the URI Keycloak actually rejected instead of guessing.
# This is the reliable way: `makeRedirectUri` resolves differently depending
# on how Expo Go loaded the app, so the host is not predictable from the
# tunnel URL, and Keycloak records the exact value it refused.
if [[ "$URI" == "--from-logs" ]]; then
  CONTAINER="${KEYCLOAK_CONTAINER:-luxish-keycloak-1}"
  URI=$(docker logs "$CONTAINER" --tail 400 2>&1     | grep -o 'error="invalid_redirect_uri", redirect_uri="[^"]*"'     | tail -1 | sed 's/.*redirect_uri="//; s/"$//')
  if [[ -z "$URI" ]]; then
    echo "no rejected redirect_uri in the last 400 log lines." >&2
    echo "Try signing in once first, so there is a rejection to read." >&2
    exit 1
  fi
  echo "read from logs: $URI"
fi

if [[ -z "$URI" ]]; then
  echo "usage: $0 exp://<host>/--/callback" >&2
  echo "       $0 --from-logs      # register whatever Keycloak last refused" >&2
  exit 2
fi
if [[ "$URI" != exp://* ]]; then
  echo "refusing: expected an exp:// URI, got $URI" >&2
  exit 2
fi
if [[ "$URI" == *"*"* ]]; then
  echo "refusing: wildcards defeat the point of this script" >&2
  exit 2
fi

KC="${KEYCLOAK_URL:-http://localhost:55080}"
REALM="${KEYCLOAK_REALM:-luxish}"
CLIENT="${KEYCLOAK_CLIENT:-luxish-mobile}"

TOKEN=$(curl -sf --max-time 15 \
  -d "client_id=admin-cli" -d "username=${KEYCLOAK_ADMIN:-admin}" \
  -d "password=${KEYCLOAK_ADMIN_PASSWORD:-admin}" -d "grant_type=password" \
  "$KC/realms/master/protocol/openid-connect/token" \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

ID=$(curl -sf -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/clients?clientId=$CLIENT" \
  | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")

CURRENT=$(curl -sf -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/clients/$ID" \
  | python -c "import sys,json;print(json.dumps(json.load(sys.stdin)['redirectUris']))")

BODY=$(URI="$URI" CURRENT="$CURRENT" python - <<'PY'
import json, os
uris = json.loads(os.environ["CURRENT"])
new = os.environ["URI"]
if new not in uris:
    uris.append(new)
print(json.dumps({"redirectUris": uris}))
PY
)

curl -sf -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$BODY" "$KC/admin/realms/$REALM/clients/$ID"

echo "registered: $URI"
