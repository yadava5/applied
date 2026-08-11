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
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple

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
    APPLICATION_STATUSES,
    CATEGORY_TO_STATUS,
    DEFAULT_APPLICATION_STATUS,
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

# Who set a deadline. A `user` one is a decision and the sync never overwrites
# it; a `mail` one is a reading of the latest message that stated a date, and a
# newer message may legitimately supersede it.
DUE_FROM_USER = "user"
DUE_FROM_MAIL = "mail"

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

# ``Application.dismissed_reason`` — WHO removed a row from the board. Nothing
# here is a delete: a dismissed row and its emails stay on disk and can be
# restored. The distinction matters on the next sync:
#   - ``user``   : a human said "this is not an application". Fresh mail must
#                  NOT argue with that, so the row stays dismissed.
#   - ``resync`` : the rebuild removed it automatically. Fresh mail naming the
#                  same company is better evidence than the removal was, so the
#                  row comes back.
DISMISSED_BY_USER = "user"
DISMISSED_BY_RESYNC = "resync"


def _is_auto_row(source: str | None) -> bool:
    """Only rows explicitly tagged as unedited Gmail-auto are purge/advance-able."""

    return source == SOURCE_GMAIL_AUTO


class RemovedApplication(NamedTuple):
    """One row a rebuild took off the board — named so the UI can say which."""

    id: int
    company: str


class MergeResult(NamedTuple):
    """What one merge of a scan into the board actually did.

    ``purged`` counts rows the rebuild removed; ``removed`` names them. They are
    populated from exactly the same rows, so the button can report "3 filed, 2
    removed (MotherDuck, Supabase)" instead of silently changing the board —
    and can offer an undo, because a removal is now a reversible state.
    """

    created: int
    updated: int
    purged: int
    needs_review: int
    removed: tuple[RemovedApplication, ...] = ()


@dataclass(frozen=True)
class ScanCoverage:
    """What one scan can HONESTLY be said to have looked at.

    A Gmail scan is bounded three ways at once — by ``in:inbox`` vs
    ``in:anywhere``, by ``newer_than:<N>m``, and by a message/page cap — so the
    set of messages it returns is never the set of messages that exist. This
    records the part that is actually knowable:

    - ``message_ids`` — the messages the scan demonstrably READ. Nothing else
      about the mailbox is observable from a scan.
    - ``oldest`` / ``newest`` — the span those messages occupy. Derived from the
      data rather than from the requested ``range``, because a scan truncated by
      the message cap covers far less than the range it asked for, and Gmail
      returns newest-first so the truncation is always at the old end.

    All instants are naive UTC to match ``Email.received_at`` (the column is
    TIMESTAMP WITHOUT TIME ZONE), so an aware timestamp relayed by a client can
    never raise "can't compare offset-naive and offset-aware datetimes" in the
    middle of a purge.
    """

    message_ids: frozenset[str]
    oldest: datetime | None = None
    newest: datetime | None = None

    @classmethod
    def from_items(cls, items) -> ScanCoverage:
        """Build coverage from the classified messages one scan returned.

        Takes ALL scanned items, not just the ones that rolled up: a message the
        scan re-read and classified as noise is precisely the evidence that
        contradicts a stale row, and it appears in neither the rolled set nor
        the review queue.
        """

        ids: set[str] = set()
        dates: list[datetime] = []
        for item in items:
            message_id = getattr(item, "message_id", None)
            if message_id:
                ids.add(message_id)
            received_at = pipeline.to_naive_utc(getattr(item, "received_at", None))
            if received_at is not None:
                dates.append(received_at)
        return cls(
            message_ids=frozenset(ids),
            oldest=min(dates) if dates else None,
            newest=max(dates) if dates else None,
        )

    def covers(self, received_at: datetime | None) -> bool:
        """Was this instant inside the span the scan actually reached?"""

        moment = pipeline.to_naive_utc(received_at)
        if moment is None or self.oldest is None or self.newest is None:
            return False
        return self.oldest <= moment <= self.newest


def _scan_contradicts(emails: list[Email], coverage: ScanCoverage | None) -> bool:
    """Did this scan READ a row's own evidence and disagree with it?

    The one honest test for "this application is stale". The caller has already
    established that the freshly-rolled set does not name the row's company;
    that on its own is worth nothing, because a scan that cannot see a message
    reports the same emptiness as a mailbox that no longer contains it. What
    turns silence into evidence is the scan having re-read the very messages the
    row was filed from and no longer concluding an application from them — a
    classifier correction, which is the case the rebuild exists to clean up.

    Three ways a row survives, each one a thing the scan cannot prove:

    1. No coverage at all (an empty scan) — it observed nothing.
    2. No linked email — there is no evidence to re-read, so staleness is
       unprovable by construction. (Includes rows filed before this column
       existed and rows whose mail was pruned.)
    3. ANY linked email whose id is missing from what the scan returned. The
       test is MEMBERSHIP, not dates: a scan that read one of a row's messages
       has read one of a row's messages, and the rest are as unobserved as they
       would be after an empty scan.

    Why membership rather than the date span
    ----------------------------------------

    This used to accept "every email falls between the oldest and newest thing
    the scan returned" as proof the scan had covered them. It is not. An
    ARCHIVED message sits at a date like any other, so a scan that could never
    return it (``in:inbox``, or any bounded window) still reports its date as
    "covered" — which is how the 2026-08-10 rebuild concluded it had re-read
    mail it had not, and removed two real applications.

    The span clause is KEPT, as the stricter half of an AND, not as the test.
    It still refuses one case membership alone would allow: a message whose id
    the scan returned but whose ``Date`` header it could not parse contributes
    an id and no date, so a row dated outside everything the scan DID date is
    removable by membership and blocked here. Blocking a removal is the safe
    direction, so the conjunction stands.
    """

    if coverage is None or not emails:
        return False
    if not all(e.message_id in coverage.message_ids for e in emails):
        return False
    return all(coverage.covers(e.received_at) for e in emails)


# ApplicationStatus → the training label a manual correction should teach the
# classifier (the SetFit retrain path reads ``training_data``). Must name EVERY
# status: a status missing here is a correction that silently trains nothing,
# so ``test_status_vocabulary`` fails if the enum grows and this does not.
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
    """Request body for the cloud POST /applications endpoint.

    ``applied_date`` and ``url`` mirror the names :class:`CloudApplicationResponse`
    emits, so a hand-filed row round-trips through the same keys it came back
    under. Before they existed the dialog collected both and the API dropped
    both, and the web form worked around it by stringifying them into ``notes``.

    ``applied_date`` is an ISO-8601 date — ``YYYY-MM-DD``, what the response
    returns. A full ISO datetime (``2026-08-10T14:03:00Z``, i.e. what
    ``Date.toISOString()`` produces) is accepted and truncated to its date;
    anything else is REJECTED with a 422 rather than silently dropped, which is
    the failure being fixed.
    """

    company: str
    position: str
    status: ApplicationStatus = ApplicationStatus.APPLIED
    notes: str | None = None
    applied_date: str | None = None
    url: str | None = None


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
    # Set only on a row that has been taken OFF the board (never deleted), with
    # who took it off — ``user`` or ``resync``. Live rows carry nulls. Lets the
    # UI render an "removed by re-sync — undo" affordance over ?dismissed=true.
    dismissed_at: str | None = None
    dismissed_reason: str | None = None
    # When something is due on this application, and who said so. Both null
    # together — a deadline with no origin would be a claim nobody made.
    due_at: str | None = None
    due_source: str | None = None


class ApplicationStatusUpdate(BaseModel):
    """Body for a user's status correction (PATCH /applications/{id})."""

    status: ApplicationStatus


class ApplicationDeadlineUpdate(BaseModel):
    """Body for setting or clearing an application's deadline.

    ``None`` clears it. There is deliberately no separate delete endpoint: set
    and clear are the same decision, and splitting them invites a UI that offers
    one without the other.
    """

    due_at: datetime | None = None


class StatusVocabularyResponse(BaseModel):
    """The canonical stage vocabulary, served so no client has to restate it.

    Every field is DERIVED from :class:`ApplicationStatus` /
    :data:`CATEGORY_TO_STATUS` at import time, so this endpoint and the 422 a
    bad ``PATCH`` earns cannot disagree. It exists because they did: the board
    offered ``assessment``, the file-by-hand dialog offered six of the seven,
    and the API accepted a different seven.

    - ``statuses`` — the settable stages, in lifecycle order. THE list.
    - ``default`` — what a new row starts at.
    - ``category_to_status`` — how a classifier verdict maps onto a stage, for
      a client that wants to show ``assessment`` mail under ``interviewing``.
      A category absent from this map asserts no stage.
    - ``classifier_categories`` — everything the classifier can emit. A
      SUPERSET of the mapping's keys and NOT interchangeable with ``statuses``;
      confusing the two is the original defect.
    """

    statuses: list[str]
    default: str
    category_to_status: dict[str, str]
    classifier_categories: list[str]


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


class SplitCandidateResponse(BaseModel):
    """One application hiding inside a row that was filed before identity existed."""

    role: str | None = None
    req_id: str | None = None
    message_ids: list[str]
    # True for the cluster that would KEEP this row's id (and everything hanging
    # off it) if the user accepts the split. Exactly one candidate has it.
    retains_row: bool = False


