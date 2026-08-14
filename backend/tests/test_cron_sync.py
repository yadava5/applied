"""The scheduled sync endpoint — auth, iteration, isolation, shape (issue #23).

WHAT IS FAKED AND WHAT IS REAL
------------------------------
The *sync service* is faked: ``jobtracker.cloud.gmail_oauth.gmail_sync`` is
replaced with a recorder, because the real one talks to Google. Everything else
is the genuine code path — the real router mounted on the real cloud app, the
real secret gate, the real enumeration query against a real (SQLite) database.

WHAT THIS FILE CANNOT PROVE
---------------------------
That the enumeration returns anybody **in production**. ``user_credentials``
carries FORCE'd Row-Level Security keyed on ``auth.uid()``, and a cron has no
authenticated user, so on Postgres the query below matches no row. SQLite has
no RLS, so these tests are green either way. The Postgres-backed proof lives in
``tests/test_rls_postgres.py::test_cron_enumeration_sees_no_users_without_identity``
and it asserts the *failure*, deliberately, so the gap is a recorded fact
rather than a surprise. See ``jobtracker.cloud.cron.list_syncable_user_ids``.

THE GATE MUST BE ABLE TO FAIL
-----------------------------
``test_cron_route_is_mounted_for_both_methods`` exists so the 403 assertions
below cannot pass for the wrong reason: an endpoint that does not exist answers
404, and a 403 test that is really testing a missing route is the exact defect
shape this repo keeps finding. Deleting the ``_authorize(request)`` call from
the handler turns every 403 assertion here red — verified by doing it.
"""

from __future__ import annotations

import asyncio
import importlib
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

CRON_SECRET = "cron-c7-test-secret-at-least-16-chars"
WRONG_SECRET = "cron-c7-test-secret-at-least-16-chaR"  # one byte different
JWT_SECRET = "cron-c7-test-jwt-secret-at-least-32-bytes-long-hs256"
ENC_KEY = Fernet.generate_key().decode()

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_C = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


async def _build_cloud_app(monkeypatch: pytest.MonkeyPatch, *, secret: str | None) -> Any:
    """Reload the cloud app with (or without) a configured cron secret.

    Mirrors the proven reload sequence in ``test_gmail_oauth_cloud`` and adds
    ``jobtracker.cloud.cron`` — that module holds a ``settings`` global, so it
    must be rebound after the config reload or it answers for the previous
    environment.

    ``CRON_SECRET`` is deleted from the environment on every build. It is a
    real fallback in the handler (it is the variable Vercel itself reads), so a
    developer who happens to have one exported would otherwise make the
    "unconfigured deployment" test pass while configured.
    """

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_ENVIRONMENT", "test")
    monkeypatch.setenv("JOBTRACKER_SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", ENC_KEY)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    if secret is None:
        monkeypatch.delenv("JOBTRACKER_VERCEL_CRON_SECRET", raising=False)
    else:
        monkeypatch.setenv("JOBTRACKER_VERCEL_CRON_SECRET", secret)

    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    importlib.reload(config_module)
    connection_module._engine = None

    import jobtracker.auth.supabase_jwt as auth_module

    importlib.reload(auth_module)

    import jobtracker.credentials.cloud as cred_cloud_module

    importlib.reload(cred_cloud_module)

    import jobtracker.cloud.applications as cloud_apps_module

    importlib.reload(cloud_apps_module)

    import jobtracker.cloud.gmail_oauth as gmail_module

    importlib.reload(gmail_module)

    import jobtracker.cloud.cron as cron_module

    importlib.reload(cron_module)

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)

    from jobtracker.database import init_db

    await init_db()

    return main_cloud_module.app


async def _teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    if connection_module._engine is not None:
        await connection_module._engine.dispose()
    connection_module._engine = None
    monkeypatch.undo()
    importlib.reload(config_module)


