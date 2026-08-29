"""
Test Configuration
==================

Shared pytest fixtures and configuration.

This module provides:
- Test database setup with in-memory SQLite
- Common test data factories

IMPORTANT: This file also ensures that tests run against an isolated,
in-memory SQLite database by setting JOBTRACKER_ENVIRONMENT=test BEFORE
the database engine is imported.

Fixtures are automatically discovered by pytest.
"""

import os
from typing import AsyncGenerator

import pytest

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Ensure the app uses the test environment (in-memory DB) for all tests.
os.environ.setdefault("JOBTRACKER_ENVIRONMENT", "test")


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
async def test_engine():
    """
    Create a test database engine with in-memory SQLite.

    This provides a fresh database for each test module.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create a test database session.

    Each test gets a fresh session with automatic rollback.
    """
    async with AsyncSession(test_engine, expire_on_commit=False) as session:
        yield session


# =============================================================================
# API Client Fixtures
# =============================================================================
#
# There is no shared client fixture here any more. It built
# ``jobtracker.main.app`` -- the DESKTOP FastAPI app -- which was deleted along
# with the unmounted desktop routers it mounted (issue #73, ``apps/macos``
# de-scoped 2026-08-12). Its only consumers went with it.
#
# The cloud app is deliberately NOT given a fixture in its place. Every cloud
# suite that needs one builds it locally, because it has to reload
# ``jobtracker.config`` under ``JOBTRACKER_DEPLOYMENT=cloud`` first and then
# dispose of the engine -- see the ``cloud_app`` fixture in
# tests/test_status_vocabulary.py. A module-scoped client here would leak that
# reloaded settings object into every other test in the session.


# =============================================================================
# Test Data Factories
# =============================================================================


class ApplicationFactory:
    """Factory for creating test Application instances."""

    @staticmethod
    def create(**kwargs) -> dict:
        """Create application data with defaults."""
        from jobtracker.database.models import ApplicationStatus

        defaults = {
            "company": "Test Company",
            "position": "Software Engineer",
            "status": ApplicationStatus.APPLIED,
        }
        defaults.update(kwargs)
        return defaults


class EmailFactory:
    """Factory for creating test Email instances."""

    _counter = 0

    @classmethod
    def create(cls, **kwargs) -> dict:
        """Create email data with unique message_id."""
        from datetime import datetime
        from jobtracker.database.models import EmailSource

        cls._counter += 1
        defaults = {
            "source_account": EmailSource.GMAIL,
            "message_id": f"<test-{cls._counter}@test.com>",
            "received_at": datetime.utcnow(),
            "subject": "Test Email",
            "sender_email": "sender@test.com",
        }
        defaults.update(kwargs)
        return defaults


@pytest.fixture
def application_factory():
    """Provide ApplicationFactory for tests."""
    return ApplicationFactory


@pytest.fixture
def email_factory():
    """Provide EmailFactory for tests."""
    return EmailFactory


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001, ARG001
    """Name what did not run, at the bottom of the run, where the count is.

    See ``tests/skip_report.py`` for why this reports rather than fails. The
    formatting lives there so it can be tested without arranging for a machine
    to lack Docker; this hook only pulls the pairs out of pytest's own stats.
    """

    from tests.skip_report import summarise_skips

    entries = [
        (report.nodeid, str(report.longrepr[2]) if report.longrepr else "")
        for report in terminalreporter.stats.get("skipped", [])
    ]
    lines = summarise_skips(entries)
    if lines is None:
        return

    terminalreporter.write_sep("=", "tests that did not run", yellow=True, bold=True)
    for line in lines:
        terminalreporter.write_line(line, yellow=True)
