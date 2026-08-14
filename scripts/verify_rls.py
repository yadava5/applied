#!/usr/bin/env python3
"""Assert that row-level security still protects every table holding user data.

Run after a migration, against the database it was applied to::

    DIRECT_URL="postgresql://..." python scripts/verify_rls.py

Exit 0 = protected. Exit 1 = something is not, and it says which.

WHY THIS EXISTS
---------------
The migration workflow connects as the migration role, which is BYPASSRLS by
necessity: DDL requires it, and ``b9e42f7c10ad``'s downgrade documents that a
non-BYPASSRLS role would silently remap zero rows and report success. So the
runner is an unattended process that *can* weaken tenant isolation, and nothing
else would notice — ``alembic upgrade head`` exits 0 whether or not the schema
it produced still protects anyone.

Applied's public claim is that tenant isolation is enforced at the database
layer. ``tests/test_rls_postgres.py`` proves the policies work, but it proves it
against a database the test itself built. This proves it against the one real
users' rows are in.

WHY THE INVARIANT IS STRUCTURAL, NOT A COUNT
--------------------------------------------
"32 policies across 8 tables" is the state today, and asserting those numbers
would make adding a ninth table fail until someone bumped a constant — which
trains people to bump the constant. Worse, it would pass a table that has RLS
enabled and zero policies.

So: EVERY base table in ``public`` except ``alembic_version`` must have RLS
ENABLED and FORCED and carry at least one policy. A table added without RLS
fails here rather than leaking, and no number needs maintaining.

``alembic_version`` is the sole exemption and it is deliberate: it holds one row
of schema metadata, no user data, and the runtime role reads it directly for
``GET /health/schema``.
"""

from __future__ import annotations

import os
import sys

import psycopg

# The role the API itself connects as. RLS constrains roles, so a policy set is
# only as strong as this role's inability to bypass it.
RUNTIME_ROLE = "jobtracker_app"

# Holds schema metadata, not user data. See the module docstring.
EXEMPT_TABLES = ("alembic_version",)


def _plain_url(url: str) -> str:
    """Strip a SQLAlchemy driver suffix; psycopg wants a bare libpq URL."""

    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def main() -> int:
    url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("::error::Neither DIRECT_URL nor DATABASE_URL is set.")
        return 1

    exempt = tuple(EXEMPT_TABLES)
    failures: list[str] = []

    with psycopg.connect(_plain_url(url), connect_timeout=15) as conn:
        unprotected = conn.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND NOT (c.relname = ANY(%s))
              AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
            ORDER BY c.relname
            """,
            (list(exempt),),
        ).fetchall()

        policyless = conn.execute(
            """
            SELECT c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND NOT (c.relname = ANY(%s))
              AND NOT EXISTS (
                    SELECT 1 FROM pg_policies p
                    WHERE p.schemaname = 'public' AND p.tablename = c.relname)
            ORDER BY c.relname
            """,
            (list(exempt),),
        ).fetchall()

        role = conn.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = %s", (RUNTIME_ROLE,)
        ).fetchone()

        tables, policies = conn.execute(
            """
            SELECT (SELECT count(*) FROM pg_class c
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = 'public' AND c.relkind = 'r'
                       AND NOT (c.relname = ANY(%s))),
                   (SELECT count(*) FROM pg_policies WHERE schemaname = 'public')
            """,
            (list(exempt),),
        ).fetchone()

    for name, enabled, forced in unprotected:
        failures.append(
            f"{name}: RLS enabled={enabled} forced={forced} — both must be true. "
            f"Without FORCE, the table's owner bypasses every policy on it."
        )
    for (name,) in policyless:
        # Deliberately says nothing about whether RLS is enabled — a table can
        # land here with RLS off, and asserting "RLS is on but..." would then be
        # a false statement printed by the tool that is supposed to be the
        # authority on the question.
        failures.append(f"{name}: no row-level security policies at all.")
    if role is None:
        failures.append(
            f"role {RUNTIME_ROLE} does not exist — check what the API actually "
            f"connects as, because it is not the role these policies constrain."
        )
    elif role[0]:
        failures.append(
            f"role {RUNTIME_ROLE} has BYPASSRLS — every policy in this database "
            f"is decorative for the API's own connection."
        )

    if failures:
        for line in failures:
            print(f"::error::{line}")
        return 1

    summary = (
        f"RLS verified: {tables}/{tables} tables ENABLE+FORCE, "
        f"{policies} policies, {RUNTIME_ROLE} is NOBYPASSRLS."
    )
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write(summary + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
