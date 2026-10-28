#!/usr/bin/env bash
# Allow the mobile client to exchange a username and password for a token,
# against the LOCAL realm only.
#
# Normally off, and it must stay off anywhere real. The browser flow exists so
# the app never handles a password: with the direct grant the password passes
# through the application, which is exactly what OAuth's authorization code
# flow is designed to avoid, and it bypasses anything the browser contributes
# — MFA, identity brokering, step-up, consent.
#
# It is here because a physical iPhone cannot run a development build without
# an Apple Developer account, and Expo Go's exp:// callback does not always
# return to the app, which leaves no way at all to obtain a token on-device.
# Real Keycloak, real tokens, real signature and issuer validation; only the
# browser round trip is skipped.
#
# Not in the committed realm import, for the same reason as the SMTP settings:
# that file is inherited, and a realm that permits password grants because a
# developer once needed one is a bad thing to inherit silently.
#
#   ./enable-dev-password-login.sh           # turn on
#   ./enable-dev-password-login.sh --off     # turn off again
set -euo pipefail

ENABLE=true
[[ "${1:-}" == "--off" ]] && ENABLE=false

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

curl -sf -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"directAccessGrantsEnabled\": $ENABLE}" \
  "$KC/admin/realms/$REALM/clients/$ID"

if [[ "$ENABLE" == "true" ]]; then
  echo "Direct password grant ENABLED on $REALM/$CLIENT. Local development only."
else
  echo "Direct password grant disabled on $REALM/$CLIENT."
fi
