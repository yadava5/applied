"""The scheduled sync endpoint — auth, iteration, isolation, shape (issue #23).

WHAT IS FAKED AND WHAT IS REAL
------------------------------
The *sync service* is faked: ``jobtracker.cloud.gmail_oauth.gmail_sync`` is
replaced with a recorder, because the real one talks to Google. Everything else
is the genuine code path — the real router mounted on the real cloud app, the
real secret gate, the real enumeration query against a real (SQLite) database.

WHAT THIS FILE CANNOT PROVE
---------------------------
Anything about RLS. SQLite has no row-level security, so the per-user identity
binding that makes the enumeration work on Postgres is inert here — these tests
would be equally green with it removed. Three properties therefore have to be
proven on a real Postgres and are, in ``tests/test_rls_postgres.py``: that the
enrolled set really is enumerated under each user's own identity
(``test_cron_enumeration_uses_the_enrollment_table``), that the shared-connection
probe loop re-binds that identity per transaction and does not without its
rollback (``test_the_probe_loop_rebinds_identity_per_transaction`` and its
negative twin), and that syncing one user neither touches another's rows nor
leaves an identity bound afterwards
(``test_cron_syncs_only_the_enrolled_user_and_leaks_no_identity``).

What this file *does* prove is the surrounding contract: the gate,
``gmail_sync_enrollment`` being the only thing that selects users, the per-user
credential probe, ordering, bounding, and isolation of one user's failure.

ENROLLMENT IS SEEDED BY ``_connect_gmail`` IN EVERY TEST THAT EXPECTS WORK
--------------------------------------------------------------------------
An empty ``gmail_sync_enrollment`` means "sync nobody", so a test that seeds
credentials without enrolling gets zero candidates — a *visible* red, not a
silent pass. That is the intended direction: the fail-closed default cannot be
forgotten into a green run. ``_connect_gmail(..., enroll=False)`` is the
deliberate opt-out, and only two tests use it.

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
# DERIVED, not written out. Two reasons, and the second is the interesting one:
# a second literal here tripped the repo's gitleaks gate (generic-api-key,
# entropy 3.54) even though it is a throwaway — and a test file is not the place
# to teach the secret scanner to ignore things. Deriving it also *states* the
# property the gate needs proving against: a rejected secret that differs by one
# byte, not a wildly different string that a prefix comparison would also catch.
WRONG_SECRET = CRON_SECRET[:-1] + "X"
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


async def _connect_gmail(
    user_id: uuid.UUID, *, last_sync_at: datetime | None, enroll: bool = True
) -> None:
    """Give ``user_id`` a Gmail credential row, and optionally a sync cursor.

    Written straight to the DB rather than through the credential API: the
    enumeration never decrypts, so a real Fernet blob would only be ceremony,
    and the cursor row is what the least-recently-synced ordering reads.

    ``enroll`` writes the ``gmail_sync_enrollment`` row that production writes
    in the same transaction as the credential (``save_gmail_credentials``), and
    that the cron now enumerates. It defaults to ``True`` because that IS the
    production pairing; ``enroll=False`` exists for the one test that has to
    prove the enumeration reads the enrollment table and not
    ``user_credentials``.

    Real ``uuid.UUID`` objects throughout, deliberately: the connection module's
    GUC listener binds an identity only for a ``uuid.UUID`` and silently binds
    nothing for a ``str``, so a test that passed strings would exercise a code
    path production can never take.
    """

    assert isinstance(user_id, uuid.UUID), "enrollment holds UUIDs, not strings"

    from jobtracker.cloud.sync_state import GMAIL_ACCOUNT_TYPE
    from jobtracker.database import get_session
    from jobtracker.database.models import GmailSyncEnrollment, SyncState, UserCredential

    async with get_session() as session:
        session.add(
            UserCredential(
                user_id=user_id,
                kind="gmail_oauth",
                ciphertext=b"not-a-real-token",
            )
        )
        if enroll:
            session.add(GmailSyncEnrollment(user_id=user_id))
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
    """Being on the allowlist is not enough — the credential probe still runs.

    All three users are configured here. Only USER_A has Gmail linked, and only
    USER_A may be iterated. The allowlist is a set of *identities the cron may
    act as*, not an assertion that those users have a mailbox: without the
    per-user probe, a configured user who never connected (or who
    disconnected) would be handed to ``gmail_sync`` and would produce an
    ``errors[]`` entry on every run, forever.

    Also guards the enumeration against the lazy version of itself — "every
    user in the database" — which would spend a Gmail call per run on people
    who have never connected anything.
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
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented shape holds on the empty case too.

    The allowlist is deliberately POPULATED here while the database is empty,
    so this exercises the case it names — "configured users, none of whom has
    a mailbox" — rather than the trivially-empty allowlist, which is a
    different branch and gets its own test below.
    """


    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "users_synced": 0,
        "errors": [],
        "candidates": 0,
        # A run that reached nobody skipped nobody either. Present in the shape
        # because a lease conflict is NOT an error and has to be countable
        # separately — see the ``skipped`` field's own tests.
        "skipped": 0,
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
# The allowlist: it is the ONLY thing that selects users, and empty is closed.
# =============================================================================


async def test_the_enumeration_reads_enrollment_and_not_user_credentials(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``gmail_sync_enrollment`` is the source of the set, and the only one.

    USER_B here is a fully syncable user — a live Gmail credential row and a
    cursor, identical to USER_A in every respect except the enrollment row.
    That is what makes this test non-vacuous, and it is the exact assertion the
    design needs: the enumeration must read the membership table, because
    ``user_credentials`` is FORCE-RLS and an identity-less scan of it returns
    nothing on Postgres while returning EVERYTHING on SQLite. A revision that
    "simplified" this back to scanning ``user_credentials`` would be green on
    every other test in this file and red here.

    In production the two rows are written in one transaction
    (``save_gmail_credentials``), so this state does not occur; it is
    constructed to make the source of the answer observable.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(USER_A, last_sync_at=now - timedelta(hours=2))
    await _connect_gmail(USER_B, last_sync_at=now - timedelta(hours=1), enroll=False)

    record: list[uuid.UUID] = []
    monkeypatch.setattr(gmail_module, "gmail_sync", _fake_sync(record))

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    assert record == [USER_A], (
        f"The run synced {record}; only the ENROLLED USER_A may be touched."
    )
    assert response.json()["candidates"] == 1


async def test_an_empty_enrollment_table_syncs_nobody(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody enrolled is FAIL-CLOSED: zero users, not every user.

    The tempting reading of "the membership table is empty" is "no
    restriction", which would make a deployment walk every mailbox in the
    database on a schedule. Two users with connected mailboxes are seeded
    precisely so that "syncs nobody" cannot be true for the boring reason.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(
        USER_A, last_sync_at=now - timedelta(hours=2), enroll=False
    )
    await _connect_gmail(
        USER_B, last_sync_at=now - timedelta(hours=1), enroll=False
    )

    record: list[uuid.UUID] = []
    monkeypatch.setattr(gmail_module, "gmail_sync", _fake_sync(record))

    response = await client.post(
        "/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET}
    )
    assert response.status_code == 200, response.text
    assert record == [], "An empty enrollment table synced somebody."
    assert response.json()["candidates"] == 0


async def test_the_handler_ignores_any_user_selecting_input(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONFUSED DEPUTY. Nothing the caller sends may name whose mailbox is touched.

    This route authenticates a *caller* (a shared secret) and then acts with
    *other people's* authority. If any request input could select a user,
    anyone holding the cron secret — or anything that leaked it, e.g. a log —
    could sync an arbitrary tenant's mailbox on demand. The handler's only
    parameter is the raw ``Request`` and the invariant is written on it; this
    is the assertion that keeps it true.

    NON-VACUITY: USER_B is a fully seeded user with a live Gmail credential and
    a cursor — everything a sync needs — and is simply not enrolled. Naming a
    random UUID with no rows would pass forever regardless of the handler,
    because there would be nothing to sync even if the input WERE honoured.
    Here, if ``user_id`` were ever read, USER_B would appear in ``record``.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    now = datetime(2026, 8, 14, 12, 0, 0)
    await _connect_gmail(USER_A, last_sync_at=now - timedelta(hours=2))
    await _connect_gmail(USER_B, last_sync_at=now - timedelta(hours=1), enroll=False)

    record: list[uuid.UUID] = []
    monkeypatch.setattr(gmail_module, "gmail_sync", _fake_sync(record))

    # Every carrier a handler could plausibly read from, at once: query string,
    # JSON body, and a header, under both spellings the codebase uses.
    response = await client.post(
        f"/cron/sync?user_id={USER_B}&user_ids={USER_B}",
        headers={
            "x-vercel-cron-secret": CRON_SECRET,
            "x-user-id": str(USER_B),
        },
        json={"user_id": str(USER_B), "user_ids": [str(USER_B)]},
    )
    assert response.status_code == 200, response.text
    assert record == [USER_A], (
        f"The run synced {record}. Request input selected a user — this route "
        "must sync exactly the enrolled set and nothing else."
    )

    # The GET carrier Vercel actually uses, same probe.
    record.clear()
    getted = await client.get(
        f"/cron/sync?user_id={USER_B}",
        headers={"authorization": f"Bearer {CRON_SECRET}"},
    )
    assert getted.status_code == 200, getted.text
    assert record == [USER_A]

    # And the handler genuinely declares no user-selecting parameter, checked
    # against the signature rather than inferred from behaviour — a handler
    # that read `request.query_params` would still be caught above, but a
    # signature assertion is what stops one being ADDED.
    import inspect

    import jobtracker.cloud.cron as cron_module

    params = set(inspect.signature(cron_module.cron_sync).parameters)
    assert params == {"request"}, (
        f"cron_sync now takes {sorted(params)}. Any parameter beyond the raw "
        "Request is a way for the caller to name a victim."
    )


# =============================================================================
# The allowlist's env-var parse: real UUIDs, and junk stops the process.
# =============================================================================


def _settings_with_allowlist(monkeypatch: pytest.MonkeyPatch, raw: str):
    """Build a fresh ``Settings`` from the env var, as a deployment would."""

    from jobtracker.config import Settings

    monkeypatch.setenv("JOBTRACKER_CRON_SYNC_USER_IDS", raw)
    return Settings()


def test_the_allowlist_parses_from_the_env_var_as_uuid_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comma-separated env string → ``list[uuid.UUID]``, whitespace tolerated.

    ``uuid.UUID`` and not ``str`` is the load-bearing part.
    ``database.connection._apply_transaction_gucs`` binds the RLS identity only
    for a ``uuid.UUID`` — for a string it takes an early return and sets no
    claims at all, which RLS answers with zero rows and NO error. A list of
    strings here would therefore produce exactly the silent "syncs nobody"
    this whole change exists to end, so the element type is asserted directly.
    """

    a, b = uuid.uuid4(), uuid.uuid4()
    settings = _settings_with_allowlist(monkeypatch, f" {a} , {b} ")

    assert settings.cron_sync_user_ids == [a, b]
    assert all(isinstance(x, uuid.UUID) for x in settings.cron_sync_user_ids), (
        "Entries must be uuid.UUID objects; the GUC listener silently binds "
        "nothing for a str."
    )


