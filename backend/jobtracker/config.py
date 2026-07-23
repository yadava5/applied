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
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    database_url_override: str | None = Field(
        default=None,
        description=(
            "Explicit async DB URL (e.g. postgresql+asyncpg://... for Supabase "
            "or sqlite+aiosqlite:///path.db). When set, this overrides the "
            "computed SQLite URL used by the application engine. Leave unset "
            "on desktop builds to keep the local SQLite database."
        ),
    )
    direct_database_url: str | None = Field(
        default=None,
        description=(
            "Non-pooler database URL used by Alembic migrations only. "
            "Required on Supabase because PgBouncer (transaction pooling) "
            "does not support the prepared-statement flow Alembic emits "
            "during DDL. Not consumed by the runtime app engine."
        ),
    )

    @computed_field  # type: ignore[misc]
    @property
    def database_path(self) -> Path:
        """Full path to the SQLite database file."""
        return Path(self.database_dir).expanduser() / self.database_name

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        """SQLAlchemy async database URL.

        Resolution order:
        1. ``database_url_override`` - explicit opt-in for Postgres/Supabase.
        2. Test environment -> isolated in-memory SQLite.
        3. Desktop default -> on-disk SQLite at ``database_path``.
        """

        if self.database_url_override:
            return self.database_url_override

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
    cors_allowed_hosts: Annotated[list[str], NoDecode] = Field(
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
    supabase_jwks_url: str | None = Field(
        default=None,
        description=(
            "JWKS endpoint for Supabase's asymmetric JWT signing keys "
            "(new projects sign user tokens with ES256), e.g. "
            "https://<ref>.supabase.co/auth/v1/.well-known/jwks.json. "
            "When set, ES256 tokens verify against these keys; HS256 "
            "tokens still verify against supabase_jwt_secret."
        ),
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

    # -------------------------------------------------------------------------
    # Gmail Web OAuth (cloud, C5). Only consumed when deployment == "cloud".
    #
    # These configure the *web* authorization-code flow used by the deployed
    # app — distinct from the desktop `run_local_server` flow. The client
    # secret is a Google-issued credential: it is provided by the operator
    # via the Vercel env, is NEVER committed to the repo, NEVER returned to
    # the browser, and NEVER logged.
    # -------------------------------------------------------------------------
    google_oauth_client_id: str | None = Field(
        default=None,
        description=(
            "OAuth 2.0 client_id for the JobTracker *Web application* client "
            "(Google Cloud Console → Credentials). Public by design; pairs with "
            "google_oauth_client_secret. Env: JOBTRACKER_GOOGLE_OAUTH_CLIENT_ID."
        ),
    )
    google_oauth_client_secret: str | None = Field(
        default=None,
        description=(
            "OAuth 2.0 client_secret for the Web application client. Operator-"
            "supplied secret — set ONLY in the backend env (Vercel), never in the "
            "repo, chat, or the browser. Env: JOBTRACKER_GOOGLE_OAUTH_CLIENT_SECRET."
        ),
    )
    gmail_oauth_redirect_uri: str | None = Field(
        default=None,
        description=(
            "Absolute HTTPS callback URL registered as an Authorized redirect URI "
            "on the Web OAuth client, e.g. "
            "https://<api-host>/auth/gmail/callback. Google redirects the browser "
            "here after consent; must match the console entry byte-for-byte. "
            "Env: JOBTRACKER_GMAIL_OAUTH_REDIRECT_URI."
        ),
    )
    web_app_url: str | None = Field(
        default=None,
        description=(
            "Absolute base URL of the web app the callback bounces the user back "
            "to after a connect/disconnect, e.g. https://jobtracker-web-five."
            "vercel.app. Used as a fixed, allow-listed redirect target so the "
            "callback can never be turned into an open redirect. "
            "Env: JOBTRACKER_WEB_APP_URL."
        ),
    )
    gmail_fetch_max_results: int = Field(
        default=25,
        description=(
            "Upper bound on messages fetched per cloud Gmail read. Kept small so a "
            "single serverless invocation stays within the Vercel 60 s / memory "
            "budget; the desktop app fetches far more."
        ),
    )
    gmail_oauth_state_ttl_seconds: int = Field(
        default=600,
        description=(
            "Lifetime of the signed OAuth `state` token that binds the Google "
            "callback to the authenticated user. Short by design (10 min) to "
            "limit the CSRF/replay window."
        ),
    )
    gmail_inbox_cache_ttl_seconds: int = Field(
        default=60,
        description=(
            "Short TTL (seconds) for the per-user in-process cache of the "
            "`GET /gmail/inbox` classify result. A repeat load within the "
            "window is served from memory instead of re-hitting Gmail and "
            "re-running the classifier, which is the expensive part of that "
            "endpoint. Scoped strictly per user_id — never shared across "
            "users — so caching never weakens auth or leaks mail. Set to 0 to "
            "disable (always fetch + classify fresh)."
        ),
    )
    gmail_fetch_hard_cap: int = Field(
        default=2000,
        description=(
            "Absolute upper bound on the TOTAL number of messages a single "
            "high-volume inbox mine may request across all pages. The web UI "
            "offers 100/200/500/1000/2000; this caps whatever a caller asks "
            "for so a hand-crafted request cannot ask Gmail for an unbounded "
            "scan. Env: JOBTRACKER_GMAIL_FETCH_HARD_CAP."
        ),
    )
    gmail_fetch_page_size: int = Field(
        default=500,
        description=(
            "Messages fetched + classified in ONE serverless invocation of "
            "`GET /gmail/inbox`. The endpoint is server-paginated: it returns "
            "at most this many verdicts plus a `next_page_token`, and the web "
            "client loops until it reaches the user's chosen count. Kept at "
            "the Gmail `messages.list` page ceiling (500) so one list call "
            "feeds one page, and small enough that a page's batched metadata "
            "fetch + rules classification stays well inside the Vercel 60 s "
            "function budget. Clamped to [1, 500]. Env: "
            "JOBTRACKER_GMAIL_FETCH_PAGE_SIZE."
        ),
    )
    gmail_batch_size: int = Field(
        default=100,
        description=(
            "Sub-requests per Gmail batch HTTP request when fetching message "
            "metadata (Subject/From/Date + snippet). Gmail caps a batch at "
            "100. A 100-message metadata batch costs ~500 quota units, so the "
            "batch pace (below) keeps the per-user ~250 units/sec quota "
            "respected. Env: JOBTRACKER_GMAIL_BATCH_SIZE."
        ),
    )
    gmail_batch_pause_seconds: float = Field(
        default=0.4,
        description=(
            "Seconds to sleep between successive Gmail metadata batches to "
            "stay under the per-user quota (~250 units/sec; a full 100-message "
            "batch ≈ 500 units). Set to 0 to disable pacing. Env: "
            "JOBTRACKER_GMAIL_BATCH_PAUSE_SECONDS."
        ),
    )
    gmail_followup_stale_days: int = Field(
        default=21,
        description=(
            "Age (days) after which an `applied` email with no later "
            "interview/assessment/offer/rejection from the same company is "
            "flagged 'No response — consider following up'. The ghosting "
            "differentiator. Env: JOBTRACKER_GMAIL_FOLLOWUP_STALE_DAYS."
        ),
    )

    # Every setting the Gmail web OAuth flow needs before it can offer a
    # connect button. Each maps to an env var ``JOBTRACKER_<UPPER>``.
    # ``secret_encryption_key`` is required twice over: to encrypt the stored
    # refresh token (C4) and to sign the OAuth ``state`` token — so it belongs
    # here even though it is not a "Google" value.
    _GMAIL_OAUTH_REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "google_oauth_client_id",
        "google_oauth_client_secret",
        "gmail_oauth_redirect_uri",
        "web_app_url",
        "secret_encryption_key",
    )

    @property
    def gmail_oauth_missing_fields(self) -> list[str]:
        """Names (never values) of the required Gmail-OAuth settings still unset.

        Turns the opaque ``gmail_oauth_configured is False`` into an actionable
        list: an operator can map each name to its ``JOBTRACKER_<UPPER>`` env
        var and see exactly what to set. Only field *names* are exposed here —
        secret values are never read out — so this is safe to log or surface in
        a 503 detail. An empty list means the flow is fully configured.
        """

        return [
            name
            for name in self._GMAIL_OAUTH_REQUIRED_FIELDS
            if not getattr(self, name)
        ]

    @computed_field  # type: ignore[misc]
    @property
    def gmail_oauth_configured(self) -> bool:
        """True when every value the Gmail web OAuth flow needs is present.

        Routers use this to return an honest ``503 not configured`` (instead
        of a 500) while the operator has not yet set the Google client
        credentials + redirect URIs + encryption key in the backend env.
        Backed by :attr:`gmail_oauth_missing_fields` so the "is it configured?"
        boolean and the "what's missing?" diagnostic can never drift apart.
        """

        return not self.gmail_oauth_missing_fields

    @field_validator("cors_allowed_hosts", mode="before")
    @classmethod
    def _split_cors_hosts(cls, value: Any) -> Any:
        """Accept a comma-separated env var string for cors_allowed_hosts.

        Vercel and most shells can only pass strings, so
        `JOBTRACKER_CORS_ALLOWED_HOSTS='jobtracker.app,app.jobtracker.dev'`
        should Just Work. A list/tuple is still accepted for programmatic use.
        """

        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
