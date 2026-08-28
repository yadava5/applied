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
# What it does NOT do is lower the Hobby plan's 100-deployments-per-day cap.
# Vercel's docs are explicit, and this is the opposite of the intuitive
# reading, so it is written down here rather than re-derived later:
#
#   "Canceled builds are counted as full deployments as they execute a build
#    command in the build step. This means that any canceled builds initiated
#    using the ignore build step will still count towards your deployment
#    quotas and concurrent build slots."
#   -- https://vercel.com/docs/project-configuration/project-settings#ignored-build-step
#
# What a skip here buys is build minutes, the single Hobby concurrent-build
# slot released in well under a second instead of a full Next.js build, and a
# production deployment that no-op commits stop replacing. Cutting the
# *number* of deployments needs `git.deploymentEnabled`, which lives in both
# vercel.json files and stops one being created at all.
#
# ---------------------------------------------------------------------------
# THE API NO LONGER TAKES PREVIEW DEPLOYMENTS, AND THAT IS WHY.
# ---------------------------------------------------------------------------
#
# On 2026-08-13 the api project spent its whole allowance on previews and then
# could not deploy production for eleven hours. The live API served a commit
# from 16:48 UTC while main was twenty-one commits ahead; every main commit
# after it carried
#
#   Vercel - jobtracker-web: success
#   Vercel - jobtracker-api: failure - Deployment rate limited, retry in 24h
#
# Four of those commits touch this script's own api allowlist, so the filter
# was not the cause and no amount of tuning it would have helped: the
# deployments were never created. The whole night's backend work — the
# migration runner, the Gmail cursor fixes, the employer-identity work — was
# merged, green, and not running.
#
# Nothing consumes an api PREVIEW. `e2e-ci.yml` boots its own FastAPI on
# localhost:8000 and its own Next server on localhost:3000
# (BACKEND_API_URL/PLAYWRIGHT_BASE_URL), and `production.spec.ts` runs against
# a local `next start`. There is also no UI on a preview of this project to
# look at by hand. So ./vercel.json now says
#
#   "deploymentEnabled": { "**": false, "main": true }
#
# which stops the deployment being CREATED for every branch but main. The
# precedence is documented and is not most-specific-wins: "If a branch matches
# multiple rules and at least one rule is `true`, a deployment will occur."
# (https://vercel.com/docs/project-configuration/git-configuration). `"**"`
# alone would take production with it — main matches it — so the `"main": true`
# key is load-bearing, not decorative. Do not simplify it away.
#
# The two `dependabot/` keys it replaced are gone, and one of them never
# worked: minimatch `*` does not cross `/`, so `dependabot/*` matched none of
# the real three-segment branch names (`dependabot/npm_and_yarn/apps/web/...`).
# `dependabot/**` was carrying it alone, and `**` subsumes both.
#
# UNVERIFIED, and the reason this shipped behind a watch rather than a
# assumption: which commit's vercel.json Vercel reads when deciding whether to
# create a deployment is not documented anywhere, and vercel/vercel#11176
# ("deploymentEnabled is ignored") is open. If a branch cut before this change
# still deploys, that is the answer. Confirm on the next push to main that a
# PRODUCTION deployment is still created — if it is not, this key is the first
# suspect and reverting it restores the previous behaviour exactly.
#
# The web project is deliberately NOT changed. Its previews are looked at by a
# human before merge, which is a real use; the api's were not.
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
# When the supplied base is outside the clone, we first try to widen the clone
# by exactly one commit — `git fetch --depth=1 origin <sha>` — rather than give
# up on it. That asks the remote for a single commit and its trees, not for a
# deepened history, and it is what makes the correct wide window readable in a
# ten-commit checkout. Verified against this repo: in a real `--depth=10` clone
# at 374a07f4, 47fc1042 was absent, the fetch made it readable, and the diff
# over the full window then answered correctly.
#
# The fetch is best effort and is never load-bearing. A build container may
# have no network, no credential the remote still accepts, or a remote that
# will not serve a bare SHA; GIT_TERMINAL_PROMPT=0 makes a stale credential
# fail fast instead of blocking on a prompt nobody can answer. If the fetch
# cannot run, or the base is still unreadable after it, we build.
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
# "Vercel supplied no previous SHA" and "Vercel supplied one we cannot read"
# are not the same case, and this script used to conflate them. With nothing
# supplied there is no wider window to measure and `HEAD^` is the best guess
# available — that is the path that makes a project's first production deploy
# work, and it stays. With one supplied but unreadable we *know* the window is
# wider than one commit and we cannot see into it; narrowing to `HEAD^` there
# answers a question nobody asked, and answers it with a confident SKIP.
#
# That is not hypothetical. Deployment dpl_2oExy742yPoteHNp4PHxbKXHJ6za
# (jobtracker-api, commit 374a07f4) logged:
#
#   VERCEL_GIT_PREVIOUS_SHA 47fc1042... is outside the shallow clone; falling back
#   api: no changes in ... between 439a4845... and 374a07f4...
#
# True of that one-commit window and false of the real one: 47fc1042..374a07f4
# carries e67419e, +51 lines in backend/jobtracker/cloud/pipeline.py, plus
# requirements.txt and vercel.json. Twelve of the twenty api production
# deployments before this change were CANCELED, and that pipeline fix never got
# a deployment at all — the live api alias still resolved to a hand-run CLI
# deploy from before it merged. So an unresolvable supplied base exits BUILD,
# and the two cases stay distinguishable in the log as well as in the code.
#
# Previews do get the fetch, so a preview whose supplied base sits outside the
# clone is decided on its real window instead of always building; a push that
# touches nothing the project builds from can legitimately skip where it used
# to not be measurable.
#
# ---------------------------------------------------------------------------
# A PREVIEW'S FIRST BUILD IS NOT UNCONDITIONAL ANY MORE.
# ---------------------------------------------------------------------------
#
# A branch that has never deployed for this project has no
# VERCEL_GIT_PREVIOUS_SHA, and this script used to answer that with an
# unconditional BUILD. The reason recorded here was that "the branch has no
# preview URL yet, and the e2e pass needs one". THAT REASON WAS FALSE WHEN IT
# WAS WRITTEN AND IS STILL FALSE. Nothing in .github/workflows reads a preview
# URL: `e2e-ci.yml` pins PLAYWRIGHT_BASE_URL to http://localhost:3000 in both
# of its Playwright jobs and boots its own servers. A preview URL is looked at
# by a human, and a branch with no changes under apps/ has nothing to look at.
#
# What the unconditional build actually bought was waste. The six real
# jobtracker-web previews of 2026-08-27/28, read out of their build logs:
#
#   e353a3e  changes found in apps/web       BUILD  26s  correct
#   d5b9bb5  changes found in apps/web       BUILD  21s  correct
#   b0705a2  changes found in apps/web       BUILD  27s  correct
#   36b00a3  no usable base commit           BUILD  24s  right answer, no reason
#   736a6a2  no usable base commit           BUILD  20s  BACKEND ONLY  (#553)
#   ccf19f1  no usable base commit           BUILD  21s  BACKEND ONLY  (#547)
#   304f79c  no usable base commit           BUILD  27s  BACKEND ONLY  (#538)
#
# Three full Next.js builds of a bundle those commits cannot change, and a
# fourth that happened to be right by accident. Each is also a production-slot
# holder and a deployment that replaces nothing.
#
# THE WINDOW IS THE DEFAULT BRANCH'S TIP, and the choice is deliberate:
#
#   `HEAD^`      wrong for the reason given above — a branch's first push can
#                carry many commits, and the newest one is not the window.
#   merge base   exactly right, and unavailable: it needs history a
#                `--depth=10` clone does not have, and a `--depth=1` fetch of
#                the default branch cannot supply it either.
#   branch tip   one commit to fetch, and its only error is in the SAFE
#                direction. When the default branch has moved on with changes
#                this branch does not carry, the diff sees them and BUILDS —
#                a wasted build, never a missed one. It can only skip when the
#                branch's tree for this project's paths already equals what
#                the default branch holds, and then there is by construction
#                nothing to preview.
#
# Production is untouched by this: it keeps the `HEAD^` fallback, because
# `origin/main` on a production build IS the commit being deployed and diffing
# a commit against itself would skip every first deploy.
#
# The arm is entered only on VERCEL_ENV=preview, not on "anything that is not
# production". An unset or unrecognised VERCEL_ENV means we are not in a build
# whose shape we understand, and the doctrine three sections up applies: an
# uncertain path builds.
#
# HOW TO REPRODUCE THIS ARM WITHOUT A DEPLOYMENT. The unit suite cannot reach
# the network, so it builds a synthetic repository and hands the arm a local
# refs/remotes/origin/main. That proves the logic, not the fetch. For the
# fetch, make the clone Vercel makes:
#
#   git clone --depth=10 --branch <branch> git@github.com:yadava5/applied.git /tmp/c
#   cp vercel-ignore-build.sh /tmp/c/ && cd /tmp/c
#   VERCEL_ENV=preview VERCEL_GIT_COMMIT_REF=<branch> \
#     VERCEL_GIT_COMMIT_SHA=$(git rev-parse HEAD) bash vercel-ignore-build.sh web
#
# On 2026-08-28 that clone had no refs/remotes/origin/main, the depth-1 fetch
# supplied d131f25, and the arm answered SKIP for a branch whose whole diff is
# this script. The FIRST deployment to take this arm nonetheless logged
# "main is unreachable" — the same recipe over Vercel's HTTPS remote rather
# than SSH. That is why the failure now prints the remote list and the fetch's
# own stderr instead of only its own conclusion.
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

