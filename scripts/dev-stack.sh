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
# Create the three `.env` files on a clean clone.
#
# **They are gitignored, and before this nothing created them.** A
# reviewer who cloned the repository got no env files at all, so the
# API raised on a missing `keycloak_issuer` before it could serve a
# single request - and `pin_host` below skips a file that does not
# exist, so it could not help either. "Clone and run" was not true.
#
# Copied from the committed `.env.example` files, never overwritten:
# somebody who has put a real model key in theirs must not lose it to
# a restart.
seed_env_files() {
  local pin file
  for pin in "${HOST_PINS[@]}"; do
    file="$REPO/${pin%%|*}"
    if [ ! -f "$file" ] && [ -f "$file.example" ]; then
      cp "$file.example" "$file"
      say "created ${pin%%|*} from its example"
    fi
  done
}

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
# **The phone's API address, which nothing was rewriting.**
#
# `HOST_PINS` covers the three files that carry Keycloak's host, because
# that is what the tunnel rotated. The app's own API address was not in
# it - and `apps/mobile/.env.example` says, in as many words, that
# "dev-stack.sh rewrites both lines with this computer's address on
# every start". It rewrote one.
#
# A reviewer's clone therefore kept `http://127.0.0.1:8010`, and on a
# phone `127.0.0.1` is the phone. Sign-in worked, because Keycloak's
# line *was* pinned, and then every screen was empty: the one failure
# shape most easily read as "this app is broken".
#
# Separate from `pin_host` because the value has a different shape -
# this one carries the API's port and no realm path - and because it is
# re-pinned whenever the port changes, not only when the address does.
pin_api_url() {
  local ip="$1" port="$2"
  local file="$REPO/apps/mobile/.env"
  local want="http://$ip:$port"
  local have

  [ -f "$file" ] || return 0
  have="$(grep -E '^EXPO_PUBLIC_API_BASE_URL=' "$file" | head -1 | cut -d= -f2-)"
  [ "$have" = "$want" ] && return 0

  sed -i -E "s|^EXPO_PUBLIC_API_BASE_URL=.*|EXPO_PUBLIC_API_BASE_URL=$want|" "$file"
  say "app      API address set to $want"
  # Metro inlines `EXPO_PUBLIC_*` at bundle time, so a running Metro is
  # serving the old address. Saying so is the whole point: the symptom
  # of not knowing is an app that cannot reach a backend that is up.
  say "         (restart Metro if it is already running)"
  return 1
}

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

  # The same address, the API's port. Pinned here because this is where
  # the LAN address is already known and already re-read on every start.
  pin_api_url "$ip" "$API_PORT" || HOST_ROTATED=1
}

