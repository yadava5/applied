"""The "this week" count is measured on the date the USER APPLIED (#509).

`created_at` is when our sync inserted the row. Counting on it makes the
dashboard header a statement about our batch size rather than the user's week:
measured on the owner's production board, the header read "+47 this wk" for
applications submitted across a fortnight because one sync had just ingested
them, and every one of the 47 dated rows had an ``applied_date`` in a different
calendar week from its ``created_at``. The true answer was 7.

WHY THIS FILE READS SOURCE INSTEAD OF CALLING THE ENDPOINT. The number is
derived in TWO places — the summary endpoint here, and `summarize()` in
`apps/web/lib/dashboard/summary.ts`, which is what the demo twin and the
reference implementation use. Either one alone can be fixed while the other
keeps counting the old way, and BOTH SUITES STAY GREEN: the Python tests never
look at the TypeScript, and the web unit tests never look at the Python. That
is precisely how a twin comes to disagree with the board it stands in for, and
this repo has the scar.

So the lockstep is asserted directly. It is a coarse check and it is meant to
be: it cannot verify the two implementations agree semantically, only that
neither has quietly reverted to the wrong column while the other moved.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_SUMMARY = _REPO_ROOT / "apps" / "web" / "lib" / "dashboard" / "summary.ts"
_BACKEND = _REPO_ROOT / "backend" / "jobtracker" / "cloud" / "applications.py"


def _strip_py_comments(source: str) -> str:
    return re.sub(r"^\s*#.*$", "", source, flags=re.MULTILINE)


def _strip_ts_comments(source: str) -> str:
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


def _this_week_block(source: str) -> str:
    """The backend's this_week query, comments removed.

    Anchored on the assignment and bounded by the closing ``.one()`` so the
    assertions below cannot accidentally pass on some other query in a 4,000
    line module.
    """

    stripped = _strip_py_comments(source)
    start = stripped.index("this_week = (")
    end = stripped.index(").one()", start)
    return stripped[start:end]


def test_the_backend_counts_this_week_on_applied_date() -> None:
    block = _this_week_block(_BACKEND.read_text())
    assert "Application.applied_date" in block, (
        "the summary endpoint is no longer counting on applied_date"
    )
    assert "Application.created_at" not in block, (
        "the summary endpoint is counting this week on the row's insert time again"
    )


def test_the_web_twin_counts_this_week_the_same_way() -> None:
    """THE LOCKSTEP. Fixing one side and not the other leaves both suites green
    and the demo twin disagreeing with the signed-in board about one number."""

    # NOT skipped when the file is missing. A `skipif` here would make the one
    # cross-language guard in this repo evaporate silently in any checkout
    # whose layout moved — which is the check-that-cannot-fail shape, and a
    # verification agent already hit it: run against a backend-only copy of the
    # tree, this test reported SKIPPED and the lockstep went unmeasured while
    # the suite stayed green. This is a monorepo; the file is either there or
    # something is wrong and should say so.
    assert _WEB_SUMMARY.exists(), (
        f"{_WEB_SUMMARY} is missing — the twin-parity guard cannot run, and a "
        "silent skip here is how the two implementations drift apart"
    )
    source = _strip_ts_comments(_WEB_SUMMARY.read_text())
    start = source.index("export function summarize(")
    body = source[start : source.index("\n}", start)]

    # The BASIS, not its spelling. `summarize()` no longer names `applied_date`
    # itself: it counts through `filedAt`, which is the accessor the momentum
    # panel on the same screen already used — and using the panel's own
    # derivation instead of a private second one is the point of #509's
    # revision, not a drift away from it. Asserting the literal column name
    # here would have failed on the fix and passed on the bug, which is the
    # inverted-gate shape this repo has a name for.
    assert "filedAt(" in body, (
        "summarize() no longer counts through filedAt, so the header and the "
        "momentum caption can disagree about the same week again"
    )
    assert "thisWeek" in body
    # …and `filedAt` must still mean what its name says.
    filed_at = _strip_ts_comments((_WEB_SUMMARY.parent / "dates.ts").read_text())
    assert "app.applied_date ?? app.created_at" in filed_at, (
        "filedAt no longer prefers applied_date, so every caller counting "
        "through it silently went back to the insert time"
    )
    # The specific reversion this guards: re-deriving the window from
    # `created_at`, which is what it did before #509.
    assert not re.search(r"Date\.parse\(\s*app\.created_at\s*\)", body), (
        "summarize() is counting this week on created_at again"
    )


def test_neither_side_still_carries_a_private_window() -> None:
    """A shared basis is not a shared WINDOW.

    Both sides read the date the user applied and still disagreed: the backend
    subtracted seven days and compared with `>=` on both ends, which spans
    EIGHT dates, while the web summed the last seven buckets of `dailyCounts`.
    One day of filings wide, visible only when someone applied on the boundary.

    SINCE #519 THE WINDOW IS A CALENDAR WEEK on both sides, and this assertion
    inverted with it — the old version pinned the literals
    ``_THIS_WEEK_DAYS = 7`` and ``counts.slice(-7)``, so it defended the
    trailing window and would have gone red on the repair. That is the defect
    shape this repo keeps meeting, so the replacement is written as a PAIR:
    the calendar-week helper must be present AND the trailing-window shape must
    be gone. Either half alone is a check that cannot fail — "present" passes
    on a file that carries both, and "absent" passes on a file that computes
    nothing at all.

    WHAT THE TWO IMPLEMENTATIONS AGREE ON is not asserted here. Source strings
    cannot show that; ``test_this_week_is_a_calendar_week.py`` and
    ``apps/web/tests/unit/week-boundary.test.mjs`` run the two functions
    against one shared table of days and are where a semantic drift fails.
    This test guards the cheaper reversion: somebody re-inlining a private
    window at a call site and leaving the shared helper unused.
    """

    backend = _strip_py_comments(_BACKEND.read_text())
    assert "def _week_start(" in backend, (
        "the backend no longer names its week boundary, so nothing shared can "
        "be asserted against it"
    )
    assert "_week_start(now.date())" in backend, (
        "the summary endpoint stopped going through _week_start"
    )
    assert "_THIS_WEEK_DAYS" not in backend, (
        "the trailing seven-day window is back on the backend"
    )

    web = _strip_ts_comments((_WEB_SUMMARY.parent / "age.ts").read_text())
    assert "weekStartOf" in web and "daysElapsedThisWeek" in web, (
        "the web no longer names its week boundary"
    )
    assert "counts.slice(-7)" not in web, (
        "the web's week is a trailing seven buckets again"
    )
    assert "counts.slice(-14, -7)" not in web, (
        "the web's baseline is a trailing fourteen-to-seven window again"
    )


def test_undated_rows_are_excluded_rather_than_coalesced() -> None:
    """A row we cannot date is not evidence about any particular week.

    ``COALESCE(applied_date, created_at)`` looks like a kindness and is the
    original bug, reinstated for exactly the rows nobody can check by eye.
    """

    block = _this_week_block(_BACKEND.read_text())
    assert "coalesce" not in block.lower(), (
        "undated rows are falling back to their insert time"
    )
