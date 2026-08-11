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
from datetime import datetime
from typing import Any

from sqlalchemy import delete as sa_delete
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
) -> SyncState:
    """Stamp a successful sync and (optionally) advance the history cursor.

    ``history_id=None`` leaves any stored cursor **untouched** rather than
    clearing it: a sync whose ``getProfile`` failed, or one that merely
    persisted client-supplied items, still happened — it just cannot claim to
    have advanced the mailbox baseline.

    Flushes but does not commit; the caller owns the transaction so the cursor
    lands in the same unit of work as the rest of its bookkeeping.
    """

    state = await _upsert(session, user_id, account_email)
    state.last_sync_at = datetime.utcnow()
    state.status = SyncStatus.IDLE.value
    state.error_message = None
    if history_id:
        state.gmail_history_id = str(history_id)
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
