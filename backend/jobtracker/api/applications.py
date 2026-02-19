"""
Applications API
================

CRUD endpoints for job applications, plus auto-linking functionality.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import func, select

from jobtracker.classifier import get_classifier
from jobtracker.database import get_session
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
)
from jobtracker.services.application_insights import (
    get_follow_up_reminders,
    mark_ghosted_applications,
)
from jobtracker.tracking import get_application_linker

router = APIRouter(prefix="/applications", tags=["Applications"])
logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================


class ApplicationCreate(BaseModel):
    """Request body for creating an application."""

    company: str
    position: str
    status: ApplicationStatus = ApplicationStatus.APPLIED
    applied_date: Optional[str] = None  # ISO date string
    source: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    """Request body for updating an application."""

    company: Optional[str] = None
    position: Optional[str] = None
    status: Optional[ApplicationStatus] = None
    applied_date: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None


class ApplicationResponse(BaseModel):
    """Response model for a single application."""

    id: int
    company: str
    position: str
    status: ApplicationStatus
    applied_date: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    email_count: int = 0


class ApplicationListResponse(BaseModel):
    """Response model for application list."""

    applications: list[ApplicationResponse]
    total: int
    page: int
    page_size: int


class ApplicationEmailResponse(BaseModel):
    """Linked email shown inside an application detail view."""

    id: int
    subject: Optional[str]
    sender: Optional[str]
    received_at: Optional[str]
    classification: Optional[str]
    confidence: Optional[float]
    body_snippet: Optional[str]
    body_text: Optional[str]
    body_html: Optional[str]


class ApplicationDetailResponse(ApplicationResponse):
    """Detailed response with linked emails."""

    emails: list[ApplicationEmailResponse]


class LinkingPreviewResponse(BaseModel):
    """Preview of what linking would do for an email."""

    email_id: int
    subject: Optional[str]
    sender: Optional[str]
    classification: Optional[str]
    extraction: dict
    potential_matches: list[dict]
    would_create_new: bool


class BatchLinkResponse(BaseModel):
    """Response from batch linking operation."""

    processed: int
    linked: int
    applications_created: int
    skipped: int
    errors: int


class StatusTransitionRequest(BaseModel):
    """Request to transition application status."""

    new_status: ApplicationStatus


class MarkNotJobResponse(BaseModel):
    """Result of marking an application as not job-related."""

    success: bool
    application_id: int
    emails_reclassified: int
    message: str


class FollowUpReminderResponse(BaseModel):
    """Follow-up recommendation for a stale application."""

    application_id: int
    company: str
    position: str
    status: ApplicationStatus
    days_since_activity: int
    last_activity_at: str
    suggested_on: str
    reason: str


class FollowUpRemindersResponse(BaseModel):
    """List of follow-up reminders."""

    reminders: list[FollowUpReminderResponse]
    total: int


def _normalize_fts_query(search: str) -> Optional[str]:
    tokens = [token.strip() for token in search.replace('"', " ").split() if token.strip()]
    if not tokens:
        return None
    return " AND ".join(f"{token}*" for token in tokens)


async def _find_application_ids_for_search(session, search: str) -> Optional[list[int]]:
    """
    Resolve search term into matching application IDs using FTS5.

    Returns:
        - list of matching IDs when FTS lookup succeeds
        - None when FTS is unavailable (caller should fallback to ILIKE)
    """
    fts_query = _normalize_fts_query(search)
    if fts_query is None:
        return []

    try:
        app_rows = await session.exec(
            text(
                """
                SELECT applications.id AS application_id
                FROM applications
                JOIN applications_fts ON applications_fts.rowid = applications.id
                WHERE applications_fts MATCH :query
                """
            ).bindparams(query=fts_query)
        )
        email_rows = await session.exec(
            text(
                """
                SELECT DISTINCT emails.application_id AS application_id
                FROM emails
                JOIN emails_fts ON emails_fts.rowid = emails.id
                WHERE emails.application_id IS NOT NULL
                  AND emails_fts MATCH :query
                """
            ).bindparams(query=fts_query)
        )

        app_ids: set[int] = set()

        for row in app_rows.all():
            value = row[0] if hasattr(row, "__getitem__") else row
            if value is not None:
                app_ids.add(int(value))

        for row in email_rows.all():
            value = row[0] if hasattr(row, "__getitem__") else row
            if value is not None:
                app_ids.add(int(value))

        return sorted(app_ids)
    except Exception as exc:
        logger.debug("FTS search unavailable, falling back to ILIKE: %s", exc)
        return None


# =============================================================================
# CRUD Endpoints
# =============================================================================


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[ApplicationStatus] = None,
    company: Optional[str] = None,
    search: Optional[str] = None,
):
    """
    List all applications with optional filtering.

    - **page**: Page number (1-indexed)
    - **page_size**: Items per page (max 100)
    - **status**: Filter by status
    - **company**: Filter by company name (partial match)
    - **search**: Search in company and position
    """
    await mark_ghosted_applications()

    async with get_session() as session:
        # Build query
        stmt = select(Application)

        if status:
            stmt = stmt.where(Application.status == status)
        if company:
            stmt = stmt.where(Application.company.ilike(f"%{company}%"))
        if search:
            matching_ids = await _find_application_ids_for_search(session, search)
            if matching_ids is None:
                stmt = stmt.where(
                    (Application.company.ilike(f"%{search}%"))
                    | (Application.position.ilike(f"%{search}%"))
                )
            elif matching_ids:
                stmt = stmt.where(Application.id.in_(matching_ids))
            else:
                stmt = stmt.where(text("1 = 0"))

        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.exec(count_stmt)).one()

        # Pagination
        offset = (page - 1) * page_size
        stmt = stmt.order_by(Application.created_at.desc()).offset(offset).limit(page_size)

        result = await session.exec(stmt)
        applications = result.all()

        app_ids = [app.id for app in applications]
        email_counts: dict[int, int] = {}
        if app_ids:
            counts_result = await session.exec(
                select(Email.application_id, func.count(Email.id))
                .where(Email.application_id.in_(app_ids))
                .group_by(Email.application_id)
            )
            for row in counts_result.all():
                app_id = int(row[0])
                count = int(row[1])
                email_counts[app_id] = count

        # Build response using pre-fetched per-application counts
        app_responses = []
        for app in applications:
            app_responses.append(
                ApplicationResponse(
                    id=app.id,
                    company=app.company,
                    position=app.position,
                    status=app.status,
                    applied_date=app.applied_date.isoformat() if app.applied_date else None,
                    source=app.source,
                    url=app.url,
                    notes=app.notes,
                    created_at=app.created_at.isoformat(),
                    updated_at=app.updated_at.isoformat() if app.updated_at else None,
                    email_count=email_counts.get(app.id, 0),
                )
            )

        return ApplicationListResponse(
            applications=app_responses,
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
async def get_application(application_id: int):
    """Get a single application with linked emails."""
    async with get_session() as session:
        # Get application
        stmt = select(Application).where(Application.id == application_id)
        result = await session.exec(stmt)
        app = result.first()

        if not app:
            raise HTTPException(status_code=404, detail="Application not found")

        # Get linked emails
        email_stmt = select(Email).where(
            Email.application_id == application_id
        ).order_by(Email.received_at.desc())
        email_result = await session.exec(email_stmt)
        emails = email_result.all()

        email_data = [
            ApplicationEmailResponse(
                id=e.id,
                subject=e.subject,
                sender=e.sender_email,
                received_at=e.received_at.isoformat() if e.received_at else None,
                classification=e.classified_as.value if e.classified_as else None,
                confidence=e.classification_confidence,
                body_snippet=e.body_snippet,
                body_text=e.body_text,
                body_html=e.body_html,
            )
            for e in emails
        ]

        return ApplicationDetailResponse(
            id=app.id,
            company=app.company,
            position=app.position,
            status=app.status,
            applied_date=app.applied_date.isoformat() if app.applied_date else None,
            source=app.source,
            url=app.url,
            notes=app.notes,
            created_at=app.created_at.isoformat(),
            updated_at=app.updated_at.isoformat() if app.updated_at else None,
            email_count=len(emails),
            emails=email_data,
        )


@router.post("/{application_id}/mark-not-job", response_model=MarkNotJobResponse)
async def mark_application_not_job_posting(application_id: int):
    """
    Mark an application as not job-related.

    This reclassifies linked emails to OTHER, unlinks them, and deletes the
    application record.
    """
    async with get_session() as session:
        stmt = select(Application).where(Application.id == application_id)
        result = await session.exec(stmt)
        app = result.first()

        if not app:
            raise HTTPException(status_code=404, detail="Application not found")

        email_stmt = select(Email).where(Email.application_id == application_id)
        email_result = await session.exec(email_stmt)
        linked_emails = email_result.all()
        classifier = get_classifier()

        for email in linked_emails:
            email.application_id = None
            email.classified_as = EmailCategory.OTHER
            email.classification_confidence = 1.0
            email.classification_method = "user_marked_not_job"
            email.user_corrected = True
            email.is_reviewed = True
            session.add(email)

            # Feed explicit user action into training so future classifications improve.
            try:
                await classifier.add_correction(
                    email.id,
                    email.subject or "",
                    email.body_text or "",
                    EmailCategory.OTHER,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to add correction for email %s while marking app %s not job: %s",
                    email.id,
                    application_id,
                    exc,
                )

        await session.delete(app)
        await session.commit()

        reclassified = len(linked_emails)
        return MarkNotJobResponse(
            success=True,
            application_id=application_id,
            emails_reclassified=reclassified,
            message=(
                f"Application {application_id} removed. "
                f"{reclassified} linked emails marked as OTHER."
            ),
        )


@router.post("", response_model=ApplicationResponse, status_code=201)
async def create_application(data: ApplicationCreate):
    """Create a new application manually."""
    async with get_session() as session:
        app = Application(
            company=data.company,
            position=data.position,
            status=data.status,
            applied_date=datetime.fromisoformat(data.applied_date).date() if data.applied_date else None,
            source=data.source,
            url=data.url,
            notes=data.notes,
        )
        session.add(app)
        await session.commit()
        await session.refresh(app)

        return ApplicationResponse(
            id=app.id,
            company=app.company,
            position=app.position,
            status=app.status,
            applied_date=app.applied_date.isoformat() if app.applied_date else None,
            source=app.source,
            url=app.url,
            notes=app.notes,
            created_at=app.created_at.isoformat(),
            updated_at=None,
            email_count=0,
        )


@router.put("/{application_id}", response_model=ApplicationResponse)
async def update_application(application_id: int, data: ApplicationUpdate):
    """Update an application."""
    async with get_session() as session:
        stmt = select(Application).where(Application.id == application_id)
        result = await session.exec(stmt)
        app = result.first()

        if not app:
            raise HTTPException(status_code=404, detail="Application not found")

        # Update fields
        if data.company is not None:
            app.company = data.company
        if data.position is not None:
            app.position = data.position
        if data.status is not None:
            app.status = data.status
        if data.applied_date is not None:
            app.applied_date = datetime.fromisoformat(data.applied_date).date()
        if data.source is not None:
            app.source = data.source
        if data.url is not None:
            app.url = data.url
        if data.notes is not None:
            app.notes = data.notes

        app.updated_at = datetime.utcnow()
        session.add(app)
        await session.commit()
        await session.refresh(app)

        # Get email count
        email_count_stmt = select(func.count()).where(Email.application_id == app.id)
        email_count = (await session.exec(email_count_stmt)).one()

        return ApplicationResponse(
            id=app.id,
            company=app.company,
            position=app.position,
            status=app.status,
            applied_date=app.applied_date.isoformat() if app.applied_date else None,
            source=app.source,
            url=app.url,
            notes=app.notes,
            created_at=app.created_at.isoformat(),
            updated_at=app.updated_at.isoformat() if app.updated_at else None,
            email_count=email_count,
        )


@router.delete("/{application_id}", status_code=204)
async def delete_application(application_id: int):
    """Delete an application. Linked emails are unlinked (not deleted)."""
    async with get_session() as session:
        stmt = select(Application).where(Application.id == application_id)
        result = await session.exec(stmt)
        app = result.first()

        if not app:
            raise HTTPException(status_code=404, detail="Application not found")

        # Unlink emails first
        email_stmt = select(Email).where(Email.application_id == application_id)
        email_result = await session.exec(email_stmt)
        for email in email_result.all():
            email.application_id = None
            session.add(email)

        # Delete application
        await session.delete(app)
        await session.commit()


@router.post("/{application_id}/status", response_model=ApplicationResponse)
async def transition_status(application_id: int, data: StatusTransitionRequest):
    """Manually transition application status."""
    async with get_session() as session:
        stmt = select(Application).where(Application.id == application_id)
        result = await session.exec(stmt)
        app = result.first()

        if not app:
            raise HTTPException(status_code=404, detail="Application not found")

        app.status = data.new_status
        app.updated_at = datetime.utcnow()
        session.add(app)
        await session.commit()
        await session.refresh(app)

        email_count_stmt = select(func.count()).where(Email.application_id == app.id)
        email_count = (await session.exec(email_count_stmt)).one()

        return ApplicationResponse(
            id=app.id,
            company=app.company,
            position=app.position,
            status=app.status,
            applied_date=app.applied_date.isoformat() if app.applied_date else None,
            source=app.source,
            url=app.url,
            notes=app.notes,
            created_at=app.created_at.isoformat(),
            updated_at=app.updated_at.isoformat() if app.updated_at else None,
            email_count=email_count,
        )


# =============================================================================
# Linking Endpoints
# =============================================================================


@router.get("/link/preview/{email_id}", response_model=LinkingPreviewResponse)
async def preview_linking(email_id: int):
    """
    Preview what would happen if we link an email to an application.

    Shows extracted company/position and potential application matches.
    """
    linker = get_application_linker()
    preview = await linker.get_linking_preview(email_id)

    if not preview:
        raise HTTPException(status_code=404, detail="Email not found")

    return LinkingPreviewResponse(**preview)


@router.post("/link/email/{email_id}")
async def link_email_to_application(
    email_id: int,
    application_id: Optional[int] = Query(None, description="Link to specific application (auto-detect if not provided)"),
):
    """
    Link an email to an application.

    If application_id is provided, links to that specific application.
    Otherwise, auto-detects based on company/position extraction.
    """
    async with get_session() as session:
        # Get email
        stmt = select(Email).where(Email.id == email_id)
        result = await session.exec(stmt)
        email = result.first()

        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        if application_id:
            # Link to specific application
            app_stmt = select(Application).where(Application.id == application_id)
            app_result = await session.exec(app_stmt)
            app = app_result.first()

            if not app:
                raise HTTPException(status_code=404, detail="Application not found")

            email.application_id = application_id
            session.add(email)
            await session.commit()

            return {
                "success": True,
                "email_id": email_id,
                "application_id": application_id,
                "message": f"Linked to {app.company} - {app.position}",
            }
        else:
            # Auto-link
            linker = get_application_linker()
            app = await linker.process_email(email)

            if app:
                return {
                    "success": True,
                    "email_id": email_id,
                    "application_id": app.id,
                    "message": f"Linked to {app.company} - {app.position}",
                    "created_new": False,  # Could track this more accurately
                }
            else:
                return {
                    "success": False,
                    "email_id": email_id,
                    "message": "Could not extract company from email",
                }


@router.post("/link/batch", response_model=BatchLinkResponse)
async def batch_link_emails(
    limit: int = Query(None, ge=1, le=1000, description="Max emails to process"),
):
    """
    Process all unlinked job-related emails and link them to applications.

    Auto-creates applications for new companies.
    """
    linker = get_application_linker()
    stats = await linker.process_all_unlinked_emails(limit=limit)

    return BatchLinkResponse(**stats)


@router.get("/stats/overview")
async def get_applications_overview():
    """Get application statistics overview."""
    await mark_ghosted_applications()

    async with get_session() as session:
        # Count by status
        status_counts = {}
        for status in ApplicationStatus:
            count_stmt = select(func.count()).where(Application.status == status)
            count = (await session.exec(count_stmt)).one()
            status_counts[status.value] = count

        # Total count
        total_stmt = select(func.count()).select_from(Application)
        total = (await session.exec(total_stmt)).one()

        # Emails linked vs unlinked (job-related only)
        job_categories = [
            EmailCategory.APPLIED,
            EmailCategory.INTERVIEW,
            EmailCategory.OFFER,
            EmailCategory.REJECTION,
            EmailCategory.ASSESSMENT,
            EmailCategory.FOLLOW_UP,
        ]

        linked_stmt = select(func.count()).where(
            Email.application_id.isnot(None),
            Email.classified_as.in_(job_categories),
        )
        linked_count = (await session.exec(linked_stmt)).one()

        unlinked_stmt = select(func.count()).where(
            Email.application_id.is_(None),
            Email.classified_as.in_(job_categories),
        )
        unlinked_count = (await session.exec(unlinked_stmt)).one()

        return {
            "total_applications": total,
            "by_status": status_counts,
            "emails_linked": linked_count,
            "emails_unlinked": unlinked_count,
        }


@router.get("/insights/follow-up-reminders", response_model=FollowUpRemindersResponse)
async def get_follow_up_recommendations(
    stale_days: int = Query(default=7, ge=1, le=30),
    ghosted_days: int = Query(default=30, ge=7, le=120),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Suggest follow-ups for stale applications before they become ghosted.
    """
    await mark_ghosted_applications(stale_days=ghosted_days)
    reminders = await get_follow_up_reminders(
        stale_days=stale_days,
        ghosted_days=ghosted_days,
        limit=limit,
    )

    payload = [
        FollowUpReminderResponse(
            application_id=item.application_id,
            company=item.company,
            position=item.position,
            status=item.status,
            days_since_activity=item.days_since_activity,
            last_activity_at=item.last_activity_at.isoformat(),
            suggested_on=item.suggested_on.isoformat(),
            reason=item.reason,
        )
        for item in reminders
    ]

    return FollowUpRemindersResponse(reminders=payload, total=len(payload))
