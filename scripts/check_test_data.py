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

WHAT IT SCANS: EVERY TRACKED FILE

Until #623 it read four roots, and everything else in a public repository was
unwatched by construction. Nothing enumerated what "everything else" held, which
is the property that makes an allowlist dangerous rather than merely narrow: its
blind spot is an absence, and an absence is not something a reader notices. The
measurement was 239 non-reserved addresses across 24 tracked files outside the
roots — the demo data the product renders to every visitor, the evaluation
corpora, this script, and the policy document itself. The roots had already been
patched twice for the same defect ("a root the gate does not read"); #623 was
the third instance and was found by measuring rather than by another leak.

So the default is now "scanned", and the exceptions are a list with a reason on
each line. A path nobody thought about is read, not skipped. See `EXCLUDED`.

A FILE THAT IS NOT TEXT

Widening the scope means meeting the first PNG, and on this tree that PNG made
the whole run refuse — correctly, because a file this gate cannot read is not a
file it can call clean. The answer is a sniff on CONTENT: a file whose bytes are
not UTF-8 is skipped, and RECORDED as skipped in the baseline, so that "nobody
read this one" and "this one is clean" can never print the same.

The sniff is deliberately not an extension allowlist. That would be a second
allowlist with a second invisible blind spot, which is the shape the paragraph
above is about. It is also not git's "a NUL byte in the first 8000" heuristic:
measured on this tree, 54 tracked files fail to decode and every one of them is
a font, an image or a video, while the one tracked TEXT file carrying a NUL —
`apps/web/lib/feedback/coalesce.ts`, whose field delimiter is one — decodes
fine. The NUL rule would have dropped product source.

Three outcomes, three different things, and none of them is silence:

* it decodes            -> scanned, and its findings are baselined
* it does not decode    -> skipped, and the SKIP is baselined
* it cannot be read     -> the run fails. An `OSError` is not a sniff with an
                           answer, it is no answer: a broken checkout or a
                           tracked file that is gone.

`--write-baseline` refuses to move a file from the scanned set into the skipped
set. Recording that would launder a scanned file's findings into a skip —
corrupt one byte of a module holding fifty addresses, re-record, and the next
run is green on a file nobody has read. That is the same defect as everything in
HOW IT FAILS below, arriving through the escape hatch instead of the check.

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

A file that cannot be READ fails rather than counting as zero, and a file that
is not text is recorded as skipped rather than counted as clean. A skip that
passes silently is the same defect as everything above; a skip that is recorded
is a line in the baseline that somebody had to write, and the set of them is
ratcheted exactly like the addresses are.

