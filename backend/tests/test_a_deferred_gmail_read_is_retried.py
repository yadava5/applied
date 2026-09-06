"""Gmail's "later" must not be recorded as "never".

The defect these guard, in full, from production on 2026-09-04.

`GET /gmail/inbox` answered **500** four times in six minutes with
``HttpError 403 ... "Quota exceeded for quota metric 'Total Query Cost' and
limit 'Units per minute per user'" ... reason: 'rateLimitExceeded'``, raised
from the ``messages.list`` call in :func:`_collect_page`. The function ran for
234 ms of a 60 s budget, so this was never a timeout — Gmail refused, and the
refusal reached the user as "We couldn't finish reading your mail."

In the same minute a request that returned **200 OK** logged ``Gmail metadata
fetch lost 146 of 200 message(s)``. That is the SAME refusal taking a quieter
exit: the batch callback recorded only ``type(exception).__name__``, and
``"HttpError"`` is what a permanent 404 is called too, so a rate limit was
indistinguishable from a deleted message and 146 messages were dropped while
the scan reported success.

Why it started: nothing in this repository changed. On 2026-05-01 Google cut
the per-user ceiling from 15,000 to 6,000 units/minute and raised
``messages.get`` from 5 units to 20. Per-user throughput fell from 3,000
messages a minute to 300. A 200-message page costs ``20*200 + 5 = 4,005``
units — two thirds of a minute's budget in one invocation.

**A rate limit cannot be summoned on demand and quota recovers by itself, so
"the scan worked afterwards" would prove nothing.** :func:`_collect_page` is
documented as pure with respect to Gmail transport precisely so a fake service
can be injected; every test here drives one that refuses on cue.

Each test below names the mutation it must red on. A retry test that has never
been seen to fail is not a test.
"""

from __future__ import annotations

import json

import pytest
from googleapiclient.errors import HttpError

import jobtracker.cloud.gmail_client as gc

# HARD-CODED, AND THAT IS THE WHOLE POINT OF THESE TWO LINES.
#
# The budget assertions below used to read `gc._PAGE_RETRY_BUDGET_SECONDS` —
# the constant under test — so they compared a value against itself and passed
# for ANY value. A review raised it to 200.0 and the suite stayed green while a
# real-sized page slept **33 seconds inside a 60 s function**, which is exactly
# the FUNCTION_INVOCATION_TIMEOUT this module exists to prevent. The sibling
# file `test_the_page_size_fits_gmails_minute.py` hard-codes its constants and
# says why; the discipline had been applied to the page size and not here, to
# the more load-bearing of the two.
#
# Both numbers come from outside the module: 6 s is what a page may spend
# sleeping, and 10 s is `cron.py`'s `_CRON_PER_USER_TIMEOUT_SECONDS`, which is
# WHY the page budget must be smaller — a page that outsleeps the cron slot
# gets that user's scheduled sync cancelled.
MAX_PAGE_SLEEP_SECONDS = 6.0
CRON_PER_USER_SLOT_SECONDS = 10.0
from jobtracker.cloud.gmail_client import (
    _collect_page,
    is_rate_limited_gmail_error,
    is_retryable_gmail_error,
    is_unrecognised_gmail_refusal,
)

# Bound at import, BEFORE the autouse fixture below replaces the module
# attribute with a zero-delay stub. Without this the backoff test reads the
# stub and asserts `0.0 >= 1.0` against a function that is not the one
# shipping — the fixture would have silently disarmed the only test of the
# backoff SHAPE. It failed loudly the first time it ran, which is the only
# reason this comment exists rather than a green test measuring nothing.
_REAL_RETRY_DELAY = gc._retry_delay


# --- building a refusal that looks exactly like Gmail's ---------------------


class _Resp:
    """The slice of an httplib2 response ``HttpError`` reads."""

    def __init__(self, status: int, reason: str = "Forbidden") -> None:
        self.status = status
        self.reason = reason