def test_an_unset_or_empty_allowlist_parses_to_the_fail_closed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string and unset both mean "nobody", not "everybody"."""

    from jobtracker.config import Settings

    assert _settings_with_allowlist(monkeypatch, "").cron_sync_user_ids == []
    assert _settings_with_allowlist(monkeypatch, " , ").cron_sync_user_ids == []

    monkeypatch.delenv("JOBTRACKER_CRON_SYNC_USER_IDS", raising=False)
    assert Settings().cron_sync_user_ids == []


def test_junk_in_the_allowlist_fails_loudly_and_does_not_echo_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed entry raises at config load — it must not degrade to silence.

    The alternative failure mode is the dangerous one: a non-UUID entry that
    survived parsing would reach the ContextVar as a ``str``, the GUC listener
    would bind no identity for it, and the sync would read zero rows and report
    success. Loud beats silent here even though a bad value stops the process.

    The message names the failing INDEX and not the value: an operator can
    paste anything at all into a Vercel environment-variable box, and this
    error reaches the logs.

    THE JUNK VALUE HERE IS DELIBERATELY THREE CHARACTERS LONG. An earlier
    version of this test used a 32-character one and passed — not because the
    value was withheld, but because pydantic **truncates** ``input_value`` for
    display and the junk fell off the end. Pydantic v2 catches a ``ValueError``
    raised in a validator and renders ``input_value=<the whole env string>``
    alongside the message, so the no-echo property is only real if the
    exception is NOT a ``ValueError``. A short value sits well inside any
    truncation window, which is what makes the assertion below load-bearing
    rather than accidental. Do not lengthen it.
    """

    from jobtracker.config import CronSyncUserIdsError

    good = uuid.uuid4()
    junk = "zzz"

    with pytest.raises(CronSyncUserIdsError) as excinfo:
        _settings_with_allowlist(monkeypatch, f"{good},{junk}")

    rendered = str(excinfo.value)
    assert "entry #2" in rendered, (
        f"The error must name which entry failed; got: {rendered}"
    )
    assert junk not in rendered, (
        f"The offending value was echoed into the error, which reaches the "
        f"logs. Rendered: {rendered}"
    )
    # The whole env string must not appear either — that is the exact carrier
    # pydantic's ValidationError would have used.
    assert str(good) not in rendered, (
        f"The raw env var value was echoed. Rendered: {rendered}"
    )