The baseline records paths, counts and digests. It never records the matched
strings, for the same reason there is no denylist — and see "Why a digest is
allowed where a literal is not" in the policy document for why a truncated hash
does not reintroduce the problem.
"""

from __future__ import annotations

import argparse
import hashlib
import codecs
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

#: Tracked paths this gate does NOT read, each with the reason it does not — an
#: exclusion list, because an exclusion list and an allowlist fail in opposite
#: directions. This was `SCAN_ROOTS` until #623: four prefixes, and the rest of a
#: public repository outside the gate by construction. An entry here is a
#: decision somebody wrote down and a reviewer can argue with. A path nobody
#: thought about is scanned.
#:
#: IT IS EMPTY, AND THAT IS THE MEASURED ANSWER RATHER THAN AN OMISSION. Every
#: one of this repository's tracked files either scans clean, is recorded in the
#: baseline, or does not decode and is recorded as skipped. Nothing needed a
#: line — not the lockfiles, not the generated schema, not the built bundles.
#:
#: Adding one is deliberate: a prefix, one line saying why, and the knowledge
#: that an exclusion is coverage removed. The three findings in this gate's own
#: history were all coverage nobody knew was missing.
#:
#: THE ONE THAT WAS ARGUED FOR AND REJECTED: `docs/TEST_DATA_POLICY.md`. The
#: policy document illustrated its own rule with eight address-shaped templates
#: on routable suffixes, and a line here would have made the run green in one
#: character. It would also have exempted every address added to that file
#: afterwards, for any reason, by anybody — an exemption is not scoped to the
#: text that motivated it, and "a rule with a hole in it exactly where the rule
#: is written down" is this repository's recurring defect wearing a hat.
#:
#: The rule GOVERNS WRITING; the baseline RECORDS WHAT IS ALREADY WRITTEN; and
#: no file is outside either. Where existing text breaks the rule and nothing is
#: lost by fixing it, fix it — the document's eight were invented templates
#: making no provenance claim, so they were rewritten to name domains instead of
#: spelling addresses, and the file now scores zero and appears nowhere below.
#: Where the particulars are load-bearing, record them: this script's own
#: examples stay verbatim because one of them quotes the open-redirect fixture
#: `test_gmail_oauth_return_host.py` refuses, and an example that does not match
#: the thing it documents is worth less than a baseline line.
#:
#: (Two properties the old roots carried, kept here so they are not re-learned:
#: product source is in scope on purpose — #593's requisition numbers were in
#: `jobtracker/cloud/pipeline.py` and `classifier/rules.py`, not only in tests —
#: and `ml/demo/space/jobtracker/` is a *generated copy* of `backend/jobtracker/`
#: written by `ml/demo/package_space.py`, so repackaging the Space moves the
#: baseline. That is correct behaviour, and the policy document says so.)
EXCLUDED: tuple[tuple[str, str], ...] = ()

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


#: The two ways a file can fail to become text, kept apart because they are not
#: the same event. BINARY is an answer — the bytes are not UTF-8, the file is a
#: font or an image, and the gate records that it did not read it. UNREADABLE is
#: the absence of an answer: the file is gone, or the checkout is broken. One is
#: baselined; the other fails the run.
BINARY = "binary"
UNREADABLE = "unreadable"


class Skipped(NamedTuple):
    """A tracked file that produced no findings because none were read.

    Never silently a zero, and never merged with a clean result: `kind` is what
    keeps "nobody read this file" from printing like "this file has no
    addresses in it".
    """

    path: str
    kind: str
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


#: A DSN is not a sender. `postgresql://user:pass@host:5432/db` puts a `@`
#: between credentials and a host, which is exactly the shape `EMAIL` reads, so
#: every connection string in the tree counted as an address — and the "local
#: part" it counted was a password.
#:
#: The same `@` appears in a URL's userinfo, and that half of the tree is
#: security fixtures: `https://getapplied.vercel.app@evil.com` is the
#: open-redirect shape `config.py` and `test_gmail_oauth_return_host.py` exist
#: to refuse. Counting `vercel.app@evil.com` as a sender address made an
#: attack fixture look like published test data.
#:
#: MEASURED, not hypothetical: six matches in this tree, and both halves are
#: `scheme://...@host`, which is why one guard covers them —
#:
#:     backend/tests/test_expand_only_gate.py        2   postgresql:// DSN
#:     backend/tests/test_migration_url.py           1   postgresql:// DSN
#:     backend/tests/test_gmail_oauth_return_host.py 2   https:// userinfo
#:     backend/jobtracker/config.py                  1   https:// userinfo
#:
#: They inflated the number the baseline grandfathers and diluted the only
#: signal this gate has.
#:
#: The scan walks BACK from the local part to the nearest quote, whitespace or
#: line start, and asks whether a scheme sits in between. Bounded that way on
#: purpose: a URL earlier on the same line, or on the line above, must not
#: excuse a real address that follows it.
_URL_BOUNDARY = " \t\r\n'\"`(),[]{}"


def _inside_url(text: str, start: int) -> bool:
    """Is the match at `start` the credential half of a `scheme://user@host`?"""

    i = start
    while i > 0 and text[i - 1] not in _URL_BOUNDARY:
        i -= 1
    return "://" in text[i:start]


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
        # A connection string's `user:pass@host` is not a sender address.
        if _inside_url(text, match.start()):
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
    """Every tracked path except `EXCLUDED`, from git — never a filesystem walk.

    A walk reaches `node_modules`, `.venv*`, `.next` and `__pycache__`, none of
    which is this repository's material and all of which are full of addresses.
    A gate that reports hundreds of hits it does not own is a gate that gets
    turned off.

    The pathspec is gone (#623) and that is the whole change: git is asked for
    everything it tracks, and the filtering is done here where the reasons live.
    `git ls-files` still answers from the INDEX, so an untracked file is not
    scanned and a staged one is — the same definition `scripts/readme_facts.py`
    settled on in #621.

    AN ENTRY IS A PATH, NEVER A BARE SUBSTRING. One that ends in `/` is a
    directory and covers its subtree; anything else has to match a file exactly.
    A raw `startswith` would let `apps/web/lib` silently also exclude
    `apps/web/library/` and `apps/web/lib-utils/` — the same defect as the
    destructive-command hook matching `main` inside `maintenance`, and a
    particularly bad one here because its symptom is coverage that quietly is
    not there. Forgetting the slash therefore excludes nothing, which is the
    direction that fails safe.
    """

    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    subtrees = tuple(p for p, _reason in EXCLUDED if p.endswith("/"))
    exact = frozenset(p for p, _reason in EXCLUDED if not p.endswith("/"))
    return sorted(
        p
        for p in out.split("\0")
        if p and p not in exact and not p.startswith(subtrees)
    )


#: Byte-order marks whose files are text this gate can READ, longest first.
#:
#: ORDER IS LOAD-BEARING. `BOM_UTF32_LE` is `FF FE 00 00` and begins with
#: `BOM_UTF16_LE` (`FF FE`), so testing UTF-16 first would decode a UTF-32
#: file as UTF-16 and produce mojibake that scans clean -- the same failure
#: this constant exists to close, one encoding over.
BOM_CODECS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
    (codecs.BOM_UTF8, "utf-8-sig"),
)

#: Proportion of NUL bytes above which a file that DECODED as UTF-8 is re-read
#: as UTF-16. Measured rather than guessed: BOM-less UTF-16 holding ASCII text
#: runs at 0.50 (every second byte), and this repo's only NUL-carrying UTF-8
#: source, `apps/web/lib/feedback/coalesce.ts`, holds ONE in several kilobytes.
#: 0.30 sits far from both.
NUL_DENSITY_LIMIT = 0.30


def decode_text(raw: bytes) -> str | None:
    """The file's text, or None when these bytes are not text this can read.

    WHY THIS IS NOT JUST `.decode("utf-8")` (#832). **NUL bytes are valid
    UTF-8**, so a BOM-less UTF-16 file decodes cleanly with every letter
    interleaved with a U+0000, the `EMAIL` regex matches nothing, and the file
    is recorded as SCANNED AND CLEAN -- present in neither `findings` nor
    `skipped`. That is worse than a skip: this gate's design is that a file
    which cannot be read must never read the same as a file that is clean, and
    skips are counted in the headline and baselined precisely to keep
    unscannable visible.

    THE ISSUE PROPOSED THE BOM SNIFF AND CALLED THE DENSITY GUARD OPTIONAL.
    Measured, it is the other way round:

        "…recruiter@…" encoded utf-16  (with BOM)  -> UTF-8 decode RAISES
        the same text encoded utf-16-le (BOM-less) -> decodes, 0.50 NUL density
        the same text encoded utf-16-be (BOM-less) -> decodes, 0.50 NUL density

    A BOM begins `FF FE`, which is not valid UTF-8 at all, so a BOM'd file was
    already being skipped and RECORDED -- safe, if unread. The unsafe class is
    exactly the BOM-less one, and only the density guard sees it. The BOM sniff
    is kept because it upgrades those skips into real scans, but it is the
    smaller half, and the issue's own ordering of the two was backwards.

    The density rule is deliberately chosen over git's "NUL in the first 8000
    bytes means binary", and the reason must not be undone:
    `apps/web/lib/feedback/coalesce.ts` is product source whose field delimiter
    is a literal NUL. A presence test would drop real source out of the scan;
    a density test leaves it comfortably inside.
    """

    for bom, codec in BOM_CODECS:
        if raw.startswith(bom):
            try:
                return raw.decode(codec)
            except UnicodeDecodeError:
                # A declared BOM whose body does not decode is unreadable, and
                # unreadable is a skip.
                #
                # THIS IS DEFENSIVE, NOT LOAD-BEARING, and saying so is better
                # than implying otherwise. Falling through to the UTF-8 attempt
                # below would give the identical answer: measured, all four
                # UTF-16/32 BOMs are themselves invalid UTF-8 (`ff fe`,
                # `fe ff`, `ff fe 00 00`, `00 00 fe ff`), so that attempt
                # cannot succeed on a file that reached here; and a `ef bb bf`
                # body that fails `utf-8-sig` fails plain `utf-8` too. A
                # mutation replacing this `return` with a fall-through
                # survives the whole suite for exactly that reason.
                return None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if not raw or raw.count(0) / len(raw) <= NUL_DENSITY_LIMIT:
        return text

    # Dense NULs in something that decoded: BOM-less UTF-16. Endianness from
    # where the NULs sit -- ASCII in UTF-16LE puts them at odd indices.
    odd_nuls = sum(1 for i in range(1, len(raw), 2) if raw[i] == 0)
    even_nuls = sum(1 for i in range(0, len(raw), 2) if raw[i] == 0)
    for codec in ("utf-16-le", "utf-16-be") if odd_nuls >= even_nuls else ("utf-16-be", "utf-16-le"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    # Dense NULs that are not UTF-16 either. Not text this can read, and a
    # skip is the honest answer -- returning the interleaved UTF-8 reading
    # would be the defect.
    return None


def scan_file(path: Path) -> Finding | None:
    """Non-reserved addresses in one file, or None when the file is not text.

    The whole file, not just its string literals: the most recent leak came
    through a module DOCSTRING sitting above fixtures that had been correctly
    sanitised. Comments and docstrings are published surfaces too.

    THE TEXT/BINARY DECISION IS THE BYTES' OWN. `None` means the content did not
    decode as UTF-8, which is a sniff on the file itself rather than a guess from
    its name — an extension allowlist would be a second allowlist with a second
    invisible blind spot, and this gate has just been rebuilt to get rid of the
    first one. The caller records the skip; it never reads as a zero.

    Raises `OSError` rather than answering, and that stays a hard failure. Both
    used to be swallowed and returned as zero, so a file nobody could read was
    recorded as clean — the same defect family as the count-only ratchet it sat
    next to (#615).

    The count is by OCCURRENCE and the digest is over the DE-DUPLICATED set, so
    the two answer different questions on purpose: adding a second copy of an
    address already in the file moves the count and not the digest, and swapping
    one address for another moves the digest and not the count. Either fails.
    """

    raw = path.read_bytes()
    text = decode_text(raw)
    if text is None:
        return None
    matched = matches_in(text)
    return Finding(len(matched), digest_of(match.text for match in matched))


def scan(repo_root: Path) -> tuple[dict[str, Finding], list[Skipped]]:
    """Findings for every scanned file with at least one hit, plus the skips.

    A file with no findings and a file that was never read are both absent from
    the first return value, which is exactly why the second one exists and is
    baselined alongside it.
    """

    findings: dict[str, Finding] = {}
    skipped: list[Skipped] = []
    for rel in tracked_files(repo_root):
        try:
            finding = scan_file(repo_root / rel)
        except OSError as exc:
            skipped.append(Skipped(rel, UNREADABLE, f"{type(exc).__name__}: {exc}"))
            continue
        if finding is None:
            skipped.append(Skipped(rel, BINARY, "not UTF-8"))
            continue
        if finding.count:
            findings[rel] = finding
    return findings, skipped


class Baseline(NamedTuple):
    """What was recorded on purpose: the findings, and the files nobody read."""

    files: dict[str, Finding]
    skipped: dict[str, str]


def load_baseline(path: Path) -> Baseline:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "files" not in data:
        raise SystemExit(
            f"FAIL — {path} is in the pre-#615 format (counts only, no digests).\n"
            "A count alone cannot see a same-count address swap. Regenerate it:\n"
            "    python3 scripts/check_test_data.py --write-baseline\n"
            f"and say in the commit body why the numbers moved. See {POLICY_DOC}."
        )
    #: Checked AFTER `files`, so a pre-#615 baseline is still named as one.
    #: Degrading to "no opinion" on a missing `skipped` map would restore the
    #: exact hole #623 closed: every binary file would read as newly skipped on
    #: one branch and as nothing at all on another, and a file that had gone
    #: from scanned to unreadable would slip through the difference.
    if "skipped" not in data:
        raise SystemExit(
            f"FAIL — {path} is in the pre-#623 format (no record of which tracked\n"
            "files were skipped because they are not text). Reading it would let a\n"
            "file nobody could read pass as a file that is clean. Regenerate it:\n"
            "    python3 scripts/check_test_data.py --write-baseline\n"
            f"and say in the commit body why the numbers moved. See {POLICY_DOC}."
        )
    return Baseline(
        files={
            str(path_): Finding(int(entry["count"]), str(entry["digest"]))
            for path_, entry in data["files"].items()
        },
        skipped={str(path_): str(kind) for path_, kind in data["skipped"].items()},
    )


def previously_scanned(path: Path) -> dict[str, int]:
    """The `files` map of the baseline being replaced, read leniently.

    Only the write path uses this, and only to refuse turning a scanned file
    into a skipped one, so a baseline that is missing or in an older format
    means "nothing to protect" rather than a failure — otherwise the pre-#623
    format could never be re-recorded at all.
    """

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(p): int(e["count"]) for p, e in data.get("files", {}).items()}


def write_baseline(
    path: Path, findings: dict[str, Finding], skipped: list[Skipped]
) -> None:
    path.write_text(
        json.dumps(
            {
                "_README": [
                    "Per-file counts AND digests of sender addresses on domains that",
                    "are not RFC-reserved, across every tracked file except the ones",
                    "scripts/check_test_data.py names in EXCLUDED. The digest is a",
                    "truncated SHA-256 over the sorted, lower-cased, de-duplicated",
                    "set of matches in that file.",
                    "No matched string is ever written here — that would republish",
                    "the material the gate exists to stop. A hash is not the string:",
                    f"see 'Why a digest is allowed where a literal is not' in {POLICY_DOC}.",
                    "'skipped' lists tracked files whose bytes are not UTF-8, so",
                    "NOTHING IN THEM WAS READ. They are recorded rather than dropped",
                    "because a file nobody read must never look like a file that is",
                    "clean, and so that a new one is a deliberate line in a diff.",
                    "Any divergence fails, in EITHER direction: a count up, a count",
                    "down, a new file, a cleared file, a same-count SWAP that moves",
                    "the digest, or a change to the skipped set. This is a RATCHET,",
                    f"not a backlog — moving it is a deliberate act, see {POLICY_DOC}.",
                    "Regenerate with: python3 scripts/check_test_data.py --write-baseline",
                ],
                "files": {
                    path_: {"count": finding.count, "digest": finding.digest}
                    for path_, finding in sorted(findings.items())
                },
                "skipped": {skip.path: skip.kind for skip in sorted(skipped)},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _print_unreadable(skipped: list[Skipped]) -> None:
    for skip in skipped:
        print(f"  unreadable: {skip.path} — {skip.reason}")
    print(
        "\nA tracked file could not be READ — not `could not be decoded`, which is\n"
        "a sniff with an answer, but no answer at all. This build does not know\n"
        "what is in it, and that is not a pass. The checkout is broken or the file\n"
        "is tracked and gone. Fix it; do not ignore the line."
    )


def report(
    findings: dict[str, Finding],
    baseline: Baseline,
    skipped: list[Skipped],
) -> int:
    """Print the verdict. Returns a process exit code."""

    recorded = baseline.files
    new_files = sorted(set(findings) - set(recorded))
    cleared = sorted(p for p in recorded if p not in findings)
    grown = sorted(
        p for p in findings if p in recorded and findings[p].count > recorded[p].count
    )
    shrunk = sorted(
        p for p in findings if p in recorded and findings[p].count < recorded[p].count
    )
    #: Same count, different set. The #615 hole: one published address replaced
    #: by a brand-new one, total unchanged, previously green.
    swapped = sorted(
        p
        for p in findings
        if p in recorded
        and findings[p].count == recorded[p].count
        and findings[p].digest != recorded[p].digest
    )

    unreadable = [skip for skip in skipped if skip.kind == UNREADABLE]
    binary = {skip.path for skip in skipped if skip.kind == BINARY}
    #: The skipped set is ratcheted for the same reason the counts are. A new
    #: unreadable file means a file nobody has read joined a public repository;
    #: a file that stopped being skipped means its contents are being read for
    #: the first time. Both are events, and neither gets to be silent.
    newly_skipped = sorted(binary - set(baseline.skipped))
    #: Measured against every path that produced no findings, not against the
    #: binary ones alone. A baselined font that goes MISSING is unreadable
    #: rather than binary, and subtracting only `binary` would print "it decodes
    #: now" about a file that is not there — a message that says something
    #: untrue, on a run that already fails for the right reason.
    unread = binary | {skip.path for skip in unreadable}
    no_longer_skipped = sorted(set(baseline.skipped) - unread)

    total = sum(f.count for f in findings.values())
    print(
        f"test-data gate: {total} non-reserved addresses across "
        f"{len(findings)} tracked files (baseline "
        f"{sum(f.count for f in recorded.values())} across {len(recorded)}); "
        f"{len(binary)} tracked files skipped as not-UTF-8 and read by nothing "
        f"(baseline {len(baseline.skipped)})."
    )

    addresses_moved = bool(new_files or cleared or grown or shrunk or swapped)
    skips_moved = bool(newly_skipped or no_longer_skipped)

    if not (addresses_moved or skips_moved or unreadable):
        print("OK")
        return 0

    if unreadable:
        print("\nFAIL — a tracked file could not be scanned.\n")
        _print_unreadable(unreadable)
        if not (addresses_moved or skips_moved):
            return 1
        print()

    if skips_moved:
        print("FAIL — the recorded set of files nobody reads has moved.\n")
        for path in newly_skipped:
            print(f"  now skipped: {path} — not UTF-8, so nothing in it was read")
        for path in no_longer_skipped:
            print(
                f"  no longer skipped: {path} — it decodes now, so its contents "
                "are being read for the first time"
            )
        print(
            f"""
A file whose bytes are not UTF-8 is skipped and RECORDED as skipped, so that it
can never read like a file that is clean. Adding one — a font, an image, a video
— moves this set, and re-recording is how you say you meant to. If a file here
is a surprise, it is a file that has stopped being text; look at it before you
re-record.

    python3 scripts/check_test_data.py --write-baseline

The one thing that will not work is re-recording a file that used to be scanned:
that would launder its findings into a skip, and the write path refuses it. See
{POLICY_DOC}."""
        )
        if not addresses_moved:
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
        print(f"  count up: {path} {recorded[path].count} -> {findings[path].count}")
    for path in swapped:
        print(
            f"  SWAPPED:  {path} — count unchanged at {findings[path].count}, "
            "but the set of addresses is different"
        )
    for path in shrunk:
        print(f"  count down: {path} {recorded[path].count} -> {findings[path].count}")
    for path in cleared:
        print(f"  cleared: {path} {recorded[path].count} -> 0")

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
        # A file that could not be READ is refused HERE too. Omitting it would
        # launder the skip into a baseline that says the file is clean, and the
        # next check run would be green on a file nobody has read.
        unreadable = [skip for skip in skipped if skip.kind == UNREADABLE]
        if unreadable:
            print("FAIL — refusing to record a baseline over unreadable files.\n")
            _print_unreadable(unreadable)
            return 1

        # And the same defect through the other door, which is the one the
        # binary sniff opens. A file that WAS scanned and now does not decode
        # has not become a font: one byte of it is wrong, or it has been
        # replaced. Recording that as an ordinary skip would drop every finding
        # it used to carry and leave the next run green on a file nobody read.
        # This is the only skip the write path will not take.
        was_scanned = previously_scanned(baseline_path)
        regressed = [skip for skip in skipped if skip.path in was_scanned]
        if regressed:
            print("FAIL — refusing to record a scanned file as skipped.\n")
            for skip in regressed:
                print(
                    f"  {skip.path} — was scanned with {was_scanned[skip.path]} "
                    f"finding(s), now reads as {skip.reason}"
                )
            print(
                "\nThis is not a re-baseline, it is a file that has stopped being\n"
                "readable while holding material this gate had recorded. Recording\n"
                "it would drop those findings and turn every later run green on a\n"
                "file nobody has read. Restore the file, then re-record."
            )
            return 1

        write_baseline(baseline_path, findings, skipped)
        binary = [skip for skip in skipped if skip.kind == BINARY]
        print(
            f"Wrote {baseline_path}: "
            f"{sum(f.count for f in findings.values())} addresses across "
            f"{len(findings)} files, and {len(binary)} files skipped as not-UTF-8."
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