class ApplicationDetailResponse(BaseModel):
    """An application plus the metadata-only mail it was derived from."""

    application: CloudApplicationResponse
    messages: list[MessageRefResponse]
    # Present (length >= 2) only when this row's OWN linked mail describes more
    # than one application — a row merged before applications were told apart
    # within an employer. Empty is the normal case and means nothing to offer.
    split_candidates: list[SplitCandidateResponse] = []


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
    """Body for classifying a review item into a category.

    ``company`` is optional and only consulted when the pipeline cannot name the
    employer from the mail itself. That is the second half of the round trip the
    ``needs_employer`` response opens: the caller is told what is missing and
    re-sends the same classification with the company filled in.

    ``application_id`` is the user answering "which of these is it about?". An
    employer can hold several applications, and a message that names no role —
    "Update on your application" — belongs to exactly one of them without saying
    which. The board asks; this carries the answer. Ignored when the id is not
    the caller's own row, or not at the employer the mail names.
    """

    category: EmailCategory
    company: str | None = None
    application_id: int | None = None


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
    """Locate one user's application row for a normalized company token.

    Matching is by TOKEN on both sides (:func:`pipeline.matches_company_token`),
    not by ``lower(company) == token``. The stored side is a display name and
    the rolled side is a match key; for any company whose display name is more
    than one word they are simply different strings, so the lookup missed, the
    upsert inserted, and the board grew a second row per sync. "Together AI"
    (applications 64 and 65, 2026-08-11) is that bug in production; "Anthropic"
    never showed it because a one-word name happens to be its own token.

    Two queries, so the common case stays index-assisted: exact equality first,
    then a prefix scan over the leading normalized word, confirmed in Python.
    The prefix is a superset of what can match, save for a display name that
    starts with punctuation — those fall back to inserting a row, which is the
    old behaviour and not a regression.

    ORDER MATTERS: a LIVE row before a dismissed one (a dismissed duplicate must
    not shadow the row actually on the board), then oldest first. That is what
    makes "the second sync updates the first row" a property rather than luck —
    without it the winner is whatever the database happened to return.
    """

    live_first = (
        Application.dismissed_at.is_(None).desc(),
        Application.created_at.asc(),
        Application.id.asc(),
    )

    rows = await _company_rows(session, user_id, token)
    return rows[0] if rows else None


async def _company_rows(session, user_id: uuid.UUID, token: str) -> list[Application]:
    """Every one of this user's applications at the employer named by ``token``.

    One employer can now hold several applications, so the lookup returns the
    whole set and :func:`_resolve_application` decides which one a given piece of
    mail belongs to. The single-row ``.first()`` this replaced silently picked
    one of four Amazon rows and let the other three drift.

    Two queries, so the common case stays index-assisted: exact equality first,
    then a prefix scan over the leading normalized word, confirmed in Python.
    """

    live_first = (
        Application.dismissed_at.is_(None).desc(),
        Application.created_at.asc(),
        Application.id.asc(),
    )

    # BOTH queries, unioned — never "exact first, and stop if it found anything".
    #
    # That early return is how the owner's board grew six rows each for "IXL
    # Learning" and "Torc Robotics". A stored row named exactly "IXL" answered the
    # exact query for token `ixl`, so the four rows named "IXL Learning" — which
    # match the same token and are the same employer — were never returned. The
    # resolver then saw one row where there were five, and every rebuild minted
    # another. Renaming a row (which the sync now does when the resolver's naming
    # improves) is exactly what makes the two sets diverge, so the two changes
    # were unsafe together and only the second one showed it.
    seen: dict[int, Application] = {}

    exact = (
        await session.exec(
            select(Application)
            .where(
                Application.user_id == user_id,
                func.lower(Application.company) == token,
            )
            .order_by(*live_first)
        )
    ).all()
    for row in exact:
        seen[row.id] = row

    prefix = pipeline.normalize_company_name(token).split(" ")[0]
    if prefix:
        candidates = (
            await session.exec(
                select(Application)
                .where(
                    Application.user_id == user_id,
                    func.lower(Application.company).like(f"{prefix}%"),
                )
                .order_by(*live_first)
            )
        ).all()
        for row in candidates:
            if row.id not in seen and pipeline.matches_company_token(row.company, token):
                seen[row.id] = row

    # Re-apply the ordering across the union: a live row before a dismissed one
    # (a dismissed duplicate must never shadow the row actually on the board),
    # then oldest first. Without this the adoption target would depend on which
    # query happened to find a row, which is how "the second sync updates the
    # first row" stops being a property and becomes luck.
    return sorted(
        seen.values(),
        key=lambda row: (
            row.dismissed_at is not None,
            row.created_at or datetime.max,
            row.id or 0,
        ),
    )


async def _resolve_application(
    session,
    user_id: uuid.UUID,
    rolled: pipeline.RolledApplication,
) -> Application | None:
    """Which stored application, if any, this rolled cluster is — or None to mint.

    The employer narrows the field; these rules pick the row inside it. They are
    the persistent mirror of :func:`pipeline.partition_applications`, and the
    order is the whole point:

    1. **Requisition id.** The employer's own number. Nothing outranks it.
    2. **Role token.** The normalized title.
    3. **A row that has no identity yet** — one minted before applications were
       told apart within an employer — is ADOPTED by the cluster, in place, so
       the migration keeps the row id and everything hanging off it. Only when
       it is the sole such row: with two anonymous rows there is no way to know
       which is which, and guessing would move a user's status onto the wrong
       application.
    4. **A cluster that names no role at all** joins the employer's only row if
       there is exactly one, and otherwise mints nothing and matches nothing —
       :func:`pipeline.collect_review_items` has already routed that message to
       the queue for the user to assign.

    Live rows are preferred over dismissed ones throughout (``_company_rows``
    orders them first), so a dismissed duplicate can never shadow the row that is
    actually on the board.
    """

    rows = await _company_rows(session, user_id, rolled.company_token)
    return _pick_application(rows, rolled.req_id, rolled.role_token)


def _pick_application(
    rows: list[Application],
    req_id: str | None,
    role_token: str | None,
) -> Application | None:
    """The cascade itself, over rows already narrowed to one employer.

    Split out from :func:`_resolve_application` because three call sites need it
    and they arrive at ``(req_id, role_token)`` differently: the sync computes it
    for a whole cluster, while the review-classify and orphan-reconcile paths
    compute it from one message. Before this existed those two paths called
    ``.first()``, which — the moment an employer holds more than one application
    — files a user's own classification against an arbitrary sibling.
    """

    if not rows:
        return None

    if req_id is not None:
        for row in rows:
            if row.req_id and row.req_id == req_id:
                return row
    if role_token is not None:
        for row in rows:
            if row.role_token and row.role_token == role_token:
                return row

    if req_id is None and role_token is None:
        # Rule 4. Deliberately looks at ALL rows, not just the identity-less
        # ones, and always returns one rather than minting.
        #
        # A cluster reaches here only when the scan found NO role for this
        # employer in ANY of its mail (`partition_applications` gives anonymous
        # messages their own cluster only when nothing else at the employer is
        # identified), so there is no keyed sibling it could be confused with.
        # Returning None instead would mint a fresh row on EVERY sync at any
        # employer that already has two rows — the same unbounded growth PR #76
        # fixed for a different reason. `_company_rows` orders live-first then
        # oldest-first, so the choice is stable across syncs.
        return rows[0]

    # Rule 3 — adopt the employer's single pre-identity row, in place.
    unidentified = [row for row in rows if row.req_id is None and row.role_token is None]
    if len(unidentified) == 1:
        return unidentified[0]
    # With several, prefer the one the SYNC made. A manual row is a human's own
    # entry and may legitimately duplicate what the mail says; adopting it would
    # rewrite their record. An auto row is the sync's own and is exactly what
    # this identity belongs on.
    auto = [row for row in unidentified if _is_auto_row(row.source)]
    return auto[0] if len(auto) == 1 else None


async def _chosen_application(
    session,
    user_id: uuid.UUID,
    application_id: int | None,
    token: str,
) -> Application | None:
    """The row the USER picked for a review item, if it is a legitimate choice.

    Returns None — falling the caller back to ordinary resolution — when no id
    was sent, when the row is not this user's, or when it belongs to a different
    employer than the one the mail names. Silent rather than an error: a stale id
    from a board that has since re-synced is an ordinary race, not a caller bug,
    and filing the message correctly beats rejecting the request.
    """

    if application_id is None:
        return None
    rows = await _company_rows(session, user_id, token)
    return next((row for row in rows if row.id == application_id), None)


async def _resolve_application_for_email(
    session,
    user_id: uuid.UUID,
    token: str,
    email: Email,
) -> Application | None:
    """Resolve the application ONE stored message belongs to, or None to mint."""

    rows = await _company_rows(session, user_id, token)
    subject = email.subject or ""
    snippet = email.body_snippet or ""
    return _pick_application(
        rows,
        pipeline.extract_req_id(subject, snippet),
        pipeline.normalize_role_token(pipeline.role_from_message(subject, snippet)),
    )