def _refusal(status: int, reason: str) -> HttpError:
    """An ``HttpError`` carrying Gmail's real error envelope.

    The body shape is copied from the production trace rather than invented:
    ``error.errors[]`` with ``domain``/``reason``, which is what
    ``HttpError.__init__`` folds into ``error_details`` (it takes the first of
    ``detail``/``details``/``errors``/``message`` that is present). A fixture
    that used a different envelope would exercise our fallback parser and
    never the path production actually takes.
    """

    body = json.dumps(
        {
            "error": {
                "code": status,
                "message": (
                    "Quota exceeded for quota metric 'Total Query Cost' and "
                    "limit 'Units per minute per user' of service "
                    "'gmail.googleapis.com'."
                ),
                "errors": [{"domain": "usageLimits", "reason": reason}],
            }
        }
    ).encode()
    return HttpError(_Resp(status), body)


# THREE KINDS, and the design turns on telling them apart.
#
# `_QUOTA` — Gmail's bucket is dry. Transient, but on a MINUTE's scale, so it
#   is never retried in place; it aborts the page and becomes a 429.
# `_FLAKE` — Gmail itself wobbled. Curable by seconds of backoff, so it IS
#   retried in place, under the page's sleep budget.
# `_REFUSE` — a 403 as well, but the grant is insufficient and no amount of
#   waiting fixes it. Same status and same exception class as `_QUOTA`; only
#   the reason separates them.
# `_GONE` — the message is not there. Dropped, counted, never retried.
_QUOTA = _refusal(403, "rateLimitExceeded")
_FLAKE = _refusal(503, "backendError")
_REFUSE = _refusal(403, "authError")
_GONE = _refusal(404, "notFound")

# A REAL google.rpc envelope: status 403, no `error.errors[].reason`, no
# `error.status`, and the detail items carry no top-level reason either. This
# is the shape `_error_reasons` returns EMPTY for, and 403 is the only door
# actually open — a 429 would be caught by `is_rate_limited_gmail_error`'s
# status fallback. Verified unrecognised rather than assumed: see
# `test_the_predicate_fires_on_silence_not_on_unfamiliarity` below.
_ROGUE = HttpError(
    _Resp(403),
    json.dumps(
        {
            "error": {
                "code": 403,
                "message": "Quota exceeded.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"subject": "user", "description": "units per minute"}],
                    }
                ],
            }
        }
    ).encode(),
)

# The same silence with no JSON at all: an HTML error page from something in
# front of Gmail. Also unrecognised, and correctly so.
_OPAQUE = HttpError(_Resp(403), b"<html>upstream said no</html>")


# --- a fake Gmail service that refuses on cue -------------------------------


def _raw(mid: str) -> dict:
    return {
        "id": mid,
        "threadId": f"t-{mid}",
        "snippet": f"snippet {mid}",
        "payload": {
            "headers": [
                {"name": "Subject", "value": f"Subject {mid}"},
                {"name": "From", "value": f"{mid} <{mid}@corp.example>"},
                {"name": "Date", "value": "Mon, 01 Jul 2026 12:00:00 +0000"},
            ]
        },
    }


class _Exec:
    def __init__(self, service: FakeService) -> None:
        self._s = service

    def execute(self) -> dict:
        self._s.list_calls += 1
        if self._s.list_errors:
            raise self._s.list_errors.pop(0)
        return {"messages": [{"id": i} for i in self._s.ids], "nextPageToken": None}


class _GetRequest:
    def __init__(self, message_id: str) -> None:
        self.message_id = message_id


class _Messages:
    def __init__(self, service: FakeService) -> None:
        self._s = service

    def list(self, **kwargs: object) -> _Exec:
        return _Exec(self._s)

    def get(self, *, userId: str, id: str, format: str) -> _GetRequest:  # noqa: A002,N803
        return _GetRequest(id)


class _Users:
    def __init__(self, service: FakeService) -> None:
        self._s = service

    def messages(self) -> _Messages:
        return _Messages(self._s)


