"""The rule inside ``scripts/check_expand_only.py``, without a database.

The gate itself needs a real Postgres and lives in its own CI job. What is
tested here is everything that decides the verdict once the schema has been
read: the fingerprint parser, the five destructive facts, the four things that
deliberately are NOT destructive, and the ``CONTRACT_STEP`` waiver.

That split matters. The Postgres job proves the chain is walkable and that the
current thirteen revisions pass; these prove the classifier says the right thing
about cases the repo does not currently contain — a dropped table, a vanished
enum label — which is the whole point of a gate nobody has tripped yet.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "scripts" / "check_expand_only.py"
FINGERPRINT_SQL = REPO_ROOT / "scripts" / "schema_fingerprint.sql"


def _load_gate():
    """Import the script by path — it is a tool, not a package module.

    It deliberately imports psycopg and alembic lazily, inside the functions
    that need them, so this costs nothing here and works in the plain `test`
    job, which has no Postgres and no migration extras.
    """

    spec = importlib.util.spec_from_file_location("check_expand_only", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves annotations through
    # `sys.modules[cls.__module__]`, and an unregistered module makes that None
    # — collection dies with an AttributeError inside dataclasses.py that says
    # nothing about the real cause.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


# =============================================================================
# Fingerprint lines, in exactly the shape scripts/schema_fingerprint.sql emits
# =============================================================================


def column(table: str, name: str, type_name: str = "text", null: str = "YES") -> str:
    return f"column  {table}.{name}  type={type_name}  null={null}  default=-"


def rls(table: str) -> str:
    return f"rls     {table}  enabled=t  forced=t"


def enum(name: str, *labels: str) -> str:
    return f"enum    {name}  = {{{','.join(labels)}}}"


def table(name: str, *columns: tuple[str, str, str]) -> list[str]:
    """Every line a one-table schema produces: the columns AND the rls row."""

    return [column(name, col, type_name, null) for col, type_name, null in columns] + [
        rls(name)
    ]


BASELINE = table(
    "applications",
    ("id", "int4", "NO"),
    ("company", "varchar", "NO"),
    ("notes", "varchar", "YES"),
    ("status", "applicationstatus", "NO"),
) + [enum("applicationstatus", "APPLIED", "INTERVIEWING", "OFFER")]


def findings(before_lines: list[str], after_lines: list[str]) -> list[str]:
    before = gate.parse_fingerprint(before_lines)
    after = gate.parse_fingerprint(after_lines)
    return [f"{f.kind}: {f.what}" for f in gate.destructive_changes(before, after)]


# =============================================================================
# The parser refuses to guess
# =============================================================================


def test_a_line_it_cannot_parse_is_an_error_not_a_skip() -> None:
    """The failure mode this gate exists to avoid, applied to itself.

    Skipping an unrecognised ``column`` line would make the gate pass on a
    schema it never actually read.
    """

    with pytest.raises(gate.GateError, match="unrecognised line"):
        gate.parse_fingerprint(BASELINE + ["column  malformed-without-a-type"])


def test_facts_this_gate_does_not_judge_are_parsed_and_ignored() -> None:
    """Indexes, constraints and policies are read without being judged."""

    snapshot = gate.parse_fingerprint(
        BASELINE
        + [
            "index   CREATE INDEX ix_applications_status ON public.applications USING btree (status)",
            "constr  applications.applications_pkey  p  PRIMARY KEY (id)",
            "policy  applications.owner  cmd=ALL  permissive=PERMISSIVE  using=(user_id = auth.uid())  check=-",
        ]
    )

    assert snapshot.tables == frozenset({"applications"})
    assert snapshot.total_facts == len(BASELINE) + 3


def test_the_two_table_enumerations_must_agree() -> None:
    """A table with columns but no ``rls`` line means the parser is wrong.

    The fingerprint counts tables twice over — once through
    ``information_schema.columns`` joined to BASE TABLEs, once through
    ``pg_class`` where ``relkind='r'``. Disagreement is a parser bug, and every
    verdict downstream of it would be worthless, so it is fatal.
    """

    with pytest.raises(gate.GateError, match="table enumerations disagree"):
        gate.parse_fingerprint(BASELINE + [column("orphan", "id", "int4", "NO")])


def test_alembic_version_is_not_application_schema() -> None:
    """Alembic's bookkeeping table is excluded from the analysis."""

    lines = BASELINE + table("alembic_version", ("version_num", "varchar", "NO"))
    snapshot = gate.parse_fingerprint(lines)

    assert snapshot.tables == frozenset({"applications"})
    assert ("alembic_version", "version_num") not in snapshot.columns


