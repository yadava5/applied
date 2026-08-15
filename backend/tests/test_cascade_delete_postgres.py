"""Deleting a parent must not be able to leave unreachable orphans.

``DELETE /account`` and ``DELETE /applications/{id}`` both purge children in
application code, children-before-parents, because the four cross-entity
foreign keys were NO ACTION. That works when it completes. What it does not
survive is a PARTIAL failure — a serverless function killed on its 60 s
ceiling, or a dropped connection, part way through the ordered sequence.

The orphans that leaves are not merely untidy, they are UNREACHABLE. RLS is
FORCEd on every one of these tables on ``user_id = auth.uid()``, and the web
layer removes the Supabase auth user immediately after ``DELETE /account``
returns — so nothing can ever select those rows again while they keep counting
against the 500 MB free tier.

WHY POSTGRES. SQLite does not enforce foreign keys at all unless a
per-connection ``PRAGMA foreign_keys=ON`` is set, and it cannot ALTER a
constraint. A cascade assertion on SQLite would be green whether or not the
production DDL was ever applied — the exact "check that cannot fail" shape this
repo keeps finding. The migration is Postgres-only and so is its gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from tests.pg_support import reset_public_schema, resolve_admin_url, sync_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

USER = uuid.UUID("7b3e9d24-1c58-4a06-9f37-2e845b6c0d19")

# (table, constraint) — the four keys a9d3e5f2c841 re-declares.
CASCADING = (
    ("contacts", "contacts_application_id_fkey"),
    ("emails", "emails_application_id_fkey"),
    ("interviews", "interviews_application_id_fkey"),
    ("email_embeddings", "email_embeddings_email_id_fkey"),
)


ADMIN_URL, _OWNED_CONTAINER = resolve_admin_url()

# Shared with ``test_company_index_postgres`` — see tests/pg_support.py for why
# there is no teardown stopping it here.

pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason=(
        "No Postgres available: set JOBTRACKER_TEST_PG_ADMIN_URL, or run Docker "
        "so a throwaway postgres:16 can be started. Skipping leaves the CASCADE "
        "keys UNVERIFIED — SQLite enforces no foreign keys here and would report "
        "this green either way."
    ),
)


@pytest.fixture(scope="module")
def migrated_engine():
    """A database built by the real chain, so this tests the migration's DDL."""

    url = sync_url(ADMIN_URL)
    engine = create_engine(url, future=True)

    # Take the schema for this module — see tests/pg_support.py.
    reset_public_schema(engine, owner_ids=(USER,))

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
        for table in (
            "applications",
            "emails",
            "contacts",
            "interviews",
            "email_embeddings",
        ):
            conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    yield engine
    engine.dispose()


@pytest.mark.parametrize("table,constraint", CASCADING)
def test_the_key_is_declared_on_delete_cascade(migrated_engine, table, constraint):
    """Read from the catalogue, by the name the migration actually used."""

    with migrated_engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
            {"n": constraint},
        ).scalar()

    assert definition is not None, f"{constraint} does not exist on {table}"
    assert "ON DELETE CASCADE" in definition, (
        f"{constraint} is still {definition!r} — a partial purge can orphan "
        f"{table} rows that RLS then makes permanently unreachable"
    )


def test_the_constraint_names_are_the_real_ones(migrated_engine):
    """Guard against a migration that silently created a SECOND key.

    ``drop_constraint`` + ``create_foreign_key`` on a name that never existed
    would fail loudly — but a name that existed under a different spelling
    could leave the original NO ACTION key in place beside the new one, and
    every assertion above would still pass. So: exactly one FK per column.
    """

    insp = inspect(migrated_engine)
    for table, constraint in CASCADING:
        keys = insp.get_foreign_keys(table)
        assert len(keys) == 1, f"{table} has {len(keys)} foreign keys: {keys}"
        assert keys[0]["name"] == constraint


def test_deleting_an_application_takes_its_children_with_it(migrated_engine):
    """END TO END, at the database. The parent goes; nothing is left behind.

    This is the interrupted-purge case: the parent row is deleted WITHOUT the
    application first deleting the children, which is exactly the state a
    function killed mid-sequence produces.
    """

    with migrated_engine.begin() as conn:
        app_id = conn.execute(
            text(
                "INSERT INTO applications "
                "(user_id, company, position, status, source, created_at, updated_at) "
                "VALUES (:u, 'Acme', 'Engineer', 'APPLIED', 'gmail', now(), now()) "
                "RETURNING id"
            ),
            {"u": USER},
        ).scalar()
        email_id = conn.execute(
            text(
                "INSERT INTO emails "
                "(user_id, application_id, source_account, message_id, subject, "
                " received_at, created_at, user_corrected, is_reviewed) "
                # 'GMAIL', not 'gmail': SQLModel/SQLAlchemy persist an enum's
                # NAME, so the Postgres type's labels are the upper-case ones.
                # The same trap test_migrations_postgres.py exists for.
                "VALUES (:u, :a, 'GMAIL', 'msg-cascade-1', 'Hi', now(), now(), "
                "false, false) "
                "RETURNING id"
            ),
            {"u": USER, "a": app_id},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO contacts (user_id, application_id, email, created_at) "
                "VALUES (:u, :a, 'recruiter@acme.example', now())"
            ),
            {"u": USER, "a": app_id},
        )
        conn.execute(
            text(
                "INSERT INTO interviews "
                "(user_id, application_id, status, created_at) "
                "VALUES (:u, :a, 'SCHEDULED', now())"
            ),
            {"u": USER, "a": app_id},
        )
        conn.execute(
            text(
                "INSERT INTO email_embeddings "
                "(user_id, email_id, label, model_version, created_at) "
                "VALUES (:u, :e, 'applied', 'v1', now())"
            ),
            {"u": USER, "e": email_id},
        )

    def _counts(conn):
        return {
            "emails": conn.execute(
                text("SELECT count(*) FROM emails WHERE application_id = :a"),
                {"a": app_id},
            ).scalar(),
            "contacts": conn.execute(
                text("SELECT count(*) FROM contacts WHERE application_id = :a"),
                {"a": app_id},
            ).scalar(),
            "interviews": conn.execute(
                text("SELECT count(*) FROM interviews WHERE application_id = :a"),
                {"a": app_id},
            ).scalar(),
            "embeddings": conn.execute(
                text("SELECT count(*) FROM email_embeddings WHERE email_id = :e"),
                {"e": email_id},
            ).scalar(),
        }

    # NON-VACUITY: the children must genuinely exist before the delete, or
    # "they are all gone afterwards" is trivially true.
    with migrated_engine.connect() as conn:
        assert _counts(conn) == {
            "emails": 1,
            "contacts": 1,
            "interviews": 1,
            "embeddings": 1,
        }

    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM applications WHERE id = :a"), {"a": app_id})

    with migrated_engine.connect() as conn:
        assert _counts(conn) == {
            "emails": 0,
            "contacts": 0,
            "interviews": 0,
            # Two hops: applications -> emails -> email_embeddings. The second
            # cascade only fires because the first one deleted the email.
            "embeddings": 0,
        }
