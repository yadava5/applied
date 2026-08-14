"""Per-request cost structure of the cloud read endpoints (issue #203).

Production measured ``GET /api/applications/121`` at 850 ms for 568 bytes with
~500 ms unattributed. Handler-level timing (2026-08-14, the real app in-process
against the production pooler) attributed it:

* every read endpoint that serialises a Gmail deep link opened a SECOND
  database session — ``_connected_account_email`` → ``get_gmail_credentials``
  → its own ``get_session()`` — and under ``NullPool`` a session is a fresh
  TCP+TLS+auth connection (~216 ms from iad1) plus its own transaction GUCs;
* every transaction paid TWO ``set_config`` round trips where one statement
  carries both GUCs.

These tests pin the fixed cost structure so it cannot silently regress:

1. one request → exactly one DB session on the hot read endpoints;
2. one transaction → exactly one GUC round trip (both GUCs in one statement);
3. the ``Server-Timing`` instrument is present, so the next latency question
   starts from numbers instead of inference.

Proven to fail: each assertion was run against the pre-fix code and went red —
the session counter read 2 on all four endpoints, the GUC fake recorded two
``exec_driver_sql`` calls, and the header did not exist. See the PR for the
red/green transcript.
"""

from __future__ import annotations

import importlib
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "request-cost-test-jwt-secret-at-least-32-bytes-long-hs256"
OWNER = "abababab-abab-abab-abab-abababababab"