# =============================================================================
# The WebSocket broadcast no-op (issue #23's second criterion).
#
# GONE, and this note is the record of why rather than a silent deletion.
#
# ``test_broadcast_is_a_no_op_where_no_websocket_router_can_exist`` built a
# ``jobtracker.api.websocket.SyncWebSocketManager``, flipped
# ``settings.deployment`` between "desktop" and "cloud", and asserted the
# broadcast delivered in the first and no-opped in the second. That whole module
# was deleted with the desktop routers -- Vercel's Python runtime has never
# supported WebSockets, the only caller was ``jobtracker/api/sync.py``, and the
# only client was the SwiftUI app's ``SyncWebSocketClient.swift``.
#
# So #23's second criterion is now satisfied structurally rather than by
# assertion: there is no broadcast to no-op, and no transport to gate on. That
# is a STRONGER guarantee than the test gave, but it is a different one, and if
# a WebSocket path is ever reintroduced the deployment branch has to be
# reintroduced with it -- and re-tested.
# =============================================================================

# =============================================================================
# A run that achieved nothing may not report success.
#
# ``/cron/sync`` answered 200 whether every user synced or every user failed.
# Vercel's cron dashboard reads the status code and nothing else, so the
# schedule showed green while nothing worked — this estate's documented "checks
# that cannot fail" shape, on the one surface nobody inspects by hand.
# =============================================================================


