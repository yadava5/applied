"""
Database Connection Module
==========================

Async SQLite database connection using aiosqlite and SQLModel.

Provides:
- Async engine with WAL mode for concurrent access
- Session factory for database operations
- Context manager for automatic session cleanup
- Database initialization function

WAL Mode:
---------
Write-Ahead Logging (WAL) allows concurrent reads while writing.
This is essential for the two-process architecture where:
- Python backend writes to the database
- SwiftUI frontend reads via GRDB.swift

Usage:
------
    from jobtracker.database.connection import get_session, init_db

    # Initialize database (creates tables)
    await init_db()

    # Use session context manager
    async with get_session() as session:
        result = await session.exec(select(Application))
        applications = result.all()

    # Or get session manually
    async for session in get_session():
        # do work
        await session.commit()
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, text
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.config import settings

logger = logging.getLogger(__name__)

# Global engine instance (created on first use)
_engine: Optional[AsyncEngine] = None


def get_engine() -> AsyncEngine:
    """
    Get or create the async database engine.

    The engine is created once and reused for all connections.
    Uses StaticPool for SQLite to ensure a single connection
    is shared across all async operations.

    Returns:
        AsyncEngine: SQLAlchemy async engine instance.
    """
    global _engine

    if _engine is None:
        # Ensure database directory exists
        settings.ensure_directories()

        logger.info(f"Creating database engine: {settings.database_path}")

        _engine = create_async_engine(
            settings.database_url,
            echo=settings.environment == "development",
            # SQLite-specific settings
            connect_args={
                "check_same_thread": False,  # Required for async
            },
            # Use StaticPool for SQLite to share connection
            poolclass=StaticPool,
        )

    return _engine


async def init_db() -> None:
    """
    Initialize the database.

    Creates all tables and enables WAL mode for concurrent access.
    Safe to call multiple times (tables are only created if missing).

    This should be called on application startup.
    """
    # Import models to register them with SQLModel metadata
    # This MUST happen before create_all() is called
    from jobtracker.database import models  # noqa: F401

    engine = get_engine()

    logger.info("Initializing database...")

    async with engine.begin() as conn:
        # Enable WAL mode for concurrent read/write access
        # This allows SwiftUI to read while Python writes
        await conn.execute(text("PRAGMA journal_mode=WAL"))

        # Wait up to 5 seconds for locks (prevents immediate failures)
        await conn.execute(text("PRAGMA busy_timeout=5000"))

        # Enable foreign key constraints (disabled by default in SQLite)
        await conn.execute(text("PRAGMA foreign_keys=ON"))

        # Create all tables from SQLModel metadata
        await conn.run_sync(SQLModel.metadata.create_all)

    logger.info(f"Database initialized at: {settings.database_path}")


async def close_db() -> None:
    """
    Close the database connection.

    Should be called on application shutdown to cleanly
    close all database connections.
    """
    global _engine

    if _engine is not None:
        logger.info("Closing database connection...")
        await _engine.dispose()
        _engine = None
        logger.info("Database connection closed")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.

    Use as a context manager for automatic cleanup:

        async with get_session() as session:
            result = await session.exec(select(Application))
            apps = result.all()

    The session is automatically closed when exiting the context.
    Changes are NOT automatically committed - call session.commit()
    or session.flush() to persist changes.

    Yields:
        AsyncSession: SQLModel async session for database operations.
    """
    engine = get_engine()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Use with FastAPI's Depends() for automatic injection:

        @app.get("/applications")
        async def list_applications(session: AsyncSession = Depends(get_session_dependency)):
            result = await session.exec(select(Application))
            return result.all()

    Yields:
        AsyncSession: SQLModel async session.
    """
    async with get_session() as session:
        yield session


# =============================================================================
# Database Utilities
# =============================================================================


async def get_db_stats() -> dict:
    """
    Get database statistics for health checks.

    Returns:
        dict: Database statistics including table counts.
    """
    from jobtracker.database.models import Application, Email, TrainingData

    async with get_session() as session:
        # Get table counts
        app_count = await session.exec(
            text("SELECT COUNT(*) FROM applications")
        )
        email_count = await session.exec(
            text("SELECT COUNT(*) FROM emails")
        )
        training_count = await session.exec(
            text("SELECT COUNT(*) FROM training_data")
        )

        # Get database file size
        db_size_result = await session.exec(
            text("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
        )

        return {
            "path": str(settings.database_path),
            "applications": app_count.scalar() or 0,
            "emails": email_count.scalar() or 0,
            "training_examples": training_count.scalar() or 0,
            "size_bytes": db_size_result.scalar() or 0,
        }


async def vacuum_db() -> None:
    """
    Vacuum the database to reclaim space.

    Should be run periodically (e.g., weekly) to:
    - Reclaim space from deleted rows
    - Rebuild indexes for better performance
    - Reduce database file size
    """
    engine = get_engine()

    logger.info("Vacuuming database...")

    async with engine.begin() as conn:
        await conn.execute(text("VACUUM"))

    logger.info("Database vacuumed successfully")