async def _persist_message_refs(
    session,
    user_id: uuid.UUID,
    application_id: int | None,
    refs,
) -> set[int]:
    """Upsert metadata-only Email rows for a set of message refs (no bodies).

    Idempotent on ``(user_id, message_id)``: a re-sync updates the link and
    classification rather than duplicating. Undated messages are skipped — the
    Email row requires a receive time and we never fabricate one. Linking to
    ``application_id`` is what powers the click-through detail view; leaving it
    ``None`` (for review items) is what powers the needs-classification queue.

    SETTLED VERDICTS ARE PRESERVED. A message the user reviewed or corrected
    keeps its category/confidence/method: the classifier's opinion must not
    overwrite a human's on the next scan. This is the same guard
    :func:`_persist_review_items_additive` applies before it even builds its
    refs, but it has to live here too because the rolled-application path
    reaches this function without passing through that filter — so a corrected
    message reverted to the classifier's verdict as soon as it got linked.
    For the same reason a ``None`` ``application_id`` never CLEARS an existing
    link: the rebuild path persists review items unfiltered, which would
    otherwise un-link (and so un-file) an application the user just created.

    RETURNS the ids of the applications it moved an email AWAY from. Re-pointing
    is right — the newest resolution of a message's employer wins — but it can
    leave the previous row with no linked mail at all, which is how application
    64 ("Together AI") ended up on the owner's board with nothing behind it. The
    caller has to decide what happens to those rows; see
    :func:`_dismiss_rows_left_without_mail`. It cannot be decided here, because
    a row emptied by one rolled company may be re-filled by the next one in the
    same sync.
    """

    moved_from: set[int] = set()
    for ref in refs:
        # Naive-UTC: the Email.received_at column is TIMESTAMP WITHOUT TIME ZONE;
        # asyncpg refuses an aware datetime (from parsedate_to_datetime) here.
        received_at = pipeline.to_naive_utc(ref.received_at)
        if received_at is None:
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
            if application_id is not None:
                if (
                    existing.application_id is not None
                    and existing.application_id != application_id
                ):
                    moved_from.add(existing.application_id)
                existing.application_id = application_id
            existing.subject = ref.subject or existing.subject
            existing.sender_name = ref.sender_name
            existing.sender_email = ref.sender_email
            existing.received_at = received_at
            # Only ever ADD a snippet, never blank one. A ref that carries no
            # snippet means "this pass did not fetch one", not "this message has
            # none" — and the unconditional assignment that used to be here is
            # how the stored snippet was erased for every message that came back
            # through the review queue. The role lives in the snippet, so erasing
            # it erases the identity the board groups by.
            if ref.snippet:
                existing.body_snippet = pipeline.unescape_entities(ref.snippet)[:500]
            # A thread id, likewise: a metadata fetch that omits it must not
            # unlink a message from its conversation.
            if ref.thread_id:
                existing.thread_id = ref.thread_id
            if not (existing.user_corrected or existing.is_reviewed):
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
                    received_at=received_at,
                    body_snippet=pipeline.unescape_entities(ref.snippet or "")[:500],
                    classified_as=category,
                    classification_confidence=ref.confidence,
                    classification_method="rules",
                )
            )

    return moved_from


async def _dismiss_rows_left_without_mail(
    session, user_id: uuid.UUID, application_ids: set[int]
) -> list[RemovedApplication]:
    """Take off the board any AUTO row whose LAST linked email moved elsewhere.

    When a message is re-attributed to a different application, the row it came
    from can be left with nothing behind it. That state is worse than either of
    the two it could have had: the row is still on the board, still counted in
    the summary, and — since 2026-08-10 — permanently unremovable, because a
    scan can only contradict a row by re-reading the row's OWN mail and there is
    none left to re-read. Application 64 ("Together AI") is exactly that row.

    So the emptied row is dismissed: off the board, off the summary, still on
    disk, restorable, and re-filed automatically by
    :func:`upsert_applications_for_user` if fresh mail ever names the company
    again. Only ``gmail``-auto rows are eligible — a manual row may legitimately
    have never had mail, and a user-settled row is the user's, not the sync's.

    Deliberately NOT reported as ``purged``: that count renders as "cleared N
    stale" beside the names, and naming a company as removed while it is still
    on the board under the row its mail moved to would be a worse lie than
    saying nothing. It is logged instead.
    """

    if not application_ids:
        return []

    await session.flush()
    removed: list[RemovedApplication] = []
    now = datetime.utcnow()
    for application_id in sorted(application_ids):
        remaining = (
            await session.exec(
                select(func.count())
                .select_from(Email)
                .where(
                    Email.user_id == user_id,
                    Email.application_id == application_id,
                )
            )
        ).one()
        if remaining:
            continue
        row = (
            await session.exec(
                select(Application).where(
                    Application.user_id == user_id,
                    Application.id == application_id,
                )
            )
        ).first()
        if row is None or row.dismissed_at is not None or not _is_auto_row(row.source):
            continue
        row.dismissed_at = now
        row.dismissed_reason = DISMISSED_BY_RESYNC
        row.updated_at = now
        session.add(row)
        removed.append(RemovedApplication(id=row.id, company=row.company))

    if removed:
        await session.flush()
        logger.info(
            "Sync left %s auto row(s) with no linked mail for user_id=%s and "
            "dismissed them (restorable): %s",
            len(removed),
            user_id,
            ", ".join(f"{r.company} (id={r.id})" for r in removed),
        )
    return removed


def _safe_category(value: str) -> EmailCategory | None:
    try:
        return EmailCategory(value)
    except ValueError:
        return None


async def _reopening_evidence(
    session,
    user_id: uuid.UUID,
    existing: Application,
    rolled: pipeline.RolledApplication,
) -> tuple[datetime, datetime] | None:
    """May this REJECTED auto row leave the terminal state — and on what proof?

    Returns ``(rejected_at, applied_at)`` when a genuine re-application licenses
    a reopen, else None. One identity is one row, so a second application to a
    role that was turned down resolves onto the settled row; without this it
    hits :func:`pipeline.advance_application_status`'s terminal early-return and
    the application the user just made exists nowhere on the board.

    Two shapes of evidence, tried in that order and never combined:

    - **cluster-side.** The scan saw the rejection itself, so the comparison is
      between two messages in one cluster. When it did, that is the ONLY test
      applied: a scan whose newest rejection post-dates its newest confirmation
      is telling us the application ended, and the row's older stored mail must
      not be allowed to argue with it.
    - **row-side.** The cluster names no rejection at all — the ordinary
      incremental case, where the delta window is far narrower than the row's
      history. The rejection is then read off the row's own linked mail.

    Deliberately one-directional. Only ``rejected`` reopens; accepted, withdrawn
    and ghosted stay settled, and so does anything without a dated applied signal
    strictly newer than the rejection. A false stay is today's bug once and a
    human can correct it in one click; a false reopen re-fires on every rebuild.
    """

    if existing.status != ApplicationStatus.REJECTED:
        return None
    if pipeline.is_terminal_status(rolled.status):
        return None
    applied_at = rolled.latest_applied_signal_at
    if applied_at is None:
        return None

    if rolled.latest_rejection_at is not None:
        rejected_at = rolled.latest_rejection_at
    else:
        # Runs BEFORE ``_persist_message_refs``, so it reads the link state as it
        # stood before this cluster was filed — which is what "the rejection the
        # window missed" means. No linked rejection → no evidence → stay put.
        rejected_at = (
            await session.exec(
                select(func.max(Email.received_at)).where(
                    Email.user_id == user_id,
                    Email.application_id == existing.id,
                    Email.classified_as == EmailCategory.REJECTION,
                )
            )
        ).one()
        if rejected_at is None:
            return None

    return (rejected_at, applied_at) if applied_at > rejected_at else None


