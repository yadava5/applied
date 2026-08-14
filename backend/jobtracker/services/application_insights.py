"""
Application insight services (ghosting + follow-up suggestions).
"""

# =============================================================================
# UNSCOPED -- DESKTOP ONLY. DO NOT CALL THIS MODULE FROM THE CLOUD APP.
# =============================================================================
#
# Every row read in this module ignores ``user_id``. Cited by symbol, not
# line number, so the citation cannot go stale under an edit:
# ``mark_ghosted_applications`` and ``get_follow_up_reminders`` filter
# ``Application`` on ``status`` alone, sweeping every user's rows --
# and the first of the two then *writes* to the rows it found.
#
# The tables it touches are multi-tenant: ``database/models.py`` gives each
# entity a ``user_id`` FK to ``auth.users``. Reached from the cloud app, each
# read here returns any row whose id a caller can enumerate, regardless of who
# owns it -- the IDOR shape this project has already shipped once.
#
# It is safe today for exactly one reason: it is not mounted. The deployed ASGI
# app is ``api/index.py``, which forces ``JOBTRACKER_DEPLOYMENT=cloud`` and
# serves ``jobtracker.main_cloud``, whose route table holds only the user-scoped
# routers under ``jobtracker.cloud``. That is a property of the deployment, not
# of this file; nothing below defends itself.
#
# ``backend/tests/test_desktop_routers_are_not_mounted.py`` enforces it. It
# builds the deployed app the way Vercel does and fails if any route in it
# resolves to a handler defined under ``jobtracker.api`` or
# ``jobtracker.services``.
#
# If you need one of these endpoints in the cloud, add a user-scoped twin under
# ``jobtracker/cloud/`` (``jobtracker/cloud/applications.py`` is the worked
# example) -- do not mount this one, and do not "just add a filter" here: this
# surface is de-scoped (``apps/macos``, 2026-08-12) and its scoping is untested.
# Issue #73.

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from jobtracker.database import get_session
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
)

logger = logging.getLogger(__name__)

RESPONSE_CATEGORIES = {
    EmailCategory.INTERVIEW,
    EmailCategory.REJECTION,
    EmailCategory.OFFER,
    EmailCategory.ASSESSMENT,
    EmailCategory.FOLLOW_UP,
}

FOLLOW_UP_ELIGIBLE_STATUSES = {
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
}


@dataclass(frozen=True)
class FollowUpReminder:
    """Follow-up suggestion for a stale application."""

    application_id: int
    company: str
    position: str
    status: ApplicationStatus
    days_since_activity: int
    last_activity_at: datetime
    suggested_on: date
    reason: str


def _as_datetime(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


def _unwrap_row(row):
    return row[0] if hasattr(row, "__getitem__") else row


async def mark_ghosted_applications(stale_days: int = 30) -> int:
    """
    Mark stale APPLIED applications as GHOSTED when no response exists.

    Criteria:
    - Status is APPLIED
    - Applied/created timestamp is at least `stale_days` old
    - No linked response-category email (interview/rejection/offer/assessment/follow_up)
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=stale_days)
    marked = 0

    async with get_session() as session:
        result = await session.exec(
            select(Application).where(Application.status == ApplicationStatus.APPLIED)
        )
        applications = [_unwrap_row(row) for row in result.all()]

        for application in applications:
            anchor = _as_datetime(application.applied_date) or application.created_at
            if anchor is None or anchor > cutoff:
                continue

            response_result = await session.exec(
                select(Email.id)
                .where(Email.application_id == application.id)
                .where(Email.classified_as.in_(RESPONSE_CATEGORIES))
                .limit(1)
            )
            has_response = response_result.first() is not None
            if has_response:
                continue

            application.status = ApplicationStatus.GHOSTED
            application.updated_at = now
            session.add(application)
            marked += 1

        if marked > 0:
            await session.commit()

    if marked > 0:
        logger.info("Auto-flagged %s application(s) as ghosted", marked)

    return marked


async def get_follow_up_reminders(
    *,
    stale_days: int = 7,
    ghosted_days: int = 30,
    limit: int = 50,
) -> list[FollowUpReminder]:
    """
    Return follow-up suggestions for stale, non-terminal applications.

    A reminder is generated when:
    - Status is APPLIED or INTERVIEWING
    - Last activity is at least `stale_days` old
    - Last activity is less than `ghosted_days` old
    """
    now = datetime.utcnow()
    reminders: list[FollowUpReminder] = []

    if stale_days < 1:
        stale_days = 1
    if ghosted_days <= stale_days:
        ghosted_days = stale_days + 1

    async with get_session() as session:
        result = await session.exec(
            select(Application).where(Application.status.in_(FOLLOW_UP_ELIGIBLE_STATUSES))
        )
        applications = [_unwrap_row(row) for row in result.all()]

        for application in applications:
            anchor = _as_datetime(application.applied_date) or application.created_at
            if anchor is None:
                continue

            last_email_result = await session.exec(
                select(Email.received_at)
                .where(Email.application_id == application.id)
                .order_by(Email.received_at.desc())
                .limit(1)
            )
            last_email_row = last_email_result.first()
            last_email_at = _unwrap_row(last_email_row) if last_email_row else None

            last_response_result = await session.exec(
                select(Email.received_at)
                .where(Email.application_id == application.id)
                .where(Email.classified_as.in_(RESPONSE_CATEGORIES))
                .order_by(Email.received_at.desc())
                .limit(1)
            )
            last_response_row = last_response_result.first()
            last_response_at = _unwrap_row(last_response_row) if last_response_row else None

            candidates = [anchor]
            if last_email_at is not None:
                candidates.append(last_email_at)
            if last_response_at is not None:
                candidates.append(last_response_at)

            last_activity = max(candidates)
            days_since_activity = (now - last_activity).days

            if days_since_activity < stale_days:
                continue
            if days_since_activity >= ghosted_days:
                continue

            if application.status == ApplicationStatus.APPLIED and last_response_at is None:
                reason = "No recruiter response since you applied."
            elif application.status == ApplicationStatus.INTERVIEWING:
                reason = "No interview updates recently."
            else:
                reason = "No recent application activity."

            reminders.append(
                FollowUpReminder(
                    application_id=application.id,
                    company=application.company,
                    position=application.position,
                    status=application.status,
                    days_since_activity=days_since_activity,
                    last_activity_at=last_activity,
                    suggested_on=(last_activity + timedelta(days=stale_days)).date(),
                    reason=reason,
                )
            )

    reminders.sort(key=lambda item: item.days_since_activity, reverse=True)
    return reminders[:limit]
