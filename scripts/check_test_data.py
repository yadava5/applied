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

AN ADDRESS THAT IS ASSEMBLED AT RUN TIME

Until #647 a LITERAL was the only thing this gate could see. `EMAIL`'s domain
class admits letters, digits, dot and hyphen, so `f"careers@{domain}"` was not an
address as far as the check was concerned — and neither was `"careers@%s.com"`,
`"careers@" + domain`, nor `"careers@{0}.com".format(...)`. Every interpolation
form this repository actually uses was invisible, so a fixture author writing
senders the natural way got a green gate unconditionally. It was hiding senders
on two real companies' own domains, assembled by passing the domain from a call
site into `f"careers@{domain}"`, in a public repository, under a check reporting
OK. The addresses are not written out here for the same reason there is no
denylist: naming them would be the publication this file exists to prevent.

The fix is NOT to admit `{`, `}` and `%` into the domain class. That matches a
"domain" of `{token}.test` and hands that string to `is_allowed`, which then
reads a template as though it were a name. The question is whether the address
could RESOLVE somewhere, and for a template that is a question about the part of
the domain no interpolation can change — see `sealed_suffix`.
`f"careers@{token}.test"` is safe whatever `{token}` is and stays silent;
`f"careers@{company}.com"` is not; and `f"careers@{domain}"`, where the whole
domain arrives from somewhere else, cannot be proved either way and so counts.

WHAT IT STILL CANNOT SEE

Named here so the next reader inherits a decision rather than another blind spot.

* An interpolated LOCAL part over a literal, routable domain — `f"{i}@corp.com"`.
  The run after the `@` holds no marker so `TEMPLATE` does not fire, and the `}`
  in front of the `@` keeps `EMAIL` from firing either. Three sites in the tree,
  and one of them is `corpus/mail.py`'s iCalendar `UID:{uid}@google.com`, which
  is not an address at all — which is why closing this is a separate judgement
  about false positives and not a free widening.
* A domain concatenated out of literals only, `"careers@" + "north" + "wind.com"`,
  or built by adjacent-literal concatenation. Evasions rather than natural
  style; neither occurs here.
* Anything assembled through a call — `"@".join(...)`, a format string held in a
  constant, a template read from a file. A text scan ends where dataflow begins,
  and resolving constants is not something this file is going to start doing.

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
RESERVED_DOMAINS = frozenset({"example.com", "example.net", "example.org", "localhost"})
#: RFC 2606 §3 reserves those second-level names *and everything under them*, so
#: `email.careers.example.com` is as un-routable as the bare name. Matching the
#: bare name only is not a near-miss, it is an inverted gate: it reds on
#: `donotreply@email.careers.example.com` — the direct `.com` analogue of the
#: `email.careers.example.test` this repository already uses and this gate's own
#: failure message recommends — and the reader is then told by that message that
#: `example.com` is fine. Caught in review before merge.
RESERVED_SUFFIXES = tuple(
    "." + d for d in ("example.com", "example.net", "example.org")
)

#: Deliberately loose on the left of the `@` and strict on the right: the point
#: is to notice an address at all, not to validate one. Anchoring the TLD at two
#: or more letters keeps `@pytest.fixture` and `@playwright/test` out.
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

#: An INTERPOLATION MARKER: the ways this repository assembles a string at run
#: time. `{...}` is ONE code path serving three syntaxes — an f-string field, a
#: `str.format` field (`{}`, `{0}`, `{name}`) and a JavaScript template literal
#: (`${...}`) — so those three are not three proofs. `%s` is the second form.
#: Concatenation is the third and cannot be a character class at all, because
#: the string literal ENDS at the `@`; it has its own reader below.
_FIELD = r"\$?\{[^{}\n]*\}"
_PERCENT = r"%(?:\([A-Za-z0-9_]*\))?[-#0+ ]*\*?[0-9]*(?:\.[0-9]+)?[sdrfi]"
MARKER = f"(?:{_FIELD}|{_PERCENT})"

