"""Tests for the cloud Gmail web-OAuth + read/classify router (issue C5).

These exercise the security-critical seams of the flow **without ever
talking to Google**:

- ``/auth/gmail/authorize`` builds a correct least-privilege consent URL
  and binds the flow to the caller via a signed ``state``.
- ``/auth/gmail/callback`` rejects a forged/absent ``state`` and bounces
  to the web app with ``?gmail=error`` — never a 500, never a token leak.
- ``/auth/gmail/status`` reports configured/connected honestly.
- ``/gmail/inbox`` classifies a *stubbed* batch of messages and returns
  verdict metadata only (no bodies), 409-ing when Gmail is not connected.
- Auth is enforced (401 without a bearer token).
- A missing Google client secret degrades to 503, not 500.

The real Google token exchange and message fetch are the two functions we
monkeypatch; everything else is the genuine code path.
"""

from __future__ import annotations

import importlib
import time
import urllib.parse
from typing import Any, AsyncIterator

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "gmail-c5-test-jwt-secret-at-least-32-bytes-long-hs256"
ENC_KEY = Fernet.generate_key().decode()  # valid Fernet key; also signs state
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "https://api.example.test/auth/gmail/callback"
WEB_APP_URL = "https://web.example.test"


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Cloud app configured with Gmail OAuth env + in-memory DB.

    Mirrors the proven reload sequence in ``test_user_id_scoping`` and adds
    the Gmail OAuth env vars plus a reload of ``jobtracker.cloud.gmail_oauth``
    so the router binds to the freshly-reloaded settings.
    """

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", ENC_KEY)
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("JOBTRACKER_GMAIL_OAUTH_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("JOBTRACKER_WEB_APP_URL", WEB_APP_URL)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    # Rebind the cloud credential store's ``settings`` global to the reloaded
    # config so ``secret_encryption_key`` (Fernet + state signing) is seen even
    # when an earlier test file imported this module against a keyless settings.
    import jobtracker.credentials.cloud as cred_cloud_module

    importlib.reload(cred_cloud_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.cloud.gmail_oauth as gmail_module

    importlib.reload(gmail_module)

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)

    from jobtracker.database import init_db

    await init_db()

    yield main_cloud_module.app

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None

    monkeypatch.undo()
    importlib.reload(config_module)


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(
        transport=transport, base_url="http://cloud-test", follow_redirects=False
    ) as c:
        yield c


async def test_status_configured_but_not_connected(client: AsyncClient) -> None:
    resp = await client.get(
        "/auth/gmail/status",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"configured": True, "connected": False, "email": None}


async def test_status_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/auth/gmail/status")
    assert resp.status_code == 401


async def test_authorize_returns_least_privilege_consent_url(client: AsyncClient) -> None:
    resp = await client.get(
        "/auth/gmail/authorize",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/auth")

    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    # Least-privilege: exactly the readonly scope, nothing broader.
    assert params["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert params["client_id"] == [CLIENT_ID]
    assert params["redirect_uri"] == [REDIRECT_URI]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]

    # The state must be a valid signed token bound to the caller.
    state = params["state"][0]
    decoded = pyjwt.decode(
        state,
        ENC_KEY,
        algorithms=["HS256"],
        audience="jobtracker:gmail-oauth-state",
    )
    assert decoded["sub"] == USER_A


async def test_authorize_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/auth/gmail/authorize")
    assert resp.status_code == 401


async def test_callback_forged_state_redirects_error_not_500(client: AsyncClient) -> None:
    resp = await client.get(
        "/auth/gmail/callback",
        params={"code": "irrelevant", "state": "not-a-valid-token"},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{WEB_APP_URL}/settings?gmail=error"


async def test_callback_missing_code_redirects_error(client: AsyncClient) -> None:
    # Even with a *valid* state, no code means we cannot exchange — error.
    from jobtracker.cloud.gmail_oauth import _sign_state
    import uuid

    state = _sign_state(uuid.UUID(USER_A))
    resp = await client.get("/auth/gmail/callback", params={"state": state})
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{WEB_APP_URL}/settings?gmail=error"


async def test_callback_provider_error_redirects_error(client: AsyncClient) -> None:
    resp = await client.get(
        "/auth/gmail/callback",
        params={"error": "access_denied", "state": "x"},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{WEB_APP_URL}/settings?gmail=error"


async def test_inbox_not_connected_returns_409(client: AsyncClient) -> None:
    resp = await client.get(
        "/gmail/inbox",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 409, resp.text


async def test_inbox_classifies_stubbed_messages(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Gmail fetch stubbed, real messages flow through the classifier."""

    from datetime import datetime

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import CloudGmailMessage

    async def _fake_fetch(user_id, **_kwargs):
        return [
            CloudGmailMessage(
                message_id="m1",
                thread_id="t1",
                subject="Update on your application to Acme",
                sender_name="Acme Recruiting",
                sender_email="no-reply@lever.co",
                snippet=(
                    "Unfortunately, after careful consideration we have decided "
                    "to move forward with other candidates for this position."
                ),
                received_at=datetime.utcnow(),
            ),
            CloudGmailMessage(
                message_id="m2",
                thread_id="t2",
                subject="Your weekly newsletter",
                sender_name="Jobboard Digest",
                sender_email="newsletter@jobboard.com",
                snippet="Recommended jobs you may be interested in. Unsubscribe anytime.",
                received_at=datetime.utcnow(),
            ),
        ]

    monkeypatch.setattr(gmail_client_module, "fetch_recent_messages", _fake_fetch)

    resp = await client.get(
        "/gmail/inbox",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is True
    assert body["scanned"] == 2
    assert len(body["verdicts"]) == 2

    by_id = {v["message_id"]: v for v in body["verdicts"]}
    # The rejection language is a strong rules hit.
    assert by_id["m1"]["category"] == "rejection"
    # No body content is ever returned — only verdict metadata.
    assert set(by_id["m1"].keys()) == {
        "message_id",
        "subject",
        "sender_email",
        "sender_name",
        "category",
        "confidence",
        "method",
        "needs_review",
    }
    # Newsletter/digest content is guarded to OTHER.
    assert by_id["m2"]["category"] == "other"


async def test_disconnect_when_not_connected_is_idempotent(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/gmail/disconnect",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked"] is False


async def test_authorize_503_when_client_secret_missing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-configured deployment degrades to an honest 503, not a 500."""

    import jobtracker.cloud.gmail_oauth as gmail_module

    monkeypatch.setattr(gmail_module.settings, "google_oauth_client_secret", None)

    resp = await client.get(
        "/auth/gmail/authorize",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 503, resp.text
