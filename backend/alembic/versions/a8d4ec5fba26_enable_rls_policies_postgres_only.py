"""enable RLS policies (postgres-only)

Revision ID: a8d4ec5fba26
Revises: 6e64c46d32fd
Create Date: 2026-04-18 21:39:34.357513

Enables PostgreSQL Row-Level Security on every tenant-scoped table and
installs per-operation policies keyed off ``auth.uid()``. Provides
defence-in-depth on top of the application-level ``user_id`` scoping
added in 6e64c46d32fd: even if a handler forgets to filter by
``user_id``, RLS rejects the query at the DB layer.

This migration is a **no-op on SQLite**. SQLite has no RLS machinery,
and the tests (desktop + cloud shim) run exclusively against SQLite, so
executing the ``CREATE POLICY`` statements under SQLite would error
immediately. We gate every statement on
``op.get_context().dialect.name == 'postgresql'`` so:

- CI (``alembic upgrade head`` under SQLite) stays green.
- Production deploy (``DIRECT_URL=postgres://... alembic upgrade head``)
  applies the policies.

Policy shape
------------

For each table ``T`` with a ``user_id UUID NOT NULL`` column:

.. code-block:: sql

    ALTER TABLE T ENABLE ROW LEVEL SECURITY;
    ALTER TABLE T FORCE ROW LEVEL SECURITY;
    CREATE POLICY T_select ON T FOR SELECT
        USING (user_id = auth.uid());
    CREATE POLICY T_insert ON T FOR INSERT
        WITH CHECK (user_id = auth.uid());
    CREATE POLICY T_update ON T FOR UPDATE
        USING (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid());
    CREATE POLICY T_delete ON T FOR DELETE
        USING (user_id = auth.uid());

``auth.uid()`` is the Supabase-provided function that returns the JWT
``sub`` claim as a UUID. The FastAPI backend talks to Supabase via the
Postgres connection pooler; the JWT ``sub`` is propagated by setting
the ``request.jwt.claims`` GUC on the connection
(``SET LOCAL request.jwt.claims = :claims``). Wiring that GUC up in
the application engine is deferred to a later cloud issue — C3 ships
the schema-level piece here so the DB cannot be misconfigured later.

Caveat
------

Enabling RLS on a table without any policies blocks all access from
non-superusers. We therefore call ENABLE + the four policies for each
table in the same transaction so the table is never in the
"RLS-on-but-no-policies" state as seen by the Supabase-role connection
that runs the migration. ``FORCE`` is also enabled so the table owner
(Supabase's postgres/service role) is subject to the same policies
when it impersonates a user — otherwise RLS is silently bypassed for
the owner, defeating the defence-in-depth goal.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a8d4ec5fba26'
down_revision: Union[str, Sequence[str], None] = '6e64c46d32fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RLS_TABLES: list[str] = [
    "applications",
    "emails",
    "contacts",
    "interviews",
    "training_data",
    "email_embeddings",
    "sync_state",
]


def _is_postgres() -> bool:
    """True when the current Alembic context targets PostgreSQL.

    Checked per-invocation (not cached) so tests that reload Alembic
    with a different URL still behave correctly.
    """

    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""

    if not _is_postgres():
        # SQLite (desktop + tests) has no RLS concept. Leaving this as
        # a silent no-op keeps ``alembic upgrade head`` usable under
        # both dialects without a branching setup in env.py.
        return

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        op.execute(
            f"""
            CREATE POLICY {table}_select ON {table}
                FOR SELECT
                USING (user_id = auth.uid())
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_insert ON {table}
                FOR INSERT
                WITH CHECK (user_id = auth.uid())
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_update ON {table}
                FOR UPDATE
                USING (user_id = auth.uid())
                WITH CHECK (user_id = auth.uid())
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_delete ON {table}
                FOR DELETE
                USING (user_id = auth.uid())
            """
        )


def downgrade() -> None:
    """Downgrade schema."""

    if not _is_postgres():
        return

    for table in RLS_TABLES:
        for policy_op in ("select", "insert", "update", "delete"):
            op.execute(
                f"DROP POLICY IF EXISTS {table}_{policy_op} ON {table}"
            )
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
