"""
Database Connection Module
==========================

Async SQLite database connection using aiosqlite and SQLModel.

Provides:
- Async engine with WAL mode for concurrent access
- Session factory for database operations
- Context manager for automatic session cleanup
- Database initialization function

WAL Mode:
---------
Write-Ahead Logging (WAL) allows concurrent reads while writing.
This is essential for the two-process architecture where:
- Python backend writes to the database
- SwiftUI frontend reads via GRDB.swift

Usage:
------
    from jobtracker.database.connection import get_session, init_db

    # Initialize database (creates tables)
    await init_db()

    # Use session context manager
    async with get_session() as session:
        result = await session.exec(select(Application))
        applications = result.all()

    # Or get session manually
    async for session in get_session():
        # do work
        await session.commit()
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import SQLModel, text
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.config import settings

logger = logging.getLogger(__name__)

# Global engine instance (created on first use)
_engine: Optional[AsyncEngine] = None


# =============================================================================
# Row-Level Security: per-request user identity + per-transaction GUC wiring
# =============================================================================
#
# Postgres RLS policies key off ``auth.uid()``, which reads the ``sub`` claim
# out of the ``request.jwt.claims`` GUC. The FastAPI backend does not run
# inside Supabase's PostgREST, so nothing sets that GUC for us — we must set
# it ourselves, per request, from the verified JWT ``sub`` (or, for the Gmail
# OAuth callback, from the ``sub`` carried in the signed ``state``).
#
# The authenticated user for the current request/transaction is carried in a
# ``ContextVar`` so the *central* engine wiring below can read it without every
# call site having to thread a ``user_id`` through ``get_session()``. Two
# properties make this leak-proof under the shared Supabase PgBouncer
# (transaction pooling):
#
#   1. The GUCs are applied with ``set_config(..., is_local => true)`` inside a
#      ``begin`` event handler, so they are scoped to the *current transaction*
#      and are automatically discarded at COMMIT/ROLLBACK. A physical
#      connection handed to the next tenant by PgBouncer never carries a stale
#      ``request.jwt.claims`` or a poisoned ``search_path``.
#   2. The ContextVar is reset per request (see the cloud app middleware) and
#      is scoped explicitly via :func:`user_id_scope` on the OAuth-callback
#      write path, so one user's identity can never bleed into another's
#      transaction at the application layer either.
#
# ``search_path`` is pinned to ``public`` on every transaction as well: the
# shared pooler previously suffered a co-tenant ``search_path`` poisoning
# incident, and pinning it here (transaction-locally) makes every query
# resolve against the intended schema regardless of what a prior tenant left
# on the physical connection.
_current_user_id: ContextVar[uuid.UUID | None] = ContextVar(
    "jobtracker_current_user_id", default=None
)


def set_current_user_id(user_id: uuid.UUID | None) -> Token:
    """Bind ``user_id`` as the RLS identity for the current context.

    Returns the :class:`contextvars.Token` so callers that own the request
    lifecycle can reset it. The cloud auth dependency
    (``jobtracker.auth.current_user``) calls this after verifying the JWT.
    """

    return _current_user_id.set(user_id)


def reset_current_user_id(token: Token) -> None:
    """Reset the RLS identity ContextVar using a token from ``set_current_user_id``."""

    _current_user_id.reset(token)


def get_current_user_id() -> uuid.UUID | None:
    """Return the RLS identity bound to the current context, or ``None``."""

    return _current_user_id.get()


@contextmanager
def user_id_scope(user_id: uuid.UUID | None) -> Iterator[None]:
    """Scope the RLS identity to a block, resetting it on exit.

    Used by code paths that do not resolve the user through the normal
    ``Depends(current_user)`` dependency — most importantly the Gmail OAuth
    **callback**, which derives the user from the signed ``state`` and writes
    ``user_credentials`` (a FORCE-RLS table) without an auth dependency::

        with user_id_scope(user_id):
            await save_gmail_credentials(user_id, creds)
    """

    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)


def _install_rls_guc_listener(engine: AsyncEngine) -> None:
    """Attach a per-transaction GUC setter to a Postgres engine.

    On every transaction ``begin`` we pin ``search_path`` and, when an
    authenticated user is bound to the context, set ``request.jwt.claims`` so
    Supabase's ``auth.uid()`` resolves to that user inside the transaction.
    Both are set transaction-locally (``is_local => true``) so nothing leaks
    across the PgBouncer transaction pool.

    Scoped to the given engine instance (not the global ``Session`` class) so
    that reloading this module in tests — which builds a fresh engine — never
    stacks duplicate listeners.
    """

    @event.listens_for(engine.sync_engine, "begin")
    def _set_transaction_gucs(conn: Any) -> None:  # pragma: no cover - see PG tests
        # Always pin the schema search path for this transaction.
        conn.exec_driver_sql("SELECT set_config('search_path', 'public', true)")

        user_id = _current_user_id.get()
        if user_id is None:
            # Unauthenticated/health paths: leave request.jwt.claims unset so
            # auth.uid() returns NULL and RLS fails closed (denies) rather than
            # exposing rows. No user-scoped query should run without identity.
            return

        # ``user_id`` is always a uuid.UUID coming from a verified JWT / signed
        # state, so its string form is strictly ``[0-9a-fA-F-]`` — safe to embed
        # in the JSON literal. Guard defensively anyway.
        if not isinstance(user_id, uuid.UUID):
            return
        claims = json.dumps({"sub": str(user_id)}, separators=(",", ":"))
        conn.exec_driver_sql(
            f"SELECT set_config('request.jwt.claims', '{claims}', true)"
        )


def _is_sqlite_url(url: str) -> bool:
    """Return True if ``url`` targets a SQLite backend (sync or async)."""

    return url.startswith("sqlite")


def get_engine() -> AsyncEngine:
    """
    Get or create the async database engine.

    The engine is created once and reused for all connections.

    SQLite builds use ``StaticPool`` for in-memory DBs so state persists
    across sessions, and default pool behaviour for on-disk DBs.

    Postgres builds (Supabase) use ``NullPool`` plus asyncpg kwargs that
    disable prepared-statement caching. This is required when the app
    connects through the Supabase PgBouncer (transaction pooling), which
    does not support the PREPARE/EXECUTE protocol asyncpg uses by default.

    Returns:
        AsyncEngine: SQLAlchemy async engine instance.
    """
    global _engine

    if _engine is None:
        url = settings.database_url
        engine_kwargs: dict[str, Any] = {
            # Keep SQLAlchemy's internal echo logger disabled to prevent
            # duplicate output. SQL visibility is controlled via logger
            # levels in jobtracker.logging when JOBTRACKER_DATABASE_ECHO is
            # enabled.
            "echo": False,
        }

        if _is_sqlite_url(url):
            # Ensure database directory exists for on-disk SQLite.
            settings.ensure_directories()
            # Log the URL actually in use — NEVER ``settings.database_path``.
            # Under ``environment=test`` the engine is ``:memory:`` while
            # ``database_path`` still resolves to the real desktop database, so
            # the old line made every test run announce that it had opened
            # ~/Library/Application Support/JobTracker/jobtracker.db. That is
            # false, and it has already caused a green test run to be diagnosed
            # as writing to the user's production data. A SQLite URL carries no
            # credentials, so it is safe to log verbatim.
            logger.info(f"Creating SQLite database engine: {url}")

            engine_kwargs["connect_args"] = {
                "check_same_thread": False,  # Required for async
            }

            # In-memory SQLite must use a single shared connection to persist
            # state across sessions. File-based DBs use normal pooling.
            if url.endswith(":memory:"):
                engine_kwargs["poolclass"] = StaticPool
        else:
            # Assume Postgres via asyncpg (Supabase). Configure for pgbouncer
            # transaction-mode pooler compatibility: no server-side prepared
            # statement cache, no client-side cache. NullPool lets the pooler
            # own connection lifecycle (every checkout is a fresh connection).
            logger.info("Creating Postgres database engine (Supabase/pgbouncer-safe)")
            engine_kwargs["connect_args"] = {
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
            }
            engine_kwargs["poolclass"] = NullPool

        _engine = create_async_engine(url, **engine_kwargs)

        # On Postgres (Supabase), wire per-transaction RLS GUCs +
        # search_path pinning onto the engine. SQLite (desktop/tests) has no
        # RLS/GUC concept, so the listener is only attached for Postgres.
        if not _is_sqlite_url(url):
            _install_rls_guc_listener(_engine)

    return _engine


async def init_db() -> None:
    """
    Initialize the database.

    Behaviour is dialect-gated:

    - SQLite (desktop/tests): enables WAL + busy_timeout + foreign keys,
      creates all tables from ``SQLModel.metadata``, and installs FTS5
      virtual tables/triggers. Safe to call repeatedly.
    - Postgres (cloud/Supabase): no-op for schema management. Alembic
      owns the schema; running ``create_all`` here would race with
      Alembic and fight over ownership during cold-start deploys. WAL
      and FTS5 are SQLite-specific concepts and are skipped entirely.

    This should be called on application startup.
    """
    # Import models to register them with SQLModel metadata
    # This MUST happen before create_all() is called
    from jobtracker.database import models  # noqa: F401

    engine = get_engine()
    url = settings.database_url

    if not _is_sqlite_url(url):
        logger.info(
            "Skipping init_db() schema creation on non-SQLite backend "
            "(%s) - Alembic owns migrations.",
            url.split("://", 1)[0],
        )
        return

    logger.info("Initializing SQLite database...")

    async with engine.begin() as conn:
        # Enable WAL mode for concurrent read/write access
        # This allows SwiftUI to read while Python writes
        await conn.execute(text("PRAGMA journal_mode=WAL"))

        # Wait up to 5 seconds for locks (prevents immediate failures)
        await conn.execute(text("PRAGMA busy_timeout=5000"))

        # Enable foreign key constraints (disabled by default in SQLite)
        await conn.execute(text("PRAGMA foreign_keys=ON"))

        # Create all tables from SQLModel metadata
        await conn.run_sync(SQLModel.metadata.create_all)

        # Apply lightweight runtime migrations for existing user databases.
        await _apply_runtime_migrations(conn)

    logger.info(f"Database initialized at: {settings.database_path}")


async def _apply_runtime_migrations(conn) -> None:
    """
    Apply additive schema migrations that keep existing local DBs usable.

    We intentionally support only safe, additive changes here (new nullable
    columns) because this project currently has no full migration framework.
    """

    result = await conn.execute(text("PRAGMA table_info(emails)"))
    columns = {row[1] for row in result.fetchall()}

    if "body_html" not in columns:
        await conn.execute(text("ALTER TABLE emails ADD COLUMN body_html TEXT"))
        logger.info("Applied migration: added emails.body_html")

    if "suggested_category" not in columns:
        # ``create_all`` above adds missing TABLES, never missing COLUMNS, so an
        # existing desktop DB would otherwise keep a schema the shared SQLModel
        # no longer matches — and every ``select(Email)`` emits an explicit
        # column list, so the failure would be an OperationalError on the first
        # read, not a silent degradation. VARCHAR(19) mirrors what
        # ``create_all`` writes for this column on a fresh DB (the longest
        # label, ``PENDING_APPLICATION``); SQLite ignores the length either way.
        await conn.execute(
            text("ALTER TABLE emails ADD COLUMN suggested_category VARCHAR(19)")
        )
        logger.info("Applied migration: added emails.suggested_category")

    await _ensure_fts_search_objects(conn)


async def _ensure_fts_search_objects(conn) -> None:
    """
    Create FTS5 virtual tables + triggers for cross-entity search.

    This powers full-text search across:
    - application company/position/notes
    - linked email subject/sender/body
    """
    try:
        await conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS applications_fts
                USING fts5(
                    company,
                    position,
                    notes,
                    content='applications',
                    content_rowid='id',
                    tokenize='porter'
                )
                """
            )
        )

        await conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts
                USING fts5(
                    subject,
                    sender_name,
                    sender_email,
                    body_text,
                    body_snippet,
                    content='emails',
                    content_rowid='id',
                    tokenize='porter'
                )
                """
            )
        )

        await conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS applications_ai
                AFTER INSERT ON applications BEGIN
                  INSERT INTO applications_fts(rowid, company, position, notes)
                  VALUES (new.id, new.company, new.position, COALESCE(new.notes, ''));
                END
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS applications_ad
                AFTER DELETE ON applications BEGIN
                  INSERT INTO applications_fts(applications_fts, rowid, company, position, notes)
                  VALUES ('delete', old.id, old.company, old.position, COALESCE(old.notes, ''));
                END
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS applications_au
                AFTER UPDATE ON applications BEGIN
                  INSERT INTO applications_fts(applications_fts, rowid, company, position, notes)
                  VALUES ('delete', old.id, old.company, old.position, COALESCE(old.notes, ''));
                  INSERT INTO applications_fts(rowid, company, position, notes)
                  VALUES (new.id, new.company, new.position, COALESCE(new.notes, ''));
                END
                """
            )
        )

        await conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS emails_ai
                AFTER INSERT ON emails BEGIN
                  INSERT INTO emails_fts(rowid, subject, sender_name, sender_email, body_text, body_snippet)
                  VALUES (
                    new.id,
                    COALESCE(new.subject, ''),
                    COALESCE(new.sender_name, ''),
                    COALESCE(new.sender_email, ''),
                    COALESCE(new.body_text, ''),
                    COALESCE(new.body_snippet, '')
                  );
                END
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS emails_ad
                AFTER DELETE ON emails BEGIN
                  INSERT INTO emails_fts(emails_fts, rowid, subject, sender_name, sender_email, body_text, body_snippet)
                  VALUES (
                    'delete',
                    old.id,
                    COALESCE(old.subject, ''),
                    COALESCE(old.sender_name, ''),
                    COALESCE(old.sender_email, ''),
                    COALESCE(old.body_text, ''),
                    COALESCE(old.body_snippet, '')
                  );
                END
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS emails_au
                AFTER UPDATE ON emails BEGIN
                  INSERT INTO emails_fts(emails_fts, rowid, subject, sender_name, sender_email, body_text, body_snippet)
                  VALUES (
                    'delete',
                    old.id,
                    COALESCE(old.subject, ''),
                    COALESCE(old.sender_name, ''),
                    COALESCE(old.sender_email, ''),
                    COALESCE(old.body_text, ''),
                    COALESCE(old.body_snippet, '')
                  );
                  INSERT INTO emails_fts(rowid, subject, sender_name, sender_email, body_text, body_snippet)
                  VALUES (
                    new.id,
                    COALESCE(new.subject, ''),
                    COALESCE(new.sender_name, ''),
                    COALESCE(new.sender_email, ''),
                    COALESCE(new.body_text, ''),
                    COALESCE(new.body_snippet, '')
                  );
                END
                """
            )
        )

        app_fts_count = (
            await conn.execute(text("SELECT COUNT(*) FROM applications_fts"))
        ).scalar()
        if not app_fts_count:
            await conn.execute(text("INSERT INTO applications_fts(applications_fts) VALUES ('rebuild')"))

        email_fts_count = (
            await conn.execute(text("SELECT COUNT(*) FROM emails_fts"))
        ).scalar()
        if not email_fts_count:
            await conn.execute(text("INSERT INTO emails_fts(emails_fts) VALUES ('rebuild')"))
    except Exception as exc:
        # Keep backend usable even if host SQLite lacks FTS5.
        logger.warning("FTS5 setup skipped: %s", exc)


async def close_db() -> None:
    """
    Close the database connection.

    Should be called on application shutdown to cleanly
    close all database connections.
    """
    global _engine

    if _engine is not None:
        logger.info("Closing database connection...")
        await _engine.dispose()
        _engine = None
        logger.info("Database connection closed")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.

    Use as a context manager for automatic cleanup:

        async with get_session() as session:
            result = await session.exec(select(Application))
            apps = result.all()

    The session is automatically closed when exiting the context.
    Changes are NOT automatically committed - call session.commit()
    or session.flush() to persist changes.

    Yields:
        AsyncSession: SQLModel async session for database operations.
    """
    engine = get_engine()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Use with FastAPI's Depends() for automatic injection:

        @app.get("/applications")
        async def list_applications(session: AsyncSession = Depends(get_session_dependency)):
            result = await session.exec(select(Application))
            return result.all()

    Yields:
        AsyncSession: SQLModel async session.
    """
    async with get_session() as session:
        yield session


# =============================================================================
# Database Utilities
# =============================================================================


async def get_db_stats() -> dict:
    """
    Get database statistics for health checks.

    Returns:
        dict: Database statistics including table counts.
    """
    from jobtracker.database.models import Application, Email, TrainingData

    async with get_session() as session:
        # Get table counts
        app_count = await session.exec(
            text("SELECT COUNT(*) FROM applications")
        )
        email_count = await session.exec(
            text("SELECT COUNT(*) FROM emails")
        )
        training_count = await session.exec(
            text("SELECT COUNT(*) FROM training_data")
        )

        # File size query is SQLite-specific. On Postgres we just report 0;
        # cloud deployments observe DB size via Supabase dashboards.
        size_bytes = 0
        if _is_sqlite_url(settings.database_url):
            db_size_result = await session.exec(
                text(
                    "SELECT page_count * page_size as size "
                    "FROM pragma_page_count(), pragma_page_size()"
                )
            )
            size_bytes = db_size_result.scalar() or 0

        return {
            "path": str(settings.database_path),
            "applications": app_count.scalar() or 0,
            "emails": email_count.scalar() or 0,
            "training_examples": training_count.scalar() or 0,
            "size_bytes": size_bytes,
        }


async def vacuum_db() -> None:
    """
    Vacuum the database to reclaim space.

    SQLite-only operation. On Postgres this is a no-op because VACUUM
    behaves very differently (and is typically handled by the managed
    provider, e.g. Supabase autovacuum).
    """
    if not _is_sqlite_url(settings.database_url):
        logger.info("vacuum_db() is SQLite-only; skipping on non-SQLite backend.")
        return

    engine = get_engine()

    logger.info("Vacuuming database...")

    async with engine.begin() as conn:
        await conn.execute(text("VACUUM"))

    logger.info("Database vacuumed successfully")
