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

Per-file COUNT plus per-file DIGEST, compared against
`scripts/test_data_baseline.json`. Any divergence in either direction fails:
a count up, a count down, a file the baseline does not list, a baselined file
that has gone to zero, or — the case the first cut of this gate missed — a file
whose count is unchanged but whose SET of addresses is not. Swapping one
published address for a brand-new one nets to zero and was invisible until the
digest landed (issue #615).

Down fails too, on purpose. Under a ratchet that only ratcheted up, slack
accumulated silently: remove three addresses this month, add three different
ones next month, green both times. Now every change to this material — adding,
removing or rewriting — has to arrive as a deliberate `--write-baseline` commit
with a reason in its body. The audit is that commit; this gate is what makes it
impossible to skip.

A file that cannot be read or decoded FAILS rather than counting as zero. A
skip that passes is the same defect as everything above.

The baseline records paths, counts and digests. It never records the matched
strings, for the same reason there is no denylist — and see "Why a digest is
allowed where a literal is not" in the policy document for why a truncated hash
does not reintroduce the problem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

#: Directories whose tracked files are scanned. `backend/tests/corpus/` is a
#: subset of the first entry and needs no line of its own.
#:
#: Product source is in here on purpose. Issue #593's requisition numbers were
#: not confined to tests — they were in `jobtracker/cloud/pipeline.py` and
#: `classifier/rules.py` — so a tests-only scope would have measured the half of
#: the problem that was easiest to see.
#:
#: `ml/` was added for #615. `ml/demo/space/jobtracker/` is a *generated copy*
#: of `backend/jobtracker/`, written by `ml/demo/package_space.py` and committed,
#: so the same material was tracked twice and scanned once. #593's corrected
#: inventory named `ml/demo/space/jobtracker/classifier/rules.py` explicitly,
#: hours before the first cut of this gate merged without it — a blind spot
#: nobody had chosen. Adding it also means repackaging the Space moves the
#: baseline; that is correct, and the policy says so.
SCAN_ROOTS = (
    "backend/tests/",
    "backend/jobtracker/",
    "apps/web/tests/",
    "ml/",
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

#: Hex characters of SHA-256 kept per file. Sixteen is 64 bits — far past any
#: accidental collision across a baseline of fewer than a hundred files, and
#: short enough that the baseline stays readable in a diff.
DIGEST_CHARS = 16

DEFAULT_BASELINE = Path("scripts/test_data_baseline.json")
POLICY_DOC = "docs/TEST_DATA_POLICY.md"


class Finding(NamedTuple):
    """What one file contributes: how many addresses, and which ones — hashed."""

    count: int
    digest: str


class Skipped(NamedTuple):
    """A tracked file the scanner could not read. Never silently a zero."""

    path: str
    reason: str


def is_allowed(domain: str) -> bool:
    """True when `domain` is reserved by RFC and cannot route anywhere."""

    domain = domain.lower().rstrip(".")
    if domain in RESERVED_DOMAINS:
        return True
    return domain.endswith(RESERVED_TLDS) or domain.endswith(RESERVED_SUFFIXES)


def digest_of(addresses: Iterable[str]) -> str:
    """Truncated SHA-256 over the sorted, lower-cased, de-duplicated set.

    Lower-case FIRST, then de-duplicate, then sort — in that order. Sorting the
    raw matches and lowering afterwards would keep `A@x.io` and `a@x.io` as two
    entries and make the digest depend on the order they appear in the file,
    which turns a formatting change into a red gate.
    """

    normalised = sorted({address.lower() for address in addresses})
    packed = "\n".join(normalised).encode("utf-8")
    return hashlib.sha256(packed).hexdigest()[:DIGEST_CHARS]


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


def scan_file(path: Path) -> Finding:
    """Non-reserved addresses in one file: count by occurrence, digest by set.

    The whole file, not just its string literals: the most recent leak came
    through a module DOCSTRING sitting above fixtures that had been correctly
    sanitised. Comments and docstrings are published surfaces too.

    Raises `UnicodeDecodeError` or `OSError` rather than returning zero. This
    used to swallow both, so an unreadable file read as clean — a skip that
    counts as a pass, which is the same defect family as the count-only ratchet
    it sat next to (#615).

    The count is by OCCURRENCE and the digest is over the DE-DUPLICATED set, so
    the two answer different questions on purpose: adding a second copy of an
    address already in the file moves the count and not the digest, and swapping
    one address for another moves the digest and not the count. Either fails.
    """

    text = path.read_text(encoding="utf-8")
    matched = [
        match.group(0)
        for match in EMAIL.finditer(text)
        if not is_allowed(match.group(0).rsplit("@", 1)[1])
    ]
    return Finding(len(matched), digest_of(matched))


def scan(repo_root: Path) -> tuple[dict[str, Finding], list[Skipped]]:
    """Findings for every scanned file with at least one hit, plus the skips."""

    findings: dict[str, Finding] = {}
    skipped: list[Skipped] = []
    for rel in tracked_files(repo_root):
        try:
            finding = scan_file(repo_root / rel)
        except (UnicodeDecodeError, OSError) as exc:
            skipped.append(Skipped(rel, f"{type(exc).__name__}: {exc}"))
            continue
        if finding.count:
            findings[rel] = finding
    return findings, skipped


def load_baseline(path: Path) -> dict[str, Finding]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "files" not in data:
        raise SystemExit(
            f"FAIL — {path} is in the pre-#615 format (counts only, no digests).\n"
            "A count alone cannot see a same-count address swap. Regenerate it:\n"
            "    python3 scripts/check_test_data.py --write-baseline\n"
            f"and say in the commit body why the numbers moved. See {POLICY_DOC}."
        )
    return {
        str(path_): Finding(int(entry["count"]), str(entry["digest"]))
        for path_, entry in data["files"].items()
    }


def write_baseline(path: Path, findings: dict[str, Finding]) -> None:
    path.write_text(
        json.dumps(
            {
                "_README": [
                    "Per-file counts AND digests of sender addresses on domains that",
                    "are not RFC-reserved, under the roots scripts/check_test_data.py",
                    "scans. The digest is a truncated SHA-256 over the sorted,",
                    "lower-cased, de-duplicated set of matches in that file.",
                    "No matched string is ever written here — that would republish",
                    "the material the gate exists to stop. A hash is not the string:",
                    f"see 'Why a digest is allowed where a literal is not' in {POLICY_DOC}.",
                    "Any divergence fails, in EITHER direction: a count up, a count",
                    "down, a new file, a cleared file, or a same-count SWAP that",
                    "moves the digest. This is a RATCHET, not a backlog — moving the",
                    f"numbers is a deliberate act with a reason, see {POLICY_DOC}.",
                    "Regenerate with: python3 scripts/check_test_data.py --write-baseline",
                ],
                "files": {
                    path_: {"count": finding.count, "digest": finding.digest}
                    for path_, finding in sorted(findings.items())
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _print_skips(skipped: list[Skipped]) -> None:
    for skip in skipped:
        print(f"  unreadable: {skip.path} — {skip.reason}")
    print(
        "\nA tracked file under a scanned root could not be read, so this build\n"
        "does not know what is in it. That is not a pass. Either the file is\n"
        "binary and does not belong under a scanned root, or the checkout is\n"
        "broken. Fix the file or narrow SCAN_ROOTS — do not ignore the line."
    )


def report(
    findings: dict[str, Finding],
    baseline: dict[str, Finding],
    skipped: list[Skipped],
) -> int:
    """Print the verdict. Returns a process exit code."""

    new_files = sorted(set(findings) - set(baseline))
    cleared = sorted(p for p in baseline if p not in findings)
    grown = sorted(
        p for p in findings if p in baseline and findings[p].count > baseline[p].count
    )
    shrunk = sorted(
        p for p in findings if p in baseline and findings[p].count < baseline[p].count
    )
    #: Same count, different set. The #615 hole: one published address replaced
    #: by a brand-new one, total unchanged, previously green.
    swapped = sorted(
        p
        for p in findings
        if p in baseline
        and findings[p].count == baseline[p].count
        and findings[p].digest != baseline[p].digest
    )

    total = sum(f.count for f in findings.values())
    print(
        f"test-data gate: {total} non-reserved addresses across "
        f"{len(findings)} tracked files (baseline "
        f"{sum(f.count for f in baseline.values())} across {len(baseline)})."
    )

    if not (new_files or cleared or grown or shrunk or swapped or skipped):
        print("OK")
        return 0

    if skipped:
        print("\nFAIL — a tracked file could not be scanned.\n")
        _print_skips(skipped)
        if not (new_files or cleared or grown or shrunk or swapped):
            return 1
        print()

    print("FAIL — the recorded set of non-reserved sender addresses has moved.\n")
    if new_files and cleared:
        # Printed only when both halves of a rename are present, so it is never
        # noise on a failure it does not explain. A gate whose message says
        # things that do not apply is one people stop reading.
        print(
            "  (A `new file` beside a `cleared` below with the same count is a\n"
            "   RENAME, not an addition. Re-record the baseline and say so.)\n"
        )
    for path in new_files:
        print(f"  new file: {path} ({findings[path].count})")
    for path in grown:
        print(f"  count up: {path} {baseline[path].count} -> {findings[path].count}")
    for path in swapped:
        print(
            f"  SWAPPED:  {path} — count unchanged at {findings[path].count}, "
            "but the set of addresses is different"
        )
    for path in shrunk:
        print(f"  count down: {path} {baseline[path].count} -> {findings[path].count}")
    for path in cleared:
        print(f"  cleared: {path} {baseline[path].count} -> 0")

    print(
        f"""
If you ADDED an address: every address in a fixture, docstring, comment or
sample must sit on a domain that cannot route — anything under `.test`,
`.example` or `.invalid`, or under `example.com` / `.net` / `.org`;
`email.careers.example.com` counts. Copy the shape in
`backend/tests/test_dismissed_card_does_not_settle_its_mail.py` — invented
employers, `careers@halberd.test`, `careers@ironvale.example.test`.

If the real wording is the evidence and only the particulars can change, keep
the wording and invent the particulars, then say so in the docstring so the
provenance claim stays true.

A SWAPPED line means the count did not move but the addresses did. That is the
case a count-only ratchet could not see: one published address replaced by a
brand-new one while an unrelated cleanup freed the slot.

If you REMOVED or REWROTE published material, read {POLICY_DOC} first — this
baseline is a ratchet, not a backlog, a forward delete removes nothing from git
history or from GitHub's index, and several of these modules make provenance
claims that a scrub would falsify. Removal is not forbidden; it is not routine,
and it does not get to be silent.

Either way, once the change is the one you mean, record it on purpose:

    python3 scripts/check_test_data.py --write-baseline

and state in the commit body which files moved and why. That commit is the
audit trail; this gate exists so that it cannot be skipped.

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

    findings, skipped = scan(repo_root)

    if args.write_baseline:
        # A skip is refused HERE too. If the write path quietly omitted an
        # unreadable file, it would launder the skip into a baseline that says
        # the file is clean, and the next check run would be green on a file
        # nobody has read.
        if skipped:
            print("FAIL — refusing to record a baseline over unreadable files.\n")
            _print_skips(skipped)
            return 1
        write_baseline(baseline_path, findings)
        print(
            f"Wrote {baseline_path}: "
            f"{sum(f.count for f in findings.values())} addresses across "
            f"{len(findings)} files."
        )
        return 0

    if not baseline_path.exists():
        print(
            f"FAIL — no baseline at {baseline_path}. Generate one with "
            "--write-baseline and commit it."
        )
        return 1

    return report(findings, load_baseline(baseline_path), skipped)


if __name__ == "__main__":
    sys.exit(main())
