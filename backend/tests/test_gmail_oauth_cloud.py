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

# An origin this deployment has never heard of. A whole ORIGIN and not a bare
# hostname, because that is what the refusal has to name: acceptance #2 of #333
# asks for the offending origin in the message, and asserting a domain
# *substring* would also pass on a message that named
# `https://evil.example.com.getapplied.vercel.app`.
HOSTILE_ORIGIN = "https://evil.example.com"
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
async def cloud_app(monkeypatch: pytest.MonkeyPatch, request: Any) -> AsyncIterator[Any]:
    """Cloud app configured with Gmail OAuth env + in-memory DB.

    Mirrors the proven reload sequence in ``test_user_id_scoping`` and adds
    the Gmail OAuth env vars plus a reload of ``jobtracker.cloud.gmail_oauth``
    so the router binds to the freshly-reloaded settings.

    Indirectly parametrizable with the value of ``JOBTRACKER_WEB_APP_URL``, so
    a test can ask for the deployment that no longer sets it at all (#333).
    That case has to be reachable from HERE rather than from a unit test: the
    claim is that the whole round trip works without the variable, and the only
    way to be sure ``_web_app_base`` is not still on the success path is to
    make it raise if it is reached.
    """

    web_app_url = getattr(request, "param", WEB_APP_URL)

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", ENC_KEY)
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("JOBTRACKER_GOOGLE_OAUTH_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("JOBTRACKER_GMAIL_OAUTH_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("JOBTRACKER_WEB_APP_URL", web_app_url)
    # The callback now refuses to bounce the browser to a host this deployment
    # does not already trust as its front end (see
    # `config.trusted_web_hosts` and `test_gmail_oauth_return_host.py`), so the
    # fixture has to DECLARE that host rather than merely name it in one place.
    # That is the point of the change: the two facts must be stated together.
    #
    # `api.example.test` — this fixture's own REDIRECT_URI host — is declared
    # alongside it deliberately. On the real deployment the API's hostnames are
    # in the trusted list because Vercel injects them and CORS is built from
    # the same list; there is no `VERCEL_*` here, so declaring it is how that
    # shape is reproduced. Without it the "returning the browser to the API
    # strands it" test would be refused by the ALLOWLIST rather than by the
    # self-check it exists to exercise, and would pass with that check deleted.
    monkeypatch.setenv("JOBTRACKER_CORS_ALLOWED_HOSTS", "web.example.test,api.example.test")
    # Pinned rather than inherited: these are what make a host "the API", and a
    # value leaking in from the surrounding environment would silently change
    # which origins the tests below expect to be refused.
    monkeypatch.setenv("VERCEL_URL", "")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "")

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


# ── #333: the caller's own origin, over real HTTP ─────────────────────────


