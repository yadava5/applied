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

So this module asserts, on Postgres 17 under CI (`rls-postgres` runs this
file against `image: postgres:17`) and on Postgres 16 locally (the
testcontainers default below, deliberately unchanged):

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
from tests.pg_support import register_owned_container

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# The revision under test, and its parent — named so a rename of the file
# cannot silently turn the downgrade test into a test of some other revision.
ASSESSMENT_REVISION = "b9e42f7c10ad"
PARENT_REVISION = "b7c31e0d94aa"

# The enrollment revision and its parent, named for the same reason: the
# backfill test below must keep testing THIS revision after later ones land.
ENROLLMENT_REVISION = "e2b6f0a4d517"
ENROLLMENT_PARENT = "a9d3e5f2c841"

# The disposition revision and its parent. It CREATES a type rather than adding
# a label to one, which is a different Postgres-only hazard and has its own
# section at the bottom of this file.
DISPOSITION_REVISION = "b3e91c47da05"
DISPOSITION_PARENT = ENROLLMENT_REVISION


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

_STOP_OWNED_CONTAINER = (
    register_owned_container(_OWNED_CONTAINER)
    if _OWNED_CONTAINER is not None
    else (lambda: None)
)


def teardown_module(module) -> None:  # noqa: ANN001 - pytest hook signature
    """Release the container promptly; ``atexit`` covers the runs that skip here.

    ``teardown_module`` fires only once pytest has *executed* a test in this
    module, and the container is started at import. ``register_owned_container``
    is what covers ``--collect-only``, a ``-k`` that deselects everything, and
    an ``-x`` abort — see ``tests/pg_support.py`` for the measurement.
    """

    _STOP_OWNED_CONTAINER()


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


