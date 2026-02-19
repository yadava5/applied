"""
Email API endpoints.

Provides access to synced emails and their metadata.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from jobtracker.database import get_session
from jobtracker.database.models import Email, EmailCategory, EmailSource

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


def _normalize_fts_query(search: str) -> Optional[str]:
    tokens = [token.strip() for token in search.replace('"', " ").split() if token.strip()]
    if not tokens:
        return None
    return " AND ".join(f"{token}*" for token in tokens)


async def _find_email_ids_for_search(session, search: str) -> Optional[list[int]]:
    """
    Resolve full-text query to email IDs using FTS5.

    Returns:
        - list of IDs when FTS lookup succeeds
        - None when FTS is unavailable (caller should fallback to ILIKE)
    """
    fts_query = _normalize_fts_query(search)
    if fts_query is None:
        return []

    try:
        rows = await session.exec(
            text(
                """
                SELECT emails.id AS email_id
                FROM emails
                JOIN emails_fts ON emails_fts.rowid = emails.id
                WHERE emails_fts MATCH :query
                """
            ).bindparams(query=fts_query)
        )
        ids: list[int] = []
        for row in rows.all():
            value = row[0] if hasattr(row, "__getitem__") else row
            if value is not None:
                ids.append(int(value))
        return ids
    except Exception as exc:
        logger.debug("Email FTS search unavailable, falling back to ILIKE: %s", exc)
        return None


# =============================================================================
# Request/Response Models
# =============================================================================


class EmailResponse(BaseModel):
    """Single email response."""

    id: int
    source_account: str
    message_id: str
    thread_id: Optional[str]
    subject: str
    sender_name: Optional[str]
    sender_email: str
    received_at: datetime
    body_snippet: str
    classified_as: Optional[str]
    classification_confidence: Optional[float]
    classification_method: Optional[str]
    user_corrected: bool
    is_reviewed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailDetailResponse(EmailResponse):
    """Detailed email response including full body."""

    body_text: str
    body_html: Optional[str] = None


class EmailListResponse(BaseModel):
    """Paginated email list response."""

    emails: list[EmailResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class EmailStatsResponse(BaseModel):
    """Email statistics."""

    total_emails: int
    by_source: dict[str, int]
    by_classification: dict[str, int]
    unreviewed_count: int
    latest_email: Optional[datetime]


# =============================================================================
# Endpoints
# =============================================================================


@router.get("", response_model=EmailListResponse)
async def list_emails(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Items per page"),
    source: Optional[str] = Query(
        default=None, description="Filter by source (gmail, icloud)"
    ),
    classification: Optional[str] = Query(
        default=None, description="Filter by classification"
    ),
    unreviewed_only: bool = Query(
        default=False, description="Only show unreviewed emails"
    ),
    search: Optional[str] = Query(
        default=None, description="Search in subject and sender"
    ),
) -> EmailListResponse:
    """
    List synced emails with pagination and filtering.

    Supports filtering by:
    - Source account (gmail, icloud)
    - Classification category
    - Reviewed status
    - Search term (subject, sender)
    """
    async with get_session() as session:
        # Build base query
        query = select(Email)

        # Apply filters
        if source:
            try:
                email_source = EmailSource(source)
                query = query.where(Email.source_account == email_source)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid source: {source}. Must be 'gmail' or 'icloud'.",
                )

        if classification:
            try:
                category = EmailCategory(classification)
                query = query.where(Email.classified_as == category)
            except ValueError:
                valid = [c.value for c in EmailCategory]
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid classification: {classification}. Valid: {valid}",
                )

        if unreviewed_only:
            query = query.where(Email.is_reviewed == False)  # noqa: E712

        if search:
            matching_ids = await _find_email_ids_for_search(session, search)
            if matching_ids is None:
                search_term = f"%{search}%"
                query = query.where(
                    (Email.subject.ilike(search_term))
                    | (Email.sender_email.ilike(search_term))
                    | (Email.sender_name.ilike(search_term))
                    | (Email.body_snippet.ilike(search_term))
                    | (Email.body_text.ilike(search_term))
                )
            elif matching_ids:
                query = query.where(Email.id.in_(matching_ids))
            else:
                query = query.where(text("1 = 0"))

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        result = await session.exec(count_query)
        total = result.one()[0]  # Extract scalar from row

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.order_by(Email.received_at.desc())
        query = query.offset(offset).limit(page_size)

        # Execute query
        result = await session.exec(query)
        email_rows = result.all()
        
        # Extract Email objects from rows (SQLModel returns Row tuples)
        emails = []
        for row in email_rows:
            email = row[0] if hasattr(row, '__getitem__') else row
            emails.append(email)

        return EmailListResponse(
            emails=[
                EmailResponse(
                    id=e.id,
                    source_account=e.source_account.value if hasattr(e.source_account, 'value') else str(e.source_account),
                    message_id=e.message_id,
                    thread_id=e.thread_id,
                    subject=e.subject or "",
                    sender_name=e.sender_name,
                    sender_email=e.sender_email or "",
                    received_at=e.received_at,
                    body_snippet=e.body_snippet or "",
                    classified_as=e.classified_as.value if hasattr(e.classified_as, 'value') else e.classified_as,
                    classification_confidence=e.classification_confidence,
                    classification_method=e.classification_method.value if hasattr(e.classification_method, 'value') else e.classification_method,
                    user_corrected=e.user_corrected,
                    is_reviewed=e.is_reviewed,
                    created_at=e.created_at,
                )
                for e in emails
            ],
            total=total,
            page=page,
            page_size=page_size,
            has_more=(offset + len(emails)) < total,
        )


@router.get("/stats", response_model=EmailStatsResponse)
async def get_email_stats() -> EmailStatsResponse:
    """
    Get email statistics.

    Returns counts by source, classification, and review status.
    """
    async with get_session() as session:
        # Total count
        result = await session.exec(select(func.count()).select_from(Email))
        total = result.one()[0]

        # By source
        by_source = {}
        for email_source in EmailSource:
            result = await session.exec(
                select(func.count())
                .select_from(Email)
                .where(Email.source_account == email_source)
            )
            count = result.one()[0]
            if count > 0:
                by_source[email_source.value] = count

        # By classification
        by_classification = {}
        for category in EmailCategory:
            result = await session.exec(
                select(func.count())
                .select_from(Email)
                .where(Email.classified_as == category)
            )
            count = result.one()[0]
            if count > 0:
                by_classification[category.value] = count

        # Unclassified count
        result = await session.exec(
            select(func.count())
            .select_from(Email)
            .where(Email.classified_as == None)  # noqa: E711
        )
        unclassified = result.one()[0]
        if unclassified > 0:
            by_classification["unclassified"] = unclassified

        # Unreviewed count
        result = await session.exec(
            select(func.count())
            .select_from(Email)
            .where(Email.is_reviewed == False)  # noqa: E712
        )
        unreviewed = result.one()[0]

        # Latest email
        result = await session.exec(
            select(Email.received_at)
            .order_by(Email.received_at.desc())
            .limit(1)
        )
        row = result.first()
        latest = row[0] if row else None

        return EmailStatsResponse(
            total_emails=total,
            by_source=by_source,
            by_classification=by_classification,
            unreviewed_count=unreviewed,
            latest_email=latest,
        )


@router.get("/{email_id}", response_model=EmailDetailResponse)
async def get_email(email_id: int) -> EmailDetailResponse:
    """
    Get a specific email by ID.

    Returns full email details including body text.
    """
    async with get_session() as session:
        result = await session.exec(select(Email).where(Email.id == email_id))
        row = result.first()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email with id {email_id} not found",
            )
        
        # Extract Email from Row if needed
        email = row[0] if hasattr(row, '__getitem__') else row

        return EmailDetailResponse(
            id=email.id,
            source_account=email.source_account.value if hasattr(email.source_account, 'value') else str(email.source_account),
            message_id=email.message_id,
            thread_id=email.thread_id,
            subject=email.subject or "",
            sender_name=email.sender_name,
            sender_email=email.sender_email or "",
            received_at=email.received_at,
            body_text=email.body_text or "",
            body_html=email.body_html,
            body_snippet=email.body_snippet or "",
            classified_as=email.classified_as.value if hasattr(email.classified_as, 'value') else email.classified_as,
            classification_confidence=email.classification_confidence,
            classification_method=email.classification_method.value if hasattr(email.classification_method, 'value') else email.classification_method,
            user_corrected=email.user_corrected,
            is_reviewed=email.is_reviewed,
            created_at=email.created_at,
        )


@router.put("/{email_id}/review")
async def mark_email_reviewed(email_id: int) -> dict:
    """Mark an email as reviewed."""
    async with get_session() as session:
        result = await session.exec(select(Email).where(Email.id == email_id))
        email = result.first()

        if email is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email with id {email_id} not found",
            )

        email.is_reviewed = True
        session.add(email)
        await session.commit()

        return {"success": True, "message": "Email marked as reviewed"}


@router.delete("/{email_id}")
async def delete_email(email_id: int) -> dict:
    """
    Delete an email from the database.

    Note: This only removes it from JobTracker, not from the email provider.
    """
    async with get_session() as session:
        result = await session.exec(select(Email).where(Email.id == email_id))
        email = result.first()

        if email is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email with id {email_id} not found",
            )

        await session.delete(email)
        await session.commit()

        return {"success": True, "message": "Email deleted"}


@router.delete("")
async def delete_emails_bulk(
    source: Optional[str] = Query(
        default=None,
        description="Delete emails from this source: 'gmail' or 'icloud'",
    ),
    sender_email: Optional[str] = Query(
        default=None,
        description="Delete emails from this sender email address",
    ),
    before_date: Optional[datetime] = Query(
        default=None,
        description="Delete emails received before this date",
    ),
    after_date: Optional[datetime] = Query(
        default=None,
        description="Delete emails received after this date",
    ),
    confirm: bool = Query(
        default=False,
        description="Must be True to actually delete. Safety check.",
    ),
) -> dict:
    """
    Delete emails in bulk based on filters.

    IMPORTANT: You must set confirm=true to actually delete.
    If confirm=false (default), returns count of emails that would be deleted.

    Examples:
    - Delete all Gmail emails: DELETE /emails?source=gmail&confirm=true
    - Delete all iCloud emails: DELETE /emails?source=icloud&confirm=true
    - Preview deletion: DELETE /emails?source=gmail (without confirm)
    """
    from sqlalchemy import delete as sql_delete

    if not source and not sender_email and not before_date and not after_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one filter (source, sender_email, before_date, after_date) is required",
        )

    async with get_session() as session:
        # Build count query first
        count_query = select(func.count(Email.id))

        if source:
            if source.lower() == "gmail":
                count_query = count_query.where(
                    Email.source_account == EmailSource.GMAIL
                )
            elif source.lower() == "icloud":
                count_query = count_query.where(
                    Email.source_account == EmailSource.ICLOUD
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid source: {source}. Use 'gmail' or 'icloud'.",
                )

        if sender_email:
            count_query = count_query.where(Email.sender_email == sender_email)

        if before_date:
            count_query = count_query.where(Email.received_at < before_date)

        if after_date:
            count_query = count_query.where(Email.received_at > after_date)

        result = await session.exec(count_query)
        count_row = result.one()
        # Count query returns a Row with single value - extract it
        count = count_row[0] if hasattr(count_row, '__getitem__') else int(count_row)

        if not confirm:
            return {
                "preview": True,
                "would_delete": count,
                "message": f"Add confirm=true to delete {count} emails",
            }

        # Build delete query with same filters
        delete_query = sql_delete(Email)

        if source:
            if source.lower() == "gmail":
                delete_query = delete_query.where(
                    Email.source_account == EmailSource.GMAIL
                )
            else:
                delete_query = delete_query.where(
                    Email.source_account == EmailSource.ICLOUD
                )

        if sender_email:
            delete_query = delete_query.where(Email.sender_email == sender_email)

        if before_date:
            delete_query = delete_query.where(Email.received_at < before_date)

        if after_date:
            delete_query = delete_query.where(Email.received_at > after_date)

        await session.exec(delete_query)
        await session.commit()

        return {
            "success": True,
            "deleted": count,
            "message": f"Deleted {count} emails",
        }
