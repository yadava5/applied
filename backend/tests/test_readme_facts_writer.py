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
