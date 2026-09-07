"""Every rate-limited answer said 60 seconds whatever Gmail said (#869).

``GmailRateLimited``'s only raise site constructed it with no argument, so the
``Retry-After`` this app emits was a constant. That inference is a good one for
the case it was written for -- Gmail's units-per-minute-per-user bucket refills
on a minute boundary, so a shorter wait spends a request to be refused again --
and it is wrong for the other family the same predicate covers.

``is_rate_limited_gmail_error`` also returns True on a bare **429**, and Gmail's
own guide puts daily per-user, bandwidth and concurrency limits there:

    A 429 "Too many requests" error can occur due to daily per-user limits
    ... **with a time to retry**. Daily limits being exceeded might result in
    these errors for multiple hours before the request is accepted.

So on that path the app was discarding a retry time the server supplied and
substituting a minute for something that can last hours. The client then
re-requests from its cursor, is refused, and loops -- the app's own doing.

THE CONSUMER ALREADY EXISTED, which is why this is a passthrough and not new
machinery. ``apps/web/lib/gmail/transport.ts:159`` reads ``Retry-After`` off the
429 and falls back to 60 itself; ``lib/gmail/server.ts`` carries it as
``retryAfterSeconds`` on ``{kind: "rate_limited"}``; and ``sync-plan.ts:341``
keeps its copy deliberately number-free with the comment *"would rot the day the
backend tunes Retry-After"*. Only the backend half was missing.

WHAT THIS FILE DOES NOT PROVE, said plainly. Nothing here observes a live Gmail
429, and the issue is explicit that it is unmeasured whether Gmail's 429s on the
*read* paths this app uses carry ``Retry-After`` at all -- the quoted sentence
sits in a section that also covers sending. If they never carry it, every test
below still passes and the fallback still answers 60, which is the pre-existing
behaviour. So this change cannot make the 429 path worse, and its upside is
conditional on a header nobody has yet seen in production.
"""
from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httplib2
import pytest
from googleapiclient.errors import HttpError

from jobtracker.cloud.gmail_client import _RETRY_AFTER_MAX_SECONDS, retry_after_seconds
from jobtracker.cloud.gmail_oauth import GmailRateLimited

#: What the app answers when the server named no wait. Unchanged by #869.
FALLBACK = 60


def refusal(**headers: str) -> HttpError:
    """A 429 carrying exactly the headers named, and nothing else.

    ``httplib2.Response`` is a dict subclass that lower-cases every key it is
    constructed with, which is why the reader can ask for ``retry-after`` and
    still see a ``Retry-After`` the server sent. That is the library's
    behaviour rather than an assumption, and
    :func:`test_the_header_is_found_whatever_case_the_server_used` pins it.
    """
    raw = {"status": 429}
    raw.update(headers)
    return HttpError(httplib2.Response(raw), b'{"error":{"code":429}}')


# ===========================================================================
# 1. Reading the header.
# ===========================================================================


def test_a_supplied_wait_is_read_off_the_refusal() -> None:
    assert retry_after_seconds(refusal(**{"Retry-After": "180"})) == 180


def test_the_header_is_found_whatever_case_the_server_used() -> None:
    """The two spellings a server may send, both landing on one value."""
    upper = retry_after_seconds(refusal(**{"Retry-After": "90"}))
    lower = retry_after_seconds(refusal(**{"retry-after": "90"}))
    assert upper == lower == 90


def test_an_http_date_is_read_as_well_as_delta_seconds() -> None:
    """RFC 7231 allows both spellings, and a reader that knows only the
    integer discards the other silently -- which is indistinguishable from
    "the server said nothing" and is the bug this file exists for."""
    when = datetime.now(UTC) + timedelta(minutes=10)
    seconds = retry_after_seconds(refusal(**{"Retry-After": format_datetime(when)}))
    assert seconds is not None
    # A date is converted against the clock, so pin the band rather than a value.
    assert 570 <= seconds <= 600, seconds


def test_a_date_that_has_already_passed_is_not_a_wait_of_zero() -> None:
    """``None`` means "fall back", and 0 would mean "ask again immediately"
    -- straight back into the bucket that just refused."""
    when = datetime.now(UTC) - timedelta(minutes=10)
    assert retry_after_seconds(refusal(**{"Retry-After": format_datetime(when)})) is None


@pytest.mark.parametrize(
    "value", ["0", "-30", "", "   ", "soon", "12.5", "1,800", "\x00"]
)
def test_a_wait_that_is_not_a_positive_time_falls_back(value: str) -> None:
    assert retry_after_seconds(refusal(**{"Retry-After": value})) is None


def test_a_refusal_with_no_header_falls_back() -> None:
    assert retry_after_seconds(refusal()) is None


def test_an_exception_that_is_not_an_http_error_falls_back() -> None:
    """This runs on the failure path. An exception raised while inspecting an
    exception turns a recoverable deferral into a crash."""
    assert retry_after_seconds(ValueError("not an HttpError")) is None
    assert retry_after_seconds(RuntimeError()) is None


