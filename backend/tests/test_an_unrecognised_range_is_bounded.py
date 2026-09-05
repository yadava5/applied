"""An unrecognised ``range`` must bound the read, not unbound it (#755).

``_parse_range_months`` used to answer ``None`` -- all-time -- for every value
it did not understand, and ``build_gmail_query`` emits no age term for ``None``.
So ``?range=24``, ``?range=13`` and ``?range=xyz`` each read the whole mailbox.

Failing open is a sound instinct when the failure mode is an error page. Here it
did not degrade to LESS, it degraded to MORE, on ``gmail.readonly`` -- a Google
restricted scope. A typo in a bookmark was an unbounded read of a person's mail,
and the response said nothing about it.

WHY THIS FILE ASSERTS THE EMITTED QUERY AND NOT JUST THE PARSE

A test that only checked "no exception" passes with the bug fully reinstated,
and so does one that checks the parse returns *something*. The thing that
reaches Google is the query string, so that is what is asserted: the presence of
``newer_than:12m`` is the difference between a bounded read and an unbounded
one, and it is the only assertion here that a reinstated fallback cannot satisfy.

THE ARM THAT KEEPS THIS HONEST

``all`` and an absent parameter must STAY unbounded. Without those cases a
"fix" that simply bounded everything would pass, and it would silently truncate
the UI's own All-time option -- ``apps/web/lib/gmail/types.ts`` documents
omitting the parameter as how the client spells that request.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud.gmail_oauth import (
    _ALLOWED_RANGE_MONTHS,
    _SYNC_DEFAULT_RANGE_MONTHS,
    _parse_range_months,
)
from jobtracker.cloud.gmail_client import build_gmail_query

BOUND = f"newer_than:{_SYNC_DEFAULT_RANGE_MONTHS}m"


@pytest.mark.parametrize("value", ["24", "13", "xyz", "-5", "999", "24m", "m", "twelve"])
def test_an_unrecognised_range_emits_the_bounded_default(value: str) -> None:
    """The defect, in the place it is observable: the query sent to Google."""

    months = _parse_range_months(value)
    assert months == _SYNC_DEFAULT_RANGE_MONTHS, value

    query = build_gmail_query(range_months=months, scope="inbox")
    assert BOUND in query, (value, query)


@pytest.mark.parametrize("value", ["all", "any", "0", "", "   ", "ALL", "All"])
def test_all_time_asked_for_by_name_is_still_unbounded(value: str) -> None:
    """A user who says "all" gets all. The point is that a TYPO must not."""

    assert _parse_range_months(value) is None, value
    assert "newer_than" not in build_gmail_query(range_months=None, scope="inbox")


def test_an_absent_range_is_still_unbounded_and_that_is_the_client_contract() -> None:
    """`apps/web/lib/gmail/types.ts` omits the parameter to mean All time.

    Bounding this case would truncate the UI's own all-time option for any
    client already loaded in a browser. It is a deliberate boundary of this fix,
    not a gap -- and if that contract is ever revised so the client says
    ``range=all`` outright, this test is the one that should change with it.
    """

    assert _parse_range_months(None) is None


@pytest.mark.parametrize("months", sorted(_ALLOWED_RANGE_MONTHS))
def test_every_offered_filter_survives(months: int) -> None:
    """The boundary case the issue asks for: 12 is allowed AND is the default.

    Worth its own arm because ``range=12`` returning 12 proves nothing on its
    own -- it is the value a broken parse would also produce. The 3/6/9 arms are
    what show the allowed set is still being consulted rather than bypassed.
    """

    assert _parse_range_months(str(months)) == months
    assert _parse_range_months(f"{months}m") == months
    assert f"newer_than:{months}m" in build_gmail_query(range_months=months, scope="inbox")


def test_the_bound_is_not_read_from_the_thing_it_bounds() -> None:
    """The default must be a real month count inside the offered set.

    Sourcing the assertion from the constant alone would compare the config to
    itself and pass for any value, including 0 -- which is the unbounded case
    wearing a number.
    """

    assert _SYNC_DEFAULT_RANGE_MONTHS > 0
    assert _SYNC_DEFAULT_RANGE_MONTHS in _ALLOWED_RANGE_MONTHS
