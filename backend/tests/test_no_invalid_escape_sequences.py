r"""No tracked Python in the repo compiles with an invalid-escape warning.

Found 2026-09-02: ``scripts/readme_facts.py`` — the tool whose whole job is to
keep the README honest — printed an invalid-escape warning on every single
``--check`` run. The docstring of :func:`uncaptured_numbers` quoted the regex
``([\d,]+) lost`` in a non-raw string. Harmless today, a ``SyntaxError`` in a
future CPython, which would take the README gate down with it.

The warning had been printing above a green checkmark for days. Nobody reads
warnings that always appear, which is exactly why this belongs in a test.

THE CATEGORY IS NOT A CONSTANT, and assuming it was is how the first draft of
this file shipped a gate that could not fail on the one interpreter CI runs.
CPython promoted invalid escapes from ``DeprecationWarning`` to
``SyntaxWarning`` in 3.12. ``backend-ci.yml`` pins **3.11** in four places, so a
filter written as ``issubclass(category, SyntaxWarning)`` — which is what this
file first did, developed against 3.13 — discards the warning on CI and the scan
passes having examined nothing. So the category is not hardcoded here: it is
asked of the running interpreter by compiling a known-bad string, and it is an
error for that probe to come back empty.

**The control matters more than the scan.** A detector for a *warning* is easy
to build wrong: warnings are stateful and global, and a filter set anywhere in
the process can silence a category for the rest of the run. A scan that finds
nothing then looks identical to a scan that cannot find anything — this
repository's signature defect. So the first two tests below are controls over
the detector and its file list, and only the third asserts the tree is clean.

SCOPE, precisely. "Tracked Python" means ``git ls-files '*.py'``: every file
committed to this repository, which at the time of writing includes ``api/``
(the deployed Vercel entrypoint) and ``ml/`` as well as ``backend/`` and
``scripts/``. An earlier draft scanned two hardcoded directories and called that
"the repo"; two planted offenders in ``api/index.py`` and ``ml/service.py``
were invisible to it. Using git's own index also means no virtualenv, cache or
build directory is walked, so the gate cannot be reddened by somebody else's
code and does not depend on where the checkout happens to live.
"""

from __future__ import annotations

import subprocess
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A source string CPython must warn about on every supported version.
KNOWN_BAD = 'x = "a \\d b"\n'
#: The same string with the fix this gate asks for applied.
KNOWN_GOOD = 'x = r"a \\d b"\n'


def _invalid_escape_category() -> type[Warning]:
    """Ask THIS interpreter which warning class an invalid escape raises.

    ``DeprecationWarning`` before CPython 3.12, ``SyntaxWarning`` from 3.12.
    Probed rather than derived from ``sys.version_info`` so that the gate keeps
    working if the classification moves again.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(KNOWN_BAD, "<probe>", "exec")
        for item in caught:
            if "invalid escape sequence" in str(item.message):
                return item.category
    raise AssertionError(
        "this interpreter raised no warning for an invalid escape sequence; "
        "the scan below would examine every file and report nothing"
    )


def _tracked_python() -> list[Path]:
    """Every ``*.py`` file git has in its index, as repo-relative paths.

    Deliberately not ``rglob``: a filesystem walk has to be told about
    virtualenvs, caches and build output, and the first draft's exclusion list
    got that wrong twice — once by matching ``.venv`` exactly where a
    ``.venv311`` also existed, and once by filtering the ABSOLUTE path, which
    collects zero files in any checkout living under a ``.claude`` worktree.
    Git already knows what is ours.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "*.py"],
        capture_output=True,
        check=True,
    )
    return [Path(name) for name in result.stdout.decode().split("\0") if name]


def _invalid_escape_warnings(source: str, filename: str) -> list[str]:
    """Every invalid-escape warning raised by compiling ``source``.

    ``catch_warnings`` restores the global filter state on exit, and
    ``simplefilter("always")`` defeats the once-per-location dedupe that would
    otherwise hide a warning already emitted by an earlier import.
    """
    category = _invalid_escape_category()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(source, filename, "exec")
        return [
            f"{filename}:{item.lineno}: {item.message}"
            for item in caught
            if issubclass(item.category, category)
            and "invalid escape sequence" in str(item.message)
        ]


def test_the_detector_fires_on_a_known_bad_source() -> None:
    """The control: this is what the scan below is looking for.

    Without this, a disarmed detector and a clean repo produce the same green.
    """
    bad = _invalid_escape_warnings(KNOWN_BAD, "<known-bad>")
    assert bad, "the detector reported nothing on source that must warn"
    assert "invalid escape sequence" in bad[0]

    # ...and it stays quiet on the raw-string form, which is the fix this gate
    # asks for. A detector that fired on everything would satisfy the assertion
    # above and fail this one.
    assert _invalid_escape_warnings(KNOWN_GOOD, "<known-good>") == []


def test_the_scan_reaches_every_tracked_root_and_no_untracked_one() -> None:
    """The scan is worthless if its file list misses the code it must cover.

    ``scripts/`` sits outside ``backend/``, and ``api/index.py`` is the deployed
    entrypoint; a collector rooted at the test directory, or at two hardcoded
    directories, silently skips them.
    """
    scanned = {path.as_posix() for path in _tracked_python()}

    assert "scripts/readme_facts.py" in scanned, "the file this gate exists for"
    assert any(name.startswith("backend/") for name in scanned)
    assert len(scanned) > 100, f"only {len(scanned)} files collected"

    # Nothing vendored or generated may reach the report: those warnings are not
    # ours to fix and would make the gate un-greenable for someone else's code.
    # git's index gives this for free, and this pins that it stays true.
    leaked = [
        name
        for name in scanned
        if "node_modules" in name
        or "site-packages" in name
        or name.startswith(".venv")
        or "/.venv" in name
    ]
    assert leaked == [], f"untracked or vendored code reached the scan: {leaked[:3]}"


def test_no_tracked_python_has_an_invalid_escape_sequence() -> None:
    offenders: list[str] = []
    for relative in _tracked_python():
        source = (REPO_ROOT / relative).read_text(encoding="utf-8", errors="replace")
        offenders.extend(_invalid_escape_warnings(source, relative.as_posix()))
    assert not offenders, "invalid escape sequence in tracked Python:\n" + "\n".join(
        offenders
    )
