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


def _quota_envelope(
    *, error_info: bool, status: bool = True, shadow: bool = False, legacy: bool = False
) -> HttpError:
    """One google.rpc quota refusal, with the OPTIONAL parts switched on or off.

    Built from a single dict so the arms below differ in exactly the field
    named and in nothing else. A pair that also differed in ``status``, in the
    HTTP code or in the message would grade nothing — both arms would be read
    as quota for reasons unrelated to what is under test.

    ``shadow`` adds ``error.detail`` (singular). That is not decoration:
    ``HttpError._get_reason`` takes the FIRST of ``detail``/``details``/
    ``errors``/``message`` that is present, so ``detail`` makes
    ``error_details`` the message STRING and the ``ErrorInfo`` becomes
    readable only from the raw body. Verified against the installed
    googleapiclient rather than inferred.
    """

    error: dict[str, object] = {
        # 403, matching the response status above rather than the 429 that
        # `google.rpc.Code.RESOURCE_EXHAUSTED` maps to. Gmail answers a
        # per-user rate limit with 403, and 403 is the only door actually
        # under test: a 429 would be caught by `is_rate_limited_gmail_error`'s
        # status fallback whatever the reasons said, so a fixture built on it
        # could not fail.
        "code": 403,
        "message": (
            "Quota exceeded for quota metric 'Total Query Cost' and limit "
            "'Units per minute per user' of service 'gmail.googleapis.com'."
        ),
    }
    if status:
        error["status"] = "RESOURCE_EXHAUSTED"
    if error_info:
        error["details"] = [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "RATE_LIMIT_EXCEEDED",
                "domain": "googleapis.com",
                "metadata": {"service": "gmail.googleapis.com"},
            }
        ]
    if shadow:
        error["detail"] = "Quota exceeded."
    if legacy:
        error["errors"] = [{"domain": "usageLimits", "reason": "rateLimitExceeded"}]
    return HttpError(_Resp(403), json.dumps({"error": error}).encode())


def test_an_error_info_beside_the_status_does_not_hide_it() -> None:
    """The same envelope twice, differing ONLY in ``error.details[]`` (#863).

    ``_error_reasons`` used to read ``error_details`` and return the moment it
    yielded anything, so the raw-body parse — the only code that harvests
    ``error.status`` — ran only for envelopes carrying no details at all. The
    existing envelope test uses exactly that shape, which is why it passed
    while adding an AIP-193 ``ErrorInfo`` beside the same ``RESOURCE_EXHAUSTED``
    flipped `rate_limited` to False: the page was not aborted, the router did
    not answer 429, and every remaining sub-request in the window was dropped.

    MUST RED ON: removing BOTH halves of the fix — the union in
    `_error_reasons` AND `RATE_LIMIT_EXCEEDED` — which is the state `main`
    shipped in. Either half alone keeps this green, and that is not a
    weakness to hide: this is the OUTCOME assertion, and the outcome is
    protected twice over. The per-half mutation ledger lives on the three
    tests below, which each name a single line.

    An earlier version of this docstring claimed the early return alone reds
    it. That was measured before the constant was added and was false by the
    time it shipped — the same "a number from an earlier script" shape this
    repository keeps finding, in the ledger that exists to catch it.
    """

    without = _quota_envelope(error_info=False)
    with_ = _quota_envelope(error_info=True)

    # The arms have to be genuinely different inputs, or this grades nothing:
    # `details` is what makes `error_details` a list, and a list is the only
    # thing the early return could ever have fired on.
    assert not isinstance(without.error_details, list)
    assert isinstance(with_.error_details, list)

    assert is_rate_limited_gmail_error(without) is True
    assert is_rate_limited_gmail_error(with_) is True, (
        "an ErrorInfo beside the status must not hide the status; the page "
        "has to abort as quota, not be dropped as unreadable"
    )
    assert is_unrecognised_gmail_refusal(with_) is False


def test_the_reason_harvest_is_a_union_of_all_three_sources() -> None:
    """Equality, not membership: a widened set would pass a `>=` assertion.

    Three places can carry a reason — ``error_details``, the legacy
    ``error.errors[]``, and google.rpc's ``error.details[]``/``error.status``
    — and reading one is reading part of an envelope. Pinned with `==` so
    neither dropping a source nor inventing one goes unnoticed.

    MUST RED ON: restoring the `if reasons: return` early return — the FIRST
    arm only, whose harvest collapses to the single `error_details` reason;
    and deleting the raw-body `error.details[]` loop — the SECOND arm only,
    because arm one reaches the same reason through `error_details`, which IS
    the details list when nothing shadows it. Verified per arm rather than
    asserted for both: the earlier version of this line said "both arms" for
    the second mutation and was wrong.
    """

    every_source = _quota_envelope(error_info=True, legacy=True)
    assert isinstance(every_source.error_details, list), (
        "if this is not a list the early return could not have fired and the "
        "first arm stops grading the mutation it names"
    )
    assert gc._error_reasons(every_source) == frozenset(
        {"RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED", "rateLimitExceeded"}
    )

    # `detail` (singular) sorts before `details` in googleapiclient's own
    # lookup, so `error_details` is the message string and the ErrorInfo is
    # reachable ONLY from the raw body. This arm is the one that grades the
    # body-side `details[]` parse.
    shadowed = _quota_envelope(error_info=True, shadow=True)
    assert not isinstance(shadowed.error_details, list)
    assert gc._error_reasons(shadowed) == frozenset(
        {"RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED"}
    )


