"""One sync per mailbox at a time — and a crashed one must not wedge the user.

Nothing stopped an authenticated account firing unlimited parallel
``POST /gmail/sync``. Each call scans up to 750 messages, so the cost of
holding the button down is Vercel function-seconds, the user's own Gmail API
quota, and N copies of the additive merge racing each other over the same rows.

``SyncState`` carried a cursor but no lease: it recorded that a sync had
FINISHED, never that one was running. ``sync_started_at`` is that record.

THE TWO WAYS A LEASE GOES WRONG, and both are tested here
----------------------------------------------------------
1. It does not actually exclude — a read-then-write in Python lets two callers
   both see "idle" and both proceed. Hence the conditional UPDATE, and hence
   :func:`test_two_concurrent_acquisitions_do_not_both_win`.
2. It excludes FOREVER. A sync killed by the 60 s function ceiling leaves the
   column set with nobody to clear it, and a lease that cannot expire locks the
   user out of their own mailbox permanently — a worse bug than the one being
   fixed. Hence the TTL, and hence
   :func:`test_an_abandoned_lease_expires_rather_than_wedging_the_user`.

The case that would have shipped broken is the third one:
:func:`test_a_first_sync_can_take_the_lease_with_no_row_at_all`. ``sync_state``
is written on SUCCESS, so a brand-new user has no row and the conditional
UPDATE matches nothing. Reading that as "someone else holds it" would 409 every
new user forever — on exactly the 750-message first sync this lease exists to
protect.
"""

from __future__ import annotations

import asyncio
import uuid as _uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from jobtracker.cloud import sync_state as ss
from jobtracker.database import get_session, init_db
from jobtracker.database.models import SyncState

USER = _uuid.UUID("8d2e4a17-6c93-4b05-9e71-3f5a0c62d418")
OTHER = _uuid.UUID("1a7b3c59-2d84-4e06-8f13-9b4c5d7e2a60")
MAILBOX = "owner@example.com"


@pytest.fixture(autouse=True)
async def _fresh_db():
    """A real (in-memory) database, since the lease IS a database property.

    Mocking the session here would test the Python around the UPDATE and not
    the UPDATE, which is the only part that can actually exclude anybody.
    """

    await init_db()
    async with get_session() as session:
        for row in (await session.exec(select(SyncState))).all():
            await session.delete(row)
        await session.commit()
    yield


async def _lease_of(user_id: _uuid.UUID, email: str = MAILBOX):
    async with get_session() as session:
        state = await ss.load_gmail_sync_state(session, user_id, email)
        return state.sync_started_at if state else None


async def test_a_first_sync_can_take_the_lease_with_no_row_at_all():
    """No sync_state row yet — the case a naive conditional UPDATE gets wrong.

    ``sync_state`` is written when a sync SUCCEEDS, so this is the state every
    brand-new user is in. If "the UPDATE matched no row" were read as "held",
    every first sync would 409 forever.
    """

    assert await _lease_of(USER) is None
    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is True
    assert await _lease_of(USER) is not None


async def test_a_second_acquisition_is_refused_while_the_first_holds_it():
    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is True
    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is False


async def test_releasing_lets_the_next_sync_through():
    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is True
    await ss.release_gmail_sync_lease(USER, MAILBOX)

    assert await _lease_of(USER) is None
    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is True


async def test_an_abandoned_lease_expires_rather_than_wedging_the_user():
    """THE ANTI-WEDGE. A crashed sync must not lock its owner out forever.

    Simulated the only way it can happen in production: the lease is taken and
    never released, because the function holding it was killed. Time is moved
    rather than waited for — a test that slept 120 s would be deleted.
    """

    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is True

    # One second inside the TTL: still held. This half is what makes the other
    # half meaningful — without it, "expired" could just mean "never worked".
    still_held = datetime.utcnow() + timedelta(
        seconds=ss._SYNC_LEASE_TTL_SECONDS - 1
    )
    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX, now=still_held) is False

    # One second past it: available again, with no operator, cron or cleanup.
    expired = datetime.utcnow() + timedelta(seconds=ss._SYNC_LEASE_TTL_SECONDS + 1)
    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX, now=expired) is True


async def test_the_lease_is_per_mailbox_not_global():
    """One user syncing must not block another. A global lock would.

    Non-vacuous: both acquisitions run against the same table in the same
    database, so this fails if the predicate ever loses its user scoping.
    """

    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is True
    assert await ss.acquire_gmail_sync_lease(OTHER, "someone-else@example.com") is True