# =============================================================================
# The five destructive facts
# =============================================================================


def test_a_dropped_column_is_destructive_and_is_named() -> None:
    after = [line for line in BASELINE if "applications.notes" not in line]

    assert findings(BASELINE, after) == ["column dropped: applications.notes"]


def test_a_changed_column_type_is_destructive() -> None:
    after = [
        column("applications", "id", "int8", "NO") if "applications.id" in line else line
        for line in BASELINE
    ]

    assert findings(BASELINE, after) == ["column type changed: applications.id"]


def test_narrowing_a_column_to_not_null_is_destructive() -> None:
    after = [
        column("applications", "notes", "varchar", "NO")
        if "applications.notes" in line
        else line
        for line in BASELINE
    ]

    assert findings(BASELINE, after) == ["column narrowed to NOT NULL: applications.notes"]


def test_a_dropped_table_is_reported_once_not_once_per_column() -> None:
    """Four columns disappear with the table; one line says so.

    Reporting each column too would bury the sentence that matters under the
    ones that follow from it — the "noisy gate gets disabled" failure.
    """

    after = [enum("applicationstatus", "APPLIED", "INTERVIEWING", "OFFER")]

    assert findings(BASELINE, after) == ["table dropped: applications"]


def test_a_dropped_enum_label_is_destructive() -> None:
    after = [
        enum("applicationstatus", "APPLIED", "OFFER") if line.startswith("enum") else line
        for line in BASELINE
    ]

    assert findings(BASELINE, after) == ["enum label dropped: applicationstatus"]


def test_a_dropped_enum_type_is_destructive() -> None:
    after = [line for line in BASELINE if not line.startswith("enum")]

    assert findings(BASELINE, after) == ["enum type dropped: applicationstatus"]


# =============================================================================
# ... and the things that are deliberately NOT destructive
# =============================================================================


def test_additive_and_relaxing_changes_are_not_destructive() -> None:
    """The narrowness of the rule, stated as a test.

    A gate that also fired on new indexes, relaxed constraints, new columns and
    new enum labels would fire on nearly every revision in this repo, and the
    first person in a hurry would delete it.
    """

    after = (
        table(
            "applications",
            ("id", "int4", "NO"),
            ("company", "varchar", "YES"),  # NOT NULL relaxed to nullable
            ("notes", "varchar", "YES"),
            ("status", "applicationstatus", "NO"),
            ("req_id", "varchar", "YES"),  # new column
        )
        + [enum("applicationstatus", "APPLIED", "INTERVIEWING", "OFFER", "ASSESSMENT")]
        + table("interviews", ("id", "int4", "NO"))  # new table
        + [
            "index   CREATE INDEX ix_new ON public.applications USING btree (req_id)",
            "constr  applications.applications_pkey  p  PRIMARY KEY (id)",
        ]
    )

    assert findings(BASELINE, after) == []


def test_dropping_an_index_is_not_destructive() -> None:
    """It costs performance, not correctness. `485296d24828` does exactly this."""

    before = BASELINE + [
        "index   CREATE UNIQUE INDEX ix_emails_message_id ON public.emails USING btree (message_id)"
    ]

    assert findings(before, BASELINE) == []


