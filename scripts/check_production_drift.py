#!/usr/bin/env python3
"""
Is production running what `main` says it is running?

WHY THIS EXISTS

Merges to `main` have produced no production deployment, silently. On
2026-08-13 two of four merges deployed nothing at all (#174): `12b8aee` got a
"Deployment rate limited" status on both projects, and `60fcec2` got *nothing*
-- no deployment, no commit status, `pending` to this day. Nothing went red,
`gh pr checks` showed green, and the only way to notice was to compare the
deployments list against the merge list by hand.

The same silence has a second, worse shape. On 2026-08-14 a database password
was rotated: the Vercel environment was updated and the redeploy that would
have applied it was CANCELED, so production kept running on a dead credential
until somebody thought to curl `/health/schema`. Different mechanism, same
defect --

    the state that MATTERS (what is running) diverged from the state that was
    CHANGED (what is on main), and nothing anywhere compared the two.

So this compares the two, on a schedule, and fails loudly when they disagree
for longer than a bounded window. It is deliberately blind to the cause: a
rate limit, a lost webhook, a CANCELED redeploy and a mis-scoped ignore step
all produce the same divergence and all get the same red.

WHY NOT `GET /repos/:o/:r/deployments?sha=...`

Because it cannot answer the question. Measured on 2026-08-14: `975d72e` was
deliberately skipped by the Ignored Build Step on both projects -- a healthy,
by-design skip -- and has *zero* GitHub deployment records, exactly like
`12b8aee` and `60fcec2` which are the failure. An empty deployments list is
what a benign skip and a silent miss both look like. A CLI deploy creates no
record at all either, while genuinely changing what is running.

Compare SHAs, then. What is RUNNING against what main's tip IS.

WHAT COUNTS AS "RUNNING"

  jobtracker-api   `GET /health` reports `commit`, verbatim from Vercel's own
                   VERCEL_GIT_COMMIT_SHA (backend/jobtracker/main_cloud.py,
                   _build_commit_sha). That is ground truth from outside
                   Vercel's API and it costs no token. It returns null for a
                   CLI deploy, or where the project has "Automatically expose
                   System Environment Variables" turned off -- a REAL STATE,
                   NOT A FAILURE of this check: we fall back to the Vercel API
                   and say so, rather than reporting a miss we did not observe.

  jobtracker-web   `GET /api/version`, since 2026-08-23, and for the same
                   reason. It HAD no such endpoint, so the newest READY
                   production deployment's `meta.githubCommitSha` from the
                   Vercel REST API was the only available answer and that
                   needed a token -- which is how a credential failure came to
                   look like a deployment failure. On 2026-08-22 the token
                   stopped authenticating and every scheduled run went red on
                   the web half while the api half answered normally through
                   the identical 403. The Vercel API stays as the fallback, so
                   a project that stops exposing its commit is still checked,
                   just not for free.

Where both are available they are cross-checked: Vercel saying a
commit is deployed while the live alias serves an older one is the stale-alias
failure this estate has hit twice, and it is worth its own red.

WHEN A DIFFERENCE IS NOT A FAILURE

Three ways for production to sit behind main legitimately, and all three stay
green:

  1. The guard skipped it. `vercel-ignore-build.sh` is the Ignored Build Step
     for both projects; a commit touching nothing in a project's allowlist
     never deploys it, by design, forever. So this asks THE GUARD ITSELF --
     the same script, with the same inputs Vercel supplies -- whether the
     window running..head was one it would have built. A detector that cannot
     tell a benign skip from a silent miss cries wolf on every docs commit.
  2. The build has not had time. See DEPLOY_GRACE.
  3. A deployment for the tip is QUEUED, INITIALIZING or BUILDING. In flight
     is not a miss.

And one way to be red that is not "no deployment": production running a commit
that is not an ancestor of main at all (a CLI deploy off a branch, a rollback,
a force-push). That is divergence too and it is reported as such.

RUNNING IT AGAINST HISTORY

    check_production_drift.py --project web --head 60fcec2 --running 9394485

is the negative control, and the reason the comparison lives in a script
instead of in YAML: it can be aimed at a commit that genuinely did not deploy
and required to go red. `scripts/test_production_drift.py` pins those cases.

EXIT CODES

    0  every project agrees with main, or differs for a reason listed above
    1  DRIFT -- production is behind main and a deployment was owed
    2  UNKNOWN -- the check could not be made (no token, API error, a SHA
       missing from the clone). NOT green. A check that cannot run must not
       look like a check that passed; that is the defect this file exists to
       stop, and it would be absurd to reproduce it here.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "vercel-ignore-build.sh"

VERCEL_API = "https://api.vercel.com"

# HOW LONG PRODUCTION MAY LAG MAIN BEFORE THAT IS A FAILURE.
#
# Not a magic number. Every production deployment this repo has that DID happen
# landed about a minute after its merge:
#
#     d3765b2  #168   58s        219da9e  #265   ~35s
#     9394485  #170   53s        f5686cf  #264   ~43s
#
# So 30 minutes is roughly thirty times the observed worst case. The headroom
# is for the things that legitimately make a build slow rather than missing: a
# cold Next.js build, a queue behind another project's build slot, and GitHub's
# own cron drift. It is bounded well inside the 24-hour rate-limit window that
# caused #174, which is the point -- "eventually somebody notices" was the old
# behaviour.
#
# Shortening it does not buy the self-concealing case. `12b8aee` was main's tip
# for only twelve minutes before `9394485` merged and carried it to production;
# no scheduled check with a realistic cadence catches that, and its code
# reached production anyway. The case that matters is the LAST merge of a run
# -- `60fcec2`, which sat undeployed for hours with nothing red -- and any
# window under an hour catches it.
#
# The clock runs from the tip's COMMITTER date, which a normal GitHub merge
# sets to the merge time. A cherry-pick, or a rebase with
# --committer-date-is-author-date, would carry an older date onto main and look
# stale the moment it lands; where a token is available the in-flight exemption
# absorbs that, and on the token-free api path it would cost one false red.
DEPLOY_GRACE = timedelta(minutes=30)

# A deployment in one of these states is being worked on. Behind-but-building
# is not a miss.
IN_FLIGHT_STATES = frozenset({"QUEUED", "INITIALIZING", "BUILDING"})

OK = "OK"
DRIFT = "DRIFT"
UNKNOWN = "UNKNOWN"

EXIT_CODES = {OK: 0, DRIFT: 1, UNKNOWN: 2}


@dataclass(frozen=True)
class Project:
    """One Vercel project built from this repository."""

    key: str  # the argument vercel-ignore-build.sh takes: `web` or `api`
    vercel_name: str  # the Vercel project name; `projectId` accepts a name
    health_url: str | None  # an endpoint that reports its own running commit


PROJECTS = (
    Project(
        "web",
        "jobtracker-web",
        # Added 2026-08-23. This project used to carry `None` here and its only
        # answer came from the Vercel REST API, so it needed a token -- and when
        # the token stopped authenticating on 2026-08-22 (HTTP 403, SAML
        # re-auth) the web half went UNKNOWN on every scheduled run while the
        # api half kept answering through the IDENTICAL 403, because /health
        # costs no credential. `apps/web/app/api/version/route.ts` closes that
        # asymmetry.
        #
        # `getapplied.vercel.app`, and the host this probes was got WRONG on
        # first attempt in a way only production could correct.
        #
        # The reasoning was that `jobtracker-web.vercel.app` is the project's
        # assigned domain and so auto-follows the newest production deployment,
        # while a vanity alias does not. Sound in general, false here. Measured
        # the moment #477 deployed:
        #
        #   getapplied.vercel.app/       200  <title>Applied · your inbox, made legible</title>
        #   getapplied.vercel.app/api/version
        #                                200  {"commit":"2239a639...","ref":"main","env":"production"}
        #   jobtracker-web.vercel.app/   200  <title>Jobtracker</title>
        #   jobtracker-web.vercel.app/api/version
        #                                404
        #
        # `jobtracker-web` is still the PROJECT name, but that hostname serves
        # the pre-rename application and did not move when production did. It
        # is exactly the stale-host failure the module docstring names -- found
        # by pointing the detector at it and watching it 404 on a route that
        # had just shipped, which is the only reason it was caught before this
        # check went permanently UNKNOWN on a host nobody uses.
        #
        # Whether that hostname is a frozen alias or belongs to something else
        # is NOT established here: the Vercel token is dead (#472) so the alias
        # list cannot be read, and a mechanism nobody has observed does not go
        # in a comment. Filed separately.
        "https://getapplied.vercel.app/api/version",
    ),
    Project(
        "api",
        "jobtracker-api",
        # The api project's ASSIGNED production domain, which auto-follows the
        # newest production deployment. Deliberately not a `vercel alias set`
        # vanity URL: those do not follow, and one being stale is a separate
        # bug this check should be able to see rather than inherit.
        "https://jobtracker-api-seven.vercel.app/health",
    ),
)

PROJECTS_BY_KEY = {p.key: p for p in PROJECTS}


@dataclass
class Finding:
    """One project's verdict, and every line of evidence behind it."""

    project: str
    status: str
    code: str
    headline: str
    evidence: list[str] = field(default_factory=list)

    def render(self) -> str:
        first = f"{self.status:<7} {self.project:<15} {self.headline}"
        rest = [f"{'':<7} {'':<15} {line}" for line in self.evidence]
        return "\n".join([first, *rest])


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def resolve(rev: str) -> str | None:
    """Full SHA for `rev`, or None when it is not in this clone."""
    try:
        return git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}") or None
    except RuntimeError:
        return None


