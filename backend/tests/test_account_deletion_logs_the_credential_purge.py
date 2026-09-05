"""Deleting an account must emit a `secret_access` record for the credentials it destroys.

Why this file exists
--------------------

`docs/casa/SECRET-ACCESS-POLICY.md` §3.1 is the pack's compensating control for
the limb §3.2 cannot close: "every access to a stored user credential is
logged." That claim was true for every path through
``jobtracker/credentials/cloud.py`` and false for the one path that *destroys*
the credential — the account-deletion purge (issue #757).

``delete_account`` deletes ``user_credentials`` with a bulk
``DELETE ... WHERE user_id = :id`` inside its own transaction, which goes
around the module's seven logged access functions entirely. Before this test,
the single most audit-relevant moment in an account's life — the credential
ceasing to exist — emitted ``account.deleted`` and no ``secret_access`` record
at all, while that document's `op`/`outcome` table attributed a ``clear``
record to the purge that it had never emitted. (No line number: the citations
in this repo drift, and the row is findable by its ``clear`` cell.)

What makes this test able to fail
---------------------------------

The assertion is **the record**, not the row. "The credential row is gone after
deletion" has passed since the endpoint was written (see the sibling file
``test_account_deletion_revokes_gmail.py``, which makes the same point about
Google revocation), so asserting only that is a check that cannot fail here.

Run RED against the unmodified tree before the fix landed, with
``no secret_access record with op=clear was emitted``. The only record the
endpoint produced from the credential store was
``op=read outcome=hit`` — the revocation path reading the token on the way in
— followed by ``account.deleted ... tables_cleared=9`` from the account
router's own logger.

Two things beyond the substring are pinned deliberately:

* **``record.name`` is the credential store's logger**, not the account
  router's. A test that only greps caplog for ``op=clear`` stays green if the
  record is emitted under ``jobtracker.cloud.account``, and an aggregation
  query scoped to the credential logger — which is how §3.1 tells an assessor
  to find these records — would then silently miss the destruction record.
* **The record carries no token.** This is the newest emission site in the
  access log and therefore the one most likely to be "improved" with the
  credential attached; the whole-file sweep in
  ``test_secret_access_logging.py`` does not reach this path.
"""

from __future__ import annotations

import logging
import time
import uuid as _uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "acct-del-clearlog-test-jwt-secret-at-least-32-bytes-hs256"
ENC_KEY = Fernet.generate_key().decode()
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

# Appears nowhere else in the repo. If it turns up in a record emitted by the
# deletion path, the purge's own access record is carrying the credential it
# exists to report on.
SENTINEL = "QXZZ-account-purge-sentinel-must-never-be-logged-4b2f7d"

CRED_LOGGER = "jobtracker.credentials.cloud"


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Cloud app with a JWT secret, a Fernet key and the in-memory DB.

    Patched on the live settings object rather than via ``importlib.reload``,
    for the reason spelled out at length in ``test_account_deletion_revokes_gmail
    .cloud_app``: reloading rebinds names and reddens unrelated files that
    imported a symbol at collection time.
    """

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.credentials.cloud as cloud_module
    import jobtracker.database.connection as connection_module

    assert auth_module.settings is config_module.settings, (
        "settings identity diverged before this fixture ran; a module reload in "
        "an earlier test file has broken the by-reference patching this uses"
    )

    for field, value in (
        ("deployment", "cloud"),
        ("environment", "test"),
        ("supabase_jwt_secret", JWT_SECRET),
        ("secret_encryption_key", ENC_KEY),
    ):
        monkeypatch.setattr(config_module.settings, field, value)

    # The credential store binds ``settings`` at import; if an earlier file's
    # reload left it holding a different object, the Fernet key set above would
    # be invisible to it and the save below would fail for an unrelated reason.
    monkeypatch.setattr(cloud_module.settings, "secret_encryption_key", ENC_KEY)

    connection_module._engine = None

    from jobtracker.database import init_db
    from jobtracker.main_cloud import app

    await init_db()

    yield app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


@pytest.fixture(autouse=True)
def _never_call_google(monkeypatch: pytest.MonkeyPatch) -> None:
    """The transport seam, stubbed. Nothing here may reach the network."""

    import jobtracker.cloud.gmail_oauth as gmail_module

    async def _fake_revoke(token: str) -> bool:
        return True

    monkeypatch.setattr(gmail_module, "_revoke_at_google", _fake_revoke)


async def _connect_gmail(user_id: str) -> None:
    """Store an encrypted Gmail token for ``user_id``. Never contacts Google."""

    from jobtracker.credentials.cloud import save_gmail_credentials
    from jobtracker.credentials.types import GmailCredentials
    from jobtracker.database.connection import user_id_scope

    uid = _uuid.UUID(user_id)
    with user_id_scope(uid):
        saved = await save_gmail_credentials(
            uid,
            GmailCredentials(
                access_token=SENTINEL,
                refresh_token=f"refresh-{SENTINEL}",
                token_expiry=datetime.utcnow() + timedelta(hours=1),
                email="user-a@example.test",
                scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            ),
        )
    assert saved, "test setup: Gmail credential save must succeed"


def _access_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "secret_access" in r.getMessage()]


def _haystacks(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every emitted record rendered three ways.

    ``record.args`` is the load-bearing one: the module logs with lazy ``%s``
    formatting, so a value handed to the call as an argument never appears in
    ``record.msg``.
    """

    out: list[str] = []
    for r in caplog.records:
        out.append(str(r.msg))
        out.append(repr(r.args))
        out.append(r.getMessage())
    return out