class _Batch:
    def __init__(self, service: FakeService, callback) -> None:
        self._s = service
        self._cb = callback
        self._items: list[str] = []

    def add(self, request: _GetRequest, request_id: str) -> None:
        self._items.append(request_id)

    def execute(self) -> None:
        # Recorded as a list of lists so a test can assert not just how many
        # rounds happened but WHICH ids each round carried — that is what
        # separates "re-sent the deferred one" from "re-sent the whole window".
        self._s.batch_rounds.append(list(self._items))
        for message_id in self._items:
            queued = self._s.sub_errors.get(message_id)
            if queued:
                self._cb(message_id, None, queued.pop(0))
                continue
            self._cb(message_id, self._s.metadata.get(message_id), None)


class FakeService:
    """Drives ``_collect_page`` with scripted refusals.

    ``list_errors`` and ``sub_errors`` are QUEUES that are consumed: an entry
    raises once and the next attempt gets whatever is behind it. That is what
    makes "deferred then succeeded" expressible, which a static set of failing
    ids cannot express.
    """

    def __init__(
        self,
        ids: list[str],
        *,
        list_errors: list[Exception] | None = None,
        sub_errors: dict[str, list[Exception]] | None = None,
    ) -> None:
        self.ids = ids
        self.metadata = {i: _raw(i) for i in ids}
        self.list_errors = list(list_errors or [])
        self.sub_errors = {k: list(v) for k, v in (sub_errors or {}).items()}
        self.list_calls = 0
        self.batch_rounds: list[list[str]] = []

    def users(self) -> _Users:
        return _Users(self)

    def new_batch_http_request(self, callback) -> _Batch:
        return _Batch(self, callback)


