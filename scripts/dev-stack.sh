#!/usr/bin/env bash
#
# Start every process the app needs locally, and refuse to look healthy
# without them.
#
# This exists because the stack has a silent failure mode. The API accepts an
# upload, writes a job row, returns 201, and reports healthy with no worker
# running anywhere. Nothing is wrong from the outside; the photograph simply
# never gets sorted, and the only symptom is a spinner on a phone. Starting
# the API by hand and forgetting the workers costs an hour of looking in the
# wrong place, so the workers are not optional here.
#
# One worker per queue rather than one worker serving all four. They are
# separate queues precisely so a slow job cannot delay a fast one, and a
# single solo-pool worker throws that away: categorisation is what ends the
# spinner, and behind outfit detection and background removal it waits about
# a minute instead of about ten seconds.
#
#   ./scripts/dev-stack.sh          start everything
#   ./scripts/dev-stack.sh stop     stop everything this started
#   ./scripts/dev-stack.sh status   what is actually running
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO/services/api"
LOGS="$REPO/.devlogs"
PY="$API_DIR/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$API_DIR/.venv/bin/python"

CELERY_APP="app.queue.celery_app:celery_app"
API_PORT="${LUXISH_API_PORT:-8010}"

# Keycloak's own port, and the https tunnel in front of it. Google will not
# register a non-https redirect URI unless the host is localhost, which a
# phone is not, so the tunnel is not optional for social sign-in.
KC_PORT="${LUXISH_KEYCLOAK_PORT:-55080}"
TUNNEL_LOG="$LOGS/tunnel.log"

# Opt in with `LUXISH_TUNNEL=1`. Off by default: see `keycloak_host` for
# why the LAN address is the better everyday answer.
USE_TUNNEL="${LUXISH_TUNNEL:-0}"

# Every file that pins the public Keycloak hostname. All three have to agree
# or sign-in fails, and they fail differently: the mobile one produces a URL
# that does not resolve, the API one produces `401 bad_issuer`, and the infra
# one makes Keycloak advertise an issuer nobody else believes.
HOST_PINS=(
  "apps/mobile/.env|EXPO_PUBLIC_KEYCLOAK_ISSUER"
  "services/api/.env|LUXISH_KEYCLOAK_ISSUER"
  "infra/.env|KC_HOSTNAME"
)

mkdir -p "$LOGS"

# Each entry is "name|queues". The default worker also serves maintenance, so
# the sweeper has somewhere to run.
WORKERS=(
  "ai|ai"
  "media|media"
  "default|default,maintenance"
)

say() { printf '%s\n' "$*"; }

running() {
  # One argument: a fragment of the command line to match.
  powershell.exe -NoProfile -Command \
    "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -ErrorAction SilentlyContinue |
       Where-Object { \$_.CommandLine -like '*$1*' }).Count" 2>/dev/null | tr -d '\r\n'
}


# This machine's address on the LAN, which is what the phone can reach.
#
# Read from the adapter rather than configured, so a DHCP lease change is
# picked up on the next start instead of becoming another stale pin.
lan_ip() {
  powershell.exe -NoProfile -Command \
    "(Get-NetIPAddress -AddressFamily IPv4 |
      Where-Object { \$_.PrefixOrigin -eq 'Dhcp' -and \$_.IPAddress -notlike '169.*' } |
      Select-Object -First 1).IPAddress" 2>/dev/null | tr -d '\r\n'
}

# Point every config at the origin in `$1`, and restart what caches it.
#
# Prints nothing and restarts nothing when the value is already right,
# so the common case is silent and free.
pin_host() {
  local origin="$1"
  local changed=0
  local pin file key want have

  for pin in "${HOST_PINS[@]}"; do
    file="$REPO/${pin%%|*}"
    key="${pin##*|}"
    [ -f "$file" ] || continue
    # `KC_HOSTNAME` is the bare origin; the two issuers carry the realm path.
    want="$origin"
    [ "$key" != "KC_HOSTNAME" ] && want="$origin/realms/luxish"
    have="$(grep -E "^$key=" "$file" | head -1 | cut -d= -f2-)"
    if [ "$have" != "$want" ]; then
      # `|` as the delimiter: the value is a URL and contains slashes.
      sed -i -E "s|^$key=.*|$key=$want|" "$file"
      changed=1
    fi
  done

  [ "$changed" = "0" ] && return 0

  # Keycloak bakes the issuer into every discovery document, and the API
  # caches it in an `lru_cache` — a stale API answers 401 to every request
  # carrying a perfectly valid token.
  ( cd "$REPO/infra" && docker compose up -d keycloak > /dev/null 2>&1 ) || true
  powershell.exe -NoProfile -Command \
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -ErrorAction SilentlyContinue |
     Where-Object { \$_.CommandLine -like '*uvicorn app.main*' } |
     ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" 2>/dev/null || true
  HOST_ROTATED=1
  return 1
}

