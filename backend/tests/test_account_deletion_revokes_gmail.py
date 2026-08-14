"""Deleting an account must revoke the Gmail grant at Google, not just drop it.

Why this file exists
--------------------

``AccountSection`` told the user that deleting their account "revokes any
connected Gmail". It did not (issue #215). ``DELETE /account`` deleted the
``user_credentials`` row and stopped there, so Applied stayed listed under the
user's Google third-party access with a refresh token that had been valid the
moment we dropped our only copy of it — and dropping our copy is precisely what
makes it unrevokable afterwards. The two sensitive Gmail exits disagreed, and
the more destructive one did less: **Disconnect Gmail** revoked at Google,
**Delete account** did not.

What makes these tests able to fail
-----------------------------------

The assertion is **the call**, not the row. "The credential row is gone after
deletion" already passed before the fix — ``UserCredential`` has been in
``_DELETION_ORDER`` since the endpoint was written — so a test asserting only
that is a check that cannot fail here, and asserting it is what let the gap
ship in the first place. Every test below therefore pins what was said to
Google, using the *transport* (``_revoke_at_google``) as the seam, which is the
one place in the codebase that actually speaks Google's revocation protocol.

Verified by mutation rather than by reading: deleting the
``revoke_stored_gmail_grant`` call from ``cloud/account.py`` turns
``test_account_deletion_revokes_the_gmail_grant_at_google`` red, and removing
either failure guard reddens its own test below.

The three "revocation fails" cases are not padding. Revocation is best-effort
*by design* — a grant left standing at Google is a real harm the user can still
fix at myaccount.google.com/permissions, whereas a 500 that refuses to delete
their account strands them with the data they asked us to destroy. That
asymmetry is a decision, so it gets a test rather than a comment alone.
"""

from __future__ import annotations

import time
import uuid as _uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "acct-del-revoke-test-jwt-secret-at-least-32-bytes-hs256"
ENC_KEY = Fernet.generate_key().decode()
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REFRESH_TOKEN = "1//fake-refresh-for-user-a"
ACCESS_TOKEN = "ya29.fake-access-for-user-a"


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

    **Deliberately does NOT use the ``importlib.reload`` sequence the older
    cloud fixtures use**, and the reason is worth stating because copying that
    sequence here is the obvious move and it is wrong.

    Reloading a module rebinds the *names* in it: after
    ``importlib.reload(jobtracker.auth.supabase_jwt)`` the module holds a brand
    new ``AuthError`` class, while any test file that did
    ``from jobtracker.auth.supabase_jwt import AuthError`` at collection time
    still holds the old one. Its ``pytest.raises(AuthError)`` then stops
    catching the exception the reloaded code raises. ``test_gmail_oauth_cloud``
    and ``test_user_id_scoping`` do exactly this and get away with it only
    because their filenames sort *after* ``test_auth_supabase_jwt``; this file
    sorts before it. Measured: the reload version of this fixture left this
    file green and turned 11 of ``test_auth_supabase_jwt``'s tests red — a
    failure that says nothing whatsoever about the code under test, and reads
    like a real auth regression.

    So the settings are patched *on the live object* instead. Every module
    binds ``settings`` by reference (``from jobtracker.config import
    settings``), nothing caches the Fernet or the JWT secret, and
    ``database_url`` is a computed property — so one ``setattr`` per field
    reaches all of them, no identity anywhere changes, and ``monkeypatch``
    undoes it exactly. This is the same technique
    ``test_auth_supabase_jwt.configured_secret`` uses.
    """

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    # The by-reference assumption above, asserted rather than trusted: if some
    # earlier file's reload left these pointing at different objects, patching
    # one would silently not reach the other and every test here would fail for
    # a reason that has nothing to do with account deletion.
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

    # `environment == "test"` now resolves `database_url` to in-memory SQLite;
    # drop the cached engine so it is rebuilt against that rather than the
    # on-disk desktop DB.
    connection_module._engine = None

    from jobtracker.database import init_db
    from jobtracker.main_cloud import app

    await init_db()

    yield app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None
    # `monkeypatch` restores the four fields itself; nothing else was touched.


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as c:
        yield c


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
                access_token=ACCESS_TOKEN,
                refresh_token=REFRESH_TOKEN,
                token_expiry=datetime.utcnow() + timedelta(hours=1),
                email="user-a@example.test",
                scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            ),
        )
    assert saved, "test setup: Gmail credential save must succeed"


async def _stored_credential(user_id: str) -> Any:
    from jobtracker.credentials.cloud import get_gmail_credentials
    from jobtracker.database.connection import user_id_scope

    uid = _uuid.UUID(user_id)
    with user_id_scope(uid):
        return await get_gmail_credentials(uid)


def _record_revocations(monkeypatch: pytest.MonkeyPatch, *, result: bool = True) -> list[str]:
    """Patch the ONE function that talks to Google, and record its argument.

    Patching the transport rather than ``revoke_stored_gmail_grant`` is
    deliberate: ``delete_account`` imports the helper at call time, so a test
    that patched the helper would be asserting against its own stub if that
    import ever became a module-level binding. ``_revoke_at_google`` is looked
    up as a module global at the moment of the call, so this interception holds
    either way — and it is also the seam ``test_gmail_oauth_cloud`` already
    uses for the disconnect path.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    seen: list[str] = []

    async def _fake_revoke(token: str) -> bool:
        seen.append(token)
        return result

    monkeypatch.setattr(gmail_module, "_revoke_at_google", _fake_revoke)
    return seen


