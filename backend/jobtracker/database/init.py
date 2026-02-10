"""
Database Initialization Script
==============================

CLI script to initialize or reset the JobTracker database.

Usage:
------
    # Initialize database (create tables if not exist)
    python -m jobtracker.database.init

    # Reset database (drop all tables and recreate)
    python -m jobtracker.database.init --reset

    # Show database info
    python -m jobtracker.database.init --info
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from jobtracker.config import settings
from jobtracker.logging import setup_logging

setup_logging(log_to_file=False)
logger = logging.getLogger(__name__)


async def init_database() -> None:
    """
    Initialize the database.

    Creates all tables if they don't exist.
    Enables WAL mode for concurrent access.
    """
    from jobtracker.database import init_db

    logger.info(f"Database path: {settings.database_path}")

    await init_db()

    logger.info("Database initialized successfully!")


async def reset_database() -> None:
    """
    Reset the database.

    WARNING: This deletes all data!
    Drops all tables and recreates them.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel

    logger.warning("=" * 60)
    logger.warning("WARNING: This will delete ALL data!")
    logger.warning("=" * 60)

    # Confirm reset
    confirm = input("Type 'RESET' to confirm: ")
    if confirm != "RESET":
        logger.info("Reset cancelled.")
        return

    logger.info(f"Resetting database: {settings.database_path}")

    # Delete existing database file
    db_path = settings.database_path
    if db_path.exists():
        # Also delete WAL and SHM files
        for suffix in ["", "-wal", "-shm"]:
            path = Path(str(db_path) + suffix)
            if path.exists():
                path.unlink()
                logger.info(f"Deleted: {path}")

    # Recreate database
    await init_database()

    logger.info("Database reset complete!")


async def show_info() -> None:
    """
    Show database information.

    Displays path, size, and table statistics.
    """
    from jobtracker.database import get_db_stats, init_db

    # Initialize if needed
    await init_db()

    stats = await get_db_stats()

    print("\n" + "=" * 60)
    print("JobTracker Database Information")
    print("=" * 60)
    print(f"Path:               {stats['path']}")
    print(f"Size:               {stats['size_bytes'] / 1024:.1f} KB")
    print("-" * 60)
    print(f"Applications:       {stats['applications']}")
    print(f"Emails:             {stats['emails']}")
    print(f"Training Examples:  {stats['training_examples']}")
    print("=" * 60 + "\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Initialize or manage the JobTracker database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m jobtracker.database.init           # Initialize database
  python -m jobtracker.database.init --reset   # Reset database (deletes data!)
  python -m jobtracker.database.init --info    # Show database info
        """,
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset database (WARNING: deletes all data!)",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Show database information",
    )

    args = parser.parse_args()

    if args.reset:
        asyncio.run(reset_database())
    elif args.info:
        asyncio.run(show_info())
    else:
        asyncio.run(init_database())


if __name__ == "__main__":
    main()
