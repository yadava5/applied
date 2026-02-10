"""
FastAPI Application Entry Point
===============================

Main FastAPI application for the JobTracker backend.

This module creates and configures the FastAPI app with:
- Lifespan management (startup/shutdown handlers)
- CORS configuration for localhost access
- API routers for all endpoints
- Health check endpoint

Running the server:
-------------------
    # Development (with auto-reload)
    uvicorn jobtracker.main:app --host 127.0.0.1 --port 8000 --reload

    # Production
    uvicorn jobtracker.main:app --host 127.0.0.1 --port 8000

    # Or use the CLI entry point
    jobtracker

API Documentation:
------------------
    http://127.0.0.1:8000/docs    # Swagger UI
    http://127.0.0.1:8000/redoc   # ReDoc
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jobtracker.config import settings
from jobtracker.database import close_db, get_db_stats, init_db
from jobtracker.logging import setup_logging

# Set up logging before anything else
setup_logging()

logger = logging.getLogger(__name__)


# =============================================================================
# Lifespan Management
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events:
    - Startup: Initialize database, log startup info
    - Shutdown: Close database connections cleanly
    """
    # === STARTUP ===
    logger.info("=" * 60)
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"API: http://{settings.api_host}:{settings.api_port}")
    logger.info("=" * 60)

    # Ensure required directories exist
    settings.ensure_directories()

    # Initialize database (creates tables if needed)
    await init_db()

    logger.info("Application startup complete")

    yield  # Application runs here

    # === SHUTDOWN ===
    logger.info("Shutting down application...")

    # Close database connections
    await close_db()

    logger.info("Application shutdown complete")


# =============================================================================
# FastAPI Application
# =============================================================================


app = FastAPI(
    title=settings.app_name,
    description="Email-powered job application tracker with ML classification",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# =============================================================================
# CORS Middleware
# =============================================================================

# Allow localhost access for SwiftUI app
# Using allow_origin_regex for flexible localhost port matching
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",  # For future Tauri app
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health Check Endpoint
# =============================================================================


class ClassifierStatus(BaseModel):
    """Classifier layer status."""

    active_layers: list[str]
    setfit_trained: bool


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    version: str
    environment: str
    db_connected: bool
    db_stats: dict[str, Any] | None
    gmail_connected: bool
    icloud_connected: bool
    last_sync: datetime | None
    classifier_status: ClassifierStatus


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    description="Check if the backend is running and connected to required services.",
    tags=["System"],
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns the status of all backend components:
    - Database connection and stats
    - Gmail/iCloud connection status
    - Last sync timestamp
    - ML classifier status

    Used by:
    - SwiftUI app to verify backend is running
    - Monitoring and alerting systems
    """
    # Check database connection
    db_connected = False
    db_stats = None
    try:
        db_stats = await get_db_stats()
        db_connected = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")

    # TODO: Check Gmail connection (Phase 2)
    gmail_connected = False

    # TODO: Check iCloud connection (Phase 2)
    icloud_connected = False

    # TODO: Get last sync time (Phase 2)
    last_sync = None

    # TODO: Get classifier status (Phase 3)
    classifier_status = ClassifierStatus(
        active_layers=["rules"],  # Rules always available
        setfit_trained=False,
    )

    return HealthResponse(
        status="ok" if db_connected else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        db_connected=db_connected,
        db_stats=db_stats,
        gmail_connected=gmail_connected,
        icloud_connected=icloud_connected,
        last_sync=last_sync,
        classifier_status=classifier_status,
    )


# =============================================================================
# Root Endpoint
# =============================================================================


@app.get(
    "/",
    summary="API Root",
    description="Welcome message and API information.",
    tags=["System"],
)
async def root() -> dict[str, str]:
    """
    Root endpoint with API information.

    Provides basic info and links to documentation.
    """
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }


# =============================================================================
# Error Handlers
# =============================================================================


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for unhandled errors.

    Logs the error and returns a generic 500 response.
    Prevents stack traces from leaking to clients.
    """
    logger.exception(f"Unhandled exception: {exc}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred. Please try again.",
        },
    )


# =============================================================================
# CLI Entry Point
# =============================================================================


def run() -> None:
    """
    CLI entry point for running the server.

    Usage:
        jobtracker  # After pip install -e .
    """
    import uvicorn

    uvicorn.run(
        "jobtracker.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