async def test_account_deletion_revokes_the_gmail_grant_at_google(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refresh token must reach Google's revocation endpoint.

    This is the assertion the issue is about. Red before the fix: nothing in
    ``cloud/account.py`` mentioned revocation at all.
    """

    await _connect_gmail(USER_A)
    revoked = _record_revocations(monkeypatch)

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    # The call, with the caller's own refresh token — Google's revocation
    # cascades from the refresh token to its access tokens, which is why the
    # disconnect path prefers it too.
    assert revoked == [REFRESH_TOKEN]
    # And the stored copy is gone. Asserted second and deliberately: on its own
    # this passed before the fix, so it is a completeness check, not the gate.
    assert await _stored_credential(USER_A) is None


async def test_revocation_happens_while_the_token_still_exists(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordering: revoke, then delete the row — never the other way round.

    After ``user_credentials`` is purged there is no token left to revoke, so a
    revocation moved after the delete would silently become a no-op that still
    returns 200. Red when the revocation is moved below the deletion loop: the
    credential read finds nothing and Google is never called.
    """

    await _connect_gmail(USER_A)
    revoked = _record_revocations(monkeypatch)

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    assert len(revoked) == 1, "the token must still be readable when Google is called"


async def test_an_account_with_no_gmail_connected_never_calls_google(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No stored grant, no revocation attempt — and still a clean deletion."""

    revoked = _record_revocations(monkeypatch)

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    assert revoked == []


async def test_deletion_proceeds_when_google_refuses_the_revocation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Google answering non-2xx must not block the user from deleting.

    Best-effort is the decision, not an accident: an already-revoked or expired
    token makes Google answer 400 on every retry, and a deletion that refused
    on that would be permanently unavailable to the affected user.
    """

    await _connect_gmail(USER_A)
    revoked = _record_revocations(monkeypatch, result=False)

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    assert revoked == [REFRESH_TOKEN]
    assert await _stored_credential(USER_A) is None


async def test_deletion_survives_a_revocation_that_raises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transport that throws must not become a 500 on the deletion.

    ``_revoke_at_google`` promises never to raise, but the guard in
    ``delete_account`` does not take that promise on faith — the cost of being
    wrong is a user permanently unable to delete their account. Red when the
    ``try/except`` around the revocation is removed.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    async def _boom(token: str) -> bool:
        raise RuntimeError("google is on fire")

    await _connect_gmail(USER_A)
    monkeypatch.setattr(gmail_module, "_revoke_at_google", _boom)

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    assert await _stored_credential(USER_A) is None


async def test_deletion_survives_an_unreadable_stored_credential(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A credential the store cannot read must not block the deletion either.

    The real case is a rotated Fernet key: ``get_gmail_credentials`` raises
    rather than returning None, and unguarded that exception escapes as a 500
    from an endpoint whose whole job is to let a user leave.

    Two guards cover this — one in ``revoke_stored_gmail_grant`` (so the
    helper's never-raises contract holds for every caller) and one in
    ``delete_account`` (so this handler holds regardless of the helper). They
    are deliberately redundant, so this test goes red only when **both** are
    removed. Stated plainly rather than implied: removing either one alone
    leaves it green, and a reader who assumed otherwise would trust this test
    for something it does not prove.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    async def _unreadable(user_id):
        raise ValueError("Fernet key rotated; ciphertext is undecryptable")

    await _connect_gmail(USER_A)
    monkeypatch.setattr(gmail_module, "get_gmail_credentials", _unreadable)
    revoked = _record_revocations(monkeypatch)

    resp = await client.delete(
        "/account", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )

    assert resp.status_code == 200, resp.text
    assert revoked == [], "an unreadable credential has no token to send"
    assert await _stored_credential(USER_A) is None