def test_an_error_info_alone_is_read_as_quota() -> None:
    """`RATE_LIMIT_EXCEEDED` earns its place only on the envelope WITHOUT a status.

    The union fix alone repairs the AIP-193 shape, because `RESOURCE_EXHAUSTED`
    rides in `error.status` beside the `ErrorInfo`. So the new constant has to
    be graded on the one input where the status is absent — otherwise it is a
    string added to a set that no test can distinguish from not adding it.

    IT IS NOT A GUESS AT A NAME. `RATE_LIMIT_EXCEEDED = 5` is
    `google/api/error_reason.proto`'s value for "not enough rate quota for the
    consumer", and the enum's 48 values do NOT include `RESOURCE_EXHAUSTED` —
    that is a `google.rpc.Code`, which can only arrive in `error.status`. The
    two are one condition in two fields, not two spellings of one field.

    MUST RED ON: removing `RATE_LIMIT_EXCEEDED` from `_RATE_LIMIT_REASONS`.
    """

    only_error_info = _quota_envelope(error_info=True, status=False)

    # The arm has to actually lack the status, or `RESOURCE_EXHAUSTED` answers
    # for it and this grades the union fix a second time instead.
    assert "RESOURCE_EXHAUSTED" not in gc._error_reasons(only_error_info)
    assert gc._error_reasons(only_error_info) == frozenset({"RATE_LIMIT_EXCEEDED"})

    assert is_rate_limited_gmail_error(only_error_info) is True
    assert is_retryable_gmail_error(only_error_info) is False
    assert is_unrecognised_gmail_refusal(only_error_info) is False


def test_a_daily_limit_is_left_unclassified_on_purpose() -> None:
    """`dailyLimitExceeded` belongs to neither set, and that is the decision.

    It is a real Gmail reason (403, `domain: usageLimits`, quoted in Gmail's
    own error guide) and it was nearly filed under `_RATE_LIMIT_REASONS` on
    the strength of its name. The primary sources do not support that: it is
    PROJECT-scoped, its documented remedy is "raise the quota in the Google
    Cloud project", and no Google page ties it to a day-length window or a
    reset time. Answering 429 + Retry-After would send the browser back in a
    minute for something a minute does not fix; calling it permanent would
    silence it.

    So it stays unrecognised, which is the loud answer, and this test is what
    stops it being quietly filed under either set later.

    MUST RED ON: adding `dailyLimitExceeded` to `_RATE_LIMIT_REASONS`, to
    `_RETRYABLE_REASONS`, or to `_PERMANENT_REASONS`.
    """

    daily = _refusal(403, "dailyLimitExceeded")

    assert is_rate_limited_gmail_error(daily) is False
    assert is_retryable_gmail_error(daily) is False
    assert is_unrecognised_gmail_refusal(daily) is True, (
        "a refusal whose meaning we cannot cite must be counted, not guessed at"
    )


def test_an_unfamiliar_error_info_beside_a_quota_status_still_aborts() -> None:
    """The input where the UNION half alone decides a verdict — #863's class.

    Every other case here is known-beside-known, where the constant and the
    union each answer, or known-alone, where only the constant does. This is
    the one that isolates the union: a reason string we have never classified,
    riding beside a status we have. On the early-return code the harvest is
    that unknown string alone, nothing matches, and the refusal is dropped as
    unreadable; on the union it reads the status too and the page aborts.

    That is not a contrived shape. It is exactly what the NEXT envelope change
    looks like — `RESOURCE_EXHAUSTED` is in the rate-limit set because the
    field moved once already, and a new `ErrorInfo.reason` is the cheapest way
    for Google to extend an error it already emits.

    MUST RED ON: restoring `if reasons: return frozenset(reasons)`.
    """

    body = json.dumps(
        {
            "error": {
                "code": 403,
                "message": "Quota exceeded.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "A_REASON_THIS_CODE_HAS_NEVER_SEEN",
                        "domain": "googleapis.com",
                    }
                ],
            }
        }
    ).encode()
    unfamiliar = HttpError(_Resp(403), body)

    # The premise: the details reason really is unclassified, so the verdict
    # below cannot be coming from it. Without this the test would still pass
    # if someone added the string to a set, and it would then be grading the
    # opposite of what it claims.
    assert not (
        frozenset({"A_REASON_THIS_CODE_HAS_NEVER_SEEN"})
        & (gc._RATE_LIMIT_REASONS | gc._RETRYABLE_REASONS | gc._PERMANENT_REASONS)
    )
    assert isinstance(unfamiliar.error_details, list), (
        "the early return fires only on a list; if this is not one the "
        "mutation this test names cannot reach it"
    )

    assert gc._error_reasons(unfamiliar) == frozenset(
        {"A_REASON_THIS_CODE_HAS_NEVER_SEEN", "RESOURCE_EXHAUSTED"}
    )
    assert is_rate_limited_gmail_error(unfamiliar) is True
    assert is_unrecognised_gmail_refusal(unfamiliar) is False