# Bring up the https tunnel and point everything at it.
#
# Only reached with `LUXISH_TUNNEL=1`; see `keycloak_host` for why it is
# not the default any more.
tunnel() {
  if ! command -v cloudflared > /dev/null 2>&1; then
    say "tunnel   cloudflared not installed - Google sign-in will not work"
    return 0
  fi

  # **Alive means it serves, not that the process exists.** A quick tunnel
  # is anonymous and the edge drops it after a few hours: `cloudflared`
  # keeps running and keeps logging "Unauthorized: Tunnel not found" while
  # every request through it 502s, so a process-count check reported
  # "alive" through an entire outage.
  local current=""
  current="$(grep -ho 'https://[a-z0-9-]*[.]trycloudflare[.]com' "$TUNNEL_LOG" 2>/dev/null | head -1)"
  if [ -n "$current" ] && curl -sf -o /dev/null --max-time 15 \
      "$current/realms/luxish/.well-known/openid-configuration"; then
    pin_host "$current" || true
    say "tunnel   $current"
    return 0
  fi

  # Kill whatever is there first: a dead-but-running cloudflared holds the
  # name and would otherwise never be replaced.
  powershell.exe -NoProfile -Command \
    "Get-Process cloudflared -ErrorAction SilentlyContinue |
     Stop-Process -Force -ErrorAction SilentlyContinue" 2>/dev/null || true
  : > "$TUNNEL_LOG"
  nohup cloudflared tunnel --url "http://localhost:$KC_PORT" > "$TUNNEL_LOG" 2>&1 &
  say "tunnel   starting"

  local host=""
  local _i
  for _i in $(seq 1 40); do
    host="$(grep -ho 'https://[a-z0-9-]*[.]trycloudflare[.]com' "$TUNNEL_LOG" 2>/dev/null | head -1)"
    [ -n "$host" ] && break
    sleep 1
  done
  if [ -z "$host" ]; then
    say "tunnel   FAILED to report a hostname - see $TUNNEL_LOG"
    return 1
  fi

  if pin_host "$host"; then
    say "tunnel   $host"
  else
    say "tunnel   $host (hostname changed - rewired 3 configs)"
  fi
}

# Decide where Keycloak is reachable, and make every config agree.
#
# **The LAN by default, because it does not rotate.** This used to be a
# Cloudflare quick tunnel, whose hostname is random on every start and
# which the edge expires on its own. Three files pin that hostname — the
# phone's bundle, the API's issuer check, and Keycloak's own advertised
# issuer — so every rotation broke sign-in until all three were rewritten
# and two services restarted. It broke repeatedly. The LAN address is
# stable for as long as the DHCP lease, and is re-read here anyway, so a
# new lease costs one restart instead of a debugging session.
#
# **The tunnel is opt-in, for one reason.** Google will not register a
# non-https redirect URI unless the host is localhost, and a phone is not
# localhost. So `LUXISH_TUNNEL=1 ./scripts/dev-stack.sh` brings it up when
# Google sign-in is being tested. Email and password, the API and the app
# are all happy on http across a trusted network, and PKCE with an
# `exp://` redirect needs no TLS.
keycloak_host() {
  if [ "$USE_TUNNEL" = "1" ]; then
    tunnel
    return 0
  fi

  local ip
  ip="$(lan_ip)"
  if [ -z "$ip" ]; then
    say "keycloak no LAN address found - leaving the configured host alone"
    return 0
  fi
  if pin_host "http://$ip:$KC_PORT"; then
    say "keycloak http://$ip:$KC_PORT"
  else
    say "keycloak http://$ip:$KC_PORT (address changed - rewired 3 configs)"
  fi
}

