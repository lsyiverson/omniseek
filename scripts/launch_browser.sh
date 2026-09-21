#!/usr/bin/env bash
# Launch a Chrome with remote debugging, so a walled source can read through
# YOUR logged-in session. Mirrors the upstream omniseek scripts/launch_cdp.sh.
#
# Usage:
#   scripts/launch_browser.sh <port> [profile-dir] [url]
#
#   port         CDP port (9222 shared | 9223 xiaohongshu | 9224 xiaohongshu-cn | 9225 douyin | 9226 smzdm_read)
#   profile-dir  persistent browser profile; default ~/.omniseek/chrome-<port>.
#                Keep it stable so your login survives restarts.
#   url          optional page to open, e.g. https://www.zhihu.com so you can log in directly
#
# After this opens a window: log in by hand (QR scan, password, whatever).
# Then leave the browser running — cookies persist on disk.
set -euo pipefail

PORT="${1:-}"
if [ -z "$PORT" ]; then
  cat >&2 <<EOF
usage: $0 <port> [profile-dir] [url]

  port         CDP port the walled source expects
                 9222  shared (zhihu, yipinsanfendi, etc.)
                 9223  xiaohongshu (international)
                 9224  xiaohongshu (mainland)
                 9225  douyin
                 9226  smzdm (read-only; no login needed, just a real Chrome fingerprint)
  profile-dir  defaults to ~/.omniseek/chrome-<port>
  url          optional page to open (so you can log in directly)
EOF
  exit 1
fi

PROFILE="${2:-$HOME/.omniseek/chrome-$PORT}"
URL="${3:-}"

# Find a Chrome/Chromium binary on macOS or Linux
find_chrome() {
  local candidates=(
    "${CHROME_BIN:-}"
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "/Applications/Chromium.app/Contents/MacOS/Chromium"
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    "$(command -v google-chrome 2>/dev/null || true)"
    "$(command -v google-chrome-stable 2>/dev/null || true)"
    "$(command -v chromium 2>/dev/null || true)"
    "$(command -v chromium-browser 2>/dev/null || true)"
  )
  for c in "${candidates[@]}"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  return 1
}

CHROME="$(find_chrome || true)"
if [ -z "$CHROME" ]; then
  cat >&2 <<EOF
ERROR: no Chrome/Chromium found. Install one of:
  - Google Chrome (https://www.google.com/chrome/)
  - Chromium (brew install --cask chromium)
  - Or point CHROME_BIN at any chromium binary:
    CHROME_BIN=/path/to/chrome $0 $*
EOF
  exit 1
fi

mkdir -p "$PROFILE"
echo "==> launching $(basename "$CHROME")"
echo "    port    : $PORT  (OmniSeek connects to http://127.0.0.1:$PORT)"
echo "    profile : $PROFILE  (your login persists here)"
[ -n "$URL" ] && echo "    opening : $URL"
echo
echo "Log in to the platform in the window that opens, then LEAVE THIS BROWSER RUNNING."
echo "Press Ctrl-C here to detach (the browser keeps running)."

# Pre-flight: if a Chrome is already bound to this CDP port, kill the stale instance so this
# launch owns it. pgrep exists on macOS + Linux; on systems without it, this no-ops.
if command -v pgrep >/dev/null 2>&1 && pgrep -f "remote-debugging-port=$PORT" >/dev/null 2>&1; then
  echo "==> a Chrome is already bound to port $PORT; killing the stale instance" >&2
  pkill -f "remote-debugging-port=$PORT" || true
  sleep 2
fi

# Flag rationale (loopback-only, safe on your own machine):
#   --remote-allow-origins=*      REQUIRED on Chrome 111+; without it, the CDP WebSocket upgrade is
#                                 rejected and walled sources silently return empty.
#   --disable-blink-features=AutomationControlled  hides the navigator.webdriver=true automation
#                                 tell so the site sees an ordinary Chrome. Do NOT add --enable-automation.
#   --disable-features=PrivacySandboxAdsAPIs      suppresses the Privacy Sandbox prompt that can steal focus.
exec "$CHROME" \
  --remote-debugging-port="$PORT" \
  --remote-allow-origins='*' \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-blink-features=AutomationControlled \
  --disable-features=PrivacySandboxAdsAPIs \
  ${URL:+"$URL"}