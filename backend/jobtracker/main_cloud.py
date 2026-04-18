"""
Cloud FastAPI Application Entry Point
=====================================

Builds the FastAPI `app` served by Vercel Python serverless functions.

This module is the cloud twin of ``jobtracker.main``. It MUST NOT import
desktop-only modules (``jobtracker.credentials``, ``jobtracker.database``,
any router that transitively imports them) at module top, because those
pull in ``keyring``, ``aiosqlite``, or SQLite-specific startup code that
does not exist on Vercel.

Issue #14 (C1) ships only the shim: a working ``/health`` endpoint, an
env-driven CORS middleware, and an app object importable under
``JOBTRACKER_DEPLOYMENT=cloud``. Later issues (C2 Postgres, C3 Auth,
C4 credentials, C5 Gmail web OAuth, C6 cloud classifier, C7 cron)
progressively mount cloud-safe routers onto this app.

Usage (Vercel):
    The repo-root ``api/index.py`` does ``from jobtracker.main_cloud import app``
    and the Vercel Python runtime serves ``app`` via its built-in ASGI adapter.

Usage (local smoke):
    JOBTRACKER_DEPLOYMENT=cloud uvicorn jobtracker.main_cloud:app --port 8001
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from jobtracker.config import settings
from jobtracker.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def _build_cors_origin_regex() -> str:
    """Build the CORS ``allow_origin_regex`` from config.

    Always allows ``localhost``/``127.0.0.1`` (for local ``vercel dev``) and
    any ``*.vercel.app`` preview URL. Additional hosts come from
    ``settings.cors_allowed_hosts``.
    """

    parts: list[str] = [
        r"localhost(:\d+)?",
        r"127\.0\.0\.1(:\d+)?",
        r"[a-zA-Z0-9-]+\.vercel\.app",
    ]
    parts.extend(re.escape(host) for host in settings.cors_allowed_hosts if host)
    return rf"^https?://({'|'.join(parts)})$"


app = FastAPI(
    title=f"{settings.app_name} (cloud)",
    description="Cloud (Vercel + Supabase) deployment of the JobTracker backend.",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=_build_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    """Cloud health response. Intentionally minimal until C2/C3/C4 land."""

    status: str
    version: str
    deployment: str
    environment: str


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check (cloud)",
    tags=["System"],
)
async def health_check() -> HealthResponse:
    """Return a minimal health response.

    No database hit, no credential probe. Later issues will extend this to
    report Postgres connectivity (C2), Supabase auth (C3), and classifier
    availability (C6) once those subsystems are wired into the cloud app.
    """

    return HealthResponse(
        status="ok",
        version=settings.app_version,
        deployment=settings.deployment,
        environment=settings.environment,
    )


@app.get(
    "/",
    summary="Cloud API Root",
    tags=["System"],
)
async def root() -> dict[str, Any]:
    """Root endpoint with API information for the cloud deployment."""

    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "deployment": "cloud",
        "docs": "/docs",
        "health": "/health",
    }
