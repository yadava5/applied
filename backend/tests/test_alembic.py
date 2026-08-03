"""Alembic migration smoke tests (issue #16, C2).

These tests validate two invariants the cloud deployment depends on:

1. ``alembic check`` reports no drift between the SQLModel metadata and
   the committed migration chain. If someone edits a model without
   generating a matching revision, CI fails here.
2. ``alembic upgrade head`` successfully applies the whole migration
   chain against a file-backed SQLite database. This proves the
   migrations are syntactically valid and runnable offline (no network
   or Supabase credentials required in CI).

Both tests are subprocess-based so they exercise the exact command a
developer (or CI job) would run, and so they're fully isolated from the
pytest process' in-memory test DB fixture.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_env(database_url: str) -> dict[str, str]:
    """Build a subprocess env with DATABASE_URL set to ``database_url``.

    We copy the current env so ``PATH`` / ``PYTHONPATH`` / virtualenv
    activation variables flow through, and then pin the DB URL Alembic's
    env.py will read.
    """

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    # Make sure any pre-existing DIRECT_URL from a dev shell does not
    # override the ephemeral test URL.
    env.pop("DIRECT_URL", None)
    return env


def _run_alembic(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    """Invoke ``alembic`` via ``python -m alembic`` for portability."""

    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def sqlite_db_path(tmp_path: Path) -> Path:
    """Ephemeral on-disk SQLite file. File-based (not ``:memory:``) so the
    second subprocess invocation in ``test_alembic_check_reports_no_drift``
    sees the schema created by the first.
    """

    return tmp_path / "alembic_smoke.db"


def test_alembic_upgrade_head_applies_cleanly(sqlite_db_path: Path) -> None:
    """`alembic upgrade head` against a fresh SQLite DB must succeed."""

    url = f"sqlite:///{sqlite_db_path}"
    result = _run_alembic(["upgrade", "head"], _alembic_env(url))
    assert result.returncode == 0, (
        "alembic upgrade head failed.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    # Sanity: the DB file now exists and has tables in it.
    assert sqlite_db_path.exists()

    import sqlite3

    conn = sqlite3.connect(sqlite_db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()

    # Every SQLModel table from jobtracker.database.models must be present.
    expected = {
        "alembic_version",
        "applications",
        "contacts",
        "email_embeddings",
        "emails",
        "interviews",
        "sync_state",
        "training_data",
    }
    missing = expected - tables
    assert not missing, f"Alembic migration did not create: {missing}"


def test_alembic_check_reports_no_drift(sqlite_db_path: Path) -> None:
    """`alembic check` must report no drift vs SQLModel metadata.

    This guards against two failure modes:
    - A model was edited without generating a new revision.
    - A generated revision was hand-edited into a state that diverges
      from the live metadata.
    """

    url = f"sqlite:///{sqlite_db_path}"
    env = _alembic_env(url)

    upgrade_result = _run_alembic(["upgrade", "head"], env)
    assert upgrade_result.returncode == 0, upgrade_result.stderr

    check_result = _run_alembic(["check"], env)
    assert check_result.returncode == 0, (
        "alembic check detected drift between metadata and migrations.\n"
        f"STDOUT:\n{check_result.stdout}\n"
        f"STDERR:\n{check_result.stderr}"
    )
    assert "No new upgrade operations detected" in check_result.stdout
