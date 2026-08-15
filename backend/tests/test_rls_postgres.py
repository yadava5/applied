"""Real-Postgres Row-Level-Security enforcement tests.

Unlike the SQLite suites (which can only exercise the application-level
``user_id`` filter), these tests stand up a **real** PostgreSQL database, a
Supabase-shaped ``auth`` schema (``auth.users`` + ``auth.uid()``), and a
dedicated **non-``BYPASSRLS``** application role, then drive the *actual*
production machinery — ``jobtracker.database.connection.get_session`` with its
per-transaction ``request.jwt.claims`` GUC + ``search_path`` pinning, plus the
cloud application/credential write paths — to prove RLS genuinely isolates
tenants at the database layer.

They validate the three enforcement guarantees the hardening work exists to
provide:

1. With the GUC set, the app role inserts + reads **only** its own rows.
2. Without the GUC, inserts are rejected and cross-user reads return nothing
   (fail-closed).
3. The non-``BYPASSRLS`` role cannot see another user's rows even with the
   application-level ``WHERE user_id = ...`` filter removed (raw SQL) — i.e.
   the database, not the app, is enforcing isolation.

Plus the pooling-safety property (no GUC leak across users on a reused
engine), multi-transaction re-application, and the upsert + credential-save
paths specifically.

The module is **skipped entirely** unless ``JOBTRACKER_TEST_PG_ADMIN_URL`` is
set to a superuser SQLAlchemy async URL, e.g.::

    JOBTRACKER_TEST_PG_ADMIN_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/jobtracker \
        pytest tests/test_rls_postgres.py

so ordinary CI / desktop runs (no Postgres) stay green.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _resolve_admin_url():
    """Find a superuser Postgres, starting one if that is what it takes.

    WHY THIS IS NOT JUST A SKIPIF ANY MORE
    --------------------------------------
    This module holds the only proof that tenant isolation is enforced by the
    DATABASE rather than by application code that could forget a WHERE clause.
    It used to skip unless a human had exported JOBTRACKER_TEST_PG_ADMIN_URL by
    hand -- and a skip is green, so the default experience was ten silent skips
    and a passing suite.

    That default held. As of 2026-08-02 these ten tests had never executed
    anywhere: not locally, and not in CI either, because the job that runs them
    could not trigger on the branch the work lives on.

    A test worth writing is worth running by default. So:

      1. an explicit JOBTRACKER_TEST_PG_ADMIN_URL always wins -- CI sets it
         against its own service container, and that path is unchanged;
      2. otherwise, if Docker is available, start a throwaway postgres:16 and
         use that. Nothing to remember, nothing to export;
      3. only if there is no Docker either do we skip -- and that skip now
         means "this machine cannot run Postgres", not "nobody set a variable".
    """

    explicit = os.environ.get("JOBTRACKER_TEST_PG_ADMIN_URL")
    if explicit:
        return explicit, None

    try:
        from testcontainers.community.postgres import PostgresContainer
    except Exception:  # pragma: no cover - machine without the test extra
        return None, None

    try:
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception:  # pragma: no cover - no docker daemon, or it refused
        return None, None

    url = container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    return url, container


ADMIN_URL, _OWNED_CONTAINER = _resolve_admin_url()


_CONTAINER_STOPPED = False


def _stop_owned_container() -> None:
    """Stop the throwaway container once, from whichever path reaches it first.

    WHY ``teardown_module`` ALONE IS NOT ENOUGH
    -------------------------------------------
    The container is started at **import** time (``_resolve_admin_url`` runs at
    module scope), but ``teardown_module`` only fires once pytest has actually
    *executed* a test in this module. Every run that imports the module without
    running its tests therefore leaves a ``postgres:16`` up forever:
    ``--collect-only``, a ``-k`` expression that deselects everything here, or
    an earlier ``-x`` failure that aborts the session before this file's turn.

    That is not a hypothesis. ``pytest tests/test_rls_postgres.py
    --collect-only`` leaves a container running, and nothing reaps it — watched
    for 90 s, still up — which is exactly the reported "postgres:16 still
    running 15 minutes after the suite exited 0". A full run stops it correctly,
    which is why it looked intermittent.

    ``atexit`` covers every one of those paths. ``teardown_module`` still calls
    this so the normal case releases the port promptly rather than at process
    exit, and the flag makes the second call a no-op — ``stop()`` on an
    already-removed container raises.
    """

    global _CONTAINER_STOPPED

    if _OWNED_CONTAINER is None or _CONTAINER_STOPPED:
        return
    _CONTAINER_STOPPED = True
    with contextlib.suppress(Exception):  # already gone, or the daemon went away
        _OWNED_CONTAINER.stop()


if _OWNED_CONTAINER is not None:
    atexit.register(_stop_owned_container)


def teardown_module(module) -> None:  # noqa: ANN001 - pytest hook signature
    """Stop the container we started, if we started one."""

    _stop_owned_container()


pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason=(
        "No Postgres available: set JOBTRACKER_TEST_PG_ADMIN_URL to a superuser "
        "postgresql+asyncpg URL, or run Docker so a throwaway postgres:16 can be "
        "started automatically. These tests are the only proof of database-level "
        "tenant isolation, so skipping them leaves it UNVERIFIED on this run."
    ),
)

APP_ROLE = "jt_rls_app"
APP_PW = "jt_rls_app_pw"

# Deterministic Fernet key (any valid key; only used to exercise the credential
# encrypt/decrypt round-trip through the FORCE'd user_credentials table).
_FERNET_KEY = "fxHtKRWuaD2nQbNZoAzwEo9pG_Q4AoHTsWvj1_RlrZw="

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

_ENTITY_TABLES = [
    "applications",
    "emails",
    "contacts",
    "interviews",
    "training_data",
    "email_embeddings",
    "sync_state",
]


def _app_url() -> str:
    """The app-role SQLAlchemy async URL derived from the admin URL."""

    return (
        make_url(ADMIN_URL)
        .set(username=APP_ROLE, password=APP_PW)
        .render_as_string(hide_password=False)
    )


async def _admin_build(engine: AsyncEngine) -> None:
    """Build a clean schema + Supabase auth shim + non-bypass role + RLS."""

    from sqlmodel import SQLModel

    import jobtracker.database.models  # noqa: F401 — register metadata

    async with engine.begin() as c:
        await c.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await c.execute(text("CREATE SCHEMA public"))
        await c.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
        await c.execute(text("CREATE TABLE IF NOT EXISTS auth.users (id uuid primary key)"))
        # Supabase's auth.uid(): the sub claim out of the request.jwt.claims GUC.
        await c.execute(
            text(
                "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid "
                "LANGUAGE sql STABLE AS $$ "
                "SELECT nullif(current_setting('request.jwt.claims', true)::jsonb "
                "->> 'sub', '')::uuid $$"
            )
        )
        await c.execute(
            text("INSERT INTO auth.users(id) VALUES (:a),(:b) ON CONFLICT DO NOTHING"),
            {"a": str(USER_A), "b": str(USER_B)},
        )
        # Non-bypass, least-privilege app role (idempotent reset).
        await c.execute(
            text(
                "DO $$ BEGIN "
                f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{APP_ROLE}') THEN "
                f"EXECUTE 'DROP OWNED BY {APP_ROLE} CASCADE'; "
                f"EXECUTE 'DROP ROLE {APP_ROLE}'; "
                "END IF; END $$"
            )
        )
        await c.execute(
            text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PW}' NOBYPASSRLS NOSUPERUSER")
        )

    async with engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)

    async with engine.begin() as c:
        # Least-privilege grants: USAGE on schema, CRUD on tables, USAGE on
        # sequences (for SERIAL ids) — nothing more.
        await c.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        await c.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
            )
        )
        await c.execute(
            text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
        )
        await c.execute(text(f"GRANT USAGE ON SCHEMA auth TO {APP_ROLE}"))
        await c.execute(text(f"GRANT EXECUTE ON FUNCTION auth.uid() TO {APP_ROLE}"))

        # RLS mirrors the migrations exactly: entity tables ENABLE+FORCE+4
        # policies (a8d4ec5fba26); user_credentials ENABLE+4 policies
        # (c4user_creds_rls) + FORCE (c5_force_user_creds_rls); and every
        # predicate in the hoisted `(SELECT auth.uid())` form that
        # c6_rls_initplan_hoist leaves production in.
        #
        # The sub-select is not cosmetic and it is not optional here. Bare
        # `auth.uid()` is STABLE, so the planner re-evaluates it once PER ROW;
        # wrapping it makes it an uncorrelated subquery hoisted into an
        # InitPlan evaluated once per query (Supabase's `auth_rls_initplan`
        # lint). The comparison is identical either way, which is exactly why
        # these tests must run the shape production runs: if this shim kept
        # the bare form, the suite would go on proving the OLD policies and
        # would tell us nothing about the ones actually deployed.
        for t in _ENTITY_TABLES:
            await c.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
            await c.execute(text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
            await c.execute(
                text(
                    f"CREATE POLICY {t}_select ON {t} FOR SELECT "
                    "USING (user_id = (SELECT auth.uid()))"
                )
            )
            await c.execute(
                text(
                    f"CREATE POLICY {t}_insert ON {t} FOR INSERT "
                    "WITH CHECK (user_id = (SELECT auth.uid()))"
                )
            )
            await c.execute(
                text(
                    f"CREATE POLICY {t}_update ON {t} FOR UPDATE "
                    "USING (user_id = (SELECT auth.uid())) "
                    "WITH CHECK (user_id = (SELECT auth.uid()))"
                )
            )
            await c.execute(
                text(
                    f"CREATE POLICY {t}_delete ON {t} FOR DELETE "
                    "USING (user_id = (SELECT auth.uid()))"
                )
            )
        await c.execute(text("ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY"))
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_select ON user_credentials "
                "FOR SELECT USING (user_id = (SELECT auth.uid()))"
            )
        )
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_insert ON user_credentials "
                "FOR INSERT WITH CHECK (user_id = (SELECT auth.uid()))"
            )
        )
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_update ON user_credentials "
                "FOR UPDATE USING (user_id = (SELECT auth.uid())) "
                "WITH CHECK (user_id = (SELECT auth.uid()))"
            )
        )
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_delete ON user_credentials "
                "FOR DELETE USING (user_id = (SELECT auth.uid()))"
            )
        )
        await c.execute(text("ALTER TABLE user_credentials FORCE ROW LEVEL SECURITY"))


# Build the schema/role/RLS exactly once across the module; each test just
# truncates the tenant tables. Kept function-scoped (fresh admin engine per
# test, created + disposed inside that test's event loop) to sidestep
# pytest-asyncio's function-scoped event loop vs. module-scoped async fixture
# mismatch.
_SCHEMA_READY = False


def _live_settings_instances() -> list[Any]:
    """Every distinct ``Settings`` object currently reachable from a loaded module.

    There is normally exactly one. But ``test_credentials_cloud``,
    ``test_gmail_oauth_cloud``, ``test_main_cloud`` and ``test_user_id_scoping``
    each call ``importlib.reload(jobtracker.config)``, which **rebinds
    ``jobtracker.config.settings`` to a brand-new object** while every module
    that did ``from jobtracker.config import settings`` at import time keeps
    holding the old one. Three of those four sort before this module
    alphabetically, so in a full-suite run ``jobtracker.database.connection``
    and ``jobtracker.config`` are routinely looking at different instances.

    Setting ``database_url_override`` on only one of them is how this suite
    silently ran against in-memory SQLite instead of Postgres: ``get_engine()``
    read the stale instance, saw ``environment == "test"``, and returned
    ``sqlite+aiosqlite:///:memory:``. Eight tests failed with "no such table";
    the two that use the admin engine directly still passed.

    Collecting by ``id()`` covers whichever instances exist, in any order.

    Identified by duck-typing, deliberately, **not** ``isinstance``: the reload
    rebuilds the ``Settings`` class as well as the instance, so a stale object
    is not an instance of the freshly-imported class and an ``isinstance``
    filter silently skips exactly the object that needs patching.
    """
    import sys

    found: dict[int, Any] = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("jobtracker") or module is None:
            continue
        candidate = getattr(module, "settings", None)
        if candidate is None:
            continue
        if hasattr(candidate, "database_url_override") and hasattr(
            candidate, "secret_encryption_key"
        ):
            found.setdefault(id(candidate), candidate)
    return list(found.values())


@pytest.fixture
async def pg_app() -> AsyncIterator[AsyncEngine]:
    """Point the real connection module at the non-bypass app role.

    Mutates the ``settings`` attributes in place — no ``importlib.reload``
    dance — but applies the change to *every* live ``Settings`` instance rather
    than assuming there is one (see ``_live_settings_instances``). Restores each
    instance's own previous values on teardown and rebuilds the global engine so
    the SQLite suites are unaffected.
    """

    global _SCHEMA_READY

    import jobtracker.database.connection as conn

    admin = create_async_engine(ADMIN_URL, connect_args={"statement_cache_size": 0})
    if not _SCHEMA_READY:
        await _admin_build(admin)
        _SCHEMA_READY = True

    # Clean the tenant tables before each test for independence. ``sync_state``
    # belongs here for the same reason the other two do: with two tests now
    # writing cursor rows, leaving it dirty makes the second one inherit the
    # first one's A/B rows — which is order-dependence that would either mask a
    # real failure or invent a fake one.
    async with admin.begin() as c:
        await c.execute(
            text("TRUNCATE applications, user_credentials, sync_state RESTART IDENTITY CASCADE")
        )

    instances = _live_settings_instances()
    # Per-instance originals: an incomplete restore would silently leave later
    # SQLite-suite tests pointed at Postgres, where they would mostly still pass.
    originals = [(s, s.database_url_override, s.secret_encryption_key) for s in instances]
    orig_engine = conn._engine

    for s in instances:
        s.database_url_override = _app_url()
        s.secret_encryption_key = _FERNET_KEY
    conn._engine = None  # force a rebuild against the app-role URL (attaches RLS listener)

    try:
        # Fail loudly rather than testing the wrong database. Without this the
        # suite's failure mode was "wrong backend", which is indistinguishable
        # from "RLS not enforced" in a red/green summary.
        backend = conn.get_engine().url.get_backend_name()
        assert backend == "postgresql", (
            f"RLS suite bound to {backend!r}, not postgresql — the settings "
            "singleton was orphaned by an importlib.reload in an earlier test."
        )
        yield admin
    finally:
        await conn.close_db()
        for s, url, key in originals:
            s.database_url_override = url
            s.secret_encryption_key = key
        conn._engine = orig_engine
        await admin.dispose()


# =============================================================================
# The role + FORCE facts the enforcement rests on.
# =============================================================================


async def test_app_role_is_non_bypass_and_user_credentials_forced(
    pg_app: AsyncEngine,
) -> None:
    async with pg_app.connect() as c:
        bypass = (
            await c.execute(text(f"SELECT rolbypassrls FROM pg_roles WHERE rolname='{APP_ROLE}'"))
        ).scalar()
        forced = (
            await c.execute(
                text("SELECT relforcerowsecurity FROM pg_class WHERE relname='user_credentials'")
            )
        ).scalar()
    assert bypass is False, "app role must NOT have BYPASSRLS"
    assert forced is True, "user_credentials must be FORCE'd (c5 migration)"


# =============================================================================
# Guarantee 1: with the GUC set, insert + read only own rows.
# =============================================================================


async def test_with_guc_inserts_and_reads_only_own_rows(pg_app: AsyncEngine) -> None:
    from sqlmodel import select

    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import Application, ApplicationStatus

    with user_id_scope(USER_A):
        async with get_session() as s:
            s.add(
                Application(
                    user_id=USER_A, company="Acme", position="SWE", status=ApplicationStatus.APPLIED
                )
            )
            s.add(
                Application(
                    user_id=USER_A,
                    company="Initech",
                    position="Backend",
                    status=ApplicationStatus.APPLIED,
                )
            )
            await s.commit()

    with user_id_scope(USER_B):
        async with get_session() as s:
            s.add(
                Application(
                    user_id=USER_B,
                    company="Hooli",
                    position="Infra",
                    status=ApplicationStatus.APPLIED,
                )
            )
            await s.commit()

    with user_id_scope(USER_A):
        async with get_session() as s:
            rows = (await s.exec(select(Application))).all()
    assert {r.company for r in rows} == {"Acme", "Initech"}


# =============================================================================
# Guarantee 2: without the GUC, insert rejected + reads empty (fail-closed).
# =============================================================================


async def test_without_guc_insert_is_rejected(pg_app: AsyncEngine) -> None:
    from jobtracker.database import get_session
    from jobtracker.database.models import Application, ApplicationStatus

    # RLS's WITH CHECK rejects the write; asyncpg's InsufficientPrivilegeError
    # surfaces as a SQLAlchemy DBAPIError.
    with pytest.raises(DBAPIError):
        async with get_session() as s:  # no user_id_scope -> auth.uid() is NULL
            s.add(
                Application(
                    user_id=USER_A, company="Ghost", position="X", status=ApplicationStatus.APPLIED
                )
            )
            await s.commit()


async def test_without_guc_reads_return_nothing(pg_app: AsyncEngine) -> None:
    from sqlmodel import select

    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import Application, ApplicationStatus

    with user_id_scope(USER_A):
        async with get_session() as s:
            s.add(
                Application(
                    user_id=USER_A, company="Acme", position="SWE", status=ApplicationStatus.APPLIED
                )
            )
            await s.commit()

    async with get_session() as s:  # no scope -> auth.uid() NULL -> nothing visible
        rows = (await s.exec(select(Application))).all()
    assert rows == []


# =============================================================================
# Guarantee 3: the DB (not the app filter) isolates tenants — raw SQL.
# =============================================================================


async def test_non_bypass_role_cannot_see_other_users_rows(pg_app: AsyncEngine) -> None:
    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import Application, ApplicationStatus

    with user_id_scope(USER_A):
        async with get_session() as s:
            for company in ("Acme", "Initech"):
                s.add(
                    Application(
                        user_id=USER_A,
                        company=company,
                        position="SWE",
                        status=ApplicationStatus.APPLIED,
                    )
                )
            await s.commit()
    with user_id_scope(USER_B):
        async with get_session() as s:
            s.add(
                Application(
                    user_id=USER_B,
                    company="Hooli",
                    position="Infra",
                    status=ApplicationStatus.APPLIED,
                )
            )
            await s.commit()

    # Raw, UNFILTERED count under B: only RLS can bound this to B's single row.
    with user_id_scope(USER_B):
        async with get_session() as s:
            total = (await s.exec(text("SELECT count(*) FROM applications"))).scalar()
    assert total == 1


# =============================================================================
# Pooling safety: no GUC leak across users on a reused engine.
# =============================================================================


async def test_guc_does_not_leak_across_users_on_reused_engine(
    pg_app: AsyncEngine,
) -> None:
    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import Application, ApplicationStatus

    with user_id_scope(USER_A):
        async with get_session() as s:
            s.add(
                Application(
                    user_id=USER_A, company="Acme", position="SWE", status=ApplicationStatus.APPLIED
                )
            )
            await s.commit()

    # B on the same (reused) engine must see zero of A's rows.
    with user_id_scope(USER_B):
        async with get_session() as s:
            b_total = (await s.exec(text("SELECT count(*) FROM applications"))).scalar()
    assert b_total == 0

    # And re-entering A still sees exactly A's row (no stale/empty GUC).
    with user_id_scope(USER_A):
        async with get_session() as s:
            a_total = (await s.exec(text("SELECT count(*) FROM applications"))).scalar()
    assert a_total == 1


# =============================================================================
# Multi-transaction session: the GUC is re-applied on every transaction.
# =============================================================================


async def test_multi_transaction_session_reapplies_guc(pg_app: AsyncEngine) -> None:
    """A query issued AFTER a commit in the same session still enforces.

    Guards the ``create_application`` (commit → refresh) and ``gmail_sync``
    (upsert-commit → count) patterns: ``set_config(is_local=>true)`` is
    discarded at COMMIT, so the ``begin`` event must re-apply it on the next
    transaction or the post-commit query silently returns nothing.
    """

    from sqlmodel import select

    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import Application, ApplicationStatus

    with user_id_scope(USER_A):
        async with get_session() as s:
            s.add(
                Application(
                    user_id=USER_A, company="Acme", position="SWE", status=ApplicationStatus.APPLIED
                )
            )
            await s.commit()  # tx1 ends, GUC dropped
            # tx2 in the SAME session:
            rows = (await s.exec(select(Application))).all()
    assert len(rows) == 1


# =============================================================================
# The upsert + credential-save paths specifically.
# =============================================================================


async def test_upsert_applications_path_is_scoped(pg_app: AsyncEngine) -> None:
    from sqlmodel import select

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import upsert_applications_for_user
    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import Application

    rolled = [
        pipeline.RolledApplication(
            company_token="cedartech",
            company_display="Cedartech",
            role="Engineer",
            status="applied",
            applied_at=None,
            last_activity=None,
        )
    ]

    with user_id_scope(USER_B):
        async with get_session() as s:
            created, updated = await upsert_applications_for_user(s, USER_B, rolled)
        assert (created, updated) == (1, 0)
        async with get_session() as s:
            rows = (await s.exec(select(Application))).all()
    assert {r.company for r in rows} == {"Cedartech"}


async def test_aware_received_at_persists_as_naive_utc(pg_app: AsyncEngine) -> None:
    """Regression: an AWARE ``received_at`` must persist without a DataError.

    ``email.utils.parsedate_to_datetime`` returns a timezone-AWARE datetime, but
    the ``emails.received_at`` column is ``TIMESTAMP WITHOUT TIME ZONE``. asyncpg
    refuses to encode an aware datetime into a naive column
    (``can't subtract offset-naive and offset-aware datetimes`` → ``DataError``),
    which 500'd ``POST /gmail/sync`` in production. SQLite silently tolerates the
    mismatch, so only THIS real-Postgres path exercises the failing encoder.

    Drives the actual purge/rebuild persistence with an aware timestamp and
    asserts (a) it commits, and (b) every persisted ``received_at`` is tz-naive.
    """

    from datetime import timedelta, timezone

    from sqlmodel import select

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import (
        ScanCoverage,
        purge_and_rebuild_gmail_pipeline,
    )
    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import Application, Email

    # Mirrors the owner's real crashing value (2026-07-08 20:04:21 -04:00).
    aware = datetime(2026, 7, 8, 20, 4, 21, tzinfo=timezone(timedelta(hours=-4)))
    items = [
        pipeline.PipelineItem(
            message_id="m-stripe",
            category="applied",
            sender_email="careers@stripe.com",
            subject="Thanks for applying to the Data Scientist role at Stripe",
            sender_name="Stripe",
            received_at=aware,
            confidence=0.95,
            thread_id="th-stripe",
        ),
        pipeline.PipelineItem(
            message_id="m-review",
            category="interview",
            sender_email="talent@replit.com",
            subject="About your background",
            sender_name="Replit",
            received_at=aware,
            confidence=0.78,
        ),
    ]
    rolled = pipeline.roll_up_applications(items)
    review = pipeline.collect_review_items(items)

    with user_id_scope(USER_B):
        async with get_session() as s:
            # Before the fix this commit raised asyncpg DataError → HTTP 500.
            merged = await purge_and_rebuild_gmail_pipeline(
                s, USER_B, rolled, review, ScanCoverage.from_items(items)
            )
        assert (merged.created, merged.needs_review) == (1, 1)
        assert merged.purged == 0 and merged.removed == ()

        async with get_session() as s:
            apps = (await s.exec(select(Application))).all()
            emails = (await s.exec(select(Email))).all()

    assert {a.company for a in apps} == {"Stripe"}
    stripe = next(a for a in apps if a.company == "Stripe")
    # -04:00 20:04 → 00:04 UTC the NEXT day: applied_date is the UTC date.
    assert stripe.applied_date == datetime(2026, 7, 9).date()

    assert emails, "the underlying mail must persist for click-through + review"
    for e in emails:
        assert e.received_at is not None
        assert e.received_at.tzinfo is None, "received_at must be naive UTC"


async def test_sync_state_writes_are_rls_scoped_and_fail_closed(
    pg_app: AsyncEngine,
) -> None:
    """``sync_state`` gets the same RLS proof the other tables have.

    ``sync_state`` was in ``_ENTITY_TABLES`` — so the policies were CREATED for
    it — but no test body ever wrote to it, so the ``WITH CHECK`` path was
    unexercised. That is where every sync now records its cursor
    (``jobtracker/cloud/sync_state.py``), which makes it the newest untested
    write surface in the cloud app: one row per user per mailbox, holding the
    linked address and the Gmail ``historyId``.

    Drives the real production writer rather than a raw INSERT, and asserts the
    three things RLS is there for: the write lands under the owner's GUC, a
    second user cannot see it, and a write with no GUC at all is REJECTED
    rather than silently stored.
    """

    from sqlmodel import select

    from jobtracker.cloud.sync_state import record_gmail_sync_success
    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import SyncState

    with user_id_scope(USER_A):
        async with get_session() as s:
            await record_gmail_sync_success(
                s, USER_A, account_email="a@example.test", history_id="9001"
            )
            await s.commit()

    with user_id_scope(USER_B):
        async with get_session() as s:
            await record_gmail_sync_success(
                s, USER_B, account_email="b@example.test", history_id="7001"
            )
            await s.commit()

    # Each owner sees exactly their own cursor row — never the other's mailbox
    # address, which is the sensitive part of this table.
    with user_id_scope(USER_A):
        async with get_session() as s:
            rows_a = (await s.exec(select(SyncState))).all()
    assert {r.account_email for r in rows_a} == {"a@example.test"}
    assert {r.gmail_history_id for r in rows_a} == {"9001"}

    with user_id_scope(USER_B):
        async with get_session() as s:
            rows_b = (await s.exec(select(SyncState))).all()
    assert {r.account_email for r in rows_b} == {"b@example.test"}

    # Fail-closed: no GUC → auth.uid() is NULL → WITH CHECK rejects the insert.
    with pytest.raises(DBAPIError):
        async with get_session() as s:
            await record_gmail_sync_success(
                s, USER_A, account_email="ghost@example.test", history_id="1"
            )
            await s.commit()

    # And a row cannot be written on another user's behalf even WITH a GUC:
    # the WITH CHECK compares the column to auth.uid(), not to the caller's
    # claim about who they are writing for.
    with pytest.raises(DBAPIError), user_id_scope(USER_B):
        async with get_session() as s:
            s.add(
                SyncState(
                    user_id=USER_A,  # not the GUC's user
                    account_type="gmail",
                    account_email="forged@example.test",
                )
            )
            await s.commit()

    with user_id_scope(USER_A):
        async with get_session() as s:
            after = (await s.exec(select(SyncState))).all()
    assert {r.account_email for r in after} == {"a@example.test"}


async def test_sync_state_cross_tenant_overwrite_is_refused(
    pg_app: AsyncEngine,
) -> None:
    """B can neither read nor **overwrite** A's Gmail sync cursor.

    The sibling test above exercises SELECT (``USING``) and INSERT
    (``WITH CHECK``). Neither touches ``sync_state_update`` — and an overwrite
    is the realistic attack on this table, because unlike ``applications`` the
    row already exists. The damage is not a forged cursor appearing, it is
    somebody else's cursor being *moved*: an advanced ``gmail_history_id`` makes
    their next incremental sync skip everything before it, so the loss is
    silent mail rather than a visible bad row (see the "Cursor safety" note in
    ``jobtracker/cloud/sync_state.py``).

    The UPDATE policy's two halves fail by DIFFERENT mechanisms, and each is
    asserted here against the one it actually uses:

    * ``USING`` decides which rows an UPDATE may even see, so B's *unqualified*
      UPDATE matches zero of A's rows and **does not raise** — it quietly
      touches only B's own. Wrapping this in ``pytest.raises`` would assert the
      wrong mechanism and would still pass with ``USING`` removed entirely.
    * ``WITH CHECK`` validates the row as it will be AFTER the update, so
      re-assigning ``user_id`` to another tenant **raises**. That is the half
      that stops a row being handed away, and the half issue #74 names.
    """

    from sqlmodel import select

    from jobtracker.cloud.sync_state import record_gmail_sync_success
    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.models import SyncState

    with user_id_scope(USER_A):
        async with get_session() as s:
            await record_gmail_sync_success(
                s, USER_A, account_email="a@example.test", history_id="9001"
            )
            await s.commit()

    with user_id_scope(USER_B):
        async with get_session() as s:
            await record_gmail_sync_success(
                s, USER_B, account_email="b@example.test", history_id="7001"
            )
            await s.commit()

    # --- read half: B cannot see the row at all ---------------------------
    with user_id_scope(USER_B):
        async with get_session() as s:
            # Raw and UNFILTERED: only RLS can bound this to B's own row.
            visible = (
                await s.exec(
                    text("SELECT count(*) FROM sync_state WHERE gmail_history_id = '9001'")
                )
            ).scalar()
    assert visible == 0, "B can see A's cursor row"

    # --- overwrite half, USING: B's blind UPDATE cannot reach A's row -----
    # Deliberately NOT in pytest.raises. RLS answers a cross-tenant UPDATE by
    # making the row invisible, so the statement succeeds and affects nothing.
    with user_id_scope(USER_B):
        async with get_session() as s:
            res = await s.exec(text("UPDATE sync_state SET gmail_history_id = 'hijacked'"))
            assert res.rowcount == 1, (
                f"B's unqualified UPDATE touched {res.rowcount} rows; with two "
                "cursor rows in the table it must reach exactly B's own"
            )
            await s.commit()

    with user_id_scope(USER_A):
        async with get_session() as s:
            rows_a = (await s.exec(select(SyncState))).all()
    assert [r.gmail_history_id for r in rows_a] == ["9001"], "A's cursor was overwritten by B"

    # --- overwrite half, WITH CHECK: A cannot hand its row to B -----------
    # USING passes here (the row IS A's), so this is WITH CHECK and nothing
    # else: Postgres validates the post-update row and refuses it.
    #
    # Unqualified on purpose, and that is the whole point of this first form.
    # An UPDATE that *reads* the relation needs SELECT rights too, and the
    # SELECT policy is then applied to the existing **and the new** row
    # (PostgreSQL 16, CREATE POLICY, "Policies Applied by Command Type",
    # note a). So any statement carrying a WHERE clause is refused by
    # `sync_state_select` even with `sync_state_update`'s WITH CHECK gone —
    # measured, see the table below. Without a WHERE there is no second
    # defence, so this line and only this line is a red/green probe on the
    # WITH CHECK expression the issue names.
    with (
        pytest.raises(DBAPIError, match="new row violates row-level security policy"),
        user_id_scope(USER_A),
    ):
        async with get_session() as s:
            await s.exec(text(f"UPDATE sync_state SET user_id = '{USER_B}'::uuid"))
            await s.commit()

    # The same refusal in the shape production actually emits — an ORM flush,
    # which always carries `WHERE id = ...`. Kept as well as the probe above,
    # not instead of it: this is the statement the app runs, and the one above
    # is the one that can be made to fail.
    #
    # ``match=`` is load-bearing, not decoration. A bare
    # ``pytest.raises(DBAPIError)`` here passed even with this policy's
    # WITH CHECK weakened to ``true``, because ``IntegrityError`` is also a
    # ``DBAPIError``: moving A's row to B collides with the composite
    # ``uq_sync_state_user_account`` as soon as B holds the same address. The
    # test was green off the uniqueness constraint, not off RLS. Pinning the
    # message is what makes this assert the mechanism it claims to.
    #
    # It also has to happen BEFORE B is given a row for A's address below, so
    # the constraint is not even in a position to fire first.
    #
    # Two policies refuse this write independently, which is worth knowing
    # before anyone tries to prove this line can fail. Measured on postgres:16,
    # for `UPDATE ... SET user_id = <B> WHERE id = 1` run as A:
    #
    #   update WITH CHECK | select USING | result
    #   ------------------+--------------+--------
    #   intact            | intact       | refused
    #   true              | intact       | refused   <- SELECT policy catches it
    #   intact            | true         | refused
    #   true              | true         | ALLOWED
    #
    # That second column is not folklore: an UPDATE needing read access to the
    # existing or new row applies the SELECT policy in addition to the UPDATE
    # policies, so a row cannot be updated into a state its updater can no
    # longer see. (Drop the WHERE clause and that defence goes away: the same
    # statement unqualified is allowed once WITH CHECK is weakened, which is
    # exactly why the probe above is unqualified.) Weakening either policy
    # alone therefore leaves THIS line green — a real property of the schema,
    # not a hole in the test.
    with (
        pytest.raises(DBAPIError, match="new row violates row-level security policy"),
        user_id_scope(USER_A),
    ):
        async with get_session() as s:
            row = (await s.exec(select(SyncState))).one()
            row.user_id = USER_B
            s.add(row)
            await s.commit()

    # The same refusal through the PRODUCTION writer: B syncing the address A
    # has linked gets B's own row (the uniqueness constraint is composite), it
    # does not upsert onto A's — ``_upsert``'s scoped load cannot see A's row.
    with user_id_scope(USER_B):
        async with get_session() as s:
            await record_gmail_sync_success(
                s, USER_B, account_email="a@example.test", history_id="666"
            )
            await s.commit()
        async with get_session() as s:
            rows_b = (await s.exec(select(SyncState))).all()
    assert len(rows_b) == 2, "B should now own two cursor rows of its own"

    # Nothing moved: A still owns exactly its own untouched cursor.
    with user_id_scope(USER_A):
        async with get_session() as s:
            after = (await s.exec(select(SyncState))).all()
    assert [(r.account_email, r.gmail_history_id) for r in after] == [("a@example.test", "9001")]


async def test_credential_save_read_is_scoped_and_cross_user_blocked(
    pg_app: AsyncEngine,
) -> None:
    from jobtracker.credentials.cloud import (
        get_gmail_credentials,
        save_gmail_credentials,
    )
    from jobtracker.credentials.types import GmailCredentials
    from jobtracker.database import get_session, user_id_scope

    creds = GmailCredentials(
        access_token="at",
        refresh_token="rt",
        token_expiry=datetime(2027, 1, 1),
        email="a@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )

    with user_id_scope(USER_A):
        assert await save_gmail_credentials(USER_A, creds) is True
        got = await get_gmail_credentials(USER_A)
        assert got is not None and got.email == "a@example.com"

    with user_id_scope(USER_B):
        # B cannot read A's credential row (FORCE'd RLS).
        assert await get_gmail_credentials(USER_B) is None
        async with get_session() as s:
            cnt = (await s.exec(text("SELECT count(*) FROM user_credentials"))).scalar()
        assert cnt == 0

    # A save with NO GUC bound is blocked by RLS; the helper swallows the DB
    # error and reports failure (False) rather than silently writing.
    assert await save_gmail_credentials(USER_A, creds) is False


# =============================================================================
# The scheduled sync: a configured identity, not an exemption (issue #23 / C7).
#
# HISTORY, because the shape of these two tests only makes sense with it. The
# first implementation enumerated ``user_credentials`` directly and found
# NOBODY on Postgres: that table is FORCE-RLS on ``auth.uid()`` against a
# NOBYPASSRLS role, and a cron carries no JWT, so the policy matched no row.
# The test that lived here asserted that defect on purpose, and said that when
# the gap was closed it should be INVERTED rather than deleted. This is that
# inversion — restructured rather than merely negated, because the fix changed
# how enumeration works, not just its result.
#
# The cron now takes its users from ``settings.cron_sync_user_ids`` and runs
# each one's work inside ``user_id_scope(uid)``. No policy changed, no DDL ran,
# and no new database credential exists.
# =============================================================================


def _gmail_creds(email: str):
    from jobtracker.credentials.types import GmailCredentials

    return GmailCredentials(
        access_token="at",
        refresh_token="rt",
        token_expiry=datetime(2027, 1, 1),
        email=email,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


def _set_allowlist(monkeypatch: pytest.MonkeyPatch, *user_ids: uuid.UUID) -> None:
    """Point the cron's allowlist at ``user_ids`` on the instance it reads.

    ``monkeypatch.setattr(cron_module.settings, ...)`` and NOT
    ``monkeypatch.setenv`` + reload: four sibling modules reload
    ``jobtracker.config`` and orphan the ``settings`` object other modules
    hold, which is the trap ``_live_settings_instances`` above exists to
    document. Reaching through ``cron_module.settings`` cannot pick the wrong
    one. The env-var parse itself is covered in ``tests/test_cron_sync.py``.
    """

    import jobtracker.cloud.cron as cron_module

    monkeypatch.setattr(cron_module.settings, "cron_sync_user_ids", list(user_ids))


async def test_cron_enumeration_uses_the_configured_allowlist(
    pg_app: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enumeration now returns users — because it binds an identity per user.

    This is the inversion of ``test_cron_enumeration_sees_no_users_without_
    identity``. It is called with **no identity bound at all**, exactly as the
    cron runs, and it must return the configured users anyway.

    THE CONTROL IS THE FIRST ASSERTION, and it is what makes the rest mean
    something. An unscoped raw ``SELECT count(*) FROM user_credentials`` on the
    very same engine returns **0**, because RLS is genuinely enforcing. If that
    line ever returns 2, this module is not testing RLS at all (wrong backend,
    or a BYPASSRLS role) and every assertion below would pass for free. So:
    same connection machinery, same absence of an ambient identity, one read
    returns nothing and the other returns both users. The only difference is
    the per-user ``user_id_scope`` inside the enumeration.
    """

    from jobtracker.cloud.cron import list_syncable_user_ids
    from jobtracker.credentials.cloud import save_gmail_credentials
    from jobtracker.database import get_session, user_id_scope

    with user_id_scope(USER_A):
        assert await save_gmail_credentials(USER_A, _gmail_creds("a@example.com")) is True
    with user_id_scope(USER_B):
        assert await save_gmail_credentials(USER_B, _gmail_creds("b@example.com")) is True

    # CONTROL: RLS really is denying the identity-less read this used to rely on.
    async with get_session() as s:
        blind = (await s.exec(text("SELECT count(*) FROM user_credentials"))).scalar()
    assert blind == 0, (
        f"An unscoped read of user_credentials returned {blind} rows. RLS is "
        "NOT being enforced on this run, so nothing below is a real test."
    )

    # …and yet the enumeration, called with no identity bound, finds both.
    _set_allowlist(monkeypatch, USER_A, USER_B)
    candidates = await list_syncable_user_ids(100)
    assert candidates == [USER_A, USER_B], (
        f"The configured enumeration returned {candidates}. Each configured id "
        "must be probed inside its own user_id_scope; without the binding RLS "
        "returns nothing and the cron is back to syncing nobody."
    )

    # The allowlist is the ONLY thing that selects users: B still has a
    # credential row, and still must not be enumerated.
    _set_allowlist(monkeypatch, USER_A)
    assert await list_syncable_user_ids(100) == [USER_A]

    # Empty is FAIL-CLOSED — nobody, not everybody.
    _set_allowlist(monkeypatch)
    assert await list_syncable_user_ids(100) == []

    # A configured id with no Gmail credential is skipped rather than handed to
    # gmail_sync to fail on every run forever. USER_A is kept alongside so a
    # blanket "returns nothing" cannot pass this.
    stranger = uuid.uuid4()
    _set_allowlist(monkeypatch, USER_A, stranger)
    assert await list_syncable_user_ids(100) == [USER_A]


async def test_cron_syncs_only_the_allowlisted_user_and_leaks_no_identity(
    pg_app: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The isolation property, end to end, through the real handler.

    Two users exist with identical shapes. Only USER_A is allowlisted. Three
    things must hold afterwards, and each targets a different way the identity
    binding can be got wrong:

    1. **The sync could only SEE USER_A's data.** The stand-in for
       ``gmail_sync`` issues an UNFILTERED ``select(Application)`` — no
       ``WHERE user_id``, deliberately — so the only thing that can bound the
       result is the bound identity plus RLS. Breaks if the wrong id is bound.
    2. **USER_B's rows are byte-identical.** Snapshotted through the ADMIN
       engine (a superuser, which bypasses RLS) as ``to_jsonb`` of every row of
       every table this run could touch, before and after. Breaks if one
       tenant's identity is live while another tenant's work runs.
    3. **The identity did not survive the run.** A post-run *unscoped*
       ``get_session()`` read must return nothing. Breaks if the binding is
       applied without a reset — a session-level ``SET`` instead of
       ``set_config(..., is_local => true)``, or a bare
       ``set_current_user_id`` with no ``user_id_scope`` around it. That is
       the one that matters under PgBouncer transaction pooling, where the
       physical connection goes to the next tenant.

    WHY THE PROBE TABLE IS ``user_credentials`` AND NOT ``applications``: both
    users have a credential row, so an unscoped ``count(*)`` of 0 means RLS is
    denying rather than that the table happens to be empty. The test asserts
    that premise directly against the admin engine — a leak probe whose own
    subject is empty is a check that cannot fail, which is the defect shape
    this repo keeps finding.

    WHAT THE FAKE SYNC WRITES, AND WHY IT WRITES IT THAT WAY: it inserts a row
    attributed to ``get_current_user_id()`` — the *bound* identity — rather
    than to the ``user_id`` argument. That is what any write trusting
    ``auth.uid()`` does, and it is the only shape under which mis-binding
    shows up as corruption rather than as an error: a row explicitly carrying
    USER_A's id would simply be refused by USER_B's ``WITH CHECK``, which is a
    red test for the wrong reason. Reshaping the instrument to make the
    hazard observable is calibration; the assertions are untouched.
    """

    from sqlmodel import select
    from starlette.requests import Request

    import jobtracker.cloud.cron as cron_module
    import jobtracker.cloud.gmail_oauth as gmail_module
    from jobtracker.cloud.sync_state import record_gmail_sync_success
    from jobtracker.credentials.cloud import save_gmail_credentials
    from jobtracker.database import get_session, user_id_scope
    from jobtracker.database.connection import get_current_user_id
    from jobtracker.database.models import Application, ApplicationStatus

    # GENERATED, not written out. A literal here is what the repo's gitleaks
    # gate flags (generic-api-key, entropy 3.61) even though it is a throwaway
    # that lives for one test — and a test file is not the place to teach the
    # secret scanner exceptions. ``test_cron_sync.py`` hit the identical wall
    # and records the same reasoning. The value is irrelevant to what this test
    # proves; it only has to satisfy ``_authorize`` so the run reaches the
    # isolation assertions.
    cron_secret = f"cron-probe-{uuid.uuid4()}"

    # ---- seed two identically-shaped tenants -----------------------------
    for user_id, company in ((USER_A, "Acme"), (USER_B, "Hooli")):
        with user_id_scope(user_id):
            assert (
                await save_gmail_credentials(
                    user_id, _gmail_creds(f"{company.lower()}@example.com")
                )
                is True
            )
            async with get_session() as s:
                s.add(
                    Application(
                        user_id=user_id,
                        company=company,
                        position="SWE",
                        status=ApplicationStatus.APPLIED,
                    )
                )
                await s.commit()
            async with get_session() as s:
                await record_gmail_sync_success(
                    s,
                    user_id,
                    account_email=f"{company.lower()}@example.com",
                    history_id="1000",
                )
                await s.commit()

    async def _snapshot_b() -> dict[str, list]:
        """Every one of B's rows, read as a superuser so RLS cannot hide a change."""

        snapshot: dict[str, list] = {}
        async with pg_app.connect() as c:
            for table in ("applications", "user_credentials", "sync_state"):
                rows = (
                    await c.execute(
                        # ORDER BY the jsonb itself, not by ``id``:
                        # ``user_credentials`` is keyed on (user_id, kind) and
                        # has no ``id`` column at all. jsonb has a total order
                        # in Postgres, so this is deterministic on every table.
                        text(
                            f"SELECT to_jsonb(t.*) FROM {table} t "
                            "WHERE user_id = :uid ORDER BY 1"
                        ),
                        {"uid": str(USER_B)},
                    )
                ).all()
                snapshot[table] = [r[0] for r in rows]
        return snapshot

    before = await _snapshot_b()
    assert all(before[t] for t in before), (
        f"USER_B was not seeded on every table ({ {k: len(v) for k, v in before.items()} }); "
        "an unchanged-rows assertion over empty tables proves nothing."
    )

    # ---- the fake sync: reads unfiltered, writes as whoever is bound ------
    seen_by_sync: list[tuple[uuid.UUID | None, list[str]]] = []

    async def fake_sync(payload, user_id=None, **_):  # noqa: ANN001, ANN202
        bound = get_current_user_id()
        async with get_session() as s:
            # UNFILTERED on purpose: only auth.uid() + RLS can bound this.
            visible = (await s.exec(select(Application))).all()
            seen_by_sync.append((bound, sorted(a.company for a in visible)))
            s.add(
                Application(
                    user_id=bound,
                    company="CronMarker",
                    position="scheduled",
                    status=ApplicationStatus.APPLIED,
                )
            )
            await s.commit()

    monkeypatch.setattr(gmail_module, "gmail_sync", fake_sync)
    monkeypatch.setattr(cron_module.settings, "vercel_cron_secret", cron_secret)
    _set_allowlist(monkeypatch, USER_A)

    # ---- run the real handler, gate included -----------------------------
    # Called directly rather than through an ASGI client, deliberately: the
    # leak probe below must observe the handler's OWN context, and a transport
    # that copies the context would hide a ContextVar that was never reset.
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/cron/sync",
            "headers": [(b"x-vercel-cron-secret", cron_secret.encode())],
            "query_string": b"",
        }
    )
    response = await cron_module.cron_sync(request)

    assert response.errors == [], f"the scheduled run reported errors: {response.errors}"
    assert (response.candidates, response.users_synced) == (1, 1)

    # 1. The sync saw exactly USER_A's board — never USER_B's row.
    assert seen_by_sync == [(USER_A, ["Acme"])], (
        f"The sync ran as {seen_by_sync}. It must run bound to USER_A and see "
        "only USER_A's applications; 'Hooli' appearing here is a cross-tenant "
        "read, and a bound identity of USER_B is the identity-bleed defect."
    )

    # 2. USER_B's rows are byte-identical.
    after = await _snapshot_b()
    assert after == before, (
        "USER_B's rows changed during a run that was only ever allowed to act "
        "for USER_A. This is identity bleed: the binding is reaching work it "
        "does not belong to."
    )

    # …and the marker really did land, on USER_A, so 'nothing changed' above
    # is not just 'nothing happened'.
    with user_id_scope(USER_A):
        async with get_session() as s:
            a_companies = sorted(
                a.company for a in (await s.exec(select(Application))).all()
            )
    assert a_companies == ["Acme", "CronMarker"], (
        f"USER_A's board is {a_companies}; the run wrote nothing, so the "
        "unchanged-USER_B assertion above is vacuous."
    )

    # 3. THE LEAK PROBE. No identity may survive the run — not in the
    #    ContextVar, and not on the pooled connection.
    assert get_current_user_id() is None, (
        "The RLS identity is still bound after the run. Under PgBouncer "
        "transaction pooling this is how the next tenant inherits it."
    )
    async with get_session() as s:
        leaked = (await s.exec(text("SELECT * FROM user_credentials"))).all()
    assert leaked == [], (
        f"An unscoped read after the run returned {len(leaked)} credential "
        "row(s). The cron's identity outlived its transaction."
    )

    # NON-VACUITY of the probe: the table it reads is not empty. Without this,
    # `[] == []` would hold just as well on a table with no rows in it.
    async with pg_app.connect() as c:
        real_rows = (
            await c.execute(text("SELECT count(*) FROM user_credentials"))
        ).scalar()
    assert real_rows == 2, (
        f"The leak probe read a table holding {real_rows} rows. It must hold "
        "both users' credentials, or an empty result proves nothing."
    )


