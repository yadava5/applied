"""
Application Linker
==================

Links emails to applications and manages application state.
"""

import logging
import re
from datetime import datetime
from typing import Optional

from sqlmodel import select

from jobtracker.database import get_session
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Contact,
    ContactRole,
    Email,
    EmailCategory,
    Interview,
    InterviewStatus,
    InterviewType,
)
from jobtracker.tracking.extractor import (
    ExtractionResult,
    extract_company_and_position,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Content Guards
# =============================================================================

NON_APPLICATION_CONTENT_PATTERNS = [
    r"\bjob alerts?\b",
    r"\brecommended jobs?\b",
    r"\bjobs? you may be interested in\b",
    r"\bnew jobs? for you\b",
    r"\bunsubscribe\b",
    r"\bmanage preferences\b",
    r"\bweekly digest\b",
    r"\bdaily digest\b",
    r"\bnewsletter\b",
    r"\btop picks? for you\b",
    r"\bshop now\b",
    r"\bflash sale\b",
    r"\bcoupon\b",
    r"\bsecurity alert\b",
    r"\bverification code\b",
    r"\bconfirmation code\b",
    r"\bone[- ]time (passcode|password|code)\b",
    r"\botp\b",
    r"\bsign[- ]in\b",
    r"\blogin\b",
    r"\baccount (alert|security|verification)\b",
    r"\bbank alert\b",
    r"\bstatement available\b",
    r"\btransaction alert\b",
    r"\breferral bonus\b",
    r"\btalent community\b",
]

LIFECYCLE_EVIDENCE_PATTERNS = [
    r"\bthank(?:s| you) for applying\b",
    r"\bthank you for your online submission\b",
    r"\bonline submission\b",
    r"\bthank you for your interest in working with\b",
    r"\bthank you again for applying\b",
    r"\byour application\b",
    r"\bapplication (received|submitted)\b",
    r"\bregret to inform\b",
    r"\bunfortunately\b",
    r"\binterview\b",
    r"\bphone screen\b",
    r"\btechnical (assessment|challenge|test)\b",
    r"\boffer letter\b",
    r"\bposition has been filled\b",
]


# =============================================================================
# Status State Machine
# =============================================================================

# Email category → Application status mapping
CATEGORY_TO_STATUS: dict[EmailCategory, ApplicationStatus] = {
    EmailCategory.APPLIED: ApplicationStatus.APPLIED,
    EmailCategory.PENDING_APPLICATION: ApplicationStatus.APPLIED,
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

POSITION_EQUIVALENT_TOKENS = {
    "sde": "software",
    "swe": "software",
    "eng": "engineer",
    "dev": "developer",
}

POSITION_MODIFIER_TOKENS = {
    "senior",
    "sr",
    "junior",
    "jr",
    "staff",
    "principal",
    "lead",
    "intern",
    "new",
    "grad",
    "graduate",
    "i",
    "ii",
    "iii",
    "iv",
}

NON_PERSON_SENDER_TOKENS = (
    "no-reply",
    "noreply",
    "do-not-reply",
    "notifications",
    "support",
    "updates",
    "newsletter",
    "jobalerts",
)

INTERVIEW_DATE_PATTERNS = [
    # 2026-03-12 14:00 or 2026-03-12T14:00
    (re.compile(r"(\d{4}-\d{2}-\d{2})[T\\s](\d{1,2}:\d{2})"), "%Y-%m-%d %H:%M"),
    # Feb 12, 2026 2:30 PM
    (
        re.compile(
            r"\\b("
            r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
            r")[a-z]*\\s+(\\d{1,2}),?\\s+(\\d{4})\\s+(\\d{1,2}:\\d{2}\\s*(?:AM|PM))\\b",
            re.IGNORECASE,
        ),
        "%b %d %Y %I:%M %p",
    ),
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
        self._non_application_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in NON_APPLICATION_CONTENT_PATTERNS
        ]
        self._lifecycle_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in LIFECYCLE_EVIDENCE_PATTERNS
        ]

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

        if self._should_skip_email(email):
            logger.info(f"Skipping likely non-application email: {email.id}")
            return None

        # Extract company and position
        extraction = extract_company_and_position(
            email.sender_email,
            email.subject or "",
            email.body_text or "",
            sender_name=email.sender_name,
        )

        if not extraction.company:
            logger.debug(f"Could not extract company from email {email.id}")
            return None

        if extraction.company_confidence < 0.60:
            logger.debug(
                "Skipping email %s due to low company confidence (%.2f)",
                email.id,
                extraction.company_confidence,
            )
            return None

        logger.info(
            f"Extracted from email {email.id}: "
            f"company='{extraction.company}' (conf={extraction.company_confidence:.2f}), "
            f"position='{extraction.position}' (conf={extraction.position_confidence:.2f})"
        )

        # Find or create application
        should_auto_create = auto_create and self._should_auto_create_application(
            email,
            extraction,
        )
        application = await self._find_or_create_application(
            extraction,
            email,
            auto_create=should_auto_create,
        )

        if application:
            # Link email to application
            await self._link_email(email, application)

            # Update application status
            await self._update_application_status(application, email)
            await self._upsert_contact_from_email(application, email)
            await self._record_interview_details(application, email)

        return application

    def _email_text(self, email: Email) -> str:
        """Combined lower-cased text used for guard checks."""
        subject = email.subject or ""
        body = email.body_text or email.body_snippet or ""
        return f"{subject}\n{body}".lower()

    def _has_lifecycle_evidence(self, email: Email) -> bool:
        text = self._email_text(email)
        return any(pattern.search(text) for pattern in self._lifecycle_patterns)

    def _looks_like_digest_or_promo(self, email: Email) -> bool:
        text = self._email_text(email)
        content_hits = sum(
            1 for pattern in self._non_application_patterns if pattern.search(text)
        )
        sender = (email.sender_email or "").lower()
        sender_hit = any(
            token in sender
            for token in ("jobalerts", "jobs-noreply", "newsletter", "marketing")
        )
        return content_hits >= 2 or (sender_hit and content_hits >= 1)

    def _should_skip_email(self, email: Email) -> bool:
        if self._has_lifecycle_evidence(email):
            return False
        return self._looks_like_digest_or_promo(email)

    def _should_auto_create_application(
        self,
        email: Email,
        extraction: ExtractionResult,
    ) -> bool:
        """
        Gate auto-create to avoid polluting applications with digests/newsletters.
        """
        if extraction.company_confidence < 0.70:
            return False

        if self._looks_like_digest_or_promo(email) and not self._has_lifecycle_evidence(email):
            return False

        if email.classified_as in (
            EmailCategory.APPLIED,
            EmailCategory.PENDING_APPLICATION,
        ):
            if extraction.position_confidence >= 0.50:
                return True
            return self._has_lifecycle_evidence(email)

        return True

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
                # Re-processing should be idempotent: if this email is already linked
                # to an app for the extracted company, reuse that app.
                linked_app_id = email.application_id
                if linked_app_id is None and email.id is not None:
                    linked_stmt = select(Email.application_id).where(Email.id == email.id)
                    linked_app_id = (await session.exec(linked_stmt)).first()
                    if hasattr(linked_app_id, "__getitem__"):
                        linked_app_id = linked_app_id[0]

                if linked_app_id is not None:
                    existing_link = next(
                        (app for app in apps if app.id == linked_app_id),
                        None,
                    )
                    if existing_link:
                        if not extraction.position:
                            logger.info(
                                "Email %s already linked to application #%s; reusing",
                                email.id,
                                existing_link.id,
                            )
                            return existing_link

                        if self._positions_match(
                            existing_link.position,
                            extraction.position,
                        ):
                            logger.info(
                                "Email %s already linked to matching application #%s; reusing",
                                email.id,
                                existing_link.id,
                            )
                            return existing_link

                        existing_position_lower = (existing_link.position or "").strip().lower()
                        if existing_position_lower.startswith(
                            ("applying to ", "for applying to ")
                        ):
                            existing_link.position = extraction.position
                            existing_link.updated_at = datetime.utcnow()
                            session.add(existing_link)
                            await session.commit()
                            await session.refresh(existing_link)
                            logger.info(
                                "Normalized noisy position on application #%s to '%s'",
                                existing_link.id,
                                extraction.position,
                            )
                            return existing_link

                        if (existing_link.position or "").strip().lower() == "unknown position":
                            existing_link.position = extraction.position
                            existing_link.updated_at = datetime.utcnow()
                            session.add(existing_link)
                            await session.commit()
                            await session.refresh(existing_link)
                            logger.info(
                                "Upgraded application #%s position to '%s' from relink",
                                existing_link.id,
                                extraction.position,
                            )
                            return existing_link

                # If we have position, check if it matches any
                if extraction.position:
                    # Check for similar positions
                    for app in apps:
                        if self._positions_match(app.position, extraction.position):
                            logger.info(f"Found similar position match: Application #{app.id}")
                            return app

                    # If an earlier APPLIED email created a placeholder app, upgrade it
                    # with the newly extracted concrete position.
                    if email.classified_as in (
                        EmailCategory.APPLIED,
                        EmailCategory.PENDING_APPLICATION,
                    ):
                        placeholder_apps = [
                            app for app in apps
                            if (app.position or "").strip().lower() == "unknown position"
                        ]
                        if len(placeholder_apps) == 1:
                            app = placeholder_apps[0]
                            app.position = extraction.position
                            app.updated_at = datetime.utcnow()
                            session.add(app)
                            await session.commit()
                            await session.refresh(app)
                            logger.info(
                                "Updated placeholder application #%s position to '%s'",
                                app.id,
                                extraction.position,
                            )
                            return app

                    # No position match - this is a different job at same company
                    if auto_create:
                        return await self._create_application(extraction, email, session)
                    return None

                thread_match = await self._find_application_by_thread(
                    apps=apps,
                    email=email,
                    session=session,
                )
                if thread_match:
                    return thread_match

                # For APPLIED emails without a position, do not collapse by company.
                # A candidate may apply to multiple roles at the same company.
                if email.classified_as in (
                    EmailCategory.APPLIED,
                    EmailCategory.PENDING_APPLICATION,
                ) and auto_create:
                    # If we already have a same-day concrete-position application for
                    # this company, treat this as a duplicate confirmation and link it.
                    if email.received_at:
                        email_date = email.received_at.date()
                        positioned_same_day = [
                            app
                            for app in apps
                            if (app.position or "").strip().lower() != "unknown position"
                            and app.applied_date is not None
                            and app.applied_date == email_date
                        ]
                        if positioned_same_day:
                            logger.info(
                                "Using same-day positioned application #%s for APPLIED email %s at %s",
                                positioned_same_day[0].id,
                                email.id,
                                extraction.company,
                            )
                            return positioned_same_day[0]

                    logger.info(
                        "No position extracted for APPLIED email %s at %s; creating new application",
                        email.id,
                        extraction.company,
                    )
                    return await self._create_application(extraction, email, session)

                # For later-stage lifecycle emails without position, fall back to most recent.
                logger.info(
                    "No position extracted for %s email %s at %s; using most recent application #%s",
                    email.classified_as,
                    email.id,
                    extraction.company,
                    apps[0].id,
                )
                return apps[0]

            # No existing application - create new one
            if auto_create:
                return await self._create_application(extraction, email, session)

            return None

    async def _find_application_by_thread(
        self,
        *,
        apps: list[Application],
        email: Email,
        session,
    ) -> Optional[Application]:
        """
        Find a linked application for the same company by email thread.
        """
        if not email.thread_id:
            return None

        app_ids = [app.id for app in apps]
        if not app_ids:
            return None

        stmt = (
            select(Email.application_id)
            .where(
                Email.thread_id == email.thread_id,
                Email.application_id.in_(app_ids),
            )
            .order_by(Email.received_at.desc())
        )
        result = await session.exec(stmt)
        matched_app_id = result.first()
        if matched_app_id is None:
            return None

        match = next((app for app in apps if app.id == matched_app_id), None)
        if match:
            logger.info(
                "Matched email %s to application #%s by thread_id",
                email.id,
                match.id,
            )
        return match

    def _positions_match(self, pos1: str, pos2: str) -> bool:
        """Check if two position titles are effectively the same role."""
        if not pos1 or not pos2:
            return False

        normalized_1 = self._normalize_position_text(pos1)
        normalized_2 = self._normalize_position_text(pos2)

        if normalized_1 == normalized_2:
            return True

        # Ignore seniority/level modifiers when comparing equivalent titles.
        core_1 = self._position_core_tokens(normalized_1)
        core_2 = self._position_core_tokens(normalized_2)
        if core_1 and core_2 and core_1 == core_2:
            return True

        return False

    def _normalize_position_text(self, position: str) -> str:
        """Lowercase, normalize punctuation, and map common abbreviations."""
        tokens = re.findall(r"[a-z0-9]+", position.lower())
        normalized_tokens = [
            POSITION_EQUIVALENT_TOKENS.get(token, token) for token in tokens
        ]
        return " ".join(normalized_tokens).strip()

    def _position_core_tokens(self, normalized_position: str) -> set[str]:
        """Return comparison tokens with generic level modifiers removed."""
        return {
            token
            for token in normalized_position.split()
            if token not in POSITION_MODIFIER_TOKENS
        }

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

    def _infer_contact_role(self, text: str) -> Optional[ContactRole]:
        lower = text.lower()
        if any(token in lower for token in ("recruiter", "talent acquisition", "sourcer", "staffing")):
            return ContactRole.RECRUITER
        if "hiring manager" in lower:
            return ContactRole.HIRING_MANAGER
        if any(token in lower for token in ("human resources", "people operations", "hr team")):
            return ContactRole.HR
        return None

    def _extract_signature_name(self, body: str) -> Optional[str]:
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if not lines:
            return None

        tail = lines[-8:]
        for idx, line in enumerate(tail):
            lowered = line.lower()
            if lowered in {"thanks,", "thanks", "best,", "best", "regards,", "regards", "sincerely,"}:
                if idx + 1 < len(tail):
                    candidate = tail[idx + 1]
                    if re.match(r"^[A-Z][A-Za-z'\\-]+(?:\\s+[A-Z][A-Za-z'\\-]+){0,2}$", candidate):
                        return candidate

        # Fallback: the last human-looking line.
        for line in reversed(tail):
            if re.match(r"^[A-Z][A-Za-z'\\-]+(?:\\s+[A-Z][A-Za-z'\\-]+){0,2}$", line):
                return line
        return None

    def _extract_signature_title(self, body: str) -> Optional[str]:
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        for line in lines[-8:]:
            lower = line.lower()
            if any(token in lower for token in ("recruiter", "hiring manager", "talent", "human resources", "hr")):
                return line
        return None

    def _is_non_person_sender(self, sender_email: str) -> bool:
        lowered = sender_email.lower()
        return any(token in lowered for token in NON_PERSON_SENDER_TOKENS)

    async def _upsert_contact_from_email(self, application: Application, email: Email) -> None:
        """Create/update recruiter contact details from sender + signature hints."""
        if application.id is None or not email.sender_email:
            return
        if self._is_non_person_sender(email.sender_email):
            return

        sender_name = (email.sender_name or "").strip()
        signature_name = self._extract_signature_name(email.body_text or "")
        signature_title = self._extract_signature_title(email.body_text or "")
        inferred_role = self._infer_contact_role(
            f"{email.subject or ''}\n{email.body_text or ''}\n{signature_title or ''}"
        )

        chosen_name = signature_name or sender_name or None
        if chosen_name and len(chosen_name) > 120:
            chosen_name = chosen_name[:120]

        async with get_session() as session:
            result = await session.exec(
                select(Contact).where(
                    Contact.application_id == application.id,
                    Contact.email == email.sender_email,
                )
            )
            existing = result.first()
            contact = existing[0] if hasattr(existing, "__getitem__") else existing

            if contact is None:
                contact = Contact(
                    application_id=application.id,
                    email=email.sender_email,
                    name=chosen_name,
                    role=inferred_role,
                    notes=signature_title,
                )
                session.add(contact)
                await session.commit()
                return

            changed = False
            if chosen_name and not contact.name:
                contact.name = chosen_name
                changed = True
            if inferred_role and not contact.role:
                contact.role = inferred_role
                changed = True
            if signature_title and (not contact.notes or signature_title not in contact.notes):
                contact.notes = signature_title
                changed = True

            if changed:
                session.add(contact)
                await session.commit()

    def _extract_interview_datetime(self, text: str) -> Optional[datetime]:
        compact = re.sub(r"\\s+", " ", text)
        for pattern, format_string in INTERVIEW_DATE_PATTERNS:
            match = pattern.search(compact)
            if not match:
                continue

            try:
                if format_string == "%Y-%m-%d %H:%M":
                    raw = f"{match.group(1)} {match.group(2)}"
                else:
                    month, day, year, time_part = match.groups()
                    month = month[:3].title().replace("Sep", "Sep").replace("Sept", "Sep")
                    raw = f"{month} {day} {year} {time_part.upper().replace('.', '')}"
                return datetime.strptime(raw, format_string)
            except Exception:
                continue

        return None

    def _infer_interview_type(self, text: str) -> Optional[InterviewType]:
        lower = text.lower()
        if "onsite" in lower:
            return InterviewType.ONSITE
        if any(token in lower for token in ("technical interview", "technical screen", "coding interview")):
            return InterviewType.TECHNICAL
        if any(token in lower for token in ("zoom", "google meet", "video interview", "virtual interview")):
            return InterviewType.VIDEO
        if "phone" in lower:
            return InterviewType.PHONE
        return None

    async def _record_interview_details(self, application: Application, email: Email) -> None:
        """Extract interview details from classified interview/assessment emails."""
        if application.id is None:
            return
        if email.classified_as not in {EmailCategory.INTERVIEW, EmailCategory.ASSESSMENT}:
            return

        combined_text = f"{email.subject or ''}\n{email.body_text or ''}"
        scheduled_at = self._extract_interview_datetime(combined_text)
        interview_type = self._infer_interview_type(combined_text)
        note_parts = []
        if email.subject:
            note_parts.append(f"Source email subject: {email.subject}")
        if interview_type is None:
            note_parts.append("Type inferred from content was unavailable.")
        notes = " ".join(note_parts) if note_parts else None

        async with get_session() as session:
            existing_result = await session.exec(
                select(Interview).where(Interview.application_id == application.id)
            )
            existing = [row[0] if hasattr(row, "__getitem__") else row for row in existing_result.all()]

            duplicate = False
            for interview in existing:
                same_time = (
                    scheduled_at is not None
                    and interview.scheduled_at is not None
                    and interview.scheduled_at == scheduled_at
                )
                same_type = interview_type is not None and interview.type == interview_type
                if same_time or (scheduled_at is None and same_type):
                    duplicate = True
                    break

            if duplicate:
                return

            interview = Interview(
                application_id=application.id,
                type=interview_type,
                scheduled_at=scheduled_at,
                notes=notes,
                status=InterviewStatus.SCHEDULED,
            )
            session.add(interview)
            await session.commit()

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
                EmailCategory.PENDING_APPLICATION,
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
                sender_name=email.sender_name,
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
