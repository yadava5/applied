"""Unit tests for the high-volume cloud Gmail fetch engine (issue C7).

These cover the Gmail *transport* logic without a real token by driving a
fake ``service`` that mimics the slice of the googleapiclient surface the
fetch uses:

- ``build_gmail_query`` — range + scope → Gmail query string.
- ``_collect_page`` — one ``messages.list`` page → batched
  ``messages.get(format=full)`` → ordered, parsed messages + cursor, plus the
  in-flight body text the classifier reads and nothing retains (see
  ``test_body_is_never_persisted.py``). This said ``format=metadata`` until the
  fetch changed.

The batching (≤ ``gmail_batch_size`` per ``new_batch_http_request``), the
newest-first ordering, dropped-sub-request tolerance, and the 500-id list
clamp are all asserted here.
"""

from __future__ import annotations

import pytest

import jobtracker.cloud.gmail_client as gc
from jobtracker.cloud.gmail_client import _collect_page, build_gmail_query

# --- build_gmail_query ------------------------------------------------------


def test_build_query_inbox_with_range() -> None:
    assert build_gmail_query(6, "inbox") == "in:inbox newer_than:6m"


def test_build_query_anywhere_all_time() -> None:
    """`anywhere` carries `-in:sent`, and this expectation changed on purpose.

    `in:anywhere` means anywhere, and Gmail counts the user's own Sent mail as
    anywhere. The first windowed additive scan against a real mailbox put four
    of the owner's own outreach messages into the review queue, scored
    `applied` at 0.9 on text that genuinely reads like an application.

    The age bound still composes on the end, so the ordering is asserted too —
    Gmail's grammar is space-separated AND terms, but a reader diffing query
    logs should see a stable string rather than a set.
    """

    assert build_gmail_query(None, "anywhere") == "in:anywhere -in:sent"
    assert build_gmail_query(0, "anywhere") == "in:anywhere -in:sent"
    assert build_gmail_query(12, "anywhere") == "in:anywhere -in:sent newer_than:12m"


def test_build_query_inbox_all_time_is_bare_inbox() -> None:
    assert build_gmail_query(None, "inbox") == "in:inbox"


# --- fake Gmail service -----------------------------------------------------


def _raw(mid: str, subject: str, sender: str, date: str) -> dict:
    return {
        "id": mid,
        "threadId": f"t-{mid}",
        "snippet": f"snippet for {mid}",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": date},
            ]
        },
    }


class _Exec:
    def __init__(self, result: dict) -> None:
        self._result = result

    def execute(self) -> dict:
        return self._result


class _GetRequest:
    def __init__(self, message_id: str) -> None:
        self.message_id = message_id


class _Messages:
    def __init__(self, service: FakeService) -> None:
        self._s = service

    def list(self, *, userId: str, q: str, maxResults: int, pageToken=None) -> _Exec:  # noqa: N803
        self._s.list_calls.append(
            {"q": q, "maxResults": maxResults, "pageToken": pageToken}
        )
        idx = 0 if pageToken is None else int(pageToken)
        ids, next_token = self._s.pages[idx]
        listing: dict = {
            "messages": [{"id": i} for i in ids[:maxResults]],
            "nextPageToken": next_token,
        }
        if self._s.result_size_estimate is not None:
            listing["resultSizeEstimate"] = self._s.result_size_estimate
        return _Exec(listing)

    def get(self, *, userId: str, id: str, format: str, metadataHeaders=None):  # noqa: A002,N803
        # The format is RECORDED rather than ignored. It used to be pinned by
        # making ``metadataHeaders`` a required argument, which broke loudly
        # when the client moved to ``format="full"`` — the right instinct, but
        # it could only ever say "not metadata any more", never which format
        # was asked for. ``get_formats`` lets a test assert the actual value,
        # which is what ``test_body_is_never_persisted`` needs: reading bodies
        # is the whole point there, and a silent fallback to metadata would
        # make its absence-assertions pass for the wrong reason.
        self._s.get_formats.append(format)
        return _GetRequest(id)


class _RaisingExec:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def execute(self) -> dict:
        raise self._error


