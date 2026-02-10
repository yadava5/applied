"""
Test Configuration
==================

Shared pytest fixtures and configuration.

This module provides:
- Test database setup with in-memory SQLite
- Test client for API testing
- Common test data factories

Fixtures are automatically discovered by pytest.
"""

import pytest
from typing import AsyncGenerator

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


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


@pytest.fixture
async def test_client() -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for API testing.

    Uses httpx to make requests to the FastAPI app.
    """
    from jobtracker.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


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
