"""``_persist_message_refs`` may not pay one round trip per message.

THE COST IS THE ROUND TRIP, NOT THE QUERY. ``ix_emails_user_id_message_id``
serves the per-message lookup this function used to make perfectly — it is an
index-only probe on a composite index, microseconds of planner and executor
time. What it cannot make cheap is the *number* of times the function asks: one
``SELECT`` per ref, issued sequentially, each one a full function→pooler round
trip. ``database/connection.py`` measures that trip at ~13 ms in production.

A first sync scans up to ``_SYNC_DEFAULT_SCAN_TARGET`` (750) messages
(``gmail_oauth.py``), so the old shape spent on the order of ten seconds of the
serverless budget doing nothing but waiting for the network — against a cron
per-user timeout of 10 s (``cron.py``), which is why a first sync could be
cancelled by the schedule and never establish a cursor.

WHAT THIS TEST ASSERTS, AND WHY IT IS SHAPED THIS WAY
-----------------------------------------------------
Not an absolute statement count. A bare "fewer than N" passes for an O(n)
implementation the moment somebody lowers a constant, and it has to be re-tuned
every time an unrelated query moves. What matters is that the count does not
*scale with the number of messages*, so the assertion is on the SLOPE: run the
same persist at two sizes and require the difference to stay inside the bound
batching actually promises — ``ceil(n / _MESSAGE_LOOKUP_CHUNK)`` probes plus a
small constant.

An O(n) implementation fails that mechanically and cannot be tuned past it. To
be sure it does, ``test_the_gate_can_fail`` re-runs the same measurement against
a deliberately un-batched persist and asserts the bound is BREACHED — the gate
is proven able to go red in the same run that proves the code green.

Only ``SELECT``s against ``emails`` are counted. INSERTs arrive as one
``executemany`` per flush and would blur a total-statement count without saying
anything about the defect.
"""

from __future__ import annotations

import datetime
import math
import uuid as _uuid

import pytest
from sqlalchemy import event
from sqlmodel import select

from jobtracker.cloud import applications as apps
from jobtracker.cloud import pipeline as p
from jobtracker.database.models import Email

USER = _uuid.UUID("2f6a7c31-8b04-4c9e-9a1d-77e5b0c31f42")
BASE = datetime.datetime(2026, 8, 12, 9, 0)


def ref(n: int) -> p.MessageRef:
    return p.MessageRef(
        message_id=f"m-{n:05d}",
        thread_id=f"th-{n:05d}",
        subject="Thank you for applying to Acme",
        sender_email="no-reply@acme.com",
        sender_name="Acme",
        received_at=BASE + datetime.timedelta(minutes=n),
        category="applied",
        confidence=0.95,
        snippet="Software Engineer",
    )


class EmailSelectCounter:
    """Count SELECT statements issued against ``emails`` on one session."""

    def __init__(self, session):
        self._bind = session.get_bind() if hasattr(session, "get_bind") else None
        self.count = 0

    def _listener(self, conn, cursor, statement, parameters, context, executemany):
        text = " ".join(statement.split()).lower()
        if text.startswith("select") and " from emails" in text:
            self.count += 1

    def __enter__(self):
        event.listen(self._target, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *exc):
        event.remove(self._target, "before_cursor_execute", self._listener)
        return False


def _counter(session):
    """A statement counter bound to the engine behind ``session``."""

    engine = session.get_bind()
    counter = EmailSelectCounter.__new__(EmailSelectCounter)
    counter.count = 0
    counter._target = getattr(engine, "sync_engine", engine)
    return counter


async def _probes_for(session, persist, n: int, *, offset: int) -> int:
    """SELECTs against ``emails`` while persisting ``n`` fresh refs."""

    refs = [ref(offset + i) for i in range(n)]
    counter = _counter(session)
    with counter:
        await persist(session, USER, None, refs)
        await session.flush()
    return counter.count


def _bound(n: int) -> int:
    """What a batched implementation may spend on ``n`` refs.

    ``ceil(n / chunk)`` prefetch probes — the chunking is explicit, so the
    bound is expressed in terms of it rather than as a magic number — plus a
    small constant of slack for anything the function legitimately reads once
    per call.
    """

    return math.ceil(n / apps._MESSAGE_LOOKUP_CHUNK) + 2


async def _measure_slope(session, persist) -> tuple[int, int]:
    """Probe counts at n=50 and n=200, on disjoint message ids."""

    small = await _probes_for(session, persist, 50, offset=0)
    large = await _probes_for(session, persist, 200, offset=1000)
    return small, large