def test_a_permanent_refusal_stays_permanent_when_more_reasons_are_read() -> None:
    """Reading MORE reasons must not PROMOTE a refusal we already understood.

    The union's stated invariant is one-directional — it can move a refusal up
    the priority chain, never down — and the risk it carries is the promotion,
    not a narrowing. A revoked grant answering 403 `authError` with a
    google.rpc `PERMISSION_DENIED` beside it must still be permanent: promote
    it and the router answers 429, the browser waits a minute, and re-probes a
    grant that will never widen, forever.

    This replaces a test that asserted the same idea and could not fail: every
    fixture it ran carried exactly one reason, so a consumer keyed on
    `len(reasons) == 1` — the thing its own docstring named — passed it, and it
    was green byte-for-byte on the unfixed code.

    MUST RED ON: adding `PERMISSION_DENIED` to `_RATE_LIMIT_REASONS`, which is
    what "add the google.rpc spelling too" looks like when applied to the
    wrong row; and restoring the early return, which collapses the harvest to
    `{authError}` and takes the two-reason premise with it. Both measured.
    """

    body = json.dumps(
        {
            "error": {
                "code": 403,
                "message": "Request had insufficient authentication scopes.",
                "status": "PERMISSION_DENIED",
                "errors": [{"domain": "global", "reason": "authError"}],
            }
        }
    ).encode()
    revoked = HttpError(_Resp(403), body)

    # TWO reasons, which is the condition the old test never met.
    assert gc._error_reasons(revoked) == frozenset({"authError", "PERMISSION_DENIED"})

    assert is_rate_limited_gmail_error(revoked) is False, (
        "a permanent refusal promoted to quota makes the browser retry a "
        "revoked grant every minute"
    )
    assert is_retryable_gmail_error(revoked) is False
    assert is_unrecognised_gmail_refusal(revoked) is False


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


@pytest.mark.parametrize(
    "refusal",
    [_QUOTA, _quota_envelope(error_info=True)],
    ids=["legacy-usageLimits", "google-rpc-ErrorInfo"],
)
def test_a_rate_limited_sub_request_abandons_the_page(
    slept: list[float], refusal: HttpError
) -> None:
    """The quiet exit, closed. This is the 146-of-200 case.

    A rate-limited sub-request means the bucket is dry, so the remaining
    windows of this page would be refused too. Grinding through them spends
    more of a budget Gmail has just said is gone; raising lets the router
    answer 429 and the client refetch this page from the cursor it still holds.
    Nothing is lost — the page is refetched, not skipped.

    BOTH ENVELOPES, because the predicate and the loop are two boundaries and
    a green predicate proves nothing about the loop that consults it (#863).
    The google.rpc arm reds on the shipped state of `main` — the early return
    plus the missing constant — which is the whole point of running it here
    rather than only against the predicate.

    MUST RED ON: removing the `is_rate_limited_gmail_error` raise from `_send`
    (measured: both arms red — the ids are then silently dropped and the page
    returns 200 with a shrunken, unexplained count, exactly the production
    behaviour).
    """

    service = FakeService(["a", "b", "c"], sub_errors={"b": [refusal]})

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

    # A NAME WE HAVE NEVER CLASSIFIED IS NOT KNOWLEDGE, and this is the half a
    # first draft of the predicate got wrong. It treated "it named a reason" as
    # "we recognise it", which waves through exactly the change this exists to
    # catch: the envelope moved the quota signal once already (that is why
    # RESOURCE_EXHAUSTED is in _RATE_LIMIT_REASONS), and a RENAMED quota reason
    # would arrive unfamiliar rather than absent.
    assert is_unrecognised_gmail_refusal(_refusal(403, "quotaExceededNew")) is True
    assert is_unrecognised_gmail_refusal(_refusal(403, "someFutureReason")) is True
    # A status that does not explain itself, with nothing said, likewise.
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


