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

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_
from sqlmodel import select

from jobtracker.auth import current_user, require_user
from jobtracker.cloud import pipeline
from jobtracker.database import get_session
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Email,
    EmailCategory,
    EmailSource,
    TrainingData,
)

logger = logging.getLogger(__name__)

# When no role can be parsed from the mail metadata we store an EMPTY position
# (rendered as nothing in the UI) — never the literal "Unknown role", which the
# owner saw on every row.
_NO_ROLE = ""

# ``Application.source`` doubles as an origin+ownership tag so a re-sync can
# safely REPLACE the Gmail-derived pipeline while preserving anything the user
# touched:
#   - ``gmail``      : auto-derived from mail — purgeable, sync may advance it.
#   - ``gmail_user`` : auto-derived but the user set its status — STICKY.
#   - ``manual``     : hand-filed by the user — STICKY, never auto-touched.
# Any other/legacy value is treated as user-owned (preserved) out of caution.
SOURCE_GMAIL_AUTO = "gmail"
SOURCE_GMAIL_USER = "gmail_user"
SOURCE_MANUAL = "manual"


def _is_auto_row(source: str | None) -> bool:
    """Only rows explicitly tagged as unedited Gmail-auto are purge/advance-able."""

    return source == SOURCE_GMAIL_AUTO


# ApplicationStatus → the training label a manual correction should teach the
# classifier (the SetFit retrain path reads ``training_data``).
_STATUS_TO_TRAINING_LABEL: dict[ApplicationStatus, EmailCategory] = {
    ApplicationStatus.APPLIED: EmailCategory.APPLIED,
    ApplicationStatus.INTERVIEWING: EmailCategory.INTERVIEW,
    ApplicationStatus.OFFERED: EmailCategory.OFFER,
    ApplicationStatus.ACCEPTED: EmailCategory.OFFER,
    ApplicationStatus.REJECTED: EmailCategory.REJECTION,
    ApplicationStatus.WITHDRAWN: EmailCategory.OTHER,
    ApplicationStatus.GHOSTED: EmailCategory.OTHER,
}


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
    notes: str | None = None


class CloudApplicationResponse(BaseModel):
    """Minimal response model — matches what downstream C11+ needs."""

    id: int
    user_id: str
    company: str
    position: str
    status: ApplicationStatus
    notes: str | None = None
    created_at: str
    # ``applied_date`` is the real date the application mail was received (from
    # the email, never now()) — the board shows this, not the row's created_at.
    applied_date: str | None = None
    # Origin/ownership tag (gmail / gmail_user / manual) so the UI can show a
    # "from Gmail" badge and know which rows are user-owned.
    source: str | None = None
    # Gmail deep link to the underlying conversation (click-through), if known.
    url: str | None = None


class ApplicationStatusUpdate(BaseModel):
    """Body for a user's status correction (PATCH /applications/{id})."""

    status: ApplicationStatus


class MessageRefResponse(BaseModel):
    """One underlying email surfaced in the click-through detail view."""

    message_id: str
    thread_id: str | None = None
    subject: str | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    received_at: str | None = None
    snippet: str | None = None
    category: str | None = None
    confidence: float | None = None
    gmail_link: str | None = None


class ApplicationDetailResponse(BaseModel):
    """An application plus the metadata-only mail it was derived from."""

    application: CloudApplicationResponse
    messages: list[MessageRefResponse]


class ReviewItemResponse(BaseModel):
    """One needs-classification queue entry (an uncertain verdict)."""

    message_id: str
    thread_id: str | None = None
    subject: str | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    received_at: str | None = None
    snippet: str | None = None
    confidence: float | None = None
    gmail_link: str | None = None


class ReviewQueueResponse(BaseModel):
    """The needs-classification queue for the authenticated user."""

    items: list[ReviewItemResponse]
    total: int


class ReviewClassifyRequest(BaseModel):
    """Body for classifying a review item into a category."""

    category: EmailCategory


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
    # Uncertain verdicts awaiting a human decision — the live source for the
    # dashboard's "N need classification" number (previously a dead count).
    needs_review: int = 0


