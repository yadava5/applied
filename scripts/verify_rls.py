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

WHY PRIVILEGES ARE CHECKED TOO
------------------------------
Policies decide which rows a role is allowed to see. Privileges decide whether
the role reaches the table at all, and they are a separate gate — one that
nothing in CI looked at until this check existed: not this script, not the
expand-only gate, not the migration suites.

They are not merely unchecked, they are handed out. ``ALTER DEFAULT
PRIVILEGES`` is set on schema ``public`` for the role that owns every table
here, so a table a migration creates can arrive with a full privilege set for
``anon`` and ``authenticated`` without one line of the revision saying so, and
with nothing anywhere that would report it. Measured 2026-08-31 (issue #668):
no table currently carries such a grant. That is what makes this a ratchet and
not a bug report — it holds the state that already exists rather than waiting
for somebody to notice it changed.

``PUBLIC`` belongs in the same set because a grant to ``PUBLIC`` reaches
``anon`` by definition. ``aclexplode`` reports it as grantee OID 0, which
``pg_get_userbyid`` cannot turn into a name, so it is mapped by hand.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

import psycopg

# The role the API itself connects as. RLS constrains roles, so a policy set is
# only as strong as this role's inability to bypass it.
RUNTIME_ROLE = "jobtracker_app"

# Holds schema metadata, not user data. See the module docstring.
EXEMPT_TABLES = ("alembic_version",)

# Roles that must hold NO privilege on a table with user rows in it. `anon` and
# `authenticated` are PostgREST's roles: a grant to either is reachable from the
# public internet through the Supabase REST endpoint, which is a surface this
# application does not use and has never reviewed. `PUBLIC` is here because a
# grant to PUBLIC reaches both of the other two by definition.
#
# Not a list of the roles that ARE allowed, deliberately. An allowlist would go
# red the day someone adds a legitimate role and would be edited to pass, which
# is the same reflex as bumping a count; this set names the three that are wrong
# no matter what else the database grows.
FORBIDDEN_GRANTEES = ("anon", "authenticated", "PUBLIC")


def _plain_url(url: str) -> str:
    """Strip a SQLAlchemy driver suffix; psycopg wants a bare libpq URL."""

    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def collect_failures(
    unprotected: Sequence[tuple[str, bool, bool]],
    policyless: Sequence[tuple[str]],
    role: tuple[bool] | None,
    grants: Sequence[tuple[str, str, str]],
    exempt: Sequence[str] = EXEMPT_TABLES,
) -> list[str]:
    """Turn the four query results into the lines a failing run prints.

    Split out of :func:`main` so the verdict can be tested without a database.
    Every argument is exactly what psycopg hands back — ``fetchall()`` rows and
    a ``fetchone()`` row or ``None``, passed through unmassaged — so a fixture
    written against this signature is the same shape production produces. A
    tidier shape here would make the tests agree with each other rather than
    with the script.

    ``grants`` is the one query NOT narrowed by ``exempt`` in SQL. The exemption
    is applied here instead, because a filter written in both places is
    unreachable in the second one, and a test of an unreachable filter is this
    repository's named recurring defect wearing a test as a disguise.
    """

    failures: list[str] = []

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

    # One line per (table, grantee) rather than one per privilege: four rows
    # saying `anon` may do four things to one table is one fact, and printing it
    # as four failures makes a single mis-granted table look like a rout.
    held: dict[tuple[str, str], list[str]] = {}
    for table, grantee, privilege in grants:
        if table in exempt or grantee not in FORBIDDEN_GRANTEES:
            continue
        held.setdefault((table, grantee), []).append(privilege)
    for (table, grantee), privileges in sorted(held.items()):
        # sorted(), not the order the ACL happened to be built in: this text is
        # asserted on in the tests and printed into a public run log, and neither
        # wants a line that changes when nothing about the database did.
        failures.append(
            f"{table}: {grantee} holds {', '.join(sorted(privileges))} — nothing "
            f"may be granted to {grantee} on a table holding user rows. ALTER "
            f"DEFAULT PRIVILEGES can issue that grant without it appearing in any "
            f"revision, so its absence from the migration is not evidence it is "
            f"not there."
        )

    return failures


def main() -> int:
    url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("::error::Neither DIRECT_URL nor DATABASE_URL is set.")
        return 1

    exempt = tuple(EXEMPT_TABLES)

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

        # `pg_class.relacl` and not `information_schema.role_table_grants`: that
        # view shows only the grants where the current user is the grantor, the
        # grantee, or a member of the grantee role, so it can return nothing for
        # a table that is wide open and be telling the truth about what it can
        # see. `relacl` is the catalog itself and has no such horizon.
        #
        # `relacl` is NULL when nothing beyond the owner's implicit privileges
        # applies, and `aclexplode(NULL)` yields no rows, so a table with no
        # grants simply does not appear here. That is the right answer rather
        # than a gap: nothing granted is nothing to report. Every table IS
        # returned, exempt ones included — see collect_failures for why the
        # exemption is applied there and not in this WHERE clause.
        grants = conn.execute(
            """
            SELECT c.relname,
                   CASE WHEN a.grantee = 0 THEN 'PUBLIC'
                        ELSE pg_get_userbyid(a.grantee) END,
                   a.privilege_type
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN LATERAL aclexplode(c.relacl) AS a
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY 1, 2, 3
            """
        ).fetchall()

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

    failures = collect_failures(unprotected, policyless, role, grants, exempt)

    if failures:
        for line in failures:
            print(f"::error::{line}")
        return 1

    summary = (
        f"RLS verified: {tables}/{tables} tables ENABLE+FORCE, "
        f"{policies} policies, {RUNTIME_ROLE} is NOBYPASSRLS, "
        f"no {'/'.join(FORBIDDEN_GRANTEES)} privileges on any table."
    )
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write(summary + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
