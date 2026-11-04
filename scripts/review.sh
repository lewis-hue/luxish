#!/usr/bin/env bash
#
# One command to put the whole app on a reviewer's phone.
#
#   ./scripts/review.sh              bring everything up and print a QR code
#   ./scripts/review.sh up --android also boot an Android emulator
#   ./scripts/review.sh stop         shut down everything this started
#   ./scripts/review.sh doctor       check the machine without starting anything
#
# It brings up the data stores, the API, all four job workers, the
# scheduler and Metro, seeds the database if it is empty, and prints
# a QR code to scan with Expo Go.
#
# **The QR is the point.** Scanning it on a real phone is a better
# review than any simulator: it is the device the app is for, on the
# network it will really use. An Android emulator is available behind
# `--android` for anybody who prefers one.
#
# **There is no iOS simulator leg, and that is a platform fact rather
# than an omission.** Apple's simulator ships only inside Xcode and
# runs only on macOS. On Windows or Linux no amount of scripting
# produces one; the honest options are a real iPhone running Expo Go,
# an Android emulator, or a hosted mac.
#
# Everything is checked before anything is started, because a stack
# that comes up half-way is harder to diagnose than one that refuses.
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE="$REPO/apps/mobile"
API_DIR="$REPO/services/api"
LOGS="$REPO/.devlogs"
#: The account a reviewer signs in with.
#:
#: Created by the realm import in `infra/keycloak/import`, so it
#: exists on a clean clone before anybody runs anything. Verified
#: against a throwaway Keycloak with an empty database.
REVIEWER="me@luxish.local"

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

  # **Not a requirement any more.** The backend runs in containers,
  # so Python is only needed by somebody working on the API itself.
  # It used to be fatal here, which turned "review this app" into
  # "install a Python toolchain first".
  if [ -x "$PY" ]; then
    ok "API virtualenv present (optional - the backend runs in Docker)"
  else
    note "No local Python virtualenv. Not needed: the backend runs in Docker."
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
# Where an API script should run.
#
# **The seeders used to run on the host, always.** With the backend
# in containers that is a different SQLite file from the one the API
# serves, so every seed step reported success against a database
# nobody reads - and a reviewer scanned the QR, signed in and found
# an empty app. Measured, not assumed: the host said 719 pins and
# the container said 0.
if [ "${LUXISH_LOCAL_BACKEND:-0}" = "1" ]; then
  SEED_PHOTOS="$REPO/assets/seed-photos"
else
  # The read-only mount declared in docker-compose.
  SEED_PHOTOS="/srv/assets/seed-photos"
fi

api_py() {
  if [ "${LUXISH_LOCAL_BACKEND:-0}" = "1" ]; then
    ( cd "$API_DIR" && "$PY" "$@" )
  else
    ( cd "$REPO/infra" && docker compose exec -T api python "$@" )
  fi
}

seed_if_empty() {
  local count
  # **From `$API_DIR`, and the error is kept.**
  #
  # This ran from the repository root, where `get_settings()` cannot
  # find the API's `.env` - so it raised on a missing
  # `keycloak_issuer`, `2>/dev/null` threw the reason away, and the
  # script printed "could not count posts; skipping the seed check"
  # and carried on. The consequence was the worst one available
  # here: a reviewer scanned the QR and got an empty app, with
  # nothing on screen saying why.
  count="$( api_py - <<'PYEOF' 2>>"$LOGS/seed.log"
import asyncio, os, sys
sys.path.insert(0, ".")
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
)" || count="?"
  [ -n "$count" ] || count="?"
  if [ "$count" = "?" ]; then
    bad "could not read the database - see .devlogs/seed.log"
    note "The app will come up empty. Fix this before reviewing."
    return 1
  fi
  if [ "$count" -gt 0 ] 2>/dev/null; then
    ok "database already has $count pins"
  else
    say "  seeding a demo world (this takes a minute) ..."
    ( api_py scripts/seed_demo_world.py \
        --photos "$SEED_PHOTOS" >"$LOGS/seed.log" 2>&1 ) \
      && ok "seeded" \
      || { bad "seeding failed - see .devlogs/seed.log"; return 1; }
  fi

  # Both of these run whether or not the database was empty, and both
  # are idempotent. Hanging them off the empty branch meant a reviewer
  # who had already seeded - or who pulled after these were added -
  # never got the generated board and never got the broken pins swept.
  post_generated_pins
  repair_pins
  join_reviewer
}