@pytest.fixture(autouse=True)
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every sleep instead of taking it, and hand back the ledger.

    `_retry_delay` is deliberately NOT stubbed. The page budget is a bound on
    total sleep, so a test of that bound has to see the real delays — stubbing
    them to zero makes any budget look sufficient, which is the shape of a
    check that cannot fail. Recording `time.sleep` keeps the suite instant
    while leaving the arithmetic real.
    """

    ledger: list[float] = []
    monkeypatch.setattr(gc.time, "sleep", lambda d: ledger.append(d))
    monkeypatch.setattr(gc.settings, "gmail_batch_pause_seconds", 0.0)
    monkeypatch.setattr(gc.settings, "gmail_batch_size", 25)
    return ledger


# --- the discriminator ------------------------------------------------------


def test_quota_flake_and_refusal_are_three_different_answers() -> None:
    """The truth table the whole design rests on.

    A rate limit is transient but NOT retryable-in-place; a flake is both; a
    bad grant is neither. Collapsing the first two — which is what a single
    `is_retryable` predicate does — is what puts minutes of sleeping inside a
    60 s function.

    MUST RED ON: `is_retryable_gmail_error` dropping its
    `is_rate_limited_gmail_error` early return; either predicate keying on
    status alone; adding 403 to `_RETRYABLE_STATUSES`.
    """

    # quota: defer to the client, never retry here
    assert is_rate_limited_gmail_error(_QUOTA) is True
    assert is_retryable_gmail_error(_QUOTA) is False

    # flake: retry here
    assert is_rate_limited_gmail_error(_FLAKE) is False
    assert is_retryable_gmail_error(_FLAKE) is True

    # a 403 we cannot wait out
    assert is_rate_limited_gmail_error(_REFUSE) is False
    assert is_retryable_gmail_error(_REFUSE) is False

    # a message that is simply gone
    assert is_rate_limited_gmail_error(_GONE) is False
    assert is_retryable_gmail_error(_GONE) is False

    # 429 is a rate limit by status alone, whatever reason rides with it.
    assert is_rate_limited_gmail_error(_refusal(429, "unknownToUs")) is True
    # and a bare 503 is still a flake, so the reason check did not replace the
    # status check.
    assert is_retryable_gmail_error(_refusal(503, "unknownToUs")) is True


def test_a_quota_reason_beats_a_retryable_status() -> None:
    """The one input where the rate-limit short-circuit actually decides.

    WRITTEN BECAUSE A MUTATION FAILED TO RED. Deleting the
    `is_rate_limited_gmail_error` early return from `is_retryable_gmail_error`
    changed nothing in any other test, and the reason is that the two sets do
    not currently overlap: no rate-limit reason is in `_RETRYABLE_REASONS`, and
    429 is not in `_RETRYABLE_STATUSES`. So the guard was real intent with no
    input to prove it — a line that could be deleted for free.

    A 503 carrying `rateLimitExceeded` is that input, and it is not contrived:
    the status says "server wobbled, retry in seconds" and the reason says
    "quota, wait a minute", and the reason is the one that is true. Without the
    short-circuit, the status wins and the request is retried in place — the
    exact behaviour that put minutes of sleeping inside a 60 s function.
    """

    both = _refusal(503, "rateLimitExceeded")

    assert is_rate_limited_gmail_error(both) is True
    assert is_retryable_gmail_error(both) is False, (
        "a quota reason must outrank a retryable status, or a rate limit gets "
        "retried in place through the 5xx door"
    )


def test_the_newer_error_envelope_is_still_read_as_quota() -> None:
    """Gmail's google.rpc-shaped errors say `RESOURCE_EXHAUSTED`, not a reason.

    `HttpError` folds `error.errors[]` into `error_details` when it is present;
    when it is not, only `error.status` carries the meaning. Without
    `RESOURCE_EXHAUSTED` in `_RATE_LIMIT_REASONS` that envelope classifies as
    permanent and a quota refusal becomes a 500 again — the original defect,
    reintroduced by an envelope change nobody here controls.

    MUST RED ON: dropping `RESOURCE_EXHAUSTED`; dropping the `error.status`
    harvest in `_error_reasons`.
    """

    body = json.dumps(
        {"error": {"code": 429, "message": "Quota exceeded.", "status": "RESOURCE_EXHAUSTED"}}
    ).encode()
    modern = HttpError(_Resp(403, "Forbidden"), body)

    assert is_rate_limited_gmail_error(modern) is True
    assert is_retryable_gmail_error(modern) is False


def test_an_unreadable_403_is_treated_as_permanent() -> None:
    """A 403 whose reason we cannot parse must NOT be retried.

    Conservative on purpose: an unreadable 403 is far more likely to be a
    revoked grant than a rate limit, and retrying it spends the very budget a
    real rate limit needs.

    MUST RED ON: a fallback that returns True when no reason is found.
    """

    opaque = HttpError(_Resp(403), b"<html>upstream said no</html>")
    assert is_retryable_gmail_error(opaque) is False


def test_the_first_retry_never_lands_inside_a_second() -> None:
    """Google: "start retry periods at least one second after the error".

    This is the exact flaw in ``googleapiclient``'s own built-in retry
    (``sleep_time = rand() * 2**retry_num``), which has no floor and routinely
    produces a millisecond-scale first retry. Against a per-MINUTE bucket that
    is not a retry, it is a second miss.

    MUST RED ON: `_retry_delay` returning `random.uniform(0, 2**attempt)`.
    """

    delays = [_REAL_RETRY_DELAY(0) for _ in range(200)]
    assert min(delays) >= 1.0, "a sub-second first retry cannot clear a bucket"
    assert max(delays) <= 2.0

    # Still jittered, or every refused caller retries on the same instant and
    # rebuilds the burst that caused the refusal.
    assert len(set(delays)) > 1

    # And bounded, because the whole request lives in a 60 s function budget.
    assert _REAL_RETRY_DELAY(99) <= gc._RETRY_MAX_SECONDS


# --- the list call: the one that raised in production -----------------------


def test_a_rate_limited_list_call_raises_at_once_without_sleeping(
    slept: list[float],
) -> None:
    """Quota is never waited out inside the request. This is the core rule.

    A per-minute bucket does not refill in the seconds a bounded backoff
    affords, so retrying here spends the function's budget to arrive at the
    same refusal — and on a paged read the sleeps compound past the 60 s
    ceiling and time the whole thing out. The refusal must surface at once so
    the router can answer 429 and the CLIENT can wait.

    MUST RED ON: `is_retryable_gmail_error` losing its rate-limit early return
    (the error then retries and `slept` fills).
    """

    service = FakeService(["a"], list_errors=[_QUOTA] * 20)

    with pytest.raises(HttpError):
        _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.list_calls == 1, "quota must cost exactly one call"
    assert slept == [], "quota must never be slept on inside the request"


def test_a_flaky_list_call_is_retried_and_the_page_arrives_whole(
    slept: list[float],
) -> None:
    """A 5xx IS worth a short wait — that half of Google's guidance stands.

    MUST RED ON: reverting `_collect_page`'s list call to a bare `.execute()`.
    """

    service = FakeService(["a", "b", "c"], list_errors=[_FLAKE])

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.list_calls == 2
    assert [m.message_id for m in page.messages] == ["a", "b", "c"]
    assert page.unreadable == 0
    assert len(slept) == 1 and 1.0 <= slept[0] <= 2.0


def test_a_refused_list_call_is_not_retried(slept: list[float]) -> None:
    """The directional control: proves the retry DISCRIMINATES.

    Without it, a retry-everything implementation passes the flake test above
    and quietly burns three extra calls of a dead grant's quota per request.

    MUST RED ON: `_execute_with_retry` retrying without consulting
    `is_retryable_gmail_error`.
    """

    service = FakeService(["a"], list_errors=[_REFUSE] * 4)

    with pytest.raises(HttpError):
        _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.list_calls == 1
    assert slept == []


def test_flake_retries_are_bounded_and_the_error_still_surfaces() -> None:
    """Exhausted retries must RAISE, not invent an empty page.

    An empty `MessagePage` would read to the user as "your mailbox is empty",
    which is a worse lie than an error.

    MUST RED ON: `while True` with no attempt ceiling; swallowing the final
    error and returning an empty page.
    """

    service = FakeService(["a"], list_errors=[_FLAKE] * 20)

    with pytest.raises(HttpError):
        _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.list_calls == gc._RETRY_ATTEMPTS + 1


# --- the batch path: the 146 silently-dropped messages ----------------------


def test_a_rate_limited_sub_request_abandons_the_page(slept: list[float]) -> None:
    """The quiet exit, closed. This is the 146-of-200 case.

    A rate-limited sub-request means the bucket is dry, so the remaining
    windows of this page would be refused too. Grinding through them spends
    more of a budget Gmail has just said is gone; raising lets the router
    answer 429 and the client refetch this page from the cursor it still holds.
    Nothing is lost — the page is refetched, not skipped.

    MUST RED ON: removing the `is_rate_limited_gmail_error` raise from `_send`
    (the ids are then silently dropped and the page returns 200 with a
    shrunken, unexplained count — exactly the production behaviour).
    """

    service = FakeService(["a", "b", "c"], sub_errors={"b": [_QUOTA]})

    with pytest.raises(HttpError):
        _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert len(service.batch_rounds) == 1, "no grinding on through the page"
    assert slept == []


def test_a_flaky_sub_request_is_retried_and_the_message_is_not_lost() -> None:
    """MUST RED ON: `_send` reduced to a single `batch.execute()`."""

    service = FakeService(["a", "b", "c"], sub_errors={"b": [_FLAKE]})

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert [m.message_id for m in page.messages] == ["a", "b", "c"]
    assert page.unreadable == 0
    assert len(service.batch_rounds) == 2


def test_only_the_flaky_ids_are_resent() -> None:
    """The re-send is per SUB-REQUEST, not per batch.

    Load-bearing for the thing that caused the bug: re-sending a whole 25-id
    window to recover one message costs 500 quota units to rescue 20, against
    the very bucket under pressure.

    MUST RED ON: `pending = pending` (re-send everything) instead of
    `pending = deferred`.
    """

    service = FakeService(["a", "b", "c", "d"], sub_errors={"c": [_FLAKE]})

    _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.batch_rounds == [["a", "b", "c", "d"], ["c"]]


def test_a_permanently_refused_sub_request_is_dropped_not_retried() -> None:
    """One dead message must not sink the page, and must not be retried either.

    MUST RED ON: retrying every failed sub-request regardless of reason.
    """

    service = FakeService(["a", "b", "c"], sub_errors={"b": [_GONE] * 20})

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert [m.message_id for m in page.messages] == ["a", "c"]
    assert page.unreadable == 1, "the loss must still be counted and reported"
    assert service.batch_rounds == [["a", "b", "c"]]


def test_sub_request_retries_are_bounded_and_the_loss_is_reported() -> None:
    """An id that keeps flaking is eventually counted as lost.

    The count is what stops the UI reporting a shrunken scan as a whole one, so
    it must survive the retry path rather than be reset by it.

    MUST RED ON: an unbounded `while pending:`; `unreadable` computed before
    the re-sends rather than after.
    """

    service = FakeService(["a", "b"], sub_errors={"b": [_FLAKE] * 20})

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert [m.message_id for m in page.messages] == ["a"]
    assert page.unreadable == 1
    assert len(service.batch_rounds) == gc._RETRY_ATTEMPTS + 1
    assert service.batch_rounds[1:] == [["b"]] * gc._RETRY_ATTEMPTS


# --- the bound that keeps a page inside its function ------------------------


def test_the_page_budget_stays_under_the_cron_slot() -> None:
    """The constant itself, checked against the thing that constrains it.

    `cron.py` gives each user 10 s. A page whose sleeps can reach past that
    turns one transient Gmail flake into a cancelled scheduled sync, a held
    cursor, and the same outcome on the next tick.

    MUST RED ON: `_PAGE_RETRY_BUDGET_SECONDS = 12`, its value until a review
    measured 33 s of sleeping in a 60 s function against a green suite.
    """

    assert gc._PAGE_RETRY_BUDGET_SECONDS <= MAX_PAGE_SLEEP_SECONDS
    assert gc._PAGE_RETRY_BUDGET_SECONDS < CRON_PER_USER_SLOT_SECONDS


def test_the_attempt_count_fits_the_budget_that_bounds_it() -> None:
    """Two bounds that disagree are not a bound — the smaller wins in silence.

    Google's backoff is `2^n + jitter` with jitter under a second, so N retries
    cost at most `sum(2^i + 1 for i in range(N))`. If that exceeds the page
    budget, the attempt count is a number the runtime overrules and the reader
    believes.

    MUST RED ON: `_RETRY_ATTEMPTS = 3` against a 6 s budget (7-10 s of backoff).
    """

    worst_case = sum(2**i + 1.0 for i in range(gc._RETRY_ATTEMPTS))

    assert worst_case <= MAX_PAGE_SLEEP_SECONDS, (
        f"{gc._RETRY_ATTEMPTS} retries need up to {worst_case:.0f}s of backoff "
        f"against a {MAX_PAGE_SLEEP_SECONDS}s page budget, so the attempt "
        f"count is not what actually bounds the retries"
    )


def test_one_page_cannot_sleep_past_its_budget(
    slept: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PER-CALL retry count does not bound a PAGE. This is that bound.

    Twelve ids at a batch size of three is four windows. Each holds an id that
    flakes forever, so each window would retry `_RETRY_ATTEMPTS` times and
    sleep the full `1+2+4`-ish ramp — roughly 7 to 10 s per window, 28 to 40 s
    across the page, inside a **60 s** function that also has to classify
    everything it fetched. A 500-id page is twenty windows and lands near
    200 s. That is how a fix for a fast failure becomes a timeout.

    MUST RED ON: deleting the `budget.spend` guard from `_send`, which makes
    total sleep run to several times the ceiling. Raising
    `_PAGE_RETRY_BUDGET_SECONDS` is caught by
    `test_the_page_budget_stays_under_the_cron_slot`, NOT here — this
    assertion's bound is a literal precisely so that raising the constant
    cannot move it.
    """

    monkeypatch.setattr(gc.settings, "gmail_batch_size", 3)
    ids = [f"m{i}" for i in range(12)]
    flaky = {mid: [_FLAKE] * 50 for mid in ("m0", "m3", "m6", "m9")}
    service = FakeService(ids, sub_errors=flaky)

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    total = sum(slept)
    assert total <= MAX_PAGE_SLEEP_SECONDS, (
        f"one page slept {total:.1f}s against a {MAX_PAGE_SLEEP_SECONDS}s "
        f"ceiling; a page that can outsleep the cron's "
        f"{CRON_PER_USER_SLOT_SECONDS}s per-user slot gets that user's "
        f"scheduled sync cancelled"
    )
    # And the page still came back with everything that WAS readable, rather
    # than failing outright because some ids never answered.
    assert [m.message_id for m in page.messages] == [i for i in ids if i not in flaky]
    assert page.unreadable == 4


