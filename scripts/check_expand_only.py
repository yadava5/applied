#!/usr/bin/env python3
"""Fail the build if a revision removes or narrows something without saying so.

WHY THIS EXISTS
---------------

A push to main starts the `DB migrate` workflow **and** a Vercel deploy at the
same moment, and nothing orders them — Vercel's git integration owns its own
trigger. For an ADDITIVE revision that is survivable: old code ignores a column
it does not select, so whichever half lands first, both work. For a DESTRUCTIVE
one there is no ordering in which one PR is safe, because the old code is still
serving when the column disappears.

`docs/MIGRATIONS.md` says exactly that, and until this script existed it said it
in prose. Nothing measured it. This walks the Alembic chain **one revision at a
time** against a real Postgres, fingerprints the schema after each step, and
fails on a removal or a narrowing that has not been declared.

WHAT COUNTS AS DESTRUCTIVE — and the rule is deliberately narrow
---------------------------------------------------------------

Exactly five facts, all of which break code that is *already running*:

  1. a column disappears
  2. a column's type changes
  3. a column goes nullable -> NOT NULL
  4. a table disappears
  5. an enum label disappears (including because its type did)

Deliberately NOT destructive, and not reported: adding or dropping an index,
relaxing a constraint, adding a column, adding an enum label. A noisy gate gets
switched off, and this repo has a documented history of gates that were ignored
or deleted rather than obeyed.

WHY PER-REVISION, NOT END-TO-END
--------------------------------

`6e64c46d32fd` adds `user_id` nullable, backfills it, and flips it to NOT NULL —
all inside one revision. Diffed end-to-end that is "a new NOT NULL column",
which is additive and fine. Diffed per revision it is *still* additive, because
the column did not exist in the snapshot taken before that revision ran. Either
way it passes, and it passes for the right reason: the narrowing never applied
to a column any deployed code could already be reading.

THE OPT-OUT
-----------

A revision that genuinely needs a contract step declares it at module level:

    CONTRACT_STEP = "PR #204 removed the last reader of applications.legacy_note; \
this merges after that deploy is live."

Its presence is what makes this script pass for that revision, and it is what a
reviewer looks for. It must be a sentence — a bare `True`, or a string too short
to be a reason, is rejected, because the reason IS the artifact. A declaration
on a revision that removes nothing is also rejected: a waiver attached to
nothing is a false signal to the next reader, and a stale one would silently
cover the next drop somebody adds to that file.

WHAT THIS DOES NOT COVER — read this before trusting it
-------------------------------------------------------

* **`ADD UNIQUE` is not checked**, although `docs/MIGRATIONS.md` lists it as
  needing two merges. It is a different risk shape: a new UNIQUE breaks *new
  writes* that collide, not old *reads*, so it cannot be detected as a removal
  and deciding whether a constraint tightened or relaxed needs comparison logic
  that would produce false positives on every index rename. Four of the five
  contract triggers in that table are enforced here; this one stays a review
  responsibility.

* **VARCHAR length narrowing is invisible.** `scripts/schema_fingerprint.sql`
  records `udt_name`, so `varchar(500) -> varchar(50)` reads as no change. That
  file is the artifact that proved production byte-identical to a from-empty
  build; it is not modified here to chase a case this schema does not have
  (`models.py` declares `max_length` exactly once, on `emails.body_snippet`,
  and SQLModel renders every other string column as unbounded `AutoString`).

* **It does not replace `tests/test_migrations_postgres.py`.** That module runs
  the whole chain in ONE `upgrade head`, which is the fragile case — `env.py`
  wraps every pending revision in a single transaction, and stepping revision by
  revision as this script does gives each one its own, so `b9e42f7c10ad`'s
  `autocommit_block()` is not exercised the same way. Both are needed.

* Head/chain bookkeeping belongs to `tests/test_schema_version.py`. The single
  head is asserted here only as a precondition — a branched chain has no linear
  walk — not as a second copy of that gate.

RUNNING IT
----------

    docker run -d --name expandgate -e POSTGRES_PASSWORD=postgres \
      -p 55433:5432 postgres:16

    JOBTRACKER_TEST_PG_ADMIN_URL=postgresql://postgres:postgres@127.0.0.1:55433/postgres \
      python scripts/check_expand_only.py

**This script drops and rebuilds the `public` schema.** It therefore refuses to
read `DIRECT_URL` at all, refuses any host that is not loopback, and refuses a
database that holds rows. Point it at a scratch Postgres, never at production.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
FINGERPRINT_SQL = REPO_ROOT / "scripts" / "schema_fingerprint.sql"

# Alembic's own bookkeeping table. Excluded from the analysis for the same
# reason `verify_rls.py` excludes it: it is not application schema, and a future
# Alembic release widening `version_num` would otherwise fail this gate.
IGNORED_TABLES = frozenset({"alembic_version"})

# A reason has to be long enough to be a reason. "yes", "ok", "safe" are not.
MIN_REASON_CHARS = 20

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})

# Supabase provides these in production. `a8d4ec5fba26` creates policies over
# `auth.uid()`, which Postgres resolves at CREATE POLICY time, so the chain
# cannot run on a database that has no `auth` schema. Identical to the fixture
# in tests/test_migrations_postgres.py, and it is not test scaffolding: without
# it the chain dies with `schema "auth" does not exist` and reports nothing
# about the migrations.
AUTH_SHIM_SQL = """
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id uuid primary key);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', '')::uuid
$$;
"""


class GateError(RuntimeError):
    """Something made the check impossible to perform. Never silently skipped."""


# =============================================================================
# Parsing scripts/schema_fingerprint.sql into facts we can compare
# =============================================================================

COLUMN_RE = re.compile(
    r"^column  (?P<table>\S+)\.(?P<column>\S+)  type=(?P<type>\S+)  "
    r"null=(?P<null>YES|NO)  default=(?P<default>.*)$"
)
ENUM_RE = re.compile(r"^enum    (?P<name>\S+)  = (?P<labels>.*)$")
RLS_RE = re.compile(r"^rls     (?P<table>\S+)  enabled=\S+  forced=\S+$")
# Facts this gate deliberately does not judge. Listed so that an unrecognised
# line is an error rather than something quietly dropped on the floor.
IGNORED_PREFIXES = ("index   ", "constr  ", "policy  ")


@dataclass(frozen=True)
class ColumnFact:
    type_name: str
    not_null: bool


@dataclass
class Snapshot:
    """The schema facts this gate judges, at one point in the chain."""

    columns: dict[tuple[str, str], ColumnFact] = field(default_factory=dict)
    tables: frozenset[str] = frozenset()
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    total_facts: int = 0


def _parse_enum_labels(raw: str, line: str) -> tuple[str, ...]:
    """`{APPLIED,ASSESSMENT}` -> ('APPLIED', 'ASSESSMENT')."""

    raw = raw.strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        raise GateError(f"cannot parse enum labels from fingerprint line: {line!r}")
    inner = raw[1:-1].strip()
    if not inner:
        return ()
    return tuple(part.strip().strip('"') for part in inner.split(","))


def parse_fingerprint(lines: list[str]) -> Snapshot:
    """Turn fingerprint output into a Snapshot.

    Every line must be recognised. A line this function cannot parse is a hard
    error, never a skip: silently dropping a `column` line it did not understand
    is precisely how a gate reports green on a schema it never looked at.
    """

    columns: dict[tuple[str, str], ColumnFact] = {}
    enums: dict[str, tuple[str, ...]] = {}
    column_tables: set[str] = set()
    rls_tables: set[str] = set()

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue

        match = COLUMN_RE.match(line)
        if match:
            table, column = match["table"], match["column"]
            column_tables.add(table)
            columns[(table, column)] = ColumnFact(
                type_name=match["type"], not_null=match["null"] == "NO"
            )
            continue

        match = ENUM_RE.match(line)
        if match:
            enums[match["name"]] = _parse_enum_labels(match["labels"], line)
            continue

        match = RLS_RE.match(line)
        if match:
            rls_tables.add(match["table"])
            continue

        if line.startswith(IGNORED_PREFIXES):
            continue

        raise GateError(
            f"unrecognised line in the schema fingerprint: {line!r}\n"
            "scripts/schema_fingerprint.sql emits a category this checker does "
            "not know about. Teach check_expand_only.py about it — do not let "
            "it pass unparsed."
        )

    # Two independent enumerations of "which tables exist": one from
    # information_schema.columns joined to BASE TABLEs, one from pg_class with
    # relkind='r'. They must agree. If they ever do not, the parser is wrong and
    # every conclusion below it is worthless, so this is fatal rather than a
    # heuristic union.
    if column_tables != rls_tables:
        raise GateError(
            "the fingerprint's two table enumerations disagree — parser bug.\n"
            f"  only in column lines: {sorted(column_tables - rls_tables)}\n"
            f"  only in rls lines:    {sorted(rls_tables - column_tables)}"
        )

    return Snapshot(
        columns={
            key: value for key, value in columns.items() if key[0] not in IGNORED_TABLES
        },
        tables=frozenset(rls_tables - IGNORED_TABLES),
        enums=enums,
        total_facts=len([line for line in lines if line.strip()]),
    )


# =============================================================================
# The rule
# =============================================================================


@dataclass(frozen=True)
class Finding:
    kind: str
    what: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.what} — {self.detail}"


def destructive_changes(before: Snapshot, after: Snapshot) -> list[Finding]:
    """Everything a still-running deployment could break on. Nothing else."""

    findings: list[Finding] = []

    dropped_tables = sorted(before.tables - after.tables)
    for table in dropped_tables:
        findings.append(
            Finding(
                "table dropped",
                table,
                "code still selecting from it fails on the next request",
            )
        )

    for (table, column), was in sorted(before.columns.items()):
        if table in dropped_tables:
            # Already reported once, as the table. Listing its fourteen columns
            # underneath would bury the one line that matters.
            continue
        now = after.columns.get((table, column))
        if now is None:
            findings.append(
                Finding(
                    "column dropped",
                    f"{table}.{column}",
                    "every SELECT naming it 500s until the old code is gone",
                )
            )
            continue
        if now.type_name != was.type_name:
            findings.append(
                Finding(
                    "column type changed",
                    f"{table}.{column}",
                    f"{was.type_name} -> {now.type_name}; in-flight reads and "
                    "writes are decoded against the old type",
                )
            )
        if now.not_null and not was.not_null:
            findings.append(
                Finding(
                    "column narrowed to NOT NULL",
                    f"{table}.{column}",
                    "any deployed writer that omits it starts failing",
                )
            )

    for name, was_labels in sorted(before.enums.items()):
        now_labels = after.enums.get(name)
        if now_labels is None:
            findings.append(
                Finding(
                    "enum type dropped",
                    name,
                    f"labels lost: {', '.join(was_labels)}",
                )
            )
            continue
        lost = [label for label in was_labels if label not in now_labels]
        if lost:
            findings.append(
                Finding(
                    "enum label dropped",
                    name,
                    f"{', '.join(lost)} — rows and code still using it break",
                )
            )

    return findings


# =============================================================================
# The opt-out
# =============================================================================


def read_contract_step(module: Any, revision: str) -> str | None:
    """The revision's own declaration that it means to remove something.

    Returns the reason, or None if the revision does not declare one. Raises if
    it declares one badly — an unusable waiver must not read as "no waiver", or
    `CONTRACT_STEP = True` would fail with a message about a dropped column and
    the author would go looking in the wrong place.
    """

    if not hasattr(module, "CONTRACT_STEP"):
        return None

    value = module.CONTRACT_STEP
    if isinstance(value, bool) or not isinstance(value, str):
        raise GateError(
            f"{revision}: CONTRACT_STEP must be a string saying why this is "
            f"safe — which PR removed the last reader, and that its deploy is "
            f"live. Got {value!r}. A bare flag is not a reason, and the reason "
            f"is the artifact a reviewer reads."
        )
    reason = value.strip()
    if len(reason) < MIN_REASON_CHARS:
        raise GateError(
            f"{revision}: CONTRACT_STEP is {len(reason)} characters "
            f"({reason!r}). Say which PR removed the last reader and that its "
            f"deploy is live — at least {MIN_REASON_CHARS} characters."
        )
    return reason


# =============================================================================
# Talking to Postgres
# =============================================================================


def _psycopg_url(url: str) -> str:
    """A plain libpq URL, whatever SQLAlchemy scheme it arrived in."""

    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql+asyncpg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _alembic_url(url: str) -> str:
    """The sync-driver URL `env.py` wants in DIRECT_URL."""

    plain = _psycopg_url(url)
    return plain.replace("postgresql://", "postgresql+psycopg://", 1)


def _assert_safe_target(url: str) -> None:
    """Refuse anything that could be somebody's real database.

    This script runs `DROP SCHEMA public CASCADE`. That is fine against a
    throwaway container and catastrophic against Supabase, and the distance
    between the two is one exported variable. So: never `DIRECT_URL` (the name
    production uses), loopback only, and empty only.
    """

    host = urlsplit(_psycopg_url(url)).hostname or ""
    if host not in LOOPBACK_HOSTS:
        raise GateError(
            f"refusing to run against host {host!r}. This check DROPS the public "
            "schema; it accepts loopback only. Start a scratch Postgres and "
            "point JOBTRACKER_TEST_PG_ADMIN_URL at it."
        )


def _assert_database_is_empty(conn) -> None:
    """Fail closed if the target holds data.

    Any error while probing is itself a failure. "I could not count the rows, so
    I assumed there were none, so I dropped the schema" is not a mode this
    should have.
    """

    tables = [
        row[0]
        for row in conn.execute(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "ORDER BY c.relname"
        ).fetchall()
    ]
    for table in tables:
        if table in IGNORED_TABLES:
            continue
        count = conn.execute(f'SELECT count(*) FROM public."{table}"').fetchone()[0]
        if count:
            raise GateError(
                f'refusing to run: public."{table}" holds {count} row(s). This '
                "check rebuilds the schema from empty and would destroy them."
            )


def reset_database(conn) -> None:
    """Back to empty, with the auth objects the RLS revisions need."""

    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute(AUTH_SHIM_SQL)


def fingerprint(conn, sql: str) -> Snapshot:
    rows = conn.execute(sql).fetchall()
    return parse_fingerprint([row[0] for row in rows])


def run_alembic(url: str, revision: str) -> None:
    """`alembic upgrade <revision>` in a SUBPROCESS, exactly as a deploy runs it.

    A subprocess and not `alembic.command`: `env.py` calls
    `fileConfig(alembic.ini)`, which reconfigures the root logging config of
    whatever process runs it, and `DIRECT_URL` through the CLI is the resolution
    path production actually takes.

    `DATABASE_URL` is cleared rather than inherited — it is second in `env.py`'s
    resolution order, and a developer with one exported would otherwise have a
    surprising fallback if `DIRECT_URL` were ever dropped from this call.
    """

    env = dict(os.environ)
    env["DIRECT_URL"] = _alembic_url(url)
    env.pop("DATABASE_URL", None)

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", revision],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GateError(
            f"alembic upgrade {revision} failed ({proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )


# =============================================================================
# The walk
# =============================================================================


def chain_in_order() -> list:
    """Every revision, base -> head, with its loaded module.

    A single head is a precondition, not a second copy of
    `tests/test_schema_version.py`: two heads mean there is no linear order to
    walk and no answer this script could give.
    """

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    heads = scripts.get_heads()
    if len(heads) != 1:
        raise GateError(
            f"the revision chain has {len(heads)} heads ({', '.join(sorted(heads))}). "
            "There is no linear order to walk. Rebase one branch onto the other; "
            "tests/test_schema_version.py explains why this happens."
        )

    return list(reversed(list(scripts.walk_revisions("base", heads[0]))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail if an Alembic revision removes or narrows schema "
        "without declaring CONTRACT_STEP."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("JOBTRACKER_TEST_PG_ADMIN_URL"),
        help="Scratch Postgres URL (default: $JOBTRACKER_TEST_PG_ADMIN_URL). "
        "DIRECT_URL is deliberately NOT consulted.",
    )
    args = parser.parse_args(argv)

    # Line-buffered so the per-revision progress on stdout stays interleaved
    # with anything raised on stderr. Block-buffered (the default when stdout is
    # a pipe, i.e. in CI) printed the error above the walk that produced it.
    sys.stdout.reconfigure(line_buffering=True)

    if not args.url:
        # Not a skip. A skip is green, and green here would mean "no destructive
        # migration found" about a database that was never built.
        print(
            "ERROR: no Postgres URL. Set JOBTRACKER_TEST_PG_ADMIN_URL or pass "
            "--url. This check cannot run without a database, and it will not "
            "pass by pretending it did.",
            file=sys.stderr,
        )
        return 2

    try:
        import psycopg
    except ImportError:
        print(
            "ERROR: psycopg is not installed. "
            "pip install -r requirements.txt -r backend/requirements-migrate.txt",
            file=sys.stderr,
        )
        return 2

    try:
        _assert_safe_target(args.url)
        sql = FINGERPRINT_SQL.read_text()
        revisions = chain_in_order()

        # autocommit, and it is load-bearing: a connection left mid-transaction
        # holds ACCESS SHARE on every table the fingerprint read, and the next
        # `alembic upgrade` — which takes ACCESS EXCLUSIVE and runs under
        # env.py's five-second `lock_timeout` — would block on this process and
        # die. The check would then report a broken migration that is fine.
        with psycopg.connect(_psycopg_url(args.url), autocommit=True) as conn:
            _assert_database_is_empty(conn)
            reset_database(conn)
            before = fingerprint(conn, sql)

            undeclared: list[str] = []
            stale: list[str] = []
            waived: list[tuple[str, str, list[Finding]]] = []
            walked = 0

            print(f"walking {len(revisions)} revisions, one at a time\n")
            for script in revisions:
                revision = script.revision
                run_alembic(args.url, revision)
                after = fingerprint(conn, sql)
                findings = destructive_changes(before, after)
                reason = read_contract_step(script.module, revision)

                delta = after.total_facts - before.total_facts
                if findings and reason:
                    waived.append((revision, reason, findings))
                    print(f"  WAIVED  {revision}  ({len(findings)} removal(s))")
                    for finding in findings:
                        print(f"            {finding}")
                    print(f"            CONTRACT_STEP: {reason}")
                elif findings:
                    print(f"  FAIL    {revision}")
                    for finding in findings:
                        print(f"            {finding}")
                    undeclared.append(
                        f"{revision} ({script.doc}):\n"
                        + "\n".join(f"    - {finding}" for finding in findings)
                    )
                elif reason:
                    print(f"  STALE   {revision}  (CONTRACT_STEP waives nothing)")
                    stale.append(f"{revision} ({script.doc})")
                else:
                    print(f"  ok      {revision}  ({delta:+d} facts)")

                before = after
                walked += 1

            head_row = conn.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall()

    except GateError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2

    # Anti-vacuity. Every one of these has a real failure mode behind it: a
    # ScriptDirectory pointed at the wrong tree walks zero revisions and reports
    # success, and a chain that stops early proves nothing about the revisions
    # it never reached. Structural, not a count — nothing here needs editing
    # when a revision is added.
    if walked == 0:
        print(
            "\nERROR: walked zero revisions. The chain was not read; this run "
            "proves nothing.",
            file=sys.stderr,
        )
        return 2
    expected_head = revisions[-1].revision
    if [row[0] for row in head_row] != [expected_head]:
        print(
            f"\nERROR: the walk ended with alembic_version at "
            f"{[row[0] for row in head_row]!r}, not the chain head "
            f"{expected_head!r}. The chain did not fully apply.",
            file=sys.stderr,
        )
        return 2

    summary_lines: list[str] = []
    if undeclared:
        summary_lines.append(
            f"### Destructive schema change in {len(undeclared)} revision(s)\n"
        )
        print(
            "\n"
            "=======================================================================\n"
            f"DESTRUCTIVE SCHEMA CHANGE in {len(undeclared)} revision(s)\n"
            "=======================================================================\n"
        )
        for failure in undeclared:
            print(f"  {failure}\n")
            summary_lines.append(f"```\n{failure}\n```\n")
        guidance = (
            "A push to main runs the migration and deploys new code at the same "
            "time, in no guaranteed order, so there is no ordering in which this "
            "is safe in one merge: the old code is still serving when the column "
            "goes.\n\n"
            "Split it — see 'Contract steps' in docs/MIGRATIONS.md:\n"
            "  1. PR 1: remove every reader and writer. Merge. Confirm the deploy "
            "is live (/health reports the new commit).\n"
            "  2. PR 2: this revision, plus a module-level CONTRACT_STEP naming "
            "PR 1 and stating its deploy is live.\n"
        )
        print(guidance)
        summary_lines.append(guidance.replace("\n", "\n\n"))

    if stale:
        header = f"CONTRACT_STEP waives nothing in {len(stale)} revision(s)"
        print(
            "\n"
            "=======================================================================\n"
            f"{header}\n"
            "=======================================================================\n"
        )
        summary_lines.append(f"### {header}\n")
        for revision in stale:
            print(f"  {revision}")
            summary_lines.append(f"- `{revision}`\n")
        guidance = (
            "\nThese revisions remove and narrow nothing, so the declaration is "
            "inert. Delete it: a reason attached to no removal tells the next "
            "reviewer this revision was reasoned about when it was not, and it "
            "would silently cover the first genuine drop added to the same file.\n"
        )
        print(guidance)
        summary_lines.append(guidance)

    if not undeclared and not stale:
        headline = (
            f"{walked} revisions walked, none removes or narrows anything "
            "undeclared."
        )
        if waived:
            headline += f" {len(waived)} declared contract step(s)."
        print(f"\nOK: {headline}")
        summary_lines.append(f"### Expand-only gate\n\n{headline}\n")
        for revision, reason, findings in waived:
            summary_lines.append(
                f"- `{revision}` waived {len(findings)} removal(s): {reason}\n"
            )

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as handle:
            handle.writelines(summary_lines)

    return 1 if (undeclared or stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