# =============================================================================
# The waiver
# =============================================================================


class _Module:
    """Stand-in for a revision module. Alembic hands the real one to the gate."""

    def __init__(self, **attrs: object) -> None:
        self.__dict__.update(attrs)


def test_no_declaration_reads_as_no_declaration() -> None:
    assert gate.read_contract_step(_Module(), "abc123") is None


def test_a_real_reason_is_accepted_and_returned() -> None:
    reason = "PR #204 removed the last reader of applications.legacy_note; live."
    assert gate.read_contract_step(_Module(CONTRACT_STEP=reason), "abc123") == reason


def test_a_bare_flag_is_rejected() -> None:
    """`CONTRACT_STEP = True` must not pass. The reason IS the artifact."""

    with pytest.raises(gate.GateError, match="must be a string"):
        gate.read_contract_step(_Module(CONTRACT_STEP=True), "abc123")


def test_a_reason_too_short_to_be_a_reason_is_rejected() -> None:
    with pytest.raises(gate.GateError, match="characters"):
        gate.read_contract_step(_Module(CONTRACT_STEP="drop it"), "abc123")


def test_a_bad_declaration_never_degrades_to_no_declaration() -> None:
    """It raises rather than returning None.

    If it returned None, `CONTRACT_STEP = True` would fail with a message about
    a dropped column and the author would go looking in the wrong file.
    """

    for bad in (True, 1, ["a reason"], "short"):
        with pytest.raises(gate.GateError):
            gate.read_contract_step(_Module(CONTRACT_STEP=bad), "abc123")


# =============================================================================
# It cannot be pointed at production, and it cannot pass without a database
# =============================================================================


def test_a_non_loopback_host_is_refused() -> None:
    """This script runs DROP SCHEMA public CASCADE."""

    with pytest.raises(gate.GateError, match="refusing to run against host"):
        gate._assert_safe_target("postgresql://u:p@db.abcdefg.supabase.co:5432/postgres")


def test_loopback_in_any_driver_spelling_is_allowed() -> None:
    for url in (
        "postgresql://postgres:postgres@127.0.0.1:55433/postgres",
        "postgresql+psycopg://postgres:postgres@localhost:5432/test_db",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
    ):
        gate._assert_safe_target(url)


def test_direct_url_is_never_consulted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production credential's own variable name is not an input here.

    Exercised rather than asserted about the source: with DIRECT_URL set and
    nothing else, the gate must refuse to run instead of migrating production.
    """

    monkeypatch.setenv("DIRECT_URL", "postgresql://u:p@db.abcdefg.supabase.co:5432/postgres")
    monkeypatch.delenv("JOBTRACKER_TEST_PG_ADMIN_URL", raising=False)

    assert gate.main([]) == 2


def test_a_missing_database_is_a_failure_not_a_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Postgres means "cannot answer", and cannot-answer is not green."""

    monkeypatch.delenv("JOBTRACKER_TEST_PG_ADMIN_URL", raising=False)
    monkeypatch.delenv("DIRECT_URL", raising=False)

    assert gate.main([]) != 0


# =============================================================================
# The parser and the SQL it parses have to stay in step
# =============================================================================


def test_the_parser_still_matches_the_fingerprint_sql() -> None:
    """Every category this parser knows is still spelled that way in the SQL.

    The tests above feed the parser handwritten lines, so a change to
    `scripts/schema_fingerprint.sql`'s format strings would leave them green
    while the real gate failed. This reads the SQL and checks the literal
    prefixes — including their exact padding, which is what the regexes anchor
    on — are all still there.
    """

    sql = FINGERPRINT_SQL.read_text()

    for prefix in ("column  ", "enum    ", "rls     ", "index   ", "constr  ", "policy  "):
        assert f"format('{prefix}" in sql, (
            f"scripts/schema_fingerprint.sql no longer emits a {prefix.strip()!r} "
            "line in the shape check_expand_only.py parses"
        )