def commit_time(sha: str) -> datetime:
    return datetime.fromisoformat(git("show", "-s", "--format=%cI", sha))


def short(sha: str) -> str:
    return sha[:7]


def is_ancestor(older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def head_of_main() -> tuple[str, str]:
    """(sha, the ref it came from). `origin/main` first, then HEAD.

    On a schedule the workflow checks main out, so HEAD is main; `origin/main`
    is preferred anyway so that a stale local checkout cannot answer for the
    branch. Any other branch is not this check's business -- the caller passes
    --head explicitly if it wants one.
    """
    for ref in ("origin/main", "refs/remotes/origin/main", "main", "HEAD"):
        sha = resolve(ref)
        if sha:
            return sha, ref
    raise RuntimeError("no main to check: neither origin/main nor HEAD resolves")


# --------------------------------------------------------------------------
# the guard -- "would Vercel have built this window?"
# --------------------------------------------------------------------------

GUARD_SKIP = "skip"
GUARD_BUILD = "build"
GUARD_UNREADABLE = "unreadable"


def guard_verdict(project_key: str, base: str, head: str) -> tuple[str, str]:
    """Ask vercel-ignore-build.sh whether base..head is a window it builds.

    Reconstructed exactly as Vercel runs it: VERCEL_GIT_PREVIOUS_SHA is "the
    last successful deployment for this project and branch", which is what
    `base` is here, and VERCEL_ENV=production is the branch of the guard that
    main takes. VERCEL_GIT_COMMIT_REF is deliberately unset -- the Dependabot
    backstop must not fire on a value we invented.

    Exit codes are inverted and documented in the guard's own header: 0 SKIP,
    1 BUILD. Anything else is a crash, and the guard fails OPEN (>=1 builds).
    Fail-open is right for a deploy guard and wrong for a detector -- a crash
    would become a false red every half hour -- so a third answer is returned
    and reported as UNKNOWN rather than folded into BUILD.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERCEL_")}
    env["VERCEL_GIT_COMMIT_SHA"] = head
    env["VERCEL_GIT_PREVIOUS_SHA"] = base
    env["VERCEL_ENV"] = "production"

    result = subprocess.run(
        ["bash", str(GUARD), project_key],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    log = result.stderr.strip().splitlines()
    detail = log[-1] if log else "(no output)"
    if result.returncode == 0:
        return GUARD_SKIP, detail
    if result.returncode == 1:
        return GUARD_BUILD, detail
    return GUARD_UNREADABLE, f"exit {result.returncode}: {detail}"


# --------------------------------------------------------------------------
# the comparison -- the whole point, and offline-testable
# --------------------------------------------------------------------------


def humanise(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return f"-{humanise(-delta)}"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def evaluate(
    project_key: str,
    head_sha: str,
    running_sha: str | None,
    now: datetime,
    *,
    in_flight: str | None = None,
    grace: timedelta = DEPLOY_GRACE,
    source: str = "",
) -> Finding:
    """Compare what is running against main's tip, for one project.

    Pure with respect to the network: everything it needs is git plus the two
    SHAs. That is what lets `--head`/`--running` aim it at history.
    """
    project = PROJECTS_BY_KEY[project_key]
    name = project.vercel_name
    origin = f" ({source})" if source else ""

    if running_sha is None:
        return Finding(
            name,
            UNKNOWN,
            "no-running-commit",
            "cannot tell what production is running",
            [
                "no READY production deployment reported, and no running commit",
                "from /health. Absence of a record is not evidence of a miss --",
                "a CLI deploy leaves none either -- so this is UNKNOWN, not OK.",
            ],
        )

    if not resolve(running_sha):
        return Finding(
            name,
            UNKNOWN,
            "running-commit-unknown-to-clone",
            f"production runs {short(running_sha)}, which is not in this clone",
            [
                "checkout with fetch-depth: 0, or the comparison is guesswork",
            ],
        )

    if running_sha == head_sha:
        return Finding(
            name,
            OK,
            "in-sync",
            f"production runs main's tip {short(head_sha)}{origin}",
        )

    if not is_ancestor(running_sha, head_sha):
        return Finding(
            name,
            DRIFT,
            "off-main",
            f"production runs {short(running_sha)}, which is NOT an ancestor of "
            f"main's tip {short(head_sha)}{origin}",
            [
                "production is serving code that main does not contain: a CLI",
                "deploy off a branch, an instant rollback, or rewritten history.",
                "Whatever the cause, what is running is not what main says.",
            ],
        )

    verdict, detail = guard_verdict(project_key, running_sha, head_sha)
    window = f"{short(running_sha)}..{short(head_sha)}"

    if verdict == GUARD_UNREADABLE:
        return Finding(
            name,
            UNKNOWN,
            "guard-unreadable",
            f"vercel-ignore-build.sh could not answer for {window}",
            [detail],
        )

    if verdict == GUARD_SKIP:
        return Finding(
            name,
            OK,
            "benign-skip",
            f"production runs {short(running_sha)}, {window} behind main{origin}",
            [
                "and that is correct: the Ignored Build Step skips this window,",
                "so no deployment was ever owed. " + detail,
            ],
        )

    age = now - commit_time(head_sha)
    if in_flight:
        return Finding(
            name,
            OK,
            "in-flight",
            f"production runs {short(running_sha)}, {humanise(age)} behind main's "
            f"tip {short(head_sha)}",
            [
                f"a production deployment for it is {in_flight}. In flight is not",
                "a miss.",
            ],
        )

    if age <= grace:
        return Finding(
            name,
            OK,
            "in-window",
            f"production runs {short(running_sha)}; main's tip {short(head_sha)} "
            f"is {humanise(age)} old",
            [
                f"still inside the {humanise(grace)} deploy window. A build takes",
                "time; this is not yet a miss.",
            ],
        )

    return Finding(
        name,
        DRIFT,
        "drift",
        f"main's tip {short(head_sha)} has been undeployed for {humanise(age)}",
        [
            f"production runs {short(running_sha)}{origin}, {window} behind.",
            "The deploy guard answers BUILD for that window, so a production",
            f"deployment was owed and none arrived within {humanise(grace)}.",
            detail,
            "Nothing else reports this: a merge that never deploys posts no",
            "status and creates no deployment record (#174).",
        ],
    )


# --------------------------------------------------------------------------
# Vercel REST API
# --------------------------------------------------------------------------


class VercelError(RuntimeError):
    pass


def vercel_get(path: str, params: dict[str, str], token: str) -> dict:
    url = f"{VERCEL_API}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:  # pragma: no cover - needs a token
        body = exc.read().decode(errors="replace")[:300]
        raise VercelError(f"{path} -> HTTP {exc.code}: {body}") from exc
    except OSError as exc:  # pragma: no cover - needs a network
        raise VercelError(f"{path} -> {exc}") from exc


def candidate_scopes(token: str) -> list[dict[str, str]]:
    """Query parameters to try: VERCEL_TEAM_ID, then personal, then every team.

    The projects live under a team. Rather than hardcode a team slug -- which
    is how a job ends up authenticating fine and looking at nothing -- ask the
    token what it can see and try each scope until a project answers. The
    VERCEL_TEAM_ID override exists because that discovery is not guaranteed:
    a token whose scope forbids listing teams gets nothing back from /v2/teams
    and would otherwise have no way to be told where to look.
    """
    scopes: list[dict[str, str]] = []
    override = os.environ.get("VERCEL_TEAM_ID", "").strip()
    if override:
        scopes.append({"teamId": override})
    scopes.append({})
    try:
        teams = vercel_get("/v2/teams", {"limit": "20"}, token).get("teams", [])
    except VercelError:
        return scopes
    scopes.extend(
        {"teamId": team["id"]}
        for team in teams
        if team.get("id") and team["id"] != override
    )
    return scopes


def describe_scope(scope: dict[str, str]) -> str:
    return f"teamId={scope['teamId']}" if scope.get("teamId") else "personal account"


def production_for(
    project: Project,
    token: str,
    scopes: list[dict[str, str]],
    preferred: dict[str, str] | None,
) -> tuple[list[dict], dict[str, str] | None, str]:
    """(deployments, the scope that answered, a note when none did).

    EVERY candidate is tried, and an error from one does not stop the rest. A
    team-scoped project queried without a teamId answers 403 or 404, NOT an
    empty list, so a loop that lets the first error escape never reaches the
    team scope at all and reports "not authorized" for what is a scope
    mistake -- authenticating fine and looking at nothing, which is the exact
    failure candidate_scopes exists to avoid. The errors are kept and
    surfaced only if nothing answers.
    """
    attempts: list[str] = []
    ordered = ([preferred] if preferred is not None else []) + [
        scope for scope in scopes if scope != preferred
    ]
    for candidate in ordered:
        try:
            deployments = production_deployments(project, token, candidate)
        except VercelError as exc:
            attempts.append(f"{describe_scope(candidate)}: {exc}")
            continue
        if deployments:
            return deployments, candidate, ""
        attempts.append(f"{describe_scope(candidate)}: no production deployments")
    return (
        [],
        None,
        f"no scope answered for {project.vercel_name} -- " + "; ".join(attempts),
    )


def production_deployments(
    project: Project, token: str, scope: dict[str, str]
) -> list[dict]:
    params = {
        "projectId": project.vercel_name,
        "target": "production",
        "limit": "20",
        **scope,
    }
    return vercel_get("/v7/deployments", params, token).get("deployments", [])


def deployment_sha(deployment: dict) -> str | None:
    meta = deployment.get("meta") or {}
    return meta.get("githubCommitSha")


def deployment_state(deployment: dict) -> str:
    return deployment.get("readyState") or deployment.get("state") or ""


# --------------------------------------------------------------------------
# /health -- the running commit, from outside Vercel, with no token
# --------------------------------------------------------------------------


def running_commit_from_health(url: str) -> tuple[str | None, str]:
    """(commit or None, a note explaining which). Never raises."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except Exception as exc:  # noqa: BLE001 - any failure is the same to us
        return None, f"{url} did not answer ({exc})"
    commit = payload.get("commit")
    if not commit:
        return None, (
            f"{url} reports commit=null -- a CLI deploy, or system environment "
            "variables not exposed. A real state, not a failure of this check."
        )
    return commit, f"{url} reports commit={short(commit)}"


# --------------------------------------------------------------------------
# live mode
# --------------------------------------------------------------------------


def live_findings(head_sha: str, now: datetime, grace: timedelta) -> list[Finding]:
    token = os.environ.get("VERCEL_TOKEN", "").strip()
    findings: list[Finding] = []

    scope: dict[str, str] | None = None
    scopes = candidate_scopes(token) if token else []

    for project in PROJECTS:
        health_sha: str | None = None
        health_note = ""
        if project.health_url:
            health_sha, health_note = running_commit_from_health(project.health_url)

        vercel_sha: str | None = None
        in_flight: str | None = None
        vercel_note = ""

        if not token:
            vercel_note = (
                "VERCEL_TOKEN is not set, so the Vercel API was not consulted."
            )
        else:
            deployments, answering, failure = production_for(
                project, token, scopes, scope
            )
            if answering is not None:
                # Remember the scope that worked so the second project does not
                # re-walk every candidate.
                scope = answering
            if failure:
                vercel_note = failure
            else:
                ready = [d for d in deployments if deployment_state(d) == "READY"]
                if ready:
                    vercel_sha = deployment_sha(ready[0])
                    built_from = (
                        short(vercel_sha)
                        if vercel_sha
                        else "a CLI deploy (no commit sha)"
                    )
                    vercel_note = (
                        f"newest READY production deployment "
                        f"{ready[0].get('uid')} is {built_from}"
                    )
                else:
                    vercel_note = (
                        "the Vercel API reports no READY production deployment "
                        f"for {project.vercel_name}"
                    )
                for deployment in deployments:
                    if deployment_state(deployment) in IN_FLIGHT_STATES and (
                        deployment_sha(deployment) == head_sha
                    ):
                        in_flight = deployment_state(deployment)
                        break

        running = health_sha or vercel_sha
        source = "from /health" if health_sha else "from the Vercel API"

        if running is None and not token:
            findings.append(
                Finding(
                    project.vercel_name,
                    UNKNOWN,
                    "no-credential",
                    "cannot tell what production is running",
                    [
                        health_note or "this project exposes no running commit",
                        vercel_note,
                        "Add a read-scoped Vercel token as the VERCEL_TOKEN repo",
                        "secret. Until then this check is blind, and blind is",
                        "reported as UNKNOWN rather than passed.",
                    ],
                )
            )
            continue

        finding = evaluate(
            project.key,
            head_sha,
            running,
            now,
            in_flight=in_flight,
            grace=grace,
            source=source,
        )
        for note in (health_note, vercel_note):
            if note:
                finding.evidence.append(note)

        # The stale-alias check: Vercel believing one commit is deployed while
        # the live domain serves another has happened twice in this estate.
        if (
            finding.status == OK
            and health_sha
            and vercel_sha
            and health_sha != vercel_sha
        ):
            ready_age = now - commit_time(vercel_sha) if resolve(vercel_sha) else grace
            if ready_age > grace:
                finding = Finding(
                    project.vercel_name,
                    DRIFT,
                    "alias-stale",
                    f"Vercel says {short(vercel_sha)} is the newest READY "
                    f"production deployment, but the live domain serves "
                    f"{short(health_sha)}",
                    [
                        "the deployment succeeded and the domain did not follow",
                        "it. Re-point the alias, or promote the deployment.",
                        health_note,
                        vercel_note,
                    ],
                )
        findings.append(finding)

    return findings


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when production is not running what main says it is running."
        ),
    )
    parser.add_argument(
        "--project",
        choices=[p.key for p in PROJECTS],
        help="only this project (default: both)",
    )
    parser.add_argument(
        "--head",
        help=(
            "the commit main is at. Offline mode: with --running, no network is "
            "touched. This is what aims the detector at history."
        ),
    )
    parser.add_argument(
        "--running",
        help="the commit production is running (offline mode)",
    )
    parser.add_argument(
        "--in-flight",
        choices=sorted(IN_FLIGHT_STATES),
        help="offline mode: pretend a deployment for --head is in this state",
    )
    parser.add_argument(
        "--now",
        help="offline mode: ISO-8601 instant to measure elapsed time from",
    )
    parser.add_argument(
        "--grace-minutes",
        type=int,
        default=int(DEPLOY_GRACE.total_seconds() // 60),
        help="how long production may lag main (default: %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    grace = timedelta(minutes=args.grace_minutes)
    now = (
        datetime.fromisoformat(args.now).astimezone(timezone.utc)
        if args.now
        else datetime.now(timezone.utc)
    )

    if args.running and not args.head:
        print("--running needs --head", file=sys.stderr)
        return EXIT_CODES[UNKNOWN]

    projects = [PROJECTS_BY_KEY[args.project]] if args.project else list(PROJECTS)

    if args.head:
        head_sha = resolve(args.head)
        if not head_sha:
            print(f"{args.head} is not a commit in this clone", file=sys.stderr)
            return EXIT_CODES[UNKNOWN]
        head_ref = f"--head {args.head}"
    else:
        head_sha, head_ref = head_of_main()

    if args.running:
        running_sha = resolve(args.running) or args.running
        findings = [
            evaluate(
                project.key,
                head_sha,
                running_sha,
                now,
                in_flight=args.in_flight,
                grace=grace,
                source="given on the command line",
            )
            for project in projects
        ]
    else:
        findings = [
            f
            for f in live_findings(head_sha, now, grace)
            if not args.project or f.project == PROJECTS_BY_KEY[args.project].vercel_name
        ]

    lines = [
        f"main   {head_sha} ({head_ref}, {commit_time(head_sha).isoformat()})",
        f"now    {now.isoformat()}   grace {humanise(grace)}",
        "",
        *[f.render() for f in findings],
    ]
    report = "\n".join(lines)
    print(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### Production vs main\n\n```\n" + report + "\n```\n")

    if any(f.status == DRIFT for f in findings):
        return EXIT_CODES[DRIFT]
    if any(f.status == UNKNOWN for f in findings):
        return EXIT_CODES[UNKNOWN]
    return EXIT_CODES[OK]


if __name__ == "__main__":
    sys.exit(main())