async def _find_application_by_token(
    session, user_id: uuid.UUID, token: str
) -> Application | None:
    """Locate one user's application row for a normalized company token."""

    return (
        await session.exec(
            select(Application)
            .where(
                Application.user_id == user_id,
                func.lower(Application.company) == token,
            )
            .limit(1)
        )
    ).first()


async def _persist_message_refs(
    session,
    user_id: uuid.UUID,
    application_id: int | None,
    refs,
) -> None:
    """Upsert metadata-only Email rows for a set of message refs (no bodies).

    Idempotent on ``message_id`` (globally unique): a re-sync updates the link
    and classification rather than duplicating. Undated messages are skipped —
    the Email row requires a receive time and we never fabricate one. Linking to
    ``application_id`` is what powers the click-through detail view; leaving it
    ``None`` (for review items) is what powers the needs-classification queue.
    """

    for ref in refs:
        if ref.received_at is None:
            continue
        existing = (
            await session.exec(
                select(Email)
                .where(
                    Email.user_id == user_id,
                    Email.message_id == ref.message_id,
                )
                .limit(1)
            )
        ).first()
        category = _safe_category(ref.category)
        if existing is not None:
            existing.application_id = application_id
            existing.subject = ref.subject or existing.subject
            existing.sender_name = ref.sender_name
            existing.sender_email = ref.sender_email
            existing.body_snippet = (ref.snippet or "")[:500]
            existing.classified_as = category
            existing.classification_confidence = ref.confidence
            existing.classification_method = "rules"
            existing.thread_id = ref.thread_id
            session.add(existing)
        else:
            session.add(
                Email(
                    user_id=user_id,
                    application_id=application_id,
                    source_account=EmailSource.GMAIL,
                    message_id=ref.message_id,
                    thread_id=ref.thread_id,
                    subject=ref.subject,
                    sender_name=ref.sender_name,
                    sender_email=ref.sender_email,
                    received_at=ref.received_at,
                    body_snippet=(ref.snippet or "")[:500],
                    classified_as=category,
                    classification_confidence=ref.confidence,
                    classification_method="rules",
                )
            )


def _safe_category(value: str) -> EmailCategory | None:
    try:
        return EmailCategory(value)
    except ValueError:
        return None


async def upsert_applications_for_user(
    session,
    user_id: uuid.UUID,
    rolled: list[pipeline.RolledApplication],
) -> tuple[int, int]:
    """Idempotently persist rolled-up applications for one user.

    For each company (keyed by the normalized ``company_token``) it updates the
    existing row or inserts a new one — scoped strictly to ``user_id`` from the
    verified JWT, never a client-supplied id. Re-running with the same input
    creates no duplicates: the match is ``lower(company) == company_token``.

    Stickiness: a mail signal only advances an AUTO row (``source == 'gmail'``).
    A row the user created or corrected (manual / gmail_user) keeps its status
    untouched forever — the re-sync attaches fresh mail refs and fills an empty
    role, but never rewrites a human decision. Returns ``(created, updated)``.
    """

    created = 0
    updated = 0
    for r in rolled:
        existing = await _find_application_by_token(session, user_id, r.company_token)
        deeplink = _rolled_deeplink(r)

        if existing is not None:
            if _is_auto_row(existing.source):
                new_status = ApplicationStatus(
                    pipeline.advance_application_status(existing.status.value, r.status)
                )
                if new_status != existing.status:
                    existing.status = new_status
            if r.role and not existing.position:
                existing.position = r.role
            if r.applied_at and existing.applied_date is None:
                existing.applied_date = r.applied_at.date()
            if deeplink and not existing.url:
                existing.url = deeplink
            existing.updated_at = datetime.utcnow()
            session.add(existing)
            await session.flush()
            await _persist_message_refs(session, user_id, existing.id, r.messages)
            updated += 1
        else:
            app = Application(
                user_id=user_id,
                company=r.company_display,
                position=r.role or _NO_ROLE,
                status=ApplicationStatus(r.status),
                applied_date=r.applied_at.date() if r.applied_at else None,
                source=SOURCE_GMAIL_AUTO,
                url=deeplink,
            )
            session.add(app)
            await session.flush()
            await _persist_message_refs(session, user_id, app.id, r.messages)
            created += 1

    await session.commit()
    return created, updated


