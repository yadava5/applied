"""The cloud sync cursor — *when* a user last synced, and *how far*.

Background
----------
``sync_state`` has existed since the initial schema and carries exactly the
columns an incremental Gmail sync needs (``last_sync_at``, ``gmail_history_id``,
``status``, ``error_message``), but only the **desktop** ``SyncService`` ever
wrote to it. In the cloud build the table was dead: every ``POST /gmail/sync``
recomputed a fixed 12-month window from scratch and nothing recorded that the
sync had happened. That is the "I have to re-sync again and again" bug — the
product genuinely had no memory of a sync.

This module is the cloud writer/reader for that row. It is deliberately tiny and
holds no ``settings`` global (the cloud test fixture reloads config and rebinds
modules; a module-level ``settings`` snapshot would go stale), so it only ever
needs the models plus a session.

Isolation
---------
Every query is scoped by ``user_id`` *and* keyed on the linked
``account_email``, matching the posture of ``cloud/applications.py``. Postgres
row-level security is enabled and FORCEd on ``sync_state`` (migration
``a8d4ec5fba26``), so an unscoped query would fail closed rather than leak; the
explicit filter is the first of the two layers, not the only one.

Cursor safety
-------------
Two rules make an advanced cursor incapable of losing mail:

1. The ``historyId`` is captured from ``users.getProfile`` **before** the scan
   reads anything, so mail arriving mid-scan lands after the cursor and is
   picked up next run.
2. The cursor is only ever written **after** the scanned mail has been
   persisted. A crash anywhere earlier leaves the cursor where it was, which
   costs one more full scan — never a skipped message.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import or_
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from jobtracker.database import get_session
from jobtracker.database.models import EmailSource, SyncState, SyncStatus

logger = logging.getLogger(__name__)

# ``account_type`` stores the enum *value*, not its name (see the SyncState
# model's comment and the desktop writer in ``services/sync.py``).
GMAIL_ACCOUNT_TYPE = EmailSource.GMAIL.value


async def load_gmail_sync_state(
    session: Any, user_id: uuid.UUID, account_email: str
) -> SyncState | None:
    """Return the caller's Gmail sync row for ``account_email``, or ``None``."""

    return (
        await session.exec(
            select(SyncState).where(
                SyncState.user_id == user_id,
                SyncState.account_type == GMAIL_ACCOUNT_TYPE,
                SyncState.account_email == account_email,
            )
        )
    ).first()


async def read_gmail_sync_state(
    user_id: uuid.UUID, account_email: str
) -> SyncState | None:
    """Session-owning convenience read, for the status endpoint."""

    async with get_session() as session:
        return await load_gmail_sync_state(session, user_id, account_email)


async def _upsert(
    session: Any,
    user_id: uuid.UUID,
    account_email: str,
) -> SyncState:
    """Fetch-or-create the caller's row. Flushed, not committed."""

    state = await load_gmail_sync_state(session, user_id, account_email)
    if state is None:
        state = SyncState(
            user_id=user_id,
            account_type=GMAIL_ACCOUNT_TYPE,
            account_email=account_email,
        )
    return state


async def record_gmail_sync_success(
    session: Any,
    user_id: uuid.UUID,
    *,
    account_email: str,
    history_id: str | None = None,
    ledger: Any | None = None,
    scanned: int | None = None,
) -> SyncState:
    """Stamp a successful sync and (optionally) advance the history cursor.

    ``history_id=None`` leaves any stored cursor **untouched** rather than
    clearing it: a sync whose ``getProfile`` failed, or one that merely
    persisted client-supplied items, still happened — it just cannot claim to
    have advanced the mailbox baseline.

    ``ledger`` is a :class:`~jobtracker.cloud.pipeline.ScanLedger` — WHERE EVERY
    MESSAGE THIS RUN LOOKED AT ENDED UP. It is what makes "did you see my mail?"
    answerable from the database rather than only from a response that is gone
    when the tab closes; #422's four Microsoft applications produced no row of
    any kind, so nothing on disk distinguished a discarded message from one that
    never arrived. ``scanned`` rides beside it because it is the one number the
    pipeline cannot know: how many messages the SCAN read, before
    ``_classify_messages`` skipped the user's own sent mail.

    Both are optional and both are ALL-OR-NOTHING: a caller that passes neither
    leaves the stored ledger exactly as it was, rather than half-overwriting it
    with a fresh ``last_sync_at`` and stale counts beside it. There is no such
    caller today — every success on this path has a ledger — and the default
    exists so a future one cannot invent a wrong reading by omission.

    Typed ``Any`` for the same reason nothing else in this module holds a
    ``settings`` global: importing ``cloud.pipeline`` here would pull the whole
    classifier chain into a module that deliberately owns nothing but models and
    a session.

    Flushes but does not commit; the caller owns the transaction so the cursor
    lands in the same unit of work as the rest of its bookkeeping.
    """

    state = await _upsert(session, user_id, account_email)
    state.last_sync_at = datetime.utcnow()
    state.status = SyncStatus.IDLE.value
    state.error_message = None
    if history_id:
        state.gmail_history_id = str(history_id)
    if ledger is not None:
        state.last_scanned = scanned if scanned is not None else ledger.classified
        state.last_classified = ledger.classified
        state.last_filed = ledger.filed
        state.last_queued = ledger.queued
        state.last_dropped = ledger.dropped
        state.last_reached_nothing = ledger.reached_nothing
    session.add(state)
    await session.flush()
    return state


