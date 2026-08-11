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

import base64
import hashlib
import importlib
import time
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "gmail-c5-test-jwt-secret-at-least-32-bytes-long-hs256"
ENC_KEY = Fernet.generate_key().decode()  # valid Fernet key; also signs state
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

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
    # Sync state rides along on this endpoint (see GmailStatusResponse); with no
    # connection there is nothing to report and no DB read happens.
    assert body == {
        "configured": True,
        "connected": False,
        "email": None,
        "last_sync_at": None,
        "has_cursor": False,
        "sync_status": None,
        "sync_error": None,
    }


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
    # Least-privilege: exactly the readonly scope, nothing broader — and no
    # incremental-scope merging that could widen the token response.
    assert params["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert "include_granted_scopes" not in params
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

    # Stateless PKCE (the live "Connect Gmail → invalid_grant" regression):
    # the consent URL's S256 challenge must be derived from the exact
    # verifier the state carries (Fernet-encrypted), because the callback
    # runs in a different serverless invocation and can only recover the
    # verifier from the state itself.
    assert params["code_challenge_method"] == ["S256"]
    verifier = Fernet(ENC_KEY).decrypt(decoded["cv"].encode()).decode()
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert params["code_challenge"] == [expected_challenge]


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
    import uuid

    from jobtracker.cloud.gmail_oauth import _generate_code_verifier, _sign_state

    state = _sign_state(uuid.UUID(USER_A), _generate_code_verifier())
    resp = await client.get("/auth/gmail/callback", params={"state": state})
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{WEB_APP_URL}/settings?gmail=error"


async def test_callback_state_without_verifier_redirects_error(
    client: AsyncClient,
) -> None:
    """A signed state missing the encrypted PKCE verifier is invalid.

    Covers the deploy-rollover edge: a state minted by a pre-PKCE build
    must bounce to ``?gmail=error`` (retry with a fresh state), never 500
    and never attempt a verifier-less exchange.
    """

    now = int(time.time())
    legacy_state = pyjwt.encode(
        {
            "sub": USER_A,
            "aud": "jobtracker:gmail-oauth-state",
            "iat": now,
            "exp": now + 300,
        },
        ENC_KEY,
        algorithm="HS256",
    )
    resp = await client.get(
        "/auth/gmail/callback", params={"code": "any", "state": legacy_state}
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{WEB_APP_URL}/settings?gmail=error"


async def test_callback_round_trip_hands_pkce_verifier_to_exchange(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """authorize → callback carries the SAME verifier the challenge used.

    This is the regression test for the live bug: the deployed flow
    autogenerated a PKCE verifier inside the authorize invocation's
    ``Flow`` and lost it before the callback invocation, so every real
    exchange failed with ``invalid_grant``. Here we walk the full HTTP
    round trip (only Google itself is stubbed) and assert the callback
    redeems the code with the exact verifier whose S256 hash went to
    Google — then lands on ``?gmail=connected`` with the token stored.
    """

    from datetime import datetime, timedelta

    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.credentials.cloud import get_gmail_credentials
    from jobtracker.credentials.types import GmailCredentials

    # Leg 1: mint the consent URL; capture challenge + state.
    resp = await client.get(
        "/auth/gmail/authorize",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    params = urllib.parse.parse_qs(
        urllib.parse.urlparse(resp.json()["authorization_url"]).query
    )
    challenge = params["code_challenge"][0]
    state = params["state"][0]

    # Leg 2: Google redirects back. Stub only the Google-facing exchange.
    captured: dict[str, str] = {}

    def _fake_exchange(code: str, code_verifier: str) -> GmailCredentials:
        captured["code"] = code
        captured["code_verifier"] = code_verifier
        return GmailCredentials(
            access_token="ya29.fake",
            refresh_token="1//fake-refresh",
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            email="owner@example.test",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )

    monkeypatch.setattr(gmail_module, "_exchange_code", _fake_exchange)

    resp = await client.get(
        "/auth/gmail/callback",
        params={"code": "auth-code-from-google", "state": state},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{WEB_APP_URL}/settings?gmail=connected"

    # The verifier that reached the exchange hashes to the challenge that
    # went to Google — PKCE survived the stateless round trip.
    assert captured["code"] == "auth-code-from-google"
    derived = (
        base64.urlsafe_b64encode(
            hashlib.sha256(captured["code_verifier"].encode()).digest()
        )
        .decode()
        .rstrip("=")
    )
    assert derived == challenge

    # And the credentials are genuinely stored (encrypted) for the user.
    import uuid

    stored = await get_gmail_credentials(uuid.UUID(USER_A))
    assert stored is not None
    assert stored.email == "owner@example.test"


async def test_callback_save_failure_redirects_error_not_connected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token that exchanged but failed to persist must NOT claim success.

    ``save_gmail_credentials`` swallows storage errors into ``False``;
    the callback must treat that as a failed connection (``?gmail=error``)
    rather than bouncing to ``?gmail=connected`` while ``/status`` says
    disconnected.
    """

    from datetime import datetime, timedelta

    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.credentials.types import GmailCredentials

    resp = await client.get(
        "/auth/gmail/authorize",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(resp.json()["authorization_url"]).query
    )["state"][0]

    def _fake_exchange(code: str, code_verifier: str) -> GmailCredentials:
        return GmailCredentials(
            access_token="ya29.fake",
            refresh_token="1//fake-refresh",
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            email="owner@example.test",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )

    async def _failing_save(user_id, credentials) -> bool:
        return False

    monkeypatch.setattr(gmail_module, "_exchange_code", _fake_exchange)
    monkeypatch.setattr(gmail_module, "save_gmail_credentials", _failing_save)

    resp = await client.get(
        "/auth/gmail/callback",
        params={"code": "auth-code-from-google", "state": state},
    )
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
    """With Gmail fetch stubbed, real messages flow through the classifier.

    Exercises the server-paginated contract: the router calls
    ``fetch_message_page`` and returns per-page verdicts (now carrying
    ``received_at`` + a normalized ``company`` token), a ``category_summary``,
    and a ``next_page_token`` cursor.
    """

    from datetime import datetime

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

    async def _fake_page(user_id, **_kwargs):
        return MessagePage(
            messages=[
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
                    received_at=datetime(2026, 7, 1, 12, 0, 0),
                ),
                CloudGmailMessage(
                    message_id="m2",
                    thread_id="t2",
                    subject="Your weekly newsletter",
                    sender_name="Jobboard Digest",
                    sender_email="newsletter@jobboard.com",
                    snippet="Recommended jobs you may be interested in. Unsubscribe anytime.",
                    received_at=datetime(2026, 7, 2, 12, 0, 0),
                ),
            ],
            next_page_token="PAGE2",
        )

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    resp = await client.get(
        "/gmail/inbox",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is True
    assert body["scanned"] == 2
    assert len(body["verdicts"]) == 2
    # Pagination cursor + per-page summary are surfaced.
    assert body["next_page_token"] == "PAGE2"
    assert body["category_summary"]["rejection"] == 1
    assert body["category_summary"]["other"] == 1

    by_id = {v["message_id"]: v for v in body["verdicts"]}
    # The rejection language is a strong rules hit.
    assert by_id["m1"]["category"] == "rejection"
    # New pipeline fields ride along: ISO receipt time + a company token that
    # sees through the shared Lever relay to the employer named in the subject.
    assert by_id["m1"]["received_at"] == "2026-07-01T12:00:00"
    assert by_id["m1"]["company"] == "acme"
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
        "received_at",
        "company",
    }
    # Newsletter/digest content is guarded to OTHER.
    assert by_id["m2"]["category"] == "other"


async def test_inbox_cache_serves_repeat_without_refetch(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeat load within the TTL is served from cache, skipping Gmail.

    We count how often the (stubbed) Gmail fetch runs: the first request
    populates the cache; the second must be served from it, so the fetch
    fires exactly once. The response also carries an ``ETag`` + private
    ``Cache-Control`` validator.
    """

    from datetime import datetime

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

    calls = {"n": 0}

    async def _fake_page(user_id, **_kwargs):
        calls["n"] += 1
        return MessagePage(
            messages=[
                CloudGmailMessage(
                    message_id="m1",
                    thread_id="t1",
                    subject="Update on your application to Acme",
                    sender_name="Acme Recruiting",
                    sender_email="no-reply@lever.co",
                    snippet="We would like to schedule an interview with you.",
                    received_at=datetime(2026, 7, 1, 12, 0, 0),
                ),
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    first = await client.get("/gmail/inbox", headers=headers)
    assert first.status_code == 200, first.text
    assert calls["n"] == 1
    etag = first.headers.get("etag")
    assert etag
    assert "private" in first.headers.get("cache-control", "")

    second = await client.get("/gmail/inbox", headers=headers)
    assert second.status_code == 200, second.text
    # Served from cache — the underlying Gmail fetch did NOT run again.
    assert calls["n"] == 1
    assert second.json() == first.json()
    assert second.headers.get("etag") == etag


async def test_inbox_conditional_request_returns_304(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conditional GET with a matching If-None-Match short-circuits to 304."""

    from datetime import datetime

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

    async def _fake_page(user_id, **_kwargs):
        return MessagePage(
            messages=[
                CloudGmailMessage(
                    message_id="m1",
                    thread_id="t1",
                    subject="Your application",
                    sender_name=None,
                    sender_email="jobs@corp.com",
                    snippet="Thanks for applying.",
                    received_at=datetime(2026, 7, 1, 12, 0, 0),
                ),
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    first = await client.get("/gmail/inbox", headers=headers)
    etag = first.headers["etag"]

    conditional = await client.get(
        "/gmail/inbox",
        headers={**headers, "If-None-Match": etag},
    )
    assert conditional.status_code == 304, conditional.text
    assert conditional.headers.get("etag") == etag


async def test_inbox_forwards_filters_to_query_and_pagination(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """range/scope build the Gmail query; count/page_token drive pagination."""

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import MessagePage

    captured: dict = {}

    async def _fake_page(user_id, *, query, page_size, page_token):
        captured.update(query=query, page_size=page_size, page_token=page_token)
        return MessagePage(messages=[], next_page_token="TOK2")

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    resp = await client.get(
        "/gmail/inbox?range=6&scope=anywhere&count=200&page_token=ABC",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    # range + scope compose the Gmail search; count clamps this page's size.
    assert captured["query"] == "in:anywhere newer_than:6m"
    assert captured["page_token"] == "ABC"
    assert captured["page_size"] == 200

    body = resp.json()
    assert body["scope"] == "anywhere"
    assert body["range_months"] == 6
    assert body["next_page_token"] == "TOK2"
    assert body["query"] == "in:anywhere newer_than:6m"


async def test_inbox_unknown_range_falls_back_to_all_time(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stray/unsupported range never errors — it means all-time (no bound)."""

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import MessagePage

    captured: dict = {}

    async def _fake_page(user_id, *, query, page_size, page_token):
        captured.update(query=query)
        return MessagePage(messages=[], next_page_token=None)

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    resp = await client.get(
        "/gmail/inbox?range=999",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    assert captured["query"] == "in:inbox"
    assert resp.json()["range_months"] is None


async def test_pipeline_analyze_summary_and_follow_ups(client: AsyncClient) -> None:
    """POST /gmail/pipeline aggregates the accumulated set: summary + ghosting."""

    from datetime import UTC, datetime, timedelta

    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    recent = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    payload = {
        "items": [
            {
                "message_id": "a1",
                "category": "applied",
                "sender_email": "careers@acme.com",
                "subject": "Application received",
                "received_at": old,
            },
            {
                "message_id": "a2",
                "category": "applied",
                "sender_email": "careers@initech.com",
                "subject": "Applied",
                "received_at": recent,
            },
            {
                "message_id": "o1",
                "category": "offer",
                "sender_email": "careers@globex.com",
                "subject": "Offer",
            },
            {
                "message_id": "n1",
                "category": "other",
                "sender_email": "news@digest.com",
                "subject": "Weekly digest",
            },
        ]
    }
    resp = await client.post(
        "/gmail/pipeline",
        json=payload,
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert body["category_summary"]["applied"] == 2
    assert body["category_summary"]["offer"] == 1
    assert body["category_summary"]["other"] == 1
    # 3 lifecycle messages (2 applied + 1 offer); the digest is not job-related.
    assert body["job_related"] == 3
    # Acme: old + unanswered → follow up. Initech: too recent → not flagged.
    assert [f["company"] for f in body["follow_ups"]] == ["acme"]
    assert body["follow_ups"][0]["days_since"] >= 21


async def test_pipeline_analyze_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/gmail/pipeline", json={"items": []})
    assert resp.status_code == 401


# --- POST /gmail/sync — dashboard persistence (Phase 2) ---------------------


def _sync_items() -> list[dict]:
    # Each lifecycle item carries a >= 0.85 confidence so it clears the precision
    # gate; the digest is noise (and low-confidence) and is never persisted.
    return [
        {
            "message_id": "a1",
            "category": "applied",
            "sender_email": "no-reply@lever.co",
            "subject": "Your application to Acme",
            "sender_name": "Acme via Lever",
            "received_at": "2026-07-01T12:00:00+00:00",
            "confidence": 0.9,
            "thread_id": "th-acme",
        },
        {
            "message_id": "i1",
            "category": "interview",
            "sender_email": "no-reply@lever.co",
            "subject": "Interview with Acme",
            "sender_name": "Acme",
            "received_at": "2026-07-10T12:00:00+00:00",
            "confidence": 0.9,
            "thread_id": "th-acme",
        },
        {
            "message_id": "o1",
            "category": "offer",
            "sender_email": "hr@initech.com",
            "subject": "You have an offer",
            "sender_name": "Initech",
            "received_at": "2026-07-12T12:00:00+00:00",
            "confidence": 0.9,
            "thread_id": "th-initech",
        },
        {
            "message_id": "n1",
            "category": "other",
            "sender_email": "news@digest.com",
            "subject": "Weekly digest",
            "confidence": 0.96,
        },
    ]


async def test_sync_from_items_creates_and_is_idempotent(client: AsyncClient) -> None:
    """Syncing the mined set upserts one row per company; re-running dedupes."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    first = await client.post("/gmail/sync", json={"items": _sync_items()}, headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    # Two companies (Acme, Initech); the digest is noise and is not persisted.
    assert body["created"] == 2
    assert body["updated"] == 0
    assert body["applications"] == 2

    listing = (await client.get("/applications", headers=headers)).json()
    by_company = {a["company"].lower(): a for a in listing["applications"]}
    assert set(by_company) == {"acme", "initech"}
    # Furthest stage reached: applied+interview → interviewing; offer → offered.
    assert by_company["acme"]["status"] == "interviewing"
    assert by_company["initech"]["status"] == "offered"

    # Idempotent: the identical sync creates nothing new and never duplicates.
    second = await client.post("/gmail/sync", json={"items": _sync_items()}, headers=headers)
    assert second.status_code == 200, second.text
    body2 = second.json()
    assert body2["created"] == 0
    assert body2["updated"] == 2
    assert body2["applications"] == 2


async def test_sync_scopes_strictly_per_user(client: AsyncClient) -> None:
    """One user's synced applications never leak into another user's board."""

    a_headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    b_headers = {"Authorization": f"Bearer {_token_for(USER_B)}"}

    await client.post(
        "/gmail/sync",
        json={
            "items": [
                {
                    "message_id": "a1",
                    "category": "applied",
                    "sender_email": "careers@acme.com",
                    "subject": "Applied to Acme",
                    "confidence": 0.9,
                    "received_at": "2026-07-01T12:00:00+00:00",
                }
            ]
        },
        headers=a_headers,
    )
    await client.post(
        "/gmail/sync",
        json={
            "items": [
                {
                    "message_id": "b1",
                    "category": "applied",
                    "sender_email": "careers@globex.com",
                    "subject": "Applied to Globex",
                    "confidence": 0.9,
                    "received_at": "2026-07-01T12:00:00+00:00",
                }
            ]
        },
        headers=b_headers,
    )

    a_list = (await client.get("/applications", headers=a_headers)).json()
    b_list = (await client.get("/applications", headers=b_headers)).json()
    assert [a["company"].lower() for a in a_list["applications"]] == ["acme"]
    assert [a["company"].lower() for a in b_list["applications"]] == ["globex"]


async def test_sync_server_fetch_mode_classifies_and_persists(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no items, the server fetches a bounded page and persists it."""

    from datetime import datetime

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

    async def _fake_page(user_id, **_kwargs):
        return MessagePage(
            messages=[
                CloudGmailMessage(
                    message_id="m1",
                    thread_id="t1",
                    subject="We received your application to Cedartech",
                    sender_name="Cedartech",
                    sender_email="careers@cedartech.com",
                    snippet="Thank you for applying. Your application has been received.",
                    received_at=datetime(2026, 7, 1, 12, 0, 0),
                )
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    headers = {"Authorization": f"Bearer {_token_for(USER_B)}"}
    resp = await client.post("/gmail/sync", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] == 1
    assert body["created"] == 1

    listing = (await client.get("/applications", headers=headers)).json()
    assert [a["company"].lower() for a in listing["applications"]] == ["cedartech"]


async def test_sync_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/gmail/sync", json={})
    assert resp.status_code == 401


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


# =============================================================================
# Precision + click-through + correction/training + review queue (the fix)
# =============================================================================


def _owner_batch() -> list[dict]:
    """A mined batch mirroring the owner's real senders: mostly noise, few real.

    Only the two genuine, high-confidence application-lifecycle mails with a
    nameable employer (Stripe, Airbnb) may become rows; everything else is noise
    (no row) or an uncertain verdict (review queue).
    """

    return [
        # Handshake job alert → relay, no employer, marketing → NO row/review.
        {"message_id": "m-hs", "category": "other", "sender_email": "alerts@mail.joinhandshake.com",
         "subject": "New jobs for you", "sender_name": "Handshake", "confidence": 0.96,
         "received_at": "2026-06-01T10:00:00+00:00"},
        # Turing marketing → other → dropped entirely.
        {"message_id": "m-tur", "category": "other", "sender_email": "news@turing.com",
         "subject": "Hire pre-vetted developers", "sender_name": "Turing", "confidence": 0.9,
         "received_at": "2026-06-02T10:00:00+00:00"},
        # Miami OH onboarding (edu) misfiled as rejection, uncertain → review only.
        {"message_id": "m-miami", "category": "rejection", "sender_email": "noreply@miamioh.edu",
         "subject": "Online Onboarding", "sender_name": "Miami OH", "confidence": 0.75,
         "received_at": "2026-06-03T10:00:00+00:00"},
        # A person on webmail, confident 'offer' → NO row (never OFFERED) → review.
        {"message_id": "m-person", "category": "offer", "sender_email": "julee.johnson@gmail.com",
         "subject": "Re: our chat", "sender_name": "Julee Johnson", "confidence": 0.9,
         "received_at": "2026-06-04T10:00:00+00:00"},
        # REAL: Thanks for applying to Stripe → one applied row, dated the email.
        {"message_id": "m-stripe", "category": "applied", "sender_email": "careers@stripe.com",
         "subject": "Thanks for applying to the Data Scientist role at Stripe", "sender_name": "Stripe",
         "confidence": 0.95, "thread_id": "th-stripe", "received_at": "2026-05-15T09:00:00+00:00"},
        # REAL: interview relayed via Greenhouse naming Airbnb → interviewing row.
        {"message_id": "m-airbnb", "category": "interview", "sender_email": "no-reply@greenhouse-mail.io",
         "subject": "Interview with Airbnb", "sender_name": "Airbnb via Greenhouse", "confidence": 0.9,
         "thread_id": "th-airbnb", "received_at": "2026-05-20T09:00:00+00:00"},
    ]


async def test_sync_precision_only_real_rows_dates_and_review(client: AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    resp = await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Two real rows only — the 4 noise/uncertain items never become applications.
    assert body["created"] == 2
    assert body["applications"] == 2

    listing = (await client.get("/applications", headers=headers)).json()
    by_company = {a["company"]: a for a in listing["applications"]}
    assert set(by_company) == {"Stripe", "Airbnb"}
    # Real employer names — never "Handshake"/"Joinhandshake"/"Miamioh"/a person.
    assert "Joinhandshake" not in by_company and "Julee Johnson" not in by_company
    # Correct status + REAL received date (not today), + role extracted.
    assert by_company["Stripe"]["status"] == "applied"
    assert by_company["Stripe"]["applied_date"] == "2026-05-15"
    assert by_company["Stripe"]["position"] == "Data Scientist"
    assert by_company["Airbnb"]["status"] == "interviewing"
    # Never the literal "Unknown role".
    assert all(a["position"] != "Unknown role" for a in listing["applications"])

    # The uncertain verdicts populate the needs-classification queue, not the board.
    review = (await client.get("/applications/review", headers=headers)).json()
    review_senders = {i["sender_email"] for i in review["items"]}
    assert "noreply@miamioh.edu" in review_senders  # edu onboarding → review
    assert "julee.johnson@gmail.com" in review_senders  # person 'offer' → review
    summary = (await client.get("/applications/summary", headers=headers)).json()
    assert summary["needs_review"] == review["total"] == len(review_senders)


def _one_app_batch(mid: str, domain: str, company: str, category: str = "applied") -> list[dict]:
    """A single-message scan that rolls up to exactly one real application."""

    return [
        {
            "message_id": mid,
            "category": category,
            "sender_email": f"careers@{domain}",
            "subject": f"Thanks for applying to the Engineer role at {company}",
            "sender_name": company,
            "confidence": 0.95,
            "thread_id": f"th-{mid}",
            "received_at": "2026-05-01T09:00:00+00:00",
        }
    ]


def _noise_item(mid: str, received_at: str = "2026-05-01T09:00:00+00:00") -> dict:
    """The SAME message id, re-read by a later scan and now judged marketing.

    This is what evidence against a row actually looks like: not silence, but
    the scan re-reading the very message the row was filed from and no longer
    concluding an application from it — the classifier correcting itself, which
    is the case the rebuild exists to clean up.
    """

    return {
        "message_id": mid,
        "category": "other",
        "sender_email": "news@turing.com",
        "subject": "Hire pre-vetted developers",
        "sender_name": "Turing",
        "confidence": 0.95,
        "received_at": received_at,
    }


async def test_auto_sync_is_additive_and_rebuild_purges_only_contradicted(
    client: AsyncClient,
) -> None:
    """Neither sync mode may drop an app on the strength of a scan's silence.

    Was ``test_auto_sync_is_additive_only_rebuild_purges``, which asserted that
    an explicit rebuild clears a row the scan simply didn't re-include. That is
    the reasoning that deleted two real applications on 2026-08-10, so the
    expectation is corrected here: a rebuild that never re-read m-tcs removes
    nothing, and only one that re-read it and no longer files it may clear TCS.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    # Sync A (additive by default) files TCS.
    respA = await client.post(
        "/gmail/sync", json={"items": _one_app_batch("m-tcs", "tcs.com", "Tata")}, headers=headers
    )
    assert respA.status_code == 200, respA.text
    listA = (await client.get("/applications", headers=headers)).json()
    assert listA["total"] == 1
    tcs_company = listA["applications"][0]["company"]

    # Sync B (additive) scans a DIFFERENT window — only Aven, TCS not included.
    respB = await client.post(
        "/gmail/sync", json={"items": _one_app_batch("m-aven", "aven.com", "Aven")}, headers=headers
    )
    assert respB.status_code == 200, respB.text
    assert respB.json()["purged"] == 0  # additive removes nothing
    listB = (await client.get("/applications", headers=headers)).json()
    companies_B = {a["company"] for a in listB["applications"]}
    # DURABLE: TCS survived a scan that never mentioned it; Aven was added.
    assert tcs_company in companies_B
    assert listB["total"] == 2

    # A rebuild that merely fails to mention TCS removes NOTHING. Absence is
    # not evidence, whichever mode asked the question.
    respC = await client.post(
        "/gmail/sync",
        json={"items": _one_app_batch("m-aven", "aven.com", "Aven"), "mode": "rebuild"},
        headers=headers,
    )
    assert respC.status_code == 200, respC.text
    assert respC.json()["purged"] == 0
    listC = (await client.get("/applications", headers=headers)).json()
    assert tcs_company in {a["company"] for a in listC["applications"]}

    # A rebuild that RE-READ m-tcs and now calls it marketing has actually
    # contradicted the row — that, and only that, clears TCS.
    respD = await client.post(
        "/gmail/sync",
        json={
            "items": [
                *_one_app_batch("m-aven", "aven.com", "Aven"),
                _noise_item("m-tcs"),
            ],
            "mode": "rebuild",
        },
        headers=headers,
    )
    assert respD.status_code == 200, respD.text
    assert respD.json()["purged"] == 1
    # The response NAMES what it removed, so the button can say so.
    assert [r["company"] for r in respD.json()["removed"]] == [tcs_company]
    listD = (await client.get("/applications", headers=headers)).json()
    assert tcs_company not in {a["company"] for a in listD["applications"]}
    assert listD["total"] == 1


async def test_additive_sync_no_duplicate_and_status_only_advances(
    client: AsyncClient,
) -> None:
    """Repeat additive syncs upsert one row per company; status only advances."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    await client.post(
        "/gmail/sync", json={"items": _one_app_batch("s1", "stripe.com", "Stripe")}, headers=headers
    )
    l1 = (await client.get("/applications", headers=headers)).json()
    assert l1["total"] == 1
    row_id = l1["applications"][0]["id"]
    assert l1["applications"][0]["status"] == "applied"

    # An interview signal for the SAME company advances the SAME row (no dupe).
    await client.post(
        "/gmail/sync",
        json={
            "items": [
                {
                    "message_id": "s2",
                    "category": "interview",
                    "sender_email": "careers@stripe.com",
                    "subject": "Interview with Stripe",
                    "sender_name": "Stripe",
                    "confidence": 0.9,
                    "thread_id": "th-s2",
                    "received_at": "2026-05-10T09:00:00+00:00",
                }
            ]
        },
        headers=headers,
    )
    l2 = (await client.get("/applications", headers=headers)).json()
    assert l2["total"] == 1  # upserted, not duplicated
    assert l2["applications"][0]["id"] == row_id
    assert l2["applications"][0]["status"] == "interviewing"  # advanced

    # A later applied-only signal must NOT downgrade interviewing → applied.
    await client.post(
        "/gmail/sync", json={"items": _one_app_batch("s1", "stripe.com", "Stripe")}, headers=headers
    )
    l3 = (await client.get("/applications", headers=headers)).json()
    assert l3["total"] == 1
    assert l3["applications"][0]["status"] == "interviewing"  # monotonic, no regression


async def test_application_detail_click_through_has_gmail_link(client: AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    listing = (await client.get("/applications", headers=headers)).json()
    stripe = next(a for a in listing["applications"] if a["company"] == "Stripe")

    detail = (await client.get(f"/applications/{stripe['id']}", headers=headers)).json()
    assert detail["application"]["company"] == "Stripe"
    msgs = detail["messages"]
    assert len(msgs) == 1
    assert msgs[0]["message_id"] == "m-stripe"
    assert msgs[0]["subject"].startswith("Thanks for applying")
    assert msgs[0]["gmail_link"].endswith("#all/th-stripe")
    # The row itself also carries the deep link for a one-click open.
    assert stripe["url"].endswith("#all/th-stripe")


async def test_status_correction_is_sticky_through_resync_and_trains(client: AsyncClient) -> None:
    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import TrainingData

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    listing = (await client.get("/applications", headers=headers)).json()
    airbnb = next(a for a in listing["applications"] if a["company"] == "Airbnb")

    # The user corrects Airbnb: interviewing → rejected.
    patch = await client.patch(
        f"/applications/{airbnb['id']}", json={"status": "rejected"}, headers=headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "rejected"
    assert patch.json()["source"] == "gmail_user"  # now user-owned → sticky

    # A correction trains the model (training_data row written).
    async with get_session() as session:
        labels = (await session.exec(sm_select(TrainingData.label))).all()
    assert "rejection" in labels

    # A re-sync (mail still says 'interviewing') must NOT overwrite the decision.
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    listing2 = (await client.get("/applications", headers=headers)).json()
    airbnb2 = next(a for a in listing2["applications"] if a["company"] == "Airbnb")
    assert airbnb2["status"] == "rejected"


async def test_dismiss_removes_row_and_trains_other(client: AsyncClient) -> None:
    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import TrainingData

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    listing = (await client.get("/applications", headers=headers)).json()
    stripe = next(a for a in listing["applications"] if a["company"] == "Stripe")

    resp = await client.post(f"/applications/{stripe['id']}/dismiss", headers=headers)
    assert resp.status_code == 200 and resp.json()["dismissed"] is True

    listing2 = (await client.get("/applications", headers=headers)).json()
    assert "Stripe" not in {a["company"] for a in listing2["applications"]}
    async with get_session() as session:
        labels = (await session.exec(sm_select(TrainingData.label))).all()
    assert "other" in labels  # taught that it was misfiled


async def test_review_item_classify_creates_sticky_application(client: AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    # An uncertain but real interview (below the gate) → lands in the review queue.
    items = [
        {"message_id": "rv1", "category": "interview", "sender_email": "talent@replit.com",
         "subject": "About your background", "sender_name": "Replit", "confidence": 0.78,
         "received_at": "2026-05-25T09:00:00+00:00"},
    ]
    await client.post("/gmail/sync", json={"items": items}, headers=headers)
    review = (await client.get("/applications/review", headers=headers)).json()
    assert any(i["message_id"] == "rv1" for i in review["items"])

    # Classifying it into 'interview' creates a sticky application for Replit.
    resp = await client.post(
        "/applications/review/rv1/classify", json={"category": "interview"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["application_id"] is not None

    listing = (await client.get("/applications", headers=headers)).json()
    replit = next(a for a in listing["applications"] if a["company"].lower() == "replit")
    assert replit["status"] == "interviewing"
    assert replit["source"] == "gmail_user"  # sticky
    # It leaves the queue.
    review2 = (await client.get("/applications/review", headers=headers)).json()
    assert not any(i["message_id"] == "rv1" for i in review2["items"])


async def test_resync_purges_stale_auto_but_preserves_manual(client: AsyncClient) -> None:
    """Rebuild clears a CONTRADICTED auto row; the manual row is untouched.

    The rebuild half was rewritten after the 2026-08-10 data loss: it used to
    assert that a scan omitting Airbnb clears Airbnb, which is the reasoning
    that destroyed two real applications.

    Depends on ``_owner_batch``'s dates: the scan's coverage span runs
    2026-05-15 … 2026-06-04, and m-airbnb (2026-05-20) has to fall inside it for
    the row to be removable at all. Move those dates and this test quietly stops
    testing what it says it does.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    # A hand-filed application the user owns.
    manual = await client.post(
        "/applications", json={"company": "MyStartup", "position": "Founding Engineer"}, headers=headers
    )
    assert manual.status_code == 201
    assert manual.json()["source"] == "manual"

    # First sync produces Stripe + Airbnb (auto).
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    companies = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert {"MyStartup", "Stripe", "Airbnb"} <= companies

    only_stripe = [i for i in _owner_batch() if i["message_id"] != "m-airbnb"]

    # A routine ADDITIVE sync that no longer includes Airbnb must NOT purge it —
    # a bounded scan missing a company is not evidence the application is gone.
    add_resp = await client.post("/gmail/sync", json={"items": only_stripe}, headers=headers)
    assert add_resp.json()["purged"] == 0
    companies_add = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert "Airbnb" in companies_add  # durable — additive kept it

    # Neither does a REBUILD on the same silent scan — it never re-read
    # m-airbnb, so it holds no evidence about the Airbnb row at all.
    silent = await client.post(
        "/gmail/sync", json={"items": only_stripe, "mode": "rebuild"}, headers=headers
    )
    assert silent.json()["purged"] == 0
    assert silent.json()["removed"] == []
    companies_silent = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert "Airbnb" in companies_silent

    # A rebuild that RE-READ m-airbnb and no longer files it does clear the
    # stale AUTO row — while the manual row survives untouched.
    resp = await client.post(
        "/gmail/sync",
        json={
            "items": [*only_stripe, _noise_item("m-airbnb", "2026-05-20T09:00:00+00:00")],
            "mode": "rebuild",
        },
        headers=headers,
    )
    assert resp.json()["purged"] == 1
    assert [r["company"] for r in resp.json()["removed"]] == ["Airbnb"]
    companies2 = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert "Airbnb" not in companies2  # contradicted auto row gone
    assert "MyStartup" in companies2  # manual row preserved
    assert "Stripe" in companies2


async def test_correction_endpoints_require_auth(client: AsyncClient) -> None:
    assert (await client.patch("/applications/1", json={"status": "rejected"})).status_code == 401
    assert (await client.post("/applications/1/dismiss")).status_code == 401
    assert (await client.delete("/applications/1")).status_code == 401
    assert (await client.get("/applications/review")).status_code == 401
    assert (await client.get("/applications/1")).status_code == 401


async def test_correction_404_for_unknown_or_other_users_row(client: AsyncClient) -> None:
    a_headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    b_headers = {"Authorization": f"Bearer {_token_for(USER_B)}"}
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=a_headers)
    a_id = (await client.get("/applications", headers=a_headers)).json()["applications"][0]["id"]
    # User B cannot see or mutate user A's row.
    assert (await client.get(f"/applications/{a_id}", headers=b_headers)).status_code == 404
    assert (
        await client.patch(f"/applications/{a_id}", json={"status": "rejected"}, headers=b_headers)
    ).status_code == 404


# =============================================================================
# Silent-failure regressions: a classification must always produce a VISIBLE
# outcome, and a re-sync must never revert or unlink a human decision.
# =============================================================================


def _crusoe_email_kwargs(message_id: str = "crusoe-orphan-1") -> dict:
    """The exact production shape of the ATS mail that filed nothing.

    ``no-reply@ashbyhq.com`` is a relay (so the domain is not the employer) and
    the subject has no at/with/to connective — which is why ``resolve_employer``
    returned None and the classify endpoint reported success while creating
    nothing (``training_data`` id 4 / ``emails`` id 58 in production).
    """

    return {
        "message_id": message_id,
        "sender_email": "no-reply@ashbyhq.com",
        "sender_name": "Crusoe Hiring Team",
        "subject": "Crusoe | Application Received",
    }


async def test_ats_pipe_subject_now_files_a_real_application(client: AsyncClient) -> None:
    """A confident 'Crusoe | Application Received' rolls up to a real row."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    items = [
        {
            **_crusoe_email_kwargs("m-crusoe"),
            "category": "applied",
            "confidence": 0.9,
            "received_at": "2026-08-10T21:18:52+00:00",
        }
    ]
    resp = await client.post("/gmail/sync", json={"items": items}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1

    listing = (await client.get("/applications", headers=headers)).json()
    assert [a["company"] for a in listing["applications"]] == ["Crusoe"]
    assert listing["applications"][0]["applied_date"] == "2026-08-10"


async def test_classify_without_employer_is_visible_not_silent(client: AsyncClient) -> None:
    """The reported bug: classify → 2xx, no application, item gone. Never again.

    A confident 'offer' from a person on consumer webmail has no nameable
    employer by design. Classifying it must NOT report a bare success: the
    response says ``needs_employer``, the item stays in the queue, and the
    user's label is still recorded for training. Supplying a company then
    completes the decision.
    """

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import TrainingData

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    items = [
        {
            "message_id": "no-emp-1",
            "category": "offer",
            "sender_email": "julee.johnson@gmail.com",
            "sender_name": "Julee Johnson",
            "subject": "You have an offer",
            "confidence": 0.9,
            "received_at": "2026-06-04T10:00:00+00:00",
        }
    ]
    await client.post("/gmail/sync", json={"items": items}, headers=headers)
    review = (await client.get("/applications/review", headers=headers)).json()
    assert any(i["message_id"] == "no-emp-1" for i in review["items"])

    resp = await client.post(
        "/applications/review/no-emp-1/classify", json={"category": "offer"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Honest outcome: nothing was created, and the response says so out loud.
    assert body["needs_employer"] is True
    assert body["application_id"] is None
    assert body["message_id"] == "no-emp-1"
    assert body["detail"]

    # The decision was NOT swallowed: the item is still actionable...
    review_after = (await client.get("/applications/review", headers=headers)).json()
    assert any(i["message_id"] == "no-emp-1" for i in review_after["items"])
    # ...no phantom application appeared...
    assert (await client.get("/applications", headers=headers)).json()["total"] == 0
    # ...and the label was still kept for the classifier.
    async with get_session() as session:
        labels = (await session.exec(sm_select(TrainingData.label))).all()
    assert "offer" in labels

    # Round trip 2: the caller supplies what the response asked for.
    resp2 = await client.post(
        "/applications/review/no-emp-1/classify",
        json={"category": "offer", "company": "Wayne Enterprises"},
        headers=headers,
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["needs_employer"] is False
    assert resp2.json()["application_id"] is not None

    listing = (await client.get("/applications", headers=headers)).json()
    assert [a["company"] for a in listing["applications"]] == ["Wayne Enterprises"]
    assert listing["applications"][0]["status"] == "offered"
    assert listing["applications"][0]["source"] == "gmail_user"
    review_final = (await client.get("/applications/review", headers=headers)).json()
    assert not any(i["message_id"] == "no-emp-1" for i in review_final["items"])


async def test_sync_reconciles_orphaned_classification_idempotently(
    client: AsyncClient,
) -> None:
    """An already-stranded classification is recovered on the next sync — once.

    Reproduces the production row directly: classified APPLIED, reviewed,
    user-corrected, and with no ``application_id``. It is invisible on the board
    and gone from the queue, so nothing but a reconciliation can rescue it.
    """

    import uuid as _uuid
    from datetime import datetime as _dt

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email, EmailCategory, EmailSource

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    async with get_session() as session:
        session.add(
            Email(
                user_id=_uuid.UUID(USER_A),
                application_id=None,
                source_account=EmailSource.GMAIL,
                received_at=_dt(2026, 8, 10, 21, 18, 52),
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.8,
                classification_method="rules",
                user_corrected=True,
                is_reviewed=True,
                **_crusoe_email_kwargs(),
            )
        )
        await session.commit()

    # Nothing on the board yet — the classification produced no application.
    assert (await client.get("/applications", headers=headers)).json()["total"] == 0

    first = await client.post("/gmail/sync", json={"items": []}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1

    listing = (await client.get("/applications", headers=headers)).json()
    assert listing["total"] == 1
    crusoe = listing["applications"][0]
    assert crusoe["company"] == "Crusoe"
    assert crusoe["status"] == "applied"
    assert crusoe["source"] == "gmail_user"  # came from a human decision → sticky
    assert crusoe["applied_date"] == "2026-08-10"  # the email's date, not today

    # The email is now linked, so it shows up in the click-through detail view.
    detail = (await client.get(f"/applications/{crusoe['id']}", headers=headers)).json()
    assert [m["message_id"] for m in detail["messages"]] == ["crusoe-orphan-1"]

    # Idempotent: a second sync creates nothing and duplicates nothing.
    second = await client.post("/gmail/sync", json={"items": []}, headers=headers)
    assert second.json()["created"] == 0
    assert (await client.get("/applications", headers=headers)).json()["total"] == 1

    async with get_session() as session:
        rows = (await session.exec(sm_select(Email))).all()
    assert len(rows) == 1 and rows[0].application_id == crusoe["id"]


async def _classify_replit_review_item(client: AsyncClient, headers: dict) -> dict:
    """Sync one below-gate Replit interview and let the user classify it."""

    items = [
        {
            "message_id": "rv-replit",
            "category": "interview",
            "sender_email": "talent@replit.com",
            "sender_name": "Replit",
            "subject": "About your background",
            "confidence": 0.78,
            "received_at": "2026-05-25T09:00:00+00:00",
        }
    ]
    await client.post("/gmail/sync", json={"items": items}, headers=headers)
    resp = await client.post(
        "/applications/review/rv-replit/classify",
        json={"category": "interview"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["application_id"] is not None
    return items[0]


async def test_resync_does_not_revert_a_user_corrected_verdict(client: AsyncClient) -> None:
    """``_persist_message_refs`` must not overwrite a settled classification.

    The rolled-application path reaches that function without passing through
    the settled-message filter, so a corrected message had its verdict reset to
    the classifier's the moment it got linked to an application.
    """

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email, EmailCategory

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    item = await _classify_replit_review_item(client, headers)

    # A later scan re-classifies the SAME message, confidently and differently,
    # and this time it clears the gate — so it rolls up and gets linked.
    rescan = [{**item, "category": "applied", "confidence": 0.95}]
    resp = await client.post("/gmail/sync", json={"items": rescan}, headers=headers)
    assert resp.status_code == 200, resp.text

    async with get_session() as session:
        email = (
            await session.exec(sm_select(Email).where(Email.message_id == "rv-replit"))
        ).first()
    # The human's verdict survives the machine's.
    assert email.classified_as == EmailCategory.INTERVIEW
    assert email.classification_confidence == pytest.approx(0.78)
    assert email.user_corrected is True
    # ...and the row the user created keeps its status.
    listing = (await client.get("/applications", headers=headers)).json()
    replit = next(a for a in listing["applications"] if a["company"].lower() == "replit")
    assert replit["status"] == "interviewing"


async def test_rebuild_does_not_unlink_a_user_classified_email(client: AsyncClient) -> None:
    """A rebuild persists review items unfiltered; that must not clear a link.

    Without the guard, ``_persist_review_items`` writes ``application_id=None``
    over the row the user just filed, un-filing the application on the next
    explicit Re-sync.
    """

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    item = await _classify_replit_review_item(client, headers)
    app_id = (await client.get("/applications", headers=headers)).json()["applications"][0]["id"]

    # The classifier still thinks it is a 0.78 guess, so it re-enters the review
    # set on the explicit rebuild.
    resp = await client.post(
        "/gmail/sync", json={"items": [item], "mode": "rebuild"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    async with get_session() as session:
        email = (
            await session.exec(sm_select(Email).where(Email.message_id == "rv-replit"))
        ).first()
    assert email is not None and email.application_id == app_id
    detail = (await client.get(f"/applications/{app_id}", headers=headers)).json()
    assert [m["message_id"] for m in detail["messages"]] == ["rv-replit"]


# =============================================================================
# Sync cursor — incremental sync, its fallbacks, and the state it exposes
# =============================================================================
#
# The owner's complaint was "I have to re-sync again and again every time I go
# in, and also when a new email arrives." The cause was structural: POST
# /gmail/sync had no cursor read and no cursor write, so every call recomputed a
# fixed 12-month / 750-message window from scratch, and nothing anywhere
# recorded that a sync had happened — ``sync_state`` had zero rows in
# production. These tests pin the fix: the cursor is written, it is used, its
# two normal failure modes degrade to a full scan instead of an error, and
# disconnect drops it.

GMAIL_ADDRESS = "owner@example.test"


async def _connect_gmail(user_id: str, email: str = GMAIL_ADDRESS) -> None:
    """Store an encrypted Gmail token for ``user_id``. Never contacts Google."""

    import uuid as _uuid
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from jobtracker.credentials.cloud import save_gmail_credentials
    from jobtracker.credentials.types import GmailCredentials
    from jobtracker.database.connection import user_id_scope

    uid = _uuid.UUID(user_id)
    with user_id_scope(uid):
        saved = await save_gmail_credentials(
            uid,
            GmailCredentials(
                access_token="ya29.fake",
                refresh_token="1//fake-refresh",
                token_expiry=_dt.utcnow() + _td(hours=1),
                email=email,
                scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            ),
        )
    assert saved, "test setup: Gmail credential save must succeed"


async def _sync_rows(user_id: str) -> list:
    """Every ``sync_state`` row owned by ``user_id``."""

    import uuid as _uuid

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import SyncState

    async with get_session() as session:
        return list(
            (
                await session.exec(
                    sm_select(SyncState).where(SyncState.user_id == _uuid.UUID(user_id))
                )
            ).all()
        )


def _msg(
    message_id: str,
    *,
    subject: str,
    sender: str,
    snippet: str,
    day: int,
    name: str | None = None,
) -> Any:
    from datetime import datetime as _dt

    from jobtracker.cloud.gmail_client import CloudGmailMessage

    return CloudGmailMessage(
        message_id=message_id,
        thread_id=f"t-{message_id}",
        subject=subject,
        sender_name=name,
        sender_email=sender,
        snippet=snippet,
        received_at=_dt(2026, 7, day, 12, 0, 0),
    )


def _applied_msg(message_id: str = "m-applied", day: int = 1) -> Any:
    return _msg(
        message_id,
        subject="We received your application to Cedartech",
        sender="careers@cedartech.com",
        snippet="Thank you for applying. Your application has been received.",
        day=day,
        name="Cedartech",
    )


def _interview_msg(message_id: str = "m-interview", day: int = 10) -> Any:
    return _msg(
        message_id,
        subject="Interview with Cedartech",
        sender="careers@cedartech.com",
        snippet="We would like to schedule an interview with you next week.",
        day=day,
        name="Cedartech",
    )


def _install_gmail_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    full_messages: list | None = None,
    history_results: list | None = None,
    profile_ids: list | None = None,
    history_error: Exception | None = None,
) -> dict:
    """Stub the three Gmail reads a server-side sync makes; return call counters.

    ``profile_ids``/``history_results`` are consumed per call and the last entry
    repeats, so a test can say "baseline 9001 on the first sync, 9100 on the
    second" without writing a state machine.
    """

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import MessagePage

    calls: dict = {"full": 0, "history": 0, "profile": 0, "start_history_ids": []}
    ids = list(profile_ids or ["9001"])
    results = list(history_results or [])

    def _nth(seq: list, n: int) -> Any:
        return seq[min(n - 1, len(seq) - 1)]

    async def _fake_profile(user_id, **_kwargs):
        calls["profile"] += 1
        return _nth(ids, calls["profile"])

    async def _fake_page(user_id, **_kwargs):
        calls["full"] += 1
        return MessagePage(messages=list(full_messages or []), next_page_token=None)

    async def _fake_history(user_id, *, start_history_id, **_kwargs):
        calls["history"] += 1
        calls["start_history_ids"].append(start_history_id)
        if history_error is not None:
            raise history_error
        return _nth(results, calls["history"]) if results else None

    monkeypatch.setattr(gmail_client_module, "fetch_mailbox_history_id", _fake_profile)
    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)
    monkeypatch.setattr(gmail_client_module, "fetch_history_messages", _fake_history)
    return calls


async def test_first_sync_writes_the_cursor_and_status_renders_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The missing half of the product: a sync that is REMEMBERED.

    Before this, ``sync_state`` was written only by the desktop service and had
    zero rows in production, so the web app had nothing to render for "last
    synced …" — which is why it always looked like it had never synced.
    """

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch, full_messages=[_applied_msg()], profile_ids=["9001"]
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.post("/gmail/sync", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1

    # No cursor existed, so this run was the full scan — and it baselined.
    assert calls["full"] == 1
    assert calls["history"] == 0
    assert calls["profile"] == 1

    rows = await _sync_rows(USER_A)
    assert len(rows) == 1
    row = rows[0]
    assert row.account_type == "gmail"
    assert row.account_email == GMAIL_ADDRESS
    assert row.gmail_history_id == "9001"
    assert row.status == "idle"
    assert row.error_message is None
    assert row.last_sync_at is not None

    status = (await client.get("/auth/gmail/status", headers=headers)).json()
    assert status["connected"] is True
    assert status["email"] == GMAIL_ADDRESS
    assert status["has_cursor"] is True
    assert status["sync_status"] == "idle"
    assert status["sync_error"] is None

    # The timestamp carries an EXPLICIT UTC offset. Naive, the browser would
    # parse it as local time and render "in 4 hours" for a sync that just ran —
    # which would defeat the whole point of surfacing it.
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    parsed = _dt.fromisoformat(status["last_sync_at"])
    assert parsed.tzinfo is not None
    assert abs((_dt.now(_UTC) - parsed).total_seconds()) < 300


async def test_second_sync_takes_the_incremental_path(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sync #2 asks Gmail what CHANGED instead of re-listing 12 months.

    This is the fix for "and also when a new email arrives": the second run
    reads ``users.history.list`` from the stored baseline, never touches
    ``messages.list``, and re-baselines to the freshly captured historyId.
    """

    from jobtracker.cloud.gmail_client import HistoryPage

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg(day=1)],
        history_results=[HistoryPage(messages=[_interview_msg(day=10)])],
        profile_ids=["9001", "9100"],
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    first = await client.post("/gmail/sync", json={}, headers=headers)
    assert first.status_code == 200, first.text
    assert (calls["full"], calls["history"]) == (1, 0)

    second = await client.post("/gmail/sync", json={}, headers=headers)
    assert second.status_code == 200, second.text

    # The expensive re-list did NOT happen again; the delta did.
    assert calls["full"] == 1
    assert calls["history"] == 1
    assert calls["start_history_ids"] == ["9001"]
    assert second.json()["scanned"] == 1

    # The new mail still lands on the board, and the cursor moved forward.
    listing = (await client.get("/applications", headers=headers)).json()
    assert [a["company"].lower() for a in listing["applications"]] == ["cedartech"]
    assert listing["applications"][0]["status"] == "interviewing"
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9100"


async def test_incremental_delta_never_downgrades_an_advanced_row(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 3-message delta must not undo what a 750-message scan established.

    ``roll_up_applications`` computes "furthest stage reached" from whatever it
    is handed. Handed a partial batch containing only a stale ``applied``
    message, the merge must still leave an interviewing row alone and must not
    rewrite its applied date.
    """

    from jobtracker.cloud.gmail_client import HistoryPage

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg("m1", day=1), _interview_msg("m2", day=10)],
        # The delta carries ONLY an older "applied" message.
        history_results=[HistoryPage(messages=[_applied_msg("m3", day=2)])],
        profile_ids=["9001", "9100"],
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    before = (await client.get("/applications", headers=headers)).json()["applications"][0]
    assert before["status"] == "interviewing"

    await client.post("/gmail/sync", json={}, headers=headers)
    assert calls["history"] == 1

    after = (await client.get("/applications", headers=headers)).json()["applications"][0]
    assert after["id"] == before["id"]
    assert after["status"] == "interviewing"  # monotonic — never walked back
    assert after["applied_date"] == before["applied_date"] == "2026-07-01"


async def test_expired_history_cursor_falls_back_to_a_full_scan(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gmail's 404 for an aged-out cursor is normal operation, not a failure.

    History is kept for roughly a week. A user who did not open the app for
    eight days must get a silent full scan and a fresh baseline — a 200 with
    ``status='idle'``, never a user-facing error.
    """

    from jobtracker.cloud.gmail_client import HistoryPage

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg()],
        history_results=[HistoryPage(messages=[], expired=True)],
        profile_ids=["9001", "9500"],
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9001"

    second = await client.post("/gmail/sync", json={}, headers=headers)
    assert second.status_code == 200, second.text

    # The cursor was tried, rejected, and the full scan re-ran and re-baselined.
    assert calls["history"] == 1
    assert calls["full"] == 2
    assert second.json()["scanned"] == 1
    row = (await _sync_rows(USER_A))[0]
    assert row.gmail_history_id == "9500"
    assert row.status == "idle"
    assert row.error_message is None

    status = (await client.get("/auth/gmail/status", headers=headers)).json()
    assert status["sync_status"] == "idle"
    assert status["sync_error"] is None


async def test_truncated_history_also_falls_back_rather_than_skipping(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """More new mail than one invocation walks → full scan, not a partial read."""

    from jobtracker.cloud.gmail_client import HistoryPage

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg()],
        history_results=[HistoryPage(messages=[], truncated=True)],
        profile_ids=["9001", "9700"],
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    second = await client.post("/gmail/sync", json={}, headers=headers)

    assert second.status_code == 200, second.text
    assert calls["full"] == 2
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9700"


async def test_incremental_sync_still_reconciles_orphans(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An orphan must not become unreachable because the sync got cheaper.

    The reconciliation catch-up is what rescues a settled-but-unlinked
    classification. It runs on the DB, not on the scan, so an incremental run
    that found ZERO new messages must still run it — i.e. an empty delta must
    never be short-circuited into an early return.
    """

    import uuid as _uuid
    from datetime import datetime as _dt

    from jobtracker.cloud.gmail_client import HistoryPage
    from jobtracker.database import get_session
    from jobtracker.database.models import Email, EmailCategory, EmailSource

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[],
        history_results=[HistoryPage(messages=[])],  # nothing new at all
        profile_ids=["9001", "9100"],
    )
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    # Sync once so a cursor exists, THEN strand the classification — otherwise
    # the full scan's reconciliation would have already rescued it.
    await client.post("/gmail/sync", json={}, headers=headers)
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9001"

    async with get_session() as session:
        session.add(
            Email(
                user_id=_uuid.UUID(USER_A),
                application_id=None,
                source_account=EmailSource.GMAIL,
                received_at=_dt(2026, 8, 10, 21, 18, 52),
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.8,
                classification_method="rules",
                user_corrected=True,
                is_reviewed=True,
                **_crusoe_email_kwargs(),
            )
        )
        await session.commit()
    assert (await client.get("/applications", headers=headers)).json()["total"] == 0

    second = await client.post("/gmail/sync", json={}, headers=headers)
    assert second.status_code == 200, second.text
    # Incremental path, zero new messages — and the orphan is still rescued.
    assert calls["history"] == 1
    assert calls["full"] == 1
    assert second.json()["scanned"] == 0
    assert second.json()["created"] == 1

    listing = (await client.get("/applications", headers=headers)).json()
    assert listing["total"] == 1
    assert listing["applications"][0]["company"] == "Crusoe"


async def test_rebuild_ignores_the_cursor_and_full_scans(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The explicit "Re-sync" button means START CLEAN, so never incremental.

    ``mode="rebuild"`` purges every auto row whose company is missing from the
    scan. Feeding it a three-message delta would wipe the board — so rebuild
    always re-lists the full window.
    """

    from jobtracker.cloud.gmail_client import HistoryPage

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg()],
        history_results=[HistoryPage(messages=[])],
        profile_ids=["9001", "9100"],
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)

    rebuilt = await client.post(
        "/gmail/sync", json={"mode": "rebuild"}, headers=headers
    )
    assert rebuilt.status_code == 200, rebuilt.text
    assert calls["history"] == 0
    assert calls["full"] == 2
    # It still records the run and re-baselines.
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9100"


async def test_explicit_range_forces_a_full_scan(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller who named a window asked for that window, not a delta."""

    from jobtracker.cloud.gmail_client import HistoryPage

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg()],
        history_results=[HistoryPage(messages=[])],
        profile_ids=["9001"],
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    await client.post("/gmail/sync", json={"range": "6"}, headers=headers)
    assert calls["history"] == 0
    assert calls["full"] == 2


async def test_items_relay_stamps_last_sync_but_never_baselines(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client-supplied mine records WHEN, never HOW FAR.

    The workbench's mine can be a narrower window than the server's own
    750-message scan, so baselining from it would permanently prevent the deeper
    scan from ever running again. ``last_sync_at`` is still honest.
    """

    await _connect_gmail(USER_A)
    _install_gmail_stubs(monkeypatch, profile_ids=["9001"])

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.post(
        "/gmail/sync", json={"items": _sync_items()}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    rows = await _sync_rows(USER_A)
    assert len(rows) == 1
    assert rows[0].last_sync_at is not None
    assert rows[0].gmail_history_id is None
    assert rows[0].status == "idle"

    status = (await client.get("/auth/gmail/status", headers=headers)).json()
    assert status["last_sync_at"] is not None
    assert status["has_cursor"] is False


async def test_disconnect_clears_the_cursor(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A historyId only means something against the mailbox that issued it.

    Surviving a disconnect, it would hand a re-linked account a foreign
    baseline — and an incremental sync from a foreign baseline skips mail.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    await _connect_gmail(USER_A)
    _install_gmail_stubs(
        monkeypatch, full_messages=[_applied_msg()], profile_ids=["9001"]
    )

    async def _no_revoke(token: str) -> bool:
        return True

    monkeypatch.setattr(gmail_module, "_revoke_at_google", _no_revoke)

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    assert len(await _sync_rows(USER_A)) == 1

    resp = await client.post("/auth/gmail/disconnect", headers=headers)
    assert resp.status_code == 200, resp.text
    assert await _sync_rows(USER_A) == []

    status = (await client.get("/auth/gmail/status", headers=headers)).json()
    assert status["connected"] is False
    assert status["has_cursor"] is False
    assert status["last_sync_at"] is None


async def test_disconnect_clears_the_cursor_even_with_no_stored_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clear happens BEFORE the "was not connected" early return."""

    import uuid as _uuid

    from jobtracker.credentials.cloud import delete_gmail_credentials

    await _connect_gmail(USER_A)
    _install_gmail_stubs(
        monkeypatch, full_messages=[_applied_msg()], profile_ids=["9001"]
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    assert len(await _sync_rows(USER_A)) == 1

    # The token is gone but the cursor row is not — the exact stale-row case.
    from jobtracker.database.connection import user_id_scope

    with user_id_scope(_uuid.UUID(USER_A)):
        await delete_gmail_credentials(_uuid.UUID(USER_A))

    resp = await client.post("/auth/gmail/disconnect", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked"] is False
    assert await _sync_rows(USER_A) == []


async def test_account_deletion_removes_sync_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sync_state`` is still purged by DELETE /account."""

    await _connect_gmail(USER_A)
    _install_gmail_stubs(
        monkeypatch, full_messages=[_applied_msg()], profile_ids=["9001"]
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    assert len(await _sync_rows(USER_A)) == 1

    resp = await client.delete("/account", headers=headers)
    assert resp.status_code == 200, resp.text
    assert await _sync_rows(USER_A) == []


async def test_sync_failure_records_error_and_does_not_advance_the_cursor(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed sync is recorded as one, and re-covers the same ground next time.

    ``last_sync_at`` must keep its old value (the UI renders it as "last synced
    …", which has to mean the last SUCCESS) and the cursor must not move, so the
    retry re-reads the window the failure interrupted.
    """

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg()],
        profile_ids=["9001", "9900"],
        history_error=RuntimeError("gmail exploded"),
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    before = (await _sync_rows(USER_A))[0]
    stamped_at, baseline = before.last_sync_at, before.gmail_history_id

    with pytest.raises(RuntimeError):
        await client.post("/gmail/sync", json={}, headers=headers)

    assert calls["history"] == 1
    row = (await _sync_rows(USER_A))[0]
    assert row.status == "error"
    assert row.error_message == "RuntimeError"  # type only — never a token-bearing repr
    assert row.gmail_history_id == baseline == "9001"
    assert row.last_sync_at == stamped_at

    status = (await client.get("/auth/gmail/status", headers=headers)).json()
    assert status["sync_status"] == "error"
    assert status["sync_error"] == "RuntimeError"


async def test_sync_without_gmail_connected_writes_no_cursor(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No linked address → nothing to key a cursor row on. Items still persist."""

    headers = {"Authorization": f"Bearer {_token_for(USER_B)}"}
    resp = await client.post(
        "/gmail/sync", json={"items": _sync_items()}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 2
    assert await _sync_rows(USER_B) == []


async def test_unavailable_baseline_is_logged_not_silently_normal(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A profile read that never succeeds must not look like healthy operation.

    ``fetch_mailbox_history_id`` degrades to ``None`` on any failure so a bad
    read cannot sink a sync. The trap is that a deployment where it fails
    *persistently* would full-scan forever while ``/auth/gmail/status`` cheerfully
    reports ``idle`` — the owner's original complaint, silently restored. The
    sync still succeeds; it just says so in the log.
    """

    import logging

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch, full_messages=[_applied_msg()], profile_ids=[None]
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.gmail_oauth"):
        resp = await client.post("/gmail/sync", json={}, headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1  # the sync itself still works
    assert calls["profile"] == 1
    assert any("cannot advance the cursor" in r.message for r in caplog.records)

    # The run is recorded, but honestly: no cursor, so the next sync is full.
    row = (await _sync_rows(USER_A))[0]
    assert row.last_sync_at is not None
    assert row.gmail_history_id is None
    status = (await client.get("/auth/gmail/status", headers=headers)).json()
    assert status["has_cursor"] is False


# =============================================================================
# The rebuild data-loss incident (2026-08-10)
# =============================================================================
#
# The owner pressed "Re-sync". Before: Anthropic, MotherDuck, Supabase. After:
# MotherDuck and Supabase were GONE from Postgres along with their emails. Both
# confirmations had been ARCHIVED, the rebuild's scan defaulted to ``in:inbox``,
# and the purge treated "absent from this scan" as "no longer exists".
#
# These tests pin the corrected reasoning: a scan may only remove a row whose
# own evidence it re-read and disagreed with. Absence proves nothing.


def _ats_msg(message_id: str, company: str, domain: str, day: int) -> Any:
    """A real ATS confirmation naming ``company`` — rolls up to one applied row."""

    return _msg(
        message_id,
        subject=f"We received your application to {company}",
        sender=f"careers@{domain}",
        snippet="Thank you for applying. Your application has been received.",
        day=day,
        name=company,
    )


async def _companies(client: AsyncClient, headers: dict) -> set[str]:
    listing = (await client.get("/applications", headers=headers)).json()
    return {a["company"].lower() for a in listing["applications"]}


async def test_rebuild_never_deletes_rows_the_scan_could_not_see(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REGRESSION — the exact incident. Three filed rows, a rebuild that sees one.

    Anthropic, MotherDuck and Supabase are filed from three real ATS
    confirmations. The user then archives the MotherDuck and Supabase mail, so
    the rebuild's scan returns ONLY the Anthropic message. Nothing may be
    removed: the scan never re-read the other two rows' evidence, so it holds no
    evidence about them at all.

    Against the pre-fix code this fails — MotherDuck and Supabase are deleted
    together with their emails, which is what happened in production.
    """

    import uuid as _uuid

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    filed = [
        _ats_msg("m-anthropic", "Anthropic", "anthropic.com", day=1),
        _ats_msg("m-motherduck", "MotherDuck", "motherduck.com", day=2),
        _ats_msg("m-supabase", "Supabase", "supabase.com", day=3),
    ]
    _install_gmail_stubs(monkeypatch, full_messages=filed, profile_ids=["9001"])
    first = await client.post("/gmail/sync", json={}, headers=headers)
    assert first.status_code == 200, first.text
    assert await _companies(client, headers) == {"anthropic", "motherduck", "supabase"}

    # The two confirmations are archived, so an ``in:inbox`` scan — and any
    # bounded scan that simply misses them — returns Anthropic alone.
    _install_gmail_stubs(monkeypatch, full_messages=[filed[0]], profile_ids=["9002"])
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert resp.status_code == 200, resp.text

    survived = await _companies(client, headers)
    assert survived == {"anthropic", "motherduck", "supabase"}, (
        "a rebuild deleted applications whose mail the scan never re-read — "
        "absence from a bounded scan is not evidence a row is stale"
    )
    assert resp.json()["purged"] == 0
    assert resp.json()["removed"] == []

    # The linked emails survive too — the incident took those with the rows.
    async with get_session() as session:
        message_ids = set(
            (
                await session.exec(
                    sm_select(Email.message_id).where(
                        Email.user_id == _uuid.UUID(USER_A)
                    )
                )
            ).all()
        )
    assert {"m-anthropic", "m-motherduck", "m-supabase"} <= message_ids


async def test_rebuild_does_not_destroy_review_items_the_scan_could_not_see(
    client: AsyncClient,
) -> None:
    """The same error, one table over: the queue is rebuilt, not emptied.

    ``_reset_review_queue`` used to DELETE every unlinked, un-reviewed Gmail
    email before re-persisting the scan's review items — so an uncertain
    message that an earlier, wider scan had surfaced was destroyed by any later
    rebuild whose window missed it. It is the incident's reasoning applied to
    the ``emails`` table directly, and it destroys rows that were never linked
    to an application at all (which is why the application-level regression
    test cannot catch it).
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    uncertain = {
        "message_id": "rv-archived",
        "category": "interview",
        "sender_email": "talent@replit.com",
        "subject": "About your background",
        "sender_name": "Replit",
        "confidence": 0.78,  # below the gate → review queue, never a row
        "received_at": "2026-05-25T09:00:00+00:00",
    }
    await client.post("/gmail/sync", json={"items": [uncertain]}, headers=headers)
    queue = (await client.get("/applications/review", headers=headers)).json()
    assert [i["message_id"] for i in queue["items"]] == ["rv-archived"]

    # A rebuild whose scan never re-read rv-archived (it was archived) must not
    # decide the question was resolved.
    resp = await client.post(
        "/gmail/sync",
        json={
            "items": _one_app_batch("m-aven", "aven.com", "Aven"),
            "mode": "rebuild",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    queue_after = (await client.get("/applications/review", headers=headers)).json()
    assert [i["message_id"] for i in queue_after["items"]] == ["rv-archived"], (
        "a rebuild deleted a queued message it never re-read"
    )


async def test_rebuild_clears_queue_items_the_scan_did_re_read(
    client: AsyncClient,
) -> None:
    """The queue still gets REBUILT — for the part of it the scan re-covered.

    The counterpart to the test above, and what keeps it honest: a message the
    scan re-read and now files confidently leaves the queue, exactly as before.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    uncertain = {
        "message_id": "rv-seen",
        "category": "interview",
        "sender_email": "talent@replit.com",
        "subject": "About your background",
        "sender_name": "Replit",
        "confidence": 0.78,
        "received_at": "2026-05-25T09:00:00+00:00",
    }
    await client.post("/gmail/sync", json={"items": [uncertain]}, headers=headers)
    assert (await client.get("/applications/review", headers=headers)).json()["total"] == 1

    # Re-read at high confidence: it becomes a real row and leaves the queue.
    resp = await client.post(
        "/gmail/sync",
        json={"items": [{**uncertain, "confidence": 0.95}], "mode": "rebuild"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get("/applications/review", headers=headers)).json()["total"] == 0
    assert "replit" in await _companies(client, headers)


async def test_rebuild_forces_anywhere_scope_whatever_the_caller_asks_for(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan that may REMOVE rows has to be able to see what it is judging.

    ``scope`` defaults to ``in:inbox``, which does not search archived mail —
    the direct cause of the incident. A routine sync may still be told which
    scope to use; a rebuild may not, because that choice decides what the purge
    is allowed to conclude.
    """

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import MessagePage

    queries: list[str] = []

    async def _fake_page(user_id, *, query, **_kwargs):
        queries.append(query)
        return MessagePage(
            messages=[_ats_msg("m-anthropic", "Anthropic", "anthropic.com", day=1)],
            next_page_token=None,
        )

    async def _fake_profile(user_id, **_kwargs):
        return "9001"

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)
    monkeypatch.setattr(gmail_client_module, "fetch_mailbox_history_id", _fake_profile)

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    # A routine sync is still the caller's to scope.
    resp = await client.post("/gmail/sync", json={"scope": "inbox"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert queries[-1].startswith("in:inbox")

    # A rebuild is not — even asked for ``inbox`` outright, it searches all mail.
    resp = await client.post(
        "/gmail/sync", json={"mode": "rebuild", "scope": "inbox"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert queries[-1].startswith("in:anywhere")


async def test_rebuild_keeps_a_row_whose_older_mail_the_scan_never_reached(
    client: AsyncClient,
) -> None:
    """Re-reading ONE of a row's messages does not license removing the row.

    Cedartech is filed from two messages: an April confirmation and a May
    interview. A rebuild whose scan only reaches back to May re-reads the May
    message and no longer files it — but the April message, which is the actual
    application confirmation, is older than anything the scan saw. Removing on
    that basis would be guessing about the half it never read.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    def _cedartech(message_id: str, category: str, received_at: str) -> dict:
        return {
            "message_id": message_id,
            "category": category,
            "sender_email": "careers@cedartech.com",
            "subject": f"{'We received your application to' if category == 'applied' else 'Interview with'} Cedartech",
            "sender_name": "Cedartech",
            "confidence": 0.95,
            "received_at": received_at,
        }

    filed = [
        _cedartech("m-old", "applied", "2026-04-01T09:00:00+00:00"),
        _cedartech("m-new", "interview", "2026-05-10T09:00:00+00:00"),
    ]
    await client.post("/gmail/sync", json={"items": filed}, headers=headers)
    assert "cedartech" in await _companies(client, headers)

    # Scan span is [2026-05-01, 2026-05-10] — m-old (April) is out of reach.
    shallow = await client.post(
        "/gmail/sync",
        json={
            "items": [
                *_one_app_batch("m-aven", "aven.com", "Aven"),
                _noise_item("m-new", "2026-05-10T09:00:00+00:00"),
            ],
            "mode": "rebuild",
        },
        headers=headers,
    )
    assert shallow.status_code == 200, shallow.text
    assert shallow.json()["purged"] == 0
    assert "cedartech" in await _companies(client, headers)

    # A scan that DID reach both messages, and files neither, has read the whole
    # case against the row — so this one removes it. (Which is what makes the
    # assertion above a real guard and not a coincidence.)
    deep = await client.post(
        "/gmail/sync",
        json={
            "items": [
                _noise_item("m-old", "2026-04-01T09:00:00+00:00"),
                _noise_item("m-new", "2026-05-10T09:00:00+00:00"),
                *_one_app_batch("m-aven", "aven.com", "Aven"),
            ],
            "mode": "rebuild",
        },
        headers=headers,
    )
    assert deep.json()["purged"] == 1
    assert [r["company"] for r in deep.json()["removed"]] == ["Cedartech"]
    assert "cedartech" not in await _companies(client, headers)


async def test_rebuild_keeps_an_auto_row_with_no_linked_mail(
    client: AsyncClient,
) -> None:
    """No linked email means no evidence to re-read — staleness is unprovable."""

    import uuid as _uuid

    from jobtracker.database import get_session
    from jobtracker.database.models import Application

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    async with get_session() as session:
        session.add(
            Application(
                user_id=_uuid.UUID(USER_A),
                company="Ghostco",
                position="",
                source="gmail",  # auto row, so purge-eligible in principle
            )
        )
        await session.commit()

    resp = await client.post(
        "/gmail/sync",
        json={
            "items": _one_app_batch("m-aven", "aven.com", "Aven"),
            "mode": "rebuild",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["purged"] == 0
    assert "ghostco" in await _companies(client, headers)


async def test_rebuild_reports_what_it_filed_and_what_it_removed(
    client: AsyncClient,
) -> None:
    """The counts the button renders: "N filed, M removed", with the names."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post(
        "/gmail/sync",
        json={"items": _one_app_batch("m-tcs", "tcs.com", "Tata")},
        headers=headers,
    )
    filed_company = (await client.get("/applications", headers=headers)).json()[
        "applications"
    ][0]["company"]

    resp = await client.post(
        "/gmail/sync",
        json={
            "items": [
                *_one_app_batch("m-aven", "aven.com", "Aven"),
                _noise_item("m-tcs"),
            ],
            "mode": "rebuild",
        },
        headers=headers,
    )
    body = resp.json()
    assert body["created"] == 1  # Aven filed
    assert body["purged"] == 1  # Tata removed
    assert body["applications"] == 1  # live rows only — the removed one is out
    assert [r["company"] for r in body["removed"]] == [filed_company]
    assert all(isinstance(r["id"], int) for r in body["removed"])


async def test_a_row_a_resync_removed_is_restorable_not_deleted(
    client: AsyncClient,
) -> None:
    """Removal is a state, so the wrong removal costs a click, not the data."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post(
        "/gmail/sync",
        json={"items": _one_app_batch("m-tcs", "tcs.com", "Tata")},
        headers=headers,
    )
    original = (await client.get("/applications", headers=headers)).json()[
        "applications"
    ][0]

    resp = await client.post(
        "/gmail/sync",
        json={
            "items": [
                *_one_app_batch("m-aven", "aven.com", "Aven"),
                _noise_item("m-tcs"),
            ],
            "mode": "rebuild",
        },
        headers=headers,
    )
    removed_id = resp.json()["removed"][0]["id"]
    assert removed_id == original["id"]

    # It is off the board but listed as removed, tagged with WHO removed it.
    removed_list = (
        await client.get("/applications?dismissed=true", headers=headers)
    ).json()
    assert [a["id"] for a in removed_list["applications"]] == [removed_id]
    assert removed_list["applications"][0]["dismissed_reason"] == "resync"
    assert removed_list["applications"][0]["dismissed_at"] is not None

    # Undo returns it verbatim — same id, status and filed date, mail intact.
    restored = await client.post(
        f"/applications/{removed_id}/restore", headers=headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["dismissed_at"] is None
    assert restored.json()["status"] == original["status"]
    assert restored.json()["applied_date"] == original["applied_date"]

    board = (await client.get("/applications", headers=headers)).json()
    assert removed_id in {a["id"] for a in board["applications"]}
    detail = (await client.get(f"/applications/{removed_id}", headers=headers)).json()
    assert [m["message_id"] for m in detail["messages"]] == ["m-tcs"]


async def test_user_dismiss_is_reversible_and_a_later_sync_does_not_refile_it(
    client: AsyncClient,
) -> None:
    """A human "not an application" outlives the classifier's opinion.

    Dismiss no longer deletes, so it has to keep the row off the board itself:
    a later scan that still calls the mail an application must not quietly put
    it back. Restoring is the user's call, not the sync's.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post(
        "/gmail/sync",
        json={"items": _one_app_batch("m-tcs", "tcs.com", "Tata")},
        headers=headers,
    )
    row = (await client.get("/applications", headers=headers)).json()["applications"][0]

    dismissed = await client.post(
        f"/applications/{row['id']}/dismiss", headers=headers
    )
    assert dismissed.status_code == 200
    assert dismissed.json() == {"dismissed": True, "restorable": True}
    assert await _companies(client, headers) == set()

    # The same mail, scanned again, does NOT resurrect it.
    await client.post(
        "/gmail/sync",
        json={"items": _one_app_batch("m-tcs", "tcs.com", "Tata")},
        headers=headers,
    )
    assert await _companies(client, headers) == set()
    removed_list = (
        await client.get("/applications?dismissed=true", headers=headers)
    ).json()
    assert removed_list["applications"][0]["dismissed_reason"] == "user"

    # But the user can take it back, because nothing was destroyed.
    assert (
        await client.post(f"/applications/{row['id']}/restore", headers=headers)
    ).status_code == 200
    assert row["company"].lower() in await _companies(client, headers)


async def test_dismissed_rows_are_out_of_the_summary_tiles(
    client: AsyncClient,
) -> None:
    """A removed row must not keep counting in the funnel it left."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    before = (await client.get("/applications/summary", headers=headers)).json()
    assert before["total"] == 2

    stripe = next(
        a
        for a in (await client.get("/applications", headers=headers)).json()[
            "applications"
        ]
        if a["company"] == "Stripe"
    )
    await client.post(f"/applications/{stripe['id']}/dismiss", headers=headers)

    after = (await client.get("/applications/summary", headers=headers)).json()
    assert after["total"] == 1
    assert "applied" not in after["status_counts"]  # Stripe was the only one
    assert after["this_week"] == before["this_week"] - 1


async def test_setting_a_status_on_a_removed_row_brings_it_back(
    client: AsyncClient,
) -> None:
    """A correction must not land on a row nobody can see.

    Without this, patching a dismissed row left it hidden, sticky and tagged
    user-owned — invisible on the board and now immune to the sync that would
    otherwise have restored it. Deciding an application's stage is a statement
    that you want it.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    created = await client.post(
        "/applications", json={"company": "Acme", "position": "SWE"}, headers=headers
    )
    row_id = created.json()["id"]
    await client.post(f"/applications/{row_id}/dismiss", headers=headers)
    assert await _companies(client, headers) == set()

    patched = await client.patch(
        f"/applications/{row_id}", json={"status": "interviewing"}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["dismissed_at"] is None
    assert patched.json()["status"] == "interviewing"
    assert "acme" in await _companies(client, headers)


async def test_restore_is_scoped_to_the_owner(client: AsyncClient) -> None:
    """Another user's row is a 404, restored or not."""

    a_headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    b_headers = {"Authorization": f"Bearer {_token_for(USER_B)}"}
    created = await client.post(
        "/applications", json={"company": "Acme", "position": "SWE"}, headers=a_headers
    )
    row_id = created.json()["id"]

    assert (
        await client.post(f"/applications/{row_id}/restore", headers=b_headers)
    ).status_code == 404
    assert (await client.post(f"/applications/{row_id}/restore")).status_code == 401


# =============================================================================
# POST /applications — the hand-filed row keeps its date and its link
# =============================================================================


async def test_manual_create_persists_applied_date_and_url(
    client: AsyncClient,
) -> None:
    """The dialog collects a date and a link; both used to be dropped.

    ``CloudApplicationCreate`` accepted only company/position/status/notes, so
    the web form stringified the other two into ``notes``. They round-trip now,
    under the same names the response emits.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.post(
        "/applications",
        json={
            "company": "Acme",
            "position": "Backend Engineer",
            "applied_date": "2026-08-10",
            "url": "https://boards.greenhouse.io/acme/jobs/42",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["applied_date"] == "2026-08-10"
    assert resp.json()["url"] == "https://boards.greenhouse.io/acme/jobs/42"

    # And they are actually in the row, not just echoed back.
    listed = (await client.get("/applications", headers=headers)).json()[
        "applications"
    ][0]
    assert listed["applied_date"] == "2026-08-10"
    assert listed["url"] == "https://boards.greenhouse.io/acme/jobs/42"


async def test_manual_create_without_the_new_fields_is_unchanged(
    client: AsyncClient,
) -> None:
    """Omitting them behaves exactly as before — both null, row still manual."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.post(
        "/applications",
        json={"company": "Acme", "position": "Backend Engineer"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["applied_date"] is None
    assert resp.json()["url"] is None
    assert resp.json()["source"] == "manual"


async def test_manual_create_rejects_a_malformed_date_visibly(
    client: AsyncClient,
) -> None:
    """A date we cannot parse is a 422 — silently dropping it IS the old bug."""

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.post(
        "/applications",
        json={"company": "Acme", "position": "SWE", "applied_date": "10/08/2026"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "applied_date" in resp.json()["detail"]
    assert (await client.get("/applications", headers=headers)).json()["total"] == 0

    # A full ISO timestamp (Date.toISOString()) is accepted and truncated.
    ok = await client.post(
        "/applications",
        json={
            "company": "Acme",
            "position": "SWE",
            "applied_date": "2026-08-10T14:03:00Z",
        },
        headers=headers,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["applied_date"] == "2026-08-10"