# Put the reviewer in the follow graph.
#
# Followers and following live on the profile, behind the counts;
# the Community tab they used to live in was removed because it was
# a second feed of the fits Discover already ranks better.
#
# **Only works after they have signed in once, and that is not a
# bug.** The API keys an account on `(provider, subject)` from the
# token and deliberately refuses to adopt an existing row by email -
# an email collision raises `identity_link_required` rather than
# silently merging two people. So a row pre-created here would not
# become their account; it would block their first sign-in with a
# 409.
#
# Instead this runs every time and does nothing until the row
# exists. Discover, Search and the wardrobe are full from the first
# launch regardless; this is the follow graph, which needs a person
# to hang off.
join_reviewer() {
  if ( api_py scripts/seed_demo_world.py --join "$REVIEWER" >"$LOGS/join.log" 2>&1 ); then
    if grep -q "no account for" "$LOGS/join.log" 2>/dev/null; then
      note "sign in once, then run this again to put yourself in the follow graph"
    else
      ok "$REVIEWER follows a spread of the demo world"
    fi
  else
    note "could not wire up the reviewer account - see .devlogs/join.log"
  fi
}

# The 300 generated pins ship in the repository; this is what turns
# them into accounts, fits and hashtags the app can actually serve.
# Idempotent - matched on the picture's checksum, so a second run adds
# nothing.
post_generated_pins() {
  if ( api_py scripts/import_generated_pins.py >"$LOGS/pins.log" 2>&1 ); then
    ok "the generated board is posted"
  else
    note "could not post the generated board - see .devlogs/pins.log"
  fi
}

# A published pin with no photograph is a permanently blank tile in
# the middle of Discover, and it reads as the app being broken rather
# than as one bad row. The API cannot create one; seeding that writes
# rows directly can, so the board is checked after it runs.
repair_pins() {
  if ( api_py scripts/repair_pins.py --fix >"$LOGS/repair.log" 2>&1 ); then
    ok "every pin has a photograph"
  else
    note "pin check could not run - see .devlogs/repair.log"
  fi
}

# Stop Metro, however it was started.
#
# By port and by command line, because this script may not be what
# started it: a reviewer who ran `npx expo start` by hand still needs
# `review.sh stop` to stop it, and a bundle built against an old API
# address has to be replaced rather than left running.
#: One line on purpose: a `\` continuation inside this string has been
#: eaten twice by the tooling that edits this file, and a half-written
#: kill command fails silently.
_KILL_8081='Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }'

stop_metro() {
  # By port first, because that is what `expo start` actually holds
  # and what the next start will collide with.
  powershell.exe -NoProfile -Command "$_KILL_8081" >/dev/null 2>&1 || true
  pkill -f "expo start" 2>/dev/null || true
  taskkill //F //IM node.exe //FI "WINDOWTITLE eq expo*" >/dev/null 2>&1 || true
}

# What the running bundle was built against, if anything is running.
#
# **A running Metro is not the same as a correct one.** `EXPO_PUBLIC_*`
# values are inlined when the bundle is built, so a Metro started
# before the API address changed keeps serving the old one - and this
# function used to see a live Metro, say "already running" and leave
# it there. The reviewer then scanned a perfectly good QR code and the
# app talked to an address nothing was listening on, which reads as a
# broken app rather than a stale bundle.
#
# Recorded beside the log so the check survives this script exiting.
metro_target_file() { printf '%s' "$LOGS/metro-api-url"; }

metro_is_current() {
  local want="$1" had
  [ -f "$(metro_target_file)" ] || return 1
  had="$(cat "$(metro_target_file)" 2>/dev/null)"
  [ "$had" = "$want" ]
}