def test_unrecognised_is_always_a_subset_of_the_loss() -> None:
    """A subset that can exceed its superset is a wiring mistake, not a count.

    ``unrecognised`` is documented as a share OF ``unreadable``. Nothing in the
    types enforces that: the two are accumulated in different places --
    ``unreadable`` from ``len(ids) - len(out)`` at the page, ``unrecognised``
    from a set of ids inside the batch -- so a mistake in either would show up
    here and nowhere else. Driven across the four shapes that reach the page
    differently rather than on one fixture, since a single case cannot tell a
    real subset from an accident.

    MUST RED ON: `unrecognised` sourced from the raw refusal count rather than
    from ids that produced nothing; the page taking it from a different batch
    than the one it counted `unreadable` from.
    """

    for name, errors in [
        ("clean", {}),
        ("one gone", {"b": [_GONE] * 20}),
        ("one unreadable envelope", {"b": [_ROGUE] * 20}),
        ("two, mixed causes", {"b": [_GONE] * 20, "c": [_ROGUE] * 20}),
    ]:
        page = _collect_page(
            FakeService(["a", "b", "c", "d"], sub_errors=errors),
            query="in:inbox",
            page_size=50,
            page_token=None,
        )
        assert page.unrecognised <= page.unreadable, (
            f"{name}: unrecognised={page.unrecognised} exceeds "
            f"unreadable={page.unreadable}, so it is not a share of it"
        )
        assert page.unrecognised >= 0

    # And the mixed case specifically: two losses, exactly one of them silent.
    mixed = _collect_page(
        FakeService(["a", "b", "c", "d"], sub_errors={"b": [_GONE] * 20, "c": [_ROGUE] * 20}),
        query="in:inbox",
        page_size=50,
        page_token=None,
    )
    assert mixed.unreadable == 2
    assert mixed.unrecognised == 1, "the deleted message was counted as an envelope change"
    assert [m.message_id for m in mixed.messages] == ["a", "d"]


def test_the_three_reason_sets_do_not_overlap() -> None:
    """A reason in two sets makes the predicate's ORDER load-bearing by accident.

    is_unrecognised_gmail_refusal asks rate-limit, then retryable, then
    permanent. If a string appeared in two of those, the answer would depend on
    which check ran first rather than on what the string means, and the next
    person to reorder the guards for readability would change behaviour without
    touching a rule.

    MUST RED ON: adding a reason to _PERMANENT_REASONS that is already a rate
    limit or a flake.
    """

    from jobtracker.cloud.gmail_client import (
        _PERMANENT_REASONS,
        _RATE_LIMIT_REASONS,
        _RETRYABLE_REASONS,
    )

    pairs = [
        ("rate-limit", _RATE_LIMIT_REASONS, "retryable", _RETRYABLE_REASONS),
        ("rate-limit", _RATE_LIMIT_REASONS, "permanent", _PERMANENT_REASONS),
        ("retryable", _RETRYABLE_REASONS, "permanent", _PERMANENT_REASONS),
    ]
    for a_name, a, b_name, b in pairs:
        assert not (a & b), f"{a_name} and {b_name} both claim {sorted(a & b)}"

    # And each is non-empty, so the disjointness above is not vacuous.
    for name, s in [
        ("rate-limit", _RATE_LIMIT_REASONS),
        ("retryable", _RETRYABLE_REASONS),
        ("permanent", _PERMANENT_REASONS),
    ]:
        assert s, f"{name} is empty; the disjointness assertions grade nothing"


def test_an_unrecognised_refusal_survives_a_retry_round_beside_it() -> None:
    """The counter's own target scenario, and it is the COMMON presentation.

    An envelope change fails many sub-requests in the same window. If any one
    of them is an ordinary 5xx flake, the round retries -- and `failures` is
    cleared at the top of every round. A recorder that only runs at the
    terminal exit therefore sees an empty dict for the unrecognised id, which
    was never re-sent because it was never deferred.

    So the defect the counter exists to make loud goes quiet again, precisely
    when it matters most. Every other test in this file uses a single failing
    id and cannot see it.

    MUST RED ON: calling `_record_unrecognised` only at `_send`'s exits rather
    than once per round.
    """

    service = FakeService(
        ["a", "b", "c"], sub_errors={"b": [_ROGUE] * 20, "c": [_FLAKE]}
    )

    page = _collect_page(service, query="in:inbox", page_size=50, page_token=None)

    # `c` flaked once and then answered; `b` is the permanent silent refusal.
    assert [m.message_id for m in page.messages] == ["a", "c"]
    assert page.unreadable == 1
    assert page.unrecognised == 1, (
        "the unrecognised refusal was cleared by the retry round beside it"
    )
    assert service.batch_rounds == [["a", "b", "c"], ["c"]], (
        "the flake must be the only id re-sent"
    )
