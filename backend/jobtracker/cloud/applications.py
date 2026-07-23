"""Cloud-only ``/applications`` router — demonstrates user_id scoping.

This is the minimum-viable scoped endpoint wired in C3 to prove the
``current_user`` + ``user_id`` pipeline works end-to-end. Full CRUD,
linking, and insights endpoints remain in ``jobtracker.api.applications``
for the desktop build; downstream cloud issues (C11 onwards) will port
each one over with the same pattern applied here.

Why a separate package instead of extending ``api/applications.py``?
------------------------------------------------------------------

- The desktop router has no auth and passes ``user_id`` implicitly via
  the local sentinel. Adding a per-endpoint ``Depends(current_user)``
  branch inside the shared router would bifurcate every handler and
  regress the 157 desktop tests.
- The cloud import graph must stay thin. ``api/__init__.py`` eagerly
  imports every desktop router, which drags in ``jobtracker.credentials``
  → ``keyring`` and other Keychain-only deps. Cloud routers must sit
  outside the ``api`` package so they do not trigger that import.
- Keeping cloud handlers in their own package lets the cloud app
  mount them with a router-level ``require_user()`` dependency so no
  individual handler can accidentally skip auth.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import select

from jobtracker.auth import current_user, require_user
from jobtracker.cloud import pipeline
from jobtracker.database import get_session
from jobtracker.database.models import Application, ApplicationStatus

# Placeholder position for a Gmail-derived application when no role could be
# parsed from the mail metadata (bodies are never fetched).
_UNKNOWN_ROLE = "Unknown role"


router = APIRouter(
    prefix="/applications",
    tags=["Applications (cloud)"],
    dependencies=[require_user()],
)

# Pagination bounds for the list endpoint. The default page size is large
# enough that a typical account (tens of applications) still gets its whole
# board in one page — preserving the pre-pagination behaviour — while the
# hard cap keeps a single response bounded for pathological accounts so a
# serverless invocation never has to serialize thousands of rows at once.
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

# How recent an application counts as "this week" for the summary tile. Kept
# in one place so the backend aggregate and the frontend's array-based
# `summarize()` fold agree on the window (7 days).
_THIS_WEEK_WINDOW = timedelta(days=7)


class CloudApplicationCreate(BaseModel):
    """Request body for the cloud POST /applications endpoint."""

    company: str
    position: str
    status: ApplicationStatus = ApplicationStatus.APPLIED
    notes: Optional[str] = None


class CloudApplicationResponse(BaseModel):
    """Minimal response model — matches what downstream C11+ needs."""

    id: int
    user_id: str
    company: str
    position: str
    status: ApplicationStatus
    notes: Optional[str] = None
    created_at: str


class CloudApplicationListResponse(BaseModel):
    """Paginated list of applications owned by the authenticated user."""

    applications: list[CloudApplicationResponse]
    total: int


class ApplicationSummaryResponse(BaseModel):
    """Lightweight pipeline summary — counts only, no application rows.

    This is the O(1)-transfer companion to the O(n) list endpoint. The
    dashboard's stat tiles + funnel need per-status counts, a total, and a
    "filed this week" number — none of which require shipping every row to
    the client. The backend computes them with two index-assisted aggregate
    queries (``GROUP BY status`` and a windowed ``COUNT``) against the
    ``ix_applications_user_id_status`` composite index, so response size and
    DB work stay constant as an account grows.

    ``status_counts`` is keyed by the raw backend status value (``applied``,
    ``interviewing``, ``offered``, ``rejected``, ``accepted``, ``withdrawn``,
    ``ghosted``); only non-zero statuses are included. The frontend folds
    these into its display stages so stage semantics live in exactly one
    place (``lib/dashboard/summary.ts``).
    """

    total: int
    this_week: int
    status_counts: dict[str, int]


async def upsert_applications_for_user(
    session,
    user_id: uuid.UUID,
    rolled: list[pipeline.RolledApplication],
) -> tuple[int, int]:
    """Idempotently persist rolled-up applications for one user.

    For each company (keyed by the normalized ``company_token``) it updates the
    existing row or inserts a new one — scoped strictly to ``user_id`` from the
    verified JWT, never a client-supplied id. Re-running with the same input
    creates no duplicates: the match is ``lower(company) == company_token`` and
    Gmail-created rows store ``company = token.title()`` so they round-trip.

    Status only advances (see ``pipeline.advance_application_status``): a re-sync
    never downgrades a row and never overrides a settled/manual status. Returns
    ``(created, updated)``.
    """

    created = 0
    updated = 0
    for r in rolled:
        existing = (
            await session.exec(
                select(Application)
                .where(
                    Application.user_id == user_id,
                    func.lower(Application.company) == r.company_token,
                )
                .limit(1)
            )
        ).first()

        if existing is not None:
            new_status = ApplicationStatus(
                pipeline.advance_application_status(existing.status.value, r.status)
            )
            changed = False
            if new_status != existing.status:
                existing.status = new_status
                changed = True
            if r.role and (not existing.position or existing.position == _UNKNOWN_ROLE):
                existing.position = r.role
                changed = True
            if r.applied_at and existing.applied_date is None:
                existing.applied_date = r.applied_at.date()
                changed = True
            if changed:
                existing.updated_at = datetime.utcnow()
                session.add(existing)
            updated += 1
        else:
            session.add(
                Application(
                    user_id=user_id,
                    company=r.company_display,
                    position=r.role or _UNKNOWN_ROLE,
                    status=ApplicationStatus(r.status),
                    applied_date=r.applied_at.date() if r.applied_at else None,
                    source="gmail",
                )
            )
            created += 1

    await session.commit()
    return created, updated


def _serialize(app: Application) -> CloudApplicationResponse:
    """Convert an ``Application`` ORM row to the public response shape."""

    return CloudApplicationResponse(
        id=app.id,
        user_id=str(app.user_id),
        company=app.company,
        position=app.position,
        status=app.status,
        notes=app.notes,
        created_at=(
            app.created_at.isoformat() if app.created_at else datetime.utcnow().isoformat()
        ),
    )


@router.get("", response_model=CloudApplicationListResponse)
async def list_applications_cloud(
    user_id: uuid.UUID = Depends(current_user),
    page: int = Query(1, ge=1, description="1-based page number."),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Rows per page (capped so a single response stays bounded).",
    ),
    status: Optional[ApplicationStatus] = Query(
        None, description="Filter to a single application status."
    ),
    company: Optional[str] = Query(
        None, description="Case-insensitive substring match on company."
    ),
    search: Optional[str] = Query(
        None, description="Case-insensitive substring match on company/position/notes."
    ),
) -> CloudApplicationListResponse:
    """List applications owned by the authenticated Supabase user, paginated.

    The ``Depends(current_user)`` both enforces authentication (via the
    router-level dependency) and injects the resolved UUID so this
    handler can scope the query. Postgres RLS policies (see Alembic
    revision ``a8d4ec5fba26``) are a second line of defence: even if
    the ``WHERE user_id = ...`` clause were dropped, the DB would still
    return only rows matching ``auth.uid()``.

    ``total`` is the full count of rows matching the (owner + filter)
    predicate — not the size of the returned page — so the UI can render an
    honest "X of Y" without a second request. Server-side ``LIMIT``/``OFFSET``
    keeps the transferred payload bounded regardless of account size; the
    default page size still fits a typical whole board in one response.
    """

    filters = [Application.user_id == user_id]
    if status is not None:
        filters.append(Application.status == status)
    if company:
        filters.append(Application.company.ilike(f"%{company}%"))
    if search:
        like = f"%{search}%"
        filters.append(
            or_(
                Application.company.ilike(like),
                Application.position.ilike(like),
                Application.notes.ilike(like),
            )
        )

    offset = (page - 1) * page_size

    async with get_session() as session:
        total = (
            await session.exec(
                select(func.count()).select_from(Application).where(*filters)
            )
        ).one()

        stmt = (
            select(Application)
            .where(*filters)
            .order_by(Application.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await session.exec(stmt)).all()

    return CloudApplicationListResponse(
        applications=[_serialize(app) for app in rows],
        total=total,
    )


@router.get("/summary", response_model=ApplicationSummaryResponse)
async def application_summary_cloud(
    user_id: uuid.UUID = Depends(current_user),
) -> ApplicationSummaryResponse:
    """Return counts-only pipeline summary for the authenticated user.

    Powers the dashboard stat tiles + funnel without transferring a single
    application row. Two aggregate queries run against the composite
    ``(user_id, status)`` index:

    - ``GROUP BY status`` → per-status counts (≤7 rows regardless of how many
      applications the user has). ``total`` is their sum.
    - a windowed ``COUNT(*)`` for applications created in the last 7 days.

    Both are O(1) in transfer and index-assisted in the DB, so this endpoint
    stays flat as an account scales from 10 to 10,000 applications — the whole
    reason it exists instead of counting client-side over the full list.
    """

    now = datetime.utcnow()
    week_ago = now - _THIS_WEEK_WINDOW

    async with get_session() as session:
        grouped = (
            await session.exec(
                select(Application.status, func.count())
                .where(Application.user_id == user_id)
                .group_by(Application.status)
            )
        ).all()

        this_week = (
            await session.exec(
                select(func.count())
                .select_from(Application)
                .where(
                    Application.user_id == user_id,
                    Application.created_at >= week_ago,
                    Application.created_at <= now,
                )
            )
        ).one()

    status_counts: dict[str, int] = {}
    total = 0
    for status_value, count in grouped:
        key = status_value.value if hasattr(status_value, "value") else str(status_value)
        status_counts[key] = count
        total += count

    return ApplicationSummaryResponse(
        total=total,
        this_week=this_week,
        status_counts=status_counts,
    )


@router.post("", response_model=CloudApplicationResponse, status_code=201)
async def create_application_cloud(
    data: CloudApplicationCreate,
    user_id: uuid.UUID = Depends(current_user),
) -> CloudApplicationResponse:
    """Create an application scoped to the authenticated user.

    The ``user_id`` column is set from the JWT's ``sub`` claim, not from
    any client-supplied value — there is no way for a client to write a
    row on behalf of another user through this endpoint. The Postgres
    RLS ``WITH CHECK`` clause would reject a mismatched insert as well,
    but checking here first avoids the round-trip on misconfigured
    clients.
    """

    async with get_session() as session:
        app = Application(
            user_id=user_id,
            company=data.company,
            position=data.position,
            status=data.status,
            notes=data.notes,
        )
        session.add(app)
        await session.commit()
        await session.refresh(app)

    return _serialize(app)