def test_a_wait_longer_than_the_ceiling_is_clamped_down() -> None:
    """Clamping DOWN is the safe direction: understating costs one more
    refusal, overstating strands a scan Gmail would have served."""
    assert retry_after_seconds(refusal(**{"Retry-After": "99999"})) == _RETRY_AFTER_MAX_SECONDS
    assert _RETRY_AFTER_MAX_SECONDS == 3600


# ===========================================================================
# 2. What the client is actually told. The control the issue asks for.
# ===========================================================================


def test_two_refusals_differing_only_in_the_header_answer_differently() -> None:
    """THE CONTROL, and the reason the file is not just the parser tests above.

    Same status, same body, same everything -- one header apart. A suite that
    only drove the absent case would grade the fallback and nothing else, and
    would stay green against the exact bug this fixes.
    """
    supplied = GmailRateLimited(retry_after_seconds(refusal(**{"Retry-After": "900"})))
    silent = GmailRateLimited(retry_after_seconds(refusal()))

    assert supplied.headers["Retry-After"] == "900"
    assert silent.headers["Retry-After"] == str(FALLBACK)
    assert supplied.headers["Retry-After"] != silent.headers["Retry-After"]


def test_the_status_and_the_message_do_not_move_with_the_wait() -> None:
    """Only the wait is new. 429 is load-bearing -- ``lib/gmail/server.ts``
    maps 503 onto "Gmail is not configured on this deployment" and 409 onto
    "not connected", and both would be a lie here."""
    for exc in (GmailRateLimited(), GmailRateLimited(900)):
        assert exc.status_code == 429
        assert "rate-limiting this mailbox" in exc.detail


def test_the_default_is_still_a_minute() -> None:
    """The pre-existing behaviour, kept as the fallback rather than deleted."""
    assert GmailRateLimited().headers["Retry-After"] == str(FALLBACK)


# ===========================================================================
# 3. Placement: the parser is only useful where the exception is raised.
# ===========================================================================


def test_the_raise_site_passes_the_refusal_to_the_parser() -> None:
    """A source-level check, and its limits are worth stating.

    The regressions this catches are precise, and both were found by mutating
    rather than reasoned about:

    * ``raise GmailRateLimited() from exc`` — the shape that was there before,
      which makes every rate-limited answer a constant again.
    * ``retry_after_seconds()`` with no argument — which passed an earlier
      version of this test GREEN and raises ``TypeError: missing 1 required
      positional argument`` **while handling the original exception**, so every
      rate-limited scan becomes a 500. A gate written to guard a line, green
      while the line 500s, is this estate's recurring defect.

    It accepts either spelling — the parser called inline, or bound to a name
    first so the value can be logged — and checks the LINKAGE rather than the
    text, so hoisting the call is a refactor and not a failure. The argument's
    name is deliberately not pinned; renaming ``exc`` is not a defect.

    It is source-level because ``gmail_inbox`` is a FastAPI endpoint behind
    ``current_user``, a credentials lookup and a database session, and no
    harness in this suite drives it — ``GmailRateLimited`` is referenced by no
    other test file at all, so the 429 path has never been exercised at the
    endpoint. That debt predates this change. It is also cheaper to retire than
    it looks: ``fetch_message_page`` is imported lazily inside ``gmail_inbox``,
    so monkeypatching it to raise a header-carrying ``HttpError`` plus one
    dependency override would drive the real ``except`` branch and demote this
    test to belt-and-braces. Filed as follow-up rather than done here.

    So: this asserts the call shape and cannot prove the branch executes. What
    it proves is that nobody quietly severed the wiring.
    """
    from jobtracker.cloud import gmail_oauth

    tree = ast.parse(inspect.getsource(gmail_oauth.gmail_inbox))

    parser_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "retry_after_seconds"
    ]
    assert parser_calls, "gmail_inbox never calls retry_after_seconds"
    for call in parser_calls:
        assert len(call.args) == 1 and not call.keywords, (
            "retry_after_seconds is called with the wrong number of arguments. "
            "This raises inside an except block, turning a recoverable deferral "
            f"into a 500: {ast.dump(call)}"
        )
        assert isinstance(call.args[0], ast.Name), ast.dump(call)

    # Names bound to the parser's result, so the hoisted spelling is accepted.
    bound = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "retry_after_seconds"
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    raises = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "GmailRateLimited"
    ]
    assert raises, "gmail_inbox no longer raises GmailRateLimited at all"
    for call in raises:
        assert call.args, (
            "GmailRateLimited() is constructed with no argument again, so every "
            "rate-limited answer is a constant whatever Gmail said (#869)"
        )
        arg = call.args[0]
        inline = (
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Name)
            and arg.func.id == "retry_after_seconds"
        )
        hoisted = isinstance(arg, ast.Name) and arg.id in bound
        assert inline or hoisted, (
            "GmailRateLimited is constructed with something that did not come "
            f"from retry_after_seconds: {ast.dump(arg)}"
        )