async def test_authorize_carries_the_callers_origin_in_the_state(
    client: AsyncClient,
) -> None:
    """A trusted `return_origin` reaches the state, canonicalised.

    The claim is deliberately NOT encrypted the way `cv` is — the origin is the
    address bar the user is looking at, not a secret — so it can be read
    straight off the decoded state here, which is also how it is read when
    debugging a redirect in production.
    """

    resp = await client.get(
        "/auth/gmail/authorize",
        params={"return_origin": f"{WEB_APP_URL}/"},
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    state = urllib.parse.parse_qs(
        urllib.parse.urlparse(resp.json()["authorization_url"]).query
    )["state"][0]

    decoded = pyjwt.decode(
        state,
        ENC_KEY,
        algorithms=["HS256"],
        audience="jobtracker:gmail-oauth-state",
    )
    assert decoded["ro"] == WEB_APP_URL, (
        "the trailing slash must be normalised away by the backend, not "
        "carried into a Location header"
    )


async def test_authorize_refuses_an_untrusted_origin_before_google(
    client: AsyncClient,
) -> None:
    """ACCEPTANCE #2. Refused at `/authorize`, with the origin named.

    "Before Google is ever reached" is asserted by the absence of a consent
    URL in the response, not by trusting the reading of the source: a 400 body
    carries no `authorization_url`, so nothing was minted and the user is told
    at the click rather than after consenting.

    400 and not 503 matters at this seam specifically: `lib/gmail/server.ts`
    maps 503 to "Gmail isn't enabled on this deployment yet", which for a bad
    origin is both wrong and actionless.
    """

    resp = await client.get(
        "/auth/gmail/authorize",
        params={"return_origin": HOSTILE_ORIGIN},
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "authorization_url" not in body
    assert HOSTILE_ORIGIN in body["detail"]


async def test_authorize_refuses_the_apis_own_origin(client: AsyncClient) -> None:
    """ACCEPTANCE #4. The stranded-on-the-backend case, over HTTP.

    `api.example.test` IS in this deployment's trusted list (see the fixture,
    which reproduces why: CORS and the return host read one list, and the API's
    own hostnames belong on it). It is still refused, because the API serves no
    `/settings` and returning the browser there is the same broken outcome as
    an unset return host wearing a different costume.
    """

    api_origin = f"https://{urllib.parse.urlparse(REDIRECT_URI).hostname}"
    resp = await client.get(
        "/auth/gmail/authorize",
        params={"return_origin": api_origin},
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )

    assert resp.status_code == 400, resp.text
    assert "api.example.test" in resp.json()["detail"]


@pytest.mark.parametrize("cloud_app", [""], indirect=True)
async def test_the_round_trip_returns_to_the_caller_with_web_app_url_unset(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ACCEPTANCE #1. Connect works with JOBTRACKER_WEB_APP_URL unset entirely.

    Proved through the CALLBACK, not at `/authorize`: a 200 from `/authorize`
    would say nothing about whether `_web_app_base` is still on the success
    path. Here the variable is empty, so that helper raises 503 if it is
    reached at all — the redirect below can only come from the origin carried
    in the state.
    """

    from datetime import datetime, timedelta

    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.credentials.types import GmailCredentials

    resp = await client.get(
        "/auth/gmail/authorize",
        params={"return_origin": WEB_APP_URL},
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
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

    monkeypatch.setattr(gmail_module, "_exchange_code", _fake_exchange)

    resp = await client.get(
        "/auth/gmail/callback",
        params={"code": "auth-code-from-google", "state": state},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{WEB_APP_URL}/settings?gmail=connected"


@pytest.mark.parametrize("cloud_app", [""], indirect=True)
async def test_with_web_app_url_unset_a_stateless_callback_still_refuses_loudly(
    client: AsyncClient,
) -> None:
    """The other half of ACCEPTANCE #1, so it is not read as "unset is fine".

    A callback whose state cannot be read carries no origin, and there is
    genuinely nowhere to send the browser. It must 503 with the operator
    message rather than degrade into the RELATIVE `/settings?...` the old code
    produced — which the browser resolved against the API's own host, stranding
    the user on a backend with no such page. Silent wrong answers are the
    failure mode this whole area is about.
    """

    resp = await client.get(
        "/auth/gmail/callback",
        params={"code": "irrelevant", "state": "not-a-valid-token"},
    )

    assert resp.status_code == 503, resp.text
    assert "JOBTRACKER_WEB_APP_URL" in resp.json()["detail"]


@pytest.mark.parametrize("cloud_app", [""], indirect=True)
async def test_status_is_configured_without_the_web_app_url(
    client: AsyncClient,
) -> None:
    """The variable is off the "required to offer Gmail" list, and must be.

    Leaving it there would make the deployment report itself unconfigured — a
    503 naming a variable the flow no longer needs — which is exactly the kind
    of untrue requirement #333 exists to remove.
    """

    resp = await client.get(
        "/auth/gmail/status",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["configured"] is True


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
    # The exact wire shape. Pinned as a SET so a field added to the model is a
    # deliberate edit here, not something that appears unannounced — the scan
    # view's client type is hand-maintained and has to be moved in step.
    # ``snippet`` is Gmail's own preview (the text the verdict was made from),
    # never a full body; the two dedicated tests below cover its content.
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
        "snippet",
        "gmail_link",
    }
    # Newsletter/digest content is guarded to OTHER.
    assert by_id["m2"]["category"] == "other"


async def test_inbox_verdict_carries_snippet_and_deep_link(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mined row ships the preview it was judged from, and a way to open it.

    Without these the live-scan view asked the reader to confirm or correct a
    verdict having shown them only a subject and a sender — no content, no
    link. The preview arrives UNESCAPED (Gmail sends ``&#39;``; rendering the
    entity verbatim is a bug already fixed once on the board) and the link
    selects the connected account with ``authuser`` rather than the positional
    ``/u/0/`` slot, which is the first account in the browser session and so
    the wrong inbox for anyone signed into several.
    """

    from datetime import datetime

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

    await _connect_gmail(USER_A)

    async def _fake_page(user_id, **_kwargs):
        return MessagePage(
            messages=[
                CloudGmailMessage(
                    message_id="m1",
                    thread_id="t1",
                    subject="Thanks for applying to Acme",
                    sender_name="Acme Recruiting",
                    sender_email="careers@acme.test",
                    snippet="We&#39;ve received your application and will be in touch.",
                    received_at=datetime(2026, 7, 1, 12, 0, 0),
                )
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    resp = await client.get(
        "/gmail/inbox",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    verdict = resp.json()["verdicts"][0]

    assert verdict["snippet"] == "We've received your application and will be in touch."
    # The conversation, not the message: `#all/` reaches archived mail too.
    assert verdict["gmail_link"] == (
        f"https://mail.google.com/mail/?authuser={urllib.parse.quote(GMAIL_ADDRESS)}"
        "#all/t1"
    )


async def test_inbox_snippet_is_null_when_absent_and_bounded_when_long(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The preview is null when there is none, and 500 chars at most.

    Null rather than ``""`` because a client must be able to tell "this message
    has no preview" from "here is an empty preview" — the row renders nothing
    for null instead of drawing a blank line under the subject. The 500-char
    bound is the same one the store applies to ``body_snippet``, so a message
    reads identically whether it was mined or filed.
    """

    from datetime import datetime

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import CloudGmailMessage, MessagePage

    await _connect_gmail(USER_A)

    async def _fake_page(user_id, **_kwargs):
        return MessagePage(
            messages=[
                CloudGmailMessage(
                    message_id="empty",
                    thread_id="t-empty",
                    subject="Interview scheduling",
                    sender_name="Acme",
                    sender_email="careers@acme.test",
                    snippet="",
                    received_at=datetime(2026, 7, 1, 12, 0, 0),
                ),
                CloudGmailMessage(
                    message_id="long",
                    thread_id="t-long",
                    subject="Interview scheduling",
                    sender_name="Acme",
                    sender_email="careers@acme.test",
                    snippet="x" * 900,
                    received_at=datetime(2026, 7, 1, 12, 0, 0),
                ),
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    resp = await client.get(
        "/gmail/inbox",
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert resp.status_code == 200, resp.text
    by_id = {v["message_id"]: v for v in resp.json()["verdicts"]}

    assert by_id["empty"]["snippet"] is None
    # A message with no preview is still openable — the link is independent.
    assert by_id["empty"]["gmail_link"].endswith("#all/t-empty")
    assert by_id["long"]["snippet"] == "x" * 500


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
    #
    # `-in:sent` rides along on `anywhere`, and this surface wants it for the
    # same reason the scan does. The endpoint's own contract says `anywhere`
    # exists "so filed-away interview & offer emails are found" — INBOUND mail.
    # The workbench is where a human files mail by hand, so showing them their
    # own outreach here would just move the defect from the classifier to the
    # user: the four rows that exposed this were his own sent messages, and
    # they read like applications to a person too.
    assert captured["query"] == "in:anywhere -in:sent newer_than:6m"
    assert captured["page_token"] == "ABC"
    assert captured["page_size"] == 200

    body = resp.json()
    assert body["scope"] == "anywhere"
    assert body["range_months"] == 6
    assert body["next_page_token"] == "TOK2"
    assert body["query"] == "in:anywhere -in:sent newer_than:6m"


async def test_inbox_reports_unreadable_messages_and_the_size_estimate(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page tells the caller what it lost and roughly how much is out there.

    ``scanned`` counts what was read. On its own that is a smaller number
    presented as the whole, so ``unreadable`` travels with it — and Gmail's own
    ``resultSizeEstimate`` comes through as the (approximate) denominator a
    progress readout needs.
    """

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import MessagePage

    async def _fake_page(user_id, *, query, page_size, page_token):
        return MessagePage(
            messages=[],
            next_page_token=None,
            unreadable=60,
            result_size_estimate=2000,
        )

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    resp = await client.get(
        "/gmail/inbox", headers={"Authorization": f"Bearer {_token_for(USER_A)}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["unreadable"] == 60
    assert body["result_size_estimate"] == 2000

    # Defaults stay honest when the transport says nothing about either.
    async def _quiet_page(user_id, *, query, page_size, page_token):
        return MessagePage(messages=[], next_page_token=None)

    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _quiet_page)
    quiet = await client.get(
        "/gmail/inbox?range=6",  # a different cache key, so not the entry above
        headers={"Authorization": f"Bearer {_token_for(USER_A)}"},
    )
    assert quiet.json()["unreadable"] == 0
    assert quiet.json()["result_size_estimate"] is None


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


def _noise_msg(message_id: str, day: int) -> Any:
    """:func:`_noise_item`'s server-scan twin — the same message, re-fetched.

    A rebuild can only run as a server-side scan now, so contradiction evidence
    has to arrive as a Gmail message rather than a relayed verdict. The real
    rules classifier calls this ``other`` at 0.50, so it rolls up to nothing and
    is not review-worthy: it contributes exactly its id and its date to the
    scan's coverage, which is what makes it evidence AGAINST a row filed from
    the same id.
    """

    return _msg(
        message_id,
        subject="Hire pre-vetted developers",
        sender="news@turing.com",
        snippet="Hire pre-vetted developers from Turing, on demand.",
        day=day,
        name="Turing",
    )


async def test_auto_sync_is_additive_and_rebuild_purges_only_contradicted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither sync mode may drop an app on the strength of a scan's silence.

    Was ``test_auto_sync_is_additive_only_rebuild_purges``, which asserted that
    an explicit rebuild clears a row the scan simply didn't re-include. That is
    the reasoning that deleted two real applications on 2026-08-10, so the
    expectation is corrected here: a rebuild that never re-read m-tcs removes
    nothing, and only one that re-read it and no longer files it may clear TCS.

    Every rebuild here drives the SERVER-side scan, because relayed ``items``
    can no longer be a rebuild at all (a client picks its own scope, so its
    coverage cannot license a purge). The additive halves still relay items —
    that path is untouched.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    tcs_msg = _ats_msg("m-tcs", "Tata", "tcs.com", day=1)
    aven_msg = _ats_msg("m-aven", "Aven", "aven.com", day=2)

    # Sync A (additive by default) files TCS.
    _install_gmail_stubs(monkeypatch, full_messages=[tcs_msg], profile_ids=["9001"])
    respA = await client.post("/gmail/sync", json={}, headers=headers)
    assert respA.status_code == 200, respA.text
    listA = (await client.get("/applications", headers=headers)).json()
    assert listA["total"] == 1
    tcs_company = listA["applications"][0]["company"]

    # Sync B (additive) scans a DIFFERENT window — only Aven, TCS not included.
    _install_gmail_stubs(monkeypatch, full_messages=[aven_msg], profile_ids=["9002"])
    respB = await client.post("/gmail/sync", json={}, headers=headers)
    assert respB.status_code == 200, respB.text
    assert respB.json()["purged"] == 0  # additive removes nothing
    listB = (await client.get("/applications", headers=headers)).json()
    companies_B = {a["company"] for a in listB["applications"]}
    # DURABLE: TCS survived a scan that never mentioned it; Aven was added.
    assert tcs_company in companies_B
    assert listB["total"] == 2

    # A rebuild that merely fails to mention TCS removes NOTHING. Absence is
    # not evidence, whichever mode asked the question.
    respC = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert respC.status_code == 200, respC.text
    assert respC.json()["purged"] == 0
    listC = (await client.get("/applications", headers=headers)).json()
    assert tcs_company in {a["company"] for a in listC["applications"]}

    # A rebuild that RE-READ m-tcs and now calls it marketing has actually
    # contradicted the row — that, and only that, clears TCS.
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[aven_msg, _noise_msg("m-tcs", day=1)],
        profile_ids=["9003"],
    )
    respD = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
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


async def test_status_correction_is_sticky_through_resync_and_labels_no_mail(
    client: AsyncClient,
) -> None:
    """A stage correction settles the ROW and says nothing about its messages.

    It used to write a ``training_data`` example for every linked email, read
    off the new stage — which is how an assessment invite entered the corpus as
    a ``rejection``. See ``tests/test_training_corpus_integrity.py``.
    """

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email, EmailCategory, TrainingData

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

    async with get_session() as session:
        labels = (await session.exec(sm_select(TrainingData.label))).all()
        assert list(labels) == []  # no per-message label was manufactured
        email = (
            await session.exec(
                sm_select(Email).where(Email.message_id == "m-airbnb")
            )
        ).first()
    # The message is still what the classifier said it was, and is not flagged
    # as human-judged — flagging it would freeze it against re-classification.
    assert email is not None
    assert email.classified_as == EmailCategory.INTERVIEW
    assert email.user_corrected is False and email.is_reviewed is False

    # A re-sync (mail still says 'interviewing') must NOT overwrite the decision.
    await client.post("/gmail/sync", json={"items": _owner_batch()}, headers=headers)
    listing2 = (await client.get("/applications", headers=headers)).json()
    airbnb2 = next(a for a in listing2["applications"] if a["company"] == "Airbnb")
    assert airbnb2["status"] == "rejected"


async def test_dismiss_removes_row_without_relabelling_its_mail(
    client: AsyncClient,
) -> None:
    """Dismissal is a statement about the ROW, and it is reversible.

    It used to write an ``other`` example per linked email while leaving each
    email's stored classification untouched, so the corpus and the database
    disagreed about the same message. Making them agree would mean flagging the
    mail user-corrected, which freezes it — a bad trade on an action ``restore``
    can undo. See ``tests/test_training_corpus_integrity.py``.
    """

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email, EmailCategory, TrainingData

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
        assert list(labels) == []
        email = (
            await session.exec(
                sm_select(Email).where(Email.message_id == "m-stripe")
            )
        ).first()
    assert email is not None
    assert email.classified_as == EmailCategory.APPLIED
    assert email.user_corrected is False and email.is_reviewed is False


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


# ---------------------------------------------------------------------------
# "None of these" has to survive the HTTP boundary (#554)
#
# `backend/tests/test_none_of_these_opens_a_row.py` proves what
# `classify_review_item` DOES with the flag, and the web unit tests prove the
# browser and the proxy both build it. Between those two fronts sit three
# rebuilds nothing executes in CI: the Next route handler, `classifyReviewItem`,
# and `classify_review_item_cloud`'s own re-spread of `data` into arguments.
#
# That gap is not theoretical. Deleting `none_of_these=data.none_of_these` from
# the endpoint leaves every one of those tests green — the flag never reaches the
# function, "none of these" silently degrades to the oldest-row tie-break, and
# #554 is back in production with a green board. Three fields have already been
# lost on a hop exactly like it (`confidence`, `applied_date`, `url`), and a
# fourth (`confirm_new_company`) was lost on the two hops above it.
#
# So these two tests go over HTTP, against the real app, and they are a PAIR:
# one asserts the flag changes the outcome, the other asserts it is the flag
# doing it and not the endpoint having stopped resolving altogether.
# ---------------------------------------------------------------------------


async def _two_northwind_rows_and_a_blind_review_item(
    client: AsyncClient, headers: dict[str, str], message_id: str
) -> list[int]:
    """Two applications at one employer, and a held message naming no role."""

    ids = []
    for position in ("Backend Engineer", "Platform Engineer"):
        created = await client.post(
            "/applications",
            json={"company": "Northwind", "position": position},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])

    relayed = [
        {
            "message_id": message_id,
            "category": "needs_review",
            "sender_email": "talent@northwind.com",
            "sender_name": "Northwind",
            # Names no role anywhere the resolver can reach — which is the whole
            # reason a message like this reaches the picker.
            "subject": "Update on your application",
            "confidence": 0.62,
            "received_at": "2026-05-25T09:00:00+00:00",
        }
    ]
    synced = await client.post("/gmail/sync", json={"items": relayed}, headers=headers)
    assert synced.status_code == 200, synced.text
    return ids


async def _northwind_rows(client: AsyncClient, headers: dict[str, str]) -> list[dict]:
    listing = (await client.get("/applications", headers=headers)).json()
    return [a for a in listing["applications"] if a["company"].lower() == "northwind"]


async def test_none_of_these_reaches_the_backend_and_opens_a_row(
    client: AsyncClient,
) -> None:
    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    existing = await _two_northwind_rows_and_a_blind_review_item(client, headers, "rv-none")

    resp = await client.post(
        "/applications/review/rv-none/classify",
        json={"category": "rejection", "none_of_these": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    filed = resp.json()["application_id"]
    assert filed is not None
    assert filed not in existing, (
        "the user said none of these and the message was filed onto one of them "
        "— the flag did not reach classify_review_item"
    )

    rows = await _northwind_rows(client, headers)
    assert len(rows) == 3, "the answer opens the row the board was missing"
    for row in rows:
        if row["id"] in existing:
            assert row["status"] == "applied", (
                f"application {row['id']} was moved to {row['status']} by a "
                "message the user said was not about it"
            )


async def test_without_the_flag_the_same_request_settles_an_existing_row(
    client: AsyncClient,
) -> None:
    """The control. Same fixture, same endpoint, the flag removed.

    Without this the test above passes whenever the endpoint mints — including
    when it has stopped resolving for some unrelated reason — and would say
    nothing about the flag.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    existing = await _two_northwind_rows_and_a_blind_review_item(client, headers, "rv-silent")

    resp = await client.post(
        "/applications/review/rv-silent/classify",
        json={"category": "rejection"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["application_id"] in existing, (
        "silence must still resolve onto an existing row; the fix separates the "
        "ANSWER from silence, it does not change what silence means"
    )
    assert len(await _northwind_rows(client, headers)) == 2, "silence opens nothing"


async def test_the_chosen_application_reaches_the_backend_too(
    client: AsyncClient,
) -> None:
    """The picker's OTHER answer crosses the same seam, and had the same hole.

    Found by mutating the endpoint after the two tests above landed: replacing
    `application_id=data.application_id` with `None` left every test green. The
    suite's existing `test_the_users_choice_of_application_is_honoured` calls
    `_chosen_application` directly and never invokes the endpoint, so the whole
    picker could become decoration without a single red.

    The SECOND row is chosen deliberately. The failure this guards is filing onto
    the employer's oldest, so choosing the first would be satisfied by the bug.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    existing = await _two_northwind_rows_and_a_blind_review_item(client, headers, "rv-pick")
    chosen = existing[1]

    resp = await client.post(
        "/applications/review/rv-pick/classify",
        json={"category": "rejection", "application_id": chosen},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["application_id"] == chosen, (
        "the user picked a row and the message landed somewhere else — the id "
        "did not reach classify_review_item"
    )

    rows = {r["id"]: r for r in await _northwind_rows(client, headers)}
    assert len(rows) == 2, "a pick resolves; it does not open a row"
    assert rows[chosen]["status"] == "rejected"
    assert rows[existing[0]]["status"] == "applied", "the oldest row was not the answer"


async def test_the_flag_is_not_manufactured_at_the_api_boundary(
    client: AsyncClient,
) -> None:
    """A truthy value is not a person clicking "none of these".

    The "only a literal true" rule is enforced in the proxy's `readClassifyBody`,
    which a caller reaching this API directly never passes through. `StrictBool`
    is what makes the rule hold here too — without it Pydantic coerces, and the
    string "false" is truthy.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await _two_northwind_rows_and_a_blind_review_item(client, headers, "rv-coerce")

    for raw in ["true", "false", 1, "1"]:
        resp = await client.post(
            "/applications/review/rv-coerce/classify",
            json={"category": "rejection", "none_of_these": raw},
            headers=headers,
        )
        assert resp.status_code == 422, (
            f"none_of_these={raw!r} was accepted as an answer: {resp.text}"
        )

    # CONTROL — a real boolean is still an answer. Without this, a validator that
    # refused everything would satisfy the loop above and break the feature.
    ok = await client.post(
        "/applications/review/rv-coerce/classify",
        json={"category": "rejection", "none_of_these": True},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert len(await _northwind_rows(client, headers)) == 3


async def test_confirm_new_company_is_not_manufactured_either(
    client: AsyncClient,
) -> None:
    """The OTHER flag on this model, and it had the annotation but no gate.

    `none_of_these` and `confirm_new_company` are both `StrictBool` for one
    stated reason — "one of these flags skips the typo check and the other OPENS
    A ROW; neither may be manufactured" — and only the row-opening half was
    asserted. Relaxing `confirm_new_company` back to `bool` left the entire
    suite green, so the rule was half a rule.

    This is the cheaper half: skipping the near-miss confirmation opens a second
    application under a misspelling rather than destroying one. It is still the
    check that exists because a "Verkeda" row was once opened silently.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await _two_northwind_rows_and_a_blind_review_item(client, headers, "rv-cnc")

    for raw in ["true", "false", 1, "1"]:
        resp = await client.post(
            "/applications/review/rv-cnc/classify",
            json={"category": "rejection", "confirm_new_company": raw},
            headers=headers,
        )
        assert resp.status_code == 422, (
            f"confirm_new_company={raw!r} was accepted as an answer: {resp.text}"
        )

    # CONTROL — a real boolean is still an answer, and the request still files.
    ok = await client.post(
        "/applications/review/rv-cnc/classify",
        json={"category": "rejection", "confirm_new_company": True},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------------------
# The two arguments #558 left behind (#562)
#
# Same seam, same shape of hole. `classify_review_item_cloud` rebuilds the
# parsed body into keyword arguments, and a field deleted from that rebuild is
# a field `classify_review_item` never sees. #558 closed `none_of_these` and
# `application_id`; the two below were still one-line deletions.
#
# `confirm_new_company` is the one that was genuinely uncovered: deleting
# `confirm_new_company=data.confirm_new_company` leaves this file, the web unit
# suite and every e2e spec green. It is also the field that has ALREADY been
# lost once, on the two proxy hops above this one — which is why
# `classify-request.ts` exists as a separately-testable module.
#
# `scanned=data.message` was NOT in that state, and this comment is where that
# is recorded rather than repeated as folklore: `tests/test_scan_classify.py`
# drives this endpoint over HTTP with a `message` payload, and deleting the
# argument reds six of its tests. Its pair is kept here anyway, stated
# beside the review-queue surface it shares an endpoint with, and it says in
# its own docstring which file owns the claim.
# ---------------------------------------------------------------------------


async def _one_northwind_row_and_a_relayed_review_item(
    client: AsyncClient, headers: dict[str, str], message_id: str
) -> int:
    """One application at "Northwind", and a held message naming no employer.

    The relay sender is the whole fixture. `no-reply@greenhouse-mail.io` behind
    its own display name names nobody, so classify has to fall back to the
    caller's `company` — and only a HAND-TYPED name is ever asked about (see
    `named_by_hand` in `classify_review_item`). A message from the employer's
    own domain resolves itself and never reaches the question.
    """

    created = await client.post(
        "/applications",
        json={"company": "Northwind", "position": "Backend Engineer"},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    relayed = [
        {
            "message_id": message_id,
            "category": "needs_review",
            "sender_email": "no-reply@greenhouse-mail.io",
            "sender_name": "Greenhouse",
            "subject": "Update on your application",
            "confidence": 0.62,
            "received_at": "2026-05-25T09:00:00+00:00",
        }
    ]
    synced = await client.post("/gmail/sync", json={"items": relayed}, headers=headers)
    assert synced.status_code == 200, synced.text
    return created.json()["id"]


async def _board(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict]:
    """The board by employer name — these tests turn on WHICH names are on it."""

    listing = (await client.get("/applications", headers=headers)).json()
    return {a["company"]: a for a in listing["applications"]}


async def test_confirm_new_company_reaches_the_backend_and_opens_the_second_row(
    client: AsyncClient,
) -> None:
    """Defends `confirm_new_company=data.confirm_new_company` in the endpoint.

    Delete that line and the human's answer to "did you mean the one already on
    your board?" never arrives: the re-POST is read as the first POST all over
    again, so "no, a different company" re-asks forever and an employer one edit
    from one already on the board can never be filed from the review queue at
    all. The user loses the row, not just the prompt.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await _one_northwind_row_and_a_relayed_review_item(client, headers, "rv-confirm")

    asked = await client.post(
        "/applications/review/rv-confirm/classify",
        json={"category": "rejection", "company": "Northwynd"},
        headers=headers,
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["needs_company_confirmation"] is True
    assert asked.json()["suggested_company"] == "Northwind"
    assert asked.json()["application_id"] is None

    # The same request, plus the answer. Everything else is byte-identical, so
    # the flag is the only thing that can change the outcome.
    filed = await client.post(
        "/applications/review/rv-confirm/classify",
        json={
            "category": "rejection",
            "company": "Northwynd",
            "confirm_new_company": True,
        },
        headers=headers,
    )
    assert filed.status_code == 200, filed.text
    assert filed.json().get("needs_company_confirmation") is None, (
        "the user answered the question and was asked it again — the flag did "
        "not reach classify_review_item"
    )
    opened = filed.json()["application_id"]
    assert opened is not None

    board = await _board(client, headers)
    assert set(board) == {"Northwind", "Northwynd"}, (
        "the answer is that these are two employers; it opens a SEPARATE row"
    )
    assert board["Northwynd"]["id"] == opened
    assert board["Northwynd"]["status"] == "rejected"
    assert board["Northwind"]["status"] == "applied", (
        "the near miss was acted on — the rejection settled the row it merely resembled"
    )


async def test_without_the_answer_the_same_request_asks_again_and_files_nothing(
    client: AsyncClient,
) -> None:
    """The control. Same fixture, same endpoint, the answer withheld.

    Without this the test above passes whenever the endpoint files something —
    including a build that had stopped asking at all — and would say nothing
    about the flag. Re-sending the question's own body is not an answer to it.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    northwind = await _one_northwind_row_and_a_relayed_review_item(client, headers, "rv-unanswered")

    for attempt in (1, 2):
        resp = await client.post(
            "/applications/review/rv-unanswered/classify",
            json={"category": "rejection", "company": "Northwynd"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["needs_company_confirmation"] is True, (
            f"attempt {attempt}: an unanswered question stopped being asked"
        )
        assert resp.json()["application_id"] is None

    board = await _board(client, headers)
    assert set(board) == {"Northwind"}, "an unanswered question opens nothing"
    assert board["Northwind"]["id"] == northwind
    assert board["Northwind"]["status"] == "applied"


async def test_a_scanned_message_crosses_the_hop_and_is_filed(
    client: AsyncClient,
) -> None:
    """Defends `scanned=data.message` in the endpoint.

    Delete that line and a correction made on the LIVE SCAN becomes a 404: the
    scan's rows are verdicts about mail this database has never stored, so the
    correction lands on nothing and the user's click does nothing.

    NOT the primary cover for that line, and it does not claim to be —
    `tests/test_scan_classify.py` already drives this endpoint over HTTP with a
    `message` payload, and six of its tests red on this deletion (its
    `test_a_scanned_message_is_stored_and_then_corrected` records that
    mutation). #562's table says the argument is uncovered; it is not. This is
    the same assertion stated beside the review-queue tests it shares the
    endpoint with.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    scanned = "scan-quarry-assessment"

    resp = await client.post(
        f"/applications/review/{scanned}/classify",
        json={
            "category": "assessment",
            "message": {
                "sender_email": "talent@quarry-data.test",
                "received_at": "2026-08-11T09:30:00+00:00",
                "subject": "Take-home exercise for the Data Platform role",
                "sender_name": "Quarry Data",
                # The scan's own verdict, as the user was looking at it: below
                # the review floor, so no sync would ever have stored it.
                "category": "other",
                "confidence": 0.0,
                "method": "rules",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    filed = resp.json()["application_id"]
    assert filed is not None

    board = await _board(client, headers)
    assert set(board) == {"Quarry Data"}
    assert board["Quarry Data"]["id"] == filed
    assert board["Quarry Data"]["status"] == "assessment"

    # ...and the message itself was stored, or the correction would have nothing
    # to sit on and could never be corrected a second time.
    listing = (await client.get("/applications/mail", headers=headers)).json()
    stored = {m["message_id"]: m for m in listing["messages"]}
    assert scanned in stored, "the verdict was accepted and the message was not stored"
    assert stored[scanned]["category"] == "assessment"
    assert stored[scanned]["user_corrected"] is True


async def test_without_the_metadata_the_same_correction_is_a_404(
    client: AsyncClient,
) -> None:
    """The control. Same message id, same category, the payload removed.

    This is the state the whole scan view was in, and it is what makes the 200
    above mean something: an unconditional mint would satisfy that test while
    letting any caller write a row for a message id it made up.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    resp = await client.post(
        "/applications/review/scan-quarry-assessment/classify",
        json={"category": "assessment"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text
    assert (await client.get("/applications", headers=headers)).json()["applications"] == []


# ---------------------------------------------------------------------------
# Rule 3 asks WHO MADE THE ROW (#559)
#
# `_pick_application`'s rule 3 adopts an employer's single identity-less row IN
# PLACE — the next sync stamps its cluster's `req_id` and `role_token` onto it.
# The one-candidate branch used to do that whatever the row's source was, while
# the comment on the several-candidates branch below it already said the
# opposite: a row a human made is not the sync's to re-key.
#
# The row a user opens by answering "none of these" is exactly the shape that
# branch adopts. It is identity-less BY CONSTRUCTION — the message reached the
# picker precisely because it names no role — and it is user-owned, and at an
# employer whose other cards are keyed it is the only unidentified one.
#
# The independent corpus cannot price this: `answer_the_queue` mints and then
# only READS the board, so no `gmail_user` row ever reaches `_pick_application`,
# and the harm needs exactly the sync that runs afterwards. These two tests are
# that sync.
#
# The three `thread_id`s below are distinct on purpose. A message sharing a
# thread with a stored one is routed by that thread and never reaches rule 3, so
# collapsing them would leave both tests green with the rule under test unrun.
# ---------------------------------------------------------------------------


def _northwind_confirmation(
    message_id: str, role: str, req_id: str, *, day: int, thread: str
) -> dict:
    """One Northwind confirmation that NAMES the application it is about."""

    return {
        "message_id": message_id,
        "category": "applied",
        "sender_email": "careers@northwind.com",
        "sender_name": "Northwind",
        "subject": "Thank you for applying to Northwind",
        "snippet": (
            "Hi, thanks for applying to Northwind! We've received your "
            f"application for the {role} (ID: {req_id}) position."
        ),
        "confidence": 0.95,
        "thread_id": thread,
        "received_at": f"2026-05-{day:02d}T09:00:00+00:00",
    }


async def _stored_northwind_rows(user_id: str) -> dict[int, dict]:
    """Northwind's rows WITH their identity columns, read from the database.

    `_serialize` publishes neither `req_id` nor `role_token` — deliberately, they
    are resolution internals — so the board listing cannot see the re-keying this
    section is about.
    """

    import uuid as _uuid

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Application

    uid = _uuid.UUID(user_id)
    async with get_session() as session:
        rows = (
            await session.exec(
                sm_select(Application).where(
                    Application.user_id == uid, Application.company == "Northwind"
                )
            )
        ).all()
        return {
            row.id: {
                "id": row.id,
                "source": row.source,
                "req_id": row.req_id,
                "role_token": row.role_token,
                "position": row.position,
                "dismissed_at": row.dismissed_at,
            }
            for row in rows
        }


async def _filed_against(user_id: str, message_id: str) -> int | None:
    """The application a stored message ended up linked to."""

    import uuid as _uuid

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    uid = _uuid.UUID(user_id)
    async with get_session() as session:
        email = (
            await session.exec(
                sm_select(Email).where(
                    Email.user_id == uid, Email.message_id == message_id
                )
            )
        ).first()
        return email.application_id if email else None


async def _make_it_the_syncs_own_row(user_id: str, row_id: int) -> None:
    """Flip one row's `source` to the sync's own, changing nothing else.

    The control's single variable. Done in the database because no product path
    can produce this row: an anonymous confirmation arriving at an employer that
    already holds a card is resolved by rule 4 onto that card (measured while
    writing these tests: `created=0, updated=1`), so the sync never mints a
    second blank row there. Everything else — the employer, the messages, the
    answer, the sync that follows — is byte-identical to the test above, which is
    what makes the pair directional.
    """

    import uuid as _uuid

    from sqlmodel import select as sm_select

    from jobtracker.cloud.applications import SOURCE_GMAIL_AUTO
    from jobtracker.database import get_session
    from jobtracker.database.models import Application

    uid = _uuid.UUID(user_id)
    async with get_session() as session:
        row = (
            await session.exec(
                sm_select(Application).where(
                    Application.user_id == uid, Application.id == row_id
                )
            )
        ).one()
        row.source = SOURCE_GMAIL_AUTO
        session.add(row)
        await session.commit()


async def _a_keyed_row_and_the_row_an_answer_opened(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[int, int]:
    """Northwind holds one KEYED application; the user then answers "none of these".

    Returns ``(the keyed row, the row the answer opened)``. The shape of the
    minted row is asserted HERE rather than in the tests, because both of them
    rest on it: if the answer stopped minting, or minted something already
    carrying an identity, neither test below would be exercising rule 3 at all
    and both would pass on a fixture that proves nothing.
    """

    from jobtracker.cloud.applications import _is_auto_row

    keyed = await client.post(
        "/gmail/sync",
        json={
            "items": [
                _northwind_confirmation(
                    "nw-keyed", "Backend Engineer", "44120", day=20, thread="th-keyed"
                )
            ]
        },
        headers=headers,
    )
    assert keyed.status_code == 200, keyed.text
    assert keyed.json()["created"] == 1, "the fixture's first application"

    held = await client.post(
        "/gmail/sync",
        json={
            "items": [
                {
                    "message_id": "nw-blind",
                    "category": "needs_review",
                    "sender_email": "talent@northwind.com",
                    "sender_name": "Northwind",
                    # Names no role anywhere the resolver can reach — the reason
                    # a message like this is held for a person in the first place.
                    "subject": "Update on your application",
                    "confidence": 0.62,
                    "thread_id": "th-blind",
                    "received_at": "2026-05-25T09:00:00+00:00",
                }
            ]
        },
        headers=headers,
    )
    assert held.status_code == 200, held.text
    assert held.json()["needs_review"] == 1, "the blind message must reach the queue"

    answered = await client.post(
        "/applications/review/nw-blind/classify",
        json={"category": "rejection", "none_of_these": True},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text
    opened = answered.json()["application_id"]
    assert opened is not None, "the answer opened no row"

    rows = await _stored_northwind_rows(USER_A)
    live = [r for r in rows.values() if r["dismissed_at"] is None]
    # One keyed, one blank, one employer — and the blind sender is a different
    # local part (`talent@`) from the confirmations' (`careers@`), so this also
    # states that both still resolve to Northwind. If they ever stopped, the
    # tests below would be about two employers and would pass meaninglessly.
    assert len(live) == 2, f"expected a keyed row and the opened row, got {live}"
    keyed_id = next(r["id"] for r in live if r["id"] != opened)
    assert rows[keyed_id]["req_id"] == "44120"
    assert rows[keyed_id]["role_token"] == "backend engineer"

    minted = rows[opened]
    assert minted["req_id"] is None and minted["role_token"] is None, (
        f"the opened row already carries an identity ({minted['req_id']!r}, "
        f"{minted['role_token']!r}); rule 3 would never consider it and these "
        "tests would measure nothing"
    )
    assert _is_auto_row(minted["source"]) is False, (
        f"the opened row's source is {minted['source']!r}, which the sync owns "
        "— a human's answer must produce a user-owned row"
    )
    return keyed_id, opened


async def test_a_later_sync_does_not_re_key_the_row_the_user_opened(
    client: AsyncClient,
) -> None:
    """The card a person opened must not absorb another application's identity.

    Delete the `_is_auto_row` test from rule 3's one-candidate branch and the
    next sync adopts this row in place, writing the Data Scientist application's
    `req_id` and `role_token` onto the card the user opened by answering "none of
    these". `role_token` is half an application's identity, so from that moment
    the user's own card answers to the OTHER application's mail: its rejection
    settles this card, its interviews land on it, and nothing on the board says
    the two were ever different applications.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    keyed_id, opened_id = await _a_keyed_row_and_the_row_an_answer_opened(client, headers)

    synced = await client.post(
        "/gmail/sync",
        json={
            "items": [
                _northwind_confirmation(
                    "nw-other", "Data Scientist", "77341", day=30, thread="th-other"
                )
            ]
        },
        headers=headers,
    )
    assert synced.status_code == 200, synced.text

    rows = await _stored_northwind_rows(USER_A)
    opened = rows[opened_id]
    assert opened["req_id"] is None and opened["role_token"] is None, (
        f"the sync re-keyed the user's own row (req_id={opened['req_id']!r}, "
        f"role_token={opened['role_token']!r}) — it now answers to the Data "
        "Scientist application's mail"
    )

    landed = await _filed_against(USER_A, "nw-other")
    assert landed is not None, "the identified confirmation was not filed at all"
    assert landed != opened_id, "it landed on the row the user opened"
    assert landed != keyed_id, "it landed on the OTHER requisition's row"
    assert rows[landed]["role_token"] == "data scientist"
    assert rows[keyed_id]["req_id"] == "44120", "the keyed sibling was rewritten"


async def test_the_syncs_own_blank_row_is_still_adopted_in_place(
    client: AsyncClient,
) -> None:
    """The control, and the behaviour rule 3 exists for.

    Identical scenario, one column different: the single identity-less row is the
    SYNC's own. It must still be adopted in place — same row id, now carrying the
    identity its mail names. What a user loses if this stops is a duplicate card
    per requisition at every employer whose first mail named no role: the blank
    card keeps the mail that made it, and the identity the later message carries
    mints a second row beside it.

    Without this control the fix above would be satisfied by a rule 3 that never
    adopts anything at all.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    keyed_id, blank_id = await _a_keyed_row_and_the_row_an_answer_opened(client, headers)
    await _make_it_the_syncs_own_row(USER_A, blank_id)

    synced = await client.post(
        "/gmail/sync",
        json={
            "items": [
                _northwind_confirmation(
                    "nw-other", "Data Scientist", "77341", day=30, thread="th-other"
                )
            ]
        },
        headers=headers,
    )
    assert synced.status_code == 200, synced.text

    rows = await _stored_northwind_rows(USER_A)
    live = [r for r in rows.values() if r["dismissed_at"] is None]
    assert len(live) == 2, (
        f"the identity minted a row instead of landing on the sync's own blank "
        f"one: {live}"
    )
    adopted = rows[blank_id]
    assert adopted["req_id"] == "77341" and adopted["role_token"] == "data scientist", (
        f"the sync's own blank row was not adopted (req_id={adopted['req_id']!r}, "
        f"role_token={adopted['role_token']!r})"
    )
    assert await _filed_against(USER_A, "nw-other") == blank_id
    assert rows[keyed_id]["req_id"] == "44120", "the keyed sibling was rewritten"


async def test_resync_purges_stale_auto_but_preserves_manual(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rebuild clears a CONTRADICTED auto row; the manual row is untouched.

    The rebuild half was rewritten after the 2026-08-10 data loss: it used to
    assert that a scan omitting Airbnb clears Airbnb, which is the reasoning
    that destroyed two real applications. It now also runs its rebuilds through
    the SERVER scan, because a relayed item set is refused as a rebuild.

    Every message here carries a date from ``_msg`` (July 2026), so the scan's
    coverage span and the stored rows' dates come from one source and cannot
    drift apart.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    stripe_msg = _ats_msg("m-stripe", "Stripe", "stripe.com", day=1)
    airbnb_msg = _ats_msg("m-airbnb", "Airbnb", "airbnb.com", day=2)

    # A hand-filed application the user owns.
    manual = await client.post(
        "/applications", json={"company": "MyStartup", "position": "Founding Engineer"}, headers=headers
    )
    assert manual.status_code == 201
    assert manual.json()["source"] == "manual"

    # First sync produces Stripe + Airbnb (auto).
    _install_gmail_stubs(
        monkeypatch, full_messages=[stripe_msg, airbnb_msg], profile_ids=["9001"]
    )
    await client.post("/gmail/sync", json={}, headers=headers)
    companies = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert {"MyStartup", "Stripe", "Airbnb"} <= companies

    # A routine ADDITIVE sync that no longer includes Airbnb must NOT purge it —
    # a bounded scan missing a company is not evidence the application is gone.
    _install_gmail_stubs(monkeypatch, full_messages=[stripe_msg], profile_ids=["9002"])
    add_resp = await client.post("/gmail/sync", json={}, headers=headers)
    assert add_resp.json()["purged"] == 0
    companies_add = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert "Airbnb" in companies_add  # durable — additive kept it

    # Neither does a REBUILD on the same silent scan — it never re-read
    # m-airbnb, so it holds no evidence about the Airbnb row at all.
    silent = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert silent.json()["purged"] == 0
    assert silent.json()["removed"] == []
    companies_silent = {a["company"] for a in (await client.get("/applications", headers=headers)).json()["applications"]}
    assert "Airbnb" in companies_silent

    # A rebuild that RE-READ m-airbnb and no longer files it does clear the
    # stale AUTO row — while the manual row survives untouched.
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[stripe_msg, _noise_msg("m-airbnb", day=2)],
        profile_ids=["9003"],
    )
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
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
    # NULL, and it used to be 0.78. Both spellings assert the same thing — that
    # the rescan did not write its own verdict here — because 0.78 was the
    # classifier's figure from BEFORE the correction and the rescan's is 0.95.
    # Since a correction now clears the column outright (a human decision
    # carries no probability), "unchanged" reads as None, and asserting it is
    # strictly stronger than asserting 0.78: it fails if the rescan writes
    # anything at all, including a value that happens to match the old one.
    assert email.classification_confidence is None
    assert email.classification_method == "user"
    assert email.user_corrected is True
    # ...and the row the user created keeps its status.
    listing = (await client.get("/applications", headers=headers)).json()
    replit = next(a for a in listing["applications"] if a["company"].lower() == "replit")
    assert replit["status"] == "interviewing"


async def test_rebuild_does_not_unlink_a_user_classified_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuild persists review items unfiltered; that must not clear a link.

    Without the guard, ``_persist_review_items`` writes ``application_id=None``
    over the row the user just filed, un-filing the application on the next
    explicit Re-sync.

    The message is an ATS-relay interview whose employer the pipeline cannot
    name (``no-reply@greenhouse-mail.io`` fronting a display name that is just
    the relay). It is confidently a lifecycle mail and still unfileable, so it
    goes to the review queue on every pass — including the rebuild's own scan,
    which is what makes it the right probe for this guard.
    """

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    relayed = [
        {
            "message_id": "rv-relay",
            "category": "interview",
            "sender_email": "no-reply@greenhouse-mail.io",
            "sender_name": "Greenhouse",
            "subject": "Interview invitation",
            "confidence": 0.95,
            "received_at": "2026-07-01T12:00:00+00:00",
        }
    ]
    await client.post("/gmail/sync", json={"items": relayed}, headers=headers)
    queue = (await client.get("/applications/review", headers=headers)).json()
    assert [i["message_id"] for i in queue["items"]] == ["rv-relay"]

    # The user supplies the employer the mail never named — that files a sticky
    # row and links the message to it.
    classified = await client.post(
        "/applications/review/rv-relay/classify",
        json={"category": "interview", "company": "Replit"},
        headers=headers,
    )
    assert classified.status_code == 200, classified.text
    app_id = classified.json()["application_id"]
    assert app_id is not None

    # The rebuild's own scan re-reads the same message and still cannot name the
    # employer, so it re-enters the review set and the ref it writes carries
    # ``application_id=None``.
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[
            _msg(
                "rv-relay",
                subject="Interview invitation",
                sender="no-reply@greenhouse-mail.io",
                snippet="We would like to schedule a chat.",
                day=1,
                name="Greenhouse",
            )
        ],
        profile_ids=["9001"],
    )
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert resp.status_code == 200, resp.text

    async with get_session() as session:
        email = (
            await session.exec(sm_select(Email).where(Email.message_id == "rv-relay"))
        ).first()
    assert email is not None and email.application_id == app_id
    detail = (await client.get(f"/applications/{app_id}", headers=headers)).json()
    assert [m["message_id"] for m in detail["messages"]] == ["rv-relay"]


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

    def _applied_to_role(message_id: str, day: int) -> Any:
        # NAMES THE ROLE, unlike ``_applied_msg``. This test is about status,
        # not identity, and since a second role-less confirmation at one
        # employer became a second application (2026-08-21) a role-less delta
        # would mint a card here and the assertions below would be reading a
        # different row than the one they mean. Keying both messages on the same
        # title keeps the subject of the test the rollup, not the resolver.
        return _msg(
            message_id,
            subject="We received your application to Cedartech",
            sender="careers@cedartech.com",
            snippet="Thank you for applying to the Platform Engineer position at Cedartech.",
            day=day,
            name="Cedartech",
        )

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_to_role("m1", day=1), _interview_msg("m2", day=10)],
        # The delta carries ONLY an older "applied" message.
        history_results=[HistoryPage(messages=[_applied_to_role("m3", day=2)])],
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


async def test_client_relayed_items_can_never_run_a_rebuild(
    client: AsyncClient,
) -> None:
    """``items`` + ``mode="rebuild"`` is REFUSED — the incident, re-armed.

    The forced ``in:anywhere`` scope guards the server-scan path only. A client
    that relays its own ``items`` chooses the window and the scope itself, and
    the purge would compute its coverage from whatever that client happened to
    read. Here Aven is filed from two messages — one still in the inbox, one
    archived. A client scan with ``scope=inbox`` re-reads the inbox message and
    never sees the archived one, but the archived message's date falls INSIDE
    the span the scan reached, so date-containment alone declares the row
    contradicted and removes it. That is precisely the 2026-08-10 deletion,
    reachable through a different door.

    Against the pre-fix code this fails twice over: the request is accepted and
    the Aven row is purged.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    # Aven filed from TWO messages: 2026-05-10 (inbox) and 2026-05-05 (later
    # archived by the user, so an ``in:inbox`` scan cannot return it).
    filed = [
        {
            "message_id": "m-aven-inbox",
            "category": "applied",
            "sender_email": "careers@aven.com",
            "subject": "Thanks for applying to the Engineer role at Aven",
            "sender_name": "Aven",
            "confidence": 0.95,
            "received_at": "2026-05-10T09:00:00+00:00",
        },
        {
            "message_id": "m-aven-archived",
            "category": "interview",
            "sender_email": "careers@aven.com",
            "subject": "Interview with Aven",
            "sender_name": "Aven",
            "confidence": 0.95,
            "received_at": "2026-05-05T09:00:00+00:00",
        },
    ]
    first = await client.post("/gmail/sync", json={"items": filed}, headers=headers)
    assert first.status_code == 200, first.text
    assert "aven" in await _companies(client, headers)

    # The client's own (inbox-scoped) scan: it re-read m-aven-inbox and no
    # longer files it, plus one older message that widens the span to 05-01 —
    # so 2026-05-05 sits inside a span the scan never actually reached into.
    relayed = [
        _noise_item("m-aven-inbox", "2026-05-10T09:00:00+00:00"),
        *_one_app_batch("m-other", "othercorp.com", "Othercorp"),
    ]
    resp = await client.post(
        "/gmail/sync", json={"items": relayed, "mode": "rebuild"}, headers=headers
    )

    # The property that matters, asserted before the status code: nothing went.
    assert "aven" in await _companies(client, headers), (
        "a client-relayed rebuild purged a row whose archived mail it never "
        "read — date-span containment is not message-id membership"
    )
    # And the refusal itself: a relayed item set may not be a rebuild at all.
    assert resp.status_code == 400, resp.text
    assert "rebuild" in resp.json()["detail"].lower()


async def test_rebuild_does_not_destroy_review_items_the_scan_could_not_see(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    await _connect_gmail(USER_A)
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
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[_ats_msg("m-aven", "Aven", "aven.com", day=1)],
        profile_ids=["9001"],
    )
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert resp.status_code == 200, resp.text
    queue_after = (await client.get("/applications/review", headers=headers)).json()
    assert [i["message_id"] for i in queue_after["items"]] == ["rv-archived"], (
        "a rebuild deleted a queued message it never re-read"
    )


async def test_rebuild_clears_queue_items_the_scan_did_re_read(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The queue still gets REBUILT — for the part of it the scan re-covered.

    The counterpart to the test above, and what keeps it honest: a message the
    scan re-read and now files confidently leaves the queue, exactly as before.
    """

    await _connect_gmail(USER_A)
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

    # Re-read by the rebuild's own scan as a confident application: it becomes a
    # real row and leaves the queue.
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[_ats_msg("rv-seen", "Replit", "replit.com", day=1)],
        profile_ids=["9001"],
    )
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
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
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-reading ONE of a row's messages does not license removing the row.

    Cedartech is filed from two messages: an early confirmation and a later
    interview. A rebuild whose scan only reaches the later one re-reads it and
    no longer files it — but the confirmation, which is the actual application
    evidence, was never in the scan at all. Removing on that basis would be
    guessing about the half it never read.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg("m-old", day=1), _interview_msg("m-new", day=10)],
        profile_ids=["9001"],
    )
    await client.post("/gmail/sync", json={}, headers=headers)
    assert "cedartech" in await _companies(client, headers)

    # The scan re-reads m-new only; m-old was never returned.
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[
            _ats_msg("m-aven", "Aven", "aven.com", day=11),
            _noise_msg("m-new", day=10),
        ],
        profile_ids=["9002"],
    )
    shallow = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert shallow.status_code == 200, shallow.text
    assert shallow.json()["purged"] == 0
    assert "cedartech" in await _companies(client, headers)

    # A scan that DID reach both messages, and files neither, has read the whole
    # case against the row — so this one removes it. (Which is what makes the
    # assertion above a real guard and not a coincidence.)
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[
            _noise_msg("m-old", day=1),
            _noise_msg("m-new", day=10),
            _ats_msg("m-aven", "Aven", "aven.com", day=11),
        ],
        profile_ids=["9003"],
    )
    deep = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert deep.json()["purged"] == 1
    assert [r["company"] for r in deep.json()["removed"]] == ["Cedartech"]
    assert "cedartech" not in await _companies(client, headers)


async def test_rebuild_keeps_an_auto_row_with_no_linked_mail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No linked email means no evidence to re-read — staleness is unprovable."""

    import uuid as _uuid

    from jobtracker.database import get_session
    from jobtracker.database.models import Application

    await _connect_gmail(USER_A)
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

    _install_gmail_stubs(
        monkeypatch,
        full_messages=[_ats_msg("m-aven", "Aven", "aven.com", day=1)],
        profile_ids=["9001"],
    )
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["purged"] == 0
    assert "ghostco" in await _companies(client, headers)


async def test_rebuild_reports_what_it_filed_and_what_it_removed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counts the button renders: "N filed, M removed", with the names."""

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[_ats_msg("m-tcs", "Tata", "tcs.com", day=1)],
        profile_ids=["9001"],
    )
    await client.post("/gmail/sync", json={}, headers=headers)
    filed_company = (await client.get("/applications", headers=headers)).json()[
        "applications"
    ][0]["company"]

    _install_gmail_stubs(
        monkeypatch,
        full_messages=[
            _ats_msg("m-aven", "Aven", "aven.com", day=2),
            _noise_msg("m-tcs", day=1),
        ],
        profile_ids=["9002"],
    )
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
    body = resp.json()
    assert body["created"] == 1  # Aven filed
    assert body["purged"] == 1  # Tata removed
    assert body["applications"] == 1  # live rows only — the removed one is out
    assert [r["company"] for r in body["removed"]] == [filed_company]
    assert all(isinstance(r["id"], int) for r in body["removed"])


async def test_a_row_a_resync_removed_is_restorable_not_deleted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removal is a state, so the wrong removal costs a click, not the data."""

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    _install_gmail_stubs(
        monkeypatch,
        full_messages=[_ats_msg("m-tcs", "Tata", "tcs.com", day=1)],
        profile_ids=["9001"],
    )
    await client.post("/gmail/sync", json={}, headers=headers)
    original = (await client.get("/applications", headers=headers)).json()[
        "applications"
    ][0]

    _install_gmail_stubs(
        monkeypatch,
        full_messages=[
            _ats_msg("m-aven", "Aven", "aven.com", day=2),
            _noise_msg("m-tcs", day=1),
        ],
        profile_ids=["9002"],
    )
    resp = await client.post("/gmail/sync", json={"mode": "rebuild"}, headers=headers)
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

    # THE FIXTURE MAIL IS MONTHS OLD, so neither row is "this week" under the
    # #509 basis. This line used to read `after == before - 1`, arithmetic that
    # held only because both rows were CREATED during the test — the count was
    # measuring the insert, which is the whole defect #509 removed.
    #
    # Asserting the ZEROES rather than `after == before` on purpose: equality
    # alone is satisfied by any basis, including the old one, and would leave
    # this line vacuous. Pinning both to 0 fails immediately if the endpoint
    # goes back to counting `created_at`, where these would read 2 and 1 — so
    # this is the integration-level proof that the endpoint reads the new
    # column, which the unit tests cannot give.
    assert before["this_week"] == 0
    assert after["this_week"] == 0


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


async def test_manual_create_dates_the_row_today_and_leaves_url_null(
    client: AsyncClient,
) -> None:
    """A hand-created application is ALWAYS dated; ``url`` still is not.

    THIS ASSERTION CHANGED ON PURPOSE, and the old one was right about the old
    contract: omitting ``applied_date`` used to store NULL. It cannot any more.
    Since #509 the "this week" count reads ``applied_date``, and ``>= NULL`` is
    false in SQL — so an undated row could never appear in that number, and a
    user who typed an application in by hand and left the date blank would
    simply never see it in their week, with nothing anywhere saying why.

    Today is a DEFAULT and not an invention: the Add-application form now shows
    today's date in its field (`localTodayISO`, the reader's own day), so the
    value is on screen and editable before the form is submitted. This endpoint
    defaults it too, so an API caller cannot create the undated row the form no
    longer can.

    ``url`` keeps its null, which is what makes this a scoped contract change
    rather than a general "fill in the blanks" policy — and asserting it here
    is what would catch one.
    """

    from datetime import datetime

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.post(
        "/applications",
        json={"company": "Acme", "position": "Backend Engineer"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    # The exact day, not merely "not null": `is not None` passes against a
    # default of 1970-01-01, and a row dated wrongly is worse than one dated
    # not at all.
    assert resp.json()["applied_date"] == datetime.utcnow().date().isoformat()
    assert resp.json()["url"] is None
    assert resp.json()["source"] == "manual"


async def test_an_explicit_applied_date_is_never_overwritten_by_the_default(
    client: AsyncClient,
) -> None:
    """THE CONTROL for the default above.

    A default that also clobbered a supplied value would pass every assertion
    in the test above while destroying exactly the case the field exists for:
    someone back-filling an application they made months ago.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    resp = await client.post(
        "/applications",
        json={
            "company": "Acme",
            "position": "Backend Engineer",
            "applied_date": "2026-01-15",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["applied_date"] == "2026-01-15"


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


# =============================================================================
# The duplicate-row and duplicate-queue-entry defects (2026-08-11)
# =============================================================================
#
# Two things the owner saw in live data the evening after the sync fixes:
#
#   - "Together AI" on the board TWICE (applications 64 and 65), the older row
#     with no linked email at all, because the only message had been re-pointed
#     to the newer one.
#   - "Crusoe | Application Received" in the review queue twice (emails 58 and
#     73) — two messages of a single Gmail thread, asked about separately.


def _together_ai_item(message_id: str, received_at: str) -> dict:
    """One ATS confirmation for a MULTI-WORD employer, relayed by the client.

    ``resolve_employer`` reduces this to the token ``together`` while the row it
    files stores the display name "Together AI" — the mismatch the upsert used
    to look through.
    """

    return {
        "message_id": message_id,
        "category": "applied",
        "sender_email": "no-reply@ashbyhq.com",
        "sender_name": "Together AI",
        "subject": "Thank you for applying to Together AI",
        "confidence": 0.95,
        "thread_id": "th-together",
        "received_at": received_at,
    }


async def _live_rows_without_mail(user_id: str) -> list[str]:
    """Companies of LIVE applications that have no linked email at all."""

    import uuid as _uuid

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Application, Email

    uid = _uuid.UUID(user_id)
    async with get_session() as session:
        rows = (
            await session.exec(
                sm_select(Application).where(
                    Application.user_id == uid,
                    Application.dismissed_at.is_(None),
                    Application.source == "gmail",
                )
            )
        ).all()
        stranded = []
        for row in rows:
            linked = (
                await session.exec(
                    sm_select(Email).where(
                        Email.user_id == uid, Email.application_id == row.id
                    )
                )
            ).all()
            if not linked:
                stranded.append(row.company)
    return stranded


async def test_a_multi_word_company_files_one_row_not_one_per_sync(
    client: AsyncClient,
) -> None:
    """The owner's duplicate: a second row per sync for "Together AI".

    The upsert looked the row up as ``lower(company) == token``, which is only
    ever true for a one-word company name. "Anthropic" matched itself and behaved;
    "Together AI" (token ``together``) never matched, so every sync inserted
    another row and moved the one linked email onto it, leaving the previous row
    on the board with nothing behind it.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    first = await client.post(
        "/gmail/sync",
        json={"items": [_together_ai_item("m-together", "2026-07-01T12:00:00+00:00")]},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    board = (await client.get("/applications", headers=headers)).json()
    assert [a["company"] for a in board["applications"]] == ["Together AI"]
    original_id = board["applications"][0]["id"]

    # The same message, re-read by a later sync.
    second = await client.post(
        "/gmail/sync",
        json={"items": [_together_ai_item("m-together", "2026-07-01T12:00:00+00:00")]},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0, "a repeat sync must update, not insert"
    assert second.json()["updated"] == 1

    board2 = (await client.get("/applications", headers=headers)).json()
    assert board2["total"] == 1, "the same company was filed twice"
    assert board2["applications"][0]["id"] == original_id

    # The mail still points at the row that survived, and no live row is empty.
    detail = (await client.get(f"/applications/{original_id}", headers=headers)).json()
    assert [m["message_id"] for m in detail["messages"]] == ["m-together"]
    assert await _live_rows_without_mail(USER_A) == []


async def test_a_row_whose_last_email_moves_away_is_dismissed_not_stranded(
    client: AsyncClient,
) -> None:
    """Re-pointing may empty a row; it may not leave one on the board empty.

    An emptied row is the worst of the available states — visible, counted, and
    (since a scan may only contradict a row by re-reading the row's own mail)
    permanently unremovable, because it has no mail left to re-read. It is
    dismissed instead: off the board, still on disk, restorable.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    filed = {
        "message_id": "m-moves",
        "category": "applied",
        "sender_email": "careers@cedartech.com",
        "sender_name": "Cedartech",
        "subject": "We received your application to Cedartech",
        "confidence": 0.95,
        "received_at": "2026-07-01T12:00:00+00:00",
    }
    await client.post("/gmail/sync", json={"items": [filed]}, headers=headers)
    assert "cedartech" in await _companies(client, headers)

    # The same message id, now attributed to a different employer — the message
    # moves, and Cedartech is left with nothing.
    moved = {
        **filed,
        "sender_email": "careers@aven.com",
        "sender_name": "Aven",
        "subject": "We received your application to Aven",
    }
    resp = await client.post("/gmail/sync", json={"items": [moved]}, headers=headers)
    assert resp.status_code == 200, resp.text

    assert await _live_rows_without_mail(USER_A) == [], (
        "a row was left on the board with no linked mail — it can never be "
        "contradicted, so nothing will ever remove it"
    )
    assert "aven" in await _companies(client, headers)
    assert "cedartech" not in await _companies(client, headers)

    # Dismissed, not deleted: it is listed as removed and can be restored.
    removed = (
        await client.get("/applications?dismissed=true", headers=headers)
    ).json()
    assert [a["company"] for a in removed["applications"]] == ["Cedartech"]


def _crusoe_item(message_id: str, received_at: str) -> dict:
    """One message of the Crusoe thread, uncertain enough for the queue."""

    return {
        "message_id": message_id,
        "category": "applied",
        "sender_email": "no-reply@ashbyhq.com",
        "sender_name": "Crusoe",
        "subject": "Crusoe | Application Received",
        "confidence": 0.78,  # below the auto-file gate → review queue
        "thread_id": "19fed7e0706ee704",
        "received_at": received_at,
    }


async def test_two_messages_of_one_thread_are_one_review_entry(
    client: AsyncClient,
) -> None:
    """One conversation is one decision — the owner was asked twice.

    Emails 58 and 73 are two messages of thread ``19fed7e0706ee704``, both
    unlinked and both in the queue. The filing path had grouped this shape by
    thread for months; the review path had not.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    resp = await client.post(
        "/gmail/sync",
        json={
            "items": [
                _crusoe_item("19fed7e0706ee704", "2026-08-10T20:00:00+00:00"),
                _crusoe_item("19fedeb77e1accb3", "2026-08-11T01:00:00+00:00"),
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    queue = (await client.get("/applications/review", headers=headers)).json()
    assert queue["total"] == 1, "one Gmail thread produced two queue entries"
    # The newest message of the thread represents it.
    assert queue["items"][0]["message_id"] == "19fedeb77e1accb3"

    # The dashboard tile counts what the queue shows, not the rows behind it.
    summary = (await client.get("/applications/summary", headers=headers)).json()
    assert summary["needs_review"] == 1


async def test_classifying_a_thread_settles_every_message_in_it(
    client: AsyncClient,
) -> None:
    """Otherwise the sibling message comes straight back to the queue.

    Both messages are persisted (an earlier sync had already queued one when the
    second arrived), so settling has to reach the row the user never saw.
    """

    import uuid as _uuid

    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Email

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    # Two syncs, so both messages exist as separate queue rows on disk — the
    # exact state of emails 58 and 73.
    await client.post(
        "/gmail/sync",
        json={"items": [_crusoe_item("19fed7e0706ee704", "2026-08-10T20:00:00+00:00")]},
        headers=headers,
    )
    await client.post(
        "/gmail/sync",
        json={"items": [_crusoe_item("19fedeb77e1accb3", "2026-08-11T01:00:00+00:00")]},
        headers=headers,
    )
    queue = (await client.get("/applications/review", headers=headers)).json()
    assert queue["total"] == 1
    representative = queue["items"][0]["message_id"]

    classified = await client.post(
        f"/applications/review/{representative}/classify",
        json={"category": "applied"},
        headers=headers,
    )
    assert classified.status_code == 200, classified.text
    app_id = classified.json()["application_id"]
    assert app_id is not None

    # Nothing of that conversation is left to ask about.
    assert (await client.get("/applications/review", headers=headers)).json()["total"] == 0
    summary = (await client.get("/applications/summary", headers=headers)).json()
    assert summary["needs_review"] == 0

    async with get_session() as session:
        rows = (
            await session.exec(
                sm_select(Email).where(
                    Email.user_id == _uuid.UUID(USER_A),
                    Email.thread_id == "19fed7e0706ee704",
                )
            )
        ).all()
    assert len(rows) == 2
    assert all(e.is_reviewed for e in rows)
    assert {e.application_id for e in rows} == {app_id}


def _verkada_item(message_id: str, role: str, received_at: str) -> dict:
    """One message of the real Verkada thread, uncertain enough for the queue.

    Thread ``19ff36237eef1ef3``, read from the owner's mailbox 2026-08-22: five
    Greenhouse acknowledgements for FOUR roles, all under one subject from one
    no-reply address, which is exactly why Gmail threaded them. Snippets are
    Gmail's own. Scored under the auto-file gate because the queue is the path
    under test — mail that clears the gate never reaches it.
    """

    return {
        "message_id": message_id,
        "category": "applied",
        "sender_email": "no-reply@us.greenhouse-mail.io",
        "sender_name": "Verkada",
        "subject": "Thank you for applying to Verkada",
        "snippet": (
            f"Hi Ayush, Thank you so much for applying to the {role} role at "
            "Verkada! We are always looking for great talent and we are excited "
            "to receive your application. We will review it as"
        ),
        "confidence": 0.78,
        "thread_id": "19ff36237eef1ef3",
        "received_at": received_at,
    }


_VERKADA_THREAD = (
    ("19ff36237eef1ef3", "Backend Engineer, Alarms"),
    ("19ff39a08b3bc051", "Frontend Engineer - Access Control"),
    ("19ff39afaed0fc1d", "Backend Engineer - Connectivity"),
    ("19ff3c8bf80031ab", "Backend Engineer, Alarms"),
    ("19ff3c8c90a8650d", "Embedded Software Engineer, Access Control"),
)


async def test_one_ats_thread_is_asked_about_once_per_application(
    client: AsyncClient,
) -> None:
    """Four applications in one Gmail thread, and the user is asked four times.

    The whole cycle, because a fix at fewer than every site is invisible: the
    pipeline can queue four rows and the endpoint still render one. Sync, queue,
    the summary tile the queue is linked from, and then classifying one entry —
    which must settle its own duplicate and NOTHING else. Issue #454.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    resp = await client.post(
        "/gmail/sync",
        json={
            "items": [
                _verkada_item(mid, role, f"2026-08-12T0{i}:00:00+00:00")
                for i, (mid, role) in enumerate(_VERKADA_THREAD)
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    queue = (await client.get("/applications/review", headers=headers)).json()
    # Five messages, four applications: the two "Backend Engineer, Alarms"
    # acknowledgements are ONE decision, and the other three are their own.
    assert queue["total"] == 4, [i["snippet"][:60] for i in queue["items"]]
    # And the four are TELLABLE APART. Subject and sender are byte-identical
    # across all of them — that is why Gmail threaded them — so the entry has to
    # carry which application it is about or the queue asks the same question
    # four times with no way to answer differently.
    assert sorted(i["role"] for i in queue["items"]) == [
        "Backend Engineer - Connectivity",
        "Backend Engineer, Alarms",
        "Embedded Software Engineer, Access Control",
        "Frontend Engineer - Access Control",
    ]
    assert len({i["subject"] for i in queue["items"]}) == 1
    # The tile the queue is reached from must agree with it.
    summary = (await client.get("/applications/summary", headers=headers)).json()
    assert summary["needs_review"] == 4

    # Classifying one settles that application and leaves the other three.
    representative = queue["items"][0]["message_id"]
    classified = await client.post(
        f"/applications/review/{representative}/classify",
        json={"category": "applied"},
        headers=headers,
    )
    assert classified.status_code == 200, classified.text

    remaining = (await client.get("/applications/review", headers=headers)).json()
    assert remaining["total"] == 3
    assert (
        await client.get("/applications/summary", headers=headers)
    ).json()["needs_review"] == 3


async def test_answering_one_application_does_not_bury_its_thread_siblings(
    client: AsyncClient,
) -> None:
    """The cross-sync half of #454, which the single-sync test cannot reach.

    ``_persist_review_items_additive`` keeps a conversation the user has already
    decided about out of the queue, so a later message on it does not ask the
    same question twice. Keyed on the thread alone, answering ONE of Verkada's
    four applications suppressed the other three on every subsequent sync — the
    within-sync fix cannot help a message that is filtered out before it is
    persisted.

    Two syncs on purpose: the first three arrive, one is answered, and only then
    does the fourth turn up. That is the ordinary shape of a delta.
    """

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    first, second = _VERKADA_THREAD[:3], _VERKADA_THREAD[4:]

    assert (
        await client.post(
            "/gmail/sync",
            json={
                "items": [
                    _verkada_item(mid, role, f"2026-08-12T0{i}:00:00+00:00")
                    for i, (mid, role) in enumerate(first)
                ]
            },
            headers=headers,
        )
    ).status_code == 200

    queue = (await client.get("/applications/review", headers=headers)).json()
    assert queue["total"] == 3
    answered = queue["items"][0]
    assert (
        await client.post(
            f"/applications/review/{answered['message_id']}/classify",
            json={"category": "applied"},
            headers=headers,
        )
    ).status_code == 200

    # A LATER SYNC, carrying the fourth application of the same conversation.
    assert (
        await client.post(
            "/gmail/sync",
            json={
                "items": [
                    _verkada_item(mid, role, "2026-08-12T05:00:00+00:00")
                    for mid, role in second
                ]
            },
            headers=headers,
        )
    ).status_code == 200

    remaining = (await client.get("/applications/review", headers=headers)).json()
    # The two still-unanswered ones from the first sync, plus the new one. The
    # answered application does not come back, which is what the settled filter
    # is for and is unchanged.
    assert sorted(i["role"] for i in remaining["items"]) == sorted(
        [r for _m, r in first if r != answered["role"]]
        + [r for _m, r in second]
    ), [i["role"] for i in remaining["items"]]
    assert remaining["total"] == 3


# =============================================================================
# What ``scanned`` is allowed to imply
# =============================================================================


async def test_sync_reports_what_it_lost_and_why_it_stopped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``scanned`` alone cannot be told apart from coverage.

    The full-scan path used to discard ``MessagePage.unreadable`` entirely — the
    ids it listed and could not read back — so a scan that lost 60 of 2,000
    messages reported 1,940 as though that were the mailbox. Now the response
    says how many it read, how many it lost, why it stopped reading, and
    (approximately, from Gmail's own estimate) how many the query matches.
    """

    import jobtracker.cloud.gmail_client as gmail_client_module
    from jobtracker.cloud.gmail_client import MessagePage

    await _connect_gmail(USER_A)

    async def _fake_profile(user_id, **_kwargs):
        return "9001"

    async def _fake_page(user_id, **_kwargs):
        return MessagePage(
            messages=[_applied_msg()],
            next_page_token=None,
            unreadable=7,
            result_size_estimate=1200,
        )

    monkeypatch.setattr(gmail_client_module, "fetch_mailbox_history_id", _fake_profile)
    monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    body = (await client.post("/gmail/sync", json={}, headers=headers)).json()

    assert body["scanned"] == 1
    assert body["unreadable"] == 7
    assert body["stopped_by"] == "complete"  # the query ran out, not the budget
    assert body["result_size_estimate"] == 1200


async def test_an_incremental_sync_also_reports_what_it_lost(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The history path drops metadata the same way the full scan does.

    Reporting ``unreadable: 0`` here whatever it lost would be the same defect
    one path over — which is why ``HistoryPage`` carries the number too.
    """

    from jobtracker.cloud.gmail_client import HistoryPage

    await _connect_gmail(USER_A)
    calls = _install_gmail_stubs(
        monkeypatch,
        full_messages=[_applied_msg(day=1)],
        history_results=[
            HistoryPage(messages=[_interview_msg(day=10)], unreadable=4)
        ],
        profile_ids=["9001", "9100"],
    )

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    await client.post("/gmail/sync", json={}, headers=headers)
    body = (await client.post("/gmail/sync", json={}, headers=headers)).json()

    assert calls["history"] == 1
    assert body["scanned"] == 1
    assert body["unreadable"] == 4
    # A usable delta IS everything since the cursor, and Gmail offers no
    # estimate for it — so no estimate is invented.
    assert body["stopped_by"] == "complete"
    assert body["result_size_estimate"] is None
    # …and it did NOT step over what it lost: the cursor stays where it was, so
    # the next run re-walks the same delta. See
    # ``test_a_message_lost_between_two_syncs_is_not_skipped_forever``.
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9001"


# =============================================================================
# A message that arrives BETWEEN two syncs that both run (issue #166)
# =============================================================================


class _FakeMailbox:
    """A Gmail stand-in that answers ``history.list`` from a real cursor.

    ``_install_gmail_stubs`` hands back a scripted ``HistoryPage`` whatever
    ``start_history_id`` it is asked for, which is fine for the tests that only
    care what the RESPONSE says. It cannot express the defect this file's next
    test is about, because that defect is entirely about which delta the second
    request gets: a fake that ignores the cursor will hand back the missing
    message no matter how far the cursor moved, and the test passes on a
    product that lost it.

    So this one models the mailbox. Messages carry a ``historyId``; a delta is
    everything strictly newer than the requested cursor; and ``failing_gets``
    names ids whose batched ``messages.get`` comes back empty — Gmail LISTED
    them, we could not read them, which is exactly what ``unreadable`` counts
    (``gmail_client._collect_history``: ``unreadable = len(ids) - len(out)``).

    ``failing_gets`` is honoured by the FULL SCAN too, because the real client
    loses ids there the same way and for the same reason
    (``fetch_message_page``: ``unreadable = len(ids) - len(out)``, "the batch's
    own losses PLUS metadata that came back and would not parse"). A fake that
    only ever loses messages on a delta cannot express issue #180 at all.

    ``expired`` makes ``history.list`` answer the way Gmail answers a cursor
    older than its ~1-week window: a 404, surfaced as an unusable page, which
    sends the caller down the full-scan-and-re-baseline path.
    """

    def __init__(self) -> None:
        # (history_id, message) in arrival order.
        self.messages: list[tuple[int, Any]] = []
        self.failing_gets: set[str] = set()
        self.expired = False
        self.deltas: list[tuple[str, list[str]]] = []
        # Every cursor history.list was asked for, expired answers included —
        # ``deltas`` only records the walks that produced one.
        self.history_requests: list[str] = []

    def deliver(self, history_id: int, message: Any) -> None:
        self.messages.append((history_id, message))

    @property
    def current_history_id(self) -> str:
        return str(max((h for h, _ in self.messages), default=1))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import jobtracker.cloud.gmail_client as gmail_client_module
        from jobtracker.cloud.gmail_client import HistoryPage, MessagePage

        async def _fake_profile(user_id, **_kwargs):
            return self.current_history_id

        async def _fake_page(user_id, **_kwargs):
            # The full scan re-lists the window newest-first — and loses the
            # same ids the batch loses on a delta.
            listed = [m for _h, m in sorted(self.messages, reverse=True, key=lambda e: e[0])]
            read = [m for m in listed if m.message_id not in self.failing_gets]
            return MessagePage(
                messages=read,
                next_page_token=None,
                unreadable=len(listed) - len(read),
            )

        async def _fake_history(user_id, *, start_history_id, **_kwargs):
            self.history_requests.append(str(start_history_id))
            if self.expired:
                return HistoryPage(messages=[], expired=True)
            listed = [m for h, m in self.messages if h > int(start_history_id)]
            read = [m for m in listed if m.message_id not in self.failing_gets]
            self.deltas.append(
                (str(start_history_id), [m.message_id for m in listed])
            )
            return HistoryPage(messages=read, unreadable=len(listed) - len(read))

        monkeypatch.setattr(
            gmail_client_module, "fetch_mailbox_history_id", _fake_profile
        )
        monkeypatch.setattr(gmail_client_module, "fetch_message_page", _fake_page)
        monkeypatch.setattr(
            gmail_client_module, "fetch_history_messages", _fake_history
        )


async def test_a_message_lost_between_two_syncs_is_not_skipped_forever(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #166: a rejection inside a covered window, ingested by nothing.

    The reported shape, verbatim: three messages on the same day, the first and
    the third on the board, the middle one on neither the board nor in
    ``emails`` — and syncs demonstrably ran on both sides of it.

    The mechanism reproduced here is the one the issue's second candidate names.
    An incremental delta LISTS a message and cannot read its metadata back: a
    dropped sub-request inside the 100-message batch, which
    ``_batch_fetch_metadata`` logs and counts and then carries on past, because
    one bad message must not sink a page. The page is still ``usable`` — it is
    not ``expired`` and not ``truncated`` — so ``_incremental_scan`` returns it,
    and ``gmail_sync`` writes the baseline captured before the run.

    That baseline is NEWER than the message that was lost. From the next sync on,
    the delta starts after it, and no incremental run can ever name it again.
    ``unreadable: 1`` is reported honestly on the response nobody reads, and the
    message is gone — not from a window the scan never reached, but from the
    middle of one it did.

    A full scan would still re-list it, which is why this only bites once the
    cursor exists; the first sync here establishes it exactly as production's did.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    rejection = _msg(
        "m-together",
        subject="Update on your application to Together AI",
        sender="careers@together.ai",
        snippet=(
            "We regret to inform you that we will not be moving forward with "
            "your application."
        ),
        day=12,
        name="Together AI",
    )
    later = _msg(
        "m-amazon",
        subject="Thank you for Applying to Amazon!",
        sender="no-reply@amazon.jobs",
        snippet="Thank you for applying. Your application has been received.",
        day=12,
        name="Amazon",
    )

    mailbox = _FakeMailbox()
    mailbox.deliver(9002, _applied_msg("m-earlier", day=11))
    mailbox.install(monkeypatch)

    # Sync 1 — no cursor yet, so this is the full scan, and it baselines at 9002.
    first = await client.post("/gmail/sync", json={"mode": "additive"}, headers=headers)
    assert first.status_code == 200, first.text
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9002"

    # Both messages arrive. The rejection's metadata get fails this once —
    # transient, the way a dropped batch sub-request is.
    mailbox.deliver(9050, rejection)
    mailbox.deliver(9080, later)
    mailbox.failing_gets.add("m-together")

    second = await client.post("/gmail/sync", json={"mode": "additive"}, headers=headers)
    assert second.status_code == 200, second.text
    body = second.json()
    # The run LISTED both and read one. It says so.
    assert mailbox.deltas[-1] == ("9002", ["m-together", "m-amazon"])
    assert (body["scanned"], body["unreadable"]) == (1, 1)

    # THE ASSERTION. A run that could not read everything it listed must not
    # move the cursor past it: the baseline it captured (9080) sits after the
    # message it lost, so recording it would put that message permanently out of
    # every future delta's reach.
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9002"

    # Sync 3 — the transient failure is over. Because the cursor was held, the
    # delta still names the rejection, and it lands.
    mailbox.failing_gets.clear()
    third = await client.post("/gmail/sync", json={"mode": "additive"}, headers=headers)
    assert third.status_code == 200, third.text
    assert mailbox.deltas[-1][0] == "9002"
    assert third.json()["unreadable"] == 0

    listing = (await client.get("/applications", headers=headers)).json()
    rows = {a["company"].lower(): a["status"] for a in listing["applications"]}
    assert "together ai" in rows, f"the lost rejection never reached the board: {rows}"
    assert rows["together ai"] == "rejected"

    # A clean run DOES advance, so the fix costs one repeated delta, not a
    # cursor that never moves again.
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9080"


async def test_a_first_full_scan_that_loses_a_message_still_baselines(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #180: the cursor hold must not fire on a full scan.

    Holding the cursor means passing ``history_id=None``, which PRESERVES
    whatever is stored. On the incremental branch that is the whole point. On a
    first full scan there is nothing stored, so "preserve" means "record
    nothing" — and the next sync full-scans again, hits the same unreadable ids
    for the same reason, and again records nothing. An account whose first scan
    loses one message never gets a cursor and full-scans forever.

    The trigger is not exotic: ``unreadable`` counts every id Gmail listed that
    could not be turned into a row, batch losses and unparseable metadata alike,
    and a probe measured 68 of them on a 100-message page.

    Recording is not free — the baseline is newer than the id that would not
    read, so no later delta names it either. Holding is worse: the next full
    scan loses the same id for the same reason, and there is no cursor to show
    for it. Recording at least leaves the account on deltas, with the id still
    reachable by a Re-sync, and says so in the log.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    mailbox = _FakeMailbox()
    mailbox.deliver(9002, _applied_msg("m-applied", day=11))
    mailbox.deliver(
        9080,
        _msg(
            "m-lost",
            subject="Your application to Northwind",
            sender="careers@northwind.example",
            snippet="Thank you for applying. Your application has been received.",
            day=12,
            name="Northwind",
        ),
    )
    mailbox.failing_gets.add("m-lost")
    mailbox.install(monkeypatch)

    first = await client.post("/gmail/sync", json={"mode": "additive"}, headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    # No cursor was stored, so this ran the full scan — and it lost one of the
    # two ids it listed, honestly reported.
    assert mailbox.history_requests == []
    assert (body["scanned"], body["unreadable"]) == (1, 1)

    # THE ASSERTION. The baseline goes in regardless: a full scan steps past
    # nothing, so withholding it would only cost the cursor.
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9080"

    # And the consequence that makes it matter — the next sync is a DELTA off
    # that cursor, not a third full re-list of the whole window.
    second = await client.post("/gmail/sync", json={"mode": "additive"}, headers=headers)
    assert second.status_code == 200, second.text
    assert mailbox.history_requests == ["9080"]


async def test_a_lossy_re_baseline_records_the_cursor_it_went_to_get(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other full-scan route, and the one that is easy to break.

    When Gmail 404s a cursor out of its ~1-week history window the sync full-
    scans *in order to* re-baseline. Scoping the hold to the incremental branch
    has to leave that free to record, or the same permanent-full-scan bug comes
    back by a different road: the cursor would expire once, the re-baseline
    would find any unreadable id, and the account would never hold a usable
    cursor again.
    """

    await _connect_gmail(USER_A)
    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}

    mailbox = _FakeMailbox()
    mailbox.deliver(9002, _applied_msg("m-applied", day=11))
    mailbox.install(monkeypatch)

    first = await client.post("/gmail/sync", json={"mode": "additive"}, headers=headers)
    assert first.status_code == 200, first.text
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9002"

    # Time passes; the cursor ages out. New mail arrives, and one id will not
    # read back on the re-baselining scan.
    mailbox.deliver(
        9050,
        _msg(
            "m-lost",
            subject="Your application to Northwind",
            sender="careers@northwind.example",
            snippet="Thank you for applying. Your application has been received.",
            day=12,
            name="Northwind",
        ),
    )
    mailbox.failing_gets.add("m-lost")
    mailbox.expired = True

    second = await client.post("/gmail/sync", json={"mode": "additive"}, headers=headers)
    assert second.status_code == 200, second.text
    body = second.json()

    # This really is the re-baseline path and not "no cursor stored": the run
    # asked history.list for the stored cursor and was refused.
    assert mailbox.history_requests == ["9002"]
    assert body["unreadable"] == 1

    # So the scan it fell back to must land the new baseline it went to get.
    assert (await _sync_rows(USER_A))[0].gmail_history_id == "9050"


async def test_a_relayed_mine_says_the_server_did_not_scan_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server cannot characterise a scan it did not make, and says so
    rather than presenting the client's count as its own coverage."""

    await _connect_gmail(USER_A)
    _install_gmail_stubs(monkeypatch, profile_ids=["9001"])

    headers = {"Authorization": f"Bearer {_token_for(USER_A)}"}
    body = (
        await client.post(
            "/gmail/sync", json={"items": _sync_items()}, headers=headers
        )
    ).json()

    assert body["stopped_by"] == "relay"
    assert body["unreadable"] == 0
    assert body["result_size_estimate"] is None
