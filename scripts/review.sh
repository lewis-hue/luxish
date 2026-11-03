#!/usr/bin/env bash
#
# One command to put the whole app in front of a reviewer.
#
#   ./scripts/review.sh          bring everything up and open the app
#   ./scripts/review.sh stop     shut down everything this started
#   ./scripts/review.sh doctor   check the machine without starting anything
#
# It brings up the data stores, the API, all four job workers, the
# scheduler and Metro, seeds the database if it is empty, and then
# opens the app however this machine can:
#
#   1. an Android emulator, if the Android SDK and an AVD are here;
#   2. otherwise a QR code to scan with Expo Go on a real phone.
#
# **There is no iOS simulator leg, and that is a platform fact rather
# than an omission.** Apple's simulator ships only inside Xcode and
# runs only on macOS. On Windows or Linux no amount of scripting
# produces one; the honest options are an Android emulator, a real
# iPhone running Expo Go, or a hosted mac. The script says which of
# those it is using rather than pretending.
#
# Everything is checked before anything is started, because a stack
# that comes up half-way is harder to diagnose than one that refuses.
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE="$REPO/apps/mobile"
API_DIR="$REPO/services/api"
LOGS="$REPO/.devlogs"
PY="$API_DIR/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$API_DIR/.venv/bin/python"

GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; OFF=$'\033[0m'

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %sok%s   %s\n' "$GREEN" "$OFF" "$*"; }
bad()  { printf '  %sno%s   %s\n' "$RED" "$OFF" "$*"; }
note() { printf '       %s%s%s\n' "$DIM" "$*" "$OFF"; }
head2(){ printf '\n%s%s%s\n' "$BOLD" "$*" "$OFF"; }

# --------------------------------------------------------------------------- #
# Is this machine able to run it at all?
# --------------------------------------------------------------------------- #
doctor() {
  local fatal=0
  head2 "What this machine has"

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    ok "Docker is running"
  else
    bad "Docker is not running"
    note "Postgres, Redis and Keycloak live in containers. Start Docker Desktop."
    fatal=1
  fi

  if [ -x "$PY" ]; then
    ok "API virtualenv at services/api/.venv"
  else
    bad "no virtualenv at services/api/.venv"
    note "python -m venv services/api/.venv && services/api/.venv/*/pip install -r services/api/requirements.txt"
    fatal=1
  fi

  if command -v node >/dev/null 2>&1; then
    ok "node $(node --version)"
  else
    bad "node is not installed"
    fatal=1
  fi

  if [ -d "$MOBILE/node_modules" ] || [ -d "$REPO/node_modules" ]; then
    ok "mobile dependencies installed"
  else
    bad "mobile dependencies missing"
    note "npm install"
    fatal=1
  fi

  # How the app will be opened. Not fatal either way: the QR path
  # needs nothing installed.
  if emulator_binary >/dev/null; then
    local avds
    avds="$(list_avds)"
    if [ -n "$avds" ]; then
      ok "Android emulator, with: $(echo "$avds" | tr '\n' ' ')"
    else
      bad "Android SDK found but no virtual device created"
      note "Create one in Android Studio > Device Manager, or scan the QR instead."
    fi
  else
    note "No Android SDK. The app will open by QR code in Expo Go instead."
    note "That is a complete path - a real phone is a better review than an emulator."
  fi

  if [ "$fatal" -ne 0 ]; then
    say ""
    say "Fix the items marked 'no' and run this again."
    return 1
  fi
  return 0
}

emulator_binary() {
  local candidates=(
    "${ANDROID_HOME:-}/emulator/emulator"
    "${ANDROID_SDK_ROOT:-}/emulator/emulator"
    "${LOCALAPPDATA:-}/Android/Sdk/emulator/emulator.exe"
    "$HOME/Android/Sdk/emulator/emulator"
    "$HOME/Library/Android/sdk/emulator/emulator"
  )
  for one in "${candidates[@]}"; do
    [ -n "$one" ] && [ -x "$one" ] && { printf '%s' "$one"; return 0; }
  done
  command -v emulator >/dev/null 2>&1 && { command -v emulator; return 0; }
  return 1
}

list_avds() {
  local bin
  bin="$(emulator_binary)" || return 0
  "$bin" -list-avds 2>/dev/null | grep -v '^$' || true
}

# --------------------------------------------------------------------------- #
# Up
# --------------------------------------------------------------------------- #
seed_if_empty() {
  local count
  count="$("$PY" - <<'PYEOF' 2>/dev/null || echo "?"
import asyncio, os, sys
sys.path.insert(0, "services/api")
os.environ.setdefault("LUXISH_ENVIRONMENT", "local")
async def go():
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as c:
        n = (await c.execute(sa.text("select count(*) from posts"))).scalar()
    await engine.dispose()
    print(n or 0)
asyncio.run(go())
PYEOF
)"
  if [ "$count" = "?" ]; then
    note "could not count posts; skipping the seed check"
    return 0
  fi
  if [ "$count" -gt 0 ] 2>/dev/null; then
    ok "database already has $count pins"
    return 0
  fi

  say "  seeding a demo world (this takes a minute) ..."
  ( cd "$API_DIR" && "$PY" scripts/seed_demo_world.py \
      --photos "$REPO/assets/seed-photos" >"$LOGS/seed.log" 2>&1 ) \
    && ok "seeded" \
    || { bad "seeding failed - see .devlogs/seed.log"; return 1; }

  repair_pins
}

