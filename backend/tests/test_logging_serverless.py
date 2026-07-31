"""
Logging must not depend on a writable filesystem.

`main_cloud.py` calls `setup_logging()` at MODULE IMPORT time, with the default
`log_to_file=True`. That default was written for the desktop build, where
rotating files under ~/Library/Logs/JobTracker are correct. On Vercel the
filesystem outside /tmp is read-only, nothing survives the invocation, and the
platform already collects stdout — so the file handlers are wasted work at best
and an OSError raised during a cold start at worst.

These tests pin both halves: serverless skips file handlers entirely, and a
directory that cannot be created degrades to console logging rather than taking
the process down.
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from jobtracker.logging import _is_serverless, setup_logging

SERVERLESS_MARKERS = [
    "VERCEL",
    "AWS_LAMBDA_FUNCTION_NAME",
    "FUNCTIONS_WORKER_RUNTIME",
    "K_SERVICE",
]


@pytest.fixture(autouse=True)
def _clean_env_and_handlers(monkeypatch):
    """Each test starts with no serverless markers and a clean root logger."""
    for marker in SERVERLESS_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    yield
    logging.getLogger().handlers.clear()


def _file_handlers():
    return [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]


@pytest.mark.parametrize("marker", SERVERLESS_MARKERS)
def test_detects_each_serverless_platform(monkeypatch, marker):
    assert _is_serverless() is False
    monkeypatch.setenv(marker, "1")
    assert _is_serverless() is True


def test_serverless_adds_no_file_handlers(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(
        "jobtracker.logging.settings.log_dir", str(tmp_path / "logs"), raising=False
    )

    setup_logging(log_to_file=True)

    assert _file_handlers() == []
    # Console logging still works — this is not "logging off".
    assert logging.getLogger().handlers, "expected at least a console handler"


def test_desktop_still_writes_files(monkeypatch, tmp_path):
    """The desktop behaviour this module was written for must be unchanged."""
    monkeypatch.setattr(
        "jobtracker.logging.settings.log_dir", str(tmp_path / "logs"), raising=False
    )

    setup_logging(log_to_file=True)

    assert _file_handlers(), "desktop build should still get rotating file handlers"


def test_unwritable_log_dir_does_not_crash_startup(monkeypatch, tmp_path):
    """
    A read-only location must degrade to console logging, not raise. This is the
    case that would have taken down a cold start, because setup_logging() runs
    at import time in main_cloud.py.
    """
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)  # r-x: cannot create children
    monkeypatch.setattr(
        "jobtracker.logging.settings.log_dir", str(readonly / "nested"), raising=False
    )

    try:
        setup_logging(log_to_file=True)  # must not raise
        assert _file_handlers() == []
        assert logging.getLogger().handlers, "console logging must survive"
    finally:
        readonly.chmod(0o700)
