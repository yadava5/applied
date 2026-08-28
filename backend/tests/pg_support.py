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
a laptop and a CI runner handle.

WHERE THIS ACTUALLY RUNS, checked rather than assumed. ``backend-ci.yml``'s
whole-suite ``test`` job sets only ``JOBTRACKER_ENVIRONMENT`` and
``PYTHON_KEYRING_BACKEND`` — it does NOT set
``JOBTRACKER_TEST_PG_ADMIN_URL`` — so on CI every Postgres module resolves its
own throwaway container via testcontainers, and the two modules sharing this
helper share one. The jobs that DO export that variable (``rls-postgres``,
``migrations``) each run a single module against it, so nothing is shared there
either.

THE SHARED-DATABASE RULE, and its limit. When that variable is set, every
Postgres suite pointed at it lands in the SAME database, so each must begin by
making the schema its own. ``reset_public_schema`` is that step, and it is the
same ``DROP SCHEMA public CASCADE`` / ``CREATE SCHEMA public`` the two existing
suites already perform for the same reason. Without it, whichever module runs
second inherits the first one's tables and its ``alembic upgrade head`` fails
with "relation already exists" — a failure about test ordering wearing the
costume of a broken migration.

That per-module reset is NOT sufficient for the one configuration nothing in CI
uses: exporting ``JOBTRACKER_TEST_PG_ADMIN_URL`` and running the WHOLE suite,
which points all four Postgres modules at one database. ``test_rls_postgres``
builds its schema once per process behind a module-level ``_SCHEMA_READY`` flag
and ``test_migrations_postgres`` rebuilds per test, so a reset here can land
between another module's build and its use; the observed symptom is
``type "applicationstatus" already exists`` from this helper's own
``upgrade head``. Measured, not theorised — and measured only there: with the
variable unset (CI's arrangement, one container per module) the same suite runs
clean under ``--cov``. If you want a single local Postgres for everything, run
the four Postgres modules in separate pytest invocations.
"""

from __future__ import annotations

import atexit
import contextlib
import os
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

_RESOLVED: tuple[str | None, Any] | None = None


def register_owned_container(container: Any) -> Callable[[], None]:
    """Stop ``container`` when this interpreter exits, and hand back the stopper.

    WHY THIS IS OURS TO DO, AND NOT RYUK'S
    ---------------------------------------
    Testcontainers ships a resource reaper (Ryuk) whose whole job is this, and
    it is enabled here — ``testcontainers_config.ryuk_disabled`` is ``False``
    and no ``.testcontainers.properties`` overrides it. It genuinely starts:
    driving ``PostgresContainer("postgres:16").start()`` from a throwaway
    script and listing containers from inside that same process shows
    ``testcontainers/ryuk:0.8.1  testcontainers-ryuk-8ccd7575-…`` alive beside
    the database.

    It still reaps nothing. Ryuk kills a session's containers
    ``RYUK_RECONNECTION_TIMEOUT`` (10 s) after the client that spawned it drops
    the socket — but ``Reaper.delete_instance`` is itself registered with
    ``atexit`` and **stops the Ryuk container** on the way out. The client kills
    its own reaper before the reaper's timer can start. Measured: two seconds
    after that script exited, the Ryuk container was gone and the ``postgres:16``
    was still up; it was still up thirty seconds later.

    So on any orderly exit the container is ours to stop, and only ours. Ryuk
    remains the backstop for the path where ``atexit`` never runs at all — a
    ``SIGKILL`` — which is why nothing here disables it.

    WHY ``teardown_module`` IS NOT ENOUGH ON ITS OWN
    ------------------------------------------------
    Every module that uses a throwaway Postgres resolves it at **import** time,
    but ``teardown_module`` only fires once pytest has actually *executed* a
    test in that module. A run that imports without running — ``--collect-only``,
    a ``-k`` that deselects everything, an ``-x`` abort earlier in the session —
    leaves the container up forever. ``atexit`` is what covers those.

    THE FLAG IS PER CONTAINER
    -------------------------
    ``stop()`` on an already-removed container raises, so the stopper must be
    idempotent — ``teardown_module`` calls it for the normal case, so the port
    is released promptly rather than at process exit, and ``atexit`` calls it
    again. The flag lives in this closure rather than in a module global
    because three modules register three different containers through here, and
    one shared flag would make every registration after the first a silent
    no-op.
    """

    stopped = False

    def stop() -> None:
        nonlocal stopped
        if stopped:
            return
        stopped = True
        with contextlib.suppress(Exception):  # already gone, or the daemon did
            container.stop()

    atexit.register(stop)
    return stop



def resolve_admin_url() -> tuple[str | None, Any]:
    """``(url, container)`` — memoised, so repeated imports reuse one server.

    An explicit ``JOBTRACKER_TEST_PG_ADMIN_URL`` wins (CI's service container),
    otherwise a throwaway ``postgres:16`` via testcontainers, otherwise
    ``(None, None)`` and the caller skips. A suite that runs only when a human
    exported a variable is a suite that never runs.

    A container started here is registered for teardown before it is handed
    out — see ``register_owned_container`` for why that cannot be left to
    Ryuk or to ``teardown_module``.
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

    register_owned_container(container)
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