# =============================================================================
# Guarantee 6: the sync lease works under FORCE RLS as the non-bypass role.
#
# THIS IS THE ONE THAT CANNOT BE TESTED ON SQLITE, and the failure it guards
# against is total rather than partial. ``acquire_gmail_sync_lease`` decides
# whether a sync may proceed from the ROW COUNT of a conditional UPDATE. If a
# policy silently filtered that UPDATE to zero rows, the helper would read
# "nobody updated" as "somebody else holds the lease" and answer 409 to every
# sync, for every user, forever — including the "Sync now" button. Every
# assertion in tests/test_sync_lease.py would stay green, because SQLite has no
# RLS at all.
#
# That is precisely the shape cron.py's own docstring records: an unscoped
# SELECT that matched no row on Postgres while every unit test passed on
# SQLite. A rowcount-driven decision under RLS has to be exercised against
# real policies and a real NOBYPASSRLS role, which is what this fixture gives.
# =============================================================================


async def test_the_sync_lease_is_taken_and_released_under_rls(
    pg_app: AsyncEngine,
) -> None:
    """Acquire → refuse → release → re-acquire, as the app role."""

    from jobtracker.cloud.sync_state import (
        acquire_gmail_sync_lease,
        release_gmail_sync_lease,
    )
    from jobtracker.database import user_id_scope

    mailbox = "owner-a@example.com"

    with user_id_scope(USER_A):
        # A first sync has no sync_state row: the INSERT path, under a policy
        # whose WITH CHECK must accept the row the helper builds.
        assert await acquire_gmail_sync_lease(USER_A, mailbox) is True, (
            "the lease could not be taken at all under RLS — every sync would "
            "409 forever, including the user's own Sync now button"
        )

        # The conditional UPDATE must see the row it just wrote. If the UPDATE
        # were filtered to zero rows this would ALSO return False, so the
        # release/re-acquire below is what tells the two apart.
        assert await acquire_gmail_sync_lease(USER_A, mailbox) is False

        await release_gmail_sync_lease(USER_A, mailbox)

        # THE DISCRIMINATING ASSERTION. Releasing is an UPDATE and re-acquiring
        # is an UPDATE; if either were silently filtering to zero rows, this
        # could not come back True.
        assert await acquire_gmail_sync_lease(USER_A, mailbox) is True, (
            "the lease was never actually released/re-taken — the UPDATE is "
            "being filtered to zero rows by a policy"
        )