@pytest.fixture
async def cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app with a cron secret configured."""

    yield await _build_cloud_app(monkeypatch, secret=CRON_SECRET)
    await _teardown(monkeypatch)


@pytest.fixture
async def unconfigured_cloud_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """The cloud app with NO cron secret configured anywhere."""

    yield await _build_cloud_app(monkeypatch, secret=None)
    await _teardown(monkeypatch)


@pytest.fixture
async def client(cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cron-test") as c:
        yield c


@pytest.fixture
async def unconfigured_client(unconfigured_cloud_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=unconfigured_cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cron-test") as c:
        yield c


async def _connect_gmail(user_id: uuid.UUID, *, last_sync_at: datetime | None) -> None:
    """Give ``user_id`` a Gmail credential row, and optionally a sync cursor.

    Written straight to the DB rather than through the credential API: the
    enumeration never decrypts, so a real Fernet blob would only be ceremony,
    and the cursor row is what the least-recently-synced ordering reads.
    """

    from jobtracker.cloud.sync_state import GMAIL_ACCOUNT_TYPE
    from jobtracker.database import get_session
    from jobtracker.database.models import SyncState, UserCredential

    async with get_session() as session:
        session.add(
            UserCredential(
                user_id=user_id,
                kind="gmail_oauth",
                ciphertext=b"not-a-real-token",
            )
        )
        if last_sync_at is not None:
            session.add(
                SyncState(
                    user_id=user_id,
                    account_type=GMAIL_ACCOUNT_TYPE,
                    account_email=f"{user_id}@example.test",
                    last_sync_at=last_sync_at,
                )
            )
        await session.commit()


def _fake_sync(record: list[uuid.UUID], **behaviour: Any):
    """A stand-in for ``gmail_sync`` that records who it was asked to sync.

    ``behaviour`` maps a ``user_id`` to what that user's sync should do:
    ``"hang"`` sleeps past the per-user timeout, ``"raise"`` blows up. Anything
    else succeeds.
    """

    async def fake(payload: Any, user_id: uuid.UUID | None = None, **_: Any) -> Any:
        record.append(user_id)
        action = behaviour.get(str(user_id))
        if action == "hang":
            await asyncio.sleep(5.0)
        elif action == "raise":
            raise RuntimeError("bearer ya29.SECRET-TOKEN-MUST-NOT-LEAK")
        return None

    return fake


# =============================================================================
# The gate. These are the assertions that must go red if the check is removed.
# =============================================================================


def test_cron_route_is_mounted_for_both_methods(cloud_app) -> None:
    """Positive control for every 403 below: the route exists, GET and POST.

    A missing route answers 404, not 403 — but this repo has shipped a "check"
    that passed because the thing it checked was not there, so the route table
    is asserted directly rather than inferred from a status code.

    GET matters on its own: Vercel Cron makes an HTTP **GET** request to the
    configured path. A POST-only route (which is what issue #23 specifies)
    would 405 on every scheduled invocation forever.
    """

    def walk(routes: Any) -> Any:
        for route in routes:
            yield route
            original = getattr(route, "original_router", None)
            if original is not None:
                yield from walk(getattr(original, "routes", []) or [])
            nested = getattr(route, "routes", None)
            if nested and original is None:
                yield from walk(nested)

    methods: set[str] = set()
    for route in walk(cloud_app.routes):
        if getattr(route, "path", None) == "/cron/sync":
            methods |= set(getattr(route, "methods", None) or [])

    assert methods, "/cron/sync is not mounted on the cloud app at all."
    assert {"GET", "POST"} <= methods, (
        f"/cron/sync answers {sorted(methods)}. Vercel Cron sends GET; the "
        "issue's manual probe sends POST. Both are required."
    )


async def test_missing_secret_is_403(client: AsyncClient) -> None:
    response = await client.post("/cron/sync")
    assert response.status_code == 403, response.text


async def test_wrong_secret_is_403(client: AsyncClient) -> None:
    """One byte different is refused — via both accepted carriers."""

    header = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": WRONG_SECRET}
    )
    bearer = await client.post(
        "/cron/sync", headers={"authorization": f"Bearer {WRONG_SECRET}"}
    )
    assert header.status_code == 403, header.text
    assert bearer.status_code == 403, bearer.text


async def test_empty_secret_header_is_403(client: AsyncClient) -> None:
    """An empty header must not compare equal to anything."""

    response = await client.post("/cron/sync", headers={"x-vercel-cron-secret": ""})
    assert response.status_code == 403, response.text


async def test_unconfigured_deployment_fails_closed(
    unconfigured_client: AsyncClient,
) -> None:
    """No secret set anywhere → 403, never an open endpoint.

    The tempting reading of "no secret configured" is "no gate", which would
    make a deployment that forgot the env var serve every user's mailbox walk
    to anyone who found the path.
    """

    response = await unconfigured_client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 403, response.text
    # A refused call must not report work it did not do.
    assert "users_synced" not in response.text


async def test_a_refused_call_does_no_work(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate runs before the enumeration, not after it.

    An endpoint that enumerated every user and *then* checked the secret would
    still be a 403 — and would still be a way to make an unauthenticated
    caller cost the database a query per probe.
    """

    import jobtracker.cloud.cron as cron_module

    called = False

    async def boom(_limit: int) -> list[uuid.UUID]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(cron_module, "list_syncable_user_ids", boom)

    response = await client.post("/cron/sync", headers={"x-vercel-cron-secret": "nope"})
    assert response.status_code == 403
    assert not called, "The enumeration ran before the secret was checked."


# =============================================================================
# Authorised behaviour: iteration, isolation, shape.
# =============================================================================


async def test_correct_secret_syncs_every_connected_user(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both carriers are accepted, and every connected user is iterated."""

    import jobtracker.cloud.cron as cron_module
    import jobtracker.cloud.gmail_oauth as gmail_module

    await _connect_gmail(USER_A, last_sync_at=None)
    await _connect_gmail(USER_B, last_sync_at=datetime(2026, 8, 1, 12, 0, 0))

    record: list[uuid.UUID] = []
    monkeypatch.setattr(gmail_module, "gmail_sync", _fake_sync(record))

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["users_synced"] == 2
    assert body["errors"] == []
    assert set(record) == {USER_A, USER_B}

    # Vercel's own carrier, on a GET, which is how the schedule actually fires.
    record.clear()
    getted = await client.get(
        "/cron/sync", headers={"authorization": f"Bearer {CRON_SECRET}"}
    )
    assert getted.status_code == 200, getted.text
    assert getted.json()["users_synced"] == 2
    assert set(record) == {USER_A, USER_B}

    assert cron_module.CRON_SECRET_HEADER == "x-vercel-cron-secret"


async def test_users_without_a_mailbox_are_not_iterated(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only users with a connected Gmail credential are candidates.

    Guards the enumeration against the lazy version of itself — "every user in
    the database" — which would spend a Gmail call per run on people who have
    never connected anything.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.database import get_session
    from jobtracker.database.models import Application, ApplicationStatus, UserCredential

    await _connect_gmail(USER_A, last_sync_at=None)
    async with get_session() as session:
        # USER_B exists in the product but has no mailbox linked.
        session.add(
            Application(
                user_id=USER_B,
                company="Acme",
                position="SWE",
                status=ApplicationStatus.APPLIED,
            )
        )
        # USER_C linked iCloud, not Gmail.
        session.add(
            UserCredential(user_id=USER_C, kind="icloud_mail", ciphertext=b"x")
        )
        await session.commit()

    record: list[uuid.UUID] = []
    monkeypatch.setattr(gmail_module, "gmail_sync", _fake_sync(record))

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    assert record == [USER_A]
    assert response.json()["candidates"] == 1


async def test_least_recently_synced_users_go_first(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordering is what makes a bounded batch fair rather than starving.

    A run that stops on its time budget must leave the users it skipped at the
    front of the next run's queue. Without an order, a fixed batch would sync
    the same arbitrary handful forever.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(USER_A, last_sync_at=now)
    await _connect_gmail(USER_B, last_sync_at=now - timedelta(hours=3))
    await _connect_gmail(USER_C, last_sync_at=None)  # never synced

    record: list[uuid.UUID] = []
    monkeypatch.setattr(gmail_module, "gmail_sync", _fake_sync(record))

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    assert record == [USER_C, USER_B, USER_A], (
        "Candidates must be ordered never-synced first, then oldest sync first."
    )


async def test_one_users_timeout_does_not_abort_the_batch(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung mailbox is isolated: it lands in ``errors``, the rest still sync.

    The per-user timeout is shortened for the test; the constant it replaces is
    read from module globals at call time, so this exercises the real
    ``asyncio.wait_for`` wrapping rather than a stand-in for it.
    """

    import jobtracker.cloud.cron as cron_module
    import jobtracker.cloud.gmail_oauth as gmail_module

    monkeypatch.setattr(cron_module, "_CRON_PER_USER_TIMEOUT_SECONDS", 0.05)

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(USER_A, last_sync_at=now - timedelta(hours=3))
    await _connect_gmail(USER_B, last_sync_at=now - timedelta(hours=2))
    await _connect_gmail(USER_C, last_sync_at=now - timedelta(hours=1))

    record: list[uuid.UUID] = []
    monkeypatch.setattr(
        gmail_module, "gmail_sync", _fake_sync(record, **{str(USER_B): "hang"})
    )

    started = time.monotonic()
    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["users_synced"] == 2
    assert body["errors"] == [f"{USER_B}: TimeoutError"]
    assert record == [USER_A, USER_B, USER_C], (
        "The batch must continue past the hung user, not stop at it."
    )
    assert elapsed < 4.0, (
        f"The run took {elapsed:.2f}s — the hung user was awaited to "
        "completion instead of being cancelled at its timeout."
    )


async def test_one_users_exception_does_not_abort_the_batch_and_leaks_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising sync is caught, reported by TYPE, and never by message.

    The fake raises an exception whose message contains a token-shaped string.
    ``errors`` is returned over the wire, so a handler that formatted ``str(exc)``
    into it would put a bearer token in an HTTP response.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(USER_A, last_sync_at=now - timedelta(hours=2))
    await _connect_gmail(USER_B, last_sync_at=now - timedelta(hours=1))

    record: list[uuid.UUID] = []
    monkeypatch.setattr(
        gmail_module, "gmail_sync", _fake_sync(record, **{str(USER_A): "raise"})
    )

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["users_synced"] == 1
    assert body["errors"] == [f"{USER_A}: RuntimeError"]
    assert record == [USER_A, USER_B]
    assert "ya29" not in response.text, (
        "The exception message reached the response body — that is where a "
        "Gmail token would have gone."
    )


async def test_batch_size_bounds_the_users_touched(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``settings.sync_batch_size`` is the ceiling on users per invocation."""

    import jobtracker.cloud.cron as cron_module
    import jobtracker.cloud.gmail_oauth as gmail_module

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(USER_A, last_sync_at=now - timedelta(hours=3))
    await _connect_gmail(USER_B, last_sync_at=now - timedelta(hours=2))
    await _connect_gmail(USER_C, last_sync_at=now - timedelta(hours=1))

    monkeypatch.setattr(cron_module.settings, "sync_batch_size", 2)

    record: list[uuid.UUID] = []
    monkeypatch.setattr(gmail_module, "gmail_sync", _fake_sync(record))

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["users_synced"] == 2
    assert record == [USER_A, USER_B]
    assert body["stopped_by"] == "batch"


async def test_run_deadline_stops_the_batch_before_the_function_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run budget, not the batch cap, is what usually stops a run.

    ``vercel.json`` gives the function ``maxDuration: 60``; at 10 s per user
    the deadline is reached long before a cap of 100 users is. Checked BEFORE a
    user's sync starts, so nothing can begin inside the budget and finish
    outside it.
    """

    import jobtracker.cloud.cron as cron_module
    import jobtracker.cloud.gmail_oauth as gmail_module

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(USER_A, last_sync_at=now - timedelta(hours=3))
    await _connect_gmail(USER_B, last_sync_at=now - timedelta(hours=2))
    await _connect_gmail(USER_C, last_sync_at=now - timedelta(hours=1))

    monkeypatch.setattr(cron_module, "_CRON_RUN_BUDGET_SECONDS", 0.15)

    record: list[uuid.UUID] = []

    async def slow(payload: Any, user_id: uuid.UUID | None = None, **_: Any) -> Any:
        record.append(user_id)
        await asyncio.sleep(0.1)

    monkeypatch.setattr(gmail_module, "gmail_sync", slow)

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stopped_by"] == "deadline"
    assert len(record) < 3, "The deadline did not stop the batch."
    assert body["candidates"] == 3, (
        "The response must still report how many users were waiting."
    )


async def test_return_shape_when_nobody_has_connected_a_mailbox(
    client: AsyncClient,
) -> None:
    """The documented shape holds on the empty case too."""

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "users_synced": 0,
        "errors": [],
        "candidates": 0,
        "stopped_by": "complete",
    }


async def test_the_sync_runs_under_the_users_own_rls_identity(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-user identity is bound around each sync — the whole isolation story.

    The cron has no JWT. If it did not bind an identity per user, every read
    inside the sync would run with ``auth.uid()`` NULL: on Postgres that fails
    closed (nothing syncs), and the alternative someone would reach for — a
    privileged unscoped connection — is a cross-tenant write waiting to happen.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.database.connection import get_current_user_id

    await _connect_gmail(USER_A, last_sync_at=None)

    seen: list[uuid.UUID | None] = []

    async def observing(payload: Any, user_id: uuid.UUID | None = None, **_: Any) -> Any:
        seen.append(get_current_user_id())

    monkeypatch.setattr(gmail_module, "gmail_sync", observing)

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    assert seen == [USER_A], (
        f"RLS identity during the sync was {seen}, not the user being synced."
    )

    # …and it is released afterwards, so nothing inherits it.
    assert get_current_user_id() is None


# =============================================================================
# The WebSocket broadcast no-op (issue #23's second criterion).
# =============================================================================


async def test_broadcast_is_a_no_op_where_no_websocket_router_can_exist() -> None:
    """``sync_ws_manager.broadcast`` no-ops in cloud and delivers on desktop.

    Both paths, because "it does nothing" is only meaningful next to a run
    where it does something — a broadcast that never delivered anywhere would
    satisfy the cloud half on its own.
    """

    import jobtracker.api.websocket as ws_module

    delivered: list[dict[str, Any]] = []

    class FakeConnection:
        async def send_json(self, message: dict[str, Any]) -> None:
            delivered.append(message)

    manager = ws_module.SyncWebSocketManager()
    manager._connections.add(FakeConnection())  # type: ignore[arg-type]

    # Desktop: the transport exists, the message is delivered.
    original = ws_module.settings.deployment
    try:
        ws_module.settings.deployment = "desktop"
        await manager.broadcast({"event": "started"})
        assert delivered == [{"event": "started"}]

        # Cloud: no router can be mounted, so this is a no-op — with the SAME
        # call site and the SAME registered connection.
        ws_module.settings.deployment = "cloud"
        await manager.broadcast({"event": "completed"})
        assert delivered == [{"event": "started"}], (
            "broadcast() delivered in cloud mode, where no WebSocket router "
            "can be mounted."
        )
        assert ws_module.websocket_transport_available() is False
    finally:
        ws_module.settings.deployment = original