def test_the_budget_is_shared_by_the_list_call_and_the_batches(
    slept: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One page, one allowance — not one allowance per call site.

    A budget created per call would let the list call spend its own ramp and
    then every window spend a fresh one, which is the per-call bound this test
    exists to distinguish from a page bound.

    MUST RED ON: `_execute_with_retry` or `_batch_fetch_metadata` constructing
    its own `_RetryBudget()` instead of receiving `_collect_page`'s.
    """

    monkeypatch.setattr(gc.settings, "gmail_batch_size", 3)
    ids = [f"m{i}" for i in range(12)]
    # Exactly `_RETRY_ATTEMPTS` list flakes, so the list call spends its whole
    # allowance and then SUCCEEDS. One more would raise before a single batch
    # ran, and the test would prove nothing about sharing — it would only prove
    # the list call is bounded, which the test above already does.
    service = FakeService(
        ids,
        list_errors=[_FLAKE] * gc._RETRY_ATTEMPTS,
        sub_errors={mid: [_FLAKE] * 50 for mid in ("m0", "m3", "m6", "m9")},
    )

    _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    # The list call alone spends roughly 1-2 s + 2-3 s. If each batch window
    # then got a FRESH budget, four windows would add four more ramps and the
    # total would run past this bound several times over.
    assert sum(slept) <= MAX_PAGE_SLEEP_SECONDS


# --- an envelope we cannot read must be loud, not one more unit of loss ------


def test_the_predicate_fires_on_silence_not_on_unfamiliarity() -> None:
    """#744, and the negatives are the load-bearing half.

    The obvious spelling — "matched neither reason set" — is WRONG, and wrong
    in the direction that makes the counter useless. Measured, it is true for
    three of these five, and only `_ROGUE` is the condition worth surfacing:

        403 authError  -> a revoked grant. Recognised, understood, permanent.
        404 notFound   -> the ordinary case. Every deleted message.
        403 google.rpc -> no readable reason at all. The open door.

    A count that increments on every deleted message is non-zero on
    essentially every real page, so an envelope change would arrive as one
    more unit in a number already large. That is the opposite of loud.

    MUST RED ON: defining the predicate as `not (_error_reasons(exc) & known)`;
    dropping the `_SELF_EXPLANATORY_STATUSES` check; letting a rate limit or a
    flake through.
    """

    # The one it exists for, and the same silence wearing no JSON at all.
    assert is_unrecognised_gmail_refusal(_ROGUE) is True
    assert is_unrecognised_gmail_refusal(_OPAQUE) is True

    # NEGATIVES. Each of these would be swept in by the naive predicate.
    assert is_unrecognised_gmail_refusal(_GONE) is False, (
        "a deleted message is the ordinary case; counting it drowns the signal"
    )
    assert is_unrecognised_gmail_refusal(_REFUSE) is False, (
        "authError is recognised and permanent — the invariant at "
        "gmail_client.py's permanent-403 note exists to protect it"
    )
    assert is_unrecognised_gmail_refusal(_QUOTA) is False, "a rate limit aborts the page"
    assert is_unrecognised_gmail_refusal(_FLAKE) is False, "a flake is retried"

    # And the reason it is not just "status == 403": a 403 that NAMES something
    # is not silent, even when the name means nothing to us.
    assert is_unrecognised_gmail_refusal(_refusal(403, "somethingNewFromGoogle")) is False
    # while a status that does not explain itself, with nothing said, is.
    assert is_unrecognised_gmail_refusal(HttpError(_Resp(451), b"")) is True

    # THE CASE `_SELF_EXPLANATORY_STATUSES` EXISTS FOR, and without it this
    # assertion is the only thing standing between the constant and a mutation
    # that deletes it. A 404 carrying no parseable body at all is still a
    # message that is gone — the STATUS is the reason — so it must not read as
    # an envelope change. Found by mutation: `return True` in place of the
    # status check left all other tests green.
    assert is_unrecognised_gmail_refusal(HttpError(_Resp(404), b"")) is False
    assert is_unrecognised_gmail_refusal(HttpError(_Resp(400), b"<html>bad</html>")) is False


def test_a_page_counts_an_unrecognised_refusal_apart_from_a_missing_message() -> None:
    """The two losses are the same size and must not read the same.

    Both pages lose exactly one message and report `unreadable == 1`. The whole
    point of #744 is that one of them is a message that is gone and the other
    is Gmail refusing in a dialect this client does not speak — and the second
    is the one that means a scan may be silently shrinking.

    MUST RED ON: `unrecognised` computed as `dropped`; the count taken before
    the retry loop settles; `_GONE` counted as unrecognised (which is what
    makes this a control rather than a pair of assertions).
    """

    gone = _collect_page(
        FakeService(["a", "b", "c"], sub_errors={"b": [_GONE] * 20}),
        query="in:inbox",
        page_size=50,
        page_token=None,
    )
    rogue = _collect_page(
        FakeService(["a", "b", "c"], sub_errors={"b": [_ROGUE] * 20}),
        query="in:inbox",
        page_size=50,
        page_token=None,
    )

    # Identical where they should be: same messages kept, same loss counted.
    assert [m.message_id for m in gone.messages] == ["a", "c"]
    assert [m.message_id for m in rogue.messages] == ["a", "c"]
    assert gone.unreadable == rogue.unreadable == 1

    # And separated where it matters.
    assert gone.unrecognised == 0, "a deleted message is not an envelope change"
    assert rogue.unrecognised == 1, "an unreadable refusal reached the caller as silence"


def test_an_unrecognised_refusal_is_still_not_retried() -> None:
    """Counting it must not quietly turn it into a retry.

    The issue floats "treat an unrecognised failure as retryable-once", and it
    was rejected: a 403 we cannot read is more likely a revoked grant than a
    rate limit, and retrying burns the budget a real rate limit needs. This
    pins that the new count did not smuggle the rejected option in.

    MUST RED ON: adding the unrecognised set to `deferred`.
    """

    service = FakeService(["a", "b", "c"], sub_errors={"b": [_ROGUE] * 20})

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert page.unrecognised == 1
    assert service.batch_rounds == [["a", "b", "c"]], "the refusal was retried"


def test_a_clean_page_reports_zero_unrecognised() -> None:
    """The floor. A counter that is never zero cannot signal anything."""

    page = _collect_page(
        FakeService(["a", "b", "c"]), query="in:inbox", page_size=50, page_token=None
    )

    assert page.unreadable == 0
    assert page.unrecognised == 0
