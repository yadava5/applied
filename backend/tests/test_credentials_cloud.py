"""Round-trip tests for ``jobtracker.credentials.cloud`` (issue #21, C4).

Every test runs against the in-memory SQLite test DB (via conftest's
``JOBTRACKER_ENVIRONMENT=test`` + ``init_db()``). The cloud backend
is dialect-aware: ``_upsert_credential`` uses a Postgres-only
ON CONFLICT path when the bind is Postgres, and falls back to a
SELECT-then-UPDATE-or-INSERT emulation on SQLite. These tests exercise
the SQLite fallback; the Postgres path is covered by a later issue
(C8 test_cloud marker) with a real Supabase dev project.
"""

from __future__ import annotations

import importlib
import uuid
from datetime import datetime, timedelta

import pytest

from jobtracker.credentials.types import GmailCredentials, ICloudCredentials


# Any valid Fernet key (generated once; deterministic in tests).
_TEST_FERNET_KEY = "fxHtKRWuaD2nQbNZoAzwEo9pG_Q4AoHTsWvj1_RlrZw="


@pytest.fixture
async def cloud_env(monkeypatch: pytest.MonkeyPatch):
    """Configure settings for the cloud credential backend + initialize DB."""

    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", _TEST_FERNET_KEY)

    import jobtracker.config as config_module

    importlib.reload(config_module)

    # Re-import the cloud module *after* settings reload so its
    # module-level ``from jobtracker.config import settings`` picks up
    # the new singleton.
    import jobtracker.credentials.cloud as cloud_module

    importlib.reload(cloud_module)

    from jobtracker.database import init_db

    await init_db()

    yield cloud_module

    monkeypatch.undo()
    importlib.reload(config_module)


@pytest.fixture
def user_id() -> uuid.UUID:
    # Fresh UUID per test so rows from one test don't bleed into the
    # next (conftest's in-memory SQLite engine is a session singleton).
    return uuid.uuid4()


@pytest.fixture
def other_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def gmail_credentials() -> GmailCredentials:
    return GmailCredentials(
        access_token="at-abc",
        refresh_token="rt-xyz",
        token_expiry=datetime(2026, 5, 1, 12, 0, 0),
        email="user@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


@pytest.fixture
def icloud_credentials() -> ICloudCredentials:
    return ICloudCredentials(
        email="user@icloud.com",
        app_password="aaaa-bbbb-cccc-dddd",
    )


async def test_gmail_round_trip(
    cloud_env, user_id: uuid.UUID, gmail_credentials: GmailCredentials
) -> None:
    assert await cloud_env.save_gmail_credentials(user_id, gmail_credentials) is True
    retrieved = await cloud_env.get_gmail_credentials(user_id)

    assert retrieved is not None
    assert retrieved.access_token == gmail_credentials.access_token
    assert retrieved.refresh_token == gmail_credentials.refresh_token
    assert retrieved.email == gmail_credentials.email
    assert retrieved.scopes == gmail_credentials.scopes
    # Datetime survived the JSON round-trip.
    assert retrieved.token_expiry == gmail_credentials.token_expiry


async def test_icloud_round_trip(
    cloud_env, user_id: uuid.UUID, icloud_credentials: ICloudCredentials
) -> None:
    assert await cloud_env.save_icloud_credentials(user_id, icloud_credentials) is True
    retrieved = await cloud_env.get_icloud_credentials(user_id)

    assert retrieved is not None
    assert retrieved.email == icloud_credentials.email
    assert retrieved.app_password == icloud_credentials.app_password


async def test_gmail_upsert_overwrites(
    cloud_env, user_id: uuid.UUID, gmail_credentials: GmailCredentials
) -> None:
    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)

    rotated = GmailCredentials(
        access_token="new-token",
        refresh_token=gmail_credentials.refresh_token,
        token_expiry=gmail_credentials.token_expiry + timedelta(hours=1),
        email=gmail_credentials.email,
        scopes=gmail_credentials.scopes,
    )
    await cloud_env.save_gmail_credentials(user_id, rotated)

    retrieved = await cloud_env.get_gmail_credentials(user_id)
    assert retrieved is not None
    assert retrieved.access_token == "new-token"
    assert retrieved.token_expiry == rotated.token_expiry


