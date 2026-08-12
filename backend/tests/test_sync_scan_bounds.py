"""What bounds a server-side sync scan, and what it is allowed to claim.

Two defects measured against the live app on 2026-08-10, pinned here:

1. **A page-count bound is the wrong bound.** Gmail treats ``maxResults`` as an
   upper bound, not a quota, and hands back fewer messages per page as the query
   widens. Measured at ``page_size=100``, ``scope=inbox``: 68 messages for
   ``newer_than:3m``, 43 for ``6m``, 45 for ``12m``, 41 for all-time — every one
   of them with a next-page token. A loop bounded by a maximum number of PAGES
   therefore accumulates a *smaller* total for a *wider* window, and the product
   reports "All time" as having scanned less than "3 months". A user widening
   the window sees less and concludes the app is broken.

2. **``scanned`` was presented as coverage.** A bare count of what a scan read
   is the same sentence whether the window held 41 messages or 4,100, and the
   sync path additionally threw away ``MessagePage.unreadable`` — the ids it
   listed and could not read back — so the smaller number was reported as though
   it were the whole.

The fake here is the important part: its page sizes SHRINK as the query widens,
which is the real behaviour being defended against, not a hypothetical.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest

USER = __import__("uuid").UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# Queries as ``build_gmail_query`` composes them, narrowest first.
NARROW = "in:inbox newer_than:3m"
WIDE = "in:inbox"


class _StubVerdict:
    def __init__(self, category: Any, confidence: float) -> None:
        self.category = category
        self.confidence = confidence


class _StubClassifier:
    """Answers every message the same way — the scan's bound is what is under
    test, not the classification."""

    async def classify(self, subject: str, snippet: str, sender: str) -> _StubVerdict:
        from jobtracker.database.models import EmailCategory

        return _StubVerdict(EmailCategory.OTHER, 0.1)


class _ShrinkingGmail:
    """A Gmail whose page sizes shrink as the query widens.

    ``corpora`` maps a query to ``(total_messages, per_page_cap)``. The cap is
    Gmail's own ceiling on that query and is applied on top of the caller's
    ``page_size``, exactly like the live behaviour: ask for 100, get 41.
    """

    def __init__(
        self,
        corpora: dict[str, tuple[int, int]],
        *,
        unreadable_per_page: int = 0,
        estimates: dict[str, int | None] | None = None,
    ) -> None:
        self.corpora = corpora
        self.unreadable_per_page = unreadable_per_page
        self.estimates = estimates or {}
        self.calls: list[tuple[str, int]] = []  # (query, requested page_size)

    async def fetch_message_page(
        self,
        user_id: Any,
        *,
        query: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> Any:
        from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

        self.calls.append((query, page_size or 0))
        total, cap = self.corpora[query]
        start = int(page_token or 0)
        served = max(0, min(page_size or cap, cap, total - start))
        messages = [
            CloudGmailMessage(
                message_id=f"{query}-{i}",
                thread_id=f"t{i}",
                subject="Subject",
                sender_name="Sender",
                sender_email="someone@example.test",
                snippet="snippet",
                received_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
            for i in range(start, start + served)
        ]
        nxt = str(start + served) if start + served < total else None
        return MessagePage(
            messages=messages,
            next_page_token=nxt,
            unreadable=self.unreadable_per_page,
            result_size_estimate=self.estimates.get(query),
        )


async def _scan(
    monkeypatch: pytest.MonkeyPatch,
    gmail: _ShrinkingGmail,
    query: str,
    *,
    target: int = 750,
    deadline: float | None = None,
) -> Any:
    """Drive the real ``_full_scan`` against the fake and return its result."""

    import jobtracker.cloud.gmail_client as gmail_client_module
    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.cloud import pipeline

    monkeypatch.setattr(
        gmail_client_module, "fetch_message_page", gmail.fetch_message_page
    )
    return await gmail_module._full_scan(
        USER,
        query=query,
        target=target,
        classifier=_StubClassifier(),
        pipeline=pipeline,
        deadline=deadline,
    )


# =============================================================================
# The stopping condition
# =============================================================================


async def test_a_wider_window_never_examines_less_than_a_narrower_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE property. A wider query matches a superset of the mail, so it must
    never come back having read fewer messages — however small Gmail's pages get.

    The narrow window holds 100 messages in pages of 60; the wide one holds 300
    in pages of 20. Bounded by pages, the wide scan reads 80 and "loses" to the
    narrow one. Bounded by messages examined, it reads all 300.
    """

    gmail = _ShrinkingGmail({NARROW: (100, 60), WIDE: (300, 20)})

    narrow = await _scan(monkeypatch, gmail, NARROW)
    wide = await _scan(monkeypatch, gmail, WIDE)

    assert narrow.scanned == 100
    assert wide.scanned == 300
    assert wide.scanned >= narrow.scanned
    # Both ran out of MAIL, not of budget — so both may honestly say "complete".
    assert narrow.stopped_by == "complete"
    assert wide.stopped_by == "complete"


