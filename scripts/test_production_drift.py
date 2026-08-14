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

Every SHA below is a real commit of this repository, with its real timestamp,
and the elapsed times are computed against those timestamps rather than
asserted. That is what makes these fixtures worth more than synthetic ones --
and it is also why the suite FAILS, loudly, when the clone is too shallow to
contain them, instead of skipping.
"""

from __future__ import annotations

import subprocess
import sys
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

    print(f"\n{len(CASES) - failures}/{len(CASES)} cases passed")
    if failures:
        print(
            "\nThe drift detector no longer answers correctly for commits whose "
            "answer is known. Fix the detector, not these fixtures."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
