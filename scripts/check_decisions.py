#!/usr/bin/env python3
"""Refuse a decision record whose own claims have gone stale.

`docs/DECISIONS.md` records decisions whose rejected alternative is attractive
and whose reason is invisible from the code. A prose file cannot stop a
regression — only a gate can — so this script gates the part of the file that
IS mechanically checkable, and the document's header states plainly what is
left over.

WHAT IT CHECKS

1.  **Shape.** Every ``## DEC-nnn`` entry carries all seven fields, exactly
    once each, and ``Status:`` reads ``active (YYYY-MM-DD)`` or
    ``superseded by DEC-nnn (YYYY-MM-DD)``. Ids are unique.
2.  **The gate named actually exists.** Every path in an ``Enforced by:`` line
    is a tracked file. An entry claiming enforcement by a test that was deleted
    is the failure this repository keeps re-finding — a check that cannot fail,
    wearing a citation.
3.  **Markers point both ways.** Every path in a ``Markers:`` line exists AND
    contains the entry's own ``DEC-nnn`` literal; and every ``DEC-nnn`` marker
    found anywhere in the tracked tree has an entry here. One direction alone
    is unchecked coverage: forward-only misses a marker for a deleted entry,
    reverse-only misses an entry whose marker was edited away.

WHAT IT CANNOT CHECK, and the header of the document says so rather than
implying otherwise:

*   a decision nobody wrote down;
*   a reversal that edits the code around a surviving marker, leaving the
    marker true about its location and false about its subject;
*   whether the prose is still accurate. Only a reader can do that, which is
    why every entry carries a ``Valid while:`` line naming its falsifier.

Exit 0 when the record agrees with the tree, 1 when it does not. Stdlib only,
no network, no install — the same contract as ``check_test_data.py``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "DECISIONS.md"

#: The seven fields. Order is not enforced -- presence and uniqueness are --
#: because a reader scanning for `Enforced by:` should not have to know where
#: in the block it sits.
FIELDS = (
    "Status",
    "Claim",
    "Why",
    "Moved away from",
    "Enforced by",
    "Valid while",
    "Markers",
)

ENTRY = re.compile(r"^## (DEC-\d{3})\b(.*)$", re.MULTILINE)
STATUS = re.compile(r"^(active|superseded by DEC-\d{3}) \(\d{4}-\d{2}-\d{2}\)$")
MARKER = re.compile(r"\bDEC-\d{3}\b")

#: A path-shaped token: at least one `/`, a dot in the last segment, and an
#: optional `:NNN` line suffix that is stripped before the tree is consulted.
#: Deliberately narrow -- prose in these fields mentions symbols and issue
#: numbers, and a looser reader would demand that `applications.py:2197` exist
#: as a file.
PATH = re.compile(r"(?<![\w/.])((?:[\w.@+-]+/)+[\w.@+-]+\.[A-Za-z0-9]+)(?::\d+)?")

#: The exact sentence an entry uses when nothing enforces it. It is a fixed
#: string rather than a pattern so that "mostly enforced" cannot be spelled
#: into existence: an entry either names a file that exists, or says this.
NO_GATE = "nothing enforces this; prose only"


def tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return set(out.split())


def parse(text: str) -> list[dict[str, object]]:
    """Split the document into entries. Anything above the first is preamble."""
    entries: list[dict[str, object]] = []
    marks = list(ENTRY.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end() : end]
        fields: dict[str, list[str]] = {}
        for line in body.splitlines():
            for f in FIELDS:
                if line.startswith(f + ":"):
                    fields.setdefault(f, []).append(line[len(f) + 1 :].strip())
        entries.append(
            {
                "id": m.group(1),
                "title": m.group(2).strip(),
                "line": text[: m.start()].count("\n") + 1,
                "fields": fields,
                "body": body,
            }
        )
    return entries


def check(text: str, tracked: set[str], tree: Path) -> list[str]:
    problems: list[str] = []
    entries = parse(text)

    if not entries:
        return ["docs/DECISIONS.md contains no DEC entries — nothing was checked."]

    seen: dict[str, int] = {}
    for e in entries:
        eid, line, fields = e["id"], e["line"], e["fields"]  # type: ignore[assignment]
        where = f"{eid} (line {line})"

        if eid in seen:
            problems.append(f"{where}: duplicate id, first seen at line {seen[eid]}.")
        seen[eid] = line  # type: ignore[index]

        for f in FIELDS:
            got = fields.get(f, [])  # type: ignore[union-attr]
            if not got:
                problems.append(f"{where}: missing required field '{f}:'.")
            elif len(got) > 1:
                problems.append(f"{where}: field '{f}:' appears {len(got)} times.")

        for s in fields.get("Status", []):  # type: ignore[union-attr]
            if not STATUS.match(s):
                problems.append(
                    f"{where}: Status must read 'active (YYYY-MM-DD)' or "
                    f"'superseded by DEC-nnn (YYYY-MM-DD)', got {s!r}."
                )

        for value in fields.get("Enforced by", []):  # type: ignore[union-attr]
            paths = [p.group(1) for p in PATH.finditer(value)]
            if value.strip() == NO_GATE:
                continue
            if not paths:
                problems.append(
                    f"{where}: 'Enforced by:' names no file and is not the exact "
                    f"words {NO_GATE!r}."
                )
            for p in paths:
                if p not in tracked:
                    problems.append(
                        f"{where}: 'Enforced by:' cites {p}, which is not a tracked "
                        f"file. A gate that no longer exists is not a gate."
                    )

        for value in fields.get("Markers", []):  # type: ignore[union-attr]
            if value.strip() == "none":
                continue
            paths = [p.group(1) for p in PATH.finditer(value)]
            if not paths:
                problems.append(f"{where}: 'Markers:' names no file and is not 'none'.")
            for p in paths:
                if p not in tracked:
                    problems.append(f"{where}: 'Markers:' cites {p}, which is not tracked.")
                    continue
                try:
                    content = (tree / p).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    problems.append(f"{where}: 'Markers:' cites {p}, which could not be read.")
                    continue
                if eid not in content:
                    problems.append(
                        f"{where}: {p} is listed as a marker but does not contain "
                        f"the literal {eid}."
                    )

    # The reverse direction. A marker in the tree with no entry here is a
    # pointer into a document that will not answer.
    known = {e["id"] for e in entries}
    for p in sorted(tracked):
        if p == "docs/DECISIONS.md" or p == "scripts/check_decisions.py":
            continue
        try:
            content = (tree / p).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for found in sorted(set(MARKER.findall(content))):
            if found not in known:
                problems.append(
                    f"{p} carries the marker {found}, which has no entry in "
                    f"docs/DECISIONS.md."
                )
    return problems


def main() -> int:
    if not DOC.exists():
        print(f"decisions gate: {DOC} does not exist.", file=sys.stderr)
        return 1
    problems = check(DOC.read_text(encoding="utf-8"), tracked_files(), REPO_ROOT)
    n = len(parse(DOC.read_text(encoding="utf-8")))
    if problems:
        print(f"decisions gate: {n} entries, {len(problems)} problem(s).\n")
        for p in problems:
            print(f"  {p}")
        print(
            "\nFAIL — docs/DECISIONS.md disagrees with the tree. The document is a "
            "record, not a wish: fix the entry or fix the code it points at."
        )
        return 1
    print(f"decisions gate: {n} entries, all fields present, every gate and marker resolves.")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
