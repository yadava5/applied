"""The run says which tests did not run, and why — issue #470.

`pytest -q` on a machine with no Docker prints `1726 passed, 56 skipped`. The 56
include all 21 row-level-security tests, which are the only proof in the
repository that tenant isolation is enforced by the database rather than by
application code that could forget a WHERE clause. That summary line is what a
person reads before deciding a change is safe, and it never said which 56.

Two halves here, and both are needed. The unit cases pin the formatting without
arranging for a machine to lack Docker. The subprocess cases prove the hook is
actually WIRED — a perfectly-formatted function that `conftest.py` never calls
would satisfy every unit case in this file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.skip_report import clean_reason, summarise_skips

BACKEND_DIR = Path(__file__).resolve().parent.parent

#: A socket that cannot exist, so `PostgresContainer.start()` raises, so
#: `ADMIN_URL` is None, so every Postgres module skips. This is the reported
#: scenario reproduced rather than described.
NO_DOCKER = "unix:///nonexistent-for-this-test.sock"


def test_nothing_skipped_prints_nothing() -> None:
    """The common path stays silent. A report on every run is one nobody reads."""

    assert summarise_skips([]) is None


def test_the_modules_and_their_reasons_are_named() -> None:
    lines = summarise_skips(
        [
            ("tests/test_rls_postgres.py::test_a", "Skipped: no Postgres"),
            ("tests/test_rls_postgres.py::test_b", "Skipped: no Postgres"),
            ("tests/test_migrations_postgres.py::test_c", "Skipped: no Postgres"),
        ]
    )
    assert lines is not None
    body = "\n".join(lines)
    assert "3 tests did not run" in body
    assert "tests/test_rls_postgres.py: 2 skipped — no Postgres" in body
    assert "tests/test_migrations_postgres.py: 1 skipped — no Postgres" in body


def test_a_module_skipping_for_two_reasons_reports_both() -> None:
    """Otherwise the second cause hides behind the first, which is the bug again."""

    lines = summarise_skips(
        [
            ("tests/test_x.py::a", "Skipped: no Docker"),
            ("tests/test_x.py::b", "Skipped: no Docker"),
            ("tests/test_x.py::c", "Skipped: needs a network"),
        ]
    )
    body = "\n".join(lines or [])
    assert "2 skipped — no Docker" in body
    assert "1 skipped — needs a network" in body


def test_one_skip_is_not_pluralised() -> None:
    lines = summarise_skips([("tests/test_x.py::a", "Skipped: because")])
    assert lines is not None and "1 test did not run" in lines[0]


def test_pytests_own_prefix_is_stripped_and_the_reason_is_one_line() -> None:
    assert clean_reason("Skipped: a reason\n  wrapped over lines") == "a reason wrapped over lines"


def _run(args: list[str], env_extra: dict[str, str]) -> str:
    env = dict(os.environ)
    env["JOBTRACKER_ENVIRONMENT"] = "test"
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env.pop("JOBTRACKER_TEST_PG_ADMIN_URL", None)
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q", "-p", "no:cacheprovider",
         "--override-ini=addopts="],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=900,
    )
    return proc.stdout + proc.stderr


def test_a_real_run_with_no_docker_names_the_rls_suite() -> None:
    """End to end, against the reported scenario rather than a description of it."""

    out = _run(["tests/test_rls_postgres.py"], {"DOCKER_HOST": NO_DOCKER})
    assert "tests that did not run" in out, out[-3000:]
    assert "tests/test_rls_postgres.py" in out
    assert "21 skipped" in out
    assert "UNVERIFIED" in out, "the module's own reason should reach the reader"


def test_a_run_where_nothing_skips_says_nothing() -> None:
    """Directional control. Without it, a block printed unconditionally passes above."""

    out = _run(["tests/test_a_skip_is_named.py::test_one_skip_is_not_pluralised"], {})
    assert "tests that did not run" not in out, out[-3000:]