start_metro() {
  local want
  want="$(grep -E '^EXPO_PUBLIC_API_BASE_URL=' "$MOBILE/.env" 2>/dev/null | head -1 | cut -d= -f2-)"

  if curl -s --max-time 3 "http://127.0.0.1:8081/status" >/dev/null 2>&1; then
    if metro_is_current "$want"; then
      ok "Metro already running on :8081"
      return 0
    fi
    note "the API address changed; restarting Metro so the bundle picks it up"
    # `expo start` holds the port, so the old one has to go first.
    # Killed by port rather than by pid, because this script may not
    # be the thing that started it.
    stop_metro
    sleep 2
  fi
  mkdir -p "$LOGS"
  printf '%s' "$want" > "$(metro_target_file)"
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

  # **The QR is the product, not the fallback.**
  #
  # This used to prefer an Android emulator whenever the SDK and an
  # AVD happened to be installed, and only drew a QR when they were
  # not. That is backwards for the thing this script exists to do:
  # hand somebody a code to scan so they can hold the app in their
  # hand. A reviewer with Android Studio on their laptop still wants
  # their phone.
  #
  # The emulator is still one flag away, for whoever prefers it.
  show_qr

  if [ "${WANT_EMULATOR:-0}" -eq 1 ]; then
    boot_emulator
  elif emulator_binary >/dev/null && [ -n "$(list_avds)" ]; then
    say ""
    note "An Android emulator is available. ./scripts/review.sh up --android"
  fi
}

# Boot an Android emulator and launch the app in it. Opt-in.
boot_emulator() {
  local bin avd
  say ""
  # A device already attached is reused. Without this check a second
  # run boots a duplicate emulator against the same AVD, which fails
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
      if adb_ready; then printf '
'; ok "emulator is up"; break; fi
      printf '.'; sleep 2
    done
    printf '
'
    if adb_ready; then
      ( cd "$MOBILE" && npx expo start --android --non-interactive >>"$LOGS/metro.log" 2>&1 & )
      ok "app launching in the emulator"
      note "Expo Go is installed into it on first run; give it a moment."
      return 0
    fi
    bad "the emulator did not finish booting - the QR above still works"
  else
    bad "no Android SDK or no virtual device - the QR above still works"
  fi
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
  # **Through the library's API, and the failure is reported.**
  #
  # The CLI form prints nothing on this platform, and the first
  # version swallowed every error - so a missing dependency looked
  # identical to a QR that simply had not rendered, and the URL
  # underneath read as the only option rather than as the fallback.
  # `qrcode-terminal` is a declared devDependency now for the same
  # reason: it resolved only as a transitive Expo dependency, which
  # is a QR that disappears on an unrelated upgrade.
  local drawn=0
  if command -v node >/dev/null 2>&1; then
    if ( cd "$REPO" && node -e "
      require('qrcode-terminal').generate(process.argv[1], {small: true},
        (code) => console.log(code));
    " "exp://$host:8081" ); then
      drawn=1
    fi
  fi
  if [ "$drawn" -eq 0 ]; then
    bad "could not draw the QR code"
    note "Run 'npm install' at the repo root, or type the URL below into Expo Go."
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
  say "  API        http://$host:${LUXISH_API_PORT:-8010}      (docs at /docs)"
  say "  Keycloak   http://$host:55080"
  say "  Metro      http://$host:8081"
  say ""
  say "  Sign in with   me@luxish.local   /   admin123"
  say ""
  note "Logs in .devlogs/   Stop everything with ./scripts/review.sh stop"
}

down() {
  bash "$REPO/scripts/dev-stack.sh" stop || true
  stop_metro
  say "stopped"
}

# `--android` additionally boots an emulator. The QR is drawn either
# way, because the phone is the point.
WANT_EMULATOR=0
for arg in "$@"; do
  case "$arg" in
    --android|--emulator) WANT_EMULATOR=1 ;;
  esac
done

case "${1:-up}" in
  up|start) up ;;
  stop|down) down ;;
  doctor) doctor ;;
  *) say "usage: $0 [up|stop|doctor] [--android]"; exit 2 ;;
esac
