#!/usr/bin/env python3
"""Refuse a new sender address that is not a reserved, un-routable domain.

WHY THIS EXISTS

This repository is public, and its fixtures grew by precedent. Issue #593 found
an ATS relay address, verbatim subject lines, real requisition numbers and real
role titles spread across test modules, product source and six issue bodies —
none of it a credential, none of it about a third party, all of it job-search
information about one identifiable person, and none of it the result of a
decision. Each new test copied the shape of the last one, because no rule
existed to cite.

`docs/TEST_DATA_POLICY.md` is the rule. This is what makes it fail.

WHAT IT DOES NOT DO, DELIBERATELY

It carries no denylist. A list of the exact strings this gate exists to forbid
would republish every one of them, in a new tracked file, in a repository that
is public — which is the failure it is supposed to prevent, committed by the
prevention. So the check is on SHAPE: an address whose domain is not reserved
for documentation and testing is flagged, whatever it says.

It also does not scrub. The material already published stays exactly where it
is; several of these modules are graded against real ATS wordings and say so in
their docstrings, and rewriting the prose around a deletion would ship a
provenance claim that is no longer true. See "The baseline is a ratchet, not a
backlog" in the policy document. This gate draws the line at NEW material.

HOW IT FAILS

Per-file counts, ratcheted against `scripts/test_data_baseline.json`. A count
that goes UP fails. A scanned file that is not in the baseline at all fails. A
count that goes DOWN does not fail — it is reported, and lowering the recorded
number is a deliberate act with a reason in the commit body, not housekeeping.

The baseline records paths and counts. It never records the matched strings,
for the same reason there is no denylist.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

#: Directories whose tracked files are scanned. `backend/tests/corpus/` is a
#: subset of the first entry and needs no line of its own.
#:
#: Product source is in here on purpose. Issue #593's requisition numbers were
#: not confined to tests — they were in `jobtracker/cloud/pipeline.py` and
#: `classifier/rules.py` — so a tests-only scope would have measured the half of
#: the problem that was easiest to see.
SCAN_ROOTS = (
    "backend/tests/",
    "backend/jobtracker/",
    "apps/web/tests/",
)

#: RFC 2606 §2 reserves the `.test`, `.example`, `.invalid` and `.localhost`
#: top-level domains, and §3 reserves `example.com`, `example.net` and
#: `example.org`; RFC 6761 §6.3 makes `.localhost` un-routable by definition.
#: Nothing in this set can ever reach a real mailbox, which is the entire
#: property being asserted — so the allowlist is citable rather than a matter of
#: taste, and it is closed. A domain that merely *looks* invented (`acme.com`,
#: `northwind.com`) is a real registration owned by somebody else and does not
#: belong here.
RESERVED_TLDS = (".test", ".example", ".invalid", ".localhost")
RESERVED_DOMAINS = frozenset(
    {"example.com", "example.net", "example.org", "localhost"}
)
#: RFC 2606 §3 reserves those second-level names *and everything under them*, so
#: `email.careers.example.com` is as un-routable as the bare name. Matching the
#: bare name only is not a near-miss, it is an inverted gate: it reds on
#: `donotreply@email.careers.example.com` — the direct `.com` analogue of the
#: `email.careers.example.test` this repository already uses and this gate's own
#: failure message recommends — and the reader is then told by that message that
#: `example.com` is fine. Caught in review before merge.
RESERVED_SUFFIXES = tuple("." + d for d in ("example.com", "example.net", "example.org"))

#: Deliberately loose on the left of the `@` and strict on the right: the point
#: is to notice an address at all, not to validate one. Anchoring the TLD at two
#: or more letters keeps `@pytest.fixture` and `@playwright/test` out.
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

DEFAULT_BASELINE = Path("scripts/test_data_baseline.json")
POLICY_DOC = "docs/TEST_DATA_POLICY.md"


def is_allowed(domain: str) -> bool:
    """True when `domain` is reserved by RFC and cannot route anywhere."""

    domain = domain.lower().rstrip(".")
    if domain in RESERVED_DOMAINS:
        return True
    return domain.endswith(RESERVED_TLDS) or domain.endswith(RESERVED_SUFFIXES)


def tracked_files(repo_root: Path) -> list[str]:
    """Tracked paths under `SCAN_ROOTS`, from git — never a filesystem walk.

    A walk reaches `node_modules`, `.venv*`, `.next` and `__pycache__`, none of
    which is this repository's material and all of which are full of addresses.
    A gate that reports hundreds of hits it does not own is a gate that gets
    turned off.
    """

    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *SCAN_ROOTS],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.split("\0") if p)


def count_file(path: Path) -> int:
    """Non-reserved addresses in one file, counted by occurrence.

    The whole file, not just its string literals: the most recent leak came
    through a module DOCSTRING sitting above fixtures that had been correctly
    sanitised. Comments and docstrings are published surfaces too.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    return sum(
        1
        for match in EMAIL.finditer(text)
        if not is_allowed(match.group(0).rsplit("@", 1)[1])
    )


