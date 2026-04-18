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

    # Deployment target. "desktop" keeps every existing assumption (SQLite,
    # Keychain, WebSocket router, localhost CORS). "cloud" selects the
    # Vercel-safe code paths (Postgres via DATABASE_URL, encrypted-column
    # credentials, polling, env-driven CORS). Downstream issues wire the
    # cloud paths in one at a time; this flag only gates which app builder
    # is imported.
    deployment: Literal["desktop", "cloud"] = "desktop"

    # -------------------------------------------------------------------------
    # API Server
    # -------------------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_reload: bool = Field(
        default=False,
        description="Auto-reload on code changes (development only).",
    )

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_dir: str = Field(
        default="~/Library/Application Support/JobTracker",
        description="Directory for SQLite database and related files",
    )
    database_name: str = "jobtracker.db"
    database_echo: bool = Field(
        default=False,
        description="Enable verbose SQL statement logging.",
    )

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
    uvicorn_access_log: bool = Field(
        default=False,
        description="Enable Uvicorn per-request access logging.",
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
    ml_model_delivery_strategy: Literal[
        "download_on_first_launch", "bundle_in_app"
    ] = Field(
        default="download_on_first_launch",
        description=(
            "How ML models are delivered for desktop builds. "
            "'download_on_first_launch' keeps app size smaller and downloads models "
            "the first time classification is used."
        ),
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
    analytics_enabled: bool = Field(
        default=False,
        description="Expose analytics endpoints (off by default while de-scoped).",
    )

    # -------------------------------------------------------------------------
    # Keychain
    # -------------------------------------------------------------------------
    keychain_service: str = "jobtracker"

    # -------------------------------------------------------------------------
    # Cloud (Vercel + Supabase). Only consumed when deployment == "cloud".
    # -------------------------------------------------------------------------
    cors_allowed_hosts: list[str] = Field(
        default_factory=list,
        description=(
            "Extra hostnames permitted by CORS in cloud mode. Comma-separated "
            "in the env var, for example "
            "JOBTRACKER_CORS_ALLOWED_HOSTS='jobtracker.app,app.jobtracker.dev'. "
            "Vercel preview URLs (*.vercel.app) are always allowed."
        ),
    )
    supabase_jwt_secret: str | None = Field(
        default=None,
        description="Supabase JWT signing secret; required for cloud auth middleware (C3).",
    )
    secret_encryption_key: str | None = Field(
        default=None,
        description=(
            "Fernet key (urlsafe base64, 32 bytes) used to encrypt user credentials "
            "stored in the cloud `user_credentials` table (C4). Generate with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`."
        ),
    )
    vercel_cron_secret: str | None = Field(
        default=None,
        description=(
            "Shared secret Vercel Cron attaches via `x-vercel-cron-secret` header; "
            "used by `POST /cron/sync` (C7) to reject unauthenticated cron calls."
        ),
    )

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
