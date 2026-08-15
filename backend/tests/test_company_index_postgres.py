"""The company lookup's index, verified where the planner actually lives.

``_company_rows`` filters on ``lower(company)``, twice. Production's only
company index was ``ix_applications_company`` on the RAW column, which cannot
serve either predicate — the index stores the original bytes and ``lower()`` is
not order-preserving over them. Migration ``e7a1c4d92b30`` adds the functional
index that can.

WHY THIS MODULE HAS TO BE A POSTGRES MODULE
-------------------------------------------
Everything about this fix is a *planner* fact. SQLite has no
``text_pattern_ops``, no ``EXPLAIN`` output of this shape, and its query planner
makes different choices — a SQLite assertion here would be green regardless of
whether the production index works, which is the "check that cannot fail" shape.

WHAT IS ASSERTED, AND WHAT IS NOT
---------------------------------
NOT a speed-up. ``applications`` holds 65 live rows in production, three orders
of magnitude below where any planner prefers an index to a scan, so no honest
before/after timing exists to measure and none is claimed. What is asserted is
the property that matters before real users arrive: given a table large enough
to *want* an index, the planner **can** use this one — for BOTH predicates.

The second half is the one that would have shipped wrong. Under a non-C
collation (Supabase is ``en_US.utf8``) a DEFAULT btree cannot push
``LIKE 'prefix%'`` into an index condition. ``test_the_default_opclass_would_not_have_worked``
builds that index and proves it: same table, same query, prefix left in
``Filter``. The green assertion above it is only meaningful because that red one
holds.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

INDEX_NAME = "ix_applications_user_id_lower_company"

# Big enough that a sequential scan is genuinely the more expensive plan. At the
# production row count (65) Postgres would correctly ignore every index here,
# and a test seeded that way would assert nothing.
SEED_ROWS = 200_000

USER = uuid.UUID("3c9f1b52-7d0a-4e63-9f18-5b2c84a7e011")


def _resolve_admin_url() -> tuple[str | None, Any]:
    """Find a Postgres, starting one if that is what it takes.

    Same resolution as ``test_migrations_postgres.py`` — an explicit
    ``JOBTRACKER_TEST_PG_ADMIN_URL`` (CI's service container) wins, else a
    throwaway ``postgres:16``, else skip. A suite that runs only when a human
    exported a variable is a suite that never runs.
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
    if _OWNED_CONTAINER is not None:
        _OWNED_CONTAINER.stop()


pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason=(
        "No Postgres available: set JOBTRACKER_TEST_PG_ADMIN_URL, or run Docker "
        "so a throwaway postgres:16 can be started. Skipping leaves the "
        "lower(company) index UNVERIFIED — the SQLite suites have no "
        "text_pattern_ops and no comparable planner, so nothing else in this "
        "repo can see whether it works."
    ),
)


def _sync_url() -> str:
    return (
        make_url(ADMIN_URL)
        .set(drivername="postgresql+psycopg")
        .render_as_string(hide_password=False)
    )


@pytest.fixture(scope="module")
def seeded_engine():
    """A migrated database with a table large enough to prefer an index.

    The schema comes from ``alembic upgrade head`` — the real chain, in a
    subprocess, exactly as ``test_migrations_postgres.py`` runs it — so this
    tests the index the migration actually creates rather than one the test
    typed out itself. That distinction is the whole point: a hand-written
    ``CREATE INDEX`` here would stay green if the migration were deleted.
    """

    url = _sync_url()
    engine = create_engine(url, future=True)

    # The RLS migrations create policies over ``auth.uid()``, which Postgres
    # resolves at policy-creation time, so the chain cannot apply to a database
    # with no ``auth`` schema. Production gets it from Supabase; provide the
    # same two objects, as test_migrations_postgres.py does.
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS auth.users (id uuid primary key)"))
        conn.execute(
            text("INSERT INTO auth.users(id) VALUES (:a) ON CONFLICT DO NOTHING"),
            {"a": USER},
        )
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid "
                "LANGUAGE sql STABLE AS $$ SELECT NULLIF("
                "current_setting('request.jwt.claims', true)::json->>'sub', "
                "'')::uuid $$"
            )
        )

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
        # RLS is FORCEd on applications by the chain; the seeding role must not
        # be blocked by a policy that has no JWT to evaluate.
        conn.execute(text("ALTER TABLE applications DISABLE ROW LEVEL SECURITY"))
        conn.execute(
            text(
                # Company names spread over 9,000 distinct leading words, so a
                # prefix is SELECTIVE. This matters: seeded with one repeated
                # name, `LIKE 'company%'` matches every row and a sequential
                # scan is genuinely the cheaper plan — the test would then be
                # measuring the planner being right, not the index being
                # unusable.
                "INSERT INTO applications "
                "(user_id, company, position, status, source, created_at, updated_at) "
                "SELECT :uid, 'Corp' || (i % 9000) || ' Holdings', 'Engineer', "
                "'APPLIED', 'gmail', now(), now() "
                "FROM generate_series(1, :n) AS i"
            ),
            {"uid": USER, "n": SEED_ROWS},
        )
        conn.execute(text("ANALYZE applications"))

    yield engine
    engine.dispose()


