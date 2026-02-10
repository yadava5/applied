"""
Database Module
===============

Provides async SQLite database access using aiosqlite and SQLModel.

Components:
-----------
- models: SQLModel table definitions (Application, Email, Contact, etc.)
- connection: Async engine and session management with WAL mode

The database is stored at:
    ~/Library/Application Support/JobTracker/jobtracker.db

Usage:
------
    from jobtracker.database import get_session, init_db
    from jobtracker.database.models import Application, Email

    # Initialize database on startup
    await init_db()

    # Use session for database operations
    async with get_session() as session:
        result = await session.exec(select(Application))
        apps = result.all()
"""

from jobtracker.database.connection import (
    close_db,
    get_db_stats,
    get_engine,
    get_session,
    get_session_dependency,
    init_db,
    vacuum_db,
)

__all__ = [
    "close_db",
    "get_db_stats",
    "get_engine",
    "get_session",
    "get_session_dependency",
    "init_db",
    "vacuum_db",
]
