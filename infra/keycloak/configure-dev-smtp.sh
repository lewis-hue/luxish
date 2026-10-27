#!/usr/bin/env bash
# Point the local realm at the Mailpit container, so verification emails work.
#
# Not in the committed realm import on purpose. That file is inherited by
# anything built from it, and a realm that believes its mail server is a
# container called "mailpit" would fail silently in any environment where
# that host does not exist — and failing to send a verification email is the
# kind of failure nobody notices until a user cannot sign up.
#
# The realm keeps `verifyEmail: true`, which is the behaviour that ships.
# This makes the local stack able to satisfy it rather than exempting it.
#
#   ./configure-dev-smtp.sh            # read the mail at http://localhost:55026
set -euo pipefail

KC="${KEYCLOAK_URL:-http://localhost:55080}"
REALM="${KEYCLOAK_REALM:-luxish}"

TOKEN=$(curl -sf --max-time 15 \
  -d "client_id=admin-cli" -d "username=${KEYCLOAK_ADMIN:-admin}" \
  -d "password=${KEYCLOAK_ADMIN_PASSWORD:-admin}" -d "grant_type=password" \
  "$KC/realms/master/protocol/openid-connect/token" \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Merge into the realm rather than PUT a bare object: a partial realm update
# in Keycloak replaces what it is given and leaves the rest, but sending only
# this key has been known to reset adjacent settings between versions.
CURRENT=$(curl -sf -H "Authorization: Bearer $TOKEN" "$KC/admin/realms/$REALM")

BODY=$(CURRENT="$CURRENT" python - <<'PY'
import json, os
realm = json.loads(os.environ["CURRENT"])
realm["smtpServer"] = {
    # The compose service name. Keycloak resolves it on the compose network.
    "host": "mailpit",
    "port": "1025",
    "from": "no-reply@luxish.local",
    "fromDisplayName": "LUXish (local)",
    "ssl": "false",
    "starttls": "false",
    "auth": "false",
}
print(json.dumps(realm))
PY
)

curl -sf -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "$BODY" "$KC/admin/realms/$REALM"

echo "SMTP pointed at mailpit. Read the mail at http://localhost:55026"