def scan(repo_root: Path) -> dict[str, int]:
    """Per-file counts for every scanned file that has at least one hit."""

    counts: dict[str, int] = {}
    for rel in tracked_files(repo_root):
        n = count_file(repo_root / rel)
        if n:
            counts[rel] = n
    return counts


def load_baseline(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data["counts"].items()}


def write_baseline(path: Path, counts: dict[str, int]) -> None:
    path.write_text(
        json.dumps(
            {
                "_README": [
                    "Per-file counts of sender addresses on domains that are not",
                    "RFC-reserved, under the roots scripts/check_test_data.py scans.",
                    "Paths and counts ONLY — never the matched strings, or this file",
                    "would republish the material the gate exists to stop.",
                    "This is a RATCHET, not a backlog. A number going up fails. A",
                    f"number going down is allowed but is never routine — see {POLICY_DOC}.",
                    "Regenerate with: python3 scripts/check_test_data.py --write-baseline",
                ],
                "counts": dict(sorted(counts.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def report(counts: dict[str, int], baseline: dict[str, int]) -> int:
    """Print the verdict. Returns a process exit code."""

    new_files = sorted(set(counts) - set(baseline))
    grown = sorted(
        p for p in counts if p in baseline and counts[p] > baseline[p]
    )
    shrunk = sorted(
        p for p in counts if p in baseline and counts[p] < baseline[p]
    )
    cleared = sorted(p for p in baseline if p not in counts)

    total = sum(counts.values())
    print(
        f"test-data gate: {total} non-reserved addresses across "
        f"{len(counts)} tracked files (baseline {sum(baseline.values())} "
        f"across {len(baseline)})."
    )

    if not new_files and not grown:
        for path in shrunk:
            print(f"  down: {path} {baseline[path]} -> {counts[path]}")
        for path in cleared:
            print(f"  cleared: {path} {baseline[path]} -> 0")
        if shrunk or cleared:
            print(
                "\nCounts went DOWN. That is allowed and does not fail — but it is\n"
                "not routine. If a fixture was legitimately rewritten, lower the\n"
                "baseline with --write-baseline and say why in the commit body.\n"
                f"If you are 'tidying up' published material, read {POLICY_DOC}\n"
                "first: this baseline is a ratchet, not a backlog, and several of\n"
                "these modules make provenance claims that a scrub would falsify."
            )
        print("OK")
        return 0

    print("\nFAIL — new sender addresses on domains that are not RFC-reserved.\n")
    if new_files and cleared:
        # Printed only when both halves of a rename are present, so it is never
        # noise on a failure it does not explain. A gate whose message says
        # things that do not apply is one people stop reading.
        print(
            "  (A `new file` beside a `cleared` below with the same count is a\n"
            "   RENAME, not an addition. Re-record the baseline and say so.)\n"
        )
        for path in cleared:
            print(f"  cleared: {path} {baseline[path]} -> 0")
    for path in new_files:
        print(f"  new file: {path} ({counts[path]})")
    for path in grown:
        print(f"  count up: {path} {baseline[path]} -> {counts[path]}")

    print(
        f"""
Every address in a fixture, docstring, comment or sample must sit on a domain
that cannot route: anything under `.test`, `.example` or `.invalid`, or under
`example.com` / `.net` / `.org` — `email.careers.example.com` counts. Copy the
shape in
`backend/tests/test_dismissed_card_does_not_settle_its_mail.py` — invented
employers, `careers@halberd.test`, `careers@ironvale.example.test`.

If the real wording is the evidence and only the particulars can change, keep
the wording and invent the particulars, then say so in the docstring so the
provenance claim stays true.

If this address genuinely has to be real — product logic that must recognise a
named ATS relay, say — raise the baseline on purpose:

    python3 scripts/check_test_data.py --write-baseline

and state in the commit body which file went up and why.

The rule, and why nothing already published is being deleted: {POLICY_DOC}"""
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="regenerate the baseline from the current tree instead of checking",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="tree to scan (default: the repository this script lives in)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=f"baseline file (default: <repo-root>/{DEFAULT_BASELINE})",
    )
    args = parser.parse_args(argv)

    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    baseline_path = args.baseline or repo_root / DEFAULT_BASELINE

    counts = scan(repo_root)

    if args.write_baseline:
        write_baseline(baseline_path, counts)
        print(
            f"Wrote {baseline_path}: {sum(counts.values())} addresses across "
            f"{len(counts)} files."
        )
        return 0

    if not baseline_path.exists():
        print(
            f"FAIL — no baseline at {baseline_path}. Generate one with "
            "--write-baseline and commit it."
        )
        return 1

    return report(counts, load_baseline(baseline_path))


if __name__ == "__main__":
    sys.exit(main())