# The branch every preview is measured against when Vercel supplies no base;
# see A PREVIEW'S FIRST BUILD below. Vercel exposes no default-branch variable,
# so this is written down here rather than guessed at the call site.
readonly DEFAULT_BRANCH=main

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
# dependency churn; their previews are not worth a deployment. This does
# nothing once the PR is merged, because the merge lands on main — which is the
# gap the path filtering below closes.
#
# This is now a BACKSTOP, not the primary mechanism. `git.deploymentEnabled`
# in both vercel.json files stops Dependabot deployments from being *created*
# at all, which is the only thing that actually saves quota — reaching this
# branch of the script means a deployment was created anyway, so skip it.
# Note the prefix match here is on the whole ref and is not glob-based, so
# unlike the minimatch patterns in vercel.json it needs no `**`.
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

# A base Vercel supplied and a base it did not are handled differently on
# purpose; see WHY THE BASE IS NOT JUST `HEAD^` above. Nothing below may blank
# $base_sha once it has been supplied — that is exactly how the supplied case
# used to fall through into the `HEAD^` fallback and skip real changes.
base_sha="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [ -n "$base_sha" ] && ! git cat-file -e "${base_sha}^{commit}" 2>/dev/null; then
  log "VERCEL_GIT_PREVIOUS_SHA ${base_sha} is outside the shallow clone; fetching it"
  GIT_TERMINAL_PROMPT=0 git fetch --no-tags --depth=1 origin "$base_sha" >/dev/null 2>&1 || true
  if git cat-file -e "${base_sha}^{commit}" 2>/dev/null; then
    log "fetched ${base_sha}; measuring the full window"
  else
    log "cannot resolve supplied base ${base_sha}; building rather than narrowing to HEAD^"
    exit "$BUILD"
  fi
