"""The decisions gate has to be able to fail, five ways, or it is furniture.

`scripts/check_decisions.py` guards `docs/DECISIONS.md`. A gate over a prose
file is exactly the kind this repository keeps catching itself shipping green
from birth and green forever, so every branch that can report a problem gets a
fixture here that makes it report one — and the real document is asserted clean
in the same run, so a checker that returns "problem" for everything cannot pass
either.

The reverse-direction test is the one worth reading. A marker check that only
looks forward — "every file this entry lists contains the id" — stays green
when someone deletes an entry and leaves an orphaned marker sitting in the code, which
is a pointer into a document that will not answer. Both directions or neither.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_decisions.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_decisions", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_decisions"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


#: A minimal well-formed entry. Each test breaks exactly one thing in it, so a
#: reported problem is attributable to the break and not to the fixture.
ID = "DEC-" + "001"
#: Assembled rather than written out. `git ls-files` includes THIS module, so a
#: literal marker here would be an orphan in the real tree and the reverse check
#: would red on its own test suite. Building the ids keeps the tree honest
#: without an exclusion list -- and an exclusion list is the shape this
#: repository keeps re-finding as unchecked coverage.
ORPHAN = "DEC-" + "742"

GOOD = f"""# Decision record

## {ID} — a claim

Status: active (2026-09-05)
Claim: something
Why: because
Moved away from: the other thing
Enforced by: nothing enforces this; prose only
Valid while: the sun rises
Markers: none
"""


def _tree(tmp_path: Path, files: dict[str, str]) -> tuple[set[str], Path]:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return set(files), tmp_path


def test_the_fixture_itself_is_clean(tmp_path: Path) -> None:
    """The positive control. Without it, every assertion below is unfalsifiable."""
    tracked, tree = _tree(tmp_path, {})
    assert mod.check(GOOD, tracked, tree) == []


def test_a_missing_field_is_a_problem(tmp_path: Path) -> None:
    tracked, tree = _tree(tmp_path, {})
    broken = GOOD.replace("Valid while: the sun rises\n", "")
    problems = mod.check(broken, tracked, tree)
    assert any("missing required field 'Valid while:'" in p for p in problems), problems


def test_a_malformed_status_is_a_problem(tmp_path: Path) -> None:
    tracked, tree = _tree(tmp_path, {})
    for bad in ("Status: active", "Status: done (2026-09-05)", "Status: active (yesterday)"):
        broken = GOOD.replace("Status: active (2026-09-05)", bad)
        problems = mod.check(broken, tracked, tree)
        assert any("Status must read" in p for p in problems), (bad, problems)


def test_a_gate_that_does_not_exist_is_a_problem(tmp_path: Path) -> None:
    """The point of the whole script: an entry may not cite a deleted test."""
    tracked, tree = _tree(tmp_path, {"backend/tests/test_real.py": "x"})
    cited_real = GOOD.replace(
        "Enforced by: nothing enforces this; prose only",
        "Enforced by: backend/tests/test_real.py",
    )
    assert mod.check(cited_real, tracked, tree) == []

    cited_gone = GOOD.replace(
        "Enforced by: nothing enforces this; prose only",
        "Enforced by: backend/tests/test_deleted_last_month.py",
    )
    problems = mod.check(cited_gone, tracked, tree)
    assert any("is not a tracked file" in p for p in problems), problems


def test_an_enforced_by_that_names_nothing_is_a_problem(tmp_path: Path) -> None:
    """'Enforced by: the test suite' is the wording this refuses."""
    tracked, tree = _tree(tmp_path, {})
    broken = GOOD.replace(
        "Enforced by: nothing enforces this; prose only",
        "Enforced by: the unit tests, mostly",
    )
    problems = mod.check(broken, tracked, tree)
    assert any("names no file" in p for p in problems), problems


def test_a_marker_the_file_does_not_carry_is_a_problem(tmp_path: Path) -> None:
    """Forward direction: the entry lists a file that has lost its marker."""
    tracked, tree = _tree(tmp_path, {"src/thing.ts": f"// {ID} lives here\n"})
    listed = GOOD.replace("Markers: none", "Markers: src/thing.ts")
    assert mod.check(listed, tracked, tree) == []

    tracked, tree = _tree(tmp_path, {"src/thing.ts": "// the marker was edited away\n"})
    problems = mod.check(listed, tracked, tree)
    assert any(f"does not contain the literal {ID}" in p for p in problems), problems


def test_a_marker_in_the_tree_with_no_entry_is_a_problem(tmp_path: Path) -> None:
    """Reverse direction. This is the one a forward-only check misses."""
    tracked, tree = _tree(tmp_path, {"src/orphan.ts": f"// {ORPHAN}: see the record\n"})
    problems = mod.check(GOOD, tracked, tree)
    assert any(ORPHAN in p and "no entry" in p for p in problems), problems


def test_a_document_with_no_entries_refuses_rather_than_passing(tmp_path: Path) -> None:
    """A gate that measured nothing must not report OK -- the house defect."""
    tracked, tree = _tree(tmp_path, {})
    problems = mod.check("# Decision record\n\nnothing here yet.\n", tracked, tree)
    assert problems and "nothing was checked" in problems[0]


def test_the_real_document_passes(tmp_path: Path) -> None:
    """End to end against the committed record, through the real git tree."""
    text = (REPO_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    problems = mod.check(text, mod.tracked_files(), REPO_ROOT)
    assert problems == [], problems


@pytest.mark.parametrize("field", mod.FIELDS)
def test_every_declared_field_is_actually_required(tmp_path: Path, field: str) -> None:
    """Guards the list itself: a field added to FIELDS but never demanded."""
    tracked, tree = _tree(tmp_path, {})
    line = next(ln for ln in GOOD.splitlines() if ln.startswith(field + ":"))
    problems = mod.check(GOOD.replace(line + "\n", ""), tracked, tree)
    assert any(f"missing required field '{field}:'" in p for p in problems), problems
