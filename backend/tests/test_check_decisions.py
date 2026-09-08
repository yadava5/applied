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


#: A second well-formed id, assembled for the same reason `ID` is: a literal
#: here would be an unregistered marker in the tracked tree and the
#: completeness check below would red on its own test module.
ID2 = "DEC-" + "002"


def _entry(eid: str, title: str, markers: str) -> str:
    """One well-formed entry. Only id, title and Markers vary between tests."""
    return (
        f"## {eid} — {title}\n\n"
        "Status: active (2026-09-05)\n"
        "Claim: something\n"
        "Why: because\n"
        "Moved away from: the other thing\n"
        "Enforced by: nothing enforces this; prose only\n"
        "Valid while: the sun rises\n"
        f"Markers: {markers}\n"
    )


def test_a_marker_the_entry_does_not_claim_is_a_problem(tmp_path: Path) -> None:
    """Reverse direction, COMPLETENESS half -- #950.

    The forward check asks whether a declared file carries the id. This asks
    the other half: whether a file carrying the id was declared. Both arms are
    here, in one test, because a check that reds on everything is not a check.
    """
    doc = "# Decision record\n\n" + _entry(ID, "a claim", "src/declared.py")

    # Arm 1 -- the file is declared. Must stay silent, or the assertion below
    # proves nothing about unlisted files specifically.
    tracked, tree = _tree(tmp_path, {"src/declared.py": f"# {ID} why this exists\n"})
    assert mod.check(doc, tracked, tree) == []

    # Arm 2 -- a second file carries the same id and no entry claims it.
    tracked, tree = _tree(
        tmp_path,
        {
            "src/declared.py": f"# {ID} why this exists\n",
            "src/unlisted.py": f"# {ID} why this exists\n",
        },
    )
    problems = mod.check(doc, tracked, tree)
    assert any("src/unlisted.py" in p and "does not list it" in p for p in problems), problems
    assert not any("src/declared.py" in p for p in problems), problems


def test_the_950_collision_reds_where_it_used_to_pass(tmp_path: Path) -> None:
    """The exact shape #950 was filed for, end to end.

    Two branches independently allocate one id. `docs/DECISIONS.md` conflicts
    textually -- the good case, and the only thing that catches this today --
    and the conflict is resolved by keeping ONE side, which is the reflex. The
    losing branch's marker sites survive in the tree and go on resolving, to a
    real and well-formed entry about something else.

    Before this check the gate printed `OK` here with three marker sites
    pointing at the wrong decision. Landing on the wrong entry is strictly
    worse than landing on nothing, so it has to red.
    """
    merged = "# Decision record\n\n" + _entry(ID, "branch A's decision", "src/a1.py")
    tracked, tree = _tree(
        tmp_path,
        {
            "src/a1.py": f"# {ID} branch A\n",
            "src/b1.py": f"# {ID} branch B\n",
            "src/b2.py": f"# {ID} branch B\n",
            "src/b3.py": f"# {ID} branch B\n",
        },
    )
    problems = mod.check(merged, tracked, tree)
    losers = [p for p in problems if "does not list it" in p]
    assert len(losers) == 3, problems
    for f in ("src/b1.py", "src/b2.py", "src/b3.py"):
        assert any(f in p for p in losers), (f, problems)


def test_two_entries_sharing_one_id_is_a_problem(tmp_path: Path) -> None:
    """The other resolution of the same conflict: keep BOTH headings.

    This branch already existed and had no test, which is its own instance of
    the shape -- a check nothing had ever made red.
    """
    doc = "# Decision record\n\n" + _entry(ID, "first", "none") + "\n" + _entry(ID, "second", "none")
    tracked, tree = _tree(tmp_path, {})
    problems = mod.check(doc, tracked, tree)
    assert any("duplicate id" in p for p in problems), problems


def test_a_gap_in_the_ids_is_a_problem(tmp_path: Path) -> None:
    """A deleted entry, once its markers are tidied away too, leaves a file
    that is internally consistent and locally unimpeachable. The sequence is
    the only thing left that remembers the entry was there."""
    contiguous = "# Decision record\n\n" + _entry(ID, "one", "none") + "\n" + _entry(ID2, "two", "none")
    tracked, tree = _tree(tmp_path, {})
    assert mod.check(contiguous, tracked, tree) == []

    gapped = "# Decision record\n\n" + _entry(ID, "one", "none") + "\n" + _entry("DEC-" + "003", "three", "none")
    problems = mod.check(gapped, tracked, tree)
    assert any("no gaps" in p and ID2 in p for p in problems), problems


# --------------------------------------------------------------------------
# #958 — a wrapped field value keeps its continuation lines.
#
# `parse` read `line.startswith(f + ":")` and nothing else, so a `Markers:`
# list that wrapped lost every path after the first physical line. The forward
# check then skipped those paths silently and the REVERSE completeness check
# reported that the entry "does not list" a file a reader can see listed. The
# half that spoke was the half that was wrong, which is worse than a check that
# fails to notice.
# --------------------------------------------------------------------------

#: The same two paths, spelled on one line and across two. Every assertion
#: below compares the two readings of THESE, so neither spelling can drift.
ONE_LINE = "Markers: src/one.py, src/two.py\n"
WRAPPED = "Markers: src/one.py,\n  src/two.py\n"


def _carrying(marker: str) -> dict[str, str]:
    return {"src/one.py": f"# {marker}\n", "src/two.py": f"# {marker}\n"}


