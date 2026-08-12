#!/usr/bin/env bash
#
# Vercel "Ignored Build Step" guard — path-filtered builds.
#
# Two Vercel projects build from this one repository:
#
#   jobtracker-web  Root Directory apps/web        -> apps/web/vercel.json
#   jobtracker-api  Root Directory <repo root>     -> ./vercel.json
#
# so *every* commit triggers *two* deployments. Most of that is waste. Four
# production builds of the web app in a single hour came from commits that
# cannot change the web bundle at all (three GitHub Actions version bumps and
# a Python dependency the cloud function never installs). This script answers
# one question per project: did this commit touch anything the project
# actually builds from?
#
# ---------------------------------------------------------------------------
# EXIT CODES ARE INVERTED. READ THIS BEFORE EDITING.
# ---------------------------------------------------------------------------
#
#     exit 0  ->  SKIP the build (the deployment is marked CANCELED)
#     exit 1  ->  BUILD as normal
#
# Vercel's docs, verbatim: "If the command exits with code 1, the build
# continues as normal. If the command exits with code 0, the build is
# immediately aborted, and the deployment state is set to CANCELED." Any code
# >= 1 builds, so a crash in this script — 127 for a missing file, 128 for a
# git error — lands on BUILD, not on SKIP. That is deliberate, see below.
#
# ---------------------------------------------------------------------------
# THIS SCRIPT MUST FAIL OPEN.
# ---------------------------------------------------------------------------
#
# A wrong SKIP silently stops deploying real changes: the site keeps serving
# the previous build and nothing anywhere reports an error. A wrong BUILD
# costs one wasted deployment. The two are not symmetric, so every uncertain
# path here — no git checkout, unreadable history, an unknown project name, a
# base commit we cannot resolve — exits 1 and builds.
#
# The shallow-clone case is the one that actually bites. Vercel clones with
# `git clone --depth=10`, so on a young or freshly-created branch `HEAD^` can
# be absent, and `VERCEL_GIT_PREVIOUS_SHA` (the last *successful* deployment
# for this project and branch) can point outside those ten commits. Both are
# checked with `git cat-file -e` before use; if neither yields a base commit
# we cannot compute a diff, so we build.
#
# ---------------------------------------------------------------------------
# WHY THE BASE IS NOT JUST `HEAD^`.
# ---------------------------------------------------------------------------
#
# `git diff HEAD^ HEAD` only sees the newest commit. Push two commits to main
# at once — N-1 touching apps/web, N touching only .github — and a HEAD^-only
# guard skips the build and the web change never ships. VERCEL_GIT_PREVIOUS_SHA
# is the last thing this project actually deployed on this branch, so diffing
# against it covers everything that has accumulated since. `HEAD^` is only the
# production fallback for when Vercel does not supply it.
#
# On previews there is deliberately no `HEAD^` fallback: with no previous
# deployment the branch has no preview URL yet, and the e2e pass needs one. A
# branch's first build always happens.
#
# ---------------------------------------------------------------------------
# MAINTENANCE: THE PATH LISTS ARE AN ALLOWLIST.
# ---------------------------------------------------------------------------
#
# A commit that touches nothing in a project's list is skipped for that
# project. A NEW BUILD INPUT THAT IS NOT ADDED HERE WILL NEVER DEPLOY. If you
# add a directory that either deployment reads from, add it below in the same
# commit.
#
set -u

readonly SKIP=0
readonly BUILD=1

log() { printf '[vercel-ignore-build] %s\n' "$*" >&2; }

# Run from the repository root so every pathspec below is root-relative and
# reads the same for both projects, whatever Root Directory Vercel started us
# in (the ignore command runs inside the project's Root Directory).
cd "$(dirname "$0")" 2>/dev/null || { log 'cannot cd to script dir; building'; exit "$BUILD"; }
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$repo_root" ]; then
  log 'no git checkout here; building'
  exit "$BUILD"
fi
cd "$repo_root" || exit "$BUILD"

project="${1:-}"

# Preserved from the previous dashboard command, which was
#   if [ "${VERCEL_GIT_COMMIT_REF#dependabot/}" != "$VERCEL_GIT_COMMIT_REF" ]; ...
# i.e. a plain prefix match on the branch name. Dependabot branches are
# lockfile churn; their previews are not worth a deployment. This does nothing
# once the PR is merged, because the merge lands on main — which is the gap the
# path filtering below closes.
case "${VERCEL_GIT_COMMIT_REF:-}" in
  dependabot/*)
    log "branch ${VERCEL_GIT_COMMIT_REF} is a Dependabot branch; skipping"
    exit "$SKIP"
    ;;
esac

case "$project" in
  api)
    # The Python cloud function. api/index.py is the entrypoint, the ROOT
    # requirements.txt is what Vercel pip-installs (backend/requirements.txt is
    # deliberately a different, much heavier file and is not used here), and
    # vercel.json's `includeFiles` ships backend/jobtracker/**. vercel.json
    # itself carries the function config, headers and CSP; .vercelignore is
    # read from the repo root for every project in this repo and decides what
    # survives into the build.
    paths=(api requirements.txt backend/jobtracker vercel.json .vercelignore)
    ;;
  web)
    # The Next.js app. apps/web is self-contained: its own package.json and
    # pnpm-lock.yaml, no workspace: deps, no transpilePackages, no
    # outputFileTracingRoot. The root vercel.json is NOT an input — Vercel
    # reads configuration from the Root Directory, so this project reads
    # apps/web/vercel.json. The root .vercelignore IS an input: it once
    # excluded apps/web and every web build failed with NEXT_NO_VERSION.
    paths=(apps/web .vercelignore)
    ;;
  *)
    log "unknown project '${project}'; building"
    exit "$BUILD"
    ;;
esac

# VERCEL_GIT_COMMIT_SHA is the commit being deployed, so it equals HEAD in a
# real build. Reading it through a variable is what makes this script testable
# against historical commits without a deployment.
head_sha="${VERCEL_GIT_COMMIT_SHA:-HEAD}"
if ! git cat-file -e "${head_sha}^{commit}" 2>/dev/null; then
  log "head ${head_sha} is not in this clone; building"
  exit "$BUILD"
fi

base_sha="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [ -n "$base_sha" ] && ! git cat-file -e "${base_sha}^{commit}" 2>/dev/null; then
  log "VERCEL_GIT_PREVIOUS_SHA ${base_sha} is outside the shallow clone; falling back"
  base_sha=''
fi
if [ -z "$base_sha" ] && [ "${VERCEL_ENV:-}" = 'production' ]; then
  base_sha="$(git rev-parse --verify -q "${head_sha}^" 2>/dev/null || true)"
fi
if [ -z "$base_sha" ]; then
  log 'no usable base commit; building'
  exit "$BUILD"
fi

# `git diff --quiet` exits 0 for "no difference" and 1 for "differences", which
# is the inversion Vercel wants already. Anything else (128 and friends) is an
# error and falls through to BUILD.
if git diff --quiet "$base_sha" "$head_sha" -- "${paths[@]}"; then
  log "${project}: no changes in ${paths[*]} between ${base_sha} and ${head_sha}; skipping"
  exit "$SKIP"
fi

log "${project}: changes found in ${paths[*]}; building"
exit "$BUILD"