# Run the backend in containers, which is the default.
#
# **So reviewing this app needs Docker and Node, and not Python.**
# The API and the four workers used to run as local processes, so a
# reviewer had to install Python 3.12, build a virtualenv and
# resolve seventeen dependencies before anything started - and a
# version mismatch failed in ways that looked like a broken app
# rather than a missing toolchain.
#
# `LUXISH_LOCAL_BACKEND=1` keeps the old path for anybody actually
# working on the API, where an editable install and a debugger
# attached to a local process are worth the setup.
docker_backend() {
  say "building the backend image (first run takes a few minutes) ..."
  if ! ( cd "$REPO/infra" && docker compose build api >"$LOGS/build.log" 2>&1 ); then
    say "image build FAILED - see $LOGS/build.log"
    tail -5 "$LOGS/build.log"
    exit 1
  fi

  # **`--force-recreate`, and it is not belt and braces.**
  #
  # The API and the four workers share one image on purpose, so that a
  # worker can never lag the API by a rebuild. `docker compose up -d`
  # undoes that: it recreates only the containers it considers stale,
  # so a rebuild followed by a plain `up` left the API on the new image
  # and the workers running the old one.
  #
  # That is not a cosmetic difference. It happened here while adding
  # cancellation: the API accepted the stop and wrote the row, the
  # workers had no idea what the row meant, drew the picture anyway and
  # marked it ready a minute later. Every immediate check passed and
  # the feature silently did not work.
  if ! ( cd "$REPO/infra" && docker compose up -d --force-recreate            >"$LOGS/compose.log" 2>&1 ); then
    say "the stack did not come up - see $LOGS/compose.log"
    exit 1
  fi

  printf '       waiting for the API '
  local up=0
  for _ in $(seq 1 60); do
    if curl -sf --max-time 2 "http://127.0.0.1:$API_PORT/healthz" >/dev/null 2>&1; then
      up=1; break
    fi
    printf '.'; sleep 2
  done
  printf '
'
  if [ "$up" -ne 1 ]; then
    say "api      did not become healthy - docker compose logs api"
    exit 1
  fi

  # Migrations run inside the container, against the same database
  # the API will serve. See the note in the local path for why this
  # is not left to chance.
  if ! ( cd "$REPO/infra" && docker compose exec -T api           alembic upgrade head >"$LOGS/migrate.log" 2>&1 ); then
    say "migrations FAILED - see $LOGS/migrate.log"
    tail -5 "$LOGS/migrate.log"
    exit 1
  fi
  say "db       at head"

  # **Is the thing on that port the thing we just started?**
  #
  # A socket left behind by a dead process kept listening on
  # `0.0.0.0:8010`. Docker could not have that address, took
  # `[::]:8010`, and reported a successful publish - so every IPv4
  # client, the phone included, reached a months-old build with no
  # workers behind it. Renders were accepted and never drawn, and the
  # app read as slow rather than misrouted.
  #
  # `/healthz` cannot see this: the dead listener answered it happily.
  # Comparing the served contract against the committed one can.
  if ! node "$REPO/scripts/verify-api.mjs" "$API_PORT" >"$LOGS/verify.log" 2>&1; then
    say "something other than this build is answering on :$API_PORT"
    cat "$LOGS/verify.log"
    exit 1
  fi

  say "api      on :$API_PORT (container, serving this checkout)"
  say "workers  ai, media, default and beat (containers, same image)"
}

start() {
  seed_env_files
  HOST_ROTATED=0

  if [ "${LUXISH_LOCAL_BACKEND:-0}" != "1" ]; then
    keycloak_host || true
    docker_backend
    return 0
  fi

  if [ ! -x "$PY" ]; then
    say "No virtualenv at $API_DIR/.venv. Create it, or unset"
    say "LUXISH_LOCAL_BACKEND to run the backend in Docker instead."
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
    # **`--reload`, because its absence cost most of a day.**
    #
    # Without it the API keeps running whatever code it started
    # with, so a fix that is in the file is not in the process.
    # Three separate bugs were reported against a build that had
    # already been fixed, and one of them - a 500 on search by
    # picture - was a function signature corrected an hour earlier.
    # The symptom is indistinguishable from the fix not working,
    # which is the worst thing to hand somebody testing on a phone.
    #
    # This is the dev stack. Production runs the same module with
    # its own command and is unaffected.
    #
    # Scoped to `app` so a write under `.venv` or `.devlogs` does
    # not trigger a restart loop.
    nohup "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT" \
      --reload --reload-dir app \
      > "$LOGS/api.log" 2>&1 &
    say "api      starting on :$API_PORT (reloads on change)"
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
    say "An address in the app's bundle changed. Restart Metro so it is picked up:"
    say "    npx expo start --clear"
    say "Then reload the app on the phone. Until you do, the app is still using"
    say "the old one: EXPO_PUBLIC_* values are compiled into the bundle, not read"
    say "at runtime. Signing in fails if the issuer moved, and every screen comes"
    say "up empty if the API address did."
  fi
}

stop() {
  # The backend runs in containers by default, so stopping has to
  # reach them. Harmless when they were never started.
  ( cd "$REPO/infra" && docker compose stop api worker-ai worker-media       worker-default beat >/dev/null 2>&1 ) || true

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

# **`restart` exists because the workers cannot reload themselves.**
#
# The API watches its own files now, but Celery's prefork pool loads
# the task modules once at start, so a change to anything under
# `app/workers` is invisible until the processes go away. That was
# real: a packshot redraw ran seven times against the old handler and
# returned byte-for-byte identical pictures, which reads as the fix
# not working rather than as a stale process.
#
# `stop` then `start` was what everyone typed instead, which is two
# commands and one of them is easy to forget.
restart() {
  stop
  # Celery's children take a moment to release the broker
  # connections; starting into that produces a worker that claims
  # the queue and then dies.
  sleep 2
  start
}

case "${1:-start}" in
  start)   start ;;
  stop)    stop ;;
  restart) restart ;;
  status)  status ;;
  *)       say "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