def _rolled_deeplink(r: pipeline.RolledApplication) -> str | None:
    """Gmail deep link for a rolled row's most-recent message, if any."""

    if not r.messages:
        return None
    primary = r.messages[0]
    return pipeline.gmail_deeplink(
        thread_id=primary.thread_id, message_id=primary.message_id
    )


async def _reset_review_queue(session, user_id: uuid.UUID) -> None:
    """Delete the user's prior UNreviewed Gmail review items (rebuilt each sync).

    Only unlinked (``application_id IS NULL``), un-reviewed, gmail-sourced rows
    are cleared — a review item the user already classified became a real
    application (linked) or was marked reviewed, and is preserved.
    """

    await session.exec(
        sa_delete(Email).where(
            Email.user_id == user_id,
            Email.source_account == EmailSource.GMAIL,
            Email.application_id.is_(None),
            Email.is_reviewed == False,  # noqa: E712 — SQL boolean, not identity
        )
    )


async def _persist_review_items(session, user_id: uuid.UUID, review) -> int:
    """Persist uncertain verdicts as unlinked needs-review Email rows.

    Returns the number of items surfaced to the queue (dated items only).
    """

    refs = [
        pipeline.MessageRef(
            message_id=item.message_id,
            thread_id=item.thread_id,
            subject=item.subject,
            sender_email=item.sender_email,
            sender_name=item.sender_name,
            received_at=item.received_at,
            category="needs_review",
            confidence=item.confidence,
            snippet="",
        )
        for item in review
    ]
    await _persist_message_refs(session, user_id, None, refs)
    return sum(1 for r in refs if r.received_at is not None)


async def purge_and_rebuild_gmail_pipeline(
    session,
    user_id: uuid.UUID,
    rolled: list[pipeline.RolledApplication],
    review: list,
) -> tuple[int, int, int, int]:
    """REPLACE the Gmail-derived pipeline for one user, preserving edits.

    This is what a re-sync runs so the owner's 21 garbage rows are wiped and the
    board is rebuilt from the corrected rollup. It:

      1. Deletes AUTO rows (``source == 'gmail'``) whose company is no longer in
         the freshly-rolled set — i.e. the stale noise — along with their emails.
      2. Upserts the fresh rolled set (continuing companies keep their id and
         filed date; new ones are inserted).
      3. Rebuilds the needs-classification queue from the review items.

    Manual and user-corrected rows (and anything the user classified) are never
    touched. Idempotent and user-scoped. Returns
    ``(created, updated, purged, needs_review)``.
    """

    keep_tokens = {r.company_token for r in rolled}

    auto_rows = (
        await session.exec(
            select(Application).where(
                Application.user_id == user_id,
                Application.source == SOURCE_GMAIL_AUTO,
            )
        )
    ).all()

    purged = 0
    for row in auto_rows:
        if row.company.lower() in keep_tokens:
            continue
        await session.exec(
            sa_delete(Email).where(
                Email.user_id == user_id, Email.application_id == row.id
            )
        )
        await session.delete(row)
        purged += 1
    await session.flush()

    created, updated = await upsert_applications_for_user(session, user_id, rolled)

    await _reset_review_queue(session, user_id)
    needs_review = await _persist_review_items(session, user_id, review)

    await session.commit()
    return created, updated, purged, needs_review


