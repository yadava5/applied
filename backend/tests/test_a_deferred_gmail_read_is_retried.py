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
from jobtracker.cloud.gmail_client import _collect_page, is_retryable_gmail_error

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


# `rateLimitExceeded` is Gmail saying "later". `authError` is a 403 too — the
# grant is insufficient and no amount of waiting fixes it. Same status, same
# exception class; only the reason separates them, which is the whole point.
_DEFER = _refusal(403, "rateLimitExceeded")
_REFUSE = _refusal(403, "authError")
_GONE = _refusal(404, "notFound")


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
def _instant(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real sleeping. The DELAY is asserted separately, on the pure function.

    Patching the clock rather than the delay function would leave every test
    here waiting out a real backoff; patching `_retry_delay` to 0 keeps the
    retry LOGIC under test while the backoff SHAPE is pinned separately by
    `test_the_first_retry_never_lands_inside_a_second`, which calls
    `_REAL_RETRY_DELAY` — the reference captured at import, above, precisely
    because this fixture is autouse and would otherwise reach it too.
    """

    monkeypatch.setattr(gc, "_retry_delay", lambda attempt: 0.0)
    monkeypatch.setattr(gc.settings, "gmail_batch_pause_seconds", 0.0)
    monkeypatch.setattr(gc.settings, "gmail_batch_size", 25)


# --- the discriminator ------------------------------------------------------


def test_a_deferred_read_and_a_refused_one_are_told_apart() -> None:
    """Both are 403 ``HttpError``. Only the reason separates them.

    MUST RED ON: `is_retryable_gmail_error` keying on `_error_status` alone,
    or on `403 in _RETRYABLE_STATUSES`.
    """

    assert is_retryable_gmail_error(_DEFER) is True
    assert is_retryable_gmail_error(_REFUSE) is False

    # And the status-only cases still work, so the reason check did not
    # replace the status check.
    assert is_retryable_gmail_error(_refusal(429, "unknownToUs")) is True
    assert is_retryable_gmail_error(_refusal(503, "unknownToUs")) is True
    assert is_retryable_gmail_error(_GONE) is False


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


def test_a_deferred_list_call_is_retried_and_the_page_arrives_whole() -> None:
    """MUST RED ON: reverting `_collect_page`'s list call to a bare `.execute()`."""

    service = FakeService(["a", "b", "c"], list_errors=[_DEFER])

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.list_calls == 2, "the refusal should have been retried once"
    assert [m.message_id for m in page.messages] == ["a", "b", "c"]
    assert page.unreadable == 0


def test_a_refused_list_call_is_not_retried() -> None:
    """The directional half: proves the retry DISCRIMINATES.

    Without this, a retry-everything implementation passes the test above and
    quietly burns three extra calls of a dead grant's quota on every request.

    MUST RED ON: `_execute_with_retry` retrying without consulting
    `is_retryable_gmail_error`.
    """

    service = FakeService(["a"], list_errors=[_REFUSE, _REFUSE, _REFUSE, _REFUSE])

    with pytest.raises(HttpError):
        _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.list_calls == 1, "a permanent refusal must cost exactly one call"


def test_retries_are_bounded_and_the_refusal_still_surfaces() -> None:
    """Exhausted retries must RAISE, so the router can answer 429 rather than
    inventing an empty page that reads as "your mailbox is empty".

    MUST RED ON: `while True` with no attempt ceiling; or swallowing the final
    error and returning an empty `MessagePage`.
    """

    service = FakeService(["a"], list_errors=[_DEFER] * 20)

    with pytest.raises(HttpError):
        _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.list_calls == gc._RETRY_ATTEMPTS + 1


# --- the batch path: the 146 silently-dropped messages ----------------------


def test_a_deferred_sub_request_is_retried_and_the_message_is_not_lost() -> None:
    """The quiet exit. This is the 146-of-200 case, in miniature.

    MUST RED ON: `_send` reduced to a single `batch.execute()` with no re-send
    (i.e. the code as it stood on 2026-09-04).
    """

    service = FakeService(["a", "b", "c"], sub_errors={"b": [_DEFER]})

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert [m.message_id for m in page.messages] == ["a", "b", "c"]
    assert page.unreadable == 0, "a deferred message must not be counted as lost"
    assert len(service.batch_rounds) == 2


def test_only_the_deferred_ids_are_resent() -> None:
    """The re-send is per SUB-REQUEST, not per batch.

    This is load-bearing for the thing that caused the bug: re-sending a whole
    25-id window to recover one deferred message costs 500 quota units to
    rescue 20, against the very bucket that just refused.

    MUST RED ON: `pending = window` (re-send everything) instead of
    `pending = deferred`.
    """

    service = FakeService(["a", "b", "c", "d"], sub_errors={"c": [_DEFER]})

    _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert service.batch_rounds == [["a", "b", "c", "d"], ["c"]]


def test_a_permanently_refused_sub_request_is_dropped_not_retried() -> None:
    """One bad message must not sink the page, and must not be retried either.

    MUST RED ON: retrying every failed sub-request regardless of reason.
    """

    service = FakeService(["a", "b", "c"], sub_errors={"b": [_GONE] * 20})

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert [m.message_id for m in page.messages] == ["a", "c"]
    assert page.unreadable == 1, "the loss must still be counted and reported"
    assert service.batch_rounds == [["a", "b", "c"]], "no re-send for a dead id"


def test_sub_request_retries_are_bounded_and_the_loss_is_reported() -> None:
    """A sub-request Gmail keeps deferring is eventually counted as lost.

    The count is what the UI needs to stop reporting a shrunken scan as a
    whole one, so it must survive the retry path rather than being reset by it.

    MUST RED ON: an unbounded `while pending:`; or `unreadable` computed before
    the re-sends rather than after.
    """

    service = FakeService(["a", "b"], sub_errors={"b": [_DEFER] * 20})

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    assert [m.message_id for m in page.messages] == ["a"]
    assert page.unreadable == 1
    assert len(service.batch_rounds) == gc._RETRY_ATTEMPTS + 1
    # Every round after the first carries only the deferred id.
    assert service.batch_rounds[1:] == [["b"]] * gc._RETRY_ATTEMPTS