class _History:
    def __init__(self, service: FakeService) -> None:
        self._s = service

    def list(  # noqa: N803 — mirrors the googleapiclient kwarg names
        self,
        *,
        userId: str,
        startHistoryId: str,
        historyTypes: list[str],
        maxResults: int,
        pageToken=None,
    ):
        self._s.history_calls.append(
            {
                "startHistoryId": startHistoryId,
                "historyTypes": historyTypes,
                "maxResults": maxResults,
                "pageToken": pageToken,
            }
        )
        if self._s.history_error is not None:
            return _RaisingExec(self._s.history_error)
        idx = 0 if pageToken is None else int(pageToken)
        records, next_token = self._s.history_pages[idx]
        return _Exec({"history": records, "nextPageToken": next_token})


class _Users:
    def __init__(self, service: FakeService) -> None:
        self._s = service

    def messages(self) -> _Messages:
        return _Messages(self._s)

    def history(self) -> _History:
        return _History(self._s)

    def getProfile(self, *, userId: str) -> _Exec:  # noqa: N802,N803 — Gmail's name
        self._s.profile_calls += 1
        return _Exec(
            {
                "emailAddress": "owner@example.test",
                "historyId": self._s.profile_history_id,
            }
        )


class _Batch:
    def __init__(self, service: FakeService, callback) -> None:
        self._s = service
        self._cb = callback
        self._items: list[tuple[str, _GetRequest]] = []

    def add(self, request: _GetRequest, request_id: str) -> None:
        self._items.append((request_id, request))

    def execute(self) -> None:
        self._s.batch_sizes.append(len(self._items))
        for request_id, _request in self._items:
            if request_id in self._s.batch_errors:
                # Gmail answered this sub-request with an error; the real client
                # hands the callback an exception and no response.
                self._cb(request_id, None, RuntimeError("sub-request failed"))
                continue
            self._cb(request_id, self._s.metadata.get(request_id), None)


class FakeService:
    """Minimal stand-in for a googleapiclient Gmail service."""

    def __init__(
        self,
        pages,
        metadata,
        *,
        history_pages=None,
        history_error: Exception | None = None,
        profile_history_id: str | None = None,
        batch_errors: set | None = None,
        result_size_estimate: object = None,
    ) -> None:
        # pages: list[(ids, next_page_token)]; metadata: {id: raw|None}
        self.pages = pages
        self.metadata = metadata
        self.list_calls: list[dict] = []
        self.batch_sizes: list[int] = []
        # Every ``format`` a messages.get was built with, in order.
        self.get_formats: list[str] = []
        # ids whose metadata sub-request fails outright (vs. answering empty)
        self.batch_errors = batch_errors or set()
        # Gmail's own ``resultSizeEstimate``; ``None`` omits the field entirely.
        self.result_size_estimate = result_size_estimate
        # history_pages: list[(history_records, next_page_token)]
        self.history_pages = history_pages or []
        self.history_error = history_error
        self.history_calls: list[dict] = []
        self.profile_history_id = profile_history_id
        self.profile_calls = 0

    def users(self) -> _Users:
        return _Users(self)

    def new_batch_http_request(self, callback) -> _Batch:
        return _Batch(self, callback)


@pytest.fixture(autouse=True)
def _no_batch_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep tests instant regardless of the configured inter-batch pace.
    monkeypatch.setattr(gc.settings, "gmail_batch_pause_seconds", 0.0)


# --- _collect_page ----------------------------------------------------------


def test_collect_page_batches_and_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc.settings, "gmail_batch_size", 2)
    ids = ["a", "b", "c", "d", "e"]
    metadata = {
        i: _raw(i, f"Subject {i}", f"{i} <{i}@corp.com>", "Mon, 01 Jul 2026 12:00:00 +0000")
        for i in ids
    }
    service = FakeService(pages=[(ids, "NEXT")], metadata=metadata)

    page = _collect_page(service, query="in:inbox", page_size=500, page_token=None)

    # 5 ids at batch size 2 → three batches (2, 2, 1).
    assert service.batch_sizes == [2, 2, 1]
    # Gmail's newest-first list order is preserved through the batch shuffle.
    assert [m.message_id for m in page.messages] == ids
    assert page.messages[0].sender_email == "a@corp.com"
    assert page.next_page_token == "NEXT"


