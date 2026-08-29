"""A sync must be able to say how many messages it LOOKED AT, not only how many
it filed.

REPORTED FROM LIVE USE on 2026-08-21 (#422): "I applied to 4 new Microsoft and a
Google application, but when I sync it in the app, I'm not getting anything."

Part 1 of that issue was identity — four applications collapsing onto one card —
and it is fixed on main. This file is part 2, which is not about routing at all.
The four Microsoft applications produced **zero rows anywhere**: no ``emails``
row, no application, nothing in the review queue.
``applications._persist_message_refs`` writes an ``emails`` row only for a
message that clustered into an application or was flagged for review, so from
Postgres — with full access — these three states were the same state:

  * the mail never arrived,
  * it arrived after ``last_sync_at`` and is not synced yet,
  * it was fetched, scored, and thrown away.

So the most common user-facing question about this product — *did you see my
mail?* — had no answer. ``test_lifecycle_drop_is_counted.py`` closed one half of
that (a lifecycle verdict under the review floor is now named and counted). The
half left open is the wider one: a message the classifier scores ``other``
leaves through the same terminal door, and nothing counted it at all.

THE VOCABULARY IS THE CORPUS HARNESS'S, not a new one.
``tests/corpus_independent/harness.py`` already draws exactly this distinction —
**LOST** ("about a real application, and reached NOTHING") versus **DROPPED**
("under the review floor; counted, but on no screen"), because "one of these is
invisible and the other is merely bad". ``dropped`` here is that DROPPED.
``reached_nothing`` is that LOST, widened to what a running product can compute:
LOST needs ground truth and there is none at sync time, so the bucket holds
genuine misses together with the noise that was correctly ignored. It is a
haystack, and the point of #422 is that until now there was not even a haystack.

WHAT EACH TEST BELOW IS FOR

  * The reproduction, run against the endpoint: a message scored ``other``
    writes nothing, and until this change the response for it was
    character-for-character the response for an empty mailbox.
  * Every counter, in BOTH directions. A counter only ever exercised on its
    non-zero case has not been shown to read zero, and one only ever exercised
    on zero has not been shown to count. Each of ``filed``, ``queued``,
    ``dropped`` and ``reached_nothing`` gets a scan that produces it and a scan
    that must leave it at zero.
  * The partition, asserted rather than assumed. An accounting that does not
    close is how messages go missing silently.
  * That ``closes`` is capable of being False — a property that cannot fail is
    not a check.
  * The durable half: the numbers survive the response, in ``sync_state``, and
    NULL ("never recorded") stays distinguishable from 0 ("read nothing").

THE FILENAME IS LOAD-BEARING, so do not "tidy" it to match the branch. This
file borrows ``cloud_app`` from ``test_gmail_oauth_cloud.py``, and that fixture
reloads ``jobtracker.config`` on teardown without re-pointing the modules that
hold a reference to the old ``settings`` object. ``test_auth_supabase_jwt.py``
patches settings BY REFERENCE and has an explicit guard for it — "settings
identity diverged before this fixture ran; a module reload in an earlier test
file has broken the by-reference patching this uses" — so any module using that
fixture EARLIER in an alphabetical run reds 15 auth assertions and errors six
account-deletion tests. Under the name this file was first given
(``test_a_sync_...``) it did exactly that, and the failures named nothing to do
with sync counters.

Sorting immediately after ``test_gmail_oauth_cloud.py``, whose fixture this is,
puts it where every other consumer of that fixture already sits and where the
suite is green. That is a workaround and it is written down as one: the leak is
a pre-existing defect in a fixture shape roughly eighteen test modules share,
and fixing it is its own change — a reload cannot be undone by
``monkeypatch.undo``, and reloading the dependents instead breaks
``AuthError``'s class identity, which was measured.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from jobtracker.cloud import pipeline as p

# The cloud app, its client and a Gmail connection, from the suite that owns
# them. Same idiom as ``test_body_is_never_persisted.py`` importing
# ``FakeService``: one reload sequence, defined once.
from tests.test_gmail_oauth_cloud import (  # noqa: F401 — fixtures by name
    GMAIL_ADDRESS,
    USER_A,
    _applied_msg,
    _connect_gmail,
    _install_gmail_stubs,
    _msg,
    _sync_rows,
    _token_for,
    client,
    cloud_app,
)

HEADERS = {"Authorization": f"Bearer {_token_for(USER_A)}"}


# =============================================================================
# The shapes, measured rather than assumed
# =============================================================================
#
# Every one of these was run through ``roll_up_applications`` and
# ``collect_review_items`` before it was written down, and each lands in exactly
# one bucket. They are synthetic: this repository is public and no real mailbox
# content belongs in it. The Microsoft shape is the one exception worth naming —
# it is the sender and subject from #422, which are a no-reply address and a
# form letter, and it is already in ``test_lifecycle_drop_is_counted.py``.


def _item(
    message_id: str,
    category: str,
    sender: str,
    subject: str,
    confidence: float,
    *,
    thread: str | None = None,
    snippet: str = "",
) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        category=category,
        sender_email=sender,
        subject=subject,
        sender_name=None,
        received_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        confidence=confidence,
        thread_id=thread or f"th-{message_id}",
        snippet=snippet,
    )


def _filed(n: int = 1) -> p.PipelineItem:
    """Clears the auto-file gate, names an employer and a role → a card.

    ``n`` varies the employer as well as the id: two confirmations from ONE
    employer are one application, and a test that wanted two filed messages
    would silently get one card and one message.
    """

    return _item(
        f"filed-{n}",
        "applied",
        "no-reply@greenhouse.io",
        f"Thank you for applying to Cedar Labs {n} - Software Engineer",
        0.95,
        snippet="We have received your application.",
    )


def _queued(n: int = 1) -> p.PipelineItem:
    """The classifier itself asked for a human → the review queue."""

    return _item(
        f"queued-{n}",
        "needs_review",
        f"careers@vantor{n}.test",
        "About your application",
        0.5,
        snippet="Hello.",
    )


def _dropped(n: int = 1) -> p.PipelineItem:
    """#422's shape: a lifecycle verdict under the floor, from a non-ATS sender.

    ``rejection`` at 0.60 is what the live classifier returns for this body —
    measured in ``test_lifecycle_drop_is_counted.py``, not guessed here.
    """

    return _item(
        f"dropped-{n}",
        "rejection",
        "donotreply@email.careers.microsoft.test",
        "Thank you for your application!",
        0.60,
        snippet="Thank you for taking the time to submit your application.",
    )


def _noise(n: int = 1) -> p.PipelineItem:
    """A newsletter. Correctly ignored, and counted anyway."""

    return _item(
        f"noise-{n}",
        "other",
        "news@example.test",
        "Your weekly digest",
        0.0,
        snippet="This week in tech.",
    )


def _ledger_over(items: list[p.PipelineItem]) -> p.ScanLedger:
    """Route one scan exactly as ``POST /gmail/sync`` routes it, then partition."""

    rolled = p.roll_up_applications(items)
    dropped: list[p.DroppedVerdict] = []
    review = p.collect_review_items(items, dropped)
    return p.ledger_for_scan(items, rolled, review, dropped)


def _as_dict(item: p.PipelineItem) -> dict[str, Any]:
    """The same message as ``POST /gmail/sync`` accepts it."""

    return {
        "message_id": item.message_id,
        "category": item.category,
        "sender_email": item.sender_email,
        "subject": item.subject,
        "received_at": item.received_at.isoformat(),
        "confidence": item.confidence,
        "thread_id": item.thread_id,
        "snippet": item.snippet,
    }


# =============================================================================
# The reproduction
# =============================================================================


async def test_a_message_scored_other_writes_no_row_anywhere(
    client: AsyncClient,
) -> None:
    """THE DEFECT, driven through the endpoint.

    A message the pipeline discards produces no ``emails`` row, no application
    and no queue entry. That is not being changed here and must not be: storing
    the subject and sender of mail the product decided *not* to file is exactly
    what ``apps/web/app/(app)/privacy/page.tsx`` promises it does not do. What
    is being changed is that the absence is now COUNTED.
    """

    from sqlalchemy import text

    from jobtracker.database import get_session

    resp = await client.post(
        "/gmail/sync", json={"items": [_as_dict(_noise())]}, headers=HEADERS
    )
    assert resp.status_code == 200, resp.text

    async with get_session() as session:
        for table in ("emails", "applications"):
            count = (await session.exec(text(f"select count(*) from {table}"))).one()[0]
            assert count == 0, (
                f"precondition for this whole file: a discarded message leaves no "
                f"{table} row, and {count} were written"
            )

    body = resp.json()
    assert body["scanned"] == 1
    assert body["classified"] == 1
    assert body["reached_nothing"] == 1, (
        "the message left no row, so the count is the only trace of it there "
        "can be. Without this number the sync has looked at a message and has "
        "no way to say so."
    )


async def test_a_discarded_message_and_a_quiet_mailbox_now_read_differently(
    client: AsyncClient,
) -> None:
    """THE REPRODUCTION, stated as the contrast that made #422 undiagnosable.

    Before this change the two responses below were identical except for
    ``scanned`` — and ``scanned`` is a bare count of what was read, which says
    nothing about whether anything survived it. ``created=0, updated=0,
    dropped=0, needs_review=0`` was the answer both to "we threw your
    application away" and to "you have no new mail".

    Every field that existed before is asserted EQUAL here, deliberately. That
    is what makes the one field that differs the finding rather than noise, and
    it is what fails if a future change starts distinguishing the two cases
    somewhere else and this number is quietly dropped as redundant.
    """

    discarded = await client.post(
        "/gmail/sync", json={"items": [_as_dict(_noise())]}, headers=HEADERS
    )
    quiet = await client.post("/gmail/sync", json={"items": []}, headers=HEADERS)
    assert discarded.status_code == quiet.status_code == 200

    a, b = discarded.json(), quiet.json()

    for field in (
        "created",
        "updated",
        "applications",
        "purged",
        "needs_review",
        "dropped",
        "removed",
        "filed",
        "queued",
    ):
        assert a[field] == b[field], (
            f"{field} tells the two runs apart, which is not what this assertion "
            "is for — it exists to show that everything the product used to "
            "report was blind to the difference"
        )

    assert a["reached_nothing"] == 1
    assert b["reached_nothing"] == 0
    assert a["reached_nothing"] != b["reached_nothing"], (
        "a sync that read a message and discarded it must not answer the same "
        "sentence as a sync that read nothing"
    )


# =============================================================================
# Every counter, in both directions
# =============================================================================


async def test_filed_counts_a_message_on_a_card_and_reads_zero_without_one() -> None:
    assert _ledger_over([_filed()]).filed == 1
    assert _ledger_over([_noise(), _dropped()]).filed == 0, (
        "a counter that never reads zero reports that a sync happened, not that "
        "anything was filed"
    )


async def test_queued_counts_a_message_in_the_review_queue_and_reads_zero_without_one() -> None:
    assert _ledger_over([_queued()]).queued == 1
    assert _ledger_over([_filed(), _noise()]).queued == 0


async def test_dropped_counts_a_floored_lifecycle_verdict_and_reads_zero_without_one() -> None:
    assert _ledger_over([_dropped()]).dropped == 1
    assert _ledger_over([_filed(), _queued(), _noise()]).dropped == 0, (
        "ordinary noise is not a drop; if it counted, every sync of a real "
        "mailbox would report hundreds and the number would mean nothing"
    )


async def test_reached_nothing_counts_ignored_mail_and_reads_zero_when_all_is_placed() -> None:
    """The number #422 is actually about, and the half that is easy to get wrong.

    A scan in which every message is filed, queued or named as dropped must
    report ZERO here. Without that assertion ``reached_nothing`` could be
    ``classified`` — always non-zero, always useless.
    """

    assert _ledger_over([_noise()]).reached_nothing == 1
    assert _ledger_over([_filed(), _queued(), _dropped()]).reached_nothing == 0


async def test_classified_counts_the_scan_and_reads_zero_on_an_empty_one() -> None:
    assert _ledger_over([_filed(), _noise()]).classified == 2
    assert _ledger_over([]).classified == 0
    assert p.EMPTY_LEDGER.classified == 0 and p.EMPTY_LEDGER.closes


# =============================================================================
# The partition
# =============================================================================


async def test_the_partition_closes_over_a_scan_holding_all_four_shapes() -> None:
    """``classified == filed + queued + dropped + reached_nothing``, exactly."""

    ledger = _ledger_over([_filed(), _queued(), _dropped(), _noise()])

    assert (ledger.classified, ledger.filed, ledger.queued, ledger.dropped,
            ledger.reached_nothing) == (4, 1, 1, 1, 1)
    assert ledger.closes


async def test_closes_can_be_false() -> None:
    """THE DIRECTIONAL CONTROL. A property that cannot fail checks nothing.

    ``reached_nothing`` is computed as a set difference, so a ledger built by
    :func:`pipeline.ledger_for_scan` closes by construction — which is the
    design, and which also means the assertions above would all still pass if
    ``closes`` were ``return True``. This is the case that says otherwise.
    """

    wrong = p.ScanLedger(classified=10, filed=1, queued=1, dropped=1, reached_nothing=1)
    assert not wrong.closes


async def test_a_message_cannot_be_counted_in_two_buckets() -> None:
    """Disjointness is the assumption closure rests on, so it is asserted too.

    The interesting case is UNPLACEABLE mail: a gated confirmation at an
    employer already holding several applications clears the precision gate but
    is promoted into the review queue instead of being guessed onto a card. It
    is the one shape where a message is reachable from both routing functions,
    and ``roll_up_applications`` excludes exactly what
    ``unplaceable_message_ids`` returns — so it must be queued and not filed,
    never both.
    """

    unplaceable = _item(
        "unplaceable-1",
        "interview",
        "no-reply@greenhouse.io",
        "Interview with Vantor",
        0.95,
        snippet="Let's talk.",
    )
    items = [unplaceable, _filed()]
    known_multi = frozenset({"vantor"})

    rolled = p.roll_up_applications(items, known_multi)
    dropped: list[p.DroppedVerdict] = []
    review = p.collect_review_items(items, dropped, known_multi)
    ledger = p.ledger_for_scan(items, rolled, review, dropped)

    assert unplaceable.message_id in p.unplaceable_message_ids(items, known_multi)
    assert (ledger.classified, ledger.filed, ledger.queued) == (2, 1, 1)
    assert ledger.closes


async def test_the_partition_closes_over_the_adversarial_corpus() -> None:
    """THE POSITIVE CONTROL, at a scale hand-built shapes cannot reach.

    Four shapes chosen by the author to land in four buckets prove very little
    about disjointness: they were chosen. The independent corpus is 17k messages
    built to break the pipeline — quoted history, conditional explainers,
    verdicts past the body cap, relay noise, hostile text — and every one of
    them must still land in exactly one bucket.

    Asserted as a PROPERTY and not as numbers. The corpus grows, and pinning
    ``filed == 13314`` here would make this file fail whenever a family is added,
    which is not what it is watching for.
    """

    from tests.corpus_independent import generate, harness

    items = [harness._item(v) for v in harness.classify_all(generate.generate())]
    assert len(items) > 1000, "sanity: the corpus generator produced a corpus"

    rolled = p.roll_up_applications(items)
    dropped: list[p.DroppedVerdict] = []
    review = p.collect_review_items(items, dropped)

    filed = {m.message_id for r in rolled for m in r.messages}
    queued = {r.message_id for r in review}
    floored = {d.message_id for d in dropped}
    assert not (filed & queued), sorted(filed & queued)[:5]
    assert not (filed & floored), sorted(filed & floored)[:5]
    assert not (queued & floored), sorted(queued & floored)[:5]

    ledger = p.ledger_for_scan(items, rolled, review, dropped)
    assert ledger.classified == len(items)
    assert ledger.closes
    assert ledger.reached_nothing > 0, (
        "if a corpus this adversarial left nothing unplaced, the bucket would "
        "be unreachable and this whole file would be measuring a number that "
        "cannot occur"
    )


# =============================================================================
# Why the partition closes over ``classified`` and not over ``scanned``
# =============================================================================


async def test_a_scan_can_read_more_messages_than_it_classifies() -> None:
    """``scanned`` is the outer number, and it is honest that it does not close.

    ``_classify_messages`` skips the user's OWN sent mail before a
    ``PipelineItem`` exists — a message you wrote is not an update about you —
    so a scan that reads two messages can hand the pipeline one. Partitioning
    over ``scanned`` would therefore report a message in no bucket at all, which
    is the failure this file is about, arriving by a different door.
    """

    from jobtracker.cloud import gmail_oauth as g

    class _Verdict:
        def __init__(self) -> None:
            from jobtracker.database.models import EmailCategory

            self.category = EmailCategory.OTHER
            self.confidence = 0.1
            self.method = "rules"

    class _Classifier:
        async def classify(self, subject: str, snippet: str, sender: str) -> _Verdict:
            return _Verdict()

    def _msg(message_id: str, sender: str) -> SimpleNamespace:
        return SimpleNamespace(
            message_id=message_id,
            thread_id=f"th-{message_id}",
            subject="Following up",
            snippet="Hello again.",
            sender_email=sender,
            sender_name=None,
            received_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        )

    read = [_msg("theirs", "careers@example.test"), _msg("mine", GMAIL_ADDRESS)]
    items = await g._classify_messages(read, _Classifier(), p, None, GMAIL_ADDRESS)

    assert len(read) == 2 and len(items) == 1, (
        "precondition: the owner's own message is skipped before it becomes an "
        "item, which is what makes scanned and classified different numbers"
    )
    assert _ledger_over(items).classified == 1


async def test_a_server_scan_stores_the_scans_count_and_the_pipelines_apart(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE ENDPOINT SEAM, and it needed its own test to be covered.

    The unit test above proves ``record_gmail_sync_success`` writes whatever
    ``scanned`` it is handed. It says nothing about whether the HANDLER hands it
    the right thing: dropping the argument at the call site falls back to
    ``ledger.classified``, and on the relay path — which every other test here
    uses — the two are equal, so that mutation passed 122 tests. Only a
    SERVER-side scan can tell them apart, so only a server-side scan closes it.

    Two messages are read from Gmail and one of them is the owner's own, which
    ``_classify_messages`` skips before an item exists. ``scanned`` must say two
    and ``classified`` must say one, on the response AND in the row.
    """

    _install_gmail_stubs(
        monkeypatch,
        full_messages=[
            _applied_msg("m-theirs"),
            # The owner writing to a company. Job-search outreach classifies as
            # ``applied`` on text that genuinely reads like an application,
            # which is why the guard is structural rather than textual.
            _msg(
                "m-mine",
                subject="Application for Software Engineer",
                sender=GMAIL_ADDRESS,
                snippet="Please find my application attached.",
                day=2,
            ),
        ],
    )
    await _connect_gmail(USER_A)

    body = (await client.post("/gmail/sync", json={}, headers=HEADERS)).json()
    assert body["scanned"] == 2, body
    assert body["classified"] == 1, (
        "the owner's own message was read and never routed; counting it as "
        "classified would put it in a bucket it never reached"
    )
    assert body["scanned"] > body["classified"]

    row = (await _sync_rows(USER_A))[0]
    assert row.last_scanned == 2
    assert row.last_classified == 1
    assert row.last_scanned > row.last_classified, (
        "the stored row must keep the two apart as well; collapsing them hides "
        "every message a scan read and never handed to the pipeline"
    )


