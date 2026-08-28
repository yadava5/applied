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