async def _add_training_example(
    session,
    user_id: uuid.UUID,
    email: Email | None,
    label: EmailCategory,
    *,
    subject: str = "",
    body: str = "",
) -> None:
    """Record a user correction in ``training_data`` (the SetFit retrain path).

    Cloud-safe: writes the row directly instead of routing through
    ``HybridClassifier.add_correction`` (which would lazy-import torch /
    sentence-transformers / setfit and blow the serverless budget). Desktop
    SetFit retraining reads exactly this table. Idempotent on ``email_id``.
    """

    email_id = email.id if email is not None else None
    subj = (email.subject if email is not None else subject) or subject
    text = (email.body_snippet if email is not None else body) or body

    existing = None
    if email_id is not None:
        existing = (
            await session.exec(
                select(TrainingData)
                .where(
                    TrainingData.user_id == user_id,
                    TrainingData.email_id == email_id,
                )
                .limit(1)
            )
        ).first()

    if existing is not None:
        existing.label = label.value
        existing.subject = subj
        existing.body_text = text
        existing.source = "user_correction"
        session.add(existing)
    else:
        session.add(
            TrainingData(
                user_id=user_id,
                email_id=email_id,
                label=label.value,
                subject=subj,
                body_text=text,
                source="user_correction",
            )
        )


async def record_status_correction(
    session,
    user_id: uuid.UUID,
    application_id: int,
    new_status: ApplicationStatus,
) -> Application | None:
    """Apply a user's status correction and TRAIN the model from it.

    Makes the status STICKY (tags the row user-owned so future syncs never
    overwrite it) and, for every linked email, writes a training example
    labelled with the category implied by the new status. Scoped to the owner;
    returns the updated row or None when it does not exist for this user.
    """

    app = (
        await session.exec(
            select(Application).where(
                Application.user_id == user_id, Application.id == application_id
            )
        )
    ).first()
    if app is None:
        return None

    app.status = new_status
    if _is_auto_row(app.source):
        app.source = SOURCE_GMAIL_USER  # gmail-derived but now user-settled
    app.updated_at = datetime.utcnow()
    session.add(app)

    label = _STATUS_TO_TRAINING_LABEL.get(new_status)
    if label is not None:
        emails = (
            await session.exec(
                select(Email).where(
                    Email.user_id == user_id, Email.application_id == application_id
                )
            )
        ).all()
        for email in emails:
            email.user_corrected = True
            email.is_reviewed = True
            session.add(email)
            await _add_training_example(session, user_id, email, label)

    await session.commit()
    await session.refresh(app)
    return app


async def dismiss_application(
    session, user_id: uuid.UUID, application_id: int
) -> bool:
    """Mark a row 'not an application' — remove it and teach the model it was noise.

    Records each linked email as an ``other`` training example (so the classifier
    learns it was wrongly filed), then deletes the emails and the row. Scoped to
    the owner. Returns False when the row does not exist for this user.
    """

    app = (
        await session.exec(
            select(Application).where(
                Application.user_id == user_id, Application.id == application_id
            )
        )
    ).first()
    if app is None:
        return False

    emails = (
        await session.exec(
            select(Email).where(
                Email.user_id == user_id, Email.application_id == application_id
            )
        )
    ).all()
    for email in emails:
        await _add_training_example(
            session, user_id, email, EmailCategory.OTHER
        )
    for email in emails:
        await session.delete(email)

    await session.delete(app)
    await session.commit()
    return True


async def delete_application(
    session, user_id: uuid.UUID, application_id: int
) -> bool:
    """Hard-delete an application and its linked emails. Scoped to the owner."""

    app = (
        await session.exec(
            select(Application).where(
                Application.user_id == user_id, Application.id == application_id
            )
        )
    ).first()
    if app is None:
        return False
    await session.exec(
        sa_delete(Email).where(
            Email.user_id == user_id, Email.application_id == application_id
        )
    )
    await session.delete(app)
    await session.commit()
    return True