def test_collect_page_drops_failed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc.settings, "gmail_batch_size", 100)
    ids = ["a", "b", "c"]
    metadata = {
        "a": _raw("a", "S", "a@corp.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
        "b": None,  # sub-request failed → dropped, not a hollow row
        "c": _raw("c", "S", "c@corp.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
    }
    service = FakeService(pages=[(ids, None)], metadata=metadata)

    page = _collect_page(service, query="in:inbox", page_size=500, page_token=None)
    assert [m.message_id for m in page.messages] == ["a", "c"]
    assert page.next_page_token is None


def test_collect_page_counts_what_it_could_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shrinking page has to SAY it shrank.

    Dropping failed sub-requests silently means "scanned 2" is reported for a
    page of 3, indistinguishable from a mailbox that only held 2. Both ways a
    message can vanish are counted: a sub-request that errored, and one that
    answered with nothing.
    """

    monkeypatch.setattr(gc.settings, "gmail_batch_size", 100)
    ids = ["a", "b", "c", "d"]
    metadata = {
        "a": _raw("a", "S", "a@corp.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
        "b": None,  # answered with nothing
        "c": _raw("c", "S", "c@corp.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
        "d": _raw("d", "S", "d@corp.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
    }
    service = FakeService(pages=[(ids, None)], metadata=metadata, batch_errors={"d"})

    page = _collect_page(service, query="in:inbox", page_size=500, page_token=None)
    assert [m.message_id for m in page.messages] == ["a", "c"]
    assert page.unreadable == 2
    # The page adds up: what came back plus what was lost is what was listed.
    assert len(page.messages) + page.unreadable == len(ids)


def test_batch_fetch_metadata_reports_its_own_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count is derived from what came back, not from the callback's arg.

    An id answered with an empty body reaches the callback with
    ``exception=None``, so counting exceptions would report zero drops while a
    message genuinely disappeared.
    """

    monkeypatch.setattr(gc.settings, "gmail_batch_size", 100)
    metadata = {
        "a": _raw("a", "S", "a@corp.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
        "b": None,
    }
    service = FakeService(pages=[(["a", "b"], None)], metadata=metadata)

    # `budget` is required, not defaulted: a per-call default would let a new
    # caller silently get its own sleep allowance, which is exactly the
    # per-call bound that does not bound a page.
    fetched = gc._batch_fetch_metadata(
        service, ["a", "b"], batch_size=100, pause_seconds=0.0, budget=gc._RetryBudget()
    )
    assert set(fetched.messages) == {"a"}
    assert fetched.dropped == 1


def test_unparseable_metadata_also_counts_as_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata that arrives but will not parse shrinks the page just the same."""

    monkeypatch.setattr(gc.settings, "gmail_batch_size", 100)
    metadata = {
        "a": _raw("a", "S", "a@corp.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
        "b": {"id": "b", "payload": "not-a-mapping"},  # parse fails → dropped
    }
    service = FakeService(pages=[(["a", "b"], None)], metadata=metadata)

    page = _collect_page(service, query="in:inbox", page_size=500, page_token=None)
    assert [m.message_id for m in page.messages] == ["a"]
    assert page.unreadable == 1


def test_collect_page_carries_gmails_result_size_estimate() -> None:
    """The progress denominator comes through — as an estimate, coerced safely."""

    metadata = {"a": _raw("a", "S", "a@c.com", "Mon, 01 Jul 2026 12:00:00 +0000")}
    service = FakeService(
        pages=[(["a"], "NEXT")], metadata=metadata, result_size_estimate=2000
    )
    page = _collect_page(service, query="in:inbox", page_size=500, page_token=None)
    assert page.result_size_estimate == 2000

    # Absent → None (never a fabricated 0, which would read as "nothing here").
    bare = FakeService(pages=[(["a"], None)], metadata=metadata)
    assert (
        _collect_page(bare, query="in:inbox", page_size=500, page_token=None)
    ).result_size_estimate is None

    # Junk or negative → None / clamped, never handed on as a denominator.
    junk = FakeService(
        pages=[(["a"], None)], metadata=metadata, result_size_estimate="lots"
    )
    assert (
        _collect_page(junk, query="in:inbox", page_size=500, page_token=None)
    ).result_size_estimate is None
    negative = FakeService(
        pages=[(["a"], None)], metadata=metadata, result_size_estimate=-5
    )
    assert (
        _collect_page(negative, query="in:inbox", page_size=500, page_token=None)
    ).result_size_estimate == 0


def test_empty_page_still_carries_the_estimate() -> None:
    """A page with no ids returns early — and must not lose the estimate there."""

    service = FakeService(pages=[([], None)], metadata={}, result_size_estimate=1200)
    page = _collect_page(service, query="in:inbox", page_size=500, page_token=None)
    assert page.messages == []
    assert page.result_size_estimate == 1200
    assert page.unreadable == 0


def test_collect_page_empty_listing_returns_cursor_only() -> None:
    service = FakeService(pages=[([], None)], metadata={})
    page = _collect_page(service, query="in:inbox", page_size=500, page_token=None)
    assert page.messages == []
    assert page.next_page_token is None
    # No ids → no batch was executed.
    assert service.batch_sizes == []


def test_collect_page_clamps_list_to_gmail_ceiling() -> None:
    service = FakeService(pages=[(["a"], None)], metadata={"a": _raw("a", "S", "a@c.com", "")})
    _collect_page(service, query="in:inbox", page_size=9999, page_token=None)
    # messages.list must never be asked for more than Gmail's 500 ceiling.
    assert service.list_calls[0]["maxResults"] == 500


def test_collect_page_forwards_page_token() -> None:
    service = FakeService(
        pages=[(["a"], "T1"), (["b"], None)],
        metadata={"a": _raw("a", "S", "a@c.com", ""), "b": _raw("b", "S", "b@c.com", "")},
    )
    page = _collect_page(service, query="in:inbox", page_size=500, page_token="1")
    assert service.list_calls[0]["pageToken"] == "1"
    assert [m.message_id for m in page.messages] == ["b"]


# --- incremental read: getProfile + users.history.list ----------------------
#
# The transport half of the sync-cursor work. The router-level fallback
# behaviour lives in ``test_gmail_oauth_cloud.py``; what is asserted here is
# that we *detect* Gmail's signals correctly in the first place — above all the
# documented 404 for an aged-out ``startHistoryId``, which must never surface as
# an error.


def _added(mid: str, *, labels: list[str] | None = None) -> dict:
    """One ``messagesAdded`` entry as Gmail shapes it."""

    return {
        "message": {
            "id": mid,
            "threadId": f"t-{mid}",
            "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
        }
    }


def _history_record(record_id: str, added: list[dict]) -> dict:
    return {"id": record_id, "messagesAdded": added}


class _FakeResp:
    """Stand-in for the httplib2 response googleapiclient hands HttpError."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "Not Found" if status == 404 else "Error"


def _http_error(status: int) -> gc.HttpError:
    return gc.HttpError(
        _FakeResp(status),
        b'{"error": {"code": %d, "message": "Requested entity was not found."}}'
        % status,
    )


def test_mailbox_history_id_reads_profile() -> None:
    service = FakeService(pages=[([], None)], metadata={}, profile_history_id=98765)
    # Gmail returns historyId as a number; we normalize to str for storage.
    assert gc._mailbox_history_id(service) == "98765"
    assert service.profile_calls == 1


def test_mailbox_history_id_absent_is_none() -> None:
    service = FakeService(pages=[([], None)], metadata={}, profile_history_id=None)
    assert gc._mailbox_history_id(service) is None


def test_collect_history_returns_added_messages_newest_first() -> None:
    metadata = {
        "h1": _raw("h1", "Applied to Acme", "a@acme.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
        "h2": _raw("h2", "Interview at Acme", "a@acme.com", "Thu, 10 Jul 2026 12:00:00 +0000"),
    }
    service = FakeService(
        pages=[([], None)],
        metadata=metadata,
        # Gmail hands history back oldest-first.
        history_pages=[([_history_record("1", [_added("h1"), _added("h2")])], None)],
    )

    page = gc._collect_history(
        service, start_history_id="900", max_messages=50, scope="inbox"
    )

    assert page.usable
    assert not page.expired and not page.truncated
    # Normalized to the full scan's newest-first contract.
    assert [m.message_id for m in page.messages] == ["h2", "h1"]
    call = service.history_calls[0]
    assert call["startHistoryId"] == "900"
    assert call["historyTypes"] == ["messageAdded"]


def test_collect_history_skips_drafts_sent_and_non_inbox() -> None:
    metadata = {
        i: _raw(i, "S", f"{i}@c.com", "Mon, 01 Jul 2026 12:00:00 +0000")
        for i in ("keep", "draft", "sent", "archived")
    }
    service = FakeService(
        pages=[([], None)],
        metadata=metadata,
        history_pages=[
            (
                [
                    _history_record(
                        "1",
                        [
                            _added("keep"),
                            _added("draft", labels=["DRAFT"]),
                            _added("sent", labels=["SENT"]),
                            _added("archived", labels=["CATEGORY_PERSONAL"]),
                        ],
                    )
                ],
                None,
            )
        ],
    )

    inbox = gc._collect_history(
        service, start_history_id="900", max_messages=50, scope="inbox"
    )
    assert [m.message_id for m in inbox.messages] == ["keep"]

    # ``anywhere`` also takes the archived message, but never drafts/sends.
    service.history_calls.clear()
    anywhere = gc._collect_history(
        service, start_history_id="900", max_messages=50, scope="anywhere"
    )
    assert sorted(m.message_id for m in anywhere.messages) == ["archived", "keep"]


def test_collect_history_404_is_expired_not_an_error() -> None:
    """Gmail's documented aged-out-cursor signal must degrade, not raise.

    History is retained for roughly a week; past that ``startHistoryId`` gets a
    404. The caller re-baselines with a full scan — a user who did not open the
    app for eight days is not an error condition.
    """

    service = FakeService(
        pages=[([], None)], metadata={}, history_error=_http_error(404)
    )

    page = gc._collect_history(
        service, start_history_id="stale", max_messages=50, scope="inbox"
    )

    assert page.expired is True
    assert page.truncated is False
    assert page.messages == []
    assert page.usable is False  # → caller full-scans and re-baselines


def test_collect_history_other_http_error_propagates() -> None:
    """A 500 is a real failure and must NOT be laundered into 'nothing new'."""

    service = FakeService(
        pages=[([], None)], metadata={}, history_error=_http_error(500)
    )
    with pytest.raises(gc.HttpError):
        gc._collect_history(
            service, start_history_id="900", max_messages=50, scope="inbox"
        )


def test_collect_history_truncates_rather_than_skipping() -> None:
    """More new mail than we will walk → full-scan signal, not a partial read.

    Consuming part of the history and then advancing the cursor past the rest is
    exactly how an incremental sync silently loses mail.
    """

    ids = [f"m{i}" for i in range(10)]
    service = FakeService(
        pages=[([], None)],
        metadata={i: _raw(i, "S", f"{i}@c.com", "") for i in ids},
        history_pages=[([_history_record("1", [_added(i) for i in ids])], None)],
    )

    page = gc._collect_history(
        service, start_history_id="900", max_messages=3, scope="inbox"
    )
    assert page.truncated is True
    assert page.expired is False
    assert page.messages == []
    assert page.usable is False


def test_collect_history_dedupes_and_drops_deleted_messages() -> None:
    """A message added twice counts once; one deleted since is simply dropped."""

    service = FakeService(
        pages=[([], None)],
        metadata={
            "dup": _raw("dup", "S", "d@c.com", "Mon, 01 Jul 2026 12:00:00 +0000"),
            "gone": None,  # metadata sub-request failed → deleted since it was added
        },
        history_pages=[
            (
                [
                    _history_record("1", [_added("dup"), _added("gone")]),
                    _history_record("2", [_added("dup")]),
                ],
                None,
            )
        ],
    )

    page = gc._collect_history(
        service, start_history_id="900", max_messages=50, scope="inbox"
    )
    assert [m.message_id for m in page.messages] == ["dup"]


def test_collect_history_walks_pages_until_cursor_exhausted() -> None:
    metadata = {
        i: _raw(i, "S", f"{i}@c.com", "Mon, 01 Jul 2026 12:00:00 +0000")
        for i in ("p1", "p2")
    }
    service = FakeService(
        pages=[([], None)],
        metadata=metadata,
        history_pages=[
            ([_history_record("1", [_added("p1")])], "1"),
            ([_history_record("2", [_added("p2")])], None),
        ],
    )

    page = gc._collect_history(
        service, start_history_id="900", max_messages=50, scope="inbox"
    )
    assert sorted(m.message_id for m in page.messages) == ["p1", "p2"]
    assert [c["pageToken"] for c in service.history_calls] == [None, "1"]


def test_collect_history_empty_delta_is_usable_and_empty() -> None:
    """Nothing new is a legitimate answer — distinct from expired/truncated."""

    service = FakeService(pages=[([], None)], metadata={}, history_pages=[([], None)])
    page = gc._collect_history(
        service, start_history_id="900", max_messages=50, scope="inbox"
    )
    assert page.usable is True
    assert page.messages == []
    # No ids → no metadata batch was executed.
    assert service.batch_sizes == []