def _pin_candidates(monkeypatch: pytest.MonkeyPatch, *user_ids: uuid.UUID) -> None:
    """Pin the candidate list, so a test can be about the REPORTING alone.

    Enumeration has its own tests; seeding real credential rows here would make
    these assertions depend on two mechanisms at once.
    """

    import jobtracker.cloud.cron as cron_module

    async def _fake(limit: int, *, deadline: float | None = None) -> list[uuid.UUID]:
        return list(user_ids)[:limit]

    monkeypatch.setattr(cron_module, "list_syncable_user_ids", _fake)


def _per_user_result(monkeypatch: pytest.MonkeyPatch, behaviour) -> None:
    """Replace the per-user sync with ``behaviour(user_id)``."""

    import jobtracker.cloud.cron as cron_module

    async def _fake(user_id: uuid.UUID) -> None:
        await behaviour(user_id)

    monkeypatch.setattr(cron_module, "_sync_one_user", _fake)


async def _fire(client: AsyncClient):
    return await client.post("/cron/sync", headers={"x-vercel-cron-secret": CRON_SECRET})


async def test_a_run_where_every_user_failed_does_not_answer_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE DEFECT. Both candidates raise and the schedule still showed green."""

    _pin_candidates(monkeypatch, USER_A, USER_B)

    async def _always_fail(user_id: uuid.UUID) -> None:
        raise RuntimeError("gmail exploded")

    _per_user_result(monkeypatch, _always_fail)

    response = await _fire(client)

    assert response.status_code == 503, (
        f"a run that synced nobody and failed everybody answered "
        f"{response.status_code}"
    )
    body = response.json()
    assert body["users_synced"] == 0
    assert len(body["errors"]) == 2, body
    # The body survives the non-2xx. A status code alone would lose WHICH users
    # failed, which is the other half of being honest.
    assert all("RuntimeError" in e for e in body["errors"]), body


async def test_a_partial_failure_still_answers_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One of two failed — a working schedule with one bad mailbox.

    Pins the BOUNDARY: identical wiring to the test above, differing only in
    that one user succeeds. A dashboard that goes red on any single-user blip
    is a dashboard that gets muted.
    """

    _pin_candidates(monkeypatch, USER_A, USER_B)

    async def _fail_one(user_id: uuid.UUID) -> None:
        if user_id == USER_B:
            raise RuntimeError("gmail exploded")

    _per_user_result(monkeypatch, _fail_one)

    response = await _fire(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["users_synced"] == 1
    assert len(body["errors"]) == 1


async def test_a_run_that_only_collided_with_live_syncs_is_not_a_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE FALSE RED that ``skipped`` exists to prevent.

    Both users are mid-sync in their browsers, so the per-user lease refuses
    both. Every candidate went unsynced BY THIS RUN — and every one of them is
    being synced. Counting those as errors would fire the honest status code on
    the healthiest possible outcome.
    """

    import jobtracker.cloud.gmail_oauth as gmail_module

    _pin_candidates(monkeypatch, USER_A, USER_B)

    async def _already_running(user_id: uuid.UUID) -> None:
        # Read off the RELOADED module. ``_build_cloud_app`` reloads
        # gmail_oauth, which rebinds the class object; an instance of the
        # pre-reload class would not be caught by the handler's ``except``.
        raise gmail_module.SyncAlreadyRunning()

    _per_user_result(monkeypatch, _already_running)

    response = await _fire(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["skipped"] == 2, body
    assert body["errors"] == [], (
        "a lease conflict is not an error — it means a sync is already running"
    )


async def test_the_not_connected_409_is_still_an_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Gmail is not connected" is also a 409, and it IS a fault.

    It means the candidate list is stale: enumeration said this user has a
    mailbox and the sync disagreed. Matching the lease conflict on its STATUS
    CODE rather than its type would swallow this and let a wholly broken
    deployment report itself healthy — the same defect this section fixes, one
    level down.
    """

    from fastapi import HTTPException
    from fastapi import status as http_status

    _pin_candidates(monkeypatch, USER_A)

    async def _not_connected(user_id: uuid.UUID) -> None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Gmail is not connected for this user. Connect it first.",
        )

    _per_user_result(monkeypatch, _not_connected)

    response = await _fire(client)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["skipped"] == 0, body
    assert body["errors"] == [f"{USER_A}: HTTP409"], body


