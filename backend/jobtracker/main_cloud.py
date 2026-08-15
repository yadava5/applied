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
import os
import re
import uuid
from typing import Any

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from jobtracker.config import (
    configured_web_app_host,
    settings,
    trusted_web_hosts,
    web_app_host_is_trusted,
)
from jobtracker.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def _build_cors_origin_regex() -> str:
    r"""Build the CORS ``allow_origin_regex`` from config.

    Allows ``localhost``/``127.0.0.1`` (for local ``vercel dev``), THIS
    deployment's own Vercel hostnames, and any extra hosts from
    ``settings.cors_allowed_hosts``.

    WHY THERE IS NO ``*.vercel.app`` WILDCARD ANY MORE
    ---------------------------------------------------
    This function used to include ``[a-zA-Z0-9-]+\.vercel\.app`` so that
    preview deployments would work. Combined with ``allow_credentials=True``
    below, that made the allowlist effectively open: anyone can deploy
    ``anything.vercel.app`` for free, and the middleware would echo their
    origin back with credentials permitted. SECURITY_AUDIT.md finding 2
    (2026-07-22) recorded it as MEDIUM and confirmed it empirically —
    ``evil-attacker-12345.vercel.app`` was echoed; ``evil.example.com`` was
    correctly refused.

    Impact was limited rather than critical because this API authenticates
    with ``Authorization: Bearer <supabase-jwt>``, not cookies, so a hostile
    origin has no ambient credential to ride. That is a reason it was not an
    incident, not a reason to keep the hole.

    THE FIX comes from the sibling project. Cadence solves the same problem
    in ``lib/middleware/cors.ts`` by listing the deployment's OWN hostnames
    rather than a pattern:

        origin: [`https://${process.env.VERCEL_URL}`,
                 `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`,
                 process.env.FRONTEND_URL].filter(Boolean)

    Vercel injects both variables into every deployment, including previews,
    where ``VERCEL_URL`` is that preview's own hostname. So previews keep
    working and a third party's ``*.vercel.app`` does not match. Same
    behaviour, no wildcard.

    WHERE THE HOSTS COME FROM (changed 2026-08-14). The list used to be built
    here, which made this function a second, private answer to "which host is
    the web app?" — the Gmail OAuth callback held the other one, and they
    silently disagreed in production for weeks. Both now read
    ``config.trusted_web_hosts``; see that function for the measurement.
    The behaviour of this regex is unchanged, and
    ``tests/test_cors_origin_regex.py`` is what says so.
    """

    parts = [
        # Matched with an optional port so `vercel dev` on any port works;
        # the remote hosts are matched exactly.
        rf"{re.escape(host)}(:\d+)?" if host in ("localhost", "127.0.0.1") else re.escape(host)
        for host in trusted_web_hosts()
    ]
    return rf"^https?://({'|'.join(parts)})$"


# Interactive docs are OPT-IN. Until 2026-08-12 the three URLs below were
# passed unconditionally, so the production API published its complete
# interactive surface -- every path, every schema, a live "Try it out" -- to
# anyone who loaded https://<api-host>/docs.
#
# WHY THE GATE IS `enable_docs` AND NOT `environment`
# ---------------------------------------------------
# The reflexive fix is ``if settings.environment != "production"``. It would
# have changed nothing. Nothing sets JOBTRACKER_ENVIRONMENT on Vercel, so the
# deployed API reports ``"development"`` -- the field's default -- and that
# condition is false in production. A gate whose condition is never true where
# it matters is not a gate.
#
# ``enable_docs`` defaults to False instead, which puts the safe state in the
# default rather than in the configuration. The property that holds: a
# deployment carrying no environment configuration at all serves no docs.
# Passing None (rather than a path) is what makes that a 404 -- FastAPI does
# not register the route at all, so there is nothing to probe. ``app.openapi()``
# still works in-process, which is what scripts/generate_api_schema.sh uses to
# build the web client's typed bindings.
_docs_enabled = settings.enable_docs


