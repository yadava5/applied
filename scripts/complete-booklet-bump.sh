#!/usr/bin/env bash
# Finish a Dependabot booklet pull request: rebuild the System Card and show
# the drift, so the bump can be committed with its rebuild in the same change.
#
# WHY THIS EXISTS (DEC-006 in docs/DECISIONS.md)
#
# `.github/workflows/booklet.yml` requires apps/web/public/system-card to
# reproduce byte-for-byte from booklet/. A bundler, plugin or React bump moves
# the emitted bundle and therefore its hashed filename, and Dependabot does not
# run project build scripts -- so every booklet dependency PR lands red by
# construction and needs a human to commit the rebuild. That is the design, not
# a fault. This script is the human half, so it cannot be half-done.
#
# WHY DOCKER AND NOT YOUR NODE
#
# The gate compares against a build produced by the RUNNER, on node 22. The
# workflow's own comment records the measurement that settled this: a first
# pass which left the author's macOS node_modules mounted reported four repos
# green, and a re-run with them shadowed failed one outright. A build from your
# machine is not evidence about the runner, so this refuses to produce one.
#
# Usage:  scripts/complete-booklet-bump.sh          # rebuild and show the drift
#         scripts/complete-booklet-bump.sh --check  # rebuild, exit 1 if drifted
#
# It never commits. Read the diff first -- a bump that changes the CSS hash as
# well as the JS one is not what a React patch release predicts, and is worth
# understanding before it ships.

set -euo pipefail

NODE_IMAGE="node:22"
OUT="apps/web/public/system-card"
ROOT="$(git rev-parse --show-toplevel)"

check_only=0
[ "${1:-}" = "--check" ] && check_only=1

command -v docker >/dev/null 2>&1 || {
  echo "docker is required: the rebuild must happen on the same node major CI uses." >&2
  echo "Without it, run 'npm ci && npm run build:system-card' in booklet/ under node 22." >&2
  exit 2
}
docker info >/dev/null 2>&1 || { echo "docker is installed but not running." >&2; exit 2; }

# Positive control, the same one the workflow carries: prove the guarded path
# holds committed files BEFORE trusting anything about drift. A clean result
# over an empty pathspec means "looked in the wrong place", not "no drift".
tracked=$(git -C "$ROOT" ls-files -- "$OUT" | wc -l | tr -d ' ')
if [ "$tracked" -eq 0 ]; then
  echo "No committed files under $OUT. Wrong repo, or the card is no longer committed" >&2
  echo "-- in which case DEC-006 is void and this script should be deleted with it." >&2
  exit 2
fi
echo "Guarding $tracked committed files under $OUT."

echo "Rebuilding in $NODE_IMAGE (this is a clean install; it takes a minute)..."
docker run --rm -v "$ROOT":/w -w /w/booklet "$NODE_IMAGE" \
  sh -lc 'npm ci --no-audit --no-fund && npm run build:system-card' >/dev/null

drift="$(git -C "$ROOT" status --porcelain --untracked-files=all -- "$OUT")"
if [ -z "$drift" ]; then
  echo "OK: $OUT already reproduces byte-for-byte. Nothing to commit."
  exit 0
fi

echo
echo "The rebuild changed the committed card. Review this, then commit it WITH the bump:"
git -C "$ROOT" add -A -- "$OUT"
git -C "$ROOT" diff --cached --name-status -- "$OUT"
git -C "$ROOT" diff --cached --stat -- "$OUT"
echo
echo "Staged, not committed. If the CSS hash moved as well as the JS one, read why first."

[ "$check_only" -eq 1 ] && exit 1
exit 0
