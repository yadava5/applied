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


async def test_auto_sync_is_additive_only_rebuild_purges(client: AsyncClient) -> None:
    """A routine (additive) sync must NEVER drop an app the current scan missed.

    Reproduces the data-loss bug: TCS is filed by one scan, then a later scan
    whose bounded window doesn't re-include TCS ran and erased it. Additive mode
    must keep TCS; only the explicit rebuild may clear it.
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

    # Only an EXPLICIT rebuild replaces the board — TCS (absent from this scan) clears.
    respC = await client.post(
        "/gmail/sync",
        json={"items": _one_app_batch("m-aven", "aven.com", "Aven"), "mode": "rebuild"},
        headers=headers,
    )
    assert respC.status_code == 200, respC.text
    assert respC.json()["purged"] >= 1
    listC = (await client.get("/applications", headers=headers)).json()
    companies_C = {a["company"] for a in listC["applications"]}
    assert tcs_company not in companies_C
    assert listC["total"] == 1


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
    from jobtracker.database import get_session
    from jobtracker.database.models import TrainingData
    from sqlmodel import select as sm_select

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
    from jobtracker.database import get_session
    from jobtracker.database.models import TrainingData
    from sqlmodel import select as sm_select

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

    # Only an EXPLICIT rebuild (the Re-sync button) purges the stale AUTO row,
    # while the manual row survives untouched.
    resp = await client.post(
        "/gmail/sync", json={"items": only_stripe, "mode": "rebuild"}, headers=headers
    )
    assert resp.json()["purged"] == 1
    companies2 = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert "Airbnb" not in companies2  # stale auto row gone (rebuild only)
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
