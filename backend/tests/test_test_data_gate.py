"""The test-data gate has to be able to fail — issues #593 and #615.

This repository's named recurring defect is a check that cannot fail, and it has
shipped four rounds of one. ``scripts/check_test_data.py`` makes these claims,
and each is a separate code path:

* a count going UP in a file the baseline already lists     -> red
* a file appearing that the baseline does not list at all   -> red
* a count going DOWN, or a baselined file going to zero     -> red
* a SAME-COUNT swap: the set moved, the total did not       -> red
* a tracked file that cannot be read or decoded             -> red
* an address on an RFC-reserved domain                      -> green
* the same addresses in a different order or case           -> green
* an address ASSEMBLED at run time on a routable domain     -> red
* the same assembly with an RFC-reserved literal suffix     -> green

The reserved-domain row and the reordering row are not padding. A gate that
reddened on ``careers@halberd.test``
would punish the exact shape ``docs/TEST_DATA_POLICY.md`` tells people to write,
which is the inverted-gate failure: a check that defends the bug. And a digest
that moved when the file was merely reformatted would make the gate a nuisance
that gets deleted.

The swap and the divergence-down cases are #615. The first cut of this gate
compared per-file counts only, so replacing one published address with a
brand-new one left the total at 554 and reported ``OK`` — a gate whose step was
named "refuse new real sender addresses" while the mechanism refused a larger
*count*. Slack accumulated the same way: remove three this month, add three
different ones next month, green both times.

The last two rows are #647. Until then the gate could see a LITERAL and nothing
else: ``f"careers@{domain}"`` was not an address to it, and neither was
``"careers@%s.com"``, ``"careers@" + domain`` nor ``"careers@{0}.com".format()``.
Every interpolation form this repository actually uses was invisible, so a
fixture author writing senders the natural way got a green gate unconditionally
— and it was hiding senders on real companies' own domains, assembled by passing
the domain in from a call site. The addresses are not written out anywhere in
this module, for the reason the next section gives.

Note on this file
-----------------

``backend/tests/`` is one of the roots the gate scans, so a literal offending
address written here would become its own baseline entry — the checker would
have been made to republish, in the file that tests it, the material it exists
to stop. Every probe address is therefore assembled at run time from fragments
split at the ``@``, and no LITERAL address is ever present in this source. See
:func:`test_this_module_is_not_itself_a_finding`, which asserts exactly that —
and, since #647, asserts nothing more.

Because this module IS a finding now, with a baseline entry of its own. Its
probe helpers are ``f"{_LOCAL}@{_ROUTABLE}"``: a wholly interpolated domain, the
shape the gate cannot prove safe and therefore counts. Two consequences, worth
knowing before they surprise somebody.

* ``_reserved()`` is ``f"{_LOCAL}@{_RESERVED}"`` and is counted too, even though
  ``_RESERVED`` is ``careers.example.test``. That is a false positive in spirit
  and it is unavoidable: proving it safe means resolving a module constant, and
  a text scan that started doing dataflow would be a different tool. The gate
  reads the template, and this template seals nothing.
* Editing a probe moves this module's baseline entry. That is the ratchet
  working. The alternative — writing the probes in a shape the gate cannot see,
  in order to keep the number at zero — is precisely the defect #647 is about,
  and this file above all others does not get to be written in the style its own
  subject is blind to.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_test_data.py"

#: Split at the ``@`` on purpose — see the module docstring. Neither half
#: matches the checker's address pattern, so this module scores zero.
_LOCAL = "noreply"
_ROUTABLE = "careers-relay.example-that-is-not-reserved.xyz"
#: A SECOND routable domain, for the swap case: replacing one published address
#: with a brand-new one has to red even though the count does not move.
_ROUTABLE_2 = "ats-relay.another-domain-that-is-not-reserved.xyz"
_RESERVED = "careers.example.test"

HEX16 = re.compile(r"\A[0-9a-f]{16}\Z")


def _routable() -> str:
    """An address on a domain that is NOT RFC-reserved. The thing being caught."""

    return f"{_LOCAL}@{_ROUTABLE}"


def _routable_2() -> str:
    """A DIFFERENT non-reserved address. Same shape, same length, new domain."""

    return f"{_LOCAL}@{_ROUTABLE_2}"


def _reserved() -> str:
    """An address the policy actively recommends. Must never be flagged."""

    return f"{_LOCAL}@{_RESERVED}"


def _load():
    """Import the tool by path — it is a script, not a package module.

    Same loader as ``test_readme_facts_writer.py`` and ``test_expand_only_gate``,
    registered in ``sys.modules`` before exec for the reason stated there.
    """

    spec = importlib.util.spec_from_file_location("check_test_data", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A throwaway git repo shaped like this one, with two baselined findings.

    Real ``git ls-files`` rather than a stub: tracked-ness is half of what the
    checker asserts, and a stub would let an untracked file — the ``node_modules``
    case — pass a test it would fail in production.

    ``test_pair.py`` carries TWO addresses so that a count going down (2 -> 1)
    can be told apart from a file being cleared entirely (1 -> 0). Those are
    different branches of ``report()`` and both have to red.
    """

    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    tests = tmp_path / "backend" / "tests"
    tests.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()

    (tests / "test_existing.py").write_text(f'SENDER = "{_routable()}"\n', encoding="utf-8")
    (tests / "test_pair.py").write_text(
        f'A = "{_routable()}"\nB = "{_routable_2()}"\n', encoding="utf-8"
    )
    (tests / "test_clean.py").write_text(f'SENDER = "{_reserved()}"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _baseline(tree: Path) -> Path:
    return tree / "scripts" / "test_data_baseline.json"


def _recorded(tree: Path) -> dict:
    return json.loads(_baseline(tree).read_text(encoding="utf-8"))["files"]


def _write_baseline(gate, tree: Path) -> None:
    assert gate.main(["--write-baseline", "--repo-root", str(tree)]) == 0


def _check(gate, tree: Path) -> int:
    return gate.main(["--repo-root", str(tree)])


def test_a_clean_tree_is_green(tree: Path) -> None:
    """The recorded state passes. Without this the reds below prove nothing."""

    gate = _load()
    _write_baseline(gate, tree)

    recorded = _recorded(tree)
    assert {p: e["count"] for p, e in recorded.items()} == {
        "backend/tests/test_existing.py": 1,
        "backend/tests/test_pair.py": 2,
    }, recorded
    for path, entry in recorded.items():
        assert HEX16.match(entry["digest"]), (path, entry)
    assert _check(gate, tree) == 0


def test_the_baseline_never_records_the_offending_string(tree: Path) -> None:
    """Paths, counts and digests only. A baseline holding the strings has
    republished them — which is why there is no denylist either."""

    gate = _load()
    _write_baseline(gate, tree)

    raw = _baseline(tree).read_text(encoding="utf-8")
    assert _ROUTABLE not in raw
    assert _ROUTABLE_2 not in raw
    assert _LOCAL not in raw


def test_a_count_going_up_in_a_baselined_file_reds(tree: Path) -> None:
    gate = _load()
    _write_baseline(gate, tree)

    path = tree / "backend" / "tests" / "test_existing.py"
    path.write_text(f'SENDER = "{_routable()}"\nOTHER = "hr@{_ROUTABLE}"\n', encoding="utf-8")
    assert _check(gate, tree) == 1


def test_a_same_count_swap_reds(tree: Path) -> None:
    """#615's headline. One published address out, one brand-new one in.

    The count does not move — 1 before, 1 after — so a count-only ratchet said
    OK. The digest is over the SET, so it moves and the gate reds.
    """

    gate = _load()
    _write_baseline(gate, tree)
    before = _recorded(tree)["backend/tests/test_existing.py"]

    path = tree / "backend" / "tests" / "test_existing.py"
    path.write_text(f'SENDER = "{_routable_2()}"\n', encoding="utf-8")

    findings, skipped = gate.scan(tree)
    after = findings["backend/tests/test_existing.py"]
    assert skipped == []
    # The property that makes the swap visible, stated directly: same count,
    # different digest. Asserting only the exit code would not distinguish this
    # from any other red.
    assert after.count == before["count"] == 1
    assert after.digest != before["digest"]

    assert _check(gate, tree) == 1


def test_a_brand_new_file_reds(tree: Path) -> None:
    """A separate path from the count compare: nothing to compare against."""

    gate = _load()
    _write_baseline(gate, tree)

    new = tree / "backend" / "tests" / "test_added.py"
    new.write_text(f'SENDER = "{_routable()}"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    assert _check(gate, tree) == 1


def test_a_reserved_domain_stays_green(tree: Path) -> None:
    """The policy's recommended shape must not be what turns the build red."""

    gate = _load()
    _write_baseline(gate, tree)

    new = tree / "backend" / "tests" / "test_more_clean.py"
    new.write_text(
        f'A = "{_reserved()}"\nB = "careers@halberd.test"\n'
        'C = "hiring@northwind.example"\nD = "x@y.invalid"\n'
        'E = "dev@example.com"\n'
        # SUBDOMAINS of the reserved second-level names. RFC 2606 §3 reserves
        # them too, and the first cut of the gate did not: it matched
        # `example.com` exactly and reddened on the `.com` analogue of the very
        # address the policy holds up as the shape to copy. Caught in review;
        # these four lines are what keeps it caught.
        'F = "donotreply@email.careers.example.com"\n'
        'G = "hr@mail.example.org"\n'
        'H = "no-reply@ats.example.net"\n'
        'I = "no-reply@ats.example.test"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    assert _check(gate, tree) == 0


def test_an_untracked_file_is_not_scanned(tree: Path) -> None:
    """``node_modules`` and ``.venv`` are why this reads git and not the disk."""

    gate = _load()
    _write_baseline(gate, tree)

    stray = tree / "backend" / "tests" / "node_modules"
    stray.mkdir()
    (stray / "vendor.js").write_text(f'const s = "{_routable()}";\n', encoding="utf-8")
    assert _check(gate, tree) == 0


def test_a_count_going_down_reds(tree: Path) -> None:
    """Divergence downward, #615.

    This test asserted ``== 0`` until #615: down was allowed, printed and
    forgiven. That let slack accumulate silently — remove three addresses this
    month, add three different ones next month, green both times. Removal is
    still permitted; it now has to arrive as a ``--write-baseline`` commit with
    a reason, which is the auditable event the policy wanted all along.
    """

    gate = _load()
    _write_baseline(gate, tree)

    path = tree / "backend" / "tests" / "test_pair.py"
    path.write_text(f'A = "{_routable()}"\n', encoding="utf-8")
    assert _check(gate, tree) == 1


def test_a_baselined_file_going_to_zero_reds(tree: Path) -> None:
    """The `cleared` branch — a different code path from `count down`."""

    gate = _load()
    _write_baseline(gate, tree)

    path = tree / "backend" / "tests" / "test_existing.py"
    path.write_text(f'SENDER = "{_reserved()}"\n', encoding="utf-8")
    assert _check(gate, tree) == 1


def test_re_recording_the_baseline_makes_a_removal_green(tree: Path) -> None:
    """The escape hatch has to work, or the gate is a wall and gets bypassed.

    Down reds; re-recording on purpose clears it. That commit is the audit
    trail. Without this case the divergence-down red is untested as a *gate*
    and only tested as a refusal.
    """

    gate = _load()
    _write_baseline(gate, tree)

    path = tree / "backend" / "tests" / "test_pair.py"
    path.write_text(f'A = "{_routable()}"\n', encoding="utf-8")
    assert _check(gate, tree) == 1

    _write_baseline(gate, tree)
    assert _check(gate, tree) == 0


def test_reordering_the_same_addresses_stays_green(tree: Path) -> None:
    """The digest is over a SORTED, lower-cased SET, not over file order.

    A digest that moved when a file was merely reformatted would make the gate
    a nuisance, and a nuisance gate gets deleted. This is the control on the
    swap test above: it proves the red there came from the set changing and not
    from the bytes changing.
    """

    gate = _load()
    _write_baseline(gate, tree)

    path = tree / "backend" / "tests" / "test_pair.py"
    path.write_text(
        f"# reordered, re-cased, and one duplicate line removed from nowhere\n"
        f'B = "{_routable_2().upper()}"\nA = "{_routable()}"\n',
        encoding="utf-8",
    )
    assert _check(gate, tree) == 0


def test_an_unreadable_file_reds(tree: Path) -> None:
    """A skip that counts as a pass is the same defect as the rest of #615.

    ``count_file`` used to swallow ``UnicodeDecodeError`` and ``OSError`` and
    return 0, so a file nobody could read was recorded as clean.
    """

    gate = _load()
    _write_baseline(gate, tree)

    blob = tree / "backend" / "tests" / "test_blob.py"
    blob.write_bytes(b"\xff\xfe\x00\x01 not utf-8 \xc3\x28\n")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)

    findings, skipped = gate.scan(tree)
    assert [s.path for s in skipped] == ["backend/tests/test_blob.py"], skipped
    assert _check(gate, tree) == 1


def test_write_baseline_refuses_an_unreadable_file(tree: Path) -> None:
    """The write path must not launder the skip into a clean baseline.

    If ``--write-baseline`` quietly omitted an unreadable file, the very next
    check run would be green on a file nobody has read — the skip would have
    been converted into a recorded pass.
    """

    gate = _load()
    _write_baseline(gate, tree)
    before = _baseline(tree).read_text(encoding="utf-8")

    blob = tree / "backend" / "tests" / "test_blob.py"
    blob.write_bytes(b"\xff\xfe\x00\x01 not utf-8 \xc3\x28\n")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)

    assert gate.main(["--write-baseline", "--repo-root", str(tree)]) == 1
    assert _baseline(tree).read_text(encoding="utf-8") == before


def test_a_pre_615_baseline_is_refused_not_half_read(tree: Path) -> None:
    """A counts-only baseline cannot see a swap. Say so; do not degrade to it.

    Reading the old shape and treating the missing digest as "no opinion" would
    silently restore exactly the hole #615 is about, on any branch that had not
    re-recorded.
    """

    gate = _load()
    _write_baseline(gate, tree)

    _baseline(tree).write_text(
        json.dumps({"counts": {"backend/tests/test_existing.py": 1}}, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        _check(gate, tree)
    assert "pre-#615 format" in str(exc.value)


def test_a_docstring_is_scanned_not_just_a_literal(tree: Path) -> None:
    """The leak #593 predicted arrived through a module docstring, not a fixture."""

    gate = _load()
    _write_baseline(gate, tree)

    new = tree / "backend" / "tests" / "test_docstring.py"
    new.write_text(f'"""Graded against {_routable()}."""\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    assert _check(gate, tree) == 1


def test_ml_is_scanned(tree: Path) -> None:
    """``ml/`` was a blind spot until #615 — neither scanned nor documented.

    ``ml/demo/space/jobtracker/`` is a generated copy of ``backend/jobtracker/``
    (``ml/demo/package_space.py``), so #593's material was tracked twice and
    scanned once. #593's own corrected inventory named
    ``ml/demo/space/jobtracker/classifier/rules.py`` hours before the first cut
    of this gate merged without it.
    """

    gate = _load()
    _write_baseline(gate, tree)
    space = tree / "ml" / "demo" / "space" / "jobtracker" / "classifier"
    space.mkdir(parents=True)
    (space / "rules.py").write_text(f'RELAY = "{_routable()}"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    assert _check(gate, tree) == 1


def test_a_root_that_is_not_scanned_stays_green(tree: Path) -> None:
    """The discriminating half of the test above.

    ``assert "ml/" in SCAN_ROOTS`` would be a tautology against the source it
    checks, and the red above on its own is also consistent with "any new
    tracked file anywhere reds". The same file under a root the gate does NOT
    scan has to stay green, or neither result says anything about ``ml/``.

    ``docs/`` is out of scope on purpose — see "What is not scanned" in
    ``docs/TEST_DATA_POLICY.md``. If a future change puts it in scope, this test
    is where that decision surfaces.
    """

    gate = _load()
    assert not any(root.startswith("docs/") for root in gate.SCAN_ROOTS)

    _write_baseline(gate, tree)
    unscanned = tree / "docs" / "space" / "jobtracker" / "classifier"
    unscanned.mkdir(parents=True)
    (unscanned / "rules.py").write_text(f'RELAY = "{_routable()}"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    assert _check(gate, tree) == 0


@pytest.mark.parametrize(
    "domain",
    [
        "example.com",
        "email.careers.example.com",
        "mail.example.org",
        "ats.example.net",
        "ats.example.test",
        "halberd.test",
        "ironvale.example.test",
        "northwind.example",
        "y.invalid",
        "localhost",
    ],
)
def test_reserved_domains_are_allowed(domain: str) -> None:
    assert _load().is_allowed(domain) is True


@pytest.mark.parametrize(
    "domain",
    [
        # Real registrations that merely LOOK invented, and three near-misses
        # that a naive `"example" in domain` would wave through.
        "acme.com",
        "northwind.com",
        "notexample.com",
        "notreserved-example.io",
        "fakeexample.org",
        "example.com.attacker.io",
    ],
)
def test_lookalike_domains_are_not_allowed(domain: str) -> None:
    assert _load().is_allowed(domain) is False


def test_the_digest_is_stable_and_set_shaped() -> None:
    """Order, case and duplication must not move it; a different set must."""

    gate = _load()
    a = f"{_LOCAL}@{_ROUTABLE}"
    b = f"{_LOCAL}@{_ROUTABLE_2}"
    assert gate.digest_of([a, b]) == gate.digest_of([b, a])
    assert gate.digest_of([a, b]) == gate.digest_of([b.upper(), a, a])
    assert gate.digest_of([a]) != gate.digest_of([b])
    assert HEX16.match(gate.digest_of([a]))


def test_this_module_is_not_itself_a_finding() -> None:
    """This file lives inside a scanned root. No LITERAL address may be in it.

    That is the property the note at the top of this module claims, and it is
    the one that matters: a literal here would republish, in the file that tests
    the checker, the material the checker exists to stop.

    It is NOT the same claim as "scores zero", and since #647 it must not be
    written as one. The probe helpers assemble ``f"{_LOCAL}@{_ROUTABLE}"`` at run
    time; the gate now reads a wholly interpolated domain as unprovable; so this
    module has a baseline entry. Re-asserting ``count == 0`` here would be an
    inverted gate — a test that reds precisely because the gate started seeing
    the construction style this file is written in, which is the fix.
    """

    gate = _load()
    matches = gate.matches_in(Path(__file__).read_text(encoding="utf-8"))

    assert [match for match in matches if not match.interpolated] == []
    # The discriminating half. An empty list above is also what a scan that
    # never read the file returns, and what a scanner whose pattern had stopped
    # matching returns. Something has to be found here, or the line above is
    # green for a reason that has nothing to do with this file.
    assert [match for match in matches if match.interpolated] != []


# ---------------------------------------------------------------------------
# #647 — an address that is assembled at run time
#
# A SET NEEDS ONE CASE PER MEMBER. A gate that learned f-strings and stayed
# blind to `%s` would have moved the blind spot rather than closed it, so there
# is a row below for every interpolation form this repository uses, and a
# RESERVED twin for every row. Read the two halves together: a red on its own is
# equally consistent with "the pattern got greedy and now matches everything".
#
# One honesty note about the arithmetic. There are four FORMS but three
# matchers: `{...}` serves f-string fields, `str.format` fields and JavaScript
# template literals alike, so the `f-string` row and the `str-format` row
# exercise the same `_FIELD` pattern and are not two independent proofs. `%s` is
# separate machinery. Concatenation is separate machinery AND the only
# non-regex control flow in the scanner — a loop that walks the `+` chain — so
# it gets both exits tested: a chain ending in a literal (`+ ".com"`) here, and
# a chain ending in an expression (`+ domain`) in the unsealed cases below.
# ---------------------------------------------------------------------------

#: form -> (a routable assembly, its reserved twin). The two differ ONLY in the
#: literal suffix, so a row that reds on the left and greens on the right has
#: isolated the suffix as the cause rather than the interpolation.
ASSEMBLY_FORMS = [
    pytest.param(
        'SENDER = f"careers@{token}.com"',
        'SENDER = f"careers@{token}.test"',
        id="f-string-field",
    ),
    pytest.param(
        'SENDER = "careers@%s.com" % token',
        'SENDER = "careers@%s.test" % token',
        id="percent-s",
    ),
    pytest.param(
        'SENDER = "careers@" + token + ".com"',
        'SENDER = "careers@" + token + ".test"',
        id="concatenation",
    ),
    pytest.param(
        'SENDER = "careers@{0}.com".format(token)',
        'SENDER = "careers@{0}.test".format(token)',
        id="str-format",
    ),
]

#: The same four forms with NO literal suffix at all, because the whole domain
#: interpolates. This is the shape that was hiding real companies' addresses in
#: `test_gmail_oauth_cloud.py`, where `_one_app_batch` and `_ats_msg` both build
#: a sender this way: the template says nothing about where the mail goes and
#: the call site says everything. It has no
#: reserved twin by construction — that is the point. Nothing about
#: `careers@{domain}` can be proved from `careers@{domain}`.
UNSEALED_FORMS = [
    pytest.param('SENDER = f"careers@{domain}"', id="f-string-field"),
    pytest.param('SENDER = "careers@%s" % domain', id="percent-s"),
    pytest.param('SENDER = "careers@" + domain', id="concatenation"),
    pytest.param('SENDER = "careers@{0}".format(domain)', id="str-format"),
]

PROBE = "backend/tests/test_assembled.py"


@pytest.mark.parametrize("routable, reserved", ASSEMBLY_FORMS)
def test_each_assembled_form_reds_and_its_reserved_twin_stays_green(
    tree: Path, routable: str, reserved: str
) -> None:
    """Both directions, per form, end to end through the gate.

    Asserting the exit code alone would not be enough — a red is a red for many
    reasons — so the count for the probe file is asserted too, and the reserved
    twin has to leave the file out of `findings` entirely rather than merely
    exit zero.
    """

    gate = _load()
    _write_baseline(gate, tree)
    probe = tree / "backend" / "tests" / "test_assembled.py"

    probe.write_text(routable + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    findings, skipped = gate.scan(tree)
    assert skipped == []
    assert findings[PROBE].count == 1, findings
    assert _check(gate, tree) == 1

    probe.write_text(reserved + "\n", encoding="utf-8")
    findings, _ = gate.scan(tree)
    assert PROBE not in findings, findings
    assert _check(gate, tree) == 0


@pytest.mark.parametrize("source", UNSEALED_FORMS)
def test_a_wholly_interpolated_domain_cannot_be_proved_and_counts(tree: Path, source: str) -> None:
    """`careers@{domain}` is flagged because nothing in it is sealed.

    This is the case #647 was filed for, and the one that was hiding real
    routable domains: the template is silent about where the mail goes, and the
    call site — a plain string argument, carrying no `@` and so invisible to any
    address scanner — is where the company's own domain actually is.
    """

    gate = _load()
    _write_baseline(gate, tree)
    probe = tree / "backend" / "tests" / "test_assembled.py"
    probe.write_text(source + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)

    findings, _ = gate.scan(tree)
    assert findings[PROBE].count == 1, findings
    assert _check(gate, tree) == 1


@pytest.mark.parametrize(
    "domain, sealed, allowed",
    [
        ("{}", "", False),
        ("{}.com", ".com", False),
        ("{}.test", ".test", True),
        ("{}.invalid", ".invalid", True),
        ("{}.localhost", ".localhost", True),
        ("careers.{}.test", ".test", True),
        ("{}.example.com", ".example.com", True),
        # The two that discriminate, and the reason the rule is not "the tail
        # has to start with a dot". A half-interpolated LABEL under a literal
        # reserved TLD is safe, because the TLD is what decides and no
        # interpolation reaches it — `acme-{n}hub.example` is in this tree, in
        # `test_tracking_sender_checks.py`. A tail that merely LOOKS reserved
        # but is not sealed at a dot is not safe: `{}example.com` interpolates
        # to `notexample.com`, which `is_allowed` already refuses in its literal
        # form and which a sloppier reading of this same rule would pass.
        ("acme-{}hub.example", ".example", True),
        ("{}example.com", ".com", False),
        # No marker at all: the domain is sealed in its entirety, and the
        # function has to agree with the literal path rather than raise on the
        # missing marker. It used to raise; the concatenation-overlap case below
        # is what found that.
        ("northwind.com", "northwind.com", False),
        ("halberd.test", "halberd.test", True),
    ],
)
def test_the_sealed_suffix_is_what_no_interpolation_can_change(
    domain: str, sealed: str, allowed: bool
) -> None:
    gate = _load()
    assert gate.sealed_suffix(domain) == sealed
    assert gate.is_allowed(gate.sealed_suffix(domain)) is allowed


#: A one-line JavaScript object and a one-line Python dict, each holding an
#: address. `ADDRESS` is substituted at run time with `_routable()` for the
#: reason the module note gives — writing the probe out here would put a literal
#: non-reserved address in a scanned root, which is the thing being tested.
BRACE_WRAPPERS = [
    pytest.param(
        'ROWS = [{ sender_email: "ADDRESS", flagged: 1 }]',
        id="single-line-object-literal",
    ),
    pytest.param('M = {"a": _raw("a", "S", "ADDRESS", "")}', id="single-line-dict"),
]


@pytest.mark.parametrize("wrapper", BRACE_WRAPPERS)
def test_a_literal_inside_braces_is_still_read_as_a_literal(wrapper: str) -> None:
    """The regression the obvious implementation of #647 would have shipped.

    Normalising every `{...}` in a file to a marker before scanning is the first
    thing anyone tries, and it eats a single-line JavaScript object or Python
    dict WHOLE — the literal address inside it disappears. Measured on this tree
    before the approach was abandoned: eight real addresses lost, across
    `review-classify.test.mjs`, `test_gmail_client_fetch.py`,
    `test_email_clients.py` and `reclassify-asks-which-application.test.mjs`.
    Markers are matched INSIDE the address pattern instead, never as a pre-pass,
    and these two cases are what says so.
    """

    gate = _load()
    address = _routable()
    assert gate.matches_in(wrapper.replace("ADDRESS", address)) == [gate.Match(address, False)]


def test_an_address_inside_an_assembled_run_is_counted_once() -> None:
    """The two readers must not both bill the same characters.

    `TEMPLATE`/`CONCAT_HEAD` and `EMAIL` scan the same string, and a literal
    address sitting INSIDE a `+` chain is read by both. The shape is contrived —
    it measures zero occurrences in this tree — but the guard against it is real
    code in `matches_in`, and untested code inside a gate is this repository's
    named recurring defect. Delete the `spans` check and this case returns two
    matches for one address.
    """

    gate = _load()
    source = 'S = "reply@" + host + "' + _routable() + '"'
    assert len(gate.matches_in(source)) == 1, gate.matches_in(source)


def test_renaming_the_interpolated_variable_does_not_move_the_digest(
    tree: Path,
) -> None:
    """A template is digested by its LITERAL parts, so `{domain}` -> `{d}` is a
    rename and not a change. The control on the swap case below, and the same
    argument as `test_reordering_the_same_addresses_stays_green`: a gate that
    reddens on a formatting change is a nuisance, and a nuisance gets deleted.
    """

    gate = _load()
    probe = tree / "backend" / "tests" / "test_assembled.py"
    probe.write_text('SENDER = f"careers@{domain}.com"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    _write_baseline(gate, tree)

    probe.write_text('SENDER = f"careers@{d}.com"\n', encoding="utf-8")
    assert _check(gate, tree) == 0


def test_swapping_a_templates_literal_suffix_reds(tree: Path) -> None:
    """The discriminating half of the test above. The count does not move and
    the interpolation does not move; only the literal suffix does, `.com` to
    `.io`. Without this, "renaming stays green" is also consistent with a
    scanner that had stopped distinguishing templates at all.
    """

    gate = _load()
    probe = tree / "backend" / "tests" / "test_assembled.py"
    probe.write_text('SENDER = f"careers@{domain}.com"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    _write_baseline(gate, tree)
    before = _recorded(tree)[PROBE]

    probe.write_text('SENDER = f"careers@{domain}.io"\n', encoding="utf-8")
    findings, _ = gate.scan(tree)
    assert findings[PROBE].count == before["count"] == 1
    assert findings[PROBE].digest != before["digest"]
    assert _check(gate, tree) == 1
