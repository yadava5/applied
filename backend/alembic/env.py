"""
Alembic Environment
===================

Hybrid env.py for JobTracker that supports:

- Offline mode (`alembic upgrade head --sql`) for CI and SQL-review flows.
- Online mode against SQLite (developer laptops, CI) or Postgres (Supabase).

URL resolution order (highest priority first):

1. ``DIRECT_URL``  - non-pooler Postgres URL. REQUIRED when running DDL
   against Supabase because PgBouncer in transaction mode does not support
   PREPARE statements that Alembic emits.
2. ``DATABASE_URL`` - pooled or direct URL used by the app at runtime.
3. ``settings.database_url`` - falls back to the SQLModel-settings URL,
   which is the in-memory SQLite URL in tests and an on-disk SQLite URL
   for desktop installs.

The sync driver is chosen automatically so Alembic - which is purely
synchronous - does not pull in asyncpg/aiosqlite.
"""

from __future__ import annotations

import os
import sys
import time
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# A fixed 64-bit key for the migration mutex. Any constant works as long as it
# never changes and nothing else in this database uses it; advisory locks share
# one namespace per database, so a collision would make two unrelated things
# exclude each other. Chosen as the low 63 bits of an arbitrary literal rather
# than a hash of a string, because a hash makes the value depend on the Python
# version's hash seed and therefore differ between runs.
ADVISORY_LOCK_KEY = 4_021_547_809_311_027
# Overridable so a test can prove the timeout path fires without sitting on it
# for two minutes. A guard whose failure branch has never been executed is not
# a guard.
ADVISORY_LOCK_WAIT_S = float(os.environ.get("ALEMBIC_LOCK_WAIT_S", "120"))
ADVISORY_LOCK_POLL_S = float(os.environ.get("ALEMBIC_LOCK_POLL_S", "2"))

# Bounds for a migration running unattended against a live database.
LOCK_TIMEOUT_S = 5
STATEMENT_TIMEOUT_S = 600

# Make sure `backend/` is on sys.path so `jobtracker` imports work regardless
# of where alembic is invoked from.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import SQLModel  # noqa: E402

from jobtracker.config import settings  # noqa: E402
from jobtracker.database import models  # noqa: E402,F401  # register tables
from jobtracker.database.migration_url import normalise_sync_driver  # noqa: E402