# A published pin with no photograph is a permanently blank tile in
# the middle of Discover, and it reads as the app being broken rather
# than as one bad row. The API cannot create one; seeding that writes
# rows directly can, so the board is checked after it runs.
repair_pins() {
  if ( cd "$API_DIR" && "$PY" scripts/repair_pins.py --fix >"$LOGS/repair.log" 2>&1 ); then
    ok "every pin has a photograph"
  else
    note "pin check could not run - see .devlogs/repair.log"
  fi
}

start_metro() {
  if curl -s --max-time 3 "http://127.0.0.1:8081/status" >/dev/null 2>&1; then
    ok "Metro already running on :8081"
    return 0
  fi
  mkdir -p "$LOGS"
  # From apps/mobile, never the repo root: the root has no router
  # entry, so a Metro started there serves a bundle that dies on
  # "Unable to resolve module ../../App" and looks like a broken app.
  ( cd "$MOBILE" && nohup npx expo start --clear >"$LOGS/metro.log" 2>&1 & )
  printf '       waiting for Metro '
  for _ in $(seq 1 60); do
    if curl -s --max-time 2 "http://127.0.0.1:8081/status" >/dev/null 2>&1; then
      printf '\n'; ok "Metro is up"; return 0
    fi
    printf '.'; sleep 2
  done
  printf '\n'; bad "Metro did not come up - see .devlogs/metro.log"; return 1
}

open_app() {
  head2 "Opening the app"
  local bin avd
  # A device already attached is reused. Without this check a second
  # `up` boots a duplicate emulator against the same AVD, which fails
  # to lock the disk image and leaves two half-working devices.
  if adb_ready; then
    ok "a device is already attached"
    ( cd "$MOBILE" && npx expo start --android --non-interactive >>"$LOGS/metro.log" 2>&1 & )
    ok "app launching on it"
    return 0
  fi
  if bin="$(emulator_binary)" && avd="$(list_avds | head -1)" && [ -n "$avd" ]; then
    say "  booting the Android emulator ($avd) ..."
    ( nohup "$bin" -avd "$avd" -no-snapshot-save >"$LOGS/emulator.log" 2>&1 & )
    printf '       waiting for the device '
    for _ in $(seq 1 90); do
      if adb_ready; then printf '\n'; ok "emulator is up"; break; fi
      printf '.'; sleep 2
    done
    printf '\n'
    if adb_ready; then
      ( cd "$MOBILE" && npx expo start --android --non-interactive >>"$LOGS/metro.log" 2>&1 & )
      ok "app launching in the emulator"
      note "Expo Go is installed into it on first run; give it a moment."
      return 0
    fi
    bad "the emulator did not finish booting - falling back to the QR code"
  fi
  show_qr
}

adb_ready() {
  local adb="${ANDROID_HOME:-${LOCALAPPDATA:-}/Android/Sdk}/platform-tools/adb"
  [ -x "$adb" ] || adb="$(command -v adb 2>/dev/null)" || return 1
  [ -n "$adb" ] || return 1
  "$adb" shell getprop sys.boot_completed 2>/dev/null | grep -q 1
}

lan_address() {
  # The address a phone can reach. Loopback is useless to a handset.
  "$PY" - <<'PYEOF' 2>/dev/null || echo "127.0.0.1"
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))
    print(s.getsockname()[0])
except Exception:
    print("127.0.0.1")
finally:
    s.close()
PYEOF
}

show_qr() {
  local host
  host="$(lan_address)"
  say "  Scan this with Expo Go on your phone:"
  say ""
  # Through the library's API rather than its CLI: the command-line
  # form prints nothing here, and a silent QR is worse than none
  # because the URL below then looks like the only option.
  if command -v node >/dev/null 2>&1; then
    ( cd "$MOBILE" && node -e "
      try {
        require('qrcode-terminal').generate(process.argv[1], {small: true},
          (code) => console.log(code));
      } catch (e) { /* printed as a URL below regardless */ }
    " "exp://$host:8081" 2>/dev/null ) || true
  fi
  say ""
  say "    exp://$host:8081"
  note "The phone must be on the same network as this machine."
  note "Expo Go: apps.apple.com/app/expo-go  /  play.google.com/store/apps/details?id=host.exp.exponent"
}

up() {
  doctor || return 1

  head2 "Starting the stack"
  mkdir -p "$LOGS"
  if ! bash "$REPO/scripts/dev-stack.sh" start; then
    bad "the stack did not start"
    return 1
  fi

  head2 "Content"
  seed_if_empty || true

  head2 "Metro"
  start_metro || return 1

  open_app

  head2 "Where everything is"
  local host; host="$(lan_address)"
  say "  API        http://$host:8010      (docs at /docs)"
  say "  Keycloak   http://$host:55080"
  say "  Metro      http://$host:8081"
  say ""
  say "  Sign in with  demo.review@luxish.local  /  ReviewMe!2026"
  say ""
  note "Logs in .devlogs/   Stop everything with ./scripts/review.sh stop"
}

down() {
  bash "$REPO/scripts/dev-stack.sh" stop || true
  pkill -f "expo start" 2>/dev/null || true
  taskkill //F //IM node.exe //FI "WINDOWTITLE eq expo*" >/dev/null 2>&1 || true
  say "stopped"
}

case "${1:-up}" in
  up|start) up ;;
  stop|down) down ;;
  doctor) doctor ;;
  *) say "usage: $0 [up|stop|doctor]"; exit 2 ;;
esac
