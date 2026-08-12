"""The Alembic chain, exercised against a REAL Postgres.

WHY THIS MODULE EXISTS
----------------------

Every other suite in this repo runs on SQLite, where ``sa.Enum`` renders as
``VARCHAR`` with no constraint. That makes the entire class of enum-label bugs
invisible: a migration can add the wrong label, in the wrong case, or none at
all, and 600-odd tests stay green while production 500s on the first write.

The specific bug this was written for: SQLModel/SQLAlchemy persist an enum's
**name**, so ``applicationstatus`` holds ``'ASSESSMENT'`` while the API speaks
``'assessment'``. ``ALTER TYPE ... ADD VALUE 'assessment'`` would have been
valid DDL and then failed every write with ``invalid input value for enum
applicationstatus: "ASSESSMENT"``. Nothing on SQLite can tell those two apart.

So this module asserts, on Postgres 16:

1. the whole chain applies to a bare database in ONE ``upgrade head``
   invocation — the way a fresh environment is built, and the case
   ``env.py``'s single wrapping transaction makes fragile;
2. the type's labels are exactly ``[s.name for s in ApplicationStatus]``, in
   the enum's declaration order;
3. a row written through SQLAlchemy as ``ApplicationStatus.ASSESSMENT``
   round-trips — and the lowercase spelling is genuinely rejected, so #2 is
   load-bearing rather than decorative;
4. the forward-only downgrade remaps rows and leaves the label in place.

Postgres, like ``test_rls_postgres.py``: an explicit
``JOBTRACKER_TEST_PG_ADMIN_URL`` wins (CI's service container), otherwise a
throwaway ``postgres:16`` is started via testcontainers, and only a machine
with neither skips. Alembic is synchronous, so the URL is rewritten to
``postgresql+psycopg`` — the same swap ``alembic/env.py`` performs.

THE AUTH SHIM IS NOT TEST SCAFFOLDING. ``a8d4ec5fba26`` creates policies over
``auth.uid()``, which Postgres resolves when the policy is created, so
``upgrade head`` cannot run on a database that has no ``auth`` schema. In
production Supabase provides it. Here the fixture provides the same two objects
before the chain runs; without them this module would report a failure that
says nothing about the migrations.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from jobtracker.database.models import Application, ApplicationStatus

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# The revision under test, and its parent — named so a rename of the file
# cannot silently turn the downgrade test into a test of some other revision.
ASSESSMENT_REVISION = "b9e42f7c10ad"
PARENT_REVISION = "b7c31e0d94aa"

OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _resolve_admin_url() -> tuple[str | None, Any]:
    """Find a Postgres, starting one if that is what it takes.

    Same three-step resolution as ``test_rls_postgres.py``, and for the same
    reason: a suite that skips unless a human exported an environment variable
    is a suite that never runs, and a skip is green.
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

    return container.get_connection_url(), container


ADMIN_URL, _OWNED_CONTAINER = _resolve_admin_url()


def teardown_module(module) -> None:  # noqa: ANN001 - pytest hook signature
    """Stop the container we started, if we started one."""

    if _OWNED_CONTAINER is not None:
        _OWNED_CONTAINER.stop()


pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason=(
        "No Postgres available: set JOBTRACKER_TEST_PG_ADMIN_URL, or run Docker "
        "so a throwaway postgres:16 can be started. Skipping leaves the "
        "migration chain — and every enum label in it — UNVERIFIED on this run, "
        "because the SQLite suites render sa.Enum as VARCHAR and cannot see it."
    ),
)


def _sync_url() -> str:
    """The admin URL with a synchronous driver, whatever scheme it arrived in.

    Alembic is purely synchronous. CI hands this module the ``+asyncpg`` URL it
    gives the RLS suite, and testcontainers offers ``+psycopg2``; both become
    ``+psycopg`` (v3), which is what ``alembic/env.py`` itself swaps to.
    """

    return (
        make_url(ADMIN_URL)
        .set(drivername="postgresql+psycopg")
        .render_as_string(hide_password=False)
    )