def _build_commit_sha() -> str | None:
    """The git commit this deployment was built from, or None if unknowable.

    WHY /health NEEDS THIS
    ----------------------
    On 2026-08-12 production ran a web app from one commit against an API from
    a commit three hours older, and nothing anywhere said so. Establishing it
    meant reading Vercel's deployment records and running
    ``git merge-base --is-ancestor`` per project. The API could not help:

        {"status":"ok","version":"0.1.0","deployment":"cloud", ...}

    ``version`` is ``Settings.app_version``, a constant in the source. It has
    never changed and it cannot answer "what code is actually running?". A SHA
    can, with one curl, by anyone -- including after a Vercel CLI deploy, which
    creates no GitHub deployment record at all and so leaves the platform's own
    view of "production" pointing at a stale commit indefinitely.

    HONESTY
    -------
    Reported verbatim from Vercel's own ``VERCEL_GIT_COMMIT_SHA`` and never
    synthesised. No git subprocess, no build-time stamp, no "unknown" string
    dressed up as a value: when the variable is absent -- a local run, or a
    deployment where the project has "Automatically expose System Environment
    Variables" turned off -- this returns None and /health omits the claim, the
    same rule the ``environment`` field follows.

    That the variable does reach the running function is not an assumption:
    ``_build_cors_origin_regex`` above reads ``VERCEL_URL`` from the same
    system-variable mechanism at import time, and CORS works in production.

    Read at import, like the CORS hosts: the value cannot change during a
    process lifetime, and both states are covered by subprocess probes in
    tests/test_api_docs_are_opt_in.py rather than by reloading this module,
    which corrupts a pytest session (see that file).
    """

    return os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip() or None


_COMMIT_SHA = _build_commit_sha()

