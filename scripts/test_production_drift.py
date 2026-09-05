#!/usr/bin/env python3
"""
Negative control for scripts/check_production_drift.py.

Run:  python3 scripts/test_production_drift.py

A detector written because nothing reported a silent failure has exactly one
way to be worthless: quietly answering OK. So it is aimed here at commits that
GENUINELY did not deploy -- `12b8aee` and `60fcec2`, the two merges in #174
that produced no production deployment at all -- and required to go red for
each. If it stays green on those, this exits 1 and names the case.

The other half matters as much. A detector that cannot tell a benign skip from
a silent miss is not a detector, it is an alarm bell wired to the door. So the
green cases are pinned too, and the sharpest of them is `975d72e`: #243's own
merge, which Vercel deliberately skipped on BOTH projects ("Canceled by
Ignored Build Step" on each) and which therefore left production legitimately
behind main forever. Anything that reds on that reds on every docs commit.

The second block is the provenance gate, and it is the same argument one
level down. The detector compares SHAs reported by a hostname, and for a day
that hostname was somebody else's application; a foreign host reporting main's
tip is a green check over a page nobody visits. Those cases run the REAL
`live_findings` with the Vercel API and /health stubbed, so they pin the gate
being on the path and not merely present -- the fake records every path asked
for and refuses to answer one it does not recognise.

Every SHA below is a real commit of this repository, with its real timestamp,
and the elapsed times are computed against those timestamps rather than
asserted. That is what makes these fixtures worth more than synthetic ones --
and it is also why the suite FAILS, loudly, when the clone is too shallow to
contain them, instead of skipping.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DETECTOR = REPO_ROOT / "scripts" / "check_production_drift.py"

DRIFT_EXIT = 1
UNKNOWN_EXIT = 2

# Real commits, from #174's evidence table and this repo's history.
#
#   d3765b2  #168 merged 19:14:13Z, deployed 19:15:11Z (58s)
#   12b8aee  #165 merged 19:51:27Z, NEVER DEPLOYED (rate-limited, both projects)
#   9394485  #170 merged 20:03:43Z, deployed 20:04:36Z (53s)
#   60fcec2  #171 merged 20:13:08Z, NEVER DEPLOYED (no status, no record at all)
#   975d72e  #243 merged 2026-08-14, SKIPPED BY THE GUARD on both projects
#   dcbdc8f  #267, what the live api was serving when this check was written
#   7e71ae1  #277, main's tip at that same moment
FIXTURES = (
    "d3765b2",
    "12b8aee",
    "9394485",
    "60fcec2",
    "975d72e",
    "dcbdc8f",
    "7e71ae1",
)

# Each case is (name, argv, expected exit, substrings that must all appear).
# The substrings are not decoration: an exit code alone cannot tell "red for
# the right reason" from "red because the script crashed differently".
CASES: tuple[tuple[str, list[str], int, tuple[str, ...]], ...] = (
    (
        "12b8aee never deployed: web goes RED",
        # 19:51:27Z merge; 20:30Z is 38 minutes later, past the window. In real
        # time this commit was main's tip for only 12 minutes before 9394485
        # carried it to production -- see DEPLOY_GRACE in the detector for why
        # that case is deliberately out of reach of any scheduled check.
        ["--project", "web", "--head", "12b8aee", "--running", "d3765b2",
         "--now", "2026-08-13T20:30:00+00:00"],
        DRIFT_EXIT,
        ("DRIFT", "jobtracker-web", "undeployed for 38m", "guard answers BUILD"),
    ),
    (
        "60fcec2 never deployed: web goes RED",
        ["--project", "web", "--head", "60fcec2", "--running", "9394485",
         "--now", "2026-08-13T21:00:00+00:00"],
        DRIFT_EXIT,
        ("DRIFT", "jobtracker-web", "undeployed for 46m", "guard answers BUILD"),
    ),
    (
        "60fcec2, both projects at once: still RED overall",
        ["--head", "60fcec2", "--running", "9394485",
         "--now", "2026-08-13T21:00:00+00:00"],
        DRIFT_EXIT,
        ("DRIFT", "jobtracker-web"),
    ),
    (
        "60fcec2's api half is a benign skip, and stays GREEN",
        # Both missed merges are dashboard-only. The api genuinely owed no
        # deployment for that window, and saying otherwise would be a false red
        # on the very commits this check exists for.
        ["--project", "api", "--head", "60fcec2", "--running", "9394485",
         "--now", "2026-08-13T21:00:00+00:00"],
        0,
        ("OK", "jobtracker-api", "Ignored Build Step skips this window"),
    ),
    (
        "975d72e was skipped by the guard on BOTH projects: GREEN",
        ["--head", "975d72e", "--running", "975d72e~1",
         "--now", "2026-08-14T20:00:00+00:00"],
        0,
        ("OK", "jobtracker-web", "OK", "jobtracker-api",
         "Ignored Build Step skips this window"),
    ),
    (
        "inside the deploy window: GREEN",
        # 20:33Z is 19 minutes after 60fcec2 merged. At that instant a build
        # could still have been running; the issue was filed at about this
        # time. Being behind is not yet being missed.
        ["--project", "web", "--head", "60fcec2", "--running", "9394485",
         "--now", "2026-08-13T20:33:00+00:00"],
        0,
        ("OK", "still inside the 30m deploy window"),
    ),
    (
        "a deployment in flight: GREEN however old the commit is",
        ["--project", "web", "--head", "60fcec2", "--running", "9394485",
         "--now", "2026-08-13T21:00:00+00:00", "--in-flight", "BUILDING"],
        0,
        ("OK", "BUILDING", "In flight is not"),
    ),
    (
        "production is at main's tip: GREEN",
        ["--project", "web", "--head", "60fcec2", "--running", "60fcec2"],
        0,
        ("OK", "production runs main's tip"),
    ),
    (
        "production running a commit that is not on main: RED",
        # 975d72e is a day NEWER than 60fcec2 and no ancestor of it. This is the
        # CLI-deploy / rollback shape, where a deployment record exists and is
        # healthy and production still is not what main says.
        ["--project", "web", "--head", "60fcec2", "--running", "975d72e",
         "--now", "2026-08-14T20:00:00+00:00"],
        DRIFT_EXIT,
        ("DRIFT", "NOT an ancestor"),
    ),
    (
        "the live state on 2026-08-14: api behind main, legitimately: GREEN",
        # /health answered dcbdc8f (#267) while main was at 7e71ae1 (#277), six
        # commits ahead and none of them touching the api's allowlist. Pinned
        # because a real green is as load-bearing as a real red.
        ["--project", "api", "--head", "7e71ae1", "--running", "dcbdc8f",
         "--now", "2026-08-14T21:00:00+00:00"],
        0,
        ("OK", "jobtracker-api", "Ignored Build Step skips this window"),
    ),
    (
        "a SHA that is not in the clone is UNKNOWN, never OK",
        ["--project", "web", "--head", "0" * 40, "--running", "d3765b2"],
        UNKNOWN_EXIT,
        ("not a commit in this clone",),
    ),
)

# A shrinking suite is a silently weakened one. This is the count as written;
# deleting a case is then a decision that has to be made in the open.
EXPECTED_CASES = 11


def require_fixtures() -> None:
    missing = [
        sha
        for sha in FIXTURES
        if subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        != 0
    ]
    if missing:
        sys.exit(
            "These fixtures are not in this clone: "
            + ", ".join(missing)
            + "\nCheck out with fetch-depth: 0. A suite that skips its fixtures "
            "is the check-that-cannot-fail this detector was written to stop."
        )


def run_case(argv: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(DETECTOR), *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


# --------------------------------------------------------------------------
# the provenance gate: is the host this check probes the project's own?
# --------------------------------------------------------------------------

# Read off the live Vercel API on 2026-09-05, from each project's newest READY
# production deployment. Fixtures, not inventions -- the point of the failing
# case below is that a plausible-looking hostname was tested against the REAL
# alias set and is not in it.
WEB_ALIASES = (
    "getapplied.vercel.app",
    "jobtracker-web-five.vercel.app",
    "jobtracker-web-aesh0323-7401s-projects.vercel.app",
    "jobtracker-web-git-main-aesh0323-7401s-projects.vercel.app",
)
API_ALIASES = (
    "jobtracker-api-seven.vercel.app",
    "jobtracker-api-aesh0323-7401s-projects.vercel.app",
    "jobtracker-api-git-main-aesh0323-7401s-projects.vercel.app",
)

STUB_UID = "dpl_stubbedProductionDeployment"
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


class FakeVercel:
    """Every Vercel path the detector may ask for, and nothing else.

    Two properties this has to have, and neither is decoration:

      it RECORDS what was asked for, because a gate that is never called
      passes every test written for it. The cases assert the aliases path is
      among the calls, which is the difference between "the code exists" and
      "the code is on the path";

      it RAISES on a path it does not know, rather than answering `{}`. A typo
      in the production URL would otherwise yield an empty alias list, which
      the gate reads as "the host is not ours" -- a false red produced by a
      test that passed.

    `aliases` is None for "the API names no production deployment at all",
    which is the state this repository is in TODAY: the token is dead (#472),
    no scope answers, and the gate has nothing to read aliases from. That path
    has to say so rather than go quiet, so it is a case and not a footnote.
    """

    def __init__(self, sha: str, aliases: tuple[str, ...] | None) -> None:
        self.sha = sha
        self.aliases = aliases
        self.paths: list[str] = []

    def __call__(self, path: str, params: dict, token: str) -> dict:
        self.paths.append(path)
        if path == "/v2/teams":
            return {"teams": []}
        if path == "/v7/deployments":
            if self.aliases is None:
                return {"deployments": []}
            return {
                "deployments": [
                    {
                        "uid": STUB_UID,
                        "readyState": "READY",
                        "target": "production",
                        "meta": {"githubCommitSha": self.sha},
                    }
                ]
            }
        if path == f"/v2/deployments/{STUB_UID}/aliases":
            return {
                "aliases": [{"alias": a, "redirect": None} for a in self.aliases]
            }
        raise AssertionError(f"the detector asked for an unstubbed path: {path}")


# (name, project key, the health_url to probe, the alias list the API returns,
#  VERCEL_TOKEN's value, (expected status, expected code, expected exit),
#  substrings that must all appear in the rendered finding).
#
# The alias call is expected exactly when a token is set AND a deployment
# exists to read it from, and that is asserted rather than listed: with no
# credential and no deployment there is nothing to ask.
PROVENANCE_CASES: tuple[
    tuple[
        str, str, str, tuple[str, ...] | None, str, tuple[str, str, int],
        tuple[str, ...],
    ],
    ...,
] = (
    (
        "the web host IS an alias of the project: no new red",
        "web",
        "https://getapplied.vercel.app/api/version",
        WEB_ALIASES,
        "stub-token",
        ("OK", "in-sync", 0),
        ("OK", "jobtracker-web", "is an alias of", STUB_UID),
    ),
    (
        "jobtracker-web.vercel.app is NOT an alias: RED",
        # The mistake this repository actually made, against the real alias
        # set. One operand differs from the case above and nothing else.
        "web",
        "https://jobtracker-web.vercel.app/api/version",
        WEB_ALIASES,
        "stub-token",
        ("DRIFT", "config-host-not-an-alias", 1),
        (
            "DRIFT",
            "jobtracker-web",
            "jobtracker-web.vercel.app is not an alias",
            "determined and wrong",
            # the comparison it replaced survives as evidence: a real drift
            # must not be erased by the provenance verdict.
            "the comparison this replaces",
        ),
    ),
    (
        "the api host IS an alias of the api project: GREEN",
        # Not symmetry for its own sake. This gate can only be safe to ship if
        # the OTHER hardcoded host also passes it, and that was checked against
        # the live API before these fixtures were written.
        "api",
        "https://jobtracker-api-seven.vercel.app/health",
        API_ALIASES,
        "stub-token",
        ("OK", "in-sync", 0),
        ("OK", "jobtracker-api", "is an alias of"),
    ),
    (
        "no token: the gate does not run, does not red, and SAYS so",
        # Failing closed here would red every unauthenticated run over a thing
        # it never measured. Silence would be worse: the note is the whole
        # point, so it is asserted, not the exit code alone.
        "web",
        "https://getapplied.vercel.app/api/version",
        WEB_ALIASES,
        "",
        ("OK", "in-sync", 0),
        (
            "OK",
            "VERCEL_TOKEN is not set",
            "was not checked against jobtracker-web's alias list",
            "this gate did not run",
        ),
    ),
    (
        "a token but no deployment to read aliases from: GREEN, and SAYS so",
        # The state this repository is actually in: #472's dead token means no
        # scope answers, so the gate has nothing to check against. It must not
        # red -- and it must not be silent either, which is the failure mode
        # every other note in this file exists to prevent.
        "web",
        "https://getapplied.vercel.app/api/version",
        None,
        "stub-token",
        ("OK", "in-sync", 0),
        (
            "OK",
            "no scope answered",
            "was not checked against jobtracker-web's alias list",
            "this gate did not run",
        ),
    ),
    (
        "a deployment with NO aliases is nothing to compare against: GREEN",
        # Not the same shape as a wrong host and it must not borrow its code.
        # An alias moves, so the newest-by-creation deployment answers with an
        # empty list whenever the aliases sit on an older promoted one -- an
        # instant rollback. Calling that `config-host-not-an-alias` would send
        # somebody to edit health_url, which is the wrong fix; `alias-stale`
        # and `off-main` are the codes for a rollback.
        "web",
        "https://getapplied.vercel.app/api/version",
        (),
        "stub-token",
        ("OK", "in-sync", 0),
        ("OK", "reports no aliases at all", "this gate did not run"),
    ),
)

EXPECTED_PROVENANCE_CASES = 6


def load_detector():
    """A fresh module per case, so stubs cannot leak between them.

    Registered in sys.modules before execution and replaced there each time:
    `from __future__ import annotations` makes the dataclass annotations
    strings, and @dataclass resolves them through sys.modules[__module__],
    which is None for a module that is not registered.
    """
    spec = importlib.util.spec_from_file_location("check_production_drift", DETECTOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def head_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "7e71ae1^{commit}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def run_provenance_case(case) -> tuple[list[str], str]:
    name, key, health_url, aliases, token, expected, needles = case
    del name
    status, code, exit_code = expected
    sha = head_sha()

    detector = load_detector()
    project = replace(detector.PROJECTS_BY_KEY[key], health_url=health_url)
    detector.PROJECTS = (project,)
    detector.PROJECTS_BY_KEY = {project.key: project}

    fake = FakeVercel(sha, aliases)
    detector.vercel_get = fake
    # /health is stubbed too: a test that reaches the network is a test that
    # goes red when somebody else's DNS does.
    detector.running_commit_from_health = lambda url: (
        sha,
        f"{url} reports commit={sha[:7]}",
    )

    saved = {k: os.environ.get(k) for k in ("VERCEL_TOKEN", "VERCEL_TEAM_ID")}
    try:
        os.environ.pop("VERCEL_TEAM_ID", None)
        if token:
            os.environ["VERCEL_TOKEN"] = token
        else:
            os.environ.pop("VERCEL_TOKEN", None)
        findings = detector.live_findings(sha, NOW, detector.DEPLOY_GRACE)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    problems: list[str] = []
    if len(findings) != 1:
        return [f"expected 1 finding, got {len(findings)}"], ""
    finding = findings[0]
    rendered = finding.render()

    if finding.status != status:
        problems.append(f"status {finding.status}, expected {status}")
    if finding.code != code:
        problems.append(f"code {finding.code!r}, expected {code!r}")
    if detector.EXIT_CODES[finding.status] != exit_code:
        problems.append(
            f"exits {detector.EXIT_CODES[finding.status]}, expected {exit_code}"
        )
    for needle in needles:
        if needle not in rendered:
            problems.append(f"missing from the finding: {needle!r}")

    alias_path = f"/v2/deployments/{STUB_UID}/aliases"
    asked = alias_path in fake.paths
    expected_call = bool(token) and aliases is not None
    if expected_call and not asked:
        problems.append(
            f"the gate never ran: {alias_path} was not requested "
            f"(asked for {fake.paths})"
        )
    if not expected_call and asked:
        problems.append(
            f"asked for {alias_path} with nothing to ask it about "
            f"(token={token!r}, aliases={aliases!r})"
        )
    return problems, rendered


def run_provenance_block() -> int:
    if len(PROVENANCE_CASES) != EXPECTED_PROVENANCE_CASES:
        sys.exit(
            f"expected {EXPECTED_PROVENANCE_CASES} provenance cases, found "
            f"{len(PROVENANCE_CASES)}. If a case was removed on purpose, change "
            "EXPECTED_PROVENANCE_CASES in the same commit."
        )

    failures = 0
    for case in PROVENANCE_CASES:
        problems, rendered = run_provenance_case(case)
        if problems:
            failures += 1
            print(f"FAIL  {case[0]}")
            for problem in problems:
                print(f"      {problem}")
            print("      --- finding ---")
            for line in rendered.splitlines():
                print(f"      {line}")
        else:
            print(f"ok    {case[0]}")
    return failures


def main() -> int:
    require_fixtures()

    if len(CASES) != EXPECTED_CASES:
        sys.exit(
            f"expected {EXPECTED_CASES} cases, found {len(CASES)}. If a case was "
            "removed on purpose, change EXPECTED_CASES in the same commit."
        )

    failures = 0
    for name, argv, expected_exit, needles in CASES:
        code, output = run_case(argv)
        problems = []
        if code != expected_exit:
            problems.append(f"exit {code}, expected {expected_exit}")
        for needle in needles:
            if needle not in output:
                problems.append(f"missing from output: {needle!r}")
        if problems:
            failures += 1
            print(f"FAIL  {name}")
            for problem in problems:
                print(f"      {problem}")
            print("      --- detector output ---")
            for line in output.splitlines():
                print(f"      {line}")
        else:
            print(f"ok    {name}")

    print(f"\n{len(CASES) - failures}/{len(CASES)} history cases passed")

    print("")
    provenance_failures = run_provenance_block()
    total = len(PROVENANCE_CASES)
    print(f"\n{total - provenance_failures}/{total} provenance cases passed")

    if failures:
        print(
            "\nThe drift detector no longer answers correctly for commits whose "
            "answer is known. Fix the detector, not these fixtures."
        )
    if provenance_failures:
        print(
            "\nThe detector no longer checks that the host it probes belongs to "
            "the project. A foreign host can report main's tip and pass."
        )
    return 1 if failures or provenance_failures else 0


if __name__ == "__main__":
    sys.exit(main())