def _alembic(command_name: str, revision: str) -> str:
    """Run one Alembic command against the test database, in a SUBPROCESS.

    ``DIRECT_URL`` is how production points Alembic at the non-pooler Postgres,
    and it is the first URL ``env.py`` looks for — so this drives exactly the
    resolution path a deploy uses, through the same CLI a deploy invokes.

    A subprocess rather than ``alembic.command`` in-process, and not for
    tidiness: ``env.py`` calls ``fileConfig(alembic.ini)``, which reconfigures
    the ROOT logging config of whatever process runs it. In-process that
    silently disabled propagation for every logger pytest was capturing, and two
    unrelated tests in ``test_reopen_after_rejection.py`` — which assert on the
    "Reopened" log line — went red purely from import order. Measured, not
    theorised.
    """

    env = dict(os.environ, DIRECT_URL=_sync_url())
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), command_name, revision],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"alembic {command_name} {revision} failed ({proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return proc.stdout + proc.stderr


def _enum_labels(engine: Engine, type_name: str = "applicationstatus") -> list[str]:
    """The type's labels in ``pg_enum`` sort order — i.e. lifecycle order."""

    with engine.connect() as c:
        return [
            row[0]
            for row in c.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = :name ORDER BY e.enumsortorder"
                ),
                {"name": type_name},
            )
        ]


def _insert_application(engine: Engine, status: ApplicationStatus, company: str) -> int:
    """Insert one row THROUGH SQLAlchemy, so the Enum bind processor is used.

    Raw SQL would prove nothing here: the question is what the ORM sends for
    ``ApplicationStatus.ASSESSMENT``, not what Postgres accepts when a test
    types the label by hand.
    """

    now = datetime(2026, 8, 12, 12, 0, 0)
    with engine.begin() as c:
        return c.execute(
            sa.insert(Application.__table__)
            .values(
                user_id=OWNER,
                company=company,
                position="Software Engineer",
                status=status,
                created_at=now,
                updated_at=now,
            )
            .returning(Application.__table__.c.id)
        ).scalar_one()


@pytest.fixture
def engine() -> Iterator[Engine]:
    """A bare database with Supabase's auth objects and nothing else."""

    eng = sa.create_engine(_sync_url(), poolclass=sa.pool.NullPool)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
        c.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
        c.execute(text("CREATE TABLE IF NOT EXISTS auth.users (id uuid primary key)"))
        c.execute(
            text(
                "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid "
                "LANGUAGE sql STABLE AS $$ "
                "SELECT nullif(current_setting('request.jwt.claims', true)::jsonb "
                "->> 'sub', '')::uuid $$"
            )
        )
        c.execute(
            text("INSERT INTO auth.users(id) VALUES (:a) ON CONFLICT DO NOTHING"),
            {"a": str(OWNER)},
        )
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def migrated(engine: Engine) -> Engine:
    """``alembic upgrade head`` — one invocation, from empty, like a new env."""

    _alembic("upgrade", "head")
    return engine


# =============================================================================
# The chain applies, and the type says what the enum says
# =============================================================================


def test_the_whole_chain_applies_to_a_bare_database_in_one_invocation(
    migrated: Engine,
) -> None:
    """A fresh environment runs every revision in a single upgrade.

    ``env.py`` wraps ALL pending revisions in ONE transaction (it does not set
    ``transaction_per_migration``), which is why ``b9e42f7c10ad`` adds its enum
    label inside an ``autocommit_block``: a label added and then USED in the
    same transaction raises 55P04. Running the chain revision-by-revision would
    not exercise that at all, so this deliberately goes straight to ``head``.
    """

    with migrated.connect() as c:
        assert c.execute(
            text("SELECT to_regclass('public.applications')")
        ).scalar_one() is not None
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ASSESSMENT_REVISION
        )


