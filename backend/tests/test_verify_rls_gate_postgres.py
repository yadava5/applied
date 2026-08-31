"""The RLS gate's SQL, executed against a real Postgres.

WHY THIS MODULE EXISTS
----------------------

``scripts/verify_rls.py`` decides whether tenant isolation survived a migration,
and it runs in exactly one place: ``.github/workflows/db-migrate.yml``, after
``alembic upgrade head``, against **production**. Its unit tests
(``tests/test_verify_rls_gate.py``) cover ``collect_failures`` — a pure function
over query RESULTS. They structurally cannot cover the SQL, because the SQL is
what decides which rows become results.

Issue #691 measured what that costs. Of sixteen mutations run while #688 was
built, fifteen reddened a test. The sixteenth was reverting the grant query's
``relkind IN ('r','v','m','p','f')`` to the bare ``relkind = 'r'`` — the exact
revert that re-opens the bypass the widening exists to close — and it reddened
**zero** of the thirteen. Not a gap in the test authoring: the boundary.
Nothing on the ``collect_failures`` side of it can see a ``relkind``, a
``relacl``, or any SQL at all.

So this module puts the queries on a database. It applies the real Alembic
chain to a throwaway Postgres and calls ``verify_rls.main()`` — the script's own
entry point, executing the module-level constants the script itself executes.
It deliberately does NOT re-type the SQL: a test that types the SQL out again
passes against SQL the script does not run, which is this repository's named
recurring defect wearing a test as a disguise.

THE VIEW CASE IS THE POINT
--------------------------

``ALTER DEFAULT PRIVILEGES ... ON TABLES`` is set on schema ``public`` for the
role that owns every table here, and it does not mean ``relkind = 'r'``: it
stamps views, materialised views and partitioned tables too. A view is the
worst of those, not the mildest. Owned by the same role that owns the tables,
with ``security_invoker`` off, it runs its query AS that owner — and in
production that owner holds ``rolbypassrls``. So ``anon`` with SELECT on such a
view reads every user's rows with every policy skipped, while the tables
underneath stay perfectly protected and the gate prints its green summary.

``test_a_view_over_a_protected_table_is_scanned_too`` is that case, and it is
the only test in the repository that can tell an ``'r'``-only grant query from
the widened one.

THE MUTATIONS THAT PROVE THIS CAN FAIL, run against ``postgres:17`` while it was
written — because an integration test that has never been made to fail is not
evidence:

* ``GRANTS_QUERY``, ``relkind IN ('r','v','m','p','f')`` → ``relkind = 'r'``:
  the view test FAILS, **alone**. The two table cases stay green, correctly —
  an ordinary table is ``relkind 'r'`` either way. A surgical kill, on the one
  mutation that survived everything else in the repo.
* ``GRANTS_QUERY``, drop the ``CASE WHEN a.grantee = 0 THEN 'PUBLIC'`` arm:
  ``test_a_grant_to_public_is_a_failure`` FAILS. ``pg_get_userbyid(0)`` does not
  raise and does not return NULL — it returns the literal string
  ``'unknown (OID=0)'`` — so without the mapping the widest grant Postgres has
  arrives under a grantee name that is on no list, and the gate passes it.

WHICH POSTGRES
--------------

The ``rls-postgres`` job supplies ``postgres:17``, because production is 17.6
and #688's fixtures were measured on 16, where the owner privilege set differs
(``MAINTAIN`` is a 17 privilege). Off CI this module takes whatever
``tests/pg_support.py`` resolves, which is a ``postgres:16`` testcontainer.
Nothing asserted here depends on the version — the owner's own privileges are
never a failure, because the owner is not in ``FORBIDDEN_GRANTEES`` — but the
service container is the one pinned to production's major.

WHAT THIS DOES NOT DO
---------------------

It changes no privilege anywhere but a throwaway container, and every case
revokes what it granted, so the clean-schema assertion holds under any ordering
or ``-k`` selection. It also does not assert the summary's counts: "9 tables,
35 policies" is the state today, and a test that pinned it would have to be
edited every time a revision added a table — which trains people to edit tests.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine, text

from tests.pg_support import reset_public_schema, resolve_admin_url, sync_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
SCRIPT = REPO_ROOT / "scripts" / "verify_rls.py"

# The relation the mis-grants below are made on. ``applications`` rather than a
# table this module creates: the question is whether the gate sees a grant on
# the schema the CHAIN built.
PROTECTED_TABLE = "applications"

# Named as the mistake it stands for. A view over the protected table, owned by
# the table's owner, with security_invoker off — the shape ALTER DEFAULT
# PRIVILEGES can hand ``anon`` without a line of any revision saying so.
BYPASS_VIEW = "applications_unfiltered"

ADMIN_URL, _OWNED_CONTAINER = resolve_admin_url()

# NO ``teardown_module`` stopping the container: it is SHARED (see
# tests/pg_support.py), so whichever module finished first would pull the server
# out from under the others. A throwaway container dies with the pytest process.

pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason=(
        "No Postgres available: set JOBTRACKER_TEST_PG_ADMIN_URL, or run Docker "
        "so a throwaway Postgres can be started. Skipping leaves the RLS gate's "
        "SQL UNVERIFIED — every other test of that script is on the far side of "
        "the query boundary, so nothing else in this repo can tell an "
        "'r'-only grant query from the widened one."
    ),
)


def _load() -> ModuleType:
    """Import the tool by path — it is a script, not a package module.

    The same loader ``tests/test_verify_rls_gate.py`` uses, for the same reason,
    and registered in ``sys.modules`` before exec as the sibling gate tests do.
    """

    spec = importlib.util.spec_from_file_location("verify_rls", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load()


@pytest.fixture(scope="module")
def migrated_engine():
    """A database the real chain built, plus the ``anon`` role Supabase supplies.

    ``alembic upgrade head`` in a subprocess, exactly as
    ``test_cascade_delete_postgres`` and ``test_company_index_postgres`` run it,
    so the relations under test are the ones a migration produces rather than
    ones this file typed out. The runtime role stub (``jobtracker_app``,
    NOLOGIN NOBYPASSRLS) is created by revision ``e2b6f0a4d517`` itself — see
    "THE ROLE GUARD" in that revision — which is why nothing here creates it and
    why the clean run can assert the gate found it.

    ``anon`` is different: Supabase ships it and a bare container does not, so
    without it every ``GRANT ... TO anon`` below would fail with "role does not
    exist" and this module would report an error about its own fixture. NOLOGIN,
    so the stub can never be connected as.
    """

    url = sync_url(ADMIN_URL)
    engine = create_engine(url, future=True)

    # Take the schema for this module — see tests/pg_support.py. Under CI every
    # Postgres suite pointed at one database inherits the previous module's
    # tables otherwise, and ``upgrade head`` then fails with "relation already
    # exists" — a test-ordering problem wearing the costume of a broken
    # migration.
    reset_public_schema(engine)

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=dict(os.environ, DIRECT_URL=url),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"alembic upgrade head failed ({proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )

    with engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
                "CREATE ROLE anon NOLOGIN; "
                "END IF; END $$"
            )
        )

    yield engine
    engine.dispose()


@contextlib.contextmanager
def temporarily(engine, setup: Sequence[str], teardown: Sequence[str]) -> Iterator[None]:
    """Apply ``setup``, run the test, and undo it whatever the test did.

    Every case here mis-grants a live schema, so the undo is not tidiness: the
    clean-schema assertion is the baseline all the others are measured against,
    and a leftover grant would red it for a reason that has nothing to do with
    the gate. ``finally``, so a failing assertion still cleans up.
    """

    with engine.begin() as conn:
        for statement in setup:
            conn.execute(text(statement))
    try:
        yield
    finally:
        with engine.begin() as conn:
            for statement in teardown:
                conn.execute(text(statement))


@pytest.fixture
def run_gate(capsys, monkeypatch):
    """Call ``verify_rls.main()`` against the test database and read its verdict.

    ``main()``, not a re-implementation of it: the point of this module is that
    the exact query strings the script executes get executed. It resolves the
    database from ``DIRECT_URL``, set here in the ``postgresql+psycopg`` form so
    the driver-suffix strip in ``_plain_url`` is on the path too.

    ``DATABASE_URL`` is cleared because ``main()`` falls back to it, and a stray
    value in the environment would point this at some other database.
    ``GITHUB_STEP_SUMMARY`` is cleared because ``main()`` APPENDS its green
    summary to that file — on CI the variable is set for every step, so without
    this a test run would write "RLS verified: ..." into the job summary, where
    it reads as a statement about production.
    """

    def _run() -> tuple[int, list[str]]:
        monkeypatch.setenv("DIRECT_URL", sync_url(ADMIN_URL))
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        capsys.readouterr()
        code = verifier.main()
        printed = [line for line in capsys.readouterr().out.splitlines() if line]
        return code, printed

    return _run


def _errors(printed: Sequence[str]) -> list[str]:
    """The failure lines, with the workflow-command prefix stripped."""

    return [line[len("::error::") :] for line in printed if line.startswith("::error::")]


# =============================================================================
# The clean schema — the baseline every case below is measured against
# =============================================================================


def test_the_chain_built_schema_passes_the_gate(migrated_engine, run_gate) -> None:
    """``alembic upgrade head`` on a bare database is green, end to end.

    Not a formality. This is the first time the gate's SQL has run anywhere but
    ``db-migrate.yml`` against production, so "the schema the chain produces
    satisfies the check" was an assumption rather than a measurement — and it is
    the assumption every mis-grant case below rests on, because each of them
    asserts that ONE change turned this green into a red.
    """

    code, printed = run_gate()

    assert _errors(printed) == []
    assert code == 0
    # The runtime role is named in the summary because the gate looked it up and
    # found it NOBYPASSRLS — the stub the chain creates. A run that never
    # reached the catalog could not say this.
    assert printed[-1].startswith("RLS verified: ")
    assert "jobtracker_app is NOBYPASSRLS" in printed[-1]


# =============================================================================
# A grant the gate must see
# =============================================================================


def test_a_grant_to_anon_on_a_protected_table_is_a_failure(migrated_engine, run_gate) -> None:
    """The case the whole privilege check exists for, on a real relation.

    ``anon`` is PostgREST's unauthenticated role: a grant to it is reachable
    from the public internet through Supabase's REST endpoint. The unit suite
    asserts the WORDING of this line; what is asserted here is that a grant
    sitting in ``pg_class.relacl`` reaches ``collect_failures`` at all.
    """

    with temporarily(
        migrated_engine,
        setup=[f"GRANT SELECT ON {PROTECTED_TABLE} TO anon"],
        teardown=[f"REVOKE SELECT ON {PROTECTED_TABLE} FROM anon"],
    ):
        code, printed = run_gate()

    assert code == 1
    assert _errors(printed) == [
        f"{PROTECTED_TABLE}: anon holds SELECT — nothing may be granted to anon on a "
        f"table holding user rows. ALTER DEFAULT PRIVILEGES can issue that grant "
        f"without it appearing in any revision, so its absence from the migration is "
        f"not evidence it is not there."
    ]


def test_a_view_over_a_protected_table_is_scanned_too(migrated_engine, run_gate) -> None:
    """THE case, and the one the rest of the repository cannot reach.

    Reverting ``GRANTS_QUERY`` to ``relkind = 'r'`` reds this test and nothing
    else — measured, and stated in the module docstring. The two table cases
    stay green under that mutation because a table is ``relkind 'r'`` either
    way, which is precisely why they cannot stand in for this one.

    The three ``assert``s before the gate runs are the non-vacuity half: they
    establish that the relation under test really is the dangerous shape — a
    VIEW, owned by the same role that owns ``applications``, with
    ``security_invoker`` off so it executes as that owner — and not some milder
    thing. In production that owner is ``postgres``, which holds
    ``rolbypassrls``; here it is whichever superuser the container was built
    with, so the owner is compared to the table's rather than to a literal name.

    The table underneath is untouched and stays protected. That is the trap:
    every table green and one view is exactly the state the gate used to pass.
    """

    with temporarily(
        migrated_engine,
        setup=[
            f"CREATE VIEW {BYPASS_VIEW} AS SELECT * FROM {PROTECTED_TABLE}",
            f"GRANT SELECT ON {BYPASS_VIEW} TO anon",
        ],
        teardown=[f"DROP VIEW {BYPASS_VIEW}"],
    ):
        with migrated_engine.connect() as conn:
            kind, owner, options = conn.execute(
                text(
                    "SELECT c.relkind, c.relowner, c.reloptions FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = :name"
                ),
                {"name": BYPASS_VIEW},
            ).one()
            table_owner = conn.execute(
                text(
                    "SELECT c.relowner FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = :name"
                ),
                {"name": PROTECTED_TABLE},
            ).scalar_one()

        assert kind == "v", f"{BYPASS_VIEW} is relkind {kind!r}, not a view"
        assert owner == table_owner, (
            "the view is owned by a different role than the table, so it would "
            "not execute with the table owner's privileges and this test would "
            "be measuring a milder case than the one it claims"
        )
        assert options is None, (
            f"{BYPASS_VIEW} carries reloptions {options!r}; security_invoker must "
            "be off for the view to run as its owner"
        )

        code, printed = run_gate()

    assert code == 1
    assert _errors(printed) == [
        f"{BYPASS_VIEW}: anon holds SELECT — nothing may be granted to anon on a "
        f"table holding user rows. ALTER DEFAULT PRIVILEGES can issue that grant "
        f"without it appearing in any revision, so its absence from the migration is "
        f"not evidence it is not there."
    ], "a view granted to anon is not reported — the grant query is not scanning views"


def test_a_grant_to_public_is_a_failure(migrated_engine, run_gate) -> None:
    """The widest grant Postgres has, and the one with no name to look up.

    ``aclexplode`` reports ``PUBLIC`` as grantee OID 0, and
    ``pg_get_userbyid(0)`` returns the literal string ``'unknown (OID=0)'`` —
    not NULL, not an error. So dropping the query's
    ``CASE WHEN a.grantee = 0 THEN 'PUBLIC'`` arm does not break anything
    loudly: it renames the grantee to something that is on no list, the check
    passes it, and the gate prints its green summary over a table the whole
    internet can read. Nothing on the ``collect_failures`` side can see that;
    this is the only test that can.
    """

    with temporarily(
        migrated_engine,
        setup=[f"GRANT SELECT ON {PROTECTED_TABLE} TO PUBLIC"],
        teardown=[f"REVOKE SELECT ON {PROTECTED_TABLE} FROM PUBLIC"],
    ):
        code, printed = run_gate()

    assert code == 1
    assert _errors(printed) == [
        f"{PROTECTED_TABLE}: PUBLIC holds SELECT — nothing may be granted to PUBLIC "
        f"on a table holding user rows. ALTER DEFAULT PRIVILEGES can issue that grant "
        f"without it appearing in any revision, so its absence from the migration is "
        f"not evidence it is not there."
    ], "the grantee-0 mapping is gone: a grant to PUBLIC is invisible to the gate"


def test_the_exempt_table_is_still_exempt_against_a_real_catalog(
    migrated_engine, run_gate
) -> None:
    """``alembic_version`` is the one relation the grants query does NOT filter.

    The exemption is applied in ``collect_failures`` instead, deliberately — a
    filter written in both places is unreachable in the second. That makes this
    the paired half of the ``anon`` case above: the identical grant, on the
    identical catalog, red on ``applications`` and green here. If the SQL ever
    grew its own exemption the two would stop being the same measurement.
    """

    with temporarily(
        migrated_engine,
        setup=["GRANT SELECT ON alembic_version TO anon"],
        teardown=["REVOKE SELECT ON alembic_version FROM anon"],
    ):
        code, printed = run_gate()

    assert _errors(printed) == []
    assert code == 0
