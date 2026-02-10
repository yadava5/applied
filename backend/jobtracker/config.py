"""
Configuration Module
====================

Application settings and configuration management using pydantic-settings.

All settings can be overridden via environment variables with the
JOBTRACKER_ prefix. For example:
    JOBTRACKER_API_PORT=9000
    JOBTRACKER_LOG_LEVEL=DEBUG

Settings are loaded from:
1. Default values defined in this file
2. .env file in the backend directory (if exists)
3. Environment variables (highest priority)

Usage:
------
    from jobtracker.config import settings

    print(settings.api_host)  # "127.0.0.1"
    print(settings.database_path)  # ~/Library/Application Support/JobTracker/jobtracker.db
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    All settings can be overridden via environment variables
    prefixed with JOBTRACKER_.
    """

    model_config = SettingsConfigDict(
        env_prefix="JOBTRACKER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    app_name: str = "JobTracker"
    app_version: str = "0.1.0"
    # Environment:
    # - development: normal local runs (uses on-disk SQLite DB)
    # - production: same as development for now, but reserved for future tuning
    # - test: in-memory SQLite DB for pytest (never touches real data)
    environment: Literal["development", "production", "test"] = "development"

    # -------------------------------------------------------------------------
    # API Server
    # -------------------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_reload: bool = Field(default=True, description="Auto-reload on code changes")

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_dir: str = Field(
        default="~/Library/Application Support/JobTracker",
        description="Directory for SQLite database and related files",
    )
    database_name: str = "jobtracker.db"

    @computed_field  # type: ignore[misc]
    @property
    def database_path(self) -> Path:
        """Full path to the SQLite database file."""
        return Path(self.database_dir).expanduser() / self.database_name

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        """SQLAlchemy async database URL."""
        # During tests we want a completely isolated, in-memory database that
        # does not touch the real on-disk JobTracker DB.
        if self.environment == "test":
            return "sqlite+aiosqlite:///:memory:"

        return f"sqlite+aiosqlite:///{self.database_path}"

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_dir: str = Field(
        default="~/Library/Logs/JobTracker",
        description="Directory for log files",
    )
    log_format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    log_date_format: str = "%Y-%m-%d %H:%M:%S"

    @computed_field  # type: ignore[misc]
    @property
    def log_path(self) -> Path:
        """Full path to the log directory."""
        return Path(self.log_dir).expanduser()

    # -------------------------------------------------------------------------
    # Email Sync
    # -------------------------------------------------------------------------
    sync_interval_seconds: int = Field(
        default=900,  # 15 minutes
        description="Interval between automatic email syncs",
    )
    sync_batch_size: int = Field(
        default=100,
        description="Number of emails to fetch per batch",
    )
    sync_max_age_days: int = Field(
        default=90,
        description="Maximum age of emails to sync on first run",
    )

    # -------------------------------------------------------------------------
    # Gmail API
    # -------------------------------------------------------------------------
    gmail_scopes: list[str] = Field(
        default=["https://www.googleapis.com/auth/gmail.readonly"],
        description="OAuth2 scopes for Gmail API access",
    )
    gmail_credentials_file: str = Field(
        default="credentials/gmail_credentials.json",
        description="Path to Gmail OAuth client credentials (relative to backend/)",
    )

    # -------------------------------------------------------------------------
    # iCloud Mail
    # -------------------------------------------------------------------------
    icloud_imap_host: str = "imap.mail.me.com"
    icloud_imap_port: int = 993

    # -------------------------------------------------------------------------
    # ML Classifier
    # -------------------------------------------------------------------------
    embedding_model: str = Field(
        default="intfloat/e5-small-v2",
        description="Sentence embedding model from HuggingFace",
    )
    embedding_similarity_threshold: float = Field(
        default=0.85,
        description="Minimum cosine similarity for embedding-based classification",
    )
    setfit_confidence_threshold: float = Field(
        default=0.70,
        description="Minimum confidence for SetFit classification",
    )
    setfit_retrain_threshold: int = Field(
        default=5,
        description="Number of new corrections before triggering SetFit retrain",
    )
    setfit_min_examples_per_class: int = Field(
        default=5,
        description="Minimum examples per class required for SetFit training",
    )
    lite_mode: bool = Field(
        default=False,
        description="Disable SetFit for 8GB RAM machines (rules + embeddings only)",
    )

    # -------------------------------------------------------------------------
    # Keychain
    # -------------------------------------------------------------------------
    keychain_service: str = "jobtracker"

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.

    Settings are loaded once and cached for performance.
    Use this function to access settings throughout the app.

    Returns:
        Settings: Application settings instance.
    """
    return Settings()


# Convenience alias for importing
settings = get_settings()