def test_the_enum_labels_are_the_python_enum_names_in_order(migrated: Engine) -> None:
    """THE check the SQLite suites cannot make.

    Labels are the member NAMES (uppercase), not the API values, because that
    is what SQLAlchemy persists — and ``ASSESSMENT`` sits where the enum
    declares it, between ``APPLIED`` and ``INTERVIEWING``, because the migration
    added it ``BEFORE 'INTERVIEWING'``.
    """

    labels = _enum_labels(migrated)

    assert labels == [s.name for s in ApplicationStatus]
    assert labels[:3] == ["APPLIED", "ASSESSMENT", "INTERVIEWING"]
    # The API's spelling is NOT a label. If this ever passes, the migration
    # added the value instead of the name and every write is about to 500.
    assert "assessment" not in labels


def test_an_assessment_row_round_trips_through_sqlalchemy(migrated: Engine) -> None:
    """Write ``ApplicationStatus.ASSESSMENT``, read it back, unchanged.

    The production failure this stands in for: the enum member exists in Python
    and the type does not know its label, so every insert of an assessment row
    fails — on the write path only, i.e. after deploy, not at migration time.
    """

    app_id = _insert_application(migrated, ApplicationStatus.ASSESSMENT, "Roblox")

    with migrated.connect() as c:
        stored = c.execute(
            sa.select(Application.__table__.c.status).where(
                Application.__table__.c.id == app_id
            )
        ).scalar_one()
        raw = c.execute(
            text("SELECT status::text FROM applications WHERE id = :id"), {"id": app_id}
        ).scalar_one()

    assert stored is ApplicationStatus.ASSESSMENT
    assert stored.value == "assessment"  # what the API serves
    assert raw == "ASSESSMENT"  # what the database stores

    # Every other member still round-trips too — a migration that fixed one
    # label by breaking the type would otherwise pass the assertions above.
    for status in ApplicationStatus:
        got = _insert_application(migrated, status, f"Co-{status.name}")
        with migrated.connect() as c:
            assert (
                c.execute(
                    sa.select(Application.__table__.c.status).where(
                        Application.__table__.c.id == got
                    )
                ).scalar_one()
                is status
            )


def test_the_lowercase_spelling_is_rejected_by_the_type(migrated: Engine) -> None:
    """The positive control for the test above.

    If Postgres accepted ``'assessment'`` as well, "the labels are uppercase"
    would be an observation with no consequence. It is not: the wrong case is a
    hard error, which is exactly why the migration had to add ``'ASSESSMENT'``.
    """

    with pytest.raises(DBAPIError) as excinfo:
        with migrated.begin() as c:
            c.execute(
                text(
                    "INSERT INTO applications "
                    "(user_id, company, position, status, created_at, updated_at) "
                    "VALUES (:u, 'Lowercase Co', 'SWE', 'assessment', now(), now())"
                ),
                {"u": str(OWNER)},
            )

    assert "invalid input value for enum applicationstatus" in str(excinfo.value)


# =============================================================================
# ... and the downgrade is honest about being lossy
# =============================================================================


def test_the_downgrade_remaps_rows_and_leaves_the_label(migrated: Engine) -> None:
    """Forward-only, stated as a test rather than only as a docstring.

    Postgres has no ``DROP VALUE``, so the label survives the downgrade. The
    ROWS do not: an assessment becomes an interview, which is the fold this
    change removed and is real data loss on the way back — the same shape as
    ``b7c31e0d94aa`` dropping ``due_at``.
    """

    assessment_id = _insert_application(migrated, ApplicationStatus.ASSESSMENT, "Roblox")
    applied_id = _insert_application(migrated, ApplicationStatus.APPLIED, "Untouched Co")

    _alembic("downgrade", "-1")

    with migrated.connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == PARENT_REVISION
        )
        rows = dict(
            c.execute(text("SELECT id, status::text FROM applications")).all()
        )

    assert rows[assessment_id] == "INTERVIEWING"
    assert rows[applied_id] == "APPLIED"  # nothing else is touched
    # The label is inert, not gone.
    assert "ASSESSMENT" in _enum_labels(migrated)