def _fake_enrollment(monkeypatch: pytest.MonkeyPatch, user_ids: list[uuid.UUID]) -> None:
    """Stand in for the enrollment query so the loop can be driven at any size."""

    import jobtracker.cloud.cron as cron_module

    async def _fake() -> list[uuid.UUID]:
        return list(user_ids)

    monkeypatch.setattr(cron_module, "list_enrolled_user_ids", _fake)


def _fake_probe(monkeypatch: pytest.MonkeyPatch, probes: list[uuid.UUID], last_sync):
    """Stand in for the per-user probe, recording who was asked about."""

    import jobtracker.cloud.cron as cron_module

    async def _fake(conn: Any, user_id: uuid.UUID):
        probes.append(user_id)
        return True, last_sync

    monkeypatch.setattr(cron_module, "_probe_sync_position", _fake)


async def test_the_enumeration_loop_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """``limit`` is applied AFTER probing every enrolled user.

    Ordering by cursor needs every candidate's cursor, so the batch cap cannot
    bound this loop and ``_CRON_MAX_PROBES`` has to. The cost per probe is far
    lower than it was — one round trip on an already-open connection rather than
    a fresh ~216 ms NullPool connection — but 500 enrolled users still cannot be
    allowed to consume a run that can only sync a handful.
    """

    import jobtracker.cloud.cron as cron_module

    enrolled = [uuid.uuid4() for _ in range(500)]
    _fake_enrollment(monkeypatch, enrolled)

    probes: list[uuid.UUID] = []
    _fake_probe(monkeypatch, probes, datetime.utcnow() - timedelta(hours=1))

    await cron_module.list_syncable_user_ids(5)

    assert len(probes) <= cron_module._CRON_MAX_PROBES, (
        f"the enumeration probed {len(probes)} of {len(enrolled)} enrolled "
        f"users; the cap is {cron_module._CRON_MAX_PROBES}"
    )
    # Non-vacuity: it must still probe enough to fill the batch, or "bounded"
    # would be satisfied by never enumerating anybody.
    assert len(probes) >= 5


