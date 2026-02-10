"""
Logging Module
==============

Structured logging configuration for the JobTracker backend.

Provides:
- Console logging with colored output (development)
- File logging with rotation (production)
- Async-safe logging handlers
- Structured log format with timestamps

Log files are stored at:
    ~/Library/Logs/JobTracker/
        - backend.log: Main application log
        - error.log: Error-only log

Usage:
------
    from jobtracker.logging import setup_logging
    import logging

    # Setup on app startup
    setup_logging()

    # Use standard logging
    logger = logging.getLogger(__name__)
    logger.info("Application started")
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from jobtracker.config import settings


# =============================================================================
# Custom Formatter with Colors
# =============================================================================


class ColoredFormatter(logging.Formatter):
    """
    Custom formatter with ANSI color codes for terminal output.

    Colors:
    - DEBUG: Cyan
    - INFO: Green
    - WARNING: Yellow
    - ERROR: Red
    - CRITICAL: Bold Red
    """

    # ANSI color codes
    COLORS = {
        logging.DEBUG: "\033[36m",      # Cyan
        logging.INFO: "\033[32m",       # Green
        logging.WARNING: "\033[33m",    # Yellow
        logging.ERROR: "\033[31m",      # Red
        logging.CRITICAL: "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with color codes."""
        # Add color to levelname
        color = self.COLORS.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"

        return super().format(record)


# =============================================================================
# Logging Setup
# =============================================================================


def setup_logging(
    level: Optional[str] = None,
    log_to_file: bool = True,
) -> None:
    """
    Configure logging for the application.

    Sets up:
    - Console handler with colors (always)
    - File handlers with rotation (if log_to_file=True)

    Args:
        level: Log level override (default: from settings)
        log_to_file: Whether to write logs to files
    """
    # Get log level
    log_level = getattr(logging, level or settings.log_level)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Use colored formatter for console
    console_formatter = ColoredFormatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt=settings.log_date_format,
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handlers (production or if explicitly requested)
    if log_to_file:
        _setup_file_handlers(root_logger, log_level)

    # Reduce noise from third-party libraries
    _configure_library_loggers()

    logging.info(f"Logging configured: level={settings.log_level}, file={log_to_file}")


def _setup_file_handlers(
    root_logger: logging.Logger,
    log_level: int,
) -> None:
    """
    Set up file handlers with rotation.

    Creates:
    - backend.log: All logs at configured level
    - error.log: ERROR and above only
    """
    # Ensure log directory exists
    log_dir = settings.log_path
    log_dir.mkdir(parents=True, exist_ok=True)

    # Standard formatter for files (no colors)
    file_formatter = logging.Formatter(
        fmt=settings.log_format,
        datefmt=settings.log_date_format,
    )

    # Main log file (all levels)
    main_log = log_dir / "backend.log"
    main_handler = RotatingFileHandler(
        main_log,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    main_handler.setLevel(log_level)
    main_handler.setFormatter(file_formatter)
    root_logger.addHandler(main_handler)

    # Error log file (ERROR and above)
    error_log = log_dir / "error.log"
    error_handler = RotatingFileHandler(
        error_log,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)


def _configure_library_loggers() -> None:
    """
    Configure log levels for third-party libraries.

    Reduces noise from verbose libraries while keeping
    important warnings and errors.
    """
    # Reduce SQLAlchemy verbosity
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    # Reduce aiosqlite verbosity
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    # Reduce uvicorn access log verbosity in development
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Keep uvicorn errors visible
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    # Reduce httpx/httpcore verbosity (used by Google API client)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Reduce sentence-transformers verbosity
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

    # Reduce torch verbosity
    logging.getLogger("torch").setLevel(logging.WARNING)


# =============================================================================
# Utility Functions
# =============================================================================


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a module.

    Convenience function that's equivalent to logging.getLogger().

    Args:
        name: Logger name (usually __name__)

    Returns:
        logging.Logger: Configured logger instance
    """
    return logging.getLogger(name)


class LogContext:
    """
    Context manager for temporary log level changes.

    Usage:
        with LogContext(logging.DEBUG):
            # Verbose logging here
            logger.debug("Detailed debug info")
        # Back to normal level
    """

    def __init__(self, level: int):
        self.level = level
        self.previous_level: Optional[int] = None

    def __enter__(self) -> "LogContext":
        root = logging.getLogger()
        self.previous_level = root.level
        root.setLevel(self.level)
        return self

    def __exit__(self, *args) -> None:
        if self.previous_level is not None:
            logging.getLogger().setLevel(self.previous_level)