fi
if [ -z "$base_sha" ] && [ "${VERCEL_ENV:-}" = 'production' ]; then
  base_sha="$(git rev-parse --verify -q "${head_sha}^" 2>/dev/null || true)"
  if [ -n "$base_sha" ]; then
    log "no previous deployment supplied; falling back to HEAD^ ${base_sha}"
  fi
fi
if [ -z "$base_sha" ] && [ "${VERCEL_ENV:-}" = 'preview' ]; then
  # A preview branch that has never deployed here also gets no previous SHA.
  # See A PREVIEW'S FIRST BUILD in the header for why that stopped meaning
  # "build unconditionally". Resolve the default branch's tip locally first —
  # a full clone already has it — and only ask the remote for the one commit
  # when it does not. Both arms may leave $base_sha empty, and the check below
  # then builds.
  base_sha="$(git rev-parse --verify -q "origin/${DEFAULT_BRANCH}^{commit}" 2>/dev/null || true)"
  if [ -z "$base_sha" ]; then
    # A --depth=10 --single-branch clone has no remote-tracking ref for the
    # default branch, so the tip has to be fetched — one commit, not a
    # deepened history.
    #
    # THERE IS NO `origin` ON A VERCEL BUILDER. Measured, on deployment
    # jobtracker-cne7abe27 (commit 072d79c):
    #
    #   [vercel-ignore-build] no previous deployment supplied and main is unreachable
    #   [vercel-ignore-build]   remotes:
    #   [vercel-ignore-build]   fetch said: fatal: 'origin' does not appear to be a git repository
    #
    # The remote list is EMPTY. Vercel clones and then drops the remote, so
    # every `git fetch origin ...` in this file — including the one the
    # supplied-base arm has been making since #150 — is a no-op there. The same
    # clone made by hand over SSH has an `origin` and the fetch works, which is
    # why this was invisible until the failure printed its own stderr.
    #
    # So name the URL instead of a remote. `git fetch <url> <ref>` needs no
    # remote to exist and no credential for a PUBLIC repository, which this one
    # is; if it ever stops being public the fetch fails and the arm falls
    # through to BUILD, which is the safe direction. A checkout that HAS a
    # remote (a developer running the reproduction recipe below) is tried
    # first, so the local path costs no network at all.
    #
    # VERCEL_GIT_REPO_OWNER and VERCEL_GIT_REPO_SLUG are Vercel's documented
    # system variables, and unlike the empty remote list above they have NOT
    # been observed on a builder here. That is why the failure line prints the
    # URL it built: if the variables are absent the log says "(no repository
    # URL to build)" and the deployment builds, so the next preview's log is
    # the test and there is no state in which a wrong guess here fails quietly.
    fetch_err="$(GIT_TERMINAL_PROMPT=0 git fetch --no-tags --depth=1 origin "$DEFAULT_BRANCH" 2>&1 >/dev/null)" || true
    base_sha="$(git rev-parse --verify -q 'FETCH_HEAD^{commit}' 2>/dev/null || true)"
    origin_url=""
    if [ -z "$base_sha" ] && [ -n "${VERCEL_GIT_REPO_OWNER:-}" ] && [ -n "${VERCEL_GIT_REPO_SLUG:-}" ]; then
      origin_url="https://github.com/${VERCEL_GIT_REPO_OWNER}/${VERCEL_GIT_REPO_SLUG}.git"
      fetch_err="$(GIT_TERMINAL_PROMPT=0 git fetch --no-tags --depth=1 "$origin_url" \
        "$DEFAULT_BRANCH" 2>&1 >/dev/null)" || true
      base_sha="$(git rev-parse --verify -q 'FETCH_HEAD^{commit}' 2>/dev/null || true)"
    fi
  fi
  if [ -n "$base_sha" ]; then
    log "no previous deployment supplied; measuring against ${DEFAULT_BRANCH} tip ${base_sha}"
  else
    # Say WHY. The first deployment to take this arm reported only that the
    # branch was unreachable, which is exactly as much as "it did not work" —
    # and the arm above it has been fetching just as blindly for as long.
    log "no previous deployment supplied and ${DEFAULT_BRANCH} is unreachable"
    log "  remotes: $(git remote 2>/dev/null | tr '\n' ' ')"
    log "  tried: ${origin_url:-(no repository URL to build)}"
    log "  fetch said: ${fetch_err:-(nothing)}"
  fi
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
