"""A grant the user took back must be written down — and only a real one.

When a user revokes Gmail access at myaccount.google.com the refresh fails and
``load_valid_credentials`` correctly degrades to "reconnect required". Nothing
was ever recorded, so ``cron._gmail_sync_position`` kept answering
``has_gmail=True`` off the mere existence of the credential row: that user was
picked as a candidate every fifteen minutes forever, spent one of the ~4 slots a
45 s run can afford on a sync that could only fail, and pushed a user whose
mailbox still works out of the batch.

THE DANGEROUS HALF IS THE FALSE POSITIVE. Google being briefly unreachable must
NOT read as "the user revoked access" — that would tell someone with a perfectly
good mailbox to reconnect, and would do it on the strength of a network blip.
So the split is asserted in both directions, and the transient cases outnumber
the permanent one here on purpose.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta

import pytest
from google.auth.exceptions import RefreshError, TransportError
from sqlmodel import select

from jobtracker.cloud import gmail_client
from jobtracker.credentials.cloud import KIND_GMAIL
from jobtracker.database import get_session, init_db
from jobtracker.database.models import UserCredential

USER = _uuid.UUID("5e8c2f41-9a37-4d60-b812-6c3f0e59a742")


@pytest.fixture(autouse=True)
async def _fresh_db():
    await init_db()
    async with get_session() as session:
        for row in (await session.exec(select(UserCredential))).all():
            await session.delete(row)
        await session.commit()
    yield


async def _seed_credential() -> None:
    async with get_session() as session:
        session.add(
            UserCredential(
                user_id=USER, kind=KIND_GMAIL, ciphertext=b"not-a-real-token"
            )
        )
        await session.commit()


async def _revoked_at():
    async with get_session() as session:
        row = (
            await session.exec(
                select(UserCredential).where(
                    UserCredential.user_id == USER, UserCredential.kind == KIND_GMAIL
                )
            )
        ).first()
    if row is None:
        return None
    row = row[0] if hasattr(row, "__getitem__") else row
    return row.revoked_at


# ---------------------------------------------------------------------------
# The classifier: which refresh failures are permanent?
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        RefreshError("invalid_grant: Token has been expired or revoked."),
        RefreshError("('invalid_grant: Bad Request', {'error': 'invalid_grant'})"),
        RefreshError("unauthorized_client"),
    ],
)
def test_a_revoked_grant_is_recognised_as_permanent(exc):
    assert gmail_client._is_permanently_revoked(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        # The whole false-positive family. None of these says anything about
        # whether the user still consents.
        TransportError("Failed to retrieve http://oauth2.googleapis.com/token"),
        ConnectionError("Connection reset by peer"),
        TimeoutError("timed out"),
        OSError("[Errno 65] No route to host"),
        RefreshError("Internal Server Error"),
        RefreshError("rateLimitExceeded"),
        RuntimeError("something else entirely"),
    ],
)
def test_a_transient_failure_is_not_treated_as_a_revocation(exc):
    """THE ONE THAT MATTERS. A blip must never disconnect a working account."""

    assert gmail_client._is_permanently_revoked(exc) is False


def test_a_transport_error_that_merely_mentions_the_word_is_not_a_revocation():
    """The string alone is not the test — a URL could carry any of these words.

    Pins that the classifier requires the RefreshError *type* as well, so a
    transport failure whose message happens to contain "invalid_grant" (a
    request URL, a proxy error page) cannot disconnect anybody.
    """

    assert (
        gmail_client._is_permanently_revoked(
            TransportError("POST /token?hint=invalid_grant failed")
        )
        is False
    )


# ---------------------------------------------------------------------------
# The write, and the way back out of it
# ---------------------------------------------------------------------------


async def test_marking_sets_revoked_at_on_the_row():
    await _seed_credential()
    assert await _revoked_at() is None

    await gmail_client.mark_gmail_credential_revoked(USER)

    assert await _revoked_at() is not None


async def test_marking_keeps_the_row_rather_than_deleting_it():
    """MARKED, NOT DELETED — the UI needs the address to say what to reconnect."""

    await _seed_credential()
    await gmail_client.mark_gmail_credential_revoked(USER)

    async with get_session() as session:
        rows = (
            await session.exec(
                select(UserCredential).where(UserCredential.user_id == USER)
            )
        ).all()

    assert len(rows) == 1, "the credential row was destroyed, not marked"


async def test_marking_a_user_with_no_credential_is_harmless():
    """Best-effort bookkeeping on a path already returning None. Must not raise."""

    await gmail_client.mark_gmail_credential_revoked(USER)


async def test_reconnecting_clears_the_mark():
    """THE ANTI-WEDGE. Without this a reconnected user stays invisible forever.

    ``save_gmail_credentials`` is the only evidence that could ever exist that
    the grant is good again, so it has to be what clears the flag — otherwise
    the sole way back would be an operator with database access, for a state
    the user can reach by themselves in one click.
    """

    from jobtracker.credentials.cloud import _upsert_credential

    await _seed_credential()
    await gmail_client.mark_gmail_credential_revoked(USER)
    assert await _revoked_at() is not None

    async with get_session() as session:
        await _upsert_credential(
            session, user_id=USER, kind=KIND_GMAIL, ciphertext=b"a-fresh-token"
        )
        await session.commit()

    assert await _revoked_at() is None


# ---------------------------------------------------------------------------
# What the mark actually buys: the cron stops spending a slot
# ---------------------------------------------------------------------------


async def test_a_revoked_user_drops_out_of_the_cron_candidate_list():
    """The point of the whole exercise.

    Non-vacuity: the SAME user is asserted syncable first, so this cannot pass
    because the fixture failed to seed anything.

    This is also the half ``gmail_sync_enrollment`` deliberately cannot answer.
    Revocation marks ``user_credentials.revoked_at`` and leaves the enrollment
    row standing — enrollment is "a credential was stored", not "it still
    works" — so the cron's per-user probe is what has to notice. Asserted
    against the probe rather than the enrollment table for exactly that reason.
    """

    from jobtracker.cloud.cron import _probe_sync_position
    from jobtracker.cloud.sync_state import GMAIL_ACCOUNT_TYPE
    from jobtracker.database.connection import get_engine
    from jobtracker.database.models import SyncState

    await _seed_credential()
    async with get_session() as session:
        session.add(
            SyncState(
                user_id=USER,
                account_type=GMAIL_ACCOUNT_TYPE,
                account_email="owner@example.com",
                last_sync_at=datetime.utcnow() - timedelta(hours=3),
            )
        )
        await session.commit()

    async def _probe() -> bool:
        # The probe runs on the caller's connection now — the cron holds one
        # open across the whole enumeration (issue #294).
        async with get_engine().connect() as conn:
            has_gmail, _ = await _probe_sync_position(conn, USER)
            await conn.rollback()
        return has_gmail

    assert await _probe() is True, "fixture problem: this user was never syncable"

    await gmail_client.mark_gmail_credential_revoked(USER)

    assert await _probe() is False, (
        "a revoked user still counts as having a connected mailbox, so the "
        "schedule keeps spending a candidate slot on them every run"
    )
