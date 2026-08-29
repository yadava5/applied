"""``--write`` must correct the number it matched, and no other — issue #468.

The README carries lines with several registered facts on them, the board row
being the one this was found on:

    | Board: cards / splits / merges / noise / misrouted review | **9,132 / 0 / 0 / 0 / 0** |

Three of those five numbers are facts, and each one's site pattern anchors on
the others to find its own position. So a writer that rewrites by searching the
matched text for the old value can replace a digit belonging to a NEIGHBOUR, and
the result is a number that appears nowhere in the run — plausible, wrong, and
committed by anyone who trusts the tool the failure message tells them to run.

``--check`` catches it, and CI runs ``--check``, so a corrupted row cannot merge.
This file is about ``--write`` not manufacturing one in the first place.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "readme_facts.py"

#: The row verbatim, as it stood when this was found.
BOARD_ROW = (
    "| Board: cards / splits / merges / noise / misrouted review "
    "| **9,134 / 2 / 0 / 0 / 0** |"
)
CARDS = re.compile(r"misrouted review \| \*\*([\d,]+) / \d+ / 0 / \d+ / 0\*\*")
SPLITS = re.compile(r"misrouted review \| \*\*[\d,]+ / ([\d,]+) / 0 / \d+ / 0\*\*")


def _load():
    """Import the tool by path — it is a script, not a package module.

    Same loader as ``test_expand_only_gate.py``, and registered in
    ``sys.modules`` before exec for the same reason stated there.
    """

    spec = importlib.util.spec_from_file_location("readme_facts", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_two_facts_on_one_line_do_not_corrupt_each_other() -> None:
    """cards 9,134 -> 9,132 then splits 2 -> 0, in that order.

    The order matters and is the real one: ``FACTS`` is iterated in declaration
    order and ``corpusCards`` is declared before ``corpusSplits``.
    """

    facts = _load()

    text = facts.substitute_at_group(BOARD_ROW, CARDS.search(BOARD_ROW), "9,132")
    assert "**9,132 / 2 / 0 / 0 / 0**" in text, text

    text = facts.substitute_at_group(text, SPLITS.search(text), "0")
    assert "**9,132 / 0 / 0 / 0 / 0**" in text, text


def test_the_old_approach_really_did_corrupt_it() -> None:
    """The negative control, so the test above cannot pass by coincidence.

    Without this, `substitute_at_group` could be replaced by anything that
    happens to work on this row and nothing would notice. This reproduces the
    exact 9,130 that shipped into the README twice on 2026-08-22.
    """

    def by_string_search(text: str, match: "re.Match[str]", want: str) -> str:
        replaced = match.group(0).replace(match.group(1), want, 1)
        return text[: match.start()] + replaced + text[match.end() :]

    text = by_string_search(BOARD_ROW, CARDS.search(BOARD_ROW), "9,132")
    assert "**9,132 / 2 / 0 / 0 / 0**" in text

    text = by_string_search(text, SPLITS.search(text), "0")
    # The "2" it finds first is the last digit of 9,132.
    assert "**9,130 / 2 / 0 / 0 / 0**" in text, text


def test_a_value_that_repeats_inside_its_own_match_is_still_written_once() -> None:
    """The general shape, not just the row it was found on.

    Any site whose captured value also appears earlier in the match hits this,
    including single-fact lines. Here the sentence names the number twice and
    only the captured one may move.
    """

    facts = _load()
    text = "0 of the 0 wrong verdicts sit above the gate."
    pattern = re.compile(r"0 of the ([\d,]+) wrong verdicts")
    out = facts.substitute_at_group(text, pattern.search(text), "72")
    assert out == "0 of the 72 wrong verdicts sit above the gate.", out


# ── unresolved conflict markers ──────────────────────────────────────────────
#
# The markers are BUILT rather than written out, so that this file is not itself
# a violation of the repo-wide scan it documents.

_LT = "<" * 7
_EQ = "=" * 7
_GT = ">" * 7
_PIPE = "|" * 7


def test_the_checker_refuses_a_file_mid_merge() -> None:
    """A conflicted README passed `--check` reporting that every fact agreed.

    The markers DUPLICATE the prose around them, so every number the checker
    looks for is still present and still correct — twice or three times over —
    and the reported site count goes UP, which reads as more coverage rather
    than as corruption. A README in that state was committed and pushed, and was
    caught afterwards by `git grep`, not by any gate.

    Well-formedness has to be established before agreement is even a meaningful
    question, which is what the pattern below is for.
    """
    tool = _load()

    real_conflict = (
        f"{_LT} HEAD\n"
        "**1461 tests collected, 0 skipped.**\n"
        f"{_PIPE} fe44834\n"
        "**1461 tests collected, 0 skipped.**\n"
        f"{_EQ}\n"
        "**1461 tests collected, 0 skipped.**\n"
        f"{_GT} origin/main\n"
    )
    assert tool._CONFLICT_MARKER.search(real_conflict), (
        "the exact shape git leaves behind was not recognised"
    )

    # Each of the four markers, alone, on its own line.
    for marker in (_LT, _EQ, _GT, _PIPE):
        assert tool._CONFLICT_MARKER.search(f"text\n{marker} label\nmore\n"), marker
        assert tool._CONFLICT_MARKER.search(f"text\n{marker}\nmore\n"), marker


def test_prose_that_merely_discusses_markers_is_not_one() -> None:
    """THE CONTROL. Without it the pattern could be satisfied by refusing everything.

    This repository's own README, this test file, and the checker's source all
    talk about conflict markers. A rule that fired on the words would make the
    documentation unshippable, so it is anchored to the start of a line and
    requires the run to be exactly seven characters.
    """
    tool = _load()
    for benign in (
        "a diff uses <<< and >>> to mark hunks\n",
        "  " + _LT + " indented, so not a marker\n",
        "text " + _LT + " mid-line\n",
        ("<" * 6) + " six is not seven\n",
        ("<" * 8) + " eight is not seven\n",
        "compare a <= b and c >= d\n",
    ):
        assert not tool._CONFLICT_MARKER.search(benign), benign


# ── the checker itself, invoked ──────────────────────────────────────────────
#
# THE TWO TESTS ABOVE ASSERT A REGEX, NOT A CHECK. They ask
# `_CONFLICT_MARKER.search(...)` questions directly, so they stay green with the
# pattern intact and the code that USES it deleted — which is exactly the state
# #538 was reported for, one level up: a gate that passes on corrupted input
# because it only asks about the parts it knows to look for. Proved by an
# independent audit on 2026-08-27: removing the `load()` wiring from
# `readme_facts.run` left all five tests in this file passing while `--check`
# went back to calling a conflicted README "all agree with the code".
#
# So the checker is run. `REPO` is a module global read at call time, and the
# tree below is the real repository with every top-level entry symlinked into
# a temporary directory — every fact still computes off the real source — and
# README.md alone replaced by a real copy we are free to corrupt. Nothing
# writes to the working tree.


def _mirror_repo(tmp_path, readme_text: str):
    """The real repo, with README.md swapped for `readme_text`.

    Symlinks rather than copies: `resolve_facts()` runs before the first
    `load()` and computes static facts by parsing the source under `REPO`, so a
    tree that is missing `backend/` would fail for a reason that has nothing to
    do with conflict markers, and the test would pass for the wrong reason.
    """

    root = tmp_path / "repo"
    root.mkdir()
    for entry in REPO_ROOT.iterdir():
        if entry.name != "README.md":
            (root / entry.name).symlink_to(entry)
    (root / "README.md").write_text(readme_text, encoding="utf-8")
    return root


#: The shape `git merge` leaves: the fact line survives, three times over.
def _conflicted(readme: str) -> str:
    line = "**1,461 tests collected, 0 skipped.**"
    return (
        f"{_LT} HEAD\n{line}\n{_PIPE} d41dcf0\n{line}\n{_EQ}\n{line}\n"
        f"{_GT} origin/main\n" + readme
    )


def test_check_refuses_a_readme_that_begins_mid_merge(tmp_path, capsys) -> None:
    """`--check` must exit 1, and say why, on a file it can still 'agree' with.

    Every number is present and correct in a conflicted README — the markers
    DUPLICATE the prose — and the site count goes UP, which reads as more
    coverage. So a checker that only compares numbers reports success on it.
    """

    tool = _load()
    pristine = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    tool.REPO = _mirror_repo(tmp_path, _conflicted(pristine))

    with pytest.raises(SystemExit) as exit_info:
        tool.run("check")

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "unresolved conflict marker" in err, err
    assert "README.md:1" in err, err


def test_the_same_tree_with_the_merge_finished_is_not_called_conflicted(
    tmp_path, capsys
) -> None:
    """THE CONTROL, and it is the whole point of the pair.

    Without it the test above is satisfied by a checker that refuses
    everything, and by a mirrored tree so broken that any input fails. The only
    difference between the two trees is the seven-character runs at the top.

    It deliberately does NOT require a clean exit. Whether every number in the
    README currently agrees with the code is a different gate, run by CI on
    every push; borrowing it here would red this file for a reason that has
    nothing to do with merge markers, and a control that fires on unrelated
    drift stops being read.
    """

    tool = _load()
    pristine = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    tool.REPO = _mirror_repo(tmp_path, pristine)

    try:
        tool.run("check")
    except SystemExit:
        pass
    err = capsys.readouterr().err
    assert "conflict marker" not in err, err


def test_write_refuses_a_readme_that_begins_mid_merge(tmp_path, capsys) -> None:
    """`--write` is the command the failure message tells you to run.

    THE FIXTURE CARRIES A WRONG NUMBER ON PURPOSE, and the first version of this
    test did not. With every number already correct, `--write` has nothing to
    rewrite and leaves the file alone for a reason that has nothing to do with
    the markers — so the test passed against a tool that would have corrupted a
    file it was given real work to do. The number below is deliberately wrong so
    the write is actually attempted, and the assertion compares the WHOLE file
    rather than its first line: a rewrite replaces a captured number in the
    middle of the text and never touches the leading marker, so
    ``startswith(_LT)`` is true whether or not the file was written.

    That the refusal now happens BEFORE the write is a change to
    ``readme_facts.run`` in this commit. Until it, the tool wrote every dirty
    file and then raised, so on a half-merged README it corrected a number
    inside a conflict hunk, printed "rewrote 1 number", and the refusal was the
    exit code only. Found by an independent verification pass on 2026-08-27
    which reproduced it on unmutated `main`.
    """

    tool = _load()
    pristine = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    wrong = CARDS.sub(
        lambda m: m.group(0).replace(m.group(1), "7,654,321", 1), pristine, count=1
    )
    assert wrong != pristine, "the board row moved; this fixture no longer bites"
    conflicted = _conflicted(wrong)
    root = _mirror_repo(tmp_path, conflicted)
    tool.REPO = root

    with pytest.raises(SystemExit) as exit_info:
        tool.run("write")

    assert exit_info.value.code == 1
    assert "unresolved conflict marker" in capsys.readouterr().err
    assert (root / "README.md").read_text(encoding="utf-8") == conflicted, (
        "--write refused, but not before rewriting the half-merged file"
    )


def test_write_still_writes_when_the_merge_is_finished(tmp_path) -> None:
    """THE CONTROL for the refusal above: refusing everything is not the fix.

    Same deliberately-wrong number, no markers. `--write` must correct it.
    """

    tool = _load()
    pristine = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    wrong = CARDS.sub(
        lambda m: m.group(0).replace(m.group(1), "7,654,321", 1), pristine, count=1
    )
    root = _mirror_repo(tmp_path, wrong)
    tool.REPO = root

    try:
        tool.run("write")
    except SystemExit:  # an unrelated number may also disagree; not this gate
        pass
    after = (root / "README.md").read_text(encoding="utf-8")
    assert "7,654,321" not in after, "--write left the wrong number in place"


# ── the recording cannot hide a skip, and the static parse models collection ──
#
# Issue #351. Three separable holes, each with its own cases below:
#
#   1. `--record` wrote whatever it observed. On a machine without Docker or
#      without the test extras, five `*_postgres` modules skip, skipped tests
#      are still COLLECTED, so `testsCollected >= testFunctions` still held and
#      the page's guarantee slid from "0 skipped" to "N skipped" with every gate
#      green. The documented local recipe produced exactly that artifact.
#   2. The static parse used `ast.walk` and counted things pytest never
#      collects. Diffing it against `pytest --collect-only` over the real tree
#      found TWO causes, not the one the issue named.
#   3. The file's own docstring claimed "a recorded figure cannot go stale
#      without a static one noticing", which the one-sided invariant does not
#      deliver. That claim is corrected and the drift is now printed instead.


GREEN = {
    "passed": 1768,
    "failed": 0,
    "skipped": 0,
    "errors": 0,
    "exitCode": 0,
    "allGreen": True,
    "dockerAvailable": True,
}


def test_a_clean_provisioned_run_is_recordable() -> None:
    """The positive control. Without it every refusal below proves nothing."""

    assert _load().refuse_reason(GREEN) is None


def test_a_run_without_docker_is_refused_even_when_nothing_skipped() -> None:
    """The #351 case exactly: 0 skipped is not evidence the suite was whole.

    Docker unreachable and `skipped == 0` is the combination that reads as a
    perfect run from every angle the old code looked from.
    """

    reason = _load().refuse_reason({**GREEN, "dockerAvailable": False})
    assert reason is not None
    assert "Docker" in reason


def test_a_run_that_skipped_is_refused() -> None:
    reason = _load().refuse_reason({**GREEN, "skipped": 53})
    assert reason is not None
    assert "53" in reason and "skip" in reason.lower()


def test_a_red_run_is_refused() -> None:
    reason = _load().refuse_reason(
        {**GREEN, "failed": 2, "exitCode": 1, "allGreen": False}
    )
    assert reason is not None
    assert "not green" in reason


def test_the_refusal_happens_before_the_file_is_written(tmp_path, capsys) -> None:
    """The whole point: a refusal after the write changes only the exit code.

    The artifact must not exist afterwards — not "must be unchanged", which a
    write followed by a raise would also satisfy on a machine where the file
    happened to be identical.
    """

    rf = _load()
    target = tmp_path / "docs" / "readme-facts.json"
    artifact = {"recordedAt": "2026-08-28", "suiteOutcome": {**GREEN, "skipped": 53}}

    with pytest.raises(SystemExit) as excinfo:
        rf.write_artifact(artifact, target)

    assert excinfo.value.code == 1
    assert not target.exists(), "the refusal let the artifact reach the disk"
    assert "refusing to record" in capsys.readouterr().err


def test_a_clean_run_still_reaches_the_disk(tmp_path) -> None:
    """Directional control for the case above: the refusal is not unconditional."""

    rf = _load()
    target = tmp_path / "docs" / "readme-facts.json"
    rf.write_artifact({"recordedAt": "2026-08-28", "suiteOutcome": GREEN}, target)
    assert target.exists()


# ── the static parse ──────────────────────────────────────────────────────

SYNTHETIC = '''
import pytest


@pytest.fixture
def test_session():
    """Named like a test, collected by nobody."""
    yield 1


@pytest.fixture(scope="module")
def test_engine():
    yield 2


def test_a_real_one():
    def test_a_nested_helper():
        pass
    test_a_nested_helper()


def test_shadowed():
    pass


def test_shadowed():
    pass


class TestAGroup:
    def test_a_method(self):
        pass


class NotATestClass:
    def test_not_collected_here(self):
        pass
'''


def test_the_parse_counts_what_pytest_would_collect(tmp_path) -> None:
    """Five distinct AST-only shapes, one fixture per real defect found.

    `ast.walk` over this module returns 8. pytest collects 3:
    `test_a_real_one`, `test_shadowed` (once), and `TestAGroup::test_a_method`.
    """

    module = tmp_path / "test_synthetic.py"
    module.write_text(SYNTHETIC)
    assert _load().collectable_tests(module) == {
        "test_a_real_one",
        "test_shadowed",
        "test_a_method",
    }


def test_the_old_walk_really_did_overcount_this(tmp_path) -> None:
    """The negative control: prove the shapes above are actually adversarial.

    Without this, the assertion above passes just as happily against a parser
    that was never wrong.
    """

    import ast

    module = tmp_path / "test_synthetic.py"
    module.write_text(SYNTHETIC)
    walked = sum(
        1
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )
    assert walked == 8, f"expected the old parse to see 8, saw {walked}"


def test_a_fixture_is_not_a_test_whichever_way_it_is_spelled(tmp_path) -> None:
    """`@pytest.fixture`, `@fixture` and `@pytest_asyncio.fixture`, called or bare.

    A threshold needs a case sitting on it and a set needs one per member; this
    is the set.
    """

    module = tmp_path / "test_spellings.py"
    module.write_text(
        "import pytest\n"
        "import pytest_asyncio\n"
        "from pytest import fixture\n"
        "\n"
        "@pytest.fixture\n"
        "def test_a(): ...\n"
        "\n"
        "@fixture\n"
        "def test_b(): ...\n"
        "\n"
        "@pytest_asyncio.fixture\n"
        "def test_c(): ...\n"
        "\n"
        "@pytest.fixture(scope='session')\n"
        "def test_d(): ...\n"
        "\n"
        "def test_e(): ...\n"
    )
    assert _load().collectable_tests(module) == {"test_e"}


def test_no_test_module_defines_the_same_test_twice() -> None:
    """A shadowed test is dead code that still reads as coverage.

    `test_hold_reason_and_employer_gaps.py` carried a byte-identical copy of
    `test_the_web_knows_every_reason_this_module_can_emit`; Python bound the
    second and the first had never run. Nothing said so, and the published
    count included it.
    """

    import ast
    from collections import Counter

    rf = _load()
    shadowed: dict[str, list[str]] = {}
    for path in rf.test_modules():
        names = Counter()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
                and not rf._is_fixture(node)
            ):
                names[node.name] += 1
        dupes = [n for n, c in names.items() if c > 1]
        if dupes:
            shadowed[path.name] = dupes

    assert shadowed == {}, f"tests defined twice, so the first never runs: {shadowed}"


# ── staleness is visible, not fatal ───────────────────────────────────────


def test_a_fresh_recording_produces_no_drift_note() -> None:
    rf = _load()
    fresh = {
        "recordedAt": "2026-08-28",
        "recordedCommit": "0" * 40,
        "testFunctionsAtRecord": rf.test_functions(),
        "testModulesAtRecord": len(rf.test_modules()),
    }
    assert rf.staleness_note(fresh) is None


def test_a_moved_suite_is_named_in_the_note() -> None:
    rf = _load()
    now = rf.test_functions()
    note = rf.staleness_note(
        {
            "recordedAt": "2026-08-24",
            "recordedCommit": "d2c50c4" + "0" * 33,
            "testFunctionsAtRecord": now - 148,
            "testModulesAtRecord": len(rf.test_modules()) - 12,
        }
    )
    assert note is not None
    assert str(now - 148) in note and str(now) in note


def test_an_artifact_predating_the_field_says_so_rather_than_guessing() -> None:
    note = _load().staleness_note({"recordedAt": "2026-08-15"})
    assert note is not None and "predates" in note


def test_pytest_itself_agrees_with_the_parse(tmp_path) -> None:
    """Ask pytest, rather than asserting what pytest would say.

    Every case above encodes MY model of collection. This one runs the real
    collector over the same adversarial module and requires the two to match,
    so the model cannot drift from the tool it is modelling.
    """

    import subprocess
    import sys as _sys

    module = tmp_path / "test_synthetic.py"
    module.write_text(SYNTHETIC)

    proc = subprocess.run(
        [
            _sys.executable, "-m", "pytest", str(module),
            "--collect-only", "-q", "-p", "no:cacheprovider",
            "--override-ini=addopts=", "--rootdir", str(tmp_path),
        ],
        capture_output=True, text=True, cwd=tmp_path, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]

    collected = {
        line.partition("::")[2].split("[")[0].split("::")[-1]
        for line in proc.stdout.splitlines()
        if "::" in line
    }
    assert collected, f"the collector returned nothing:\n{proc.stdout}"
    assert collected == _load().collectable_tests(module)


def test_the_recorded_machine_names_the_interpreter_that_ran_the_suite(tmp_path) -> None:
    """`--record` runs under `python3`; the suite runs under `.venv311/bin/python`.

    Those are different interpreters here — 3.14.4 and 3.11.14 — and the field
    reported the SCRIPT's version while the counts and coverage came from the
    venv's. It had always been capable of that and only began lying once
    `python3` on PATH stopped being a 3.11, so nothing in the artifact's own
    history would have shown it.

    The stand-in interpreter is deliberate: comparing two real interpreters
    would skip on a machine where they happen to match, and a skip is green —
    which is the defect this whole file is about.
    """

    import platform
    import stat
    import sys as _sys

    rf = _load()

    # positive control: asked about THIS interpreter, it says what THIS is
    assert rf.interpreter_version(_sys.executable) == platform.python_version()

    shim = tmp_path / "pretend-python"
    shim.write_text("#!/bin/sh\necho 9.9.9\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    assert platform.python_version() != "9.9.9"
    assert rf.interpreter_version(str(shim)) == "9.9.9", (
        "the version is being read from the running script rather than from "
        "the interpreter it was handed"
    )
