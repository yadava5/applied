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
import uuid
from typing import Any

from fastapi import Depends, FastAPI, status
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
    description="Cloud (Vercel + Supabase) deployment of the Applied backend.",
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


class _RLSIdentityScopeMiddleware:
    """Reset the RLS identity ContextVar around every request.

    A pure-ASGI middleware (not ``BaseHTTPMiddleware``) so it awaits the
    downstream app in the *same* context — the auth dependency's
    ``set_current_user_id(...)`` set inside the request stays visible to the
    handler and to ``get_session()``, while this middleware guarantees the
    identity is cleared before and after each request. Combined with the
    transaction-local GUCs in ``jobtracker.database.connection``, one user's
    Supabase identity can never bleed into another request, even when the ASGI
    server or a pooled connection is reused.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        from jobtracker.database.connection import (
            reset_current_user_id,
            set_current_user_id,
        )

        token = set_current_user_id(None)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_user_id(token)


app.add_middleware(_RLSIdentityScopeMiddleware)


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


# =============================================================================
# Auth (Supabase JWT) — issue #20 (C3)
# =============================================================================
#
# Auth-aware routes live *after* the health/root endpoints so the cloud
# app remains probeable without credentials. ``current_user`` and
# ``require_user`` are imported here (not at module top) so a desktop
# build that never sets DEPLOYMENT=cloud can still import main_cloud
# without pulling in the cloud auth code — in practice ``jobtracker.main``
# never imports this module, but the guard keeps the cloud graph thin
# for the subprocess-based import-hygiene test in test_main_cloud.py.

from jobtracker.auth import current_user  # noqa: E402
from jobtracker.cloud.account import router as account_cloud_router  # noqa: E402
from jobtracker.cloud.applications import router as applications_cloud_router  # noqa: E402
from jobtracker.cloud.gmail_oauth import router as gmail_cloud_router  # noqa: E402


class AuthMeResponse(BaseModel):
    """Response shape for ``/auth/me``."""

    user_id: str
    authenticated: bool = True


@app.get(
    "/auth/me",
    response_model=AuthMeResponse,
    status_code=status.HTTP_200_OK,
    summary="Echo authenticated user",
    tags=["Auth"],
)
async def auth_me(user_id: uuid.UUID = Depends(current_user)) -> AuthMeResponse:
    """Return the authenticated Supabase user's UUID.

    Useful for:
    - Web clients to confirm their JWT decodes correctly before
      mutating state.
    - Smoke probes after deploy: a 200 here proves both CORS and
      ``SUPABASE_JWT_SECRET`` are configured correctly on Vercel.
    """

    return AuthMeResponse(user_id=str(user_id))


# Router-level ``require_user()`` is already applied inside
# ``applications_cloud``; we include without extra dependencies so the
# router's own contract (auth required on every handler) is the single
# source of truth.
app.include_router(applications_cloud_router)

# Gmail web OAuth + read/classify (issue C5). Auth is declared per-endpoint
# inside the router (the callback is deliberately public and is bound to the
# user by a signed ``state`` instead). See jobtracker.cloud.gmail_oauth.
app.include_router(gmail_cloud_router)

# Account deletion (DELETE /account) — purges the caller's rows so the web
# "danger zone" no longer orphans data when it removes the Supabase auth user.
# Router declares its own ``require_user()``. See jobtracker.cloud.account.
app.include_router(account_cloud_router)