async def test_cross_user_isolation(
    cloud_env,
    user_id: uuid.UUID,
    other_user_id: uuid.UUID,
    gmail_credentials: GmailCredentials,
) -> None:
    """User A's Gmail credentials MUST NOT be visible to user B.

    This is enforced by the application-level ``WHERE user_id = :uid``
    filter in ``_fetch_credential``. RLS is additional defence in
    depth on Postgres (covered by C8 test_cloud suite).
    """

    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)

    other = await cloud_env.get_gmail_credentials(other_user_id)
    assert other is None

    # User A still sees their own row.
    mine = await cloud_env.get_gmail_credentials(user_id)
    assert mine is not None


async def test_has_helpers(
    cloud_env,
    user_id: uuid.UUID,
    gmail_credentials: GmailCredentials,
    icloud_credentials: ICloudCredentials,
) -> None:
    assert await cloud_env.has_gmail_credentials(user_id) is False
    assert await cloud_env.has_icloud_credentials(user_id) is False

    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)
    assert await cloud_env.has_gmail_credentials(user_id) is True
    assert await cloud_env.has_icloud_credentials(user_id) is False

    await cloud_env.save_icloud_credentials(user_id, icloud_credentials)
    assert await cloud_env.has_icloud_credentials(user_id) is True


async def test_delete_and_clear(
    cloud_env,
    user_id: uuid.UUID,
    gmail_credentials: GmailCredentials,
    icloud_credentials: ICloudCredentials,
) -> None:
    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)
    await cloud_env.save_icloud_credentials(user_id, icloud_credentials)

    await cloud_env.delete_gmail_credentials(user_id)
    assert await cloud_env.get_gmail_credentials(user_id) is None
    assert await cloud_env.get_icloud_credentials(user_id) is not None

    await cloud_env.clear_all_credentials(user_id)
    assert await cloud_env.get_icloud_credentials(user_id) is None


async def test_update_gmail_access_token(
    cloud_env, user_id: uuid.UUID, gmail_credentials: GmailCredentials
) -> None:
    await cloud_env.save_gmail_credentials(user_id, gmail_credentials)

    new_expiry = gmail_credentials.token_expiry + timedelta(hours=2)
    assert (
        await cloud_env.update_gmail_access_token(user_id, "refreshed-at", new_expiry)
        is True
    )

    retrieved = await cloud_env.get_gmail_credentials(user_id)
    assert retrieved is not None
    assert retrieved.access_token == "refreshed-at"
    assert retrieved.token_expiry == new_expiry
    # Other fields unchanged.
    assert retrieved.refresh_token == gmail_credentials.refresh_token
    assert retrieved.email == gmail_credentials.email


async def test_update_access_token_missing_is_noop(
    cloud_env, user_id: uuid.UUID
) -> None:
    """Refreshing a non-existent credential returns False, doesn't create."""

    now = datetime.utcnow()
    assert await cloud_env.update_gmail_access_token(user_id, "t", now) is False
    assert await cloud_env.has_gmail_credentials(user_id) is False


async def test_missing_encryption_key_raises(
    monkeypatch: pytest.MonkeyPatch, user_id: uuid.UUID
) -> None:
    """When SECRET_ENCRYPTION_KEY is unset, save/get raise explicitly.

    This guards against silent ciphertext writes under a null key —
    operators should get a loud failure at the first request.
    """

    monkeypatch.delenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", raising=False)

    import jobtracker.config as config_module

    importlib.reload(config_module)

    import jobtracker.credentials.cloud as cloud_module

    importlib.reload(cloud_module)

    from jobtracker.database import init_db

    await init_db()

    creds = GmailCredentials(
        access_token="a",
        refresh_token="r",
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        email="x@example.com",
        scopes=[],
    )
    with pytest.raises(cloud_module.CredentialEncryptionError):
        await cloud_module.save_gmail_credentials(user_id, creds)

    # Restore cleanly for later tests in the session.
    importlib.reload(config_module)
    importlib.reload(cloud_module)