async def test_one_users_lease_does_not_block_another_under_rls(
    pg_app: AsyncEngine,
) -> None:
    """Cross-tenant: A holding a lease must not stop B taking theirs.

    A policy mistake in the other direction — an UPDATE that reached rows it
    should not — would show up here as B being refused because A's row matched.
    """

    from jobtracker.cloud.sync_state import acquire_gmail_sync_lease
    from jobtracker.database import user_id_scope

    with user_id_scope(USER_A):
        assert await acquire_gmail_sync_lease(USER_A, "a@example.com") is True

    with user_id_scope(USER_B):
        assert await acquire_gmail_sync_lease(USER_B, "b@example.com") is True


async def test_sync_state_has_an_update_policy(pg_app: AsyncEngine) -> None:
    """Read the policy catalogue directly, rather than inferring it.

    The behavioural tests above are the real gate; this one names the mechanism
    so a failure says "the UPDATE policy is missing" instead of leaving someone
    to work that out from a 409.
    """

    async with pg_app.begin() as c:
        rows = (
            await c.execute(
                text(
                    "SELECT cmd FROM pg_policies "
                    "WHERE tablename = 'sync_state' AND cmd IN ('ALL', 'UPDATE')"
                )
            )
        ).all()

    assert rows, (
        "sync_state has no UPDATE (or ALL) policy, so the lease's conditional "
        "UPDATE can only ever affect zero rows under FORCE RLS"
    )