async def test_a_page_count_bound_is_what_made_the_wider_window_smaller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect itself, reproduced — and the reason the bound changed.

    Pinning ``_SYNC_MAX_LIST_CALLS`` back to the old 4-page ceiling recreates
    the exact shape of the shipped bug against the same fake: the wider window
    reads strictly LESS. It also shows the second half of the fix — a scan that
    stops on a rail now says which rail, instead of reporting the short number
    as though the mailbox were that small.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    monkeypatch.setattr(gmail_module, "_SYNC_MAX_LIST_CALLS", 4)
    gmail = _ShrinkingGmail({NARROW: (100, 60), WIDE: (300, 20)})

    narrow = await _scan(monkeypatch, gmail, NARROW)
    wide = await _scan(monkeypatch, gmail, WIDE)

    assert narrow.scanned == 100  # exhausted in 2 pages, unaffected
    assert wide.scanned == 80  # 4 pages x 20 — less mail read for more window
    assert wide.scanned < narrow.scanned  # the user-visible nonsense
    assert wide.stopped_by == "page_limit"  # ... but no longer silent


async def test_the_message_target_is_what_stops_a_deep_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the shipped rails, the target is what binds — not the list ceiling.

    30 messages a page is well below anything measured (41 was the worst live
    page for a 100-message request), and 25 list calls still reach the full
    750-message target. If that stops being true this fails, which is the point.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    gmail = _ShrinkingGmail({WIDE: (100_000, 30)})
    result = await _scan(monkeypatch, gmail, WIDE)

    assert result.scanned == 750
    assert result.stopped_by == "target"
    assert len(gmail.calls) <= gmail_module._SYNC_MAX_LIST_CALLS


async def test_the_time_budget_is_checked_before_a_page_is_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page must never BEGIN inside the budget and finish outside it.

    A deadline already in the past means not one Gmail call is made — the check
    is at the top of the loop, not after the fetch — and the result says the
    budget is why, rather than reporting zero as an empty mailbox.
    """

    gmail = _ShrinkingGmail({WIDE: (500, 100)})
    result = await _scan(
        monkeypatch, gmail, WIDE, deadline=time.monotonic() - 1.0
    )

    assert gmail.calls == []
    assert result.scanned == 0
    assert result.stopped_by == "deadline"


async def test_the_default_time_budget_leaves_room_inside_the_function_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scan is only the first half of the request; the merge follows it."""

    import jobtracker.cloud.gmail_oauth as gmail_module

    assert 0 < gmail_module._SYNC_TIME_BUDGET_SECONDS <= 45.0


async def test_an_empty_page_that_still_has_a_token_does_not_end_the_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gmail returns empty pages mid-query. Treating one as the end of the
    mailbox is the same class of bug as counting pages."""

    import jobtracker.cloud.gmail_client as gmail_client_module
    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.cloud import pipeline
    from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

    def _messages(n: int) -> list[CloudGmailMessage]:
        return [
            CloudGmailMessage(
                message_id=f"m{i}",
                thread_id="t",
                subject="Subject",
                sender_name=None,
                sender_email="someone@example.test",
                snippet="",
                received_at=None,
            )
            for i in range(n)
        ]

    scripted = [
        MessagePage(messages=[], next_page_token="A"),  # empty, but continuable
        MessagePage(messages=[], next_page_token="B"),  # and again
        MessagePage(messages=_messages(20), next_page_token="C"),
        MessagePage(messages=_messages(20), next_page_token=None),
    ]
    seen = {"n": 0}

    async def _fetch(user_id: Any, **_kwargs: Any) -> Any:
        seen["n"] += 1
        return scripted[seen["n"] - 1]

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fetch)
    result = await gmail_module._full_scan(
        USER,
        query=WIDE,
        target=750,
        classifier=_StubClassifier(),
        pipeline=pipeline,
    )

    # It kept going past both empty pages and read the mail that followed.
    assert seen["n"] == 4
    assert result.scanned == 40
    assert result.stopped_by == "complete"


# =============================================================================
# What the scan is allowed to claim
# =============================================================================


async def test_unreadable_messages_are_carried_not_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_full_scan`` used to drop ``page.unreadable`` on the floor, so the sync
    reported the smaller number as though it were the whole."""

    gmail = _ShrinkingGmail({WIDE: (100, 50)}, unreadable_per_page=3)
    result = await _scan(monkeypatch, gmail, WIDE)

    assert result.scanned == 100
    assert result.unreadable == 6  # 3 per page across the two pages
    assert len(result.items) == 100


