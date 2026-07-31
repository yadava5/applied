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

ADMIN_URL = os.environ.get("JOBTRACKER_TEST_PG_ADMIN_URL")

pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason=(
        "Set JOBTRACKER_TEST_PG_ADMIN_URL to a superuser postgresql+asyncpg URL "
        "to run the real-Postgres RLS enforcement tests."
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
        # (c4user_creds_rls) + FORCE (c5_force_user_creds_rls).
        for t in _ENTITY_TABLES:
            await c.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
            await c.execute(text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
            await c.execute(
                text(f"CREATE POLICY {t}_select ON {t} FOR SELECT USING (user_id = auth.uid())")
            )
            await c.execute(
                text(
                    f"CREATE POLICY {t}_insert ON {t} FOR INSERT WITH CHECK (user_id = auth.uid())"
                )
            )
            await c.execute(
                text(
                    f"CREATE POLICY {t}_update ON {t} FOR UPDATE "
                    "USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid())"
                )
            )
            await c.execute(
                text(f"CREATE POLICY {t}_delete ON {t} FOR DELETE USING (user_id = auth.uid())")
            )
        await c.execute(text("ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY"))
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_select ON user_credentials "
                "FOR SELECT USING (user_id = auth.uid())"
            )
        )
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_insert ON user_credentials "
                "FOR INSERT WITH CHECK (user_id = auth.uid())"
            )
        )
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_update ON user_credentials "
                "FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid())"
            )
        )
        await c.execute(
            text(
                "CREATE POLICY user_credentials_owner_delete ON user_credentials "
                "FOR DELETE USING (user_id = auth.uid())"
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

    # Clean the tenant tables before each test for independence.
    async with admin.begin() as c:
        await c.execute(text("TRUNCATE applications, user_credentials RESTART IDENTITY CASCADE"))

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
    from jobtracker.cloud.applications import purge_and_rebuild_gmail_pipeline
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
            created, updated, purged, needs_review = await purge_and_rebuild_gmail_pipeline(
                s, USER_B, rolled, review
            )
        assert (created, needs_review) == (1, 1)

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