def test_a_wrapped_markers_list_reads_as_the_same_paths(tmp_path: Path) -> None:
    """The control the issue asks for by name.

    Asserting only that the wrapped form is CLEAN would pass against a parser
    that dropped the continuation line entirely — the dropped path would simply
    never be checked. So the two spellings are compared to each other, and the
    comparison is run twice: once where both must be clean, and once where both
    must report the SAME problem. A parser that loses the line fails the second
    immediately, because losing a path is how you get an empty problem list.
    """
    tracked, tree = _tree(tmp_path, _carrying(ID))

    flat = mod.check(GOOD.replace("Markers: none\n", ONE_LINE), tracked, tree)
    wrapped = mod.check(GOOD.replace("Markers: none\n", WRAPPED), tracked, tree)
    assert flat == [] and wrapped == [], (
        f"a clean pair should report nothing; one line -> {flat}, wrapped -> {wrapped}"
    )

    # ...and now the same pair where the SECOND path is untracked, so both
    # spellings owe exactly one problem naming `src/two.py`. This is the arm
    # that the pre-#958 parser fails: it never saw the path, so it reported
    # nothing and the two lists disagreed.
    partial = {"src/one.py": f"# {ID}\n"}
    tracked, tree = _tree(tmp_path / "partial", partial)
    flat = mod.check(GOOD.replace("Markers: none\n", ONE_LINE), tracked, tree)
    wrapped = mod.check(GOOD.replace("Markers: none\n", WRAPPED), tracked, tree)
    assert flat, "the one-line spelling reported nothing; the fixture is wrong"
    assert flat == wrapped, (
        "the two spellings of one list read differently:\n"
        f"  one line -> {flat}\n  wrapped  -> {wrapped}"
    )
    assert any("src/two.py" in p for p in wrapped), (
        f"the continuation line's path was never checked: {wrapped}"
    )


def test_the_reverse_check_sees_a_path_on_a_continuation_line(tmp_path: Path) -> None:
    """The exact false red #958 reports, asserted as absent.

    `src/two.py` carries the id and IS listed, on the second line. Before the
    fix the completeness check said it was not listed, about a path visible
    directly above in the same document.
    """
    tracked, tree = _tree(tmp_path, _carrying(ID))
    problems = mod.check(GOOD.replace("Markers: none\n", WRAPPED), tracked, tree)
    assert not [p for p in problems if "does not list it" in p], (
        f"the gate reported a listed file as unlisted: {problems}"
    )


def test_a_continuation_stops_at_a_blank_line_and_at_column_zero(tmp_path: Path) -> None:
    """The value ends where the entry says it ends, both ways.

    Without this the parser would absorb the next field, or trailing prose, into
    whichever value came last — and `Markers:` is PATH-scanned, so absorbed
    prose naming any `foo/bar.py` would demand that file exist. Two separate
    terminators, asserted separately: a line at column zero, and a blank line.
    """
    tracked, tree = _tree(tmp_path, {"src/one.py": f"# {ID}\n"})

    # A blank line, then indented prose that names a path nothing tracks. If
    # the blank line did not terminate the value, this would red.
    text = GOOD.replace(
        "Markers: none\n",
        "Markers: src/one.py\n\n  See also src/nowhere.py for the shape.\n",
    )
    assert mod.check(text, tracked, tree) == [], (
        "a blank line did not end the field value"
    )

    # And the column-zero terminator, which needs prose rather than a field to
    # grade it: a line beginning `Valid while:` is recognised as a NEW field
    # before the continuation branch is ever consulted, so using one here tests
    # the field scanner and not the indentation rule. A first draft did exactly
    # that and a mutation deleting `line[:1].isspace()` survived it untouched.
    #
    # Unindented prose naming an untracked path is what separates them: absorbed
    # into `Markers:` it demands `src/nowhere.py` exist, and terminated it is
    # invisible.
    trailing = GOOD.replace(
        "Markers: none\n",
        "Markers: src/one.py\nSee also src/nowhere.py for the shape.\n",
    )
    assert mod.check(trailing, tracked, tree) == [], (
        "prose at column zero was absorbed into the field above it"
    )


def test_a_four_digit_id_is_visible_to_every_pattern(tmp_path: Path) -> None:
    """`\\b` does not match between two digits, so `\\d{3}` hid a four-digit id whole.

    Not a hypothetical about arithmetic: with the old pattern the ENTRY scanner
    found no entries at all in a document whose only entry was four digits, and
    `check` then reported "contains no DEC entries" rather than anything about
    the entry. The marker scanner missed it in the tree at the same time, so an
    orphaned four-digit marker was invisible in BOTH directions at once.

    Asserted through the reverse check, which is the direction that would have
    stayed silent: a tracked file carrying a four-digit id with no entry for it
    must be reported. The id itself is assembled rather than written, for the
    reason the header gives: a literal here is an orphan in the real tree.
    """
    four = "DEC-" + "1000"
    tracked, tree = _tree(tmp_path, {"src/one.py": f"# {four}\n"})
    problems = mod.check(GOOD, tracked, tree)
    assert any(four in p and "no entry" in p for p in problems), (
        f"a four-digit marker was invisible to the gate: {problems}"
    )
    assert mod.MARKER.findall(f"# {four}\n") == [four], (
        "the marker pattern still cannot see a four-digit id"
    )
