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
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make sure `backend/` is on sys.path so `jobtracker` imports work regardless
# of where alembic is invoked from.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from jobtracker.config import settings  # noqa: E402
from jobtracker.database import models  # noqa: E402,F401  # register tables
from sqlmodel import SQLModel  # noqa: E402

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

    # Alembic runs synchronously; swap async drivers for sync equivalents
    # so we don't require an event loop inside env.py.
    if url.startswith("sqlite+aiosqlite"):
        url = url.replace("sqlite+aiosqlite", "sqlite", 1)
    elif url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)

    return url


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


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