async def classify_review_item(
    session,
    user_id: uuid.UUID,
    message_id: str,
    category: EmailCategory,
) -> dict[str, object]:
    """Classify a needs-review email into a category — persist + train.

    Marks the email reviewed, records a training example, and — when the chosen
    category is a real lifecycle stage with a nameable employer — creates (or
    advances) a STICKY, user-owned application from it. Scoped to the owner.
    """

    email = (
        await session.exec(
            select(Email).where(
                Email.user_id == user_id, Email.message_id == message_id
            )
        )
    ).first()
    if email is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Review item not found.")

    email.classified_as = category
    email.is_reviewed = True
    email.user_corrected = True

    result: dict[str, object] = {"classified_as": category.value, "application_id": None}

    status_value = _lifecycle_to_status(category)
    employer = pipeline.resolve_employer(
        email.sender_email or "", email.subject or "", email.sender_name
    )
    if status_value is not None and employer is not None:
        token, display = employer
        app = await _find_application_by_token(session, user_id, token)
        if app is None:
            app = Application(
                user_id=user_id,
                company=display,
                position=_NO_ROLE,
                status=ApplicationStatus(status_value),
                applied_date=email.received_at.date() if email.received_at else None,
                source=SOURCE_GMAIL_USER,  # human-classified → sticky
                url=pipeline.gmail_deeplink(
                    thread_id=email.thread_id, message_id=email.message_id
                ),
            )
            session.add(app)
            await session.flush()
        else:
            app.source = SOURCE_GMAIL_USER
            app.status = ApplicationStatus(status_value)
            session.add(app)
        email.application_id = app.id
        result["application_id"] = app.id

    session.add(email)
    await _add_training_example(session, user_id, email, category)
    await session.commit()
    return result