#: What a marker is rendered as once a match has been canonicalised. Two braces
#: cannot occur in a real domain, so a canonical template can never collide with
#: a literal address in the digested set, and `rsplit` on it is unambiguous.
MARKER_TOKEN = "{}"

_LOCAL_CHAR = r"[A-Za-z0-9._%+\-]"
_DOMAIN_CHAR = r"[A-Za-z0-9.\-]"
_LOCAL_SEGMENT = f"(?:{_LOCAL_CHAR}|{MARKER})+"

#: An address-shaped TEMPLATE: a local part (literal, interpolated or both), an
#: `@`, and a domain run holding AT LEAST ONE marker. That requirement is what
#: keeps this disjoint from `EMAIL` — a domain with no marker is a literal and
#: is `EMAIL`'s business — so no run is ever counted twice.
#:
#: Note what this deliberately is NOT. It is not `EMAIL` with `{`, `}` and `%`
#: added to the domain class. That would make `careers@{token}.test` a match
#: whose "domain" is the string `{token}.test`, and hand that to `is_allowed`,
#: which would then be reading a template as though it were a name. The question
#: is whether the address could RESOLVE anywhere; see `sealed_suffix`.
TEMPLATE = re.compile(
    _LOCAL_SEGMENT + "@" + f"{_DOMAIN_CHAR}*{MARKER}(?:{_DOMAIN_CHAR}|{MARKER})*"
)

#: Concatenation, the form no marker can describe: `"careers@" + domain` ends
#: its literal at the `@` and the domain arrives as separate operands.
#: `CONCAT_HEAD` finds that ending — an optional leading expression, a local
#: part, the `@`, the closing quote and a `+` — and `CONCAT_ELEMENT` walks the
#: chain that follows, one quoted fragment or one expression at a time.
CONCAT_HEAD = re.compile(
    r"(?P<lead>[A-Za-z_][A-Za-z0-9_.]*\s*\+\s*)?"
    r"['\"]"
    f"(?P<local>(?:{_LOCAL_CHAR}|{MARKER})*)"
    r"@['\"](?=\s*\+)"
)
CONCAT_ELEMENT = re.compile(
    r"\s*\+\s*(?:"
    r"(?P<quote>['\"])(?P<literal>[^'\"\n]*)(?P=quote)"
    r"|(?P<expr>[A-Za-z_][A-Za-z0-9_.]*(?:\([^()\n]*\)|\[[^\[\]\n]*\])*)"
    r")"
)

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


class Match(NamedTuple):
    """One address-shaped run, and how it was written.

    `text` is what gets digested: a literal address verbatim, or a template with
    its markers canonicalised. `interpolated` says which, and it is not
    decoration — `test_test_data_gate.py` lives inside a scanned root and has to
    assert that no LITERAL address is present in its own source while its
    run-time probes stay legitimately visible.
    """

    text: str
    interpolated: bool


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


def canonical(text: str) -> str:
    """A match with every interpolation marker rendered as `MARKER_TOKEN`.

    Renaming the interpolated variable — `{domain}` to `{d}`, `%s` to `%(d)s` —
    is then a formatting change and not a moved digest, for the same reason
    `digest_of` lower-cases before it sorts.
    """

    return re.sub(MARKER, MARKER_TOKEN, text)


def sealed_suffix(domain: str) -> str:
    """The part of an interpolated domain that no interpolation can change.

    `domain` is canonical, so everything after the LAST `MARKER_TOKEN` is
    literal — but it is only a whole SUFFIX from its first dot onward, and that
    distinction is the whole rule:

    * `{}.test`            -> `.test`     — reserved whatever `{}` is. Safe.
    * `acme-{}hub.example` -> `.example`  — the LABEL is half-interpolated, the
      TLD is not, and the TLD is what decides. Safe. This shape is in the tree
      (`test_tracking_sender_checks.py`) and a "the tail must start with a dot"
      rule would have flagged it.
    * `{}example.com`      -> `.com`      — FLAGGED, because `{}` may be `not`.
      Exactly the discrimination `is_allowed` already makes between
      `example.com` and `notexample.com`; the seal has to start at a dot or the
      label is not sealed.
    * `{}.com`             -> `.com`      — flagged.
    * `{}`                 -> `""`        — nothing is sealed and nothing can be
      proved, so `careers@{domain}` is flagged. This is the shape that hides a
      real domain passed in from a call site.

    A domain with no marker at all is sealed in its entirety and is returned
    whole, so this function is total and agrees with the literal path: a
    concatenation whose operands all turned out to be literals is judged exactly
    as `EMAIL` would have judged it.

    Returned so that `is_allowed` decides, unchanged: it already answers False
    for `""` and for `.com`, and True for `.test` and `.example.com`.
    """

    if MARKER_TOKEN not in domain:
        return domain
    tail = domain.rsplit(MARKER_TOKEN, 1)[1]
    return tail[tail.index(".") :] if "." in tail else ""


