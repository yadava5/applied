""""This week" is a REAL CALENDAR WEEK, and both sides agree which one (#519).

THE REPORT. "the week counter should be actual real life week data, but real
calendar!" — the number was a TRAILING SEVEN DAYS on both the backend summary
tile and the momentum caption. A rolling window answers "how many in any seven
days", which is not a question anybody plans by, and it never starts over: on a
Monday morning it still carries the previous Thursday's filings.

MONDAY, read off the product rather than chosen. ``PulseDetail.tsx`` already
draws a gap before every Monday bar, so the strip the caption sits under
visibly breaks the week there; a Sunday-start count would have contradicted the
picture beside it. ``date.weekday()`` and the frontend's ``weekdayOf`` are both
0 on a Monday, so the two languages share the convention instead of each
picking one.

WHY THE TABLE IS A FILE. The boundary is derived twice — :func:`_week_start`
here and ``weekStartOf`` in ``apps/web/lib/dashboard/age.ts`` — and the two
cannot share code across Python and TypeScript. They CAN be made to fail
together: ``apps/web/tests/fixtures/week-boundary.json`` holds the only copy of
the answers, this file asserts them, and
``apps/web/tests/unit/week-boundary.test.mjs`` asserts the same rows. There is
one answer to edit, so "fix one side and both suites stay green" — the exact
way the twin drifted from the board before, recorded in
``test_this_week_basis.py`` — is no longer available.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from jobtracker.cloud.applications import _week_start

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TABLE = _REPO_ROOT / "apps" / "web" / "tests" / "fixtures" / "week-boundary.json"


def _rows() -> list[dict[str, object]]:
    table = json.loads(_TABLE.read_text())
    assert table["weekStartsOn"] == "monday", (
        "the shared table changed which day starts the week; both "
        "implementations have to move with it"
    )
    return list(table["days"])


def _day(value: str) -> date:
    return date(*(int(part) for part in value.split("-")))


@pytest.mark.parametrize("row", _rows(), ids=lambda r: str(r["day"]))
def test_the_week_starts_on_the_monday_the_shared_table_names(row) -> None:
    assert _week_start(_day(str(row["day"]))) == _day(str(row["weekStart"]))


@pytest.mark.parametrize("row", _rows(), ids=lambda r: str(r["day"]))
def test_the_elapsed_days_match_the_shared_table(row) -> None:
    """The count the caption's like-for-like baseline is measured in.

    Asserted here as well as in the web suite because it is the SAME quantity:
    the backend's window is ``[week_start, today]`` inclusive, whose width is
    exactly ``daysElapsed``. If the two ever disagree, the header counts a
    different number of days from the bars beside it.
    """

    day = _day(str(row["day"]))
    span = (day - _week_start(day)).days + 1
    assert span == row["daysElapsed"]


def test_the_table_covers_every_weekday() -> None:
    """A boundary test that never lands on a Monday proves nothing.

    Monday is the whole difficulty: it is the day the calendar week is one day
    wide and the trailing window was seven, so it is the day the two readings
    differ most and the day a partial-week comparison misreports. A table that
    happened to skip it would pass on the bug.
    """

    weekdays = {str(row["weekday"]) for row in _rows()}
    assert weekdays == {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }


def test_a_monday_starts_over_rather_than_carrying_the_weekend() -> None:
    """The behaviour the report actually asked for, stated as behaviour.

    Sunday and the Monday after it are one day apart and in DIFFERENT weeks.
    Under the trailing window they shared six of their seven days, which is why
    the number never reset. This is the assertion that goes red if anyone
    reinstates a rolling window, whatever they call the constant.
    """

    monday = date(2026, 8, 31)
    sunday = monday - timedelta(days=1)

    assert _week_start(sunday) != _week_start(monday)
    assert _week_start(monday) == monday, "a Monday's week begins on that Monday"
    assert (monday - _week_start(monday)).days + 1 == 1, (
        "a Monday counts one day, not seven — this is the reset the owner asked for"
    )