def _lifecycle_to_status(category: EmailCategory) -> str | None:
    """Map a lifecycle email category to an ApplicationStatus value, or None."""

    mapping = {
        EmailCategory.APPLIED: "applied",
        EmailCategory.PENDING_APPLICATION: "applied",
        EmailCategory.ASSESSMENT: "interviewing",
        EmailCategory.INTERVIEW: "interviewing",
        EmailCategory.OFFER: "offered",
        EmailCategory.REJECTION: "rejected",
    }
    return mapping.get(category)


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
        applied_date=app.applied_date.isoformat() if app.applied_date else None,
        source=app.source,
        url=app.url,
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
    status: ApplicationStatus | None = Query(
        None, description="Filter to a single application status."
    ),
    company: str | None = Query(
        None, description="Case-insensitive substring match on company."
    ),
    search: str | None = Query(
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

        needs_review = (
            await session.exec(
                select(func.count())
                .select_from(Email)
                .where(
                    Email.user_id == user_id,
                    Email.classified_as == EmailCategory.NEEDS_REVIEW,
                    Email.application_id.is_(None),
                    Email.is_reviewed == False,  # noqa: E712
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
        needs_review=needs_review,
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
            source=SOURCE_MANUAL,  # hand-filed → sticky, never auto-touched
        )
        session.add(app)
        await session.commit()
        await session.refresh(app)

    return _serialize(app)


def _message_ref_response(email: Email) -> MessageRefResponse:
    return MessageRefResponse(
        message_id=email.message_id,
        thread_id=email.thread_id,
        subject=email.subject,
        sender_name=email.sender_name,
        sender_email=email.sender_email,
        received_at=email.received_at.isoformat() if email.received_at else None,
        snippet=email.body_snippet,
        category=email.classified_as.value if email.classified_as else None,
        confidence=email.classification_confidence,
        gmail_link=pipeline.gmail_deeplink(
            thread_id=email.thread_id, message_id=email.message_id
        ),
    )


@router.get("/review", response_model=ReviewQueueResponse)
async def review_queue_cloud(
    user_id: uuid.UUID = Depends(current_user),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
) -> ReviewQueueResponse:
    """The needs-classification queue: uncertain verdicts awaiting a decision.

    These are the metadata-only Email rows the sync flagged ``needs_review``
    (unlinked, un-reviewed) — the real target of the dashboard's "N need
    classification" number, which is otherwise a dead count. Newest-first.
    """

    async with get_session() as session:
        rows = (
            await session.exec(
                select(Email)
                .where(
                    Email.user_id == user_id,
                    Email.classified_as == EmailCategory.NEEDS_REVIEW,
                    Email.application_id.is_(None),
                    Email.is_reviewed == False,  # noqa: E712
                )
                .order_by(Email.received_at.desc())
                .limit(limit)
            )
        ).all()

    items = [
        ReviewItemResponse(
            message_id=e.message_id,
            thread_id=e.thread_id,
            subject=e.subject,
            sender_name=e.sender_name,
            sender_email=e.sender_email,
            received_at=e.received_at.isoformat() if e.received_at else None,
            snippet=e.body_snippet,
            confidence=e.classification_confidence,
            gmail_link=pipeline.gmail_deeplink(
                thread_id=e.thread_id, message_id=e.message_id
            ),
        )
        for e in rows
    ]
    return ReviewQueueResponse(items=items, total=len(items))


@router.post("/review/{message_id}/classify", response_model=dict)
async def classify_review_item_cloud(
    message_id: str,
    data: ReviewClassifyRequest,
    user_id: uuid.UUID = Depends(current_user),
) -> dict[str, object]:
    """Classify a review item into a category — persists the decision + trains.

    A lifecycle category with a nameable employer becomes a sticky, user-owned
    application; every choice records a training example (SetFit retrain path).
    """

    async with get_session() as session:
        return await classify_review_item(session, user_id, message_id, data.category)


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
async def application_detail_cloud(
    application_id: int,
    user_id: uuid.UUID = Depends(current_user),
) -> ApplicationDetailResponse:
    """One application plus the underlying (metadata-only) mail — click-through.

    Powers the detail view: subject / sender / date / snippet per message and a
    Gmail deep link to open the real conversation. Scoped to the owner (404 for
    anyone else's row).
    """

    async with get_session() as session:
        app = (
            await session.exec(
                select(Application).where(
                    Application.user_id == user_id, Application.id == application_id
                )
            )
        ).first()
        if app is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Application not found."
            )
        emails = (
            await session.exec(
                select(Email)
                .where(
                    Email.user_id == user_id,
                    Email.application_id == application_id,
                )
                .order_by(Email.received_at.desc())
            )
        ).all()
        serialized = _serialize(app)

    return ApplicationDetailResponse(
        application=serialized,
        messages=[_message_ref_response(e) for e in emails],
    )


@router.patch("/{application_id}", response_model=CloudApplicationResponse)
async def update_application_status_cloud(
    application_id: int,
    data: ApplicationStatusUpdate,
    user_id: uuid.UUID = Depends(current_user),
) -> CloudApplicationResponse:
    """Apply a user's status correction — makes it sticky AND trains the model.

    The new status is honoured verbatim (a human decision, not the advance-only
    guard) and future syncs will never overwrite it. Every linked email becomes
    a training example. 404 when the row is not the caller's.
    """

    async with get_session() as session:
        app = await record_status_correction(
            session, user_id, application_id, data.status
        )
    if app is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Application not found."
        )
    return _serialize(app)


@router.post("/{application_id}/dismiss", response_model=dict)
async def dismiss_application_cloud(
    application_id: int,
    user_id: uuid.UUID = Depends(current_user),
) -> dict[str, object]:
    """'Not an application / dismiss' — remove the row + train it was misfiled."""

    async with get_session() as session:
        ok = await dismiss_application(session, user_id, application_id)
    if not ok:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Application not found."
        )
    return {"dismissed": True}


@router.delete("/{application_id}", response_model=dict)
async def delete_application_cloud(
    application_id: int,
    user_id: uuid.UUID = Depends(current_user),
) -> dict[str, object]:
    """Hard-delete an application (and its linked emails). Scoped to the owner."""

    async with get_session() as session:
        ok = await delete_application(session, user_id, application_id)
    if not ok:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Application not found."
        )
    return {"deleted": True}