app = FastAPI(
    title=f"{settings.app_name} (cloud)",
    description="Cloud (Vercel + Supabase) deployment of the Applied backend.",
    version=settings.app_version,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
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


class _ServerTimingMiddleware:
    """Report where each request's time went — the instrument issue #203 named.

    Production measured ``GET /api/applications/{id}`` at 850 ms for 568 bytes
    with ~500 ms unattributable from outside the process. This middleware makes
    the split visible on every response, for free, via the standard
    ``Server-Timing`` header (browser devtools render it; ``curl -sI`` shows
    it; Vercel's function logs keep the slow-request lines):

        Server-Timing: app;dur=712.4, db_connect;dur=431.9;desc="n=2",
                       db_query;dur=95.1;desc="n=7"

    - ``app``       — the whole request inside the ASGI app (excludes platform
                      routing/edge, which #203 measured separately at ~130 ms).
    - ``db_connect``— connection establishment: the NullPool tax. ``n`` is the
                      count; two connects on a read endpoint was the bug.
    - ``db_query``  — statement round trips, INCLUDING the transaction-GUC
                      ``set_config`` — that is real request cost, not overhead
                      to hide.

    Pure ASGI (same reasoning as ``_RLSIdentityScopeMiddleware``): the phase
    accumulator is a ContextVar and must be set in the same context the
    handler runs in. Durations only, no identifiers, so the header leaks
    nothing a caller does not already know. Requests slower than
    ``_SLOW_REQUEST_MS`` additionally log one INFO line so production keeps a
    queryable record without per-request log spam.
    """

    _SLOW_REQUEST_MS = 500.0

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        from time import perf_counter

        from jobtracker.database.connection import (
            begin_db_phase_capture,
            end_db_phase_capture,
            read_db_phases,
        )

        token = begin_db_phase_capture()
        started = perf_counter()

        async def send_with_timing(message: Any) -> None:
            if message.get("type") == "http.response.start":
                total_ms = (perf_counter() - started) * 1000.0
                phases = read_db_phases() or {}
                connect_ms = phases.get("connect_ms", 0.0)
                connects = int(phases.get("connects", 0))
                query_ms = phases.get("query_ms", 0.0)
                queries = int(phases.get("queries", 0))
                header = (
                    f"app;dur={total_ms:.1f}, "
                    f'db_connect;dur={connect_ms:.1f};desc="n={connects}", '
                    f'db_query;dur={query_ms:.1f};desc="n={queries}"'
                )
                headers = list(message.get("headers", []))
                headers.append((b"server-timing", header.encode("latin-1")))
                message = {**message, "headers": headers}
                if total_ms >= self._SLOW_REQUEST_MS:
                    logger.info(
                        "slow request: %s %s -> %s in %.0f ms "
                        "(db_connect %.0f ms x%d, db_query %.0f ms x%d)",
                        scope.get("method", "?"),
                        scope.get("path", "?"),
                        message.get("status", 0),
                        total_ms,
                        connect_ms,
                        connects,
                        query_ms,
                        queries,
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            end_db_phase_capture(token)


# Outermost of the pure-ASGI middlewares (added last), so `app;dur=` covers
# the RLS scope reset and CORS work as well as the handler itself.
app.add_middleware(_ServerTimingMiddleware)


class HealthResponse(BaseModel):
    """Cloud health response. Intentionally minimal until C2/C3/C4 land."""

    status: str
    version: str
    deployment: str
    environment: str | None = Field(
        default=None,
        description=(
            "The configured environment, or null when the deployment does not "
            "declare one. Null is not 'development' -- it means nobody said. "
            "This endpoint used to print the field's default, which read as an "
            "assertion that production was a development deployment."
        ),
    )
    commit: str | None = Field(
        default=None,
        description=(
            "The git commit SHA this deployment was built from, taken verbatim "
            "from VERCEL_GIT_COMMIT_SHA, or null when the platform does not "
            "supply one. Answers 'what code is actually running?', which "
            "`version` cannot: that is a constant in the source."
        ),
    )
    web_app_host: str | None = Field(
        default=None,
        description=(
            "The hostname of the Gmail OAuth callback's FALLBACK return "
            "destination, read from JOBTRACKER_WEB_APP_URL, or null when it is "
            "unset. Since #333 the normal destination is the origin the caller "
            "started from, validated at /auth/gmail/authorize and carried in "
            "the signed state, so this value is consulted only for a callback "
            "that arrives without one. Still reported, because a stale value "
            "is otherwise INVISIBLE until somebody completes a connect flow -- "
            "which is how the real one survived: it named a pre-rename alias "
            "for 26 days, the alias served the app perfectly, and the only "
            "symptom was that every returning user arrived on a hostname their "
            "session cookie was not issued for. Compare it against "
            "`web_app_host_trusted` below, never by eye."
        ),
    )
    web_app_host_trusted: bool = Field(
        default=False,
        description=(
            "Whether `web_app_host` is one of the hostnames this deployment "
            "serves the app on (`config.trusted_web_hosts`). NOT a verdict on "
            "the connect flow as a whole any more: a caller that sends its own "
            "origin never reaches the fallback, so FALSE here with the origin "
            "path working is a fine state and TRUE is not a guarantee. What "
            "FALSE does mean is that a callback which arrives WITHOUT a "
            "carried origin -- a state minted by an older web deploy, or one "
            "too forged to read -- will 503 rather than strand the user "
            "signed out. Read it as 'is the fallback usable?'. "
            "WHY THIS IS NOT A 503 ON /health. The API also serves the board, "
            "search, export and the scheduled sync, none of which touch this "
            "value; failing the whole health check -- or refusing to boot -- "
            "would turn one wrong redirect target into a total outage, and "
            "into a deploy that cannot roll forward. So the endpoint stays 200 "
            "and states the fact, and the failure is loud at the one place it "
            "actually matters."
        ),
    )


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
        # Report the environment only when one was actually configured.
        # ``settings.environment`` always holds a string; until now this
        # endpoint printed it unconditionally, so production told every caller
        # it was a "development" deployment on the strength of a default
        # nobody had set. Null is the honest answer to "which environment?"
        # when the deployment has never been told.
        environment=(
            settings.environment if settings.environment_is_configured else None
        ),
        # Null when the platform did not supply one. Never a placeholder --
        # a made-up SHA is worse than no SHA, because it looks answerable.
        commit=_COMMIT_SHA,
        # The host only -- never the whole URL, and never the trusted list.
        # A hostname this deployment publishes anyway is not a secret; the
        # allow-list is a different question and is not this endpoint's to
        # answer.
        web_app_host=configured_web_app_host(),
        web_app_host_trusted=web_app_host_is_trusted(),
    )


class SchemaVersionResponse(BaseModel):
    """What this code expects of the schema, and what the database actually is."""

    expected: str = Field(
        description=(
            "The Alembic revision this deployment's code was written against, "
            "baked in at build time."
        )
    )
    applied: str | None = Field(
        default=None,
        description=(
            "The revision stamped in the database's alembic_version table. "
            "Null means the question could not be answered — no table, an empty "
            "table, or a failed query — never 'behind'. A '+'-joined value means "
            "the table holds several rows, i.e. the migration graph forked."
        )
    )
    ok: bool = Field(
        description=(
            "True only when the two agree. False is the signal that a revision "
            "was merged without being applied to this database."
        )
    )


@app.get(
    "/health/schema",
    response_model=SchemaVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Schema Version Check (cloud)",
    tags=["System"],
)
async def schema_version_check() -> SchemaVersionResponse:
    """Report whether the database schema matches the code's expectation.

    **Why this is not folded into ``/health``.** That probe is deliberately
    credential-free and does no database work, and Supabase's free tier pauses a
    project after seven days idle — so a database round-trip there would turn a
    sleeping database into a red liveness probe and, worse, train the reader to
    ignore it. Keeping the schema question on its own path means ``/health``
    still answers "is the function up?" and this answers "does the database
    agree with it?", which are different questions with different fixes.

    **Always 200.** The status code reports whether the *check ran*, not what it
    found; the verdict is in ``ok``. A 503 here would make an ordinary,
    self-healing state (the seconds between a merge and its migration) look like
    an outage to every uptime monitor pointed at the deployment.

    The read is one row from ``alembic_version``, which carries no RLS and is
    granted to the runtime role directly.
    """

    from jobtracker.database.connection import get_session
    from jobtracker.database.schema_version import (
        EXPECTED_REVISION,
        read_applied_revision,
    )

    async with get_session() as session:
        applied = await read_applied_revision(session)

    if applied != EXPECTED_REVISION:
        logger.warning(
            "Schema version mismatch: code expects %s, database reports %s",
            EXPECTED_REVISION,
            applied,
        )

    return SchemaVersionResponse(
        expected=EXPECTED_REVISION,
        applied=applied,
        ok=applied == EXPECTED_REVISION,
    )


@app.get(
    "/",
    summary="Cloud API Root",
    tags=["System"],
)
async def root() -> dict[str, Any]:
    """Root endpoint with API information for the cloud deployment."""

    payload: dict[str, Any] = {
        "name": settings.app_name,
        "version": settings.app_version,
        "deployment": "cloud",
    }
    # Advertise the docs only when they are actually mounted -- and read that
    # off the app object rather than re-reading ``settings.enable_docs``, so
    # "advertised if and only if served" is structural instead of two
    # independent reads that happen to agree. Before this, the root of the
    # production API handed out "/docs" as a directions sign to a page that
    # should never have existed; the failure mode to avoid now is the mirror
    # image, a sign pointing at a 404.
    if app.docs_url:
        payload["docs"] = app.docs_url
    payload["health"] = "/health"
    return payload


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
from jobtracker.cloud.cron import router as cron_cloud_router  # noqa: E402
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

# Scheduled sync (GET/POST /cron/sync) — issue #23 (C7). The ONE router here
# with no ``require_user()``, deliberately: Vercel Cron carries no JWT. It is
# gated instead on a shared secret compared in constant time, and every unit of
# work inside runs under an explicit per-user RLS identity, so "no caller
# identity" never becomes "no scoping". See jobtracker.cloud.cron.
app.include_router(cron_cloud_router)