def test_the_lease_conflict_does_not_reuse_the_not_connected_status():
    """It must answer 429, NOT 409 — and the reason is in the web app.

    409 is already spoken for on ``/gmail/sync``: it means "Gmail is not
    connected", and the frontend reads it that way in four places
    (``SyncBar.tsx`` sets ``notConnected: res.status === 409``;
    ``lib/gmail/server.ts`` maps 409 to ``{kind: "not_connected"}``). Reusing it
    for the lease would tell a user whose mailbox is working — and is being
    synced at that very moment — to go and reconnect their account.

    That collision is the COMMON case, not an edge one: ``SyncBar`` runs a
    staleness auto-sync on arrival, so landing on the dashboard and pressing
    "Sync now", or just having two tabs open, collides routinely.

    Pinned here because the natural instinct on re-reading this code is
    "a conflict is a 409" — which is true in the abstract and wrong on this
    endpoint.
    """

    from fastapi import status

    from jobtracker.cloud.gmail_oauth import SyncAlreadyRunning

    exc = SyncAlreadyRunning()

    assert exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc.status_code != status.HTTP_409_CONFLICT, (
        "409 on this endpoint means 'Gmail is not connected'; the web app "
        "would prompt a reconnect for a mailbox that is working fine"
    )
    # A client that is told to wait should be told how long.
    assert exc.headers and "Retry-After" in exc.headers


async def _seed_idle_row() -> None:
    """An existing, idle row — the steady state after any successful sync.

    The race tests run against this rather than an empty table on purpose: with
    no row, every racer takes the INSERT path and collides on
    ``uq_sync_state_user_account``, so the unique constraint would be doing the
    excluding and the conditional UPDATE would never be tested at all.
    """

    async with get_session() as session:
        session.add(
            SyncState(
                user_id=USER,
                account_type=ss.GMAIL_ACCOUNT_TYPE,
                account_email=MAILBOX,
                sync_started_at=None,
            )
        )
        await session.commit()


async def test_two_concurrent_acquisitions_do_not_both_win():
    """The race the conditional UPDATE exists to close.

    Fired together so the interleaving is real rather than argued.
    """

    await _seed_idle_row()

    results = await asyncio.gather(
        *(ss.acquire_gmail_sync_lease(USER, MAILBOX) for _ in range(8))
    )

    assert sum(results) == 1, f"{sum(results)} callers were let through, not 1"


async def _naive_acquire(user_id, account_email):
    """The implementation this file forbids: SELECT, decide in Python, UPDATE.

    A faithful reduction of the obvious version — and the `await` between the
    read and the write is not a contrivance, it is what every real network
    round trip is.
    """

    async with get_session() as session:
        state = await ss.load_gmail_sync_state(session, user_id, account_email)
        if state is not None and state.sync_started_at is not None:
            return False
        await asyncio.sleep(0)
        assert state is not None
        state.sync_started_at = datetime.utcnow()
        session.add(state)
        await session.commit()
        return True


async def test_the_race_gate_can_fail():
    """PROVE THE INSTRUMENT. The same measurement against a read-then-write.

    Without this, ``test_two_concurrent_acquisitions_do_not_both_win`` is not
    evidence: if this harness serialised the eight coroutines — an in-memory
    SQLite on a StaticPool is exactly the kind of thing that might — then
    "exactly one won" would be an artefact of the fixture and would hold for a
    lease that excludes nobody.

    Measured: the naive version lets **8 of 8** through here, the real one
    exactly 1.
    """

    await _seed_idle_row()

    results = await asyncio.gather(*(_naive_acquire(USER, MAILBOX) for _ in range(8)))

    assert sum(results) > 1, (
        "the naive read-then-write lease excluded somebody, so this harness "
        "serialises the racers and the race test above proves nothing"
    )


async def test_releasing_a_lease_nobody_holds_is_harmless():
    """Called from a ``finally``, so it must be safe on every path."""

    await ss.release_gmail_sync_lease(USER, MAILBOX)
    await ss.release_gmail_sync_lease(USER, "never-seen@example.com")


async def test_taking_the_lease_does_not_disturb_the_cursor():
    """The lease shares a row with the history cursor; it may not touch it.

    ``gmail_history_id`` and ``last_sync_at`` are what make an incremental sync
    incremental. A lease that cleared either would turn every sync into a full
    750-message scan — the exact cost this whole change set is reducing.
    """

    async with get_session() as session:
        await ss.record_gmail_sync_success(
            session, USER, account_email=MAILBOX, history_id="998877"
        )
        await session.commit()

    before = await _lease_of(USER)
    assert before is None, "a successful sync must not leave a lease held"

    assert await ss.acquire_gmail_sync_lease(USER, MAILBOX) is True
    await ss.release_gmail_sync_lease(USER, MAILBOX)

    async with get_session() as session:
        state = await ss.load_gmail_sync_state(session, USER, MAILBOX)

    assert state is not None
    assert state.gmail_history_id == "998877"
    assert state.last_sync_at is not None
