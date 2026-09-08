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

import re
import time
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

import pytest

USER = __import__("uuid").UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# Queries as ``build_gmail_query`` composes them, narrowest first.
NARROW = "in:inbox newer_than:3m"
WIDE = "in:inbox"


class _StubVerdict:
    """A stand-in for ``classifier.hybrid.ClassificationResult``.

    ``method`` is not decoration: it is a required field on the real type, and
    the sync path now records WHICH LAYER answered rather than asserting
    ``"rules"`` for everything (#496). A double that omits a field its original
    always carries is not a simpler double, it is a wrong one — and this file
    proved that by failing with ``AttributeError`` on a change that was correct
    everywhere the real type is used. Keep it in step with the dataclass.
    """

    def __init__(self, category: Any, confidence: float, method: str = "rules") -> None:
        self.category = category
        self.confidence = confidence
        self.method = method


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


# Deeper than any corpus in the tests that take the default, so that what stops
# those scans is the MAIL running out and not the target — they are about the
# shape of the bound, not its size. Tests that are about the size say so by
# passing `_SYNC_DEFAULT_SCAN_TARGET` explicitly.
_DEEPER_THAN_ANY_CORPUS_HERE = 750


async def _scan(
    monkeypatch: pytest.MonkeyPatch,
    gmail: _ShrinkingGmail,
    query: str,
    *,
    target: int = _DEEPER_THAN_ANY_CORPUS_HERE,
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
    in pages of 25. Bounded by pages, the wide scan reads four pages and merely
    TIES the narrow one while holding three times the mail. Bounded by messages
    examined, it reads all 300.

    25 A PAGE, NOT 20, SINCE #912. The list rail is 12 calls now — what 6,000
    units a minute pays for once the 297-message target has taken 5,940 of them
    — so a 20-a-page fixture stops on the rail at 240 and this test would be
    measuring the budget instead of the property it exists for. 25 is the
    smallest page that still reaches the default target inside the rail
    (``ceil(297/25) = 12``), which makes it the sharpest pathological page size
    available for a test about the SHAPE of the bound. The old-bug
    reproduction below deliberately keeps 20 a page: it pins its own rail at 4
    and is unaffected by what the shipped one is.
    """

    gmail = _ShrinkingGmail({NARROW: (100, 60), WIDE: (300, 25)})

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
    page for a 100-message request), and the rail still reaches the whole
    297-message default target there: ``ceil(297/30) = 10`` of the 12 calls the
    minute pays for. If that stops being true this fails, which is the point.

    DRIVEN AT THE PRODUCTION TARGET, not at the helper's deeper default. This
    test is about the size of the bound, so reading a number the shipped scan
    would never use made it answer a question nobody asks: at 750 it needed 25
    pages of 30, which is where #912's 6,065-unit scan lived.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    gmail = _ShrinkingGmail({WIDE: (100_000, 30)})
    result = await _scan(
        monkeypatch, gmail, WIDE, target=gmail_module._SYNC_DEFAULT_SCAN_TARGET
    )

    assert result.scanned == 297
    assert result.stopped_by == "target"
    assert len(gmail.calls) == 10
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

    The frontend classifies ``stopped_by`` into complete / partial / broken.

    THIS DOCSTRING USED TO SAY IT "falls back to complete for anything it does
    not recognise". It does not, and the difference is a safety property rather
    than a detail: ``stopKind`` in ``apps/web/lib/gmail/sync-plan.ts`` returns
    **"partial"** for an unknown value, on the stated grounds that an end state
    the UI cannot vouch for must not claim the mailbox was covered. Anyone who
    "fixed" the code to match the old wording would have deleted that property.
    Corrected 2026-09-04 after a verification pass read the function.

    The set is still asserted here, for the reason below the assertion: a new
    constant has to be added deliberately, and whoever adds it is the person who
    should be teaching the UI to read it.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    known = {
        gmail_module.STOPPED_COMPLETE,
        gmail_module.STOPPED_TARGET,
        gmail_module.STOPPED_DEADLINE,
        gmail_module.STOPPED_PAGE_LIMIT,
        gmail_module.STOPPED_DISCONNECTED,
        gmail_module.STOPPED_RELAY,
        gmail_module.STOPPED_RATE_LIMITED,
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

    # AND CHECK THAT THE UI ACTUALLY LEARNED IT.
    #
    # The set above is a hand-maintained mirror, so on its own it only proves
    # somebody edited this file — the instruction to teach `sync-plan.ts` first
    # was pure honour system, and honour systems are the estate's recurring
    # defect. Adding `STOPPED_RATE_LIMITED` here while forgetting the UI would
    # have passed.
    #
    # WHAT THE FAILURE ACTUALLY IS, corrected after a verification pass caught
    # this comment asserting the opposite. `stopKind` (`sync-plan.ts`) returns
    # **"partial"** for an unrecognised value, not "complete" — read the
    # function, its own comment says the safety property is deliberate. So an
    # untaught constant does NOT report a partial scan as finished; the docstring
    # a few lines up in this file makes that claim and is wrong too.
    #
    # The real cost is quieter and worth the gate anyway: `stopReasonPhrase`
    # falls through to the generic "stopped before finishing". For a rate limit
    # that is a bad answer, because the full-scan path has no 429 and no
    # `Retry-After` — `stopped_by` is its ONLY channel to the user — so the
    # person is told the scan stopped early and never that waiting fixes it,
    # while the interactive scan gets "Gmail asked us to slow down, resuming in
    # Ns". An untaught constant makes the two paths disagree about the same
    # condition.
    #
    # COMMENTS ARE STRIPPED FIRST, and the earlier version of this that did not
    # was demonstrably foolable: a review renamed `case "rate_limited":` to a
    # typo, added `"rate_limited"` inside a nearby comment, and the gate passed
    # with the UI carrying no such case at all. This block's own prose then
    # claimed it "cannot be fooled by a value the UI merely mentions in a
    # comment" — a check asserting a property it did not have.
    #
    # Still a substring search over the stripped text rather than a parse: it
    # cannot be defeated by a formatter, and running the TypeScript does not
    # belong in a pytest run.
    plan = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "web"
        / "lib"
        / "gmail"
        / "sync-plan.ts"
    )
    if plan.exists():
        raw = plan.read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
        code = re.sub(r"//[^\n]*", " ", code)
        unread = sorted(v for v in declared if f'"{v}"' not in code)
        assert not unread, (
            f"sync-plan.ts never names {unread} in CODE (comments do not "
            f"count), so `stopReasonPhrase` falls through to the generic "
            f"'stopped before finishing'. On the full-scan path `stopped_by` "
            f"is the only channel to the user, so they are told the scan "
            f"stopped early and never that waiting fixes it."
        )


# =============================================================================
# What the scan SPENDS
# =============================================================================
#
# Everything above bounds the scan in MESSAGES and in PAGES, and asserts what
# it read. Gmail charges for neither: it charges 20 units for every
# `messages.get` and 5 for every `messages.list`, against 6,000 per user per
# minute. The two bounds therefore MULTIPLY, and #912 is what that product
# does — `_SYNC_DEFAULT_SCAN_TARGET = 297` was derived as three whole pages of
# 99 at 5,955 units "with 45 units to spare", but 45 units is nine list calls
# and the loop was allowed 25 of them. Every short page Gmail hands back is
# another 5 units the derivation never paid for, and every unreadable id is
# another 20: it took its `messages.get` slot, did not count toward 297, and
# the loop asked for a replacement.
#
# Neither file that owned half of this could see it. `test_the_page_size_fits_
# gmails_minute.py` prices ONE page against one minute; the tests above assert
# call counts and stop reasons. Nothing computed the spend of a whole SCAN.

# Read from Cloud Console (project jobtracker-502918) and Gmail's quota table,
# 2026-09-04. HARD-CODED, for the reason `test_the_page_size_fits_gmails_
# minute.py` gives at length in its module docstring: an expectation taken from
# the same source as the code compares a config against itself, catches drift
# and passes every edit. These three are the ceiling every assertion in this
# section is sourced FROM — never `_SYNC_DEFAULT_SCAN_TARGET` and never
# `_SYNC_MAX_LIST_CALLS`, which are the values under test and would make the
# gate pass for any value of themselves.
UNITS_PER_MINUTE = 6000
UNITS_PER_GET = 20
UNITS_PER_LIST = 5

# The smallest page Gmail has ever handed this project for a 100-message
# request: 68 / 43 / 45 / 41 for 3m / 6m / 12m / all-time, measured live on
# 2026-08-10 and recorded in `gmail_oauth.py`'s own commentary. A MEASUREMENT,
# not a constant of the code — it is what the rail has to stay large enough to
# reach the target through, and the reason a rail cut to what the budget
# affords is not also a rail that strands ordinary mailboxes.
WORST_OBSERVED_PAGE = 41


class _QuotaMeteredGmail:
    """A Gmail that respects ``maxResults``, and a meter for what it costs.

    ``_ShrinkingGmail`` above cannot be used for this. It adds
    ``unreadable_per_page`` on TOP of a full page, so a request for 99 comes
    back carrying 102 ids — which no real ``messages.list`` does, and which
    would make the units number wrong in exactly the direction under test.

    Here a page is what Gmail would really hand back: at most ``maxResults``
    ids, ``unreadable`` of which fail to come back as messages. That is the
    split :class:`MessagePage` documents — ``len(messages) + unreadable`` is
    what the page set out to fetch — and it is why ``requested`` and
    ``scanned`` are different numbers whenever ``unreadable_per_page`` is set.
    A fixture where they were equal could not see the second half of #912 at
    all.

    ``units`` prices what the scan spent: one ``messages.list`` per page (the
    client's ``list_pages_walked`` is 1 at every page size this scan uses) plus
    one ``messages.get`` per id LISTED, readable or not.
    """

    def __init__(
        self,
        *,
        per_page: int,
        unreadable_per_page: int = 0,
        total: int = 100_000,
    ) -> None:
        self.per_page = per_page
        self.unreadable_per_page = unreadable_per_page
        self.total = total
        self.lists = 0
        self.ids = 0
        self.requested_sizes: list[int] = []

    @property
    def units(self) -> int:
        return UNITS_PER_LIST * self.lists + UNITS_PER_GET * self.ids

    async def fetch_message_page(
        self,
        user_id: Any,
        *,
        query: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> Any:
        from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

        asked = page_size or self.per_page
        self.requested_sizes.append(asked)
        start = int(page_token or 0)
        ids = max(0, min(asked, self.per_page, self.total - start))
        self.lists += 1
        self.ids += ids
        unreadable = min(self.unreadable_per_page, ids)
        messages = [
            CloudGmailMessage(
                message_id=f"m{i}",
                thread_id=f"t{i}",
                subject="Subject",
                sender_name="Sender",
                sender_email="someone@example.test",
                snippet="snippet",
                received_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
            for i in range(start, start + ids - unreadable)
        ]
        nxt = str(start + ids) if start + ids < self.total else None
        return MessagePage(
            messages=messages,
            next_page_token=nxt,
            unreadable=unreadable,
            result_size_estimate=None,
        )


async def _metered_scan(
    monkeypatch: pytest.MonkeyPatch, gmail: _QuotaMeteredGmail
) -> Any:
    """Drive the real ``_full_scan`` at the real default target."""

    import jobtracker.cloud.gmail_oauth as gmail_module

    return await _scan(
        monkeypatch, gmail, WIDE, target=gmail_module._SYNC_DEFAULT_SCAN_TARGET
    )


def test_the_two_test_files_agree_about_gmails_quota() -> None:
    """The three numbers are duplicated on purpose; drift between them is not.

    ``test_the_page_size_fits_gmails_minute.py`` states why they are not
    imported from the application. It does not follow that a SECOND copy may
    quietly disagree with the first — the day Google moves one of these, both
    files have to move, and this is what says so instead of leaving one gate
    grading against a stale minute.

    A text read rather than an import, matching how this suite already reads
    ``types.ts`` and ``sync-plan.ts``: the point is to notice the other file's
    numbers changing, and importing them would make the two agree by
    construction.
    """

    sibling = Path(__file__).resolve().parent / "test_the_page_size_fits_gmails_minute.py"
    source = sibling.read_text(encoding="utf-8")
    ours = {
        "UNITS_PER_MINUTE": UNITS_PER_MINUTE,
        "UNITS_PER_GET": UNITS_PER_GET,
        "UNITS_PER_LIST": UNITS_PER_LIST,
    }
    for name, mine in ours.items():
        match = re.search(rf"^{name} = (\d+)$", source, flags=re.M)
        assert match, f"{name} is no longer declared where this gate can read it"
        assert int(match.group(1)) == mine, (
            f"{sibling.name} says {name} = {match.group(1)} and this file says "
            f"{mine}. One of them is grading against a quota Google no longer "
            f"charges; re-derive `_SYNC_DEFAULT_SCAN_TARGET` and "
            f"`_SYNC_MAX_LIST_CALLS` from whichever is right."
        )


async def test_a_whole_scan_of_full_pages_fits_the_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy case — AND THE TRAP, which is why it is not the only arm.

    This assertion passes with #912 reinstated. Three pages of 99 is precisely
    the case the 297 target was derived for, so measuring it proves the
    derivation and nothing about the loop that spends it. Every other test in
    this section exists because this one cannot fail for the right reason.
    """

    gmail = _QuotaMeteredGmail(per_page=99)
    result = await _metered_scan(monkeypatch, gmail)

    assert (gmail.lists, gmail.ids) == (3, 297)
    assert gmail.units == 5955
    assert gmail.units <= UNITS_PER_MINUTE
    assert result.scanned == 297
    assert result.stopped_by == "target"


@pytest.mark.parametrize(
    ("per_page", "lists", "scanned", "units", "stopped_by"),
    [
        # Gmail under-fills a page and the scan takes another one — at 5 units
        # a time the derivation never budgeted for. Re-derived against the
        # loop itself; `lists` is what the rail permits and `units` is
        # `20 * ids + 5 * lists`.
        (WORST_OBSERVED_PAGE, 8, 297, 5980, "target"),
        (30, 10, 297, 5990, "target"),
        # ON the boundary: 12 calls is exactly what the minute pays for, and
        # 25 a page is exactly the smallest page that still reaches 297 inside
        # them. 6,000 units, not one over, and the target is still met whole.
        (25, 12, 297, 6000, "target"),
        # Below it the rail binds, and the scan SAYS it stopped short rather
        # than buying the rest of the target on credit. Under the 25-call rail
        # these three read 297 messages for 6,005 / 6,015 / 6,065 units.
        (24, 12, 288, 5820, "page_limit"),
        (20, 12, 240, 4860, "page_limit"),
        (12, 12, 144, 2940, "page_limit"),
    ],
)
async def test_a_whole_scan_fits_the_minute_when_gmail_underfills_its_pages(
    monkeypatch: pytest.MonkeyPatch,
    per_page: int,
    lists: int,
    scanned: int,
    units: int,
    stopped_by: str,
) -> None:
    """#912's first vector: the scan is bounded by MESSAGES, and pages cost.

    Gmail treats ``maxResults`` as an upper bound — the live figures are 68 /
    43 / 45 / 41 for a 100-message request — so the same 297 messages arrive
    over as many pages as Gmail feels like, and each one is another
    ``messages.list``. The crossover is 25 a page: at 24 the old loop spent
    6,005 units, at 20 it spent 6,015, at 12 it spent 6,065 and used every one
    of the 25 calls it was allowed.

    MUST RED ON: `_SYNC_MAX_LIST_CALLS` going back to 25 (the 20-a-page row
    becomes 15 calls and 6,015 units). The control immediately below runs that
    mutation rather than trusting this note.
    """

    gmail = _QuotaMeteredGmail(per_page=per_page)
    result = await _metered_scan(monkeypatch, gmail)

    assert gmail.units <= UNITS_PER_MINUTE, (
        f"a default scan against {per_page}-message pages spends "
        f"{gmail.units} of {UNITS_PER_MINUTE} units per user per minute "
        f"({gmail.lists} list calls at {UNITS_PER_LIST} plus {gmail.ids} gets "
        f"at {UNITS_PER_GET}); its last pages take the 429."
    )
    assert (gmail.lists, gmail.ids, gmail.units) == (lists, scanned, units)
    assert result.scanned == scanned
    assert result.stopped_by == stopped_by


async def test_the_old_25_call_rail_is_what_put_a_short_page_scan_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The directional control: make it WORSE and watch the number go UP.

    A gate that only ever reds on loss cannot tell a fix from a coincidence.
    So this puts the rail back to the 25 it was — the same fixture, one
    constant changed — and asserts the spend crosses the ceiling it now fits
    under. 6,015 against 6,000, which is the 20-messages-a-page row of #912's
    table reproduced against the shipped loop.

    It also pins WHY 25 was wrong rather than merely large: the extra calls buy
    57 more messages for 1,155 more units, which is a bucket the scan does not
    have.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    shipped = _QuotaMeteredGmail(per_page=20)
    fitted = await _metered_scan(monkeypatch, shipped)

    monkeypatch.setattr(gmail_module, "_SYNC_MAX_LIST_CALLS", 25)
    worse = _QuotaMeteredGmail(per_page=20)
    overspent = await _metered_scan(monkeypatch, worse)

    assert worse.units > shipped.units
    assert worse.units == 6015 > UNITS_PER_MINUTE >= shipped.units
    assert (worse.lists, shipped.lists) == (15, 12)
    assert (overspent.scanned, fitted.scanned) == (297, 240)


async def test_an_unreadable_id_is_paid_for_even_though_it_is_never_scanned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#912's second vector, and it stacks with the first rather than replacing it.

    ``unreadable`` is how many ids a page LISTED and could not turn into a
    message. Every one of them consumed a request slot — the ``messages.get``
    was issued — and none of them counted toward the target, so a loop bounded
    on messages PARSED asked for a replacement page and paid 20 units again.
    ONE unreadable id per page, with nothing short about the pages at all, put
    the old loop over the ceiling on its fourth page — 6,020 units — and it
    then spent the rest of its 25 calls chasing three messages it could not
    read, finishing at 6,545 for 296 messages.

    The two numbers in the assertion are the whole point: the scan asked Gmail
    for 297 and read 288. It reports 288, beside 9 unreadable, because that is
    what it read — the fix bounds the LOOP on what was requested and leaves the
    RECEIPT saying what was parsed. A scan that said "297 scanned" with nine of
    them unreadable would be a new lie in the place of the old one.

    MUST RED ON: `_full_scan`'s bound going back to counting
    `len(page.messages)`. That mutation alone takes this fixture to 12 list
    calls, 330 gets and 6,660 units; with the 25-call rail back beside it —
    the shipped bug entire — 25 calls, 369 gets and 7,505 units.
    """

    lossy = _QuotaMeteredGmail(per_page=99, unreadable_per_page=3)
    result = await _metered_scan(monkeypatch, lossy)

    assert lossy.units <= UNITS_PER_MINUTE, (
        f"three pages of 99 with 3 unreadable ids each spent {lossy.units} of "
        f"{UNITS_PER_MINUTE} units: the unreadable ids were fetched, did not "
        f"count toward the target, and the loop bought their replacements."
    )
    assert (lossy.lists, lossy.ids, lossy.units) == (3, 297, 5955)
    # Requested and parsed are DIFFERENT NUMBERS here, which is the only shape
    # of fixture that can see this defect: 297 asked for, 288 read back.
    assert result.scanned == 288
    assert result.unreadable == 9
    assert result.scanned + result.unreadable == 297
    assert result.stopped_by == "target"

    # And the paired case: same pages, nothing unreadable. The SPEND is
    # identical because the same 297 ids were fetched either way — what moves
    # is what came back readable. Under the old bound these two differed by
    # 1,550 units.
    clean = _QuotaMeteredGmail(per_page=99)
    whole = await _metered_scan(monkeypatch, clean)

    assert clean.units == lossy.units
    assert whole.scanned == 297 != result.scanned


def test_the_list_rail_is_what_the_minute_pays_for() -> None:
    """The algebra behind the rail, stated where a reviewer can check it.

    A default scan's gets are fixed at the target, so the only thing left to
    buy is list calls: ``6000 - 20*297 = 60``, and 60 units is twelve calls at
    five. Twelve is therefore not a safety margin or a round number, it is the
    last call the minute pays for.

    Two-sided on purpose. The upper bound alone would be satisfied by a rail of
    ONE, which fits any budget by scanning almost nothing; the lower bound says
    the rail must still reach the whole target through the smallest page this
    project has ever measured (``ceil(297/41) = 8``).

    BLIND ON ITS OWN to the unreadable vector, and that is why the behavioural
    arms above are not redundant with it: this assumes the scan issues exactly
    one get per targeted message, which is a property `_full_scan` has only
    because it counts what it REQUESTED. Do not delete them in favour of this.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    target = gmail_module._SYNC_DEFAULT_SCAN_TARGET
    rail = gmail_module._SYNC_MAX_LIST_CALLS
    spend = UNITS_PER_GET * target + UNITS_PER_LIST * rail

    assert spend <= UNITS_PER_MINUTE, (
        f"a scan that reaches its {target}-message target over {rail} list "
        f"calls spends {spend} of {UNITS_PER_MINUTE} units per user per "
        f"minute. Gmail defers the remainder; the fix is the rail, not the "
        f"target, which is already derived from this same ceiling."
    )
    assert rail * WORST_OBSERVED_PAGE >= target, (
        f"{rail} list calls cannot reach {target} messages at "
        f"{WORST_OBSERVED_PAGE} a page — the smallest page Gmail has actually "
        f"handed this project — so an ordinary all-time scan would stop on the "
        f"rail rather than on its target."
    )
