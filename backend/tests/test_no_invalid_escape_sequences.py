"""No Python source in the repo compiles with a ``SyntaxWarning``.

Found 2026-09-02: ``scripts/readme_facts.py`` — the tool whose whole job is to
keep the README honest — printed an invalid-escape ``SyntaxWarning`` on every
single ``--check`` run. The docstring of :func:`uncaptured_numbers` quoted the
regex ``([\\d,]+) lost`` in a non-raw string. Harmless today; a ``SyntaxError``
in a future CPython, which would take the README gate down with it.

The warning had been printing above a green checkmark for days. Nobody reads
warnings that always appear, which is exactly why this belongs in a test rather
than in a human's attention.

**The control matters more than the scan.** A detector for a *warning* is easy
to build wrong: warnings are stateful and global, and a filter set anywhere in
the process can silence the category for the rest of the run. A scan that finds
nothing then looks identical to a scan that cannot find anything —
the estate's signature defect. So
:func:`test_the_detector_fires_on_a_known_bad_source` feeds the detector source
that is *known* to warn and requires it to report. If that test ever passes
while the scan is silently disarmed, the scan's green means nothing.
"""

from __future__ import annotations

import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that hold first-party Python. Vendored trees are excluded: their
# warnings are not ours to fix and would make this gate un-greenable.
SOURCE_DIRS = ("scripts", "backend")
EXCLUDED_PARTS = {"node_modules", ".git", "__pycache__", ".claude", "site-packages"}
# Local virtualenvs are named inconsistently — this machine carries both
# ``.venv`` (3.13) and ``.venv311``. An exact-name exclusion missed the second
# and pulled four ``pydub`` warnings into the report, which would have made the
# gate red for a third party's code on any machine that happened to have that
# directory. Match the prefix, not the name.
EXCLUDED_PREFIXES = (".venv",)


def _is_first_party(path: Path) -> bool:
    parts = path.parts
    if not EXCLUDED_PARTS.isdisjoint(parts):
        return False
    return not any(part.startswith(EXCLUDED_PREFIXES) for part in parts)


def _python_files() -> list[Path]:
    found: list[Path] = []
    for directory in SOURCE_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            if _is_first_party(path):
                found.append(path)
    return found


def _syntax_warnings(source: str, filename: str) -> list[str]:
    """Every ``SyntaxWarning`` raised by compiling ``source``.

    ``catch_warnings`` restores the global filter state on exit, and
    ``simplefilter("always")`` defeats the once-per-location dedupe that would
    otherwise hide a warning already emitted by an earlier import.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(source, filename, "exec")
        return [
            f"{filename}:{item.lineno}: {item.message}"
            for item in caught
            if issubclass(item.category, SyntaxWarning)
        ]


def test_the_detector_fires_on_a_known_bad_source() -> None:
    """The control: this is what the scan below is looking for.

    Without this, a disarmed detector and a clean repo produce the same green.
    """
    bad = _syntax_warnings('x = "a \\d b"\n', "<known-bad>")
    assert bad, "the detector reported nothing on source that must warn"
    assert "invalid escape sequence" in bad[0]

    # And it stays quiet on the raw-string form — the fix this gate asks for.
    assert _syntax_warnings('x = r"a \\d b"\n', "<known-good>") == []


def test_the_scan_actually_reaches_the_file_that_regressed() -> None:
    """The scan is worthless if its file list misses the offender.

    ``scripts/`` sits outside ``backend/``, so a collector rooted at the test
    directory would silently skip the exact file this gate was written for.
    """
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _python_files()}
    assert "scripts/readme_facts.py" in scanned
    assert any(name.startswith("backend/") for name in scanned)
    assert len(scanned) > 100, f"only {len(scanned)} files collected"

    # ...and the exclusion is not doing the scan's job for it. An over-broad
    # filter would leave the assertions above satisfiable while quietly dropping
    # most of the tree, so pin both directions: no vendored path survives, and
    # a directory named ``.venv311`` is excluded as surely as ``.venv``.
    vendored = [name for name in scanned if "/.venv" in f"/{name}" or "site-packages" in name]
    assert vendored == [], f"vendored code reached the scan: {vendored[:3]}"
    assert not _is_first_party(REPO_ROOT / "backend" / ".venv311" / "x.py")
    assert not _is_first_party(REPO_ROOT / "backend" / ".venv" / "x.py")
    assert _is_first_party(REPO_ROOT / "backend" / "tests" / "x.py")


def test_no_first_party_python_emits_a_syntax_warning() -> None:
    offenders: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        offenders.extend(
            _syntax_warnings(source, path.relative_to(REPO_ROOT).as_posix())
        )
    assert not offenders, "SyntaxWarning in first-party Python:\n" + "\n".join(
        offenders
    )