def _script_head() -> str:
    """The head of the revision chain, READ rather than pinned.

    This used to be the literal ``ASSESSMENT_REVISION``, which made "the chain
    applied in one invocation" a statement that had to be edited by hand every
    time a revision was added — and it duly went red on the first one after it
    (``c2e7f4a91b83``), reporting a moved head as a broken migration. The
    revision under test is still named, above; what is derived here is only
    "where the chain ends", which is the thing the assertion is actually about.

    ``Config`` is constructed but never run: ``fileConfig(alembic.ini)`` lives in
    ``env.py``, which ``ScriptDirectory`` does not import. So this keeps the
    module's no-in-process-Alembic rule intact (see :func:`_alembic`) — it reads
    the version files, it does not execute a migration.
    """

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None, "the revision chain has no head"
    return head


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

    Every later revision rides on this too: a chain that stops part-way leaves
    ``alembic_version`` short of the head, whatever the newest revision happens
    to be.
    """

    with migrated.connect() as c:
        assert c.execute(
            text("SELECT to_regclass('public.applications')")
        ).scalar_one() is not None
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == _script_head()
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

    # Downgrade to the NAMED parent rather than ``-1``. Relative steps assume
    # the revision under test is head, which stopped being true the moment a
    # revision was added after it; an explicit target keeps this a test of
    # ``b9e42f7c10ad``'s downgrade for good, which is what the constants at the
    # top of this file exist to guarantee.
    _alembic("downgrade", PARENT_REVISION)

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


# =============================================================================
# e2b6f0a4d517: the enrollment backfill has to actually move rows
# =============================================================================


def test_the_enrollment_backfill_carries_the_existing_gmail_users_across(
    engine: Engine,
) -> None:
    """Users who linked Gmail BEFORE this revision must be enrolled by it.

    This is the assertion the revision turns on. ``upgrade head`` exits 0
    whether or not the backfill found anything, and a green migration over an
    empty ``gmail_sync_enrollment`` leaves the scheduled sync with nobody to
    sync — the original bug (issue #291) wearing a new mask. Nothing else in
    the repo can catch that: SQLite has no ``user_credentials`` rows to carry
    across, and the RLS suite builds its schema from ``SQLModel.metadata``
    rather than by running the chain.

    So this stops at the revision's PARENT, writes credentials the way the
    world already looks, and then applies exactly one revision.

    The iCloud row is the non-vacuity half. Without it, "everyone in
    ``user_credentials`` ends up enrolled" and "everyone with a *Gmail*
    credential ends up enrolled" are the same sentence, and the
    ``WHERE kind = 'gmail_oauth'`` predicate would be untested.
    """

    gmail_user = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    icloud_user = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

    _alembic("upgrade", ENROLLMENT_PARENT)

    with engine.begin() as c:
        assert (
            c.execute(text("SELECT to_regclass('public.gmail_sync_enrollment')")).scalar()
            is None
        ), "the table exists before its own revision ran — this is measuring nothing"
        c.execute(
            text("INSERT INTO auth.users(id) VALUES (:g),(:i) ON CONFLICT DO NOTHING"),
            {"g": str(gmail_user), "i": str(icloud_user)},
        )
        # Raw SQL deliberately: the point is to reproduce the rows that are in
        # production TODAY, under the parent revision's schema — not to exercise
        # the writer, which ``test_rls_postgres.py`` drives instead.
        c.execute(
            text(
                "INSERT INTO user_credentials "
                "(user_id, kind, ciphertext, nonce, key_id, created_at, updated_at) "
                "VALUES (:g, 'gmail_oauth', '\\x00'::bytea, ''::bytea, 'v1', now(), now()), "
                "       (:i, 'icloud_mail', '\\x00'::bytea, ''::bytea, 'v1', now(), now())"
            ),
            {"g": str(gmail_user), "i": str(icloud_user)},
        )

    _alembic("upgrade", ENROLLMENT_REVISION)

    with engine.connect() as c:
        enrolled = [
            row[0]
            for row in c.execute(
                text("SELECT user_id FROM gmail_sync_enrollment ORDER BY user_id")
            )
        ]
        enrolled_at_is_set = c.execute(
            text("SELECT bool_and(enrolled_at IS NOT NULL) FROM gmail_sync_enrollment")
        ).scalar()

    assert enrolled == [gmail_user], (
        f"the backfill enrolled {enrolled}. It must carry across exactly the "
        "users holding a 'gmail_oauth' credential — an empty result means the "
        "cron syncs nobody, and including the iCloud user means the kind "
        "predicate is not doing its job."
    )
    assert enrolled_at_is_set is True


def test_the_enumeration_policy_is_role_scoped_and_the_grant_is_narrow(
    migrated: Engine,
) -> None:
    """The shape of the deliberate exposure, read back out of the catalog.

    ``e2b6f0a4d517`` states plainly what it exposes: a ``jobtracker_app``
    connection can enumerate which user_ids have linked Gmail. This asserts the
    exposure is exactly that and no wider — the permissive predicate applies to
    SELECT only, to one named role only, and the role holds no UPDATE privilege
    on the table.

    ``tests/test_rls_postgres.py`` proves the policy BEHAVES; this proves the
    migration WROTE it, which are different failures. That suite's harness
    writes its own policies, so a migration that quietly stopped naming the
    role would leave it green while production shipped a policy for every role.
    """

    with migrated.connect() as c:
        policies = {
            row[0]: (row[1], row[2], row[3])
            for row in c.execute(
                text(
                    "SELECT policyname, cmd, roles::text, qual "
                    "FROM pg_policies WHERE tablename = 'gmail_sync_enrollment'"
                )
            )
        }
        privileges = {
            row[0]
            for row in c.execute(
                text(
                    "SELECT privilege_type FROM information_schema.table_privileges "
                    "WHERE table_name = 'gmail_sync_enrollment' "
                    "AND grantee = 'jobtracker_app'"
                )
            )
        }

    assert set(policies) == {
        "gmail_sync_enrollment_enumerate",
        "gmail_sync_enrollment_owner_insert",
        "gmail_sync_enrollment_owner_delete",
    }, f"unexpected policy set: {sorted(policies)}"

    cmd, roles, qual = policies["gmail_sync_enrollment_enumerate"]
    assert cmd == "SELECT", f"the permissive policy covers {cmd}, not just SELECT"
    assert roles == "{jobtracker_app}", (
        f"the enumeration policy is granted to {roles}. Scoping it to one role "
        "is what makes a future GRANT SELECT to another role still default-deny."
    )
    assert qual == "true", f"the enumeration predicate is {qual!r}, expected 'true'"

    # Owner-scoped writes, and no UPDATE anywhere: enrollment is join-or-leave.
    assert policies["gmail_sync_enrollment_owner_insert"][0] == "INSERT"
    assert policies["gmail_sync_enrollment_owner_delete"][0] == "DELETE"
    assert privileges == {"SELECT", "INSERT", "DELETE"}, (
        f"jobtracker_app holds {sorted(privileges)} on gmail_sync_enrollment. "
        "Nothing updates this table; UPDATE must not be granted."
    )


# =============================================================================
# b3e91c47da05 — a type CREATED, and a backfill written INTO it
#
# `b9e42f7c10ad` above is about adding a label to a type that exists. This is
# the other half: a revision that creates its own type and then writes to the
# column in the same breath. SQLite renders `sa.Enum` as VARCHAR and accepts a
# bare string, so the whole hazard is invisible to every other suite — the
# first draft of this revision shipped
#
#     UPDATE emails SET review_disposition = $1::VARCHAR
#
# which is green on SQLite and, on Postgres:
#
#     DatatypeMismatch: column "review_disposition" is of type
#     reviewdisposition but expression is of type character varying
#
# i.e. `alembic upgrade head` on merge to main, against production, failing at
# the statement AFTER the column was added.
# =============================================================================


def _insert_settled_email(engine: Engine, message_id: str, corrected: bool) -> None:
    """One `emails` row as production holds it, before the column exists.

    Raw SQL on purpose, and it is the opposite of the reasoning on
    `_insert_application`: the point here is a row written by the OLD code, so
    it must not go through a model that already knows about the new column.
    """

    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO emails (user_id, source_account, message_id, "
                " received_at, classified_as, user_corrected, is_reviewed, created_at) "
                "VALUES (:u, 'GMAIL', :m, :t, 'REJECTION', :corr, :corr, :t)"
            ),
            {
                "u": str(OWNER),
                "m": message_id,
                "t": datetime(2026, 8, 11, 9, 0),
                "corr": corrected,
            },
        )


def test_the_review_disposition_labels_are_the_python_enum_names_in_order(
    migrated: Engine,
) -> None:
    """A created type is subject to the same uppercase rule as an altered one.

    SQLAlchemy persists an enum's NAME, so the type must hold ``'CONFIRMED'``
    while the API speaks ``"confirmed"``. Getting this backwards is valid DDL
    and then 500s on the first write — the failure ``b9e42f7c10ad`` is written
    about, reached by a different route.
    """

    from jobtracker.database.models import ReviewDisposition

    labels = _enum_labels(migrated, "reviewdisposition")

    assert labels == [d.name for d in ReviewDisposition]
    # The API's spelling is NOT a label.
    assert "confirmed" not in labels


def test_the_backfill_writes_unknown_through_the_enum_type(engine: Engine) -> None:
    """The statement that was broken, run against the dialect it was broken on.

    Walks to the revision BEFORE the column exists, writes the two shapes
    production holds, and upgrades — so it measures the migration rather than
    the model, and it is the only place in the repo where the bind type of that
    UPDATE is exercised at all.

    Mutation: declaring the table construct's column ``sa.String()`` instead of
    the enum type → ``DatatypeMismatch`` and a non-zero ``alembic upgrade``,
    which is what the first draft did.
    """

    _alembic("upgrade", DISPOSITION_PARENT)

    with engine.connect() as c:
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == DISPOSITION_PARENT
        )
        assert not c.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'emails' "
                "AND column_name = 'review_disposition'"
            )
        ).all(), "the column must not exist yet, or this test proves nothing"

    _insert_settled_email(engine, "pg-legacy-corrected", corrected=True)
    _insert_settled_email(engine, "pg-legacy-untouched", corrected=False)

    _alembic("upgrade", DISPOSITION_REVISION)

    with engine.connect() as c:
        rows = dict(
            c.execute(
                text("SELECT message_id, review_disposition::text FROM emails")
            ).all()
        )

    # A human decided; which act it was is not recoverable. Not "confirmed",
    # not "overridden", and not NULL — NULL already means something else.
    assert rows["pg-legacy-corrected"] == "UNKNOWN"
    assert rows["pg-legacy-untouched"] is None


def test_the_disposition_downgrade_takes_the_type_with_it(migrated: Engine) -> None:
    """A created type must be dropped, or the next upgrade collides on it.

    ``b9e42f7c10ad``'s downgrade deliberately leaves its LABEL behind because
    Postgres has no ``DROP VALUE``. A whole type is different: it can be
    dropped, it has exactly one dependent column, and leaving it would make
    ``CREATE TYPE`` fail the second time the chain ran.
    """

    assert "reviewdisposition" in _all_type_names(migrated)

    _alembic("downgrade", DISPOSITION_PARENT)

    assert "reviewdisposition" not in _all_type_names(migrated)

    # And the chain is re-runnable, which is the property the drop exists for.
    _alembic("upgrade", "head")
    assert "reviewdisposition" in _all_type_names(migrated)


def _all_type_names(engine: Engine) -> set[str]:
    """Every enum type name in the database."""

    with engine.connect() as c:
        return {
            row[0]
            for row in c.execute(
                text("SELECT typname FROM pg_type WHERE typtype = 'e'")
            )
        }
