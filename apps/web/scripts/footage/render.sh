#!/usr/bin/env bash
#
# Regenerate every clip under apps/web/public/footage/, from scratch.
#
#   pnpm footage
#
# It builds the app, serves it, records the real UI, composes the clips with
# Remotion, and checks the encoded files. Run it from anywhere; it works out
# where it lives.
#
# WHY A PRODUCTION BUILD AND NOT `next dev`. Dev has behaviour differences on
# this project and paints compile warmth mid-capture, which lands in the frames
# as a flicker nobody can explain six months later. The clips must show the app
# as it ships.
#
# ONE CLIP IS NOT REGENERATED HERE. `gmail-connects` is a hand-made screen
# recording of a real Google OAuth consent flow — it needs a human with a Google
# account, and Google's consent screen is not ours to redraw. Point
# FOOTAGE_OAUTH_SOURCE at the .mov to include it; without it the step is skipped
# loudly and the other clips still rebuild. See README.md.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB="$(cd "$HERE/../.." && pwd)"
cd "$WEB"

PORT="${FOOTAGE_PORT:-3437}"
FRAMES="${FOOTAGE_FRAMES:-$WEB/.footage-frames}"
BASE="http://127.0.0.1:$PORT"

# Fail loudly rather than capturing whatever else is on the port. Silently
# recording another agent's dev server is exactly the kind of wrong-tree mistake
# that is invisible in the output.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use. Set FOOTAGE_PORT to a free one." >&2
  exit 1
fi

echo "==> production build"
pnpm build

echo "==> serving on $BASE"
# `next` is invoked DIRECTLY rather than through `pnpm start`. pnpm supervises
# the script it runs and forwards signals to it, and a backgrounded `pnpm start`
# was reliably taking a SIGTERM roughly twenty seconds in — long enough for the
# first scene to record and for the failure to look like a capture bug rather
# than a dead server (`ELIFECYCLE ... exit code 143` in the log is the tell).
# nohup + disown keeps the server out of this script's job control; the trap
# below still shuts it down by pid.
nohup env PORT="$PORT" ./node_modules/.bin/next start >"$FRAMES.server.log" 2>&1 &
SERVER=$!
disown "$SERVER" 2>/dev/null || true
cleanup() {
  kill "$SERVER" 2>/dev/null || true
  wait "$SERVER" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$BASE/demo"; then break; fi
  sleep 0.5
done
if ! curl -fsS -o /dev/null "$BASE/demo"; then
  echo "The server never answered on $BASE. See $FRAMES.server.log" >&2
  exit 1
fi

mkdir -p "$FRAMES"

# Liveness is re-checked between steps rather than assumed: a server that dies
# mid-run produces a stack trace about a navigation, which is the wrong place to
# start looking.
alive() { curl -fsS -o /dev/null "$BASE/demo" || { echo "The server died. See $FRAMES.server.log" >&2; exit 1; }; }

# The hand-captured source, if the operator has it. Copied in rather than
# referenced, so Remotion has one asset root.
if [ -n "${FOOTAGE_OAUTH_SOURCE:-}" ]; then
  if [ ! -f "$FOOTAGE_OAUTH_SOURCE" ]; then
    echo "FOOTAGE_OAUTH_SOURCE is set but $FOOTAGE_OAUTH_SOURCE does not exist." >&2
    exit 1
  fi
  mkdir -p "$FRAMES/oauth"
  cp "$FOOTAGE_OAUTH_SOURCE" "$FRAMES/oauth/oauth-raw.mov"
fi

alive
echo "==> capture"
FOOTAGE_BASE="$BASE" FOOTAGE_FRAMES="$FRAMES" node scripts/footage/capture.mjs

alive
echo "==> compose + encode"
FOOTAGE_FRAMES="$FRAMES" node scripts/footage/render.mjs

echo "==> prove the gates fire"
FOOTAGE_FRAMES="$FRAMES" node scripts/footage/verify-negative.mjs

echo "==> verify the shipped files"
FOOTAGE_FRAMES="$FRAMES" node scripts/footage/verify.mjs

echo
echo "Done. Clips in apps/web/public/footage/."
echo "Contact sheets to LOOK at (the numbers are not the check): $FRAMES/verify/"
