"""hoist auth.uid() into an InitPlan in every RLS policy (postgres-only)

Revision ID: c6_rls_initplan_hoist
Revises: c5_force_user_creds_rls
Create Date: 2026-08-07 00:00:00.000000

Rewrites all 32 RLS policy expressions from ``user_id = auth.uid()`` to
``user_id = (SELECT auth.uid())``.

Why
---

``auth.uid()`` is declared ``STABLE``, not ``IMMUTABLE``, so when it appears
bare in a policy predicate the planner treats it as part of the per-row
qualifier and re-evaluates it **once per scanned row**. Wrapping it in a
scalar sub-select makes it an uncorrelated subquery, which the planner hoists
into an ``InitPlan`` evaluated **once per query**; the row filter then
compares against the cached parameter (``Filter: (user_id = $0)``).

This is Supabase's ``auth_rls_initplan`` linter finding, which fires on all
32 policies in production.

**This is a planning-time change only.** ``auth.uid()`` returns the same
value for every row of a given statement either way (it reads the
transaction-local ``request.jwt.claims`` GUC, which cannot change mid
statement), so the comparison — and therefore the tenant-isolation guarantee
— is bit-for-bit identical. Nothing about *which* rows are visible changes;
only how many times the function is called to decide that.

The NULL semantics are preserved too: with no user bound, the GUC is unset,
the sub-select yields NULL, and ``user_id = NULL`` is NULL rather than true,
so the policies still fail **closed**.

How
---

``ALTER POLICY``, not ``DROP`` + ``CREATE``. ALTER swaps the expression
in place inside the migration's transaction, so the policy never ceases to
exist — there is no instant, not even inside an aborted transaction, in
which a FORCE'd table is readable without a predicate.

Each policy is altered with exactly the clauses it was created with
(revisions ``a8d4ec5fba26`` and ``c4user_creds_rls``): ``USING`` for
SELECT/DELETE, ``WITH CHECK`` for INSERT, both for UPDATE. Naming ALTER
POLICY clauses a policy does not have is an error, not a no-op.

``ALTER POLICY`` has no ``IF EXISTS`` form. That is deliberate here: if a
policy name in production ever diverged from what these migrations created,
this revision aborts the whole transaction rather than silently half-applying.

Postgres-only, gated on the dialect exactly like ``a8d4ec5fba26``: SQLite
(desktop + CI, where ``tests/test_alembic.py`` runs ``alembic upgrade head``)
has no RLS machinery, so both directions are no-ops there.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c6_rls_initplan_hoist"
down_revision: Union[str, Sequence[str], None] = "c5_force_user_creds_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The seven entity tables policied in a8d4ec5fba26, in that revision's order.
RLS_TABLES: list[str] = [
    "applications",
    "emails",
    "contacts",
    "interviews",
    "training_data",
    "email_embeddings",
    "sync_state",
]

# (command, has USING, has WITH CHECK) — mirrors how the policies were created.
_SHAPES: list[tuple[str, bool, bool]] = [
    ("select", True, False),
    ("insert", False, True),
    ("update", True, True),
    ("delete", True, False),
]

# The hoisted (once-per-query) and bare (once-per-row) forms of the identity.
_HOISTED = "(SELECT auth.uid())"
_BARE = "auth.uid()"


def _policies() -> list[tuple[str, str, bool, bool]]:
    """All 32 policies as ``(policy_name, table, has_using, has_check)``.

    The entity tables use the ``{table}_{command}`` naming from
    ``a8d4ec5fba26``; ``user_credentials`` uses the ``_owner_`` infix naming
    from ``c4user_creds_rls``. Both are reproduced verbatim — ALTER POLICY
    matches on the exact name.
    """

    policies: list[tuple[str, str, bool, bool]] = [
        (f"{table}_{command}", table, has_using, has_check)
        for table in RLS_TABLES
        for command, has_using, has_check in _SHAPES
    ]
    policies += [
        (f"user_credentials_owner_{command}", "user_credentials", has_using, has_check)
        for command, has_using, has_check in _SHAPES
    ]
    return policies


def _statements(uid_expr: str) -> list[str]:
    """Build the 32 ``ALTER POLICY`` statements for a given identity expression."""

    statements: list[str] = []
    for name, table, has_using, has_check in _policies():
        clauses: list[str] = []
        if has_using:
            clauses.append(f"USING (user_id = {uid_expr})")
        if has_check:
            clauses.append(f"WITH CHECK (user_id = {uid_expr})")
        statements.append(
            f"ALTER POLICY {name} ON {table}\n    " + "\n    ".join(clauses)
        )
    return statements


def _is_postgres() -> bool:
    """True when the current Alembic context targets PostgreSQL.

    Uses ``op.get_context()`` rather than ``op.get_bind()`` to match
    ``a8d4ec5fba26``, the revision this one amends. Both work in offline
    (``--sql``) mode on this Alembic version, but the context form does not
    depend on a bind existing at all.
    """

    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Hoist ``auth.uid()`` into a sub-select so it is evaluated once per query."""

    if not _is_postgres():
        return

    for statement in _statements(_HOISTED):
        op.execute(statement)


def downgrade() -> None:
    """Restore the bare, per-row ``auth.uid()`` form."""

    if not _is_postgres():
        return

    for statement in _statements(_BARE):
        op.execute(statement)
