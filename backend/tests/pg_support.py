"""One Postgres, shared by the suites added in this change set.

WHY THIS EXISTS. ``test_rls_postgres`` and ``test_migrations_postgres`` each
resolve their own database at import time, and when no
``JOBTRACKER_TEST_PG_ADMIN_URL`` is exported that means each starts its own
throwaway ``postgres:16``. Adding two more modules that did the same took a
local full-suite run to four simultaneous containers, and the run went red with
``server closed the connection unexpectedly`` — not a product failure, but a
failure that LOOKS like one, and worse, the modules then skipped. A skip is
green.

So the two modules added here share a single container, memoised for the
process. The existing two are deliberately left alone: rewriting their
resolution is unrelated to this change set, and three containers is inside what
a laptop and a CI runner handle. Under CI nothing here starts anything at all —
``JOBTRACKER_TEST_PG_ADMIN_URL`` names the service container and every suite
uses it.

THE SHARED-DATABASE RULE. When that variable IS set, every Postgres suite in
this repo points at the SAME database, so each one must begin by making the
schema its own. ``reset_public_schema`` is that step, and it is the same
``DROP SCHEMA public CASCADE`` / ``CREATE SCHEMA public`` the two existing
suites already perform for the same reason. Without it, whichever module runs
second inherits the first one's tables and its ``alembic upgrade head`` fails
with "relation already exists" — a failure about test ordering wearing the
costume of a broken migration.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

_RESOLVED: tuple[str | None, Any] | None = None


def resolve_admin_url() -> tuple[str | None, Any]:
    """``(url, container)`` — memoised, so repeated imports reuse one server.

    An explicit ``JOBTRACKER_TEST_PG_ADMIN_URL`` wins (CI's service container),
    otherwise a throwaway ``postgres:16`` via testcontainers, otherwise
    ``(None, None)`` and the caller skips. A suite that runs only when a human
    exported a variable is a suite that never runs.
    """

    global _RESOLVED
    if _RESOLVED is not None:
        return _RESOLVED

    explicit = os.environ.get("JOBTRACKER_TEST_PG_ADMIN_URL")
    if explicit:
        _RESOLVED = (explicit, None)
        return _RESOLVED

    try:
        from testcontainers.community.postgres import PostgresContainer
    except Exception:  # pragma: no cover - machine without the test extra
        _RESOLVED = (None, None)
        return _RESOLVED

    try:
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception:  # pragma: no cover - no docker daemon, or it refused
        _RESOLVED = (None, None)
        return _RESOLVED

    _RESOLVED = (container.get_connection_url(), container)
    return _RESOLVED


def sync_url(admin_url: str) -> str:
    """The admin URL with a synchronous driver, whatever scheme it arrived in.

    Alembic is purely synchronous. CI hands these modules the ``+asyncpg`` URL
    it gives the RLS suite and testcontainers offers ``+psycopg2``; both become
    ``+psycopg`` (v3), which is what ``alembic/env.py`` itself swaps to.
    """

    return (
        make_url(admin_url)
        .set(drivername="postgresql+psycopg")
        .render_as_string(hide_password=False)
    )


def reset_public_schema(engine, owner_ids=()) -> None:
    """Empty ``public`` and install the Supabase auth objects the chain needs.

    ``a8d4ec5fba26`` creates policies over ``auth.uid()``, which Postgres
    resolves when the policy is CREATED — so ``upgrade head`` cannot run against
    a database with no ``auth`` schema. Production gets those from Supabase.
    Providing them here is not test scaffolding around the assertion; it is the
    environment the migration is written for.
    """

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS auth.users (id uuid primary key)"))
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid "
                "LANGUAGE sql STABLE AS $$ SELECT NULLIF("
                "current_setting('request.jwt.claims', true)::json->>'sub', "
                "'')::uuid $$"
            )
        )
        for owner in owner_ids:
            conn.execute(
                text("INSERT INTO auth.users(id) VALUES (:a) ON CONFLICT DO NOTHING"),
                {"a": str(owner)},
            )
