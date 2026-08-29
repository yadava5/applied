"""A grant Google already rejected must not read as a live connection.

``revoked_at`` was written faithfully (``test_revoked_grant_is_recorded.py``)
and then read by nobody. ``_fetch_credential`` selected on ``(user_id, kind)``
alone, so a revoked row came back indistinguishable from a working one:
``/auth/gmail/status`` answered ``connected: true``, Settings told the user they
were connected, and the cron — which does filter — synced nothing for them. The
user had no way to learn this and no affordance to fix it, because the UI only
offers Disconnect to someone it believes is connected.

WHY THIS FILE EXISTS AND THE EXISTING SUITE DID NOT COVER IT. Every other
backend test seeds through ``save_gmail_credentials``, whose upsert writes
``revoked_at = NULL``. Not one seeded row in the suite is revoked, so the whole
column was invisible to it and the green run said nothing about this behaviour.
The two regressions the filter can cause are therefore asserted here directly,
because nothing else in the suite would notice them:

  - Disconnect must still reach a revoked row, or the ciphertext and the
    enrollment row (a connection-cap seat) are stranded forever.
  - Account deletion must still attempt revocation on a revoked row, because
    the mark comes from a string heuristic and a LIVE grant can carry it.

Each test below is paired with the control that stops it passing vacuously.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from jobtracker.credentials.types import GmailCredentials

# Any valid Fernet key (generated once; deterministic in tests).
_TEST_FERNET_KEY = "fxHtKRWuaD2nQbNZoAzwEo9pG_Q4AoHTsWvj1_RlrZw="


@pytest.fixture
async def cloud_env(monkeypatch: pytest.MonkeyPatch):
    """Cloud credential backend with encryption configured + a live DB."""

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.credentials.cloud as cloud_module
    import jobtracker.database.connection as connection_module

    # Every settings instance the request path holds, de-duplicated by object
    # identity -- not ``importlib.reload(jobtracker.config)``, which minted a
    # new one and left the verifier holding the old (#582).
    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module, cloud_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "secret_encryption_key", _TEST_FERNET_KEY)

    from jobtracker.database import init_db

    await init_db()

    yield cloud_module


@pytest.fixture
def user_id() -> uuid.UUID:
    # Fresh per test: conftest's in-memory SQLite engine is a session singleton.
    return uuid.uuid4()


@pytest.fixture
def credentials() -> GmailCredentials:
    return GmailCredentials(
        access_token="access-token-value",
        refresh_token="refresh-token-value",
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        email="someone@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


async def _mark_revoked(cloud_module, user_id: uuid.UUID) -> None:
    """Do to the row exactly what `gmail_client` does when Google says no."""

    from jobtracker.database import get_session
    from jobtracker.database.models import UserCredential

    async with get_session() as session:
        row = (
            await session.exec(
                select(UserCredential).where(
                    UserCredential.user_id == user_id,
                    UserCredential.kind == cloud_module.KIND_GMAIL,
                )
            )
        ).first()
        row = row[0] if hasattr(row, "__getitem__") else row
        row.revoked_at = datetime.utcnow()
        session.add(row)
        await session.commit()


async def _revoked_at(cloud_module, user_id: uuid.UUID):
    from jobtracker.database import get_session
    from jobtracker.database.models import UserCredential

    async with get_session() as session:
        row = (
            await session.exec(
                select(UserCredential).where(
                    UserCredential.user_id == user_id,
                    UserCredential.kind == cloud_module.KIND_GMAIL,
                )
            )
        ).first()
        if row is None:
            return "no row"
        row = row[0] if hasattr(row, "__getitem__") else row
        return row.revoked_at


# ---------------------------------------------------------------------------
# The bug itself
# ---------------------------------------------------------------------------


async def test_a_revoked_grant_is_not_returned(cloud_env, user_id, credentials):
    """The read that `/auth/gmail/status` turns into `connected`."""

    await cloud_env.save_gmail_credentials(user_id, credentials)
    await _mark_revoked(cloud_env, user_id)

    assert await cloud_env.get_gmail_credentials(user_id) is None, (
        "a grant Google has rejected still reads as a live credential — "
        "this is what made /auth/gmail/status answer connected:true"
    )


async def test_a_live_grant_is_still_returned(cloud_env, user_id, credentials):
    """CONTROL. Without this, deleting the whole read passes the test above."""

    await cloud_env.save_gmail_credentials(user_id, credentials)

    stored = await cloud_env.get_gmail_credentials(user_id)
    assert stored is not None, "the filter is eating live credentials"
    assert stored.email == credentials.email


async def test_has_gmail_credentials_agrees(cloud_env, user_id, credentials):
    await cloud_env.save_gmail_credentials(user_id, credentials)
    assert await cloud_env.has_gmail_credentials(user_id) is True

    await _mark_revoked(cloud_env, user_id)
    assert await cloud_env.has_gmail_credentials(user_id) is False


# ---------------------------------------------------------------------------
# The two things the filter could break. Neither is covered anywhere else.
# ---------------------------------------------------------------------------


async def test_disconnect_still_reaches_a_revoked_row(
    cloud_env, user_id, credentials, monkeypatch
):
    """Disconnect is CLEANUP, so it must see what it is cleaning up.

    Take the default read in `gmail_disconnect` and this row — plus the
    enrollment row holding a connection-cap seat — is stranded permanently:
    the delete sits behind a `stored is None` early return.
    """

    from jobtracker.cloud import gmail_oauth

    await cloud_env.save_gmail_credentials(user_id, credentials)
    await _mark_revoked(cloud_env, user_id)

    monkeypatch.setattr(gmail_oauth, "_revoke_at_google", lambda _token: _true())

    response = await gmail_oauth.gmail_disconnect(user_id=user_id)

    assert response.message != "Gmail was not connected.", (
        "disconnect took the not-connected early exit on a revoked grant, "
        "stranding the ciphertext and the enrollment row forever"
    )
    assert await _revoked_at(cloud_env, user_id) == "no row", (
        "the credential row survived a disconnect"
    )


async def test_account_deletion_still_revokes_a_marked_grant(
    cloud_env, user_id, credentials, monkeypatch
):
    """`revoked_at` is a GUESS, so deletion must not trust it and skip Google.

    The mark is written from a string match over Google's error response, and
    that heuristic's own tests call the false positive the dangerous half. A
    live grant carrying a wrong mark must still be revoked when the account is
    deleted, or it outlives the account (#215).
    """

    from jobtracker.cloud import gmail_oauth

    await cloud_env.save_gmail_credentials(user_id, credentials)
    await _mark_revoked(cloud_env, user_id)

    seen: list[str] = []

    async def _fake_revoke(token: str) -> bool:
        seen.append(token)
        return True

    monkeypatch.setattr(gmail_oauth, "_revoke_at_google", _fake_revoke)

    assert await gmail_oauth.revoke_stored_gmail_grant(user_id) is True
    assert seen == [credentials.refresh_token], (
        "account deletion skipped Google-side revocation because the row "
        "carried a mark that may well be wrong"
    )


# ---------------------------------------------------------------------------
# The silent un-revoke the filter closes
# ---------------------------------------------------------------------------


async def test_a_token_refresh_cannot_silently_unrevoke(
    cloud_env, user_id, credentials
):
    """`save_gmail_credentials` clears `revoked_at` — that is for RECONNECTING.

    `update_gmail_access_token` reads, mutates and writes back down the same
    path, so before the read was filtered a refresh restored a dead grant to
    "connected" with no consent screen anywhere behind it.
    """

    await cloud_env.save_gmail_credentials(user_id, credentials)
    await _mark_revoked(cloud_env, user_id)
    marked_at = await _revoked_at(cloud_env, user_id)

    updated = await cloud_env.update_gmail_access_token(
        user_id, "a-brand-new-access-token", datetime.utcnow() + timedelta(hours=1)
    )

    assert updated is False, "a refresh resurrected a revoked grant"
    assert await _revoked_at(cloud_env, user_id) == marked_at, (
        "the refresh cleared revoked_at with no fresh consent behind it"
    )


async def test_reconnecting_still_clears_the_mark(cloud_env, user_id, credentials):
    """The one thing that IS allowed to un-revoke: a real reconnect.

    Pairs with the test above as its control — together they say the mark is
    cleared by consent and by nothing else.
    """

    await cloud_env.save_gmail_credentials(user_id, credentials)
    await _mark_revoked(cloud_env, user_id)
    assert await cloud_env.get_gmail_credentials(user_id) is None

    # What the OAuth callback does on a reconnect.
    await cloud_env.save_gmail_credentials(user_id, credentials)

    assert await _revoked_at(cloud_env, user_id) is None
    assert await cloud_env.get_gmail_credentials(user_id) is not None, (
        "a user who reconnected is still locked out — no self-service way back"
    )


async def _true() -> bool:
    return True
