"""The test-data gate has to be able to fail — issue #593.

This repository's named recurring defect is a check that cannot fail, and it has
shipped four rounds of one. ``scripts/check_test_data.py`` makes three claims,
and each of the three is a separate code path:

* a count going UP in a file the baseline already lists   -> red
* a file appearing that the baseline does not list at all -> red
* an address on an RFC-reserved domain                    -> green

The third is not padding. A gate that reddened on ``careers@halberd.test`` would
punish the exact shape ``docs/TEST_DATA_POLICY.md`` tells people to write, which
is the inverted-gate failure: a check that defends the bug.

Note on this file
-----------------

``backend/tests/`` is one of the roots the gate scans, so a literal offending
address written here would become its own baseline entry — the checker would
have been made to republish, in the file that tests it, the material it exists
to stop. Every probe address is therefore assembled at run time from fragments
split at the ``@``, so no address is ever present in this source. See
:func:`test_this_module_is_not_itself_a_finding`, which asserts it.
"""

from __future__ import annotations

import importlib.util
import json
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
_RESERVED = "careers.example.test"


def _routable() -> str:
    """An address on a domain that is NOT RFC-reserved. The thing being caught."""

    return f"{_LOCAL}@{_ROUTABLE}"


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
    """A throwaway git repo shaped like this one, with one baselined finding.

    Real ``git ls-files`` rather than a stub: tracked-ness is half of what the
    checker asserts, and a stub would let an untracked file — the ``node_modules``
    case — pass a test it would fail in production.
    """

    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    tests = tmp_path / "backend" / "tests"
    tests.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()

    (tests / "test_existing.py").write_text(
        f'SENDER = "{_routable()}"\n', encoding="utf-8"
    )
    (tests / "test_clean.py").write_text(
        f'SENDER = "{_reserved()}"\n', encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True
    )
    return tmp_path


def _baseline(tree: Path) -> Path:
    return tree / "scripts" / "test_data_baseline.json"


def _write_baseline(gate, tree: Path) -> None:
    assert gate.main(["--write-baseline", "--repo-root", str(tree)]) == 0


def _check(gate, tree: Path) -> int:
    return gate.main(["--repo-root", str(tree)])


def test_a_clean_tree_is_green(tree: Path) -> None:
    """The recorded state passes. Without this the reds below prove nothing."""

    gate = _load()
    _write_baseline(gate, tree)

    recorded = json.loads(_baseline(tree).read_text(encoding="utf-8"))["counts"]
    assert recorded == {"backend/tests/test_existing.py": 1}, recorded
    assert _check(gate, tree) == 0


def test_the_baseline_never_records_the_offending_string(tree: Path) -> None:
    """Paths and counts only. A baseline holding the strings has republished them."""

    gate = _load()
    _write_baseline(gate, tree)

    raw = _baseline(tree).read_text(encoding="utf-8")
    assert _ROUTABLE not in raw
    assert _LOCAL not in raw


def test_a_count_going_up_in_a_baselined_file_reds(tree: Path) -> None:
    gate = _load()
    _write_baseline(gate, tree)

    path = tree / "backend" / "tests" / "test_existing.py"
    path.write_text(
        f'SENDER = "{_routable()}"\nOTHER = "hr@{_ROUTABLE}"\n', encoding="utf-8"
    )
    assert _check(gate, tree) == 1


def test_a_brand_new_file_reds(tree: Path) -> None:
    """A separate path from the count compare: nothing to compare against."""

    gate = _load()
    _write_baseline(gate, tree)

    new = tree / "backend" / "tests" / "test_added.py"
    new.write_text(f'SENDER = "{_routable()}"\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=tree, check=True, capture_output=True
    )
    assert _check(gate, tree) == 1


def test_a_reserved_domain_stays_green(tree: Path) -> None:
    """The policy's recommended shape must not be what turns the build red."""

    gate = _load()
    _write_baseline(gate, tree)

    new = tree / "backend" / "tests" / "test_more_clean.py"
    new.write_text(
        f'A = "{_reserved()}"\nB = "careers@halberd.test"\n'
        'C = "hiring@northwind.example"\nD = "x@y.invalid"\n'
        'E = "dev@example.com"\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=tree, check=True, capture_output=True
    )
    assert _check(gate, tree) == 0


def test_an_untracked_file_is_not_scanned(tree: Path) -> None:
    """``node_modules`` and ``.venv`` are why this reads git and not the disk."""

    gate = _load()
    _write_baseline(gate, tree)

    stray = tree / "backend" / "tests" / "node_modules"
    stray.mkdir()
    (stray / "vendor.js").write_text(
        f'const s = "{_routable()}";\n', encoding="utf-8"
    )
    assert _check(gate, tree) == 0


def test_a_count_going_down_does_not_fail(tree: Path) -> None:
    """Down is allowed. It is also never routine — the message says so."""

    gate = _load()
    _write_baseline(gate, tree)

    path = tree / "backend" / "tests" / "test_existing.py"
    path.write_text(f'SENDER = "{_reserved()}"\n', encoding="utf-8")
    assert _check(gate, tree) == 0


def test_a_docstring_is_scanned_not_just_a_literal(tree: Path) -> None:
    """The leak #593 predicted arrived through a module docstring, not a fixture."""

    gate = _load()
    _write_baseline(gate, tree)

    new = tree / "backend" / "tests" / "test_docstring.py"
    new.write_text(f'"""Graded against {_routable()}."""\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=tree, check=True, capture_output=True
    )
    assert _check(gate, tree) == 1


def test_this_module_is_not_itself_a_finding() -> None:
    """This file lives inside a scanned root. It must score zero."""

    gate = _load()
    assert gate.count_file(Path(__file__)) == 0