async def upsert_applications_for_user(
    session,
    user_id: uuid.UUID,
    rolled: list[pipeline.RolledApplication],
) -> tuple[int, int]:
    """Idempotently persist rolled-up applications for one user.

    For each company (keyed by the normalized ``company_token``) it updates the
    existing row or inserts a new one — scoped strictly to ``user_id`` from the
    verified JWT, never a client-supplied id. Re-running with the same input
    creates no duplicates: the match is :func:`_find_application_by_token`,
    which compares TOKENS on both sides rather than the stored display name.

    A message that changes hands (re-attributed to a different employer) can
    strand the row it left. Those rows are collected across the whole loop and
    resolved once at the end (:func:`_dismiss_rows_left_without_mail`), never
    per company — a row emptied by one company may be re-filled by the next.

    Stickiness: a mail signal only advances an AUTO row (``source == 'gmail'``).
    A row the user created or corrected (manual / gmail_user) keeps its status
    untouched forever — the re-sync attaches fresh mail refs and fills an empty
    role, but never rewrites a human decision. Returns ``(created, updated)``.

    The ONE exception to "a terminal status is never left" lives here, and only
    for auto rows: a REJECTED row reopens when the mail shows a fresh
    application to the same identity, dated strictly after the rejection
    (:func:`_reopening_evidence`). Re-applying does not mint a second row — the
    resolver matches terminal rows too, so the new confirmation was landing on
    the settled one and vanishing. Every reopen is logged at INFO with the row,
    the company and both instants; that line is the whole monitoring story for
    the transition. Rows a human settled are outside this entirely, because
    ``record_status_correction`` tags them ``gmail_user``.

    Dismissed rows are matched by the same company token rather than duplicated.
    Fresh mail RESURRECTS one the rebuild removed automatically — better
    evidence than the removal that hid it — but never one a human dismissed:
    "this is not an application" is a decision, and re-filing it every sync is
    how the row the user just cleared keeps coming back.
    """

    created = 0
    updated = 0
    emptied: set[int] = set()
    # Earliest-applied first WITHIN a company. When several applications at one
    # employer meet a single pre-identity row, the earliest is the one that
    # adopts it — so the row that has been on the board (and any status the user
    # set on it) stays with the application it was actually about, and the later
    # ones are minted fresh. Across companies the order is irrelevant.
    for r in sorted(rolled, key=lambda x: (x.company_token, x.applied_at or datetime.max)):
        existing = await _resolve_application(session, user_id, r)
        deeplink = _rolled_deeplink(r)

        if existing is not None:
            # Stamp the identity on whatever row we landed on. For a row minted
            # before this concept existed this is the migration: it happens on
            # the next sync, in place, keeping the row id and therefore every
            # contact, interview and user correction hanging off it.
            if existing.req_id is None and r.req_id is not None:
                existing.req_id = r.req_id
            if existing.role_token is None and r.role_token is not None:
                existing.role_token = r.role_token
            if existing.dismissed_at is not None:
                if existing.dismissed_reason == DISMISSED_BY_USER:
                    continue  # a human said no; not counted as updated either
                existing.dismissed_at = None
                existing.dismissed_reason = None
            if _is_auto_row(existing.source):
                reopen = await _reopening_evidence(session, user_id, existing, r)
                if reopen is not None:
                    rejected_at, applied_signal_at = reopen
                    logger.info(
                        "Reopened application id=%s (%s) for user_id=%s: rejected at "
                        "%s, applied again at %s → status %s",
                        existing.id,
                        existing.company,
                        user_id,
                        rejected_at,
                        applied_signal_at,
                        r.status,
                    )
                    existing.status = ApplicationStatus(r.status)
                else:
                    new_status = ApplicationStatus(
                        pipeline.advance_application_status(existing.status.value, r.status)
                    )
                    if new_status != existing.status:
                        existing.status = new_status
                # Re-take the employer's display name. The sync owns an auto
                # row's company, and until the name resolution improved it wrote
                # some wrong ones — "Twitchjobs" from no-reply@twitchjobs.tv,
                # "Doordash" from a title-cased domain label. Without this, a fix
                # to the resolver only ever reaches rows created after it, and
                # the wrong spelling sits on the board forever. Guarded on the
                # token so this can only ever restyle the SAME employer, never
                # rename a row to a different one.
                if (
                    r.company_display != existing.company
                    and pipeline.matches_company_token(existing.company, r.company_token)
                ):
                    existing.company = r.company_display
            if r.role and (
                not existing.position
                # An auto row's role belongs to the sync, exactly as its company
                # does. Filling only an EMPTY position means every improvement to
                # role extraction reaches new rows and never the ones already on
                # the board: "Path Robotics · interest in the Software Engineer,
                # C#" survived the fix that stopped producing it, because the
                # wrong string was already stored. A user-corrected or manual row
                # keeps whatever the human wrote.
                or (_is_auto_row(existing.source) and r.role != existing.position)
            ):
                existing.position = r.role
            # A deadline the mail states refreshes one the mail previously
            # stated — a rescheduled assessment is real news. It never touches
            # one the user typed: that is a decision, and the sync does not get
            # to overrule it.
            if r.due_at is not None and existing.due_source != DUE_FROM_USER:
                existing.due_at = r.due_at
                existing.due_source = DUE_FROM_MAIL
            if r.applied_at and existing.applied_date is None:
                existing.applied_date = r.applied_at.date()
            if deeplink and not existing.url:
                existing.url = deeplink
            existing.updated_at = datetime.utcnow()
            session.add(existing)
            await session.flush()
            emptied |= await _persist_message_refs(
                session, user_id, existing.id, r.messages
            )
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
                req_id=r.req_id,
                role_token=r.role_token,
                due_at=r.due_at,
                due_source=DUE_FROM_MAIL if r.due_at is not None else None,
            )
            session.add(app)
            await session.flush()
            emptied |= await _persist_message_refs(
                session, user_id, app.id, r.messages
            )
            created += 1

    # Once, after every company has had its say — a row emptied by one of them
    # may have been re-filled by another.
    await _dismiss_rows_left_without_mail(session, user_id, emptied)

    await session.commit()
    return created, updated


def _parse_applied_date(value: str | None) -> date | None:
    """ISO-8601 ``YYYY-MM-DD`` (or a full ISO datetime) → ``date``; else 422.

    Deliberately loud. The whole reason this exists is that the create endpoint
    used to accept no date at all, so the dialog's value vanished — a parse that
    quietly returned ``None`` on bad input would reproduce that failure with
    extra steps. ``url`` gets no such treatment: nothing else in this codebase
    validates a stored URL, and inventing a rule here would reject links the
    Gmail-derived rows already store.
    """

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:  # tolerate a full ISO timestamp (Date.toISOString()) and its Z suffix
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"applied_date must be an ISO-8601 date (YYYY-MM-DD); got {value!r}."
            ),
        ) from exc


def _rolled_deeplink(r: pipeline.RolledApplication) -> str | None:
    """Gmail deep link for a rolled row's most-recent message, if any."""

    if not r.messages:
        return None
    primary = r.messages[0]
    return pipeline.gmail_deeplink(
        thread_id=primary.thread_id, message_id=primary.message_id
    )


# The email categories that imply a filed application — exactly the keys
# ``_lifecycle_to_status`` maps to a real ApplicationStatus. Kept next to the
# reconciliation that consumes them so the two cannot drift apart.
_FILING_CATEGORIES: tuple[EmailCategory, ...] = (
    EmailCategory.APPLIED,
    EmailCategory.PENDING_APPLICATION,
    EmailCategory.ASSESSMENT,
    EmailCategory.INTERVIEW,
    EmailCategory.OFFER,
    EmailCategory.REJECTION,
)


async def reconcile_orphaned_classifications(session, user_id: uuid.UUID) -> int:
    """File applications for SETTLED emails that were left without one.

    A message the user classified into a filing status is supposed to produce an
    application. When it didn't — the endpoint's employer lookup failed and the
    decision was swallowed — the row is stranded: reviewed, unlinked, invisible
    on the board and gone from the queue. This is the catch-up that un-strands
    it on the next sync, now that :func:`pipeline.resolve_employer` can name the
    employer from an ATS display-name / subject lead.

    Scoped to ``user_id`` like every other query here. Deliberately narrow: only
    rows the user actually settled (``user_corrected`` or ``is_reviewed``) with
    a filing category and no ``application_id``. An un-reviewed auto-classified
    row is excluded on purpose — by design it is either already linked or in the
    review queue, and sweeping those up would re-open the "fabricate a row from
    a low-confidence guess" bug the precision gate exists to prevent.

    Idempotent: a reconciled email gains an ``application_id``, so the very
    predicate that selected it no longer matches on the next run. Two orphans
    for one employer collapse into a single application within one pass, and an
    existing row is only ever ADVANCED (never downgraded, never un-settled).
    Returns the number of applications CREATED.

    Stickiness, the same rule :func:`upsert_applications_for_user` enforces: a
    row the user created or corrected keeps its stage, and the orphan is filed
    against it WITHOUT rewriting the status. Rows this pass minted are exempt —
    reconcile tags what it creates ``gmail_user``, so without the carve-out the
    second orphan of a pass could not roll up onto the row the first one just
    caused to exist.
    """

    orphans = (
        await session.exec(
            select(Email)
            .where(
                Email.user_id == user_id,
                Email.application_id.is_(None),
                Email.classified_as.in_(_FILING_CATEGORIES),
                or_(
                    Email.user_corrected == True,  # noqa: E712 — SQL boolean
                    Email.is_reviewed == True,  # noqa: E712 — SQL boolean
                ),
            )
            .order_by(Email.received_at)
        )
    ).all()

    created = 0
    # Row ids THIS pass minted. They carry ``gmail_user`` because they came from
    # a human decision, but they are not a *standing* correction — they are
    # three lines old — so the stickiness gate below does not apply to them.
    minted: set[int] = set()
    for email in orphans:
        status_value = _lifecycle_to_status(email.classified_as)
        if status_value is None:  # defensive: category outside the filing set
            continue
        employer = pipeline.resolve_employer(
            email.sender_email or "", email.subject or "", email.sender_name
        )
        if employer is None:
            continue  # still unnameable — never invent a company
        token, display = employer

        app = await _resolve_application_for_email(session, user_id, token, email)
        if app is None:
            # Stamp the identity the message carries onto the row it mints, so
            # the next sync recognises this application instead of filing a
            # second one beside it.
            role = pipeline.role_from_message(email.subject or "", email.body_snippet or "")
            app = Application(
                user_id=user_id,
                company=display,
                position=role or _NO_ROLE,
                status=ApplicationStatus(status_value),
                applied_date=email.received_at.date() if email.received_at else None,
                source=SOURCE_GMAIL_USER,  # came from a human decision → sticky
                url=pipeline.gmail_deeplink(
                    thread_id=email.thread_id, message_id=email.message_id
                ),
                req_id=pipeline.extract_req_id(email.subject or "", email.body_snippet or ""),
                role_token=pipeline.normalize_role_token(role),
            )
            session.add(app)
            await session.flush()
            minted.add(app.id)
            created += 1
        else:
            # A human classified this message INTO a filing category, which is
            # the newest decision on record — so it restores a dismissed row
            # (either kind) rather than filing a duplicate beside it.
            if app.dismissed_at is not None:
                app.dismissed_at = None
                app.dismissed_reason = None
                app.updated_at = datetime.utcnow()
                session.add(app)
            # Advance-only AND only on a row automation still owns — the same
            # two-part rule the sync upsert applies. ``advance_application_status``
            # alone stops a downgrade and protects a terminal state; it knows
            # nothing about who owns the row, so the ``_is_auto_row`` half has to
            # be here. Without it one stranded settled email could overwrite a
            # standing human correction — once, silently, and to a terminal
            # state nothing could then move. A row this pass minted is exempt so
            # the documented "two orphans collapse into one application within
            # one pass" still rolls their stages up.
            if _is_auto_row(app.source) or app.id in minted:
                new_status = ApplicationStatus(
                    pipeline.advance_application_status(app.status.value, status_value)
                )
                if new_status != app.status:
                    app.status = new_status
                    app.updated_at = datetime.utcnow()
                    session.add(app)
        email.application_id = app.id
        session.add(email)

    if orphans:
        await session.flush()
    if created:
        logger.info(
            "Reconciled %s orphaned classification(s) into applications for "
            "user_id=%s",
            created,
            user_id,
        )
    return created