# Alembic Config object (from alembic.ini).
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _resolve_url() -> str:
    """Pick the DB URL and normalise it to a sync driver for Alembic."""

    url = (
        os.environ.get("DIRECT_URL")
        or os.environ.get("DATABASE_URL")
        or settings.database_url
    )

    # Alembic runs synchronously; swap async drivers for sync equivalents so we
    # don't require an event loop inside env.py. Shared with db-migrate.yml's
    # reachability probe — see migration_url.py for why that sharing is the
    # whole point.
    return normalise_sync_driver(url)


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emit SQL only)."""

    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def _guard_postgres_connection(connection) -> None:
    """Bound the two ways an unattended migration can hurt a live database.

    **Timeouts.** ``ADD COLUMN ... NULL`` is catalog-only, but it still takes
    ACCESS EXCLUSIVE: queued behind one long transaction it makes every reader
    queue behind *it*. ``lock_timeout`` turns that from a stall into a clean
    abort you retry. ``statement_timeout`` bounds the migration itself. Both are
    session-level (not ``SET LOCAL``) so they survive the COMMIT that
    ``autocommit_block()`` performs — see below.

    **Mutual exclusion.** Two pushes to main in quick succession would otherwise
    run ``upgrade head`` concurrently against the same database. The advisory
    lock makes the second wait. It is deliberately ``pg_advisory_lock``'s
    session-scoped form, **not** ``pg_advisory_xact_lock``: revision
    ``b9e42f7c10ad`` opens an ``autocommit_block()`` to add an enum label, which
    commits the surrounding transaction. A transaction-scoped lock would be
    released right there, in the middle of the run, with nothing reporting that
    the mutex had silently evaporated.

    The wait is bounded and polled with ``pg_try_advisory_lock`` rather than
    blocking in ``pg_advisory_lock``, so a migration that never finishes fails a
    later run with a message instead of hanging a CI job until it is cancelled.
    """

    connection.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT_S}s'")
    connection.exec_driver_sql(f"SET statement_timeout = '{STATEMENT_TIMEOUT_S}s'")

    deadline = time.monotonic() + ADVISORY_LOCK_WAIT_S
    attempt = 0
    while True:
        acquired = connection.exec_driver_sql(
            f"SELECT pg_try_advisory_lock({ADVISORY_LOCK_KEY})"
        ).scalar()
        if acquired:
            if attempt:
                print(
                    f"alembic: acquired migration lock after {attempt} attempt(s)",
                    file=sys.stderr,
                )
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Could not acquire the migration advisory lock "
                f"({ADVISORY_LOCK_KEY}) within {ADVISORY_LOCK_WAIT_S}s. Another "
                f"`alembic upgrade` is running against this database, or a "
                f"previous one died holding the lock. Check for a live session: "
                f"SELECT * FROM pg_locks WHERE locktype = 'advisory';"
            )
        attempt += 1
        time.sleep(ADVISORY_LOCK_POLL_S)


def _release_implicit_transaction(connection) -> None:
    """Commit the transaction our own setup statements opened.

    **This is load-bearing and it is not obvious.** SQLAlchemy 2.0 autobegins a
    transaction on the first statement, so by the time the GUCs are set and the
    lock is taken, ``connection`` is mid-transaction. Alembic's
    ``context.begin_transaction()`` then sees a connection that is *already* in
    one, declines to own it, and leaves ``MigrationContext._transaction`` as
    ``None`` — whereupon revision ``b9e42f7c10ad``'s ``autocommit_block()``
    fails on ``assert self._transaction is not None`` and the whole chain dies
    on a fresh database.

    Measured, not reasoned: adding the guard without this commit turned
    ``alembic upgrade head`` from empty into an ``AssertionError`` inside
    ``alembic/runtime/migration.py``. Committing here returns the connection to
    "no transaction", which is the state Alembic expects to receive.

    Both things we set survive the commit *because* they are session-scoped:
    plain ``SET`` (not ``SET LOCAL``) persists for the session, and
    ``pg_advisory_lock`` is held until unlock or disconnect. That is checked at
    the end of the run by :func:`_assert_lock_survived` rather than assumed.
    """

    connection.commit()


def _assert_lock_survived(connection) -> None:
    """Fail if the migration mutex was lost while the revisions ran.

    This is a postcondition, not a probe. ``pg_advisory_lock`` is session-scoped
    and so is *supposed* to survive the COMMIT that ``autocommit_block()``
    performs, but that is a property of two interacting libraries rather than
    something this file controls: an Alembic change to how autocommit blocks are
    entered, or a revision that reconnects, would drop the mutex silently and
    the next concurrent run would corrupt the version table with no signal at
    all. Checking costs one query at the end of a migration and converts a
    silent class of failure into a loud one.

    ``pg_locks`` splits a 64-bit advisory key across ``classid`` (high 32) and
    ``objid`` (low 32); ``objsubid = 1`` marks the single-bigint form, which is
    what :func:`pg_try_advisory_lock` with one argument takes.
    """

    held = connection.exec_driver_sql(
        "SELECT EXISTS (SELECT 1 FROM pg_locks "
        "WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
        "AND objsubid = 1 "
        f"AND (classid::bigint * 4294967296 + objid::bigint) = {ADVISORY_LOCK_KEY})"
    ).scalar()
    if not held:
        raise RuntimeError(
            "The migration advisory lock was released before the run finished. "
            "Revisions may have been applied without mutual exclusion; verify "
            "alembic_version and the schema before running anything else."
        )


def run_migrations_online() -> None:
    """Run migrations with an active DB connection."""

    url = _resolve_url()
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # SQLite has neither advisory locks nor these GUCs, and the desktop
        # database has exactly one writer anyway.
        if not url.startswith("sqlite"):
            _guard_postgres_connection(connection)
            _release_implicit_transaction(connection)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Required for SQLite to perform table-altering operations;
            # harmless on Postgres (simply ignored for non-SQLite backends
            # by alembic's batch logic).
            render_as_batch=url.startswith("sqlite"),
        )

        with context.begin_transaction():
            context.run_migrations()

        if not url.startswith("sqlite"):
            _assert_lock_survived(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