async def test_the_enumeration_stops_on_the_run_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deadline already past stops the loop before the first probe."""

    import jobtracker.cloud.cron as cron_module

    _fake_enrollment(monkeypatch, [uuid.uuid4() for _ in range(10)])

    probes: list[uuid.UUID] = []
    _fake_probe(monkeypatch, probes, None)

    result = await cron_module.list_syncable_user_ids(5, deadline=time.monotonic() - 1)

    assert probes == []
    assert result == []


async def test_the_whole_enumeration_uses_one_connection(
    cloud_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE #294 FIX, asserted as a count rather than described in a docstring.

    This was one session — and under the cloud engine's NullPool, one fresh
    TCP+TLS+auth connection at ~216 ms — per enrolled user. At 300 users that is
    65 s of enumeration against a 45 s budget: a schedule that spends every
    invocation deciding who to sync and syncs nobody.

    Counted at the pool's ``checkout`` event, NOT at ``connect``. That choice is
    the whole reason this test can fail: the tests run on in-memory SQLite,
    which uses a ``StaticPool`` and therefore opens exactly ONE real connection
    no matter what the code does — a ``connect`` counter would read 1 for the
    per-user version too and assert nothing. ``checkout`` fires once per
    *acquisition*, which is precisely the unit that costs ~216 ms under the
    cloud engine's NullPool. Verified by reverting the loop to a connection per
    user: the count went to 27 and this assertion went red.

    Two acquisitions are permitted for the whole enumeration: one for the
    enrollment query and one held open across every probe. What must NOT happen
    is a count that grows with the number of users — so the assertion is made
    against a population large enough that per-user acquisition is unmissable.

    ``cloud_app`` rather than ``client``: this drives the enumeration directly,
    but it still needs the reloaded engine the fixture builds.
    """

    from sqlalchemy import event

    import jobtracker.cloud.cron as cron_module
    from jobtracker.database.connection import get_engine

    users = [uuid.uuid4() for _ in range(25)]
    for index, user_id in enumerate(users):
        await _connect_gmail(
            user_id, last_sync_at=datetime(2026, 8, 1, 12, 0, 0) + timedelta(minutes=index)
        )

    checkouts: list[int] = []
    engine = get_engine()

    @event.listens_for(engine.sync_engine, "checkout")
    def _count(*_args: Any) -> None:
        checkouts.append(1)

    try:
        candidates = await cron_module.list_syncable_user_ids(100)
    finally:
        event.remove(engine.sync_engine, "checkout", _count)

    # Non-vacuity first: if the enumeration returned nobody, zero acquisitions
    # would also satisfy the bound below.
    assert len(candidates) == len(users), candidates
    assert len(checkouts) <= 2, (
        f"{len(checkouts)} connection checkouts for {len(users)} users. The "
        "enumeration is acquiring one per user again — that is the #294 "
        "regression, and it costs ~216 ms each in production."
    )
