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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select

from jobtracker.auth import current_user, require_user
from jobtracker.database import get_session
from jobtracker.database.models import Application, ApplicationStatus


router = APIRouter(
    prefix="/applications",
    tags=["Applications (cloud)"],
    dependencies=[require_user()],
)


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
) -> CloudApplicationListResponse:
    """List applications owned by the authenticated Supabase user.

    The ``Depends(current_user)`` both enforces authentication (via the
    router-level dependency) and injects the resolved UUID so this
    handler can scope the query. Postgres RLS policies (see Alembic
    revision ``a8d4ec5fba26``) are a second line of defence: even if
    the ``WHERE user_id = ...`` clause were dropped, the DB would still
    return only rows matching ``auth.uid()``.
    """

    async with get_session() as session:
        stmt = (
            select(Application)
            .where(Application.user_id == user_id)
            .order_by(Application.created_at.desc())
        )
        result = await session.exec(stmt)
        rows = result.all()

    return CloudApplicationListResponse(
        applications=[_serialize(app) for app in rows],
        total=len(rows),
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