def _token_for(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": user_id, "aud": "authenticated", "iat": now, "exp": now + 300},
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app over the in-memory SQLite test DB (house pattern)."""

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

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


async def _seed_owner_row() -> int:
    from datetime import datetime

    from jobtracker.database.connection import get_session
    from jobtracker.database.models import (
        Application,
        ApplicationStatus,
        Email,
        EmailCategory,
        EmailSource,
    )

    async with get_session() as session:
        row = Application(
            user_id=uuid.UUID(OWNER),
            company="Crusoe Energy",
            position="Software Engineer",
            status=ApplicationStatus.APPLIED,
        )
        session.add(row)
        await session.flush()
        app_id = row.id
        session.add(
            Email(
                user_id=uuid.UUID(OWNER),
                application_id=app_id,
                source_account=EmailSource.GMAIL,
                message_id="m-phase-1",
                subject="Crusoe | Application Received",
                sender_email="recruiting@crusoe.ai",
                received_at=datetime(2026, 8, 11, 9, 30, 0),
                body_snippet="Thanks for applying",
                classified_as=EmailCategory.APPLIED,
            )
        )
        await session.commit()
    return app_id


class _SessionCounter:
    """Counts every AsyncSession the app constructs during one request."""

    def __init__(self, connection_module, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        real_session_cls = connection_module.AsyncSession
        counter = self

        class CountingSession(real_session_cls):  # type: ignore[misc,valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                counter.count += 1
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(connection_module, "AsyncSession", CountingSession)

    def reset(self) -> None:
        self.count = 0


@pytest.mark.asyncio
async def test_hot_read_endpoints_open_exactly_one_session(
    cloud_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One request = one session = (under NullPool in prod) one connection.

    The second session was the Gmail deep-link credential lookup opening its
    own ``get_session()``; measured at ~470 ms per request against the real
    pooler (its own connect + its own GUC round trips + the select). The
    lookup must ride the handler's session instead.
    """

    from datetime import datetime, timedelta

    from cryptography.fernet import Fernet

    import jobtracker.cloud.gmail_oauth as gmail_oauth_module
    import jobtracker.credentials.cloud as cred_cloud
    import jobtracker.database.connection as connection_module
    from jobtracker.credentials.types import GmailCredentials

    # Give the credential lookup a working Fernet key (and a fully-configured
    # Gmail OAuth surface): without the key it bails BEFORE opening its session
    # and the pre-fix double-session cost would be invisible here — the
    # production deployment always has all of these set. The reload dance in
    # the fixture leaves different modules holding different Settings
    # instances, so patch every one this request path can read.
    settings_objects: list = []
    for candidate in (
        cred_cloud.settings,
        gmail_oauth_module.settings,
        connection_module.settings,
    ):
        if not any(candidate is seen for seen in settings_objects):
            settings_objects.append(candidate)
    for settings_obj in settings_objects:
        monkeypatch.setattr(
            settings_obj, "secret_encryption_key", Fernet.generate_key().decode()
        )
        monkeypatch.setattr(settings_obj, "google_oauth_client_id", "cid")
        monkeypatch.setattr(settings_obj, "google_oauth_client_secret", "csecret")
        monkeypatch.setattr(
            settings_obj, "gmail_oauth_redirect_uri", "http://test/auth/callback"
        )
        monkeypatch.setattr(settings_obj, "web_app_url", "http://test")

    app_id = await _seed_owner_row()
    # A connected Gmail account, so /auth/gmail/status exercises BOTH of its
    # reads (credential + sync state) — the pre-fix path opened a session for
    # each of them.
    assert await cred_cloud.save_gmail_credentials(
        uuid.UUID(OWNER),
        GmailCredentials(
            access_token="t",
            refresh_token="r",
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            email="owner@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        ),
    )
    counter = _SessionCounter(connection_module, monkeypatch)
    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}

    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in (
            "/applications",
            f"/applications/{app_id}",
            "/applications/review",
            "/applications/mail",
            "/auth/gmail/status",
        ):
            counter.reset()
            response = await client.get(path, headers=headers)
            assert response.status_code == 200, (path, response.text)
            assert counter.count == 1, (
                f"{path} opened {counter.count} DB sessions for one request; "
                "each extra session is a fresh NullPool connection (~216 ms in "
                "production). The credential lookup must reuse the handler's "
                "session."
            )


@pytest.mark.asyncio
async def test_deep_links_still_carry_the_connected_account(
    cloud_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sharing the session must not silently drop the deep-link retargeting.

    A same-session lookup that quietly returned None would pass the
    session-count test above while regressing the feature it serves —
    the ``authuser`` retarget of every Gmail link.
    """

    from jobtracker.credentials.types import GmailCredentials

    app_id = await _seed_owner_row()

    async def fake_get_gmail_credentials(user_id, session=None):
        # The contract under test: the handler passes its OWN session in.
        assert session is not None, (
            "credential lookup ran outside the handler's session"
        )
        from datetime import datetime, timedelta

        return GmailCredentials(
            access_token="t",
            refresh_token="r",
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            email="owner@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )

    import jobtracker.credentials.cloud as cred_cloud

    monkeypatch.setattr(
        cred_cloud, "get_gmail_credentials", fake_get_gmail_credentials
    )

    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        detail = await client.get(f"/applications/{app_id}", headers=headers)
    assert detail.status_code == 200
    links = [m["gmail_link"] for m in detail.json()["messages"]]
    assert links and all(
        "authuser=owner%40example.com" in (link or "") for link in links
    ), links


@pytest.mark.asyncio
async def test_credential_lookup_failure_still_degrades_gracefully(
    cloud_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken credential read must never break the read endpoint.

    This was the property the separate session bought; it must survive the
    shared session. The lookup therefore runs LAST in the handler's session,
    after every row the response needs has been read.
    """

    import jobtracker.credentials.cloud as cred_cloud

    async def exploding(user_id, session=None):
        raise RuntimeError("user_credentials is on fire")

    monkeypatch.setattr(cred_cloud, "get_gmail_credentials", exploding)

    app_id = await _seed_owner_row()
    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in (
            "/applications",
            f"/applications/{app_id}",
            "/applications/review",
            "/applications/mail",
        ):
            response = await client.get(path, headers=headers)
            assert response.status_code == 200, (path, response.text)


class _FakeGucConn:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)


def test_transaction_gucs_are_one_round_trip_with_identity() -> None:
    """Both GUCs (search_path pin + RLS identity) travel in ONE statement.

    Every statement here is a network round trip on a fresh connection
    (~13 ms from iad1, and it is paid on every transaction). Two set_configs
    are one SELECT: ``SELECT set_config(...), set_config(...)``.
    """

    from jobtracker.database.connection import _apply_transaction_gucs, user_id_scope

    conn = _FakeGucConn()
    identity = uuid.UUID("abababab-abab-abab-abab-abababababab")
    with user_id_scope(identity):
        _apply_transaction_gucs(conn)

    assert len(conn.statements) == 1, conn.statements
    stmt = conn.statements[0]
    assert "set_config('search_path', 'public', true)" in stmt
    assert "request.jwt.claims" in stmt
    assert str(identity) in stmt
    # is_local=true on the identity too — nothing may outlive the transaction.
    assert re.search(r"request\.jwt\.claims'\s*,\s*'[^']*'\s*,\s*true", stmt), stmt


def test_transaction_gucs_without_identity_pin_search_path_only() -> None:
    """No identity → search_path pin only, and never an empty claims GUC."""

    from jobtracker.database.connection import _apply_transaction_gucs, user_id_scope

    conn = _FakeGucConn()
    with user_id_scope(None):
        _apply_transaction_gucs(conn)

    assert len(conn.statements) == 1, conn.statements
    assert "search_path" in conn.statements[0]
    assert "request.jwt.claims" not in conn.statements[0]


@pytest.mark.asyncio
async def test_server_timing_header_reports_request_phases(cloud_app) -> None:
    """The instrument #203 named as missing: per-request phase timing.

    Free (a response header + engine event counters), always on, readable in
    browser devtools and curl. A DB-touching request must report query time;
    every request must report total app time.
    """

    app_id = await _seed_owner_row()
    headers = {"Authorization": f"Bearer {_token_for(OWNER)}"}
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        detail = await client.get(f"/applications/{app_id}", headers=headers)

    for response in (health, detail):
        assert response.status_code == 200
        timing = response.headers.get("server-timing", "")
        assert re.search(r"app;dur=\d", timing), (
            f"no Server-Timing app phase on {response.request.url}: {timing!r}"
        )

    detail_timing = detail.headers["server-timing"]
    assert re.search(r'db_query;dur=[\d.]+;desc="n=\d+"', detail_timing), detail_timing
    # SQLite's StaticPool connects once per engine, so connect count may be 0
    # here — the phase itself must still be reported.
    assert "db_connect;dur=" in detail_timing, detail_timing


def test_pooling_knob_defaults_to_nullpool_and_opts_into_a_real_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``JOBTRACKER_DATABASE_POOL_SIZE`` — default 0 keeps today's NullPool.

    The remaining ~216 ms/request is the fresh TCP+TLS+auth connection NullPool
    mandates. Pooling through the transaction-mode pooler is safe for RLS
    (identity GUCs are transaction-local by construction) but is a deliberate,
    opt-in change of connection lifecycle — so the default must stay NullPool
    and the knob must actually engage a pre-pinging pool when set.
    """

    from sqlalchemy.pool import NullPool

    import jobtracker.database.connection as connection_module

    pg_url = "postgresql+asyncpg://user:pass@localhost:6543/postgres"

    # Patch the settings SINGLETON connection.py actually reads — reloading
    # jobtracker.config builds a new instance the engine never sees.
    monkeypatch.setattr(
        connection_module.settings, "database_url_override", pg_url
    )
    monkeypatch.setattr(connection_module.settings, "database_pool_size", 0)
    connection_module._engine = None
    try:
        engine = connection_module.get_engine()
        assert isinstance(engine.pool, NullPool)

        connection_module._engine = None
        monkeypatch.setattr(connection_module.settings, "database_pool_size", 2)
        engine = connection_module.get_engine()
        assert not isinstance(engine.pool, NullPool)
        assert engine.pool.size() == 2
        # pre_ping is what turns a pooler-killed idle connection into one
        # cheap round trip instead of a user-visible 500.
        assert engine.pool._pre_ping is True
    finally:
        connection_module._engine = None
        monkeypatch.undo()