# =============================================================================
# The durable half
# =============================================================================


async def test_the_ledger_survives_the_response_in_sync_state(
    client: AsyncClient,
) -> None:
    """The number has to outlive the tab that requested it.

    Whoever diagnoses "I synced and got nothing" is reading Postgres days after
    the response was discarded, which is where #422 found nothing at all. So the
    same ledger is written beside ``last_sync_at`` — and read back here from the
    row rather than from the response, because a test that only re-read the
    response would pass with the column never written.
    """

    await _connect_gmail(USER_A)

    resp = await client.post(
        "/gmail/sync",
        json={"items": [_as_dict(i) for i in (_filed(), _queued(), _dropped(), _noise())]},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text

    rows = await _sync_rows(USER_A)
    assert len(rows) == 1, "test setup: one Gmail sync_state row for the user"
    row = rows[0]

    assert row.last_scanned == 4
    assert row.last_classified == 4
    assert row.last_filed == 1
    assert row.last_queued == 1
    assert row.last_dropped == 1
    assert row.last_reached_nothing == 1
    assert (
        row.last_filed + row.last_queued + row.last_dropped + row.last_reached_nothing
        == row.last_classified
    ), "the accounting must close on disk too, or the row cannot be reasoned from"


async def test_the_stored_row_and_the_response_cannot_disagree(
    client: AsyncClient,
) -> None:
    """Two readers, one number — the recurring defect in this codebase.

    Both surfaces are assigned from one ``ScanLedger``. This is the assertion
    that fails if someone re-derives either side independently.
    """

    await _connect_gmail(USER_A)
    body = (
        await client.post(
            "/gmail/sync",
            json={
                "items": [
                    _as_dict(i)
                    for i in (
                        _filed(1),
                        _queued(1), _queued(2),
                        _dropped(1), _dropped(2), _dropped(3),
                        _noise(1), _noise(2), _noise(3), _noise(4),
                    )
                ]
            },
            headers=HEADERS,
        )
    ).json()

    row = (await _sync_rows(USER_A))[0]
    assert (row.last_classified, row.last_filed, row.last_queued, row.last_dropped,
            row.last_reached_nothing) == (
        body["classified"],
        body["filed"],
        body["queued"],
        body["dropped"],
        body["reached_nothing"],
    )
    # FOUR DIFFERENT NON-ZERO NUMBERS, and that is the whole design of this
    # scan. An equality between two zeroes is satisfied by a field hard-coded to
    # zero, and an equality between two ONES is satisfied by a field assigned
    # from its neighbour — ``filed=ledger.queued`` passed a version of this test
    # in which both happened to be 1. Distinct counts make both mutations
    # visible.
    assert (
        body["classified"],
        body["filed"],
        body["queued"],
        body["dropped"],
        body["reached_nothing"],
    ) == (10, 1, 2, 3, 4), body


async def test_last_scanned_is_the_scans_number_and_not_the_pipelines(
    cloud_app: Any,
) -> None:
    """A same-typed swap that no end-to-end test here can catch.

    On the relay path ``scanned`` and ``classified`` are equal by construction —
    the client sends items and each one is an item — so writing
    ``last_scanned = ledger.classified`` passes every test above. It is still
    wrong: on a SERVER scan the two differ by the owner's own mail, and storing
    the pipeline's number under the scan's name would hide exactly the messages
    that were read and never routed. Called directly, with the two deliberately
    unequal, because that is the only place the difference exists.
    """

    from jobtracker.cloud.sync_state import record_gmail_sync_success
    from jobtracker.database import get_session
    from jobtracker.database.connection import user_id_scope

    uid = _uuid.UUID(USER_A)
    ledger = p.ScanLedger(
        classified=3, filed=1, queued=0, dropped=0, reached_nothing=2
    )
    with user_id_scope(uid):
        async with get_session() as session:
            state = await record_gmail_sync_success(
                session, uid, account_email=GMAIL_ADDRESS, ledger=ledger, scanned=9
            )
            await session.commit()

    assert state.last_scanned == 9, (
        "the scan read nine messages and handed three to the pipeline; the "
        "stored row must say nine"
    )
    assert state.last_classified == 3


async def test_status_says_null_before_a_sync_and_zero_after_a_quiet_one(
    client: AsyncClient,
) -> None:
    """NULL and 0 are different answers and must stay different.

    ``null`` means no sync has recorded a ledger — every row predating revision
    ``a3f7d21c60be``, and any account whose only syncs failed. ``0`` means a
    sync ran and read nothing. Collapsing them turns "we have never looked" into
    "we looked and your mailbox was empty", which is the confusion this issue is
    about, restated one layer up.
    """

    await _connect_gmail(USER_A)

    before = (await client.get("/auth/gmail/status", headers=HEADERS)).json()
    assert before["connected"] is True
    assert before["last_scanned"] is None
    assert before["last_reached_nothing"] is None

    await client.post("/gmail/sync", json={"items": []}, headers=HEADERS)

    after = (await client.get("/auth/gmail/status", headers=HEADERS)).json()
    assert after["last_scanned"] == 0
    assert after["last_classified"] == 0
    assert after["last_reached_nothing"] == 0


async def test_status_reports_what_the_last_sync_looked_at(
    client: AsyncClient,
) -> None:
    """The read-back that makes the state diagnosable without a psql session."""

    await _connect_gmail(USER_A)
    await client.post(
        "/gmail/sync",
        json={"items": [_as_dict(i) for i in (_filed(), _dropped(), _noise())]},
        headers=HEADERS,
    )

    status = (await client.get("/auth/gmail/status", headers=HEADERS)).json()
    assert status["last_classified"] == 3
    assert status["last_filed"] == 1
    assert status["last_dropped"] == 1
    assert status["last_reached_nothing"] == 1
    assert status["last_queued"] == 0


async def test_the_ledger_is_counts_and_never_message_metadata() -> None:
    """The privacy constraint, asserted on the shape rather than trusted.

    A ledger that named what it ignored would be storing subjects and senders
    for mail the product decided NOT to file — the one thing
    ``apps/web/app/(app)/privacy/page.tsx`` publishes a promise about. Every
    field on the ledger, and every column it writes, is an integer.
    """

    from jobtracker.database.models import SyncState

    ledger = _ledger_over([_filed(), _dropped(), _noise()])
    assert all(isinstance(v, int) for v in vars(ledger).values()), vars(ledger)

    stored = [n for n in SyncState.model_fields if n.startswith("last_") and n != "last_sync_at"]
    assert stored, "sanity: the ledger columns exist to be checked"
    for name in stored:
        annotation = SyncState.model_fields[name].annotation
        assert annotation in (int, type(None)) or "int" in str(annotation), (
            f"sync_state.{name} is {annotation}; the ledger stores counts only"
        )