def _read_concatenation(text: str, head: re.Match[str]) -> tuple[str, str, int] | None:
    """Assemble `"careers@" + token + ".com"` into one canonical address.

    Returns the local part, the domain and the offset the chain ended at — kept
    apart rather than joined and re-split, because a literal fragment further
    along the chain may itself contain an `@` and `rsplit` would then take the
    wrong one. Returns None when what follows the `@` never interpolates:
    `"a@" + "b.com"` is two literals and this reader does not claim it. See
    "What it still cannot see" in the module docstring.
    """

    local = canonical(head.group("local"))
    if head.group("lead"):
        local = MARKER_TOKEN + local
    if not local:
        return None

    parts: list[str] = []
    position = head.end()
    while (element := CONCAT_ELEMENT.match(text, position)) is not None:
        parts.append(
            MARKER_TOKEN
            if element.group("expr") is not None
            else element.group("literal")
        )
        position = element.end()

    domain = "".join(parts)
    if MARKER_TOKEN not in domain:
        return None
    return local, domain, position


def matches_in(text: str) -> list[Match]:
    """Every address-shaped run in `text` that is not provably un-routable.

    Three readers over one string, and they are ordered so that the two which
    can consume a wider span run first:

    1. `TEMPLATE` — an interpolated domain. Judged on its `sealed_suffix`.
    2. `CONCAT_HEAD` — a domain assembled with `+`. Judged the same way.
    3. `EMAIL` — a literal address, judged on the domain itself, exactly as
       before this function existed. Its matches are unchanged.

    A literal address that sits INSIDE a run one of the first two already read
    is dropped rather than counted twice. That case measures zero in this tree
    today; the guard is here so the readers cannot start double-counting in
    silence if one ever appears.
    """

    found: list[Match] = []
    spans: list[tuple[int, int]] = []

    for match in TEMPLATE.finditer(text):
        spans.append(match.span())
        # Split at the FIRST `@`, on the canonical text: a marker may hold an
        # `@` of its own, and canonicalising has already replaced it.
        local, domain = canonical(match.group(0)).split("@", 1)
        if not is_allowed(sealed_suffix(domain)):
            found.append(Match(f"{local}@{domain}", True))

    for head in CONCAT_HEAD.finditer(text):
        read = _read_concatenation(text, head)
        if read is None:
            continue
        local, domain, end = read
        spans.append((head.start(), end))
        if not is_allowed(sealed_suffix(domain)):
            found.append(Match(f"{local}@{domain}", True))

    for match in EMAIL.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in spans):
            continue
        if not is_allowed(match.group(0).rsplit("@", 1)[1]):
            found.append(Match(match.group(0), False))

    return found


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

    matched = matches_in(path.read_text(encoding="utf-8"))
    return Finding(len(matched), digest_of(match.text for match in matched))


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
If the address is ASSEMBLED — an f-string, `%s`, `.format` or `+` — the gate
reads the part of the domain that no interpolation can change. A template whose
suffix is reserved stays silent: `f"careers@{{token}}.test"` is fine and is what
to write. A template whose suffix is routable is counted, because
`f"careers@{{company}}.com"` could be any company; and one with no literal suffix
at all is counted too, because `f"careers@{{domain}}"` is whatever the call site
passes in. Seal the suffix, or record the finding on purpose.

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
