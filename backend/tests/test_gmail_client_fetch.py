"""Unit tests for the high-volume cloud Gmail fetch engine (issue C7).

These cover the Gmail *transport* logic without a real token by driving a
fake ``service`` that mimics the slice of the googleapiclient surface the
fetch uses:

- ``build_gmail_query`` — range + scope → Gmail query string.
- ``_collect_page`` — one ``messages.list`` page → batched
  ``messages.get(format=metadata)`` → ordered, parsed messages + cursor.

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
    assert build_gmail_query(None, "anywhere") == "in:anywhere"
    assert build_gmail_query(0, "anywhere") == "in:anywhere"


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
        return _Exec(
            {
                "messages": [{"id": i} for i in ids[:maxResults]],
                "nextPageToken": next_token,
            }
        )

    def get(self, *, userId: str, id: str, format: str, metadataHeaders):  # noqa: A002,N803
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
        self._items: list[tuple[str, _GetRequest]] = []

    def add(self, request: _GetRequest, request_id: str) -> None:
        self._items.append((request_id, request))

    def execute(self) -> None:
        self._s.batch_sizes.append(len(self._items))
        for request_id, _request in self._items:
            self._cb(request_id, self._s.metadata.get(request_id), None)


class FakeService:
    """Minimal stand-in for a googleapiclient Gmail service."""

    def __init__(self, pages, metadata) -> None:
        # pages: list[(ids, next_page_token)]; metadata: {id: raw|None}
        self.pages = pages
        self.metadata = metadata
        self.list_calls: list[dict] = []
        self.batch_sizes: list[int] = []

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