async def record_gmail_sync_failure(
    session: Any,
    user_id: uuid.UUID,
    *,
    account_email: str,
    error_message: str,
) -> SyncState:
    """Record that a sync failed, WITHOUT advancing anything.

    ``last_sync_at`` deliberately keeps its old value: the UI renders it as
    "last synced N minutes ago", which must mean the last *successful* sync. The
    cursor is likewise left where it was, so the retry re-covers the same
    ground.
    """

    state = await _upsert(session, user_id, account_email)
    state.status = SyncStatus.ERROR.value
    state.error_message = error_message[:500]
    session.add(state)
    await session.flush()
    return state


async def note_gmail_sync_failure(
    user_id: uuid.UUID, account_email: str, error_message: str
) -> None:
    """Best-effort failure record on its OWN session. Never raises.

    The session that hit the error is rolled back and unusable, and this is
    bookkeeping: if it too fails, the original exception is what the caller must
    see, so this swallows and logs by type.
    """

    try:
        async with get_session() as session:
            await record_gmail_sync_failure(
                session,
                user_id,
                account_email=account_email,
                error_message=error_message,
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — must never mask the real failure
        logger.warning(
            "Could not record sync failure for user_id=%s (%s).",
            user_id,
            type(exc).__name__,
        )


# How long a lease may be held before another sync is allowed to break it.
#
# Sized ABOVE every ceiling a sync can legitimately hit: Vercel gives
# ``api/index.py`` ``maxDuration: 60`` and the scan's own budget is 30 s, so a
# sync that is still running at 120 s is not running — the function that owned
# it is gone. Too short and two real syncs overlap, which is the thing being
# prevented; too long and a crash locks the user out of their own mailbox for
# that whole window. This is the shortest value that cannot pre-empt a live
# sync.
_SYNC_LEASE_TTL_SECONDS = 120.0


async def acquire_gmail_sync_lease(
    user_id: uuid.UUID, account_email: str, *, now: datetime | None = None
) -> bool:
    """Take the in-flight lease for this mailbox. ``True`` if we got it.

    Nothing else stopped a user hammering ``POST /gmail/sync``: each call is a
    scan of up to ``_SYNC_DEFAULT_SCAN_TARGET`` messages, so unlimited
    parallel calls burn Vercel
    function-seconds and the user's own Gmail quota while racing N copies of the
    additive merge over the same rows.

    THE TEST AND THE WRITE ARE ONE STATEMENT. A ``SELECT`` followed by an
    ``UPDATE`` in Python is precisely the race being closed — two requests both
    read "idle", both write "mine", both proceed. So the condition lives in the
    ``WHERE`` clause and the verdict is the row count: exactly one of two
    concurrent callers can match a row whose lease is free, because the other's
    UPDATE waits on that row's lock and then re-evaluates the predicate against
    the committed value.

    EXPIRY IS PART OF THE PREDICATE, not a separate sweep. A sync killed
    mid-flight — the 60 s function ceiling, an OOM, a deploy — leaves
    ``sync_started_at`` set with nobody to clear it, and a lease that cannot
    expire would lock that user out of their own mailbox permanently. A lease
    older than ``_SYNC_LEASE_TTL_SECONDS`` is therefore simply available, which
    means recovery needs no operator, no cron and no cleanup job.

    A FIRST SYNC HAS NO ROW. ``sync_state`` is written when a sync *succeeds*,
    so a brand-new user's conditional UPDATE matches nothing — and treating "no
    row" as "someone else holds it" would 409 every new user forever, on exactly
    the full-window scan path this lease exists to protect. So a miss is
    disambiguated: no row at all means the mailbox is idle and the row is
    created holding the lease. Two racers can reach that insert together; the
    loser trips ``uq_sync_state_user_account`` and retries the UPDATE, where it
    correctly loses to the winner's lease.
    """

    moment = now or datetime.utcnow()
    cutoff = moment - timedelta(seconds=_SYNC_LEASE_TTL_SECONDS)

    async with get_session() as session:
        if await _take_lease(session, user_id, account_email, moment, cutoff):
            await session.commit()
            return True

        # Nobody to update: either the row does not exist, or the lease is
        # genuinely held. Only the first is ours to fix.
        if await load_gmail_sync_state(session, user_id, account_email) is not None:
            await session.commit()
            return False

        session.add(
            SyncState(
                user_id=user_id,
                account_type=GMAIL_ACCOUNT_TYPE,
                account_email=account_email,
                sync_started_at=moment,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # Another request created the row between our SELECT and our
            # INSERT. It holds the lease unless it has already expired, and
            # the conditional UPDATE is the only thing that can tell.
            await session.rollback()
        else:
            return True

    async with get_session() as session:
        won = await _take_lease(session, user_id, account_email, moment, cutoff)
        await session.commit()
        return won


async def _take_lease(
    session: Any,
    user_id: uuid.UUID,
    account_email: str,
    moment: datetime,
    cutoff: datetime,
) -> bool:
    """The conditional UPDATE. ``True`` when it claimed a row."""

    result = await session.exec(
        sa_update(SyncState)
        .where(
            SyncState.user_id == user_id,
            SyncState.account_type == GMAIL_ACCOUNT_TYPE,
            SyncState.account_email == account_email,
            or_(
                SyncState.sync_started_at.is_(None),
                SyncState.sync_started_at < cutoff,
            ),
        )
        .values(sync_started_at=moment)
    )
    return bool(result.rowcount)


async def release_gmail_sync_lease(user_id: uuid.UUID, account_email: str) -> None:
    """Hand the lease back. Never raises.

    Called from a ``finally``, so it runs on the failure paths too — including
    the ``HTTPException`` re-raise, which does NOT record a sync failure and
    would otherwise leave the lease held for a full TTL after a 400 the user
    could fix and retry in seconds.

    Its own session: the request's may be rolled back and unusable by the time
    this runs. Swallow-and-log for the same reason
    :func:`note_gmail_sync_failure` does — a lease that fails to release costs
    one TTL, while an exception raised out of a ``finally`` would REPLACE the
    error the caller needs to see.
    """

    try:
        async with get_session() as session:
            await session.exec(
                sa_update(SyncState)
                .where(
                    SyncState.user_id == user_id,
                    SyncState.account_type == GMAIL_ACCOUNT_TYPE,
                    SyncState.account_email == account_email,
                )
                .values(sync_started_at=None)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — must never mask the real failure
        logger.warning(
            "Could not release the sync lease for user_id=%s (%s); it will "
            "expire on its own in %ss.",
            user_id,
            type(exc).__name__,
            _SYNC_LEASE_TTL_SECONDS,
        )


async def clear_gmail_sync_state(user_id: uuid.UUID) -> None:
    """Drop the caller's Gmail cursor — called on disconnect.

    A ``historyId`` is only meaningful against the mailbox that issued it.
    Keeping it across a disconnect/reconnect would let a re-linked (possibly
    different) account inherit a foreign cursor, and an incremental sync from a
    foreign baseline is a correctness bug, not a performance one. Deletes all
    Gmail rows for the user, so it also cleans up an address they no longer use.
    """

    async with get_session() as session:
        await session.exec(
            sa_delete(SyncState).where(
                SyncState.user_id == user_id,
                SyncState.account_type == GMAIL_ACCOUNT_TYPE,
            )
        )
        await session.commit()