async def _reset_review_queue(
    session, user_id: uuid.UUID, coverage: ScanCoverage | None = None
) -> None:
    """Clear the review items THIS SCAN re-read, so the rebuild can restate them.

    Only unlinked (``application_id IS NULL``), un-reviewed, gmail-sourced rows
    are eligible — a review item the user already classified became a real
    application (linked) or was marked reviewed, and is preserved.

    And only messages the scan actually re-read. This used to clear the whole
    queue, which is the incident's reasoning applied one table over: an
    uncertain message surfaced by an earlier, wider scan was DELETED outright by
    any later rebuild whose window missed it — an ``emails`` row destroyed,
    never linked to an application, so the row-level protections never saw it.
    A queue item the scan re-read and no longer flags is genuinely resolved
    (:func:`_persist_review_items` puts back the ones that are still uncertain);
    one the scan never reached is simply unexamined. With no coverage, nothing
    is cleared.

    Scoped by MESSAGE id, deliberately, even though the queue itself is grouped
    by thread. Widening this DELETE to "every message of a thread the scan
    touched" would destroy ``emails`` rows the scan never read on the strength
    of having read a sibling — the 2026-08-10 reasoning, one table over and one
    field along. The thread grouping is applied where it is safe (when the queue
    is read, and when a decision is recorded), not where it deletes.

    It does still tidy the duplicates: a rebuild whose scan re-read BOTH
    messages of a thread clears both rows and
    :func:`pipeline.collect_review_items` restates the thread once.
    """

    if coverage is None or not coverage.message_ids:
        return

    await session.exec(
        sa_delete(Email).where(
            Email.user_id == user_id,
            Email.source_account == EmailSource.GMAIL,
            Email.application_id.is_(None),
            Email.is_reviewed == False,  # noqa: E712 — SQL boolean, not identity
            Email.message_id.in_(coverage.message_ids),
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
            snippet=item.snippet,
        )
        for item in review
    ]
    await _persist_message_refs(session, user_id, None, refs)
    return sum(1 for r in refs if r.received_at is not None)