def _plan(engine, sql: str) -> str:
    with engine.connect() as conn:
        return "\n".join(
            r[0] for r in conn.execute(text(f"EXPLAIN (COSTS OFF) {sql}"), {"uid": USER})
        )


# The two predicates _company_rows issues. Kept as literals rather than built
# from the ORM so a refactor of the helper cannot quietly change what is being
# measured.
#
# ``company`` is VARCHAR, so Postgres renders the expression as
# ``lower((company)::text)`` in both the index definition and every plan —
# hence EXPR below rather than a bare "lower(company)" in the assertions.
EXPR = "lower((company)::text)"

EQUALITY = (
    "SELECT * FROM applications "
    "WHERE user_id = :uid AND lower(company) = 'corp42 holdings'"
)
PREFIX = (
    "SELECT * FROM applications "
    "WHERE user_id = :uid AND lower(company) LIKE 'corp8123' || '%'"
)


def test_the_migration_creates_the_functional_index(seeded_engine):
    """It exists, on the expression and opclass the fix depends on."""

    with seeded_engine.connect() as conn:
        ddl = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
            {"n": INDEX_NAME},
        ).scalar()

    assert ddl is not None, f"{INDEX_NAME} was not created by the chain"
    assert EXPR in ddl.lower()
    assert "text_pattern_ops" in ddl.lower(), (
        "the index exists but in the DEFAULT operator class, which cannot serve "
        f"a prefix LIKE under a non-C collation: {ddl}"
    )


def test_the_planner_uses_it_for_the_equality_predicate(seeded_engine):
    plan = _plan(seeded_engine, EQUALITY)

    assert INDEX_NAME in plan, f"equality fell back to a scan:\n{plan}"
    assert "Seq Scan" not in plan, plan
    assert f"{EXPR} = " in plan.lower(), (
        f"the index was touched but lower(company) is not an Index Cond:\n{plan}"
    )


def test_the_planner_uses_it_for_the_prefix_predicate(seeded_engine):
    """The half that needs ``text_pattern_ops``.

    Asserting only "the index appears in the plan" would pass for the broken
    default-opclass index too — it gets used for the ``user_id`` column alone
    while the prefix stays a Filter. So the assertion is on the RANGE operators
    a pattern-opclass index scan emits (``~>=~`` / ``~<~``), which is what
    "the prefix is an index condition" actually looks like.
    """

    plan = _plan(seeded_engine, PREFIX)

    assert INDEX_NAME in plan, f"prefix fell back to a scan:\n{plan}"
    assert "~>=~" in plan and "~<~" in plan, (
        "the prefix is not an index condition — it is being re-checked as a "
        f"Filter over every row of the user:\n{plan}"
    )


def test_the_default_opclass_would_not_have_worked(seeded_engine):
    """PROVE THE INSTRUMENT — and the design decision behind the migration.

    Builds the index the obvious way (default operator class) and shows the
    prefix predicate is NOT pushed into it. Without this, the green test above
    is just an assertion that some index exists, and the ``text_pattern_ops``
    in the migration reads as superstition.
    """

    naive = "ix_applications_default_opclass_probe"
    with seeded_engine.begin() as conn:
        # Drop the real index for the duration so the planner has only the
        # naive one to choose from — otherwise it simply picks the good one and
        # the test proves nothing.
        conn.execute(text(f"DROP INDEX IF EXISTS {INDEX_NAME}"))
        conn.execute(
            text(f"CREATE INDEX {naive} ON applications (user_id, lower(company))")
        )
        conn.execute(text("ANALYZE applications"))
    try:
        plan = _plan(seeded_engine, PREFIX)
        assert "~>=~" not in plan, (
            "the default opclass DID serve the prefix — this database's "
            f"collation is not the production one, so the gate is void:\n{plan}"
        )
        # However the planner copes without a usable prefix range — a seq scan
        # here, a user_id-only bitmap scan on a board with several users — the
        # predicate lands in a re-check Filter rather than an index condition.
        assert "Filter:" in plan and f"{EXPR} ~~" in plan, (
            f"expected the prefix to be left as a re-check Filter:\n{plan}"
        )
    finally:
        with seeded_engine.begin() as conn:
            conn.execute(text(f"DROP INDEX IF EXISTS {naive}"))
            conn.execute(
                text(
                    f"CREATE INDEX {INDEX_NAME} ON applications "
                    "(user_id, lower(company) text_pattern_ops)"
                )
            )
            conn.execute(text("ANALYZE applications"))


def test_the_collation_is_the_production_one(seeded_engine):
    """The whole opclass argument is collation-dependent; pin the assumption.

    If this database were ``C``, a default btree WOULD serve the prefix and
    every conclusion above would be an artefact of the fixture rather than a
    fact about production.
    """

    with seeded_engine.connect() as conn:
        collation = conn.execute(
            text(
                "SELECT datcollate FROM pg_database WHERE datname = current_database()"
            )
        ).scalar()

    assert collation and not collation.startswith("C"), (
        f"test database collation is {collation!r}; production (Supabase) is "
        "en_US.utf8 and this suite's conclusions do not transfer"
    )
