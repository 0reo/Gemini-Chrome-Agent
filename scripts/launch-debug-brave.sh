#!/usr/bin/env bash
#
# launch-debug-brave.sh — Launch Brave with a dedicated, persistent profile that
# loads the unpacked extension AND exposes the Chrome DevTools Protocol (CDP) on
# port 9222, so chrome-devtools-mcp can attach to it (see project .mcp.json).
#
# Why this exact shape:
#   --load-extension must point at the ABSOLUTE path .output/chrome-mv3 (no
#     trailing slash). On Linux, an unpacked extension's ID is derived from that
#     path, and this exact path hashes to pggfgfolmomlhlnabkfboiiojdkhapoh — the
#     ID the native-messaging host (com.local.gemini_agent.json) is locked to.
#     Change the path and native messaging silently breaks.
#   --remote-allow-origins=* is REQUIRED on Chrome/Brave 144+, otherwise the
#     /json CDP discovery endpoints 404 and --browserUrl can't find the socket.
#   We do NOT pass --enable-automation / --headless: a normal headful launch lets
#     you log into Google once (the persistent profile remembers it afterwards)
#     without tripping Google's "this browser may not be secure" block.
#
# Usage:
#   ./scripts/launch-debug-brave.sh          # build first if needed, then launch
#   GLA_DEBUG_PORT=9333 ./scripts/launch-debug-brave.sh   # override port
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
EXT_DIR="$PROJECT_DIR/.output/chrome-mv3"          # no trailing slash — see above
PROFILE_DIR="${GLA_DEBUG_PROFILE:-$HOME/.local/share/gla-debug-profile}"
PORT="${GLA_DEBUG_PORT:-9222}"
BRAVE="${BRAVE_BIN:-/usr/bin/brave-browser}"

if [[ ! -x "$BRAVE" ]]; then
  echo "ERROR: Brave not found at $BRAVE (set BRAVE_BIN=...)." >&2
  exit 1
fi

if [[ ! -f "$EXT_DIR/manifest.json" ]]; then
  echo "Build output missing — running 'npm run build' first..." >&2
  (cd "$PROJECT_DIR" && npm run build)
fi

if ss -ltn "( sport = :$PORT )" 2>/dev/null | grep -q ":$PORT"; then
  echo "ERROR: port $PORT is already in use. Is a debug browser already running?" >&2
  echo "       Close it, or set GLA_DEBUG_PORT to a free port." >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

echo "Launching Brave:"
echo "  extension : $EXT_DIR"
echo "  profile   : $PROFILE_DIR  (persistent — Google login is remembered)"
echo "  CDP port  : http://127.0.0.1:$PORT"
echo
echo "First run only: log into your Google account, then open gemini.google.com."
echo "Leave this window open while debugging from Claude Code."
echo

exec "$BRAVE" \
  --user-data-dir="$PROFILE_DIR" \
  --remote-debugging-port="$PORT" \
  --remote-allow-origins=* \
  --load-extension="$EXT_DIR" \
  --disable-extensions-except="$EXT_DIR" \
  --no-first-run \
  --no-default-browser-check \
  "https://gemini.google.com/app"