start() {
  HOST_ROTATED=0
  if [ ! -x "$PY" ]; then
    say "No virtualenv at $API_DIR/.venv. Create it before running this."
    exit 1
  fi

  cd "$API_DIR"

  keycloak_host || true

  # Migrate before anything serves.
  #
  # Added after a new table shipped and the API returned 500s for an hour
  # because nothing had applied the revision. The failure is the worst shape
  # available: the code is correct, the tests pass, and the running app says
  # "Internal Server Error" with the real cause only in a log nobody is
  # tailing. Alembic is idempotent, so this costs a second when there is
  # nothing to do.
  if ! "$PY" -m alembic upgrade head > "$LOGS/migrate.log" 2>&1; then
    say "migrations FAILED - see $LOGS/migrate.log"
    tail -5 "$LOGS/migrate.log"
    exit 1
  fi
  say "db       at head"

  if [ "$(running "uvicorn app.main")" != "0" ]; then
    say "api      already running"
  else
    nohup "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT" \
      > "$LOGS/api.log" 2>&1 &
    say "api      starting on :$API_PORT"
  fi

  for entry in "${WORKERS[@]}"; do
    name="${entry%%|*}"
    queues="${entry##*|}"
    if [ "$(running "celery*-n $name@")" != "0" ]; then
      say "worker   $name already running"
      continue
    fi
    # --pool=solo: prefork does not work on Windows, and the threaded pool
    # does not fire worker_process_init, which is where the event loop each
    # handler needs is created.
    nohup "$PY" -m celery -A "$CELERY_APP" worker \
      -n "$name@%h" --pool=solo --loglevel=info -Q "$queues" \
      > "$LOGS/worker-$name.log" 2>&1 &
    say "worker   $name on [$queues]"
  done

  if [ "$(running "celery*beat")" != "0" ]; then
    say "beat     already running"
  else
    # Separate process: celery's -B flag is rejected on Windows. Without beat
    # the sweeper never runs, and a dispatch Redis loses is never recovered.
    nohup "$PY" -m celery -A "$CELERY_APP" beat --loglevel=info \
      > "$LOGS/beat.log" 2>&1 &
    say "beat     starting"
  fi

  say ""
  say "waiting for the API ..."
  for _ in $(seq 1 60); do
    if curl -sf --max-time 2 "http://127.0.0.1:$API_PORT/healthz" >/dev/null 2>&1; then
      say "api      ready"
      break
    fi
    sleep 1
  done

  say ""
  status

  if [ "${HOST_ROTATED:-0}" = "1" ]; then
    say ""
    say "The Keycloak address changed. Restart Metro so the app picks it up:"
    say "    npx expo start --clear"
    say "Then reload the app on the phone. Signing in will fail until you do,"
    say "because EXPO_PUBLIC_KEYCLOAK_ISSUER is bundled, not read at runtime."
  fi
}

stop() {
  powershell.exe -NoProfile -Command \
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -ErrorAction SilentlyContinue |
     Where-Object { \$_.CommandLine -like '*uvicorn app.main*' -or \$_.CommandLine -like '*celery*' } |
     ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" 2>/dev/null || true
  powershell.exe -NoProfile -Command \
    "Get-Process cloudflared -ErrorAction SilentlyContinue |
     Stop-Process -Force -ErrorAction SilentlyContinue" 2>/dev/null || true
  say "stopped the API, the workers, beat and the tunnel"
}

status() {
  printf 'keycloak : '
  kc_issuer="$(grep -E '^LUXISH_KEYCLOAK_ISSUER=' "$REPO/services/api/.env" 2>/dev/null | cut -d= -f2-)"
  # Fifteen seconds, not five: the first request through a cold tunnel
  # routinely takes ten, and a timeout here reads as DOWN on a host that
  # is working, which sends somebody debugging the wrong thing.
  if [ -n "$kc_issuer" ] && curl -sf -o /dev/null --max-time 15 \
      "$kc_issuer/.well-known/openid-configuration"; then
    printf '%s\n' "$kc_issuer"
  else
    printf 'DOWN%s\n' "${kc_issuer:+ ($kc_issuer)}"
  fi
  printf 'api      : '
  curl -s --max-time 3 "http://127.0.0.1:$API_PORT/healthz" 2>/dev/null || printf 'DOWN'
  printf '\n'
  for entry in "${WORKERS[@]}"; do
    name="${entry%%|*}"
    n="$(running "celery*-n $name@")"
    printf 'worker %-8s: %s\n' "$name" "$([ "$n" != "0" ] && echo up || echo DOWN)"
  done
  n="$(running "celery*beat")"
  printf 'beat     : %s\n' "$([ "$n" != "0" ] && echo up || echo DOWN)"
}

case "${1:-start}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *)      say "usage: $0 [start|stop|status]"; exit 2 ;;
esac