async def _persist_review_items_additive(session, user_id: uuid.UUID, review) -> int:
    """Additively surface uncertain verdicts to the needs-review queue.

    Unlike the rebuild path this NEVER resets the queue, so a review item found
    by an earlier (possibly broader) scan survives a later scan whose window
    missed it. Idempotent on ``message_id``, and it never re-opens a message the
    user already classified (linked to an application) or dismissed (reviewed):
    those are excluded up front so a subsequent low-confidence re-scan cannot
    un-link them. Returns the number of dated items surfaced this pass.

    Settled is judged per THREAD as well as per message. A conversation the user
    has already decided about must not come back to the queue because a later
    message arrived on it — that is the same "classify this application twice"
    the thread grouping in :func:`pipeline.collect_review_items` removes, only
    spread across two syncs instead of one.
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
            snippet=item.snippet,
        )
        for item in review
    ]

    scoped = []
    msg_ids = [r.message_id for r in refs if r.message_id]
    thread_ids = [r.thread_id for r in refs if r.thread_id]
    if msg_ids:
        scoped.append(Email.message_id.in_(msg_ids))
    if thread_ids:
        scoped.append(Email.thread_id.in_(thread_ids))
    if scoped:
        rows = (
            await session.exec(
                select(Email.message_id, Email.thread_id).where(
                    Email.user_id == user_id,
                    or_(*scoped),
                    or_(
                        Email.application_id.is_not(None),
                        Email.is_reviewed == True,  # noqa: E712 — SQL boolean
                    ),
                )
            )
        ).all()
        settled_messages = {message_id for message_id, _thread_id in rows}
        settled_threads = {
            thread_id for _message_id, thread_id in rows if thread_id
        }
        refs = [
            r
            for r in refs
            if r.message_id not in settled_messages
            and (r.thread_id is None or r.thread_id not in settled_threads)
        ]

    await _persist_message_refs(session, user_id, None, refs)
    return sum(1 for r in refs if r.received_at is not None)


async def sync_gmail_pipeline_additive(
    session,
    user_id: uuid.UUID,
    rolled: list[pipeline.RolledApplication],
    review: list,
) -> MergeResult:
    """ADDITIVELY merge a freshly-scanned Gmail pipeline — the durable sync.

    The non-destructive path used by routine/auto syncs (the dashboard
    connect-time backfill and the inbox workbench's relay). It ONLY inserts
    newly-found applications and advances/refreshes existing ones — status moves
    monotonically, manual and user-corrected rows are left untouched — and it
    NEVER deletes a previously-found ``gmail``/``gmail_user`` row just because
    the current, bounded scan didn't happen to re-include it. That is what lets
    the pipeline ACCUMULATE and survive syncs whose windows differ, instead of
    applications appearing then vanishing run-to-run. The destructive
    purge+rebuild is reserved for the explicit user "Re-sync" button.

    Idempotent and user-scoped. Returns a :class:`MergeResult` whose ``purged``
    is always 0 and whose ``removed`` is always empty. ``created`` includes any
    application recovered by :func:`reconcile_orphaned_classifications`.

    ONE row can still leave the board on this path, and the counts do not name
    it: an AUTO row whose LAST linked email was re-attributed to another
    application is dismissed by :func:`_dismiss_rows_left_without_mail` (called
    from the upsert, so it applies to both merge paths). That is not the removal
    this function promises never to make — nothing is dropped for being absent
    from a bounded scan; a row is retired because its own evidence now belongs
    to a different row, which is the alternative to leaving it stranded and
    permanently unremovable. It is logged, listed under ``?dismissed=true``, and
    restorable. It is deliberately NOT counted in ``purged``, because that
    number renders as "cleared N stale (names)" and the company in question is
    still on the board under the row its mail moved to.
    """

    created, updated = await upsert_applications_for_user(session, user_id, rolled)
    # Catch up on anything the user classified that never got an application.
    created += await reconcile_orphaned_classifications(session, user_id)
    needs_review = await _persist_review_items_additive(session, user_id, review)
    await session.commit()
    return MergeResult(
        created=created, updated=updated, purged=0, needs_review=needs_review
    )


async def purge_and_rebuild_gmail_pipeline(
    session,
    user_id: uuid.UUID,
    rolled: list[pipeline.RolledApplication],
    review: list,
    coverage: ScanCoverage | None = None,
) -> MergeResult:
    """REPLACE the Gmail-derived pipeline for one user, preserving edits.

    Reserved for the EXPLICIT user "Re-sync" button (a deliberate "start
    clean"), never a routine/auto sync. Auto syncs use
    :func:`sync_gmail_pipeline_additive`, which removes nothing at all. This is
    what a re-sync runs so the owner's garbage rows are cleared and the board is
    rebuilt from the corrected rollup. It:

      1. Removes AUTO rows (``source == 'gmail'``) that this scan CONTRADICTS —
         see :func:`_scan_contradicts`. Removal is a dismissal, not a delete:
         the row and its emails stay on disk and can be restored.
      2. Upserts the fresh rolled set (continuing companies keep their id and
         filed date; new ones are inserted).
      3. Reconciles any settled-but-unlinked classification into an application
         (:func:`reconcile_orphaned_classifications`).
      4. Rebuilds the needs-classification queue from the review items.

    What changed, and why
    ---------------------

    This function used to DELETE every auto row whose company was missing from
    the freshly-rolled set, along with its emails. That is a reasoning error:
    the rolled set comes from a scan bounded by scope, date range and message
    count, and a scan that cannot see a message reports exactly what a mailbox
    that no longer contains it reports. On 2026-08-10 it destroyed two real
    applications whose ATS confirmations had been archived — invisible to an
    ``in:inbox`` scan — and the rows plus their emails were gone from Postgres.

    So absence is no longer evidence. A row is only removed when the scan
    re-read the row's own messages and stopped concluding an application from
    them, and even then it is only hidden. ``coverage=None`` (a caller that
    cannot say what it looked at) therefore removes nothing.

    INVARIANT — where ``coverage`` may come from. Only a SERVER-side scan with
    ``scope="anywhere"``. That scope is forced in ``gmail_oauth._scan_server_side``
    so a rebuild can see archived mail; coverage built from client-relayed
    ``items`` carries whatever window and scope that client chose, which is not
    a thing this function can verify. ``POST /gmail/sync`` therefore REFUSES
    ``items`` together with ``mode="rebuild"`` outright — client-relayed scans
    are structurally additive-only, and every caller of this function comes
    from the server-scan branch.

    Manual and user-corrected rows (and anything the user classified) are never
    touched. Idempotent and user-scoped. Returns a :class:`MergeResult` naming
    what was removed.
    """

    keep_tokens = {r.company_token for r in rolled}

    auto_rows = (
        await session.exec(
            select(Application).where(
                Application.user_id == user_id,
                Application.source == SOURCE_GMAIL_AUTO,
                # Already off the board — re-dismissing would double-count it
                # and re-report it to the user as newly removed.
                Application.dismissed_at.is_(None),
            )
        )
    ).all()

    now = datetime.utcnow()
    removed: list[RemovedApplication] = []
    for row in auto_rows:
        # Token matching, not ``lower(company) in keep_tokens``: a stored
        # display name is not its own token unless it happens to be one word,
        # so "Together AI" was never recognised as a company this scan had just
        # re-filed — it fell through to the contradiction test on every rebuild.
        if any(pipeline.matches_company_token(row.company, t) for t in keep_tokens):
            continue
        linked = (
            await session.exec(
                select(Email).where(
                    Email.user_id == user_id, Email.application_id == row.id
                )
            )
        ).all()
        if not _scan_contradicts(list(linked), coverage):
            continue  # unseen, not disproven — the row stays
        row.dismissed_at = now
        row.dismissed_reason = DISMISSED_BY_RESYNC
        session.add(row)
        removed.append(RemovedApplication(id=row.id, company=row.company))
    await session.flush()

    created, updated = await upsert_applications_for_user(session, user_id, rolled)
    # Catch up on anything the user classified that never got an application.
    # Runs AFTER the upsert so an orphan whose employer is also in the fresh
    # rollup joins that row instead of creating a duplicate.
    created += await reconcile_orphaned_classifications(session, user_id)

    await _reset_review_queue(session, user_id, coverage)
    needs_review = await _persist_review_items(session, user_id, review)

    await session.commit()
    if removed:
        logger.info(
            "Re-sync removed %s contradicted auto row(s) for user_id=%s: %s "
            "(dismissed, not deleted — restorable)",
            len(removed),
            user_id,
            ", ".join(r.company for r in removed),
        )
    return MergeResult(
        created=created,
        updated=updated,
        purged=len(removed),
        needs_review=needs_review,
        removed=tuple(removed),
    )


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

    Setting a status on a REMOVED row restores it. Otherwise the correction
    would land on a row nobody can see — user-owned, sticky and invisible —
    which is a worse state than either of the two it came from. Someone
    deciding what stage an application is at is telling you they want it.
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

    app.dismissed_at = None
    app.dismissed_reason = None
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
    """Mark a row 'not an application' — take it off the board, teach the model.

    Records each linked email as an ``other`` training example (so the classifier
    learns it was wrongly filed), then DISMISSES the row: it disappears from the
    board and the summary, but the row and its emails stay on disk so
    :func:`restore_application` can put it back. It used to delete both, which
    made a misclick as final as the re-sync bug was. Scoped to the owner.
    Returns False when the row does not exist for this user.
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

    app.dismissed_at = datetime.utcnow()
    app.dismissed_reason = DISMISSED_BY_USER
    app.updated_at = datetime.utcnow()
    session.add(app)
    await session.commit()
    return True


async def restore_application(
    session, user_id: uuid.UUID, application_id: int
) -> Application | None:
    """Undo a dismissal — put the row (and its mail) back on the board.

    The other half of making removal recoverable: whether the row was dismissed
    by the user or taken off by a re-sync, this returns it verbatim — same id,
    same status, same filed date, same linked emails — because nothing was ever
    deleted. Idempotent on an already-live row. Scoped to the owner; ``None``
    when the row is not theirs.
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
    if app.dismissed_at is not None:
        app.dismissed_at = None
        app.dismissed_reason = None
        app.updated_at = datetime.utcnow()
        session.add(app)
        await session.commit()
        await session.refresh(app)
    return app


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
    company: str | None = None,
    application_id: int | None = None,
) -> dict[str, object]:
    """Classify a needs-review email into a category — persist + train.

    Marks the email reviewed, records a training example, and — when the chosen
    category is a real lifecycle stage with a nameable employer — files the mail
    against an application. Scoped to the owner.

    A row it MINTS is user-owned and sticky outright. A row it lands on is
    advanced through the same gate the sync uses (forward-only, and a terminal
    status is settled), and becomes user-owned only if the stage actually moved.
    Both halves are deliberate and neither is decorative: the question the user
    answered is "what is this MESSAGE?", so a stray "thank you for applying"
    must not drag a row at ``interviewing`` back to ``applied``, and a stage
    that did not move is not a decision about the stage worth making sticky.

    NEVER REPORTS SUCCESS WHILE CREATING NOTHING. When the category *is* a
    filing status but the employer cannot be named (and the caller supplied no
    ``company``), the decision is not swallowed: the email is left in the review
    queue exactly as it was — un-reviewed, still ``needs_review`` — and the
    response carries ``needs_employer: True`` naming what the caller must
    supply. The training example is still written, because the user's label is
    valuable regardless of whether a row could be filed from it.

    (Previously this branch marked the email reviewed, wrote the training row,
    created no application and returned ``{"application_id": null}`` with a
    2xx — so the item vanished from the queue and never reached the board.
    ``training_data`` id 4 / ``emails`` id 58 in production are that bug.)
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

    status_value = _lifecycle_to_status(category)
    employer = None
    if status_value is not None:
        employer = pipeline.resolve_employer(
            email.sender_email or "", email.subject or "", email.sender_name
        )
        if employer is None and company:
            employer = pipeline.employer_from_text(company)

    if status_value is not None and employer is None:
        # Visible failure: keep the label for training, keep the item in the
        # queue, and tell the caller what is missing.
        await _add_training_example(session, user_id, email, category)
        await session.commit()
        logger.warning(
            "Review classify for user_id=%s message_id=%s needs an employer: "
            "category=%s sender=%s subject=%r",
            user_id,
            message_id,
            category.value,
            email.sender_email,
            email.subject,
        )
        return {
            "classified_as": category.value,
            "application_id": None,
            "needs_employer": True,
            "message_id": message_id,
            "detail": (
                "Could not identify the employer for this email. Re-send the "
                "same classification with a 'company' to file it."
            ),
        }

    email.classified_as = category
    email.is_reviewed = True
    email.user_corrected = True

    result: dict[str, object] = {
        "classified_as": category.value,
        "application_id": None,
        "needs_employer": False,
    }

    if status_value is not None and employer is not None:
        token, display = employer
        # The user's own answer to "which application is this about?" outranks
        # every inference below it — that is the whole point of asking. Still
        # validated: the row must be theirs and must be at the employer this
        # mail actually names, so a stale or wrong id degrades to the normal
        # resolution instead of filing a message under an unrelated company.
        app = await _chosen_application(session, user_id, application_id, token)
        if app is None:
            app = await _resolve_application_for_email(session, user_id, token, email)
        if app is None:
            role = pipeline.role_from_message(email.subject or "", email.body_snippet or "")
            app = Application(
                user_id=user_id,
                company=display,
                position=role or _NO_ROLE,
                status=ApplicationStatus(status_value),
                applied_date=email.received_at.date() if email.received_at else None,
                source=SOURCE_GMAIL_USER,  # human-classified → sticky
                url=pipeline.gmail_deeplink(
                    thread_id=email.thread_id, message_id=email.message_id
                ),
                req_id=pipeline.extract_req_id(email.subject or "", email.body_snippet or ""),
                role_token=pipeline.normalize_role_token(role),
            )
            session.add(app)
            await session.flush()
        else:
            # The user is answering "what is this MESSAGE?", not "what stage is
            # this application at now?". So the stage goes through the same
            # choke point the sync uses — forward-only, terminal is settled —
            # rather than being assigned verbatim. A verbatim write here snapped
            # a row already at ``interviewing`` back to ``applied`` off one
            # stray role-less "thank you for applying", and silently reopened
            # settled rows.
            new_status = ApplicationStatus(
                pipeline.advance_application_status(app.status.value, status_value)
            )
            if new_status != app.status:
                # Only a stage that actually MOVED is a decision about the
                # stage, and only then does the row become user-owned. Flipping
                # ``source`` unconditionally is the other half of the same bug:
                # it froze the row at whatever stage it happened to hold, since
                # the advance gate in :func:`upsert_applications_for_user` can
                # never re-advance a ``gmail_user`` row.
                #
                # ``source`` carries four consequences, and this choice is a
                # trade across all four rather than three. Staying ``gmail``
                # keeps the row (a) advanceable by mail, (b) restyled when the
                # employer resolver improves, (c) re-roled when extraction
                # improves — all correct, because the user labelled a MESSAGE
                # and asserted nothing about the row's stage, company or title.
                # It also leaves the row (d) PURGEABLE: a rebuild that re-reads
                # every one of its linked messages and still concludes no
                # application may dismiss it (:func:`_merge_rolled_into_board`,
                # which selects on ``source == SOURCE_GMAIL_AUTO``), where the
                # old unconditional flip would have excluded it. Accepted
                # knowingly: that dismissal is reversible, is reported to the
                # user with a ``resync`` reason and an undo, and requires the
                # scan to have actually re-read the row's own evidence. Freezing
                # a wrong stage forever is not reversible, which is why (d) is
                # the one that gives. Decoupling the two properly needs a second
                # column, not a different reading of this one.
                app.status = new_status
                app.source = SOURCE_GMAIL_USER
            session.add(app)
        email.application_id = app.id
        result["application_id"] = app.id

    session.add(email)
    await _add_training_example(session, user_id, email, category)
    # One decision settles the whole conversation, because the queue offers one
    # entry per conversation.
    await _settle_thread_siblings(
        session, user_id, email, category, result["application_id"]
    )
    await session.commit()
    return result


async def _settle_thread_siblings(
    session,
    user_id: uuid.UUID,
    email: Email,
    category: EmailCategory,
    application_id: object,
) -> int:
    """Settle the other messages of a classified message's Gmail THREAD.

    The queue shows one entry per conversation (see
    :func:`review_queue_cloud`), so classifying that entry has to settle every
    message behind it — otherwise the sibling messages stay unlinked and
    un-reviewed, and the very next scan puts the same application back in front
    of the user. Emails 58 and 73 on the owner's account are one thread asked
    about twice.

    Narrow on purpose: only siblings that are still unlinked AND un-reviewed are
    touched, so a message already filed elsewhere or already decided is left
    alone. They are marked reviewed, given the chosen category and linked to the
    same application — but NOT flagged ``user_corrected``, and no training
    example is written for them: the human read one message, and only that one
    is honest evidence of what they were labelling.
    """

    if not email.thread_id:
        return 0

    siblings = (
        await session.exec(
            select(Email).where(
                Email.user_id == user_id,
                Email.thread_id == email.thread_id,
                Email.message_id != email.message_id,
                Email.application_id.is_(None),
                Email.is_reviewed == False,  # noqa: E712 — SQL boolean
            )
        )
    ).all()

    for sibling in siblings:
        sibling.is_reviewed = True
        sibling.classified_as = category
        if isinstance(application_id, int):
            sibling.application_id = application_id
        session.add(sibling)
    return len(siblings)


@dataclass
class _MailCluster:
    """One application's worth of a stored row's linked mail."""

    req_id: str | None
    role_token: str | None
    role: str | None
    emails: list[Email]

    @property
    def earliest(self) -> datetime:
        dated = [e.received_at for e in self.emails if e.received_at is not None]
        return min(dated) if dated else datetime.max


def cluster_stored_mail(emails: list[Email]) -> list[_MailCluster]:
    """Group one row's OWN linked mail into the applications it describes.

    The database-only twin of :func:`pipeline.partition_applications`, and the
    reason a merged row can be split without going back to Gmail: every
    contributing message was persisted with its subject and snippet, so the
    requisition ids and role titles that tell them apart are already on disk.

    Returns fewer than two clusters when there is nothing to offer — either the
    mail names no role anywhere (the honest one-row case) or it all names the
    same one. Callers must treat "< 2" as "no split available", never as an
    error.

    Messages that name no role are kept with the earliest cluster rather than
    dropped or guessed at: they are real mail belonging to this employer, and
    the retained row is the conservative home for anything unattributable.
    """

    keyed: list[_MailCluster] = []
    anonymous: list[Email] = []

    for email in emails:
        subject, snippet = email.subject or "", email.body_snippet or ""
        req_id = pipeline.extract_req_id(subject, snippet)
        role = pipeline.role_from_message(subject, snippet)
        role_token = pipeline.normalize_role_token(role)
        if req_id is None and role_token is None:
            anonymous.append(email)
            continue
        match = next(
            (
                c
                for c in keyed
                if (req_id is not None and c.req_id == req_id)
                or (role_token is not None and c.role_token == role_token)
            ),
            None,
        )
        if match is None:
            keyed.append(_MailCluster(req_id, role_token, role, [email]))
            continue
        match.emails.append(email)
        match.req_id = match.req_id or req_id
        match.role_token = match.role_token or role_token
        match.role = match.role or role

    if len(keyed) < 2:
        return []

    keyed.sort(key=lambda c: c.earliest)
    if anonymous:
        keyed[0].emails.extend(anonymous)
    return keyed


def _status_from_mail(emails: list[Email]) -> str:
    """The stage a cluster's own mail reaches — recomputed, never inherited.

    Deliberately derived from scratch. The row being split may already hold a
    TERMINAL status, and `advance_application_status` never leaves one, so
    inheriting it would hand every sibling a rejection that belonged to one
    requisition — which is the exact damage the identity work exists to undo.

    The result is ORDER-INDEPENDENT, and not because anything is sorted. From a
    non-terminal start the fold is a commutative max-by-stage-rank, and a
    rejection absorbs whatever follows it, so no permutation of the same
    messages can yield a different stage. This used to sort chronologically,
    which reads as "the latest message wins" — a guarantee it never made and
    does not need.
    """

    status = DEFAULT_APPLICATION_STATUS.value
    for email in emails:
        if email.classified_as is None:
            continue
        incoming = _lifecycle_to_status(email.classified_as)
        if incoming is not None:
            status = pipeline.advance_application_status(status, incoming)
    return status


def _lifecycle_to_status(category: EmailCategory) -> str | None:
    """Map a lifecycle email category to an ApplicationStatus value, or None.

    Reads the canonical :data:`CATEGORY_TO_STATUS` rather than restating it —
    this function used to hold a second copy, which is how ``assessment`` came
    to mean ``interviewing`` here and a settable stage in the UI.
    """

    status = CATEGORY_TO_STATUS.get(category)
    return status.value if status is not None else None


async def _connected_account_email(user_id: uuid.UUID) -> str | None:
    """The email of the user's connected Gmail account, or ``None``.

    Used only to retarget "Open in Gmail" deep links at the mailbox the user
    actually linked (the reported bug: links opened the browser-default
    ``/u/0/`` account). Best-effort — any lookup failure yields ``None`` and the
    link falls back to the ``/u/0/`` form rather than breaking the response.
    Imported lazily to keep the cloud cold-start import graph thin.
    """

    try:
        from jobtracker.credentials.cloud import get_gmail_credentials

        stored = await get_gmail_credentials(user_id)
        return stored.email if stored else None
    except Exception:  # noqa: BLE001 — a link hint must never break the endpoint
        return None


def _serialize(
    app: Application, account_email: str | None = None
) -> CloudApplicationResponse:
    """Convert an ``Application`` ORM row to the public response shape.

    ``account_email`` retargets the stored Gmail deep link (``url``) at the
    connected mailbox so "Open in Gmail" lands in the right account even for rows
    persisted before that fix; omitted callers keep the stored url verbatim.
    """

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
        url=pipeline.retarget_gmail_deeplink(app.url, account_email),
        dismissed_at=app.dismissed_at.isoformat() if app.dismissed_at else None,
        dismissed_reason=app.dismissed_reason,
        due_at=app.due_at.isoformat() if app.due_at else None,
        due_source=app.due_source if app.due_at else None,
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
    dismissed: bool = Query(
        False,
        description=(
            "Return the REMOVED rows instead of the live board — what a re-sync "
            "took off and what the user dismissed, so either can be restored."
        ),
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

    Dismissed rows are excluded by default: removal hides a row, it no longer
    deletes it. ``dismissed=true`` returns exactly those instead, which is the
    list an "undo" surface reads.
    """

    filters = [Application.user_id == user_id]
    filters.append(
        Application.dismissed_at.is_not(None)
        if dismissed
        else Application.dismissed_at.is_(None)
    )
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
            # `id` breaks the tie, and it has to. A first Gmail rebuild writes
            # hundreds of rows inside the same second, so ordering on
            # `created_at` alone leaves them tied en masse and Postgres is free
            # to return them in a different order per request. Paging through a
            # non-deterministic order silently drops and repeats rows across
            # pages — which the export now walks, and which the board's "newest
            # 200 of 250" claim depends on being true.
            .order_by(Application.created_at.desc(), Application.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await session.exec(stmt)).all()

    # Retarget each row's "Open in Gmail" link at the connected mailbox so the
    # dashboard cards open the right account, not the browser-default /u/0/.
    account_email = await _connected_account_email(user_id)
    return CloudApplicationListResponse(
        applications=[_serialize(app, account_email) for app in rows],
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
        # Dismissed rows are off the board, so they are out of every tile too —
        # otherwise the funnel would keep counting an application the user (or a
        # re-sync) removed, and the stat tiles would disagree with the list.
        grouped = (
            await session.exec(
                select(Application.status, func.count())
                .where(
                    Application.user_id == user_id,
                    Application.dismissed_at.is_(None),
                )
                .group_by(Application.status)
            )
        ).all()

        this_week = (
            await session.exec(
                select(func.count())
                .select_from(Application)
                .where(
                    Application.user_id == user_id,
                    Application.dismissed_at.is_(None),
                    Application.created_at >= week_ago,
                    Application.created_at <= now,
                )
            )
        ).one()

        # Counted per THREAD, exactly like the queue this number links to —
        # otherwise the tile says "2 need classification" for one conversation
        # the queue shows once, and the two disagree in the UI.
        needs_review = (
            await session.exec(
                select(
                    func.count(
                        func.distinct(
                            func.coalesce(Email.thread_id, Email.message_id)
                        )
                    )
                )
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

    ``applied_date`` and ``url`` are persisted when supplied. A malformed date
    is a visible 422: dropping it silently is exactly the bug that made the
    dialog's date and link disappear into ``notes``.
    """

    applied_date = _parse_applied_date(data.applied_date)
    url = (data.url or "").strip() or None

    async with get_session() as session:
        app = Application(
            user_id=user_id,
            company=data.company,
            position=data.position,
            status=data.status,
            notes=data.notes,
            applied_date=applied_date,
            url=url,
            source=SOURCE_MANUAL,  # hand-filed → sticky, never auto-touched
        )
        session.add(app)
        await session.commit()
        await session.refresh(app)

    return _serialize(app)


def _message_ref_response(
    email: Email, account_email: str | None = None
) -> MessageRefResponse:
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
            thread_id=email.thread_id,
            message_id=email.message_id,
            account_email=account_email,
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

    ONE ENTRY PER GMAIL THREAD. A conversation is one application, so being
    asked about it twice is being asked to do the same work twice: the owner's
    queue listed "Crusoe | Application Received" as two items (emails 58 and 73,
    thread ``19fed7e0706ee704``). The newest message of a thread represents it,
    and classifying it settles the rest (:func:`_settle_thread_siblings`).
    Collapsing happens here rather than in SQL so the fix also covers the
    duplicate rows earlier syncs already persisted; ``limit`` therefore bounds
    the rows READ, and the queue can return fewer entries than that.
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

    account_email = await _connected_account_email(user_id)
    items: list[ReviewItemResponse] = []
    seen_threads: set[str] = set()
    for e in rows:
        # Mail with no thread id stands alone under its own message id.
        key = e.thread_id or e.message_id
        if key in seen_threads:
            continue
        seen_threads.add(key)
        items.append(
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
                    thread_id=e.thread_id,
                    message_id=e.message_id,
                    account_email=account_email,
                ),
            )
        )
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

    A 2xx does NOT on its own mean a row was filed: when the employer cannot be
    named the response carries ``needs_employer: true`` and the item stays in
    the queue. Callers must branch on that flag (and may re-POST with
    ``company``) rather than assuming success.
    """

    async with get_session() as session:
        return await classify_review_item(
            session, user_id, message_id, data.category, data.company, data.application_id
        )


@router.get("/statuses", response_model=StatusVocabularyResponse)
async def application_statuses_cloud() -> StatusVocabularyResponse:
    """The canonical stage vocabulary — the one place a client should read it.

    Declared ABOVE ``GET /{application_id}`` deliberately: FastAPI matches in
    declaration order and would otherwise try ``"statuses"`` as an int path
    param and answer 422. Same pattern as ``/summary`` and ``/review``.

    Serves what :class:`ApplicationStatus` says, not a copy of it, so a client
    can assert its own ``<select>`` against this (or against the enum in
    ``/openapi.json``, which is generated from the same declaration) instead of
    hand-maintaining a fourth list that drifts.
    """

    return StatusVocabularyResponse(
        statuses=list(APPLICATION_STATUSES),
        default=DEFAULT_APPLICATION_STATUS.value,
        category_to_status={
            category.value: status.value
            for category, status in CATEGORY_TO_STATUS.items()
        },
        classifier_categories=list(pipeline.CANONICAL_CATEGORIES),
    )


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

    # Resolved before the row session opens so the deep-link retarget never
    # nests a second session inside this one.
    account_email = await _connected_account_email(user_id)

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
        serialized = _serialize(app, account_email)
        messages = [_message_ref_response(e, account_email) for e in emails]
        clusters = cluster_stored_mail(list(emails))
        candidates = [
            SplitCandidateResponse(
                role=c.role,
                req_id=c.req_id,
                message_ids=[e.message_id for e in c.emails],
                retains_row=(index == 0),
            )
            for index, c in enumerate(clusters)
        ]

    return ApplicationDetailResponse(
        application=serialized, messages=messages, split_candidates=candidates
    )


@router.post("/{application_id}/split", response_model=list[CloudApplicationResponse])
async def split_application_cloud(
    application_id: int,
    user_id: uuid.UUID = Depends(current_user),
) -> list[CloudApplicationResponse]:
    """Split a merged row into the applications its own mail describes.

    The migration path for rows filed before an application was identified by
    employer AND role. It reads only what is already stored — every contributing
    message kept its subject and snippet — so it needs no Gmail call, no scan
    budget, and no rebuild. That matters: a rebuild is the only other route, it
    reads as destructive, and a bounded scan may not even reach the mail in
    question.

    Conservative by construction:

    - The row is retained for its EARLIEST cluster, so its id survives and every
      contact, interview and user correction stays attached to the application
      that has been on the board longest.
    - EVERY row's status is recomputed from its own mail rather than inherited —
      the siblings' and the retained row's alike. The row may already be
      terminal, and a terminal status is never left, so inheriting would give
      every sibling one requisition's rejection; leaving the retained row alone
      (which is what it used to do) leaves that same rejection on the one row
      whose remaining mail no longer contains it. The retained row is recomputed
      only when it is still sync-owned — a stage the user set survives a split.
    - Nothing is deleted and no mail is discarded: the messages are re-pointed,
      and anything that names no role stays with the retained row.

    409 when there is nothing to split, which is the common case and not an
    error the caller should treat as a failure.
    """

    account_email = await _connected_account_email(user_id)

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
                select(Email).where(
                    Email.user_id == user_id, Email.application_id == application_id
                )
            )
        ).all()
        clusters = cluster_stored_mail(list(emails))
        if len(clusters) < 2:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This application's mail describes a single application.",
            )

        retained, siblings = clusters[0], clusters[1:]

        app.req_id = retained.req_id
        app.role_token = retained.role_token
        if retained.role:
            app.position = retained.role
        # The retained row's stage is recomputed from its OWN remaining mail for
        # exactly the reason each sibling's is. A merged row is ``rejected`` if
        # ANY of its linked mail is a rejection, so splitting off the requisition
        # the rejection actually belonged to used to leave the retained row
        # terminally rejected with no rejection of its own — and a terminal
        # status is never left, so no later sync could repair it. Gated like
        # every other automated stage write: a stage the user set is theirs, and
        # a split does not get to overrule it.
        if _is_auto_row(app.source):
            app.status = ApplicationStatus(_status_from_mail(retained.emails))
        app.updated_at = datetime.utcnow()
        session.add(app)

        created: list[Application] = []
        for cluster in siblings:
            row = Application(
                user_id=user_id,
                company=app.company,
                position=cluster.role or _NO_ROLE,
                status=ApplicationStatus(_status_from_mail(cluster.emails)),
                applied_date=(
                    cluster.earliest.date() if cluster.earliest != datetime.max else None
                ),
                # The split is a decision the user made, so the siblings are
                # user-owned and sticky — a later sync advances them from mail
                # but never rewrites the stage.
                source=SOURCE_GMAIL_USER,
                url=pipeline.gmail_deeplink(
                    thread_id=cluster.emails[0].thread_id,
                    message_id=cluster.emails[0].message_id,
                ),
                req_id=cluster.req_id,
                role_token=cluster.role_token,
            )
            session.add(row)
            await session.flush()
            for email in cluster.emails:
                email.application_id = row.id
                session.add(email)
            created.append(row)

        await session.commit()
        for row in created:
            await session.refresh(row)
        await session.refresh(app)

        logger.info(
            "Split application_id=%s for user_id=%s into %s applications (retained %s)",
            application_id,
            user_id,
            len(created) + 1,
            app.id,
        )
        return [_serialize(row, account_email) for row in (app, *created)]


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


@router.put("/{application_id}/deadline", response_model=CloudApplicationResponse)
async def set_application_deadline_cloud(
    application_id: int,
    data: ApplicationDeadlineUpdate,
    user_id: uuid.UUID = Depends(current_user),
) -> CloudApplicationResponse:
    """Set or clear when something is due on this application.

    A date written here is the USER's, and is marked as such: later syncs will
    refresh a deadline that came from mail as newer mail supersedes it, and will
    never touch this one. Sending ``null`` clears both the date and its origin,
    because a source without a date is a claim about nothing.

    404 when the row is not the caller's.
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
        due = pipeline.to_naive_utc(data.due_at) if data.due_at is not None else None
        app.due_at = due
        app.due_source = DUE_FROM_USER if due is not None else None
        app.updated_at = datetime.utcnow()
        session.add(app)
        await session.commit()
        await session.refresh(app)
        return _serialize(app)


@router.post("/{application_id}/dismiss", response_model=dict)
async def dismiss_application_cloud(
    application_id: int,
    user_id: uuid.UUID = Depends(current_user),
) -> dict[str, object]:
    """'Not an application / dismiss' — take the row off the board + train it.

    Reversible: the row leaves the board and the summary but is not deleted, so
    ``POST /applications/{id}/restore`` brings it back intact.
    """

    async with get_session() as session:
        ok = await dismiss_application(session, user_id, application_id)
    if not ok:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Application not found."
        )
    return {"dismissed": True, "restorable": True}


@router.post("/{application_id}/restore", response_model=CloudApplicationResponse)
async def restore_application_cloud(
    application_id: int,
    user_id: uuid.UUID = Depends(current_user),
) -> CloudApplicationResponse:
    """Undo a removal — put a dismissed row back on the board, intact.

    Works for both kinds of removal (a user dismiss and a re-sync's automatic
    one), because neither deletes anything. 404 when the row is not the
    caller's. Idempotent on a row that is already live.
    """

    async with get_session() as session:
        app = await restore_application(session, user_id, application_id)
    if app is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Application not found."
        )
    return _serialize(app)


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
