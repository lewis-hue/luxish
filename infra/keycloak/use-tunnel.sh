#!/usr/bin/env bash
# Point the whole local stack at an HTTPS tunnel in front of Keycloak.
#
# WHY A TUNNEL AT ALL, when the phone can reach Keycloak on the LAN:
# Google refuses an OAuth redirect URI that is not HTTPS, with one exception
# — loopback. `http://192.168.100.2:55080/...` is neither, so "Continue with
# Google" cannot work against the LAN address no matter how fast it is.
# Email sign-in works fine either way; this exists for Google.
#
# WHY CLOUDFLARED AND NOT LOCALTUNNEL:
# localtunnel answered `/realms/luxish` but returned 403 on
# `/.well-known/openid-configuration` and on the JWKS endpoint — the two
# URLs OAuth cannot proceed without — and took about five seconds per
# request. cloudflared serves the same paths in well under a second.
#
# THE CATCH: a free cloudflared quick tunnel gets a new random hostname every
# time it starts. Keycloak stamps its hostname into every token's `iss`, and
# three files plus Google's console have to agree with it. This script does
# the three files; the Google one it prints, because only you can set it.
#
#   ./use-tunnel.sh              # start a tunnel and point everything at it
#   ./use-tunnel.sh <url>        # use a tunnel that is already running
#
# After this, restart Metro — EXPO_PUBLIC_* values are compiled into the
# bundle, so a running dev server keeps serving the old issuer.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
URL="${1:-}"

if [[ -z "$URL" ]]; then
  command -v cloudflared >/dev/null || {
    echo "cloudflared is not installed. npm i -g cloudflared" >&2
    exit 1
  }
  LOG="$(mktemp)"
  echo "starting a quick tunnel to localhost:55080 ..."
  cloudflared tunnel --url http://localhost:55080 >"$LOG" 2>&1 &
  for _ in $(seq 1 30); do
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
    [[ -n "$URL" ]] && break
    sleep 2
  done
  [[ -n "$URL" ]] || { echo "tunnel did not come up; see $LOG" >&2; exit 1; }
fi

echo "tunnel: $URL"

python - "$URL" "$REPO" <<'PY'
import re
import sys
from pathlib import Path

url, repo = sys.argv[1], Path(sys.argv[2])

edits = [
    (repo / "infra/.env", r"^KC_HOSTNAME=.*$", f"KC_HOSTNAME={url}"),
    (repo / "apps/mobile/.env", r"^EXPO_PUBLIC_KEYCLOAK_ISSUER=.*$",
     f"EXPO_PUBLIC_KEYCLOAK_ISSUER={url}/realms/luxish"),
    (repo / "services/api/.env", r"^LUXISH_KEYCLOAK_ISSUER=.*$",
     f"LUXISH_KEYCLOAK_ISSUER={url}/realms/luxish"),
]
for path, pattern, replacement in edits:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, flags=re.M)
    if count != 1:
        raise SystemExit(f"expected one match for {pattern} in {path}, found {count}")
    path.write_text(updated, encoding="utf-8")
    print(f"  {path.relative_to(repo)}")
PY

echo "restarting keycloak so it stamps the new hostname ..."
(cd "$REPO/infra" && docker compose up -d keycloak >/dev/null)

for _ in $(seq 1 30); do
  STATUS=$(docker inspect luxish-keycloak-1 --format '{{.State.Health.Status}}' 2>/dev/null || true)
  [[ "$STATUS" == "healthy" ]] && break
  sleep 5
done
echo "keycloak: ${STATUS:-unknown}"

ISSUER=$(curl -s --max-time 25 "$URL/realms/luxish/.well-known/openid-configuration" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["issuer"])' 2>/dev/null || echo "unreachable")
echo "issuer:  $ISSUER"

cat <<EOF

Two things only you can do:

  1. Add this to the Google Cloud console, under the OAuth client's
     "Authorised redirect URIs". Google rejects anything else:

       $URL/realms/luxish/broker/google/endpoint

  2. Restart Metro, so the app compiles the new issuer into its bundle:

       cd apps/mobile && npx expo start --clear

Email sign-in works without step 1. Google needs it.
EOF