async def test_persisting_more_messages_does_not_cost_more_round_trips(test_session):
    """The real gate: the probe count must not scale with the message count."""

    small, large = await _measure_slope(test_session, apps._persist_message_refs)

    assert small <= _bound(50), f"n=50 issued {small} SELECTs, bound {_bound(50)}"
    assert large <= _bound(200), f"n=200 issued {large} SELECTs, bound {_bound(200)}"
    # The slope itself. Four times the messages may cost at most the extra
    # chunks they occupy.
    assert large - small <= _bound(200) - _bound(50), (
        f"quadrupling the refs cost {large - small} extra SELECTs; batching "
        f"allows {_bound(200) - _bound(50)}"
    )


async def _unbatched_persist(session, user_id, application_id, refs):
    """The shape this file exists to forbid: one SELECT per ref.

    A faithful reduction of the pre-fix loop — the per-ref lookup and the
    undated-message skip, and nothing else. It is only ever used to prove the
    measurement above can fail.
    """

    for r in refs:
        received_at = p.to_naive_utc(r.received_at)
        if received_at is None:
            continue
        (
            await session.exec(
                select(Email)
                .where(Email.user_id == user_id, Email.message_id == r.message_id)
                .limit(1)
            )
        ).first()


async def test_the_gate_can_fail(test_session):
    """PROVE THE INSTRUMENT. The same measurement, against an O(n) persist.

    Without this the green run above is not evidence: a counter that never
    increments, or a listener attached to the wrong engine, would pass every
    bound in this file while measuring nothing at all.
    """

    small, large = await _measure_slope(test_session, _unbatched_persist)

    assert small == 50, f"the counter did not see the per-ref SELECTs (saw {small})"
    assert large == 200, f"the counter did not see the per-ref SELECTs (saw {large})"
    assert large > _bound(200), "an O(n) persist slipped under the batched bound"


async def test_a_repeated_message_id_within_one_call_is_still_upserted_once(
    test_session,
):
    """Batching must not turn a duplicated id into a duplicated row.

    The old loop was protected by autoflush: the second ref's SELECT saw the
    row the first one had just added. A prefetch taken before the loop cannot
    see rows the loop itself creates, so the dedupe has to be carried in the
    map — and a regression here is a UNIQUE violation on
    ``(user_id, message_id)`` in production, not a slow query.
    """

    duplicated = [ref(7), ref(7), ref(7)]
    await apps._persist_message_refs(test_session, USER, None, duplicated)
    await test_session.flush()

    rows = (
        await test_session.exec(
            select(Email).where(Email.user_id == USER, Email.message_id == "m-00007")
        )
    ).all()
    assert len(rows) == 1


async def test_an_undated_ref_is_still_skipped(test_session):
    """The documented skip survives the rewrite.

    ``Email`` requires a receive time and this function has never fabricated
    one — ``applications.py`` states that at the ``classify_review_item``
    docstring, and a client with no date for a row is told not to offer the
    correction at all. A batched prefetch must therefore build its IN list from
    the refs that survive the skip, not from every ref handed in.
    """

    dated = ref(1)
    undated = p.MessageRef(
        message_id="m-undated",
        thread_id=None,
        subject="No date",
        sender_email="no-reply@acme.com",
        sender_name="Acme",
        received_at=None,
        category="applied",
        confidence=0.9,
        snippet="",
    )
    await apps._persist_message_refs(test_session, USER, None, [dated, undated])
    await test_session.flush()

    stored = set(
        (
            await test_session.exec(
                select(Email.message_id).where(Email.user_id == USER)
            )
        ).all()
    )
    assert stored == {"m-00001"}


@pytest.mark.parametrize("size", [1, 2, 3])
async def test_chunking_is_explicit_and_bounded(monkeypatch, test_session, size):
    """The IN list is chunked on a named constant, not on whatever fits.

    Postgres caps a statement's bind parameters at 65535. 750 ids in one
    statement is comfortably inside that, but a bound that holds only because
    today's scan target is small is not a bound. Forcing a tiny chunk size
    proves the loop really does partition the ids — and that the results of
    every chunk are merged, not just the last one's.
    """

    monkeypatch.setattr(apps, "_MESSAGE_LOOKUP_CHUNK", size)

    refs = [ref(2000 + i) for i in range(7)]
    await apps._persist_message_refs(test_session, USER, None, refs)
    await test_session.flush()

    # Second pass over the SAME ids: every one must be found by its chunk and
    # updated in place rather than inserted again.
    await apps._persist_message_refs(test_session, USER, None, refs)
    await test_session.flush()

    rows = (
        await test_session.exec(
            select(Email).where(Email.user_id == USER)
        )
    ).all()
    assert len(rows) == 7