async def test_account_deletion_emits_a_clear_record_for_the_credential_purge(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The gate. RED before the fix: the purge emitted no ``op=clear`` at all."""

    caplog.set_level(logging.DEBUG)
    await _connect_gmail(USER_A)
    caplog.clear()

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True

    # POSITIVE CONTROL on the INSTRUMENT: caplog only sees records that
    # propagate to root, so "captured nothing" is the likely way an absence
    # assertion passes for no reason.
    assert caplog.records, "caplog captured nothing — this test proves nothing"
    assert _access_records(caplog), (
        "no secret_access record was emitted by the deletion at all; the "
        f"records present were {sorted({r.name for r in caplog.records})}"
    )

    clears = [r for r in _access_records(caplog) if "op=clear" in r.getMessage()]
    assert len(clears) == 1, (
        "no secret_access record with op=clear was emitted by DELETE /account. "
        "The purge destroys `user_credentials` with a bulk DELETE, so the "
        "credential ceases to exist without the access log recording it — the "
        "exact claim docs/casa/SECRET-ACCESS-POLICY.md §3.1 makes. Records "
        f"seen: {[r.getMessage() for r in _access_records(caplog)]}"
    )

    record = clears[0]
    message = record.getMessage()

    # The record belongs to the credential store, not the account router: §3.1
    # tells an assessor these records live under one logger name.
    assert record.name == CRED_LOGGER, (
        "the clear record was emitted under "
        f"{record.name!r}; an aggregation scoped to {CRED_LOGGER!r} — which is "
        "how the policy document says to find these — would miss it"
    )
    assert record.levelno == logging.INFO, record.levelname
    assert f"user_id={USER_A}" in message, message
    assert "kind=all" in message, message
    assert "key_id=None" in message, message
    assert "outcome=deleted" in message, message

    # POSITIVE CONTROL on the SUBJECT: a credential genuinely existed and was
    # genuinely destroyed. Without this, the record above could be reporting a
    # purge that had nothing to purge.
    from jobtracker.credentials.cloud import get_gmail_credentials
    from jobtracker.database.connection import user_id_scope

    with user_id_scope(_uuid.UUID(USER_A)):
        assert await get_gmail_credentials(_uuid.UUID(USER_A)) is None

    # And the newest emission site carries no token.
    for haystack in _haystacks(caplog):
        assert SENTINEL not in haystack, (
            f"the plaintext token reached a log record: {haystack[:300]}"
        )
        assert ENC_KEY not in haystack, f"the Fernet key reached a log record: {haystack[:300]}"


async def test_the_clear_record_is_emitted_even_with_nothing_stored(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Unconditional, matching the convention the policy document discloses.

    §3.1 states there is no ``absent`` outcome: both delete paths issue the
    ``DELETE`` and log ``deleted`` without checking whether a row existed,
    because distinguishing the two would cost a ``SELECT`` round trip for a log
    field. The purge is the same statement and gets the same treatment, so the
    document's own exactness note stays true of every emission site rather than
    of five of six.
    """

    caplog.set_level(logging.DEBUG)

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    clears = [r for r in _access_records(caplog) if "op=clear" in r.getMessage()]
    assert len(clears) == 1, [r.getMessage() for r in _access_records(caplog)]
    assert "outcome=deleted" in clears[0].getMessage()