async def test_the_size_estimate_is_the_largest_seen_and_never_below_examined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gmail's ``resultSizeEstimate`` drifts between pages of one query. A
    denominator smaller than its own numerator is worse than none, so it is
    clamped — but never invented."""

    gmail = _ShrinkingGmail({WIDE: (100, 50)}, estimates={WIDE: 4200})
    assert (await _scan(monkeypatch, gmail, WIDE)).result_size_estimate == 4200

    # An estimate below what was actually read is clamped up to it.
    low = _ShrinkingGmail({WIDE: (100, 50)}, estimates={WIDE: 12})
    assert (await _scan(monkeypatch, low, WIDE)).result_size_estimate == 100

    # Gmail offered none: report none. A floor is not an estimate.
    silent = _ShrinkingGmail({WIDE: (100, 50)})
    assert (await _scan(monkeypatch, silent, WIDE)).result_size_estimate is None


# =============================================================================
# Gmail vanishing mid-scan
# =============================================================================


class _VanishingGmail:
    """Answers the first ``ok_pages`` page requests, then stops answering.

    ``fetch_message_page`` returns ``None`` when it cannot read Gmail at all —
    an expired or revoked token, or Gmail refusing. The interesting case is
    when that happens PART WAY through: earlier pages succeeded, so the scan
    holds a real but incomplete read of the window.
    """

    def __init__(self, total: int, per_page: int, ok_pages: int) -> None:
        self.total = total
        self.per_page = per_page
        self.ok_pages = ok_pages
        self.calls = 0

    async def fetch_message_page(
        self,
        user_id: Any,
        *,
        query: str,
        page_size: int,
        page_token: str | None = None,
    ) -> Any:
        from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

        self.calls += 1
        if self.calls > self.ok_pages:
            return None  # Gmail stopped answering.

        start = int(page_token) if page_token else 0
        served = min(self.per_page, page_size, self.total - start)
        messages = [
            CloudGmailMessage(
                message_id=f"m{i}",
                thread_id=f"t{i}",
                subject="Application received",
                sender_name="Careers",
                sender_email="careers@example.test",
                snippet="snippet",
                received_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
            for i in range(start, start + served)
        ]
        nxt = str(start + served) if start + served < self.total else None
        return MessagePage(
            messages=messages,
            next_page_token=nxt,
            unreadable=0,
            result_size_estimate=None,
        )


async def test_gmail_going_away_mid_scan_is_reported_not_called_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last untested terminal state of ``stopped_by``.

    Every other stop reason — complete, target, deadline, page_limit, relay —
    is pinned somewhere in this suite. ``disconnected`` was not, despite having
    its own branch in the UI: the sync bar renders "the scan lost its Gmail
    connection partway" and offers a reconnect link only for this value, so an
    untested constant here means an unreachable-in-anger surface there.

    The property that matters is that a partial read is never dressed up as a
    whole one. The scan answered page 1 and lost Gmail on page 2, so what it
    holds is real and incomplete — it must keep the mail it did read AND say
    the scan ended early, because the caller uses that to decide whether rows
    it did not see may be removed.
    """

    gmail = _VanishingGmail(total=100, per_page=25, ok_pages=1)
    result = await _scan(monkeypatch, gmail, WIDE)

    from jobtracker.cloud.gmail_oauth import STOPPED_DISCONNECTED

    assert result.stopped_by == STOPPED_DISCONNECTED
    # The first page's mail survives — losing the connection is not a reason to
    # throw away what was already read.
    assert len(result.items) == 25
    assert result.scanned == 25


async def test_gmail_unreachable_from_the_very_first_page_is_a_409_not_a_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was read at all, which is a different answer to a partial read.

    "Your scan stopped early" implies something WAS read and invites the user
    to continue it; there is nothing to continue here. The endpoint has to say
    Gmail is not connected instead, so the UI sends them to reconnect rather
    than to retry a scan that can never start.
    """

    from fastapi import HTTPException

    gmail = _VanishingGmail(total=100, per_page=25, ok_pages=0)
    with pytest.raises(HTTPException) as excinfo:
        await _scan(monkeypatch, gmail, WIDE)

    assert excinfo.value.status_code == 409
    assert "not connected" in str(excinfo.value.detail).lower()


async def test_every_stop_reason_the_backend_can_emit_is_a_known_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard on the vocabulary itself.

    The frontend classifies ``stopped_by`` into complete / partial / broken and
    falls back to "complete" for anything it does not recognise — the safest
    default for an OLD frontend against a NEW backend, and the most dangerous
    one for a value the backend invents later. So the set is asserted here: a
    new constant has to be added deliberately, and whoever adds it is the
    person who should be teaching the UI to read it.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    known = {
        gmail_module.STOPPED_COMPLETE,
        gmail_module.STOPPED_TARGET,
        gmail_module.STOPPED_DEADLINE,
        gmail_module.STOPPED_PAGE_LIMIT,
        gmail_module.STOPPED_DISCONNECTED,
        gmail_module.STOPPED_RELAY,
    }
    declared = {
        value
        for name, value in vars(gmail_module).items()
        if name.startswith("STOPPED_") and isinstance(value, str)
    }
    assert declared == known, (
        f"the backend can emit a stop reason the UI has never been taught to "
        f"read: {sorted(declared - known)}. Add it to lib/gmail/sync-plan.ts "
        f"(stopKind + stopReasonPhrase) before adding it here."
    )
