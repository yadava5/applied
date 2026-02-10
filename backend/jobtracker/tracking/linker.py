"""
Application Linker
==================

Links emails to applications and manages application state.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlmodel import select

from jobtracker.database import get_session
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
)
from jobtracker.tracking.extractor import (
    ExtractionResult,
    extract_company_and_position,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Status State Machine
# =============================================================================

# Email category → Application status mapping
CATEGORY_TO_STATUS: dict[EmailCategory, ApplicationStatus] = {
    EmailCategory.APPLIED: ApplicationStatus.APPLIED,
    EmailCategory.INTERVIEW: ApplicationStatus.INTERVIEWING,
    EmailCategory.OFFER: ApplicationStatus.OFFERED,
    EmailCategory.REJECTION: ApplicationStatus.REJECTED,
    EmailCategory.ASSESSMENT: ApplicationStatus.INTERVIEWING,  # Assessment = part of interview process
}

# Status progression order (higher index = later stage)
STATUS_ORDER = [
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFERED,
    ApplicationStatus.ACCEPTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
    ApplicationStatus.GHOSTED,
]


def can_transition(current: ApplicationStatus, new: ApplicationStatus) -> bool:
    """
    Check if status transition is valid.

    Rules:
    - Can always move forward in the pipeline (applied → interviewing → offered)
    - Rejection can happen from any stage
    - Cannot move backwards (interviewing → applied)
    - Accepted/Withdrawn are terminal states
    """
    if current == new:
        return False  # No change

    # Terminal states - cannot transition from
    if current in (ApplicationStatus.ACCEPTED, ApplicationStatus.WITHDRAWN):
        return False

    # Rejection can happen from any non-terminal state
    if new == ApplicationStatus.REJECTED:
        return current not in (ApplicationStatus.ACCEPTED, ApplicationStatus.WITHDRAWN)

    # Forward progression
    try:
        current_idx = STATUS_ORDER.index(current)
        new_idx = STATUS_ORDER.index(new)
        return new_idx > current_idx
    except ValueError:
        return False


# =============================================================================
# Application Linker
# =============================================================================


class ApplicationLinker:
    """
    Links emails to applications and manages state.

    Responsibilities:
    - Extract company/position from emails
    - Find existing applications by company/position
    - Auto-create applications for new companies
    - Update application status based on email classification
    - Link emails to applications
    """

    def __init__(self):
        pass

    async def process_email(
        self,
        email: Email,
        *,
        auto_create: bool = True,
    ) -> Optional[Application]:
        """
        Process an email and link it to an application.

        Args:
            email: Email to process
            auto_create: Whether to auto-create new applications

        Returns:
            Linked Application or None
        """
        # Skip non-job-related emails
        if email.classified_as in (EmailCategory.OTHER, EmailCategory.NEEDS_REVIEW, None):
            logger.debug(f"Skipping non-job email: {email.id}")
            return None

        # Extract company and position
        extraction = extract_company_and_position(
            email.sender_email,
            email.subject or "",
            email.body_text or "",
        )

        if not extraction.company:
            logger.debug(f"Could not extract company from email {email.id}")
            return None

        logger.info(
            f"Extracted from email {email.id}: "
            f"company='{extraction.company}' (conf={extraction.company_confidence:.2f}), "
            f"position='{extraction.position}' (conf={extraction.position_confidence:.2f})"
        )

        # Find or create application
        application = await self._find_or_create_application(
            extraction,
            email,
            auto_create=auto_create,
        )

        if application:
            # Link email to application
            await self._link_email(email, application)

            # Update application status
            await self._update_application_status(application, email)

        return application

    async def _find_or_create_application(
        self,
        extraction: ExtractionResult,
        email: Email,
        *,
        auto_create: bool,
    ) -> Optional[Application]:
        """Find existing application or create new one."""
        async with get_session() as session:
            # First, try to find by exact company + position match
            if extraction.position:
                stmt = select(Application).where(
                    Application.company.ilike(extraction.company),
                    Application.position.ilike(extraction.position),
                )
                result = await session.exec(stmt)
                app = result.first()
                if app:
                    logger.info(f"Found exact match: Application #{app.id} ({app.company} - {app.position})")
                    return app

            # Second, try to find by company only (any position)
            stmt = select(Application).where(
                Application.company.ilike(extraction.company)
            ).order_by(Application.created_at.desc())
            result = await session.exec(stmt)
            apps = result.all()

            if apps:
                # If we have position, check if it matches any
                if extraction.position:
                    # Check for similar positions
                    for app in apps:
                        if self._positions_match(app.position, extraction.position):
                            logger.info(f"Found similar position match: Application #{app.id}")
                            return app

                    # No position match - this is a different job at same company
                    if auto_create:
                        return await self._create_application(extraction, email, session)
                    return None

                # No position extracted - use most recent application for this company
                logger.info(f"Using most recent application for {extraction.company}: #{apps[0].id}")
                return apps[0]

            # No existing application - create new one
            if auto_create:
                return await self._create_application(extraction, email, session)

            return None

    def _positions_match(self, pos1: str, pos2: str) -> bool:
        """Check if two positions are similar (fuzzy match)."""
        if not pos1 or not pos2:
            return False

        # Normalize
        pos1 = pos1.lower().strip()
        pos2 = pos2.lower().strip()

        # Exact match
        if pos1 == pos2:
            return True

        # Word overlap - if >50% words overlap, consider a match
        words1 = set(pos1.split())
        words2 = set(pos2.split())
        if not words1 or not words2:
            return False

        overlap = len(words1 & words2)
        min_words = min(len(words1), len(words2))

        return overlap / min_words >= 0.5

    async def _create_application(
        self,
        extraction: ExtractionResult,
        email: Email,
        session,
    ) -> Application:
        """Create a new application record."""
        application = Application(
            company=extraction.company,
            position=extraction.position or "Unknown Position",
            status=CATEGORY_TO_STATUS.get(
                email.classified_as, ApplicationStatus.APPLIED
            ),
            applied_date=email.received_at.date() if email.received_at else None,
        )

        session.add(application)
        await session.commit()
        await session.refresh(application)

        logger.info(
            f"Created new Application #{application.id}: "
            f"{application.company} - {application.position}"
        )

        return application

    async def _link_email(self, email: Email, application: Application) -> None:
        """Link email to application."""
        if email.application_id == application.id:
            return  # Already linked

        async with get_session() as session:
            # Get fresh email from DB
            stmt = select(Email).where(Email.id == email.id)
            result = await session.exec(stmt)
            db_email = result.first()

            if db_email:
                db_email.application_id = application.id
                session.add(db_email)
                await session.commit()

                logger.info(f"Linked email #{email.id} to application #{application.id}")

    async def _update_application_status(
        self,
        application: Application,
        email: Email,
    ) -> None:
        """Update application status based on email classification."""
        if email.classified_as not in CATEGORY_TO_STATUS:
            return

        new_status = CATEGORY_TO_STATUS[email.classified_as]

        if not can_transition(application.status, new_status):
            logger.debug(
                f"Cannot transition application #{application.id} "
                f"from {application.status} to {new_status}"
            )
            return

        async with get_session() as session:
            # Get fresh application
            stmt = select(Application).where(Application.id == application.id)
            result = await session.exec(stmt)
            db_app = result.first()

            if db_app and can_transition(db_app.status, new_status):
                old_status = db_app.status
                db_app.status = new_status
                db_app.updated_at = datetime.utcnow()
                session.add(db_app)
                await session.commit()

                logger.info(
                    f"Updated application #{application.id} status: "
                    f"{old_status} → {new_status}"
                )

    async def process_all_unlinked_emails(
        self,
        *,
        limit: Optional[int] = None,
    ) -> dict:
        """
        Process all unlinked job-related emails.

        Returns:
            Stats dict with counts
        """
        stats = {
            "processed": 0,
            "linked": 0,
            "applications_created": 0,
            "skipped": 0,
            "errors": 0,
        }

        async with get_session() as session:
            # Find job-related emails without application link
            job_categories = [
                EmailCategory.APPLIED,
                EmailCategory.INTERVIEW,
                EmailCategory.OFFER,
                EmailCategory.REJECTION,
                EmailCategory.ASSESSMENT,
                EmailCategory.FOLLOW_UP,
            ]

            stmt = select(Email).where(
                Email.application_id.is_(None),
                Email.classified_as.in_(job_categories),
            ).order_by(Email.received_at.asc())

            if limit:
                stmt = stmt.limit(limit)

            result = await session.exec(stmt)
            emails = result.all()

        # Count applications before
        async with get_session() as session:
            result = await session.exec(select(Application))
            apps_before = len(result.all())

        # Process each email
        for email in emails:
            stats["processed"] += 1
            try:
                app = await self.process_email(email)
                if app:
                    stats["linked"] += 1
            except Exception as e:
                logger.error(f"Error processing email {email.id}: {e}")
                stats["errors"] += 1

        # Count applications after
        async with get_session() as session:
            result = await session.exec(select(Application))
            apps_after = len(result.all())

        stats["applications_created"] = apps_after - apps_before
        stats["skipped"] = stats["processed"] - stats["linked"] - stats["errors"]

        return stats

    async def get_linking_preview(self, email_id: int) -> Optional[dict]:
        """
        Preview what linking would do for an email.

        Returns:
            Dict with extracted info and potential matches
        """
        async with get_session() as session:
            stmt = select(Email).where(Email.id == email_id)
            result = await session.exec(stmt)
            email = result.first()

            if not email:
                return None

            # Extract company/position
            extraction = extract_company_and_position(
                email.sender_email,
                email.subject or "",
                email.body_text or "",
            )

            # Find potential matches
            matches = []
            if extraction.company:
                stmt = select(Application).where(
                    Application.company.ilike(f"%{extraction.company}%")
                )
                result = await session.exec(stmt)
                for app in result.all():
                    matches.append({
                        "id": app.id,
                        "company": app.company,
                        "position": app.position,
                        "status": app.status,
                    })

            return {
                "email_id": email_id,
                "subject": email.subject,
                "sender": email.sender_email,
                "classification": email.classified_as,
                "extraction": {
                    "company": extraction.company,
                    "company_confidence": extraction.company_confidence,
                    "position": extraction.position,
                    "position_confidence": extraction.position_confidence,
                    "method": extraction.extraction_method,
                },
                "potential_matches": matches,
                "would_create_new": len(matches) == 0 and extraction.company is not None,
            }


# =============================================================================
# Singleton
# =============================================================================

_application_linker: Optional[ApplicationLinker] = None


def get_application_linker() -> ApplicationLinker:
    """Get singleton ApplicationLinker instance."""
    global _application_linker
    if _application_linker is None:
        _application_linker = ApplicationLinker()
    return _application_linker
