"""
Analytics API endpoints.

Provides aggregate statistics and trend data for dashboard charts.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import select

from jobtracker.database import get_session
from jobtracker.database.models import Application, ApplicationStatus, Email, EmailCategory

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsOverviewResponse(BaseModel):
    total_applications: int
    by_status: dict[str, int]
    response_rate: float
    avg_response_days: float | None
    this_week: dict[str, int]


class TrendPoint(BaseModel):
    period_start: str
    applied: int
    rejected: int
    interviews: int
    offers: int


class AnalyticsTrendsResponse(BaseModel):
    period: Literal["weekly", "monthly"]
    months: int
    data: list[TrendPoint]


RESPONSE_CATEGORIES = {
    EmailCategory.INTERVIEW.value,
    EmailCategory.REJECTION.value,
    EmailCategory.OFFER.value,
    EmailCategory.ASSESSMENT.value,
    EmailCategory.FOLLOW_UP.value,
}

TREND_CATEGORIES = {
    EmailCategory.INTERVIEW.value,
    EmailCategory.REJECTION.value,
    EmailCategory.OFFER.value,
}


def _to_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _extract_rows(items):
    return [row[0] if hasattr(row, "__getitem__") else row for row in items]


def _normalized_value(value: object | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value).lower()
    return str(value).lower()


def _period_start(value: date, period: Literal["weekly", "monthly"]) -> date:
    if period == "weekly":
        return value - timedelta(days=value.weekday())
    return value.replace(day=1)


def _next_period(value: date, period: Literal["weekly", "monthly"]) -> date:
    if period == "weekly":
        return value + timedelta(days=7)
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _empty_trend_map(
    period: Literal["weekly", "monthly"],
    start_date: date,
    end_date: date,
) -> dict[str, dict[str, int]]:
    trend_map: dict[str, dict[str, int]] = {}
    bucket = _period_start(start_date, period)
    final_bucket = _period_start(end_date, period)
    while bucket <= final_bucket:
        trend_map[bucket.isoformat()] = {
            "applied": 0,
            "rejected": 0,
            "interviews": 0,
            "offers": 0,
        }
        bucket = _next_period(bucket, period)
    return trend_map


@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def get_analytics_overview() -> AnalyticsOverviewResponse:
    """
    Return high-level analytics for dashboard cards.
    """
    async with get_session() as session:
        applications = _extract_rows((await session.exec(select(Application))).all())
        emails = _extract_rows((await session.exec(select(Email))).all())

    by_status = {status.value: 0 for status in ApplicationStatus}
    for application in applications:
        status_key = _normalized_value(application.status)
        if status_key is None:
            continue
        by_status[status_key] = by_status.get(status_key, 0) + 1

    total_applications = len(applications)

    linked_response_emails = [
        email
        for email in emails
        if email.application_id is not None
        and _normalized_value(email.classified_as) in RESPONSE_CATEGORIES
    ]

    responded_application_ids = {
        email.application_id for email in linked_response_emails if email.application_id is not None
    }
    response_rate = (
        len(responded_application_ids) / total_applications
        if total_applications > 0
        else 0.0
    )

    emails_by_application: dict[int, list[Email]] = defaultdict(list)
    for email in linked_response_emails:
        if email.application_id is not None:
            emails_by_application[email.application_id].append(email)

    response_days: list[int] = []
    for application in applications:
        if application.id is None or application.applied_date is None:
            continue

        candidate_responses = [
            email
            for email in emails_by_application.get(application.id, [])
            if email.received_at is not None
        ]
        if not candidate_responses:
            continue

        first_response = min(candidate_responses, key=lambda e: e.received_at)
        delta_days = (_to_date(first_response.received_at) - application.applied_date).days
        if delta_days >= 0:
            response_days.append(delta_days)

    avg_response_days = (
        round(sum(response_days) / len(response_days), 2)
        if response_days
        else None
    )

    now = datetime.now(UTC).date()
    week_start = now - timedelta(days=now.weekday())

    applied_this_week = sum(
        1 for app in applications if app.applied_date and app.applied_date >= week_start
    )

    responses_received_this_week_ids = {
        email.application_id
        for email in linked_response_emails
        if email.application_id is not None
        and _to_date(email.received_at) is not None
        and _to_date(email.received_at) >= week_start
    }
    interviews_this_week_ids = {
        email.application_id
        for email in linked_response_emails
        if email.application_id is not None
        and _normalized_value(email.classified_as) == EmailCategory.INTERVIEW.value
        and _to_date(email.received_at) is not None
        and _to_date(email.received_at) >= week_start
    }

    return AnalyticsOverviewResponse(
        total_applications=total_applications,
        by_status=by_status,
        response_rate=round(response_rate, 4),
        avg_response_days=avg_response_days,
        this_week={
            "applied": applied_this_week,
            "responses_received": len(responses_received_this_week_ids),
            "interviews_scheduled": len(interviews_this_week_ids),
        },
    )


@router.get("/trends", response_model=AnalyticsTrendsResponse)
async def get_analytics_trends(
    period: Literal["weekly", "monthly"] = Query(default="weekly"),
    months: int = Query(default=3, ge=1, le=24),
) -> AnalyticsTrendsResponse:
    """
    Return trend points for charts.
    """
    async with get_session() as session:
        applications = _extract_rows((await session.exec(select(Application))).all())
        emails = _extract_rows((await session.exec(select(Email))).all())

    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=months * 31)

    trend_map = _empty_trend_map(period, start_date, today)

    for application in applications:
        if application.applied_date and application.applied_date >= start_date:
            key = _period_start(application.applied_date, period).isoformat()
            trend_map[key]["applied"] += 1

    # Count each category once per application per period so one noisy thread
    # does not dominate the chart.
    seen_events: set[tuple[str, int, str]] = set()
    for email in emails:
        received_date = _to_date(email.received_at)
        if received_date is None or received_date < start_date:
            continue
        if email.application_id is None:
            continue

        category = _normalized_value(email.classified_as)
        if category not in TREND_CATEGORIES:
            continue

        key = _period_start(received_date, period).isoformat()
        dedupe_key = (key, email.application_id, category)
        if dedupe_key in seen_events:
            continue
        seen_events.add(dedupe_key)

        bucket = trend_map[key]
        if category == EmailCategory.REJECTION.value:
            bucket["rejected"] += 1
        elif category == EmailCategory.INTERVIEW.value:
            bucket["interviews"] += 1
        elif category == EmailCategory.OFFER.value:
            bucket["offers"] += 1

    points = [
        TrendPoint(
            period_start=key,
            applied=counts["applied"],
            rejected=counts["rejected"],
            interviews=counts["interviews"],
            offers=counts["offers"],
        )
        for key, counts in sorted(trend_map.items(), key=lambda item: item[0])
    ]

    return AnalyticsTrendsResponse(
        period=period,
        months=months,
        data=points,
    )
