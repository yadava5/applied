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

    async with get_session() as session:
        apps = await session.exec(select(Application))
"""

from jobtracker.database.connection import get_session, init_db

__all__ = ["get_session", "init_db"]
