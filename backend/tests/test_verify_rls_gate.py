"""The verdict inside ``scripts/verify_rls.py``, without a database.

The gate itself runs once per production migration, at
``.github/workflows/db-migrate.yml:333``, against the database real users' rows
are in. It had no tests at all until this file: the only way to learn what it
says about a broken database was to break production and read the run log.

What is tested here is everything that decides the verdict once the four
catalog queries have been answered — the two RLS facts, the two role branches,
and the privilege check added for issue #668. The queries themselves still need
a Postgres and are not tested here; ``collect_failures`` is handed exactly the
rows psycopg returns, so the seam between them is a shape, not a translation.

WHY THE PRIVILEGE CHECK IS THE REASON THIS FILE EXISTS
------------------------------------------------------
``verify_rls.py`` asserted policies and asserted nothing about privileges, and
those are different gates. ``ALTER DEFAULT PRIVILEGES`` is set on schema
``public`` for the role that owns every table, so a table a migration creates
can be born with a full privilege set for ``anon`` — reachable, unauthenticated,
from the public internet through Supabase's REST endpoint — with no line of the
revision saying so and nothing in CI able to see it.

Measured on 2026-08-31, no table carries such a grant. So all three forbidden
roles get a case of their own here rather than one example standing in for the
set: the check has never fired in production and never will if it is right, and
a set whose other two members were never exercised would be two thirds of a
gate that cannot fail.

The three roles production DOES grant to — ``jobtracker_app``, ``postgres``,
``service_role`` — get a passing case for the same reason in reverse. A check
that reddens the state that exists is not a ratchet, it is an outage.

WHAT THIS FILE DELIBERATELY DOES NOT COVER
------------------------------------------
The two facts about ``aclexplode`` the query rests on — that grantee OID 0 is
``PUBLIC``, and that a ``NULL`` ``relacl`` yields no rows so an ungranted table
is simply absent — are properties of Postgres, not of this code. There is no
mutation of ``collect_failures`` that could make an assertion about them fail,
so writing one would produce a test that is green by construction, which is the
defect this repository keeps finding. Both were checked by hand against
postgres:16 when the query was written; the reasoning is in the comment above
the query in ``scripts/verify_rls.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_rls.py"


def _load() -> ModuleType:
    """Import the tool by path — it is a script, not a package module.

    Same loader as ``test_expand_only_gate.py``, ``test_test_data_gate.py`` and
    ``test_readme_facts_writer.py``, registered in ``sys.modules`` before exec
    for the reason stated there.

    Unlike ``check_expand_only.py``, this script imports psycopg at module
    scope, so loading it needs psycopg present. It is — ``psycopg[binary]`` is
    in ``backend/requirements-dev.txt``, which is what the ``test`` job installs.
    """

    spec = importlib.util.spec_from_file_location("verify_rls", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load()


# =============================================================================
# Row shapes
# =============================================================================
#
# These are psycopg's shapes, not convenient ones. `policyless` rows are
# one-tuples because production reads them with `for (name,) in policyless:`,
# and `role` is a one-tuple or None because it comes from `fetchone()`. A
# friendlier fixture would make these tests agree with each other instead of
# with the script, which is the whole failure this file is meant to rule out.

CLEAN_ROLE: tuple[bool] = (False,)


def grant(table: str, grantee: str, *privileges: str) -> list[tuple[str, str, str]]:
    """The rows ``aclexplode`` produces for one role's privileges on one table.

    One row per privilege — that is how the catalog reports it, and collapsing
    them here would hide the grouping the gate has to do.
    """

    return [(table, grantee, privilege) for privilege in privileges]


# The full owner set Postgres materialises for `postgres` the moment any grant
# is made on a table, measured against postgres:16. Present in every production
# row set, and it must never contribute a failure.
OWNER_GRANTS = grant(
    "applications",
    "postgres",
    "DELETE",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "TRIGGER",
    "TRUNCATE",
    "UPDATE",
)


def verdict(
    unprotected: Sequence[tuple[str, bool, bool]] = (),
    policyless: Sequence[tuple[str]] = (),
    role: tuple[bool] | None = CLEAN_ROLE,
    grants: Sequence[tuple[str, str, str]] = (),
) -> list[str]:
    """Ask the gate for its verdict, defaulting every check to its clean state."""

    result: list[str] = verifier.collect_failures(unprotected, policyless, role, grants)
    return result


# =============================================================================
# The privilege check — one case per member of the forbidden set (#668)
# =============================================================================


def test_a_grant_to_anon_is_a_failure() -> None:
    """The role the whole check exists for: unauthenticated, internet-facing."""

    assert verdict(grants=grant("applications", "anon", "SELECT")) == [
        "applications: anon holds SELECT — nothing may be granted to anon on a table "
        "holding user rows. ALTER DEFAULT PRIVILEGES can issue that grant without it "
        "appearing in any revision, so its absence from the migration is not evidence "
        "it is not there."
    ]


def test_a_grant_to_authenticated_is_a_failure() -> None:
    """Not a milder case than ``anon``.

    ``authenticated`` is any holder of a valid Supabase JWT, including one
    issued to a different tenant. Applied's policies are written for
    ``jobtracker_app``; a table reachable as ``authenticated`` is reachable by a
    role those policies were never written against.
    """

    assert verdict(grants=grant("emails", "authenticated", "UPDATE")) == [
        "emails: authenticated holds UPDATE — nothing may be granted to authenticated "
        "on a table holding user rows. ALTER DEFAULT PRIVILEGES can issue that grant "
        "without it appearing in any revision, so its absence from the migration is "
        "not evidence it is not there."
    ]


def test_a_grant_to_public_is_a_failure() -> None:
    """``PUBLIC`` is grantee OID 0 and has no name to look up.

    ``pg_get_userbyid(0)`` does not return anything usable, so the query maps
    the zero by hand. This case holds that mapping: if it were dropped, the
    widest possible grant in Postgres would be the one grant the gate could not
    see.
    """

    assert verdict(grants=grant("gmail_credentials", "PUBLIC", "SELECT")) == [
        "gmail_credentials: PUBLIC holds SELECT — nothing may be granted to PUBLIC on "
        "a table holding user rows. ALTER DEFAULT PRIVILEGES can issue that grant "
        "without it appearing in any revision, so its absence from the migration is "
        "not evidence it is not there."
    ]


def test_the_roles_production_actually_grants_to_are_not_a_failure() -> None:
    """The measured state of all ten tables on 2026-08-31, and it must be green.

    ``jobtracker_app`` holds DELETE/INSERT/SELECT/UPDATE, ``postgres`` owns
    everything, and ``service_role`` is Supabase's. Reddening this is not a
    stricter gate, it is a failed production migration on the next merge.
    """

    grants = (
        grant("applications", "jobtracker_app", "DELETE", "INSERT", "SELECT", "UPDATE")
        + OWNER_GRANTS
        + grant("applications", "service_role", "DELETE", "INSERT", "SELECT", "UPDATE")
    )

    assert verdict(grants=grants) == []


def test_the_exempt_table_is_exempt_from_the_privilege_check_too() -> None:
    """``alembic_version`` is excluded here as it is from the other three.

    It is the one table the grants query does NOT filter out in SQL, because the
    exemption lives in ``collect_failures`` where a test can reach it. This is
    that test: the same grant that fails on a real table passes on this one.
    """

    assert verdict(grants=grant("alembic_version", "anon", "SELECT")) == []


def test_every_privilege_one_role_holds_is_one_line_in_a_stable_order() -> None:
    """Four privileges on one table is one fact, printed once, sorted.

    Reporting each privilege separately would make a single mis-granted table
    look like a rout, and leaving the order to the ACL would make the text of a
    public run log change when nothing about the database had.
    """

    grants = grant("emails", "anon", "SELECT", "DELETE", "UPDATE", "INSERT")

    assert verdict(grants=grants) == [
        "emails: anon holds DELETE, INSERT, SELECT, UPDATE — nothing may be granted to "
        "anon on a table holding user rows. ALTER DEFAULT PRIVILEGES can issue that "
        "grant without it appearing in any revision, so its absence from the migration "
        "is not evidence it is not there."
    ]


# =============================================================================
# The three checks that were already here, saying exactly what they said before
# =============================================================================
#
# Asserted as whole strings, not substrings. The privilege check was added by
# refactoring this logic out of main(), and a refactor that quietly reworded an
# error is a regression that a `in` assertion would wave through.


def test_a_table_missing_force_is_named_and_told_why_it_matters() -> None:
    """ENABLE without FORCE looks protected in ``pg_policies`` and is not."""

    assert verdict(unprotected=[("applications", True, False)]) == [
        "applications: RLS enabled=True forced=False — both must be true. Without "
        "FORCE, the table's owner bypasses every policy on it."
    ]


def test_a_table_with_no_policies_is_named_without_claiming_rls_is_on() -> None:
    """The message says nothing about ENABLE, deliberately.

    A table can reach this check with RLS off, and "RLS is on but..." would be a
    false statement printed by the tool that is meant to be the authority.
    """

    assert verdict(policyless=[("emails",)]) == ["emails: no row-level security policies at all."]


def test_a_missing_runtime_role_is_a_failure() -> None:
    """``fetchone()`` returns None when the role is not there.

    The role name is written out rather than read from ``RUNTIME_ROLE`` on
    purpose: which role the policies constrain is the fact under test, so a
    change to it should have to be made here too.
    """

    assert verdict(role=None) == [
        "role jobtracker_app does not exist — check what the API actually connects as, "
        "because it is not the role these policies constrain."
    ]


def test_a_bypassrls_runtime_role_is_a_failure() -> None:
    """The branch the whole script was written around."""

    assert verdict(role=(True,)) == [
        "role jobtracker_app has BYPASSRLS — every policy in this database is "
        "decorative for the API's own connection."
    ]


def test_a_healthy_database_produces_no_failures() -> None:
    """All four checks clean, including a full set of legitimate grants."""

    assert verdict(grants=OWNER_GRANTS) == []


def test_the_privilege_failures_come_last() -> None:
    """The new check appends; it does not interleave with the three before it.

    Order is what a reader of a failing run log sees first, and the RLS lines
    were there first.
    """

    lines = verdict(
        unprotected=[("applications", True, False)],
        policyless=[("emails",)],
        role=(True,),
        grants=grant("gmail_credentials", "anon", "SELECT"),
    )

    assert len(lines) == 4
    assert lines[0].startswith("applications: RLS enabled=True forced=False")
    assert lines[1] == "emails: no row-level security policies at all."
    assert lines[2].startswith("role jobtracker_app has BYPASSRLS")
    assert lines[3].startswith("gmail_credentials: anon holds SELECT")
