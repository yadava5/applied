"""The ``/applications`` router — every query scoped by ``user_id``.

This began as the minimum-viable scoped endpoint wired in C3 to prove the
``current_user`` + ``user_id`` pipeline works end-to-end, alongside an
unscoped desktop twin in ``jobtracker.api.applications``. That twin was
deleted (issue #73) along with ``apps/macos``, so this is now the only
``/applications`` router in the tree and there is nothing left to port.

Why this package rather than a shared router with a deployment branch?
----------------------------------------------------------------------

- A per-endpoint ``Depends(current_user)`` branch inside one shared
  router would bifurcate every handler, and a handler that forgets the
  branch is a cross-tenant read. Mounting this package with a
  router-level ``require_user()`` dependency means no individual handler
  can accidentally skip auth.
- The cloud import graph must stay thin. The desktop package eagerly
  imported every router in it, dragging in ``jobtracker.credentials`` →
  ``keyring`` and other Keychain-only deps that have no place in a
  serverless bundle with a 250 MB ceiling.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import delete as sa_delete
from sqlalchemy import exists, func, or_
from sqlalchemy import update as sa_update
from sqlmodel import select

from jobtracker.auth import current_user, require_user
from jobtracker.cloud import pipeline

# RE-EXPORTED, not re-declared. The number and its derivation live in
# ``cloud.pipeline`` because this module imports that one and the reverse would
# cycle. Two tests import it from here by name, and #581 asks for one number in
# one place, so the alias stays.
from jobtracker.cloud.pipeline import _MAX_COMPANY_LEN
from jobtracker.database import get_session
from jobtracker.database.models import (
    APPLICATION_STATUSES,
    CATEGORY_TO_STATUS,
    DEFAULT_APPLICATION_STATUS,
    Application,
    ApplicationStatus,
    ClassificationMethod,
    Contact,
    Email,
    EmailCategory,
    EmailEmbedding,
    EmailSource,
    Interview,
    ReviewDisposition,
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

# Who set the ROLE.
#
# THE ORIGINAL JUSTIFICATION HERE WAS FALSE AND IS CORRECTED (#543). It read
# that nothing in the Gmail path can ever supply a role because
# ``format=metadata`` fetches no body and ATS subjects name only the employer.
# The fetch is ``format="full"`` (``cloud/gmail_client.py:17``, ``:521``,
# ``:907``) and has been for longer than this comment has been wrong, and the
# lead- and trailing-segment readers do resolve roles from subjects (#553,
# #626) at 40 fire / 40 exact / 0 wrong on the corpus. The sibling docstring at
# ``cloud/gmail_client.py:1121-1128`` already corrected the same claim; this
# site and its twin in ``database/models.py`` were missed.
#
# The column survives the correction because its real reason was never the
# extraction gap: a title a human typed must not be overwritten by the next
# sync, and now that the sync can produce a title, that matters more rather
# than less.
#
# NULL means the sync owns the field, which is the state of every row that
# exists today; ``user`` means a human typed it and the sync must not argue.
# There is deliberately no ``mail`` counterpart — unlike ``due_source``, the
# only question anyone asks of this column is "may the sync write here?", and a
# value written at four creation sites to answer a question nobody asks is four
# places to drift.
#
# Only the ROLE is claimed. See :func:`record_role_correction` for why this is a
# column of its own rather than the ``source`` flip a status correction uses.
ROLE_FROM_USER = "user"

# A job title is a line of text, not a document. Nothing downstream truncates
# ``position`` and the column is unbounded TEXT, so the ceiling lives at the
# write.
_MAX_ROLE_LEN = 200


# Notes are prose a person types, and unindexed, so no engine limit applies.
# This is here for the same reason every string on ``PipelineItemIn`` is bounded:
# Pydantic materialises the whole body before a field is read, so an unbounded
# string is memory the process allocates on the caller's say-so inside a
# function with a fixed memory ceiling.
_MAX_NOTES_LEN = 10_000

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


def _user_dismissed(app: Application) -> bool:
    """Did a HUMAN take this card off the board — as opposed to a re-sync?

    The in-Python twin of the ``dismissed_reason == DISMISSED_BY_USER`` arm of
    :func:`_filed_on_an_application_that_answers`. Two spellings of one idea is
    what #596 was about, so they are stated once each and cross-referenced: the
    predicate is SQL because it runs inside an ``EXISTS``, this is Python
    because its callers hold ORM rows they have already loaded. Both read the
    same column against the same constant.

    ``dismissed_at`` is tested as well as the reason, so a LIVE row carrying a
    stale reason string can never read as dismissed. NULL reason on a dismissed
    row answers False — machine-dismissed, the safe direction, for the reason
    the predicate's docstring gives.
    """

    return app.dismissed_at is not None and app.dismissed_reason == DISMISSED_BY_USER


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


def _scan_contradicts(
    emails: list[Email],
    coverage: ScanCoverage | None,
    unsure: frozenset[str] = frozenset(),
) -> bool:
    """Did this scan READ a row's own evidence and disagree with it?

    The one honest test for "this application is stale". The caller has already
    established that the freshly-rolled set does not name the row's company;
    that on its own is worth nothing, because a scan that cannot see a message
    reports the same emptiness as a mailbox that no longer contains it. What
    turns silence into evidence is the scan having re-read the very messages the
    row was filed from and no longer concluding an application from them — a
    classifier correction, which is the case the rebuild exists to clean up.

    Four ways a row survives, each one a thing the scan cannot prove:

    1. No coverage at all (an empty scan) — it observed nothing.
    2. No linked email — there is no evidence to re-read, so staleness is
       unprovable by construction. (Includes rows filed before this column
       existed and rows whose mail was pruned.)
    3. ANY linked email whose id is missing from what the scan returned. The
       test is MEMBERSHIP, not dates: a scan that read one of a row's messages
       has read one of a row's messages, and the rest are as unobserved as they
       would be after an empty scan.
    4. ANY linked email the scan sent to the REVIEW QUEUE. See below.

    Unsure is not disproven
    -----------------------

    A message is absent from the rolled set for two very different reasons, and
    only one of them is a correction. The classifier may now say the message is
    NOT an application — that is the case this function exists for. Or its
    confidence may simply have fallen under the 0.85 gate, in which case the
    pipeline routes it to the review queue and the rollup never sees it. The
    second is the scan saying "I do not know", and the caller's premise —
    "no longer concluding an application" — is then false.

    FOUND ON PRODUCTION, 2026-08-22. A rebuild took the owner's Microsoft
    application off the board while the very message it was filed from sat in
    the review queue at 80%, four points under the gate. Nothing had disproved
    it; the classifier had become less certain, and less certain removed a card.
    That is the archived-mail defect one level up: there, silence was read as
    absence, and here, hesitation is.

    The receipt made it recoverable and not silent, which is the only reason
    this was a defect and not a repeat of 2026-08-10. It still must not happen:
    the whole point of a review queue is that an uncertain verdict costs the
    user a decision, not an application.

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
    if any(e.message_id in unsure for e in emails):
        return False
    if not all(e.message_id in coverage.message_ids for e in emails):
        return False
    return all(coverage.covers(e.received_at) for e in emails)


# There is deliberately no ApplicationStatus → training-label map here any
# more. A stage is a fact about an APPLICATION; a training example is a claim
# about one MESSAGE, and the two do not convert. The map that used to sit here
# ran on every status correction and wrote a label for every linked email:
# ``rejected`` turned an assessment-invite message into a ``rejection`` example
# (``training_data`` id 2 in production), and ``withdrawn``/``ghosted`` mapped
# to ``other``, so recording that you never heard back taught the classifier
# that the genuine confirmation was not job mail. Per-message labels come from
# the review queue (:func:`classify_review_item`), where the user is actually
# answering "what is this message?".


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

# The mail listing pages smaller than the board does: a message row carries a
# subject and a snippet, so 50 of them is already a heavier response than 100
# applications. Same MAX_PAGE_SIZE ceiling.
DEFAULT_MAIL_PAGE_SIZE = 50

# The most linked messages either mail-reading path will load for ONE
# application (issue #293). Both reads were unbounded: "every email on this
# application", with no LIMIT, ordered and then clustered in Python. Bounded by
# one application's own mail, so it is not a tenant leak — but an unbounded read
# is a latent outage rather than a slow page, and nothing in the product stops a
# rebuild from linking a thousand messages to one employer.
#
# Sized FAR above any plausible answer, on the same reasoning as
# ``_COMPANY_ROWS_CAP``: the owner's whole mail table is 52 rows and the largest
# single application on it holds a handful. This is a rail, not a business rule.
#
# It is deliberately not tight, because truncating this read is not "shows fewer
# messages" — it is a WRONG answer. ``cluster_stored_mail`` sorts clusters by
# their EARLIEST message and gives the row to cluster 0, and both reads order
# newest-first, so a cap drops exactly the mail that decides which cluster keeps
# the application id. Every caller therefore checks
# :func:`_application_mail_truncated` and refuses to reason about a split from a
# truncated set rather than proposing one.
_APPLICATION_MAIL_CAP = 1000

def _week_start(today: date) -> date:
    """The Monday that begins ``today``'s week — the "this week" boundary.

    A REAL CALENDAR WEEK, and it was a trailing seven days until #519. The
    owner reported the rolling window as wrong: a week is the unit people
    apply in, and on a Monday it is supposed to start over. "How many in any
    seven days" is a different question and nobody plans by it.

    MONDAY rather than Sunday, and that is read off the product rather than
    picked: the momentum strip on the same screen already draws a gap before
    every Monday bar (``PulseDetail.tsx``), so a Sunday-start count would have
    disagreed with the picture beside it. ``date.weekday()`` is 0 on a Monday
    and the frontend's ``weekdayOf`` — ``(days_since_epoch + 3) % 7`` — is 0 on
    a Monday too, so the two sides share the convention rather than each
    choosing one.

    THE TWIN IS ``weekStartOf`` in ``apps/web/lib/dashboard/age.ts``, and the
    two are held together by a table of days asserted on both sides:
    ``tests/test_this_week_is_a_calendar_week.py`` here,
    ``tests/unit/week-boundary.test.mjs`` there. They cannot literally share an
    implementation across Python and TypeScript; they can be made to fail
    together, which is the next best thing and is what this repo's scar from
    two independent derivations of one number asks for.

    UTC, AND SINCE #518 THAT IS THE DEFAULT RATHER THAN THE ANSWER. The momentum
    caption on the same screen reads ``useLocalToday()`` — the reader's own day
    — because "what have I filed this week" is a question about the week they
    are living in, and the bars beside the caption bucket on that same day.
    This function is handed ``datetime.utcnow().date()`` on any request that
    says nothing about the reader, which is every server render: at first paint
    the server does not know the zone, so UTC is the only day it can name
    without inventing one.

    For a reader west of UTC that used to be the whole story, and it was wrong
    for the width of their offset every week — Sunday 20:00 to midnight in
    Eastern, where this tile had rolled into the new week and the caption below
    it had not. Under the trailing window the same split moved a single day's
    filings and was invisible; a calendar boundary made it a whole week's worth.

    The reader's Monday travels on the wire now. ``GET /applications/summary``
    takes an optional ``week_start`` (:func:`_reader_week_start` states what it
    will accept), the client sends it once it has hydrated and knows the zone,
    and the response reports which Monday it counted. This function is still
    the only definition of where a week begins: it computes the SSR answer AND
    it is what a supplied Monday is validated against.
    """

    return today - timedelta(days=today.weekday())


#: How far a client-supplied ``week_start`` may sit from the server's own, in
#: days. DERIVED rather than picked: UTC offsets run from -12 to +14, so a
#: browser's local calendar day is at most one day either side of the UTC day,
#: and therefore the reader's Monday is the server's Monday, the one before it
#: or the one after it — never further. It also absorbs a request that crosses
#: midnight in flight, which moves the server's Monday by exactly seven days.
_WEEK_START_SLACK_DAYS = 7


def _reader_week_start(value: str | None, utc_today: date) -> date | None:
    """The reader's own Monday, taken off the query string — or 422 (#518).

    ``None`` when nothing was supplied, which is every server render and the
    hydrating pass: the caller gets :func:`_week_start` of the UTC day instead.

    REJECTED, NEVER SNAPPED — for all three ways a value can be wrong. This
    parameter is not authored by a person; it is
    ``weekStartOf(localTodayISO())`` in ``apps/web/lib/dashboard/readerWeek.ts``,
    machine-generated from a clock. A value that is not a Monday, or that names
    a week the reader cannot be standing in, is therefore a bug in the caller
    or a request no browser made, and snapping it to the nearest Monday would
    answer a question nobody asked while the client rendered the number as
    though it had. That is this repo's "two renderers, one number" scar in a
    new place. A refusal is the safe failure instead: the client keeps the
    server-rendered UTC answer it already has on screen, which is exactly what
    it displayed before this parameter existed.

    THE THREE REFUSALS.

    * NOT A DAY. ``pattern`` on the ``Query`` admits only ``YYYY-MM-DD`` —
      deliberately narrower than either ``date.fromisoformat`` (which also
      takes ``20260824`` and ``2026-W35-1`` on 3.11) or pydantic's ``date``
      (which also takes ``2026-08-24T00:00:00``). One spelling on the wire
      means one thing to compare. This function still parses, because
      ``2026-02-30`` satisfies the pattern and is not a date.
    * NOT A MONDAY. ``date.weekday() == 0``, the same convention
      :func:`_week_start` and the frontend's ``weekdayOf`` share.
    * NOT A WEEK THIS READER CAN BE IN. Bounded by
      :data:`_WEEK_START_SLACK_DAYS` against the server's own Monday, so an
      account cannot be made to report a count for an arbitrary historical or
      future week through a parameter added to fix a timezone seam.
    """

    if value is None:
        return None

    try:
        requested = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"week_start must be an ISO-8601 calendar date (YYYY-MM-DD); "
                f"got {value!r}."
            ),
        ) from exc

    if requested.weekday() != 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"week_start must be a Monday — a week begins on one here, and "
                f"{requested.isoformat()} is a "
                f"{requested.strftime('%A')}. It is not snapped to the nearest "
                f"Monday: this value is derived from the reader's clock, so a "
                f"non-Monday means the caller is wrong and the count would "
                f"answer a question it did not ask."
            ),
        )

    server_week_start = _week_start(utc_today)
    drift = abs((requested - server_week_start).days)
    if drift > _WEEK_START_SLACK_DAYS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"week_start must name the week the reader is actually in: "
                f"{requested.isoformat()} is {drift} days from this server's "
                f"week start ({server_week_start.isoformat()}), and no "
                f"timezone puts a reader more than "
                f"{_WEEK_START_SLACK_DAYS} days away."
            ),
        )

    return requested


def _application_mail_truncated(
    emails: list[Email], user_id: uuid.UUID, application_id: int, surface: str
) -> bool:
    """Say so — loudly — if :data:`_APPLICATION_MAIL_CAP` actually bound.

    The mirror of :func:`_warn_if_capped`, for the same reason: a truncated read
    is not a slow query, it is a wrong one, and a cap that truncates in silence
    is the shape this codebase keeps finding under "checks that cannot fail".
    At 52 stored messages this can never fire, which is exactly why it has to be
    audible if it ever does.
    """

    if len(emails) < _APPLICATION_MAIL_CAP:
        return False
    logger.warning(
        "Mail for application_id=%s (user_id=%s) hit its %s-message cap on %s. "
        "The oldest messages were NOT read, so any split proposed from this set "
        "would file mail under the wrong row; the split is being withheld. "
        "Raise _APPLICATION_MAIL_CAP.",
        application_id,
        user_id,
        _APPLICATION_MAIL_CAP,
        surface,
    )
    return True


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

    THE THREE FREE-TEXT FIELDS ARE BOUNDED HERE, ON THE REQUEST, and not on
    :class:`~jobtracker.database.models.Application`. The table model is written
    by the sync as well as by this endpoint, and the failure being fixed is that
    an oversized ``company`` reached the INSERT and broke it on production
    Postgres while answering 201 on SQLite (issue #406). A bound on the wire
    refuses it with a 422 before anything is allocated or written, and says so
    in the OpenAPI document the web app's bindings are generated from — the same
    argument :class:`ApplicationRoleUpdate` makes for ``role``.

    ``position`` takes ``_MAX_ROLE_LEN`` rather than a number of its own,
    because ``ApplicationRoleUpdate.role`` writes THE SAME COLUMN: two different
    ceilings on one field would mean a title this endpoint accepts that the
    PUT then refuses.
    """

    company: str = Field(max_length=_MAX_COMPANY_LEN)
    position: str = Field(max_length=_MAX_ROLE_LEN)
    status: ApplicationStatus = ApplicationStatus.APPLIED
    notes: str | None = Field(default=None, max_length=_MAX_NOTES_LEN)
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
    # Who named the role: ``user`` when a human typed it, null when the field is
    # still the sync's. Sent for the same reason ``due_source`` is — the UI has
    # to be able to say whose word a value is without guessing. Issue #543: an
    # empty role is NOT a permanent fact about Gmail-sourced rows. Extraction
    # fills one when it can (:2197, :2804-2826), so a blank field means the mail
    # named no title this sync could read, and a later sync may fill it.
    position_source: str | None = None


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


class ApplicationRoleUpdate(BaseModel):
    """Body for setting or clearing the role a human typed (issue #72).

    ``None`` — or a string that is only whitespace — clears it. Same rule as the
    deadline: set and clear are one decision, and here clearing matters more,
    because once the field is the user's the sync may no longer correct a typo
    in it.

    ``max_length`` is on the wire rather than in the handler so a title that is
    plainly a paste of a whole job description is refused by the schema, and
    says so in the OpenAPI document the web app's bindings are generated from.
    """

    role: str | None = Field(default=None, max_length=_MAX_ROLE_LEN)


class StatusVocabularyResponse(BaseModel):
    """The canonical stage vocabulary, served so no client has to restate it.

    Every field is DERIVED from :class:`ApplicationStatus` /
    :data:`CATEGORY_TO_STATUS` at import time, so this endpoint and the 422 a
    bad ``PATCH`` earns cannot disagree. It exists because they did: three
    hand-written copies of the vocabulary, all different — the board's card
    offered a value the API refused, the file-by-hand dialog offered fewer than
    the API accepted, and only the enum was right.

    - ``statuses`` — the settable stages, in lifecycle order. THE list.
    - ``default`` — what a new row starts at.
    - ``category_to_status`` — how a classifier verdict maps onto a stage, for
      a client that wants to file mail under the stage it implies (an
      ``interview`` message means the row is ``interviewing``). A category
      absent from this map asserts no stage.
    - ``classifier_categories`` — everything the classifier can emit. A
      SUPERSET of the mapping's keys and NOT interchangeable with ``statuses``;
      confusing the two is the original defect. They overlap on ``applied`` and
      — since 2026-08-12 — ``assessment``, which is precisely when the two get
      conflated again, so both lists keep being served.
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
    # What the classifier thinks this is — a PROPOSAL, never a decision. The
    # queue already reported ``confidence``, so it was showing the strength of
    # an opinion whose content it did not have. None means the row predates the
    # column or genuinely carries no proposal; it is not "unknown category".
    suggested_category: str | None = None
    # WHICH APPLICATION this entry is about, when the mail names one — issue
    # #454. The queue now shows one entry per (conversation, application), so an
    # ATS thread legitimately produces several rows whose SUBJECT and SENDER are
    # byte-identical: "Thank you for applying to Verkada", four times. Without
    # this the four are indistinguishable in the accessible name, which is the
    # exact defect the `sr-only` label on the category select was added to fix,
    # returning in a new form.
    #
    # Derived from the same text the dedup key reads, so the row cannot display
    # one application and be filed under another.
    role: str | None = None
    # WHY this message is waiting for a human — one of ``pipeline.HOLD_REASONS``.
    #
    # It is here because the web used to GUESS it from ``confidence`` alone and
    # told every confident held row that its employer could not be named (#507).
    # Two of the three rows on the owner's board that said so named their
    # employer in the subject line directly above the sentence denying it.
    #
    # ``None`` means this deployment could not derive one. The web must render
    # nothing for that rather than falling back to a guess, which is the whole
    # defect this field exists to remove.
    hold_reason: str | None = None
    # The employer the BODY names, when the filing path could not name one —
    # i.e. only ever alongside ``hold_reason == "confirm_employer"``.
    #
    # It travels with the reason rather than being re-read in the web for the
    # same reason the reason itself does: a second reading of the same message
    # by different code is how the queue came to print a sentence that
    # contradicted the row above it. This is DISPLAY grade — a name to put in
    # front of the user to confirm, never a name anything files under.
    suggested_employer: str | None = None


class ReviewQueueResponse(BaseModel):
    """The needs-classification queue for the authenticated user."""

    items: list[ReviewItemResponse]
    total: int


class MailMessageResponse(BaseModel):
    """One stored message in the full mail listing.

    Deliberately METADATA ONLY. ``snippet`` is the persisted ``body_snippet``
    and there is no field for ``body_text`` or ``body_html``: the cloud sync
    never fetches a body and this listing is not the place to start.

    ``category``/``confidence``/``method`` are the stored verdict verbatim —
    ``classified_as``, ``classification_confidence``, ``classification_method``
    — so a reader can see WHAT was decided and HOW, which is the difference
    between "the machine says applied" and "a rule matched at 0.71".

    ``category`` carries the enum's own value (``"applied"``, ``"needs_review"``
    …), the same lowercase vocabulary ``?category=`` accepts and
    ``POST /review/{message_id}/classify`` takes back. One vocabulary end to
    end, so a value read here can be sent straight back as a correction.
    """

    message_id: str
    thread_id: str | None = None
    subject: str | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    received_at: str | None = None
    snippet: str | None = None
    category: str | None = None
    confidence: float | None = None
    method: str | None = None
    user_corrected: bool = False
    # WHICH act the human performed — ``"confirmed"``, ``"overridden"``,
    # ``"unattributed"`` or ``"unknown"``. ``user_corrected`` says only THAT a
    # human settled the row; a client rendering "corrected by you" off it alone
    # is telling half the users who touched a row that they overruled a machine
    # they in fact agreed with. ``None`` means no human decision is recorded;
    # ``"unknown"`` means one is and predates the column. See
    # :class:`~jobtracker.database.models.ReviewDisposition`.
    review_disposition: str | None = None
    is_reviewed: bool = False
    application_id: int | None = None
    # The linked application's employer, resolved in ONE query for the whole
    # page (never per row). ``None`` when the message is not filed against an
    # application — which most needs-review mail is not.
    company: str | None = None
    # Is the linked application actually ON THE BOARD right now?
    #
    # NOT the same question as ``application_id is not None``, and the web app
    # answered the wrong one for every dismissed row (#489). Dismissal is
    # deliberately not a delete (see the module note at the top of this file):
    # the row goes off the board, keeps its id, and KEEPS ITS EMAILS. So a
    # message whose application was removed still carries a link, and a client
    # reading only that link tells the user the mail is "on your board" while
    # the board does not contain it.
    #
    # Found in production 2026-08-23 on the owner's account: the one
    # needs-review message pointed at application 115, dismissed by a rebuild
    # the day before, and the Inbox said "on your board".
    #
    # ``application_id`` is deliberately still populated for a dismissed row —
    # it is what a restore/undo surface needs, and blanking it to fix a LABEL
    # would break recovery. The two facts are reported separately because they
    # are two facts.
    on_board: bool = False
    # The employer TOKEN :func:`pipeline.resolve_employer` names for this
    # message, or ``None`` when it refuses to name one. Computed for EVERY row,
    # linked or not.
    #
    # WHY IT IS NOT ``company``. ``company`` above is the LINKED application's
    # display name, so it is populated only on rows that already have an
    # answer. The surface that needs an employer is the opposite population:
    # the filed ledger asks "which application is this about?" precisely on
    # UNLINKED rows, where ``company`` is null by construction. A client
    # matching on ``company`` therefore cannot match anything it would ever
    # ask about, which is what shipped and what this field replaces.
    #
    # WHY THE TOKEN AND NOT THE DISPLAY NAME. It is the match key
    # :func:`_company_rows` and :func:`_chosen_application` narrow on, so a
    # client that offers the rows matching this token offers exactly the rows
    # the backend would accept as an answer. Compared against a stored row's
    # name by :func:`pipeline.matches_company_token` — see that function for
    # the rule and for the web mirror of it.
    #
    # FILING GRADE, USED AT DISPLAY GRADE, which is the safe direction:
    # ``resolve_employer`` reads only the sender's own domain, the subject and
    # (for relays) the display name. It never reads the body or the snippet, so
    # nothing here stamps a row with something the decider did not read.
    employer_token: str | None = None
    gmail_link: str | None = None


class MailListResponse(BaseModel):
    """A page of the user's stored mail, plus the counts the chips need.

    ``total`` is the size of the CURRENT query — it respects both ``category``
    and ``q``, because it is the number ``page``/``page_size`` walk.

    ``category_counts`` is deliberately different: it respects ``q`` but NOT
    ``category``, so each filter chip can show its own total while one of them
    is active. Counting only the filtered set would make every chip but the
    selected one read zero.
    """

    messages: list[MailMessageResponse]
    total: int
    page: int
    page_size: int
    category_counts: dict[str, int]


class ScannedMessageIn(BaseModel):
    """The metadata needed to STORE a message the live scan has only mined.

    The live-scan view (``/inbox?view=scan``) reads Gmail directly and holds
    nothing: its rows are verdicts about messages this database has never seen.
    Correcting one of them therefore has to persist the message first, or the
    correction lands on a row that does not exist — ``classify_review_item``
    answers 404 and the user's click does nothing.

    Filing first is NOT a substitute. ``pipeline.collect_review_items`` keeps
    only ``needs_review`` mail and lifecycle mail at/above the 0.70 review
    floor, so the exact case this exists for — an assessment email the
    classifier called ``other`` at 0% — is dropped by ``POST /gmail/sync`` and
    can never be reached by a correction. The user can see the row; nothing in
    the product could store it.

    ``received_at`` is REQUIRED and is never defaulted to "now": ``Email``
    requires a receive time and :func:`_persist_message_refs` deliberately skips
    undated messages rather than fabricating one. A client that has no date for
    a row must not offer the correction at all.

    ``category``/``confidence``/``method`` are the classifier's verdict AS THE
    SCAN SHOWED IT. They are stored on the minted row so it starts out as a
    faithful copy of what the user was looking at — the same thing a sync would
    have written — and the correction is then applied on top of it, leaving the
    normal "was X, user says Y" trail instead of a row that claims the user's
    label was the machine's all along.
    """

    # EVERY STRING BOUNDED, matching :class:`PipelineItemIn` field for field —
    # same rationale, and these are the same values off the same mail. They are
    # NOT bounded at ``_MAX_COMPANY_LEN``: a sender name is what an employer is
    # extracted FROM, not an employer, and 300 would refuse real mail. The
    # employer bound is applied where the display is produced, not here.
    #
    # Unbounded, these were the second half of #581. ``company`` next door was
    # the half the issue named, but ``sender_email`` and ``sender_name`` reach
    # the same indexed column through :func:`pipeline.resolve_employer`, which
    # is minted from this model at the review-classify endpoint.
    sender_email: str = Field(max_length=512)
    received_at: datetime
    subject: str | None = Field(default=None, max_length=2000)
    sender_name: str | None = Field(default=None, max_length=512)
    thread_id: str | None = Field(default=None, max_length=256)
    snippet: str | None = Field(default=None, max_length=2000)
    category: EmailCategory | None = None
    confidence: float | None = None
    method: str | None = Field(default=None, max_length=64)


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

    ``message`` is what makes the same correction possible from the LIVE SCAN,
    whose rows may never have been stored (see :class:`ScannedMessageIn`).
    Consulted only when this message id is not already on file; a stored message
    is always corrected in place, so a client cannot use this to rewrite one.

    ``confirm_new_company`` is the answer to "did you mean the one already on
    your board?". A ``company`` one edit away from a stored employer stops and
    asks rather than opening a second row under the new spelling (see
    :func:`_misspelled_employer`); this flag is the human saying no, these really
    are two employers. Deliberately an explicit acknowledgement and not a
    default: the whole point is that the typo was accepted silently once.

    ``none_of_these`` is the OTHER answer to "which of these is it about?", and
    it needs a field of its own because an absent ``application_id`` cannot
    carry it. Absent means "nobody asked" — the single-candidate queue rows, the
    mail reclassify surface, the live scan — and the honest answer to silence is
    the tie-break in :func:`_pick_application`. It is the wrong answer to a
    person saying "not one of those": for a rejection the tie-break moves a LIVE
    application to a terminal status, and ``advance_application_status`` never
    walks a terminal status back. Reading the two as one value is #554.
    """

    category: EmailCategory
    # Bounded for the same reason ``CloudApplicationCreate.company`` is, and
    # with the same number: this field reaches the same indexed column through
    # :func:`pipeline.employer_from_text`. A refusal at the door names the
    # problem; the alternative is a 500 raised by the btree (#581).
    company: str | None = Field(default=None, max_length=_MAX_COMPANY_LEN)
    application_id: int | None = None
    message: ScannedMessageIn | None = None
    # ``StrictBool`` on both, because the "only a literal true is an answer"
    # rule is enforced in `readClassifyBody` — which is the PROXY, not this
    # boundary. Pydantic's default mode coerces ``"true"``, ``"false"`` and
    # ``1``, so a caller reaching the API directly could turn the string
    # ``"false"`` (truthy) into an answer nobody gave. One of these flags skips
    # the typo check and the other OPENS A ROW; neither may be manufactured.
    confirm_new_company: StrictBool = False
    none_of_these: StrictBool = False


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
    #: The Monday ``this_week`` was counted from: the server's UTC Monday
    #: unless the caller supplied its own (``?week_start=``). Reported rather
    #: than left implicit because the client's correction turns on it (#518) —
    #: the browser compares the reader's Monday against the one that was
    #: ACTUALLY counted and only re-asks when the two differ. Re-deriving it in
    #: the browser from a second clock read is how these two surfaces came to
    #: disagree about one number in the first place.
    week_start: date
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


# The most rows either half of :func:`_company_rows` will load in one call.
#
# Sized FAR above any plausible answer — the owner's whole board is 65 rows and
# the largest single employer on it holds four — so it is a rail against a
# pathological prefix (a one-letter token on a large board), not a business
# rule. It is deliberately not tight: a cap that can silently truncate a real
# answer would re-introduce the bug the comment below spends ten lines on, where
# a lookup that returned a subset of an employer's rows made the resolver mint
# duplicates ("six rows each for IXL Learning and Torc Robotics").
_COMPANY_ROWS_CAP = 500


def _warn_if_capped(
    rows: list[Application], user_id: uuid.UUID, token: str, half: str
) -> None:
    """Say so — loudly — if the rail above actually bound.

    A truncated company lookup is not a slow query, it is a WRONG one: the
    resolver would see fewer rows at an employer than exist and mint a duplicate
    beside them. At 65 rows this can never fire, which is exactly why it has to
    be audible if it ever does — a cap that truncates in silence is the shape
    this codebase keeps finding under "checks that cannot fail".

    The token itself is NOT written to the record. It is a company name lifted
    out of a mail subject, and printing it beside ``user_id`` at WARNING is what
    turns an aggregated log into a statement about where this person applied —
    the single fact the product's privacy page promises to keep. CodeQL reads
    the line as clear-text logging of sensitive data (alert 178) because the
    variable is called ``token``; the NAME is a false positive (it is not a
    credential) and the SUBSTANCE is not.

    What replaces it has to stay actionable, because a warning nobody can act on
    is worse than none. Two facts do that without copying mail text: the token's
    LENGTH, which says whether the cap was hit by a plausible name or by
    something pathological, and one ``application_id`` out of the truncated set.
    The id is opaque, is already logged all over this module, and points at the
    row whose ``company`` column answers "which employer?" — in the database,
    under the user's own RLS policy, rather than in a log with no such scope.
    """

    if len(rows) < _COMPANY_ROWS_CAP:
        return
    logger.warning(
        "Company lookup (%s half) hit its %s-row cap for user_id=%s "
        "(token length %s, e.g. application_id=%s). The resolver is now "
        "reasoning about a TRUNCATED set and may file a duplicate application; "
        "raise _COMPANY_ROWS_CAP.",
        half,
        _COMPANY_ROWS_CAP,
        user_id,
        len(token),
        rows[0].id,
    )


async def _company_rows(session, user_id: uuid.UUID, token: str) -> list[Application]:
    """Every one of this user's applications at the employer named by ``token``.

    One employer can now hold several applications, so the lookup returns the
    whole set and :func:`_resolve_application` decides which one a given piece of
    mail belongs to. The single-row ``.first()`` this replaced silently picked
    one of four Amazon rows and let the other three drift.

    Two queries, so the common case stays index-assisted: exact equality first,
    then a prefix scan over the leading normalized word, confirmed in Python.

    "Index-assisted" was aspirational until migration ``e7a1c4d92b30``. Both
    predicates are over ``lower(company)`` and production's only company index
    was on the RAW column, which cannot answer them — so both were sequential
    scans, on a function called once per rolled cluster inside the upsert loop.
    The functional index that migration adds carries ``text_pattern_ops``,
    without which the prefix half stays a filter rather than an index condition
    under Supabase's ``en_US.utf8`` collation.

    BOTH reads are capped (see ``_COMPANY_ROWS_CAP``). They were unbounded: a
    prefix like ``"a"`` matching a large board loaded every row it touched into
    the session, per cluster, per sync.
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
            .limit(_COMPANY_ROWS_CAP)
        )
    ).all()
    _warn_if_capped(exact, user_id, token, "exact")
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
                .limit(_COMPANY_ROWS_CAP)
            )
        ).all()
        _warn_if_capped(candidates, user_id, token, "prefix")
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


async def employers_with_several_applications(
    session, user_id: uuid.UUID
) -> frozenset[str]:
    """Normalized employer tokens whose board already holds more than one card.

    What a sync knows that :func:`pipeline.partition_applications` cannot. A
    delta is usually one message, so from inside the pipeline an employer with
    four applications and one role-less rejection in today's mail is
    indistinguishable from an employer with one. Handing it this set makes the
    review-queue rule — never guess which of several applications a role-less
    message is about — apply to an incremental sync exactly as it applies to a
    rebuild.

    LIVE rows only, and the count is of rows a user can see: a dismissed
    duplicate is not on the board, and letting one push an employer over the
    threshold would send mail to the queue on the strength of a card that no
    longer exists.

    DELIBERATELY NOT :func:`_filed_on_an_application_that_answers`, and this is
    not an oversight to be tidied away. That predicate answers "does an
    application settle this mail?" and counts a user-dismissed card because a
    human's "no" stands. This one is a VISIBILITY question — "how many cards
    would the user have to choose between?" — and a card they cannot see is not
    one of them. The two sets differ by exactly the hand-dismissed rows (#597).
    """

    companies = [
        company
        for company in (
            await session.exec(
                select(Application.company).where(
                    Application.user_id == user_id,
                    Application.dismissed_at.is_(None),
                )
            )
        ).all()
        if company
    ]

    # COUNTED IN THE TOKEN SPACE THE PIPELINE ACTUALLY USES, which is not the
    # normalized company name. ``resolve_employer`` returns the sender's domain
    # brand or the LEADING WORD of a display name — "Cobalt Ridge" arrives as
    # ``cobalt`` — and ``_company_rows`` matches a stored row on either. Keying
    # this set on the full name instead produced a set that never contained the
    # token being looked up, so the rule silently did nothing: a check that
    # cannot fire, and one that reads as passing.
    #
    # COUNTED BY LEADING WORD, in one pass. ``matches_company_token`` accepts a
    # full match OR a match on the leading word, and a full match implies the
    # leading words are equal too — so the whole predicate reduces to "same
    # leading word", and a histogram answers it. The obvious version (for each
    # candidate token, scan every company) is quadratic in the size of the
    # user's board and runs on every sync; the ten-thousand-message corpus is
    # what made that visible, at 4,770 employers, but the growth is the same
    # shape for a real person who applies a lot.
    counts: Counter[str] = Counter()
    candidates: set[str] = set()
    for company in companies:
        token = pipeline.normalize_company_name(company)
        if not token:
            continue
        lead = token.split()[0]
        counts[lead] += 1
        candidates.add(token)
        candidates.add(lead)
    return frozenset(
        token for token in candidates if counts[token.split()[0]] > 1
    )


async def threads_naming_one_application(session, user_id: uuid.UUID) -> frozenset[str]:
    """Gmail thread ids whose filed mail sits on exactly ONE application.

    The other half of what a delta cannot see. An update that names no role is
    ambiguous at an employer with several cards — unless its own conversation
    already names one of them, which is the ordinary shape of an employer
    replying inside its own confirmation. Without this, every follow-up at a
    multi-application employer went to the review queue, including the ones the
    mail answers by itself.

    UNAMBIGUOUS ONLY, and that restriction is the whole safety of it. A thread
    whose filed mail spans two applications names no single card — the four
    Microsoft confirmations of 21 August share one thread and are four
    applications — so it is left out and the update it carries is asked about,
    which is the same answer :func:`pipeline.partition_applications` gives for
    the same shape in one scan.

    LIVE ROWS ONLY, exactly like its line-mate
    :func:`employers_with_several_applications`, which is read on the very next
    line of ``gmail_oauth`` and handed to the same two functions (#611). Without
    it the two disagreed about one row in one request: a ``resync``-dismissed
    card does not answer for its mail (#596), so the mail must come back and
    ask — while this set said the thread already names one card, and
    ``pipeline`` used that to escape the ambiguous-goes-to-the-queue rule and
    file the message instead.

    DELIBERATELY NOT :func:`_filed_on_an_application_that_answers`, and this is
    the same distinction its line-mate draws. That predicate would KEEP a
    hand-dismissed card's thread, which suppresses the arriving message BY
    THREAD ALONE — and this product's definition of "its mail" is thread PLUS
    identity (``review_dedup_key``), the definition that exists because one
    employer's five messages spanned four roles. At an employer with other live
    cards an identity-less update on a dismissed card's old thread may belong to
    one of THOSE, and settling it on delivery structure alone would drop it
    silently. This is a visibility question — "does a card the user can see own
    this conversation?" — so it gets the visibility test.

    GROUPED UNFILTERED, THEN NARROWED, and the order is load-bearing. Adding
    ``Application.dismissed_at.is_(None)`` to the query above looks equivalent
    and is not: a thread whose mail spans live card B and dismissed card A
    yields two applications today, so it is excluded and the update is asked
    about — the four-Microsoft rule working. Filtered, the same query sees only
    ``{B}``, the thread reads as unambiguous and the message files straight to
    B. That is a LOOSENING shipped inside a narrowing. Counting first and
    keeping only the singletons whose one row is live can only ever shrink the
    set, and leaves mixed threads behaving exactly as they did.

    THE LIVE LOOKUP IS NOT SCOPED BY USER, on purpose. The ids come from mail
    already scoped to ``user_id``; adding the conjunct would additionally drop a
    thread whose mail is linked to ANOTHER user's card, which is a second,
    unrelated behaviour change and not what #611 is about. Live-ness is the only
    new question asked here.

    ASYMMETRIC WITH :func:`_application_in_conversation` ON PURPOSE — do not
    "unify" them. That function is this one's resolve-time twin, asks the same
    "does this conversation name a card?" question, and stays UNFILTERED by
    dismissal because its routing is doctrine-correct in the cases it sees: a
    ``resync``-dismissed card landing mail is the intended resurrect (#595), and
    a hand-dismissed one is stopped one level up by
    :func:`upsert_applications_for_user`'s ``continue`` (#597). Filtering it
    would break the resurrect path. The asymmetry is real because the CALLERS
    differ: this set feeds an escape from the review queue, that one feeds a
    resolver whose caller already reads the reason column.

    SCOPE, which bounds both the defect and the fix: ``known_threads`` is
    consulted only inside ``if token in known_multi and len(keyed) != 1:``, and
    ``known_multi`` is already live-only — so this only ever bites at an
    employer holding two or more LIVE cards, for identity-less non-confirmation
    arrivals.
    """

    rows = (
        await session.exec(
            select(Email.thread_id, Email.application_id).where(
                Email.user_id == user_id,
                Email.thread_id.is_not(None),
                Email.application_id.is_not(None),
            )
        )
    ).all()
    by_thread: dict[str, set[int]] = defaultdict(set)
    for thread_id, application_id in rows:
        by_thread[thread_id].add(application_id)
    names_one = {
        thread_id: next(iter(apps))
        for thread_id, apps in by_thread.items()
        if thread_id and len(apps) == 1
    }
    if not names_one:
        return frozenset()
    # One extra read rather than a join. An outer join would report a DANGLING
    # ``application_id`` as ``dismissed_at IS NULL`` and therefore as live; an
    # inner one would drop the row and change the COUNT above, which is the very
    # thing the paragraph on grouping says must not move. Membership of a set of
    # live ids answers it without touching either.
    live = set(
        (
            await session.exec(
                select(Application.id).where(
                    Application.id.in_(sorted(set(names_one.values()))),
                    Application.dismissed_at.is_(None),
                )
            )
        ).all()
    )
    return frozenset(
        thread_id for thread_id, application_id in names_one.items() if application_id in live
    )


# VISIBILITY, NOT SETTLEMENT — do not move this to
# :func:`_filed_on_an_application_that_answers` (#597). Offering "did you mean
# a card you deliberately removed?" is a worse prompt than opening the new one,
# and its own docstring reasons the live-only choice below.
async def _misspelled_employer(session, user_id: uuid.UUID, token: str) -> str | None:
    """The employer on the board that a NEW ``token`` is probably a typo of.

    Returns the stored spelling to offer back, or None when the token names an
    employer the board already answers to (nothing to ask about) or nothing near
    enough (nothing to offer). The caller must treat a name it returns as a
    QUESTION for the user, never as a row to file against — see
    :func:`pipeline.near_miss_employer`.

    Application 119 on the owner's board is what this exists for: a rejection
    from ``no-reply@us.greenhouse-mail.io`` reached the review queue because the
    relay names no employer, a human typed "Verkeda", and the lookup for token
    ``verkeda`` found none of the four "Verkada" rows — so a status change minted
    a fifth application instead of settling one of them. Identity here is
    employer + (req_id or role); a near miss on the employer half defeats the
    whole key before the other half is ever consulted.

    LIVE rows only. A dismissed row is not on the board, and suggesting its name
    would send the user's next answer onto a row they cannot see (``_company_rows``
    puts live first, so an all-dismissed employer resolves to an invisible one).
    A typo'd re-entry of a dismissed employer therefore mints, which is the
    behaviour that path already had.
    """

    if await _company_rows(session, user_id, token):
        return None
    employers = (
        await session.exec(
            select(Application.company)
            .where(
                Application.user_id == user_id,
                Application.dismissed_at.is_(None),
            )
            .distinct()
        )
    ).all()
    return pipeline.near_miss_employer(token, employers)


async def _resolve_application(
    session,
    user_id: uuid.UUID,
    rolled: pipeline.RolledApplication,
    home: int | None = None,
    blocked: frozenset[int] = frozenset(),
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

    RULE 0, AHEAD OF EVERYTHING: A MESSAGE ALREADY HAS A HOME. ``home`` is the
    row one of this cluster's own messages is already filed against, worked out
    for the whole pass by :func:`_anonymous_homes` before any of it is resolved.
    Since :func:`pipeline.partition_applications` began giving each anonymous
    confirmation its own application, an employer like Google — three
    confirmations, no role, no requisition number, ten days apart — arrives here
    as three clusters that are IDENTICAL under ``(req_id, role_token)``, which is
    every input the cascade below has. The stored link is the only thing left
    that tells them apart, and it is what makes a re-sync idempotent instead of
    filing three more cards.

    ``blocked`` carries the rows that are spoken for: taken by an earlier cluster
    in this pass, or reserved as some other cluster's ``home``. Rule 4 returns
    the employer's oldest row, so without this every anonymous cluster would
    resolve onto the same one and the split would be undone a line after it was
    made. Reserving matters on its own: when a sync's scan window reaches mail an
    earlier one missed, the oldest cluster is no longer the one holding the
    oldest row, and rule 4 would hand it a row that belongs to a different
    application.

    Both are ignored for an identified cluster — it has a real key and does not
    need to guess.
    """

    rows = await _company_rows(session, user_id, rolled.company_token)
    if rolled.req_id is None and rolled.role_token is None:
        if home is not None:
            found = next((row for row in rows if row.id == home), None)
            if found is not None:
                return found
        # A CONFIRMATION IS NEVER ROUTED BY ITS THREAD. It asserts an
        # application, so it opens a card or lands on its own stored one and
        # nothing else; only an update asks "which of these is this about?".
        # The order is what keeps this path agreeing with
        # :func:`pipeline.partition_applications`, which does the same: anchors
        # are placed before threads are consulted, so a second confirmation
        # arriving inside the first one's conversation is two applications on a
        # rebuild and two applications on a delta.
        if any(m.category in pipeline.APPLIED_SIGNAL_CATEGORIES for m in rolled.messages):
            if await _is_a_further_application(session, user_id, rolled, rows):
                return None
        else:
            conversation = await _application_in_conversation(session, user_id, rolled, rows)
            if conversation is not None:
                return conversation
        rows = [row for row in rows if row.id not in blocked]
    return _pick_application(rows, rolled.req_id, rolled.role_token)


async def _application_in_conversation(
    session,
    user_id: uuid.UUID,
    rolled: pipeline.RolledApplication,
    rows: list[Application],
) -> Application | None:
    """The row a filed message of this cluster's own Gmail thread already sits on.

    "More about this one." A thread is how mail was DELIVERED and is never an
    identity — the four Microsoft confirmations of 21 August share one thread
    and are four applications — but where the mail carries no key at all, the
    conversation is the only structure left, and an employer replying inside its
    own confirmation is talking about that application. This is what keeps an
    update from opening a card.

    IT SAYS NOTHING ABOUT A DUPLICATE CONFIRMATION, and it used to claim to be
    "the reason a duplicate confirmation does not mint a second one". No
    confirmation ever reaches this function: :func:`_resolve_application` sends
    a cluster carrying an applied signal to :func:`_is_a_further_application`,
    and conversation routing is the ELSE arm of that branch. A re-sent
    confirmation is kept off the board by rule 0's stored link instead. Prose
    about a state the code cannot reach is how this repository has twice
    acquired a test that greens against nothing.

    Ambiguity is refused rather than guessed: a thread whose filed mail spans
    more than one of this employer's rows names no single card, so it falls
    through to the cascade like any other role-less message. Same rule as
    :func:`pipeline.partition_applications` applies in-scan, and the two must
    agree or a delta and a rebuild produce different boards.
    """

    threads = {m.thread_id for m in rolled.messages if m.thread_id}
    if not threads:
        return None
    by_id = {row.id: row for row in rows if row.id is not None}
    if not by_id:
        return None
    found = (
        await session.exec(
            select(Email.application_id).where(
                Email.user_id == user_id,
                Email.thread_id.in_(sorted(threads)),
                Email.application_id.in_(sorted(by_id)),
            )
        )
    ).all()
    candidates = {application_id for application_id in found if application_id is not None}
    if len(candidates) != 1:
        return None
    return by_id[candidates.pop()]


async def _is_a_further_application(
    session,
    user_id: uuid.UUID,
    rolled: pipeline.RolledApplication,
    rows: list[Application],
) -> bool:
    """Does this cluster ASSERT an application the board does not have yet?

    The incremental half of the rule :func:`pipeline.partition_applications`
    applies in-scan, and it has to exist separately because the two halves see
    different things. A real sync rolls up a DELTA — one message, usually — so
    the partitioner never sees an employer's second confirmation beside its
    first and its "two or more anonymous confirmations" test can never fire.
    Without this, the split worked on a rebuild and did nothing on the syncs
    that actually run, which is how the reported bug survived its first fix.

    A STORED ROW PLAYS THE PART OF THE FIRST ANCHOR. One thing must hold
    before any other is asked: THE CLUSTER CARRIES A CONFIRMATION. A rejection
    or interview invite reports on an application, it does not assert one, so
    it never mints. That test is first because it is what bounds the whole
    rule — an anonymous UPDATE cluster can never reach either branch below,
    which is the unbounded-growth scenario PR #76 fixed and the one #641's fix
    may not reopen.

    Then the BOARD decides which question is being asked, because an
    all-anonymous board and a mixed one carry different evidence.

    **AN ENTIRELY ANONYMOUS BOARD.** One of those anonymous rows must already
    hold a confirmation of its own — without this, a rejection that minted a
    row would make the confirmation following it look like a SECOND application
    and split one card in two, which is the same defect pointing the other way.
    That makes the claim literally true: this employer has an application whose
    confirmation is on the board, and here is another confirmation that is not.
    SOME, not every: here the held confirmation IS the pairing evidence, the
    stored row standing in for the first anchor.

    **A BOARD WHERE SOMETHING IS IDENTIFIED (#641).** This used to return False
    outright, on the argument that a role-less confirmation beside a keyed row
    is far more likely the supporting message rule 3 was written for (Roblox's
    email-verification mail) than a second application. That argument is right
    about ONE row and wrong about several. Where the employer already holds two
    or more live cards, :func:`pipeline.partition_applications` has ALREADY
    given this confirmation its own cluster on the rule "a new confirmation is a
    new application" — and returning False hands it to
    :func:`_pick_application`'s rule 4, which files it onto the employer's
    oldest live row. The partition's decision was honoured one layer up and
    reversed one layer down: no new card, no queue entry, no counter, and a
    whole application invisible.

    IT IS WORSE THAN AN INVISIBLE CARD. Rule 4's oldest live row may be a
    REJECTED one — ``_company_rows`` sorts live-first, and a rejected row is
    live — and a confirmation dated after that rejection then trips
    :func:`_reopening_evidence`, which walks a settled application out of its
    terminal status on a card the mail was never about.

    So on a mixed board, three things:

    * TWO OR MORE LIVE ROWS, counted the way
      :func:`employers_with_several_applications` counts them. LIVE ONLY: a
      dismissed row is not on the board, and letting one push the employer over
      the threshold would turn the Roblox case — one live card with a
      resync-dismissed duplicate beside it — into a minting one.
    * EVERY LIVE ANONYMOUS AUTO ROW ALREADY HOLDS A CONFIRMATION. Vacuously
      true when there are none, which is the ordinary shape of this board. An
      anonymous auto row with no confirmation of its own is plausibly THIS
      acknowledgement's own application — the sync mints one whenever the first
      role-less mail it reads from an employer is a rejection or an assessment,
      and the confirmation that row reports on simply has not been read yet —
      and splitting one application into two cards is what this arm refuses.
      EVERY rather than the some-condition
      above, and the difference is not cosmetic: on the anonymous board a held
      confirmation is evidence FOR a second application, here an unheld row is
      evidence AGAINST one, so one unconfirmed row is enough.
    * AUTO ROWS ONLY, the same restriction rule 3 applies and for the same
      reason (:func:`_is_auto_row`). A MANUAL row is a human's own entry and has
      no linked mail at all; a row :func:`classify_review_item` minted is a
      human's answer to "which application is this about?" and may hold nothing
      but the update they answered. Counting either would make the quantifier
      false FOREVER at any employer holding one — reinstating #641 through a
      side door, with every gate still green. This is the narrowing most likely
      to be dropped as redundant, so it has a control of its own.

    WHEN THE QUANTIFIER DECLINES the fold lands by rule 4 on ``rows[0]``, which
    may be an IDENTIFIED row rather than the unconfirmed anonymous one the
    refusal was about. That is imprecise, and it is written down rather than
    fixed: it is exactly as imprecise as the anonymous branch above, whose fold
    target is also ``rows[0]``. Steering rule 4 would change three call sites
    that are right about their own callers.

    AND A DECLINE CAN STILL COST A REOPEN. Measured, not supposed: where the
    unconfirmed anonymous auto row is ALSO the employer's oldest live row, it is
    rule 4's fold target, and if it is REJECTED with the arriving confirmation
    newer than its stored rejection then :func:`_reopening_evidence` still walks
    it out of its terminal status. So #641 closes that corruption for a settled
    row that holds its own confirmation or names a role — the shapes a board
    normally has, and the ones its controls pin — and leaves it open for a row
    whose only mail is the rejection that minted it. Closing that one means
    steering rule 4, which two other callers depend on, so it is written down as
    the boundary of this fix rather than widened into it. See
    ``test_an_unconfirmed_anonymous_row_holds_the_mint_back``.

    THE REMEDY FOR A SPARE CARD IS A DISMISS CLICK, not a merge. There is no
    merge endpoint in this repository — ``POST /applications/{id}/split`` exists
    and nothing pairs with it — so the direction is chosen knowing that: a spare
    card can be removed, an application that never appears cannot be recovered.
    """

    if not any(m.category in pipeline.APPLIED_SIGNAL_CATEGORIES for m in rolled.messages):
        return False
    if not rows:
        return False  # nothing to be a FURTHER application than; mint normally
    anonymous = [
        row for row in rows if row.req_id is None and row.role_token is None
    ]
    if len(anonymous) == len(rows):
        # THE ANONYMOUS BOARD, unchanged. Left byte-for-byte, including the
        # SOME quantifier, because #641 is about the other board and a fix that
        # quietly re-tuned this one would be two changes wearing one issue
        # number.
        ids = [row.id for row in anonymous if row.id is not None]
        if not ids:
            return False
        held = (
            await session.exec(
                select(Email.id).where(
                    Email.user_id == user_id,
                    Email.application_id.in_(ids),
                    Email.classified_as.in_(
                        [EmailCategory(c) for c in sorted(pipeline.APPLIED_SIGNAL_CATEGORIES)]
                    ),
                )
            )
        ).all()
        return bool(held)

    # THE MIXED BOARD (#641). See the docstring for why each of the three
    # narrowings below is load-bearing on its own.
    live = [row for row in rows if row.dismissed_at is None]
    if len(live) < 2:
        return False
    unconfirmed = [
        row.id
        for row in live
        if row.req_id is None
        and row.role_token is None
        and _is_auto_row(row.source)
        and row.id is not None
    ]
    if not unconfirmed:
        return True
    # Same predicate as the branch above — an Email filed against the row whose
    # committed verdict is an applied signal — quantified the other way. The two
    # category lists must stay identical or the two boards would disagree about
    # what a confirmation is.
    confirmed = (
        await session.exec(
            select(Email.application_id).where(
                Email.user_id == user_id,
                Email.application_id.in_(sorted(unconfirmed)),
                Email.classified_as.in_(
                    [EmailCategory(c) for c in sorted(pipeline.APPLIED_SIGNAL_CATEGORIES)]
                ),
            )
        )
    ).all()
    return set(unconfirmed) <= {row_id for row_id in confirmed if row_id is not None}


async def _anonymous_homes(
    session,
    user_id: uuid.UUID,
    clusters: list[pipeline.RolledApplication],
) -> dict[int, int]:
    """Which stored row each anonymous cluster already owns, by list index.

    Resolved for the whole pass UP FRONT, and that is the point rather than an
    optimisation: a cluster with no link must not be able to take a row that a
    cluster later in the list is already the home of. Doing it inside the loop
    makes the answer depend on position, which is exactly the fragility the link
    exists to remove — an employer whose rows were minted in a different order
    than its mail was received would have its cards silently swap applications.

    A row is the home of AT MOST ONE cluster: where two claim it, the earlier
    index wins and the other mints, so the row that has been on the board stays
    with the application it was about.
    """

    anonymous = [
        (index, rolled)
        for index, rolled in enumerate(clusters)
        if rolled.req_id is None and rolled.role_token is None
    ]
    if not anonymous:
        return {}

    # ONE lookup for the whole pass, not one per cluster. A rebuild rolls up the
    # entire mailbox and can hand this a dozen anonymous clusters; the sync
    # already pays ~216ms per database call, so a per-cluster query would put
    # seconds onto the slowest path in the product for no information a single
    # `IN` cannot return.
    linked = await _linked_applications_by_message(
        session,
        user_id,
        [m.message_id for _index, rolled in anonymous for m in rolled.messages],
    )

    homes: dict[int, int] = {}
    taken: set[int] = set()
    by_token: dict[str, set[int]] = {}
    for index, rolled in anonymous:
        if rolled.company_token not in by_token:
            by_token[rolled.company_token] = {
                row.id
                for row in await _company_rows(session, user_id, rolled.company_token)
                if row.id is not None
            }
        at_employer = by_token[rolled.company_token]
        # Deterministic: the same messages always propose the same row first,
        # whatever order the database returned them in.
        proposed = sorted(
            {
                linked[m.message_id]
                for m in rolled.messages
                if m.message_id in linked
            }
        )
        for application_id in proposed:
            if application_id in at_employer and application_id not in taken:
                homes[index] = application_id
                taken.add(application_id)
                break
    return homes


async def _linked_applications_by_message(
    session,
    user_id: uuid.UUID,
    message_ids: list[str],
) -> dict[str, int]:
    """The application each of these stored messages is already filed against.

    Scoped to ``user_id`` like every other read here. Chunked on the same bound
    as :func:`_persist_message_refs` so a first sync's whole scan target cannot
    walk into Postgres's bind-parameter ceiling — the number is not the point,
    the fact that there IS a bound is.
    """

    ids = sorted({m for m in message_ids if m})
    if not ids:
        return {}
    found: dict[str, int] = {}
    for start in range(0, len(ids), _MESSAGE_LOOKUP_CHUNK):
        chunk = ids[start : start + _MESSAGE_LOOKUP_CHUNK]
        rows = (
            await session.exec(
                select(Email.message_id, Email.application_id).where(
                    Email.user_id == user_id,
                    Email.message_id.in_(chunk),
                    Email.application_id.is_not(None),
                )
            )
        ).all()
        for message_id, application_id in rows:
            if application_id is not None:
                found[message_id] = application_id
    return found


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
            # A row whose requisition id CONTRADICTS this one is a different
            # application, however identical the titles read — which is exactly
            # what the docstring above promises ("Nothing outranks it") and what
            # the unguarded role-token match used to break. Two openings at one
            # employer often share a title and differ only by id; landing the
            # second one's mail on the first one's row merges two applications
            # into one card, silently, with no way back. Mirrors
            # :func:`pipeline._may_join` on the in-scan side; the two must agree
            # or a cluster and its stored row disagree about what they are.
            if req_id is not None and row.req_id and row.req_id != req_id:
                continue
            if row.role_token and row.role_token == role_token:
                return row

    if req_id is None and role_token is None:
        # Rule 4. Deliberately looks at ALL rows, not just the identity-less
        # ones, and always returns one rather than minting.
        #
        # THE PREMISE THAT USED TO BE WRITTEN HERE WAS FALSE (#641). It read
        # "a cluster reaches here only when the scan found NO role for this
        # employer in ANY of its mail", and `partition_applications` has never
        # promised that. Its anchors branch mints anonymous clusters beside
        # keyed ones with no all-anonymous requirement, and its `known_multi`
        # carve-out gives an anonymous message its own cluster at an employer
        # whose other mail is fully identified. A keyed sibling IS reachable
        # from this line, so the tie-break below can and did hand a
        # confirmation an application it was never about.
        #
        # WHAT NARROWS IT NOW IS THE CALLER, not this line. On the sync path
        # `_resolve_application` offers a cluster that ASSERTS an application —
        # one carrying a confirmation — to `_is_a_further_application` first,
        # and at an employer holding two or more live cards that gate mints
        # rather than folding. What still arrives here is UPDATE mail with no
        # identity: it reports on an application instead of asserting one, so
        # it must land on a row rather than open one, and rule 4 is right for
        # it. The other two call sites (review-classify, orphan-reconcile) ask
        # about a single message a human already spoke about, and are right for
        # their own reasons.
        #
        # AND THE ARGUMENT THAT USED TO JUSTIFY IT IS OBSOLETE — said rather
        # than deleted, because deleting it invites someone to re-derive it.
        # "Returning None would mint a fresh row on EVERY sync" was true before
        # rule 0 existed. `_anonymous_homes` now reads the stored message →
        # application link for the whole pass, so a cluster whose mail is
        # already filed is handed its own row above and never reaches this
        # line; re-minting is bounded by the link, not by this tie-break.
        # `_company_rows` orders live-first then oldest-first, so the choice is
        # stable across syncs.
        return rows[0]

    # Rule 3 — adopt the employer's single pre-identity row, in place.
    #
    # ONLY A ROW THE SYNC MADE. A manual row is a human's own entry and may
    # legitimately duplicate what the mail says; a row `classify_review_item`
    # minted is a human's answer to "which application is this about?" and is
    # identity-less BY CONSTRUCTION, because the message reached the picker
    # precisely for naming no role. Adopting either one writes ANOTHER
    # application's `req_id` and `role_token` onto it, and `role_token` is half
    # an application's identity — so the adopted card then captures the other
    # application's future mail. That is not a cosmetic mis-key.
    #
    # This test used to be applied only when there were SEVERAL candidates, and
    # the comment stating the rule sat on that branch while the one-candidate
    # branch above it returned whatever it found. One is the common case.
    unidentified = [
        row
        for row in rows
        if row.req_id is None and row.role_token is None and _is_auto_row(row.source)
    ]
    return unidentified[0] if len(unidentified) == 1 else None


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

    AND WHEN THE ROW IS ONE THE USER DISMISSED BY HAND (#597).
    :func:`_company_rows` returns dismissed rows deliberately — it sorts them
    last rather than dropping them — so before this every id present in that
    list was a legitimate pick, dismissed or not. A hand-dismissal is final, so
    landing an answer on such a row is the one thing this endpoint may not do;
    the caller falls back to resolution and mints a fresh card beside it, which
    is visible and reversible where a silent un-dismissal is neither. A
    ``resync``-dismissed row IS still a legitimate pick: answering its mail
    restores it, which is the other half of the same decision.
    """

    if application_id is None:
        return None
    rows = await _company_rows(session, user_id, token)
    return next(
        (row for row in rows if row.id == application_id and not _user_dismissed(row)),
        None,
    )


#: HOW a stored message reached the row it is being filed against. Only a
#: landing that is a CLAIM about which application this is may carry the
#: message's identity onto the row; ``LANDED_BLIND`` is the resolver saying it
#: does not know, and a title stamped on that basis is a guess wearing the
#: authority of a fact. See :func:`_adopt_mail_identity`.
LANDED_LINKED = "linked"
LANDED_KEYED = "keyed"
LANDED_BLIND = "blind"
#: The resolver read the strongest signal there is — the message's own link —
#: and DECLINED it, because it names a card the user dismissed by hand. Its own
#: value, not ``LANDED_KEYED`` and not ``LANDED_BLIND``: keyed would be a
#: refusal wearing the authority of a fact, which is the defect the comment
#: above names, and blind means "read nothing" when in fact the strongest thing
#: was read. Nothing consumes it today — both callers branch on ``app is None``
#: first — and that is why it is cheap to state now, before a caller does.
LANDED_REFUSED = "refused"


async def _resolve_application_for_email(
    session,
    user_id: uuid.UUID,
    token: str,
    email: Email,
) -> tuple[Application | None, str]:
    """Resolve the application ONE stored message belongs to, or None to mint.

    Returns the row AND how it was reached, because the two callers now write
    the message's identity onto the row and must not do that on a tie-break.

    THE MESSAGE'S OWN LINK COMES FIRST. Both callers are answering a human — the
    review queue's "what is this?" and the orphan catch-up — and both used to go
    straight to the cascade, which for a message that names no role returns the
    employer's oldest row (rule 4). That was a tie-break with one row to break
    between; now that an employer's anonymous confirmations get a row each it is
    a coin toss between three, and losing it files a person's own decision onto
    an application they were not talking about. A message already filed against
    a row of this employer's is not a guess, so it is consulted before anything
    that is.

    The residual is stated rather than fixed: an UNLINKED anonymous message at an
    employer holding several rows still lands on the oldest by rule 4. Minting
    instead would answer "which of your three Google applications?" by inventing
    a fourth, which is worse — and this is only ever reached when NOBODY WAS
    ASKED. Both correction surfaces put the question directly where it can be
    put (:func:`_chosen_application`): the needs-review queue since #554, and the
    filed ledger's reclassify control since #560. What still arrives here
    unanswered is a sync, a single-candidate employer, or a correction to a
    message that already carries a link — and for the last of those the branch
    above has already answered.

    NO LANDING EVER TOUCHES A ROW THE USER DISMISSED BY HAND (#597). Three of
    the four surfaces are covered here — the review queue's answer, the inbox's
    reclassify and the orphan catch-up — because all three arrive through this
    function. The board picker does NOT: it comes through
    :func:`_chosen_application`, which carries its own ``_user_dismissed``
    filter. TWO SITES, BOTH LOAD-BEARING. This used to claim one choke point
    "instead of four times", which reads as an invitation to delete that filter
    as redundant; deleting it reopens the picker path.

    All three of this function's own exits are covered, and the third is the one
    that is easy to miss: the message's OWN link is REFUSED rather than skipped
    (see the branch below — skipping hands the message to a live sibling), such
    rows are kept out of the cascade's candidate set, and the caller then mints
    a fresh card. Minting is the cheap direction to be wrong in — a spurious
    card is one dismiss click, whereas un-dismissing a card a person
    deliberately removed is the product arguing with them.

    A ``resync``-dismissed row is NOT excluded and must not be: it is still the
    right row to land on, and :func:`classify_review_item` un-dismisses it when
    an answer lands there. Machine removal yields to newer evidence; a human's
    does not.
    """

    rows = await _company_rows(session, user_id, token)
    if email.application_id is not None:
        linked = next((row for row in rows if row.id == email.application_id), None)
        if linked is not None:
            if not _user_dismissed(linked):
                return linked, LANDED_LINKED
            # REFUSED, NOT FALLEN THROUGH, and the difference is a merged pair
            # of applications.
            #
            # Skipping the hand-dismissed link and letting the cascade run below
            # looks like the same thing and is not. At an employer holding this
            # dismissed row AND a live one, the candidate list is then exactly
            # the live row, so `_pick_application` hands the message to it —
            # rule 3 when the message names an id (the live row is
            # identity-less, so it is the single `unidentified` adoption
            # target), rule 4 when it names nothing (`_company_rows` sorts
            # live-first, so `rows[0]` IS that row). Both routes were run:
            # `email.application_id` moves off the dismissed card onto the live
            # one, the stage advance walks the live card to the answered
            # category with no auto-row gate, and — because `live` is 1, so
            # `blind` is False — `_adopt_mail_identity` stamps THIS
            # application's `req_id` and `role_token` onto the OTHER one.
            # Rule 1 then routes all of this application's future mail there.
            # Two applications wearing one identity, undone only by
            # `POST /{id}/split`.
            #
            # A narrower patch to the `live` count fixes only the second route;
            # the first never consults it. So the refusal goes here, above the
            # cascade, where it closes both.
            #
            # The caller mints beside it, which is what the docstring below
            # promises and what the one-row case already did. That is the cheap
            # direction to be wrong in: a spurious card is one dismiss click,
            # where a silent merge is not reversible from any screen.
            #
            # `/inbox`'s reclassify control is why this is reachable rather than
            # theoretical — it sends no `application_id` for an already-filed
            # message, on the documented grounds that "the message's own link
            # beats every tie-break in `_resolve_application_for_email`". That
            # contract is a cross-component one; this branch is the half of it
            # that lives here.
            return None, LANDED_REFUSED
    subject = email.subject or ""
    snippet = email.body_snippet or ""
    # SNIPPET-GRADE, deliberately, and that is the whole reason the landing is
    # reported. `_email_identity_parts` prefers the stored `identity_*` columns,
    # which were written from the WHOLE BODY where one was fetched; this
    # cascade re-derives from subject + the first ~200 characters. So the case
    # where rule 4 fires — nothing readable here — is exactly the case where the
    # caller may still be holding a body-grade role, and stamping it onto the
    # row this tie-break happened to pick writes one application's title onto
    # another's card.
    req_id = pipeline.extract_req_id(subject, snippet)
    role_token = pipeline.normalize_role_token(
        pipeline.role_from_message(subject, snippet)
    )
    # The candidate set the cascade may pick from — see the note above. Every
    # row removed here is one the user dismissed by hand.
    candidates = [row for row in rows if not _user_dismissed(row)]
    picked = _pick_application(candidates, req_id, role_token)
    # LIVE ROWS ONLY, for the reason :func:`employers_with_several_applications`
    # already gives: a dismissed duplicate is not on the board, so letting one
    # push the count over the threshold refuses on the strength of a card that
    # no longer exists. `_company_rows` deliberately returns dismissed rows and
    # sorts them last, and `_merge_rolled_into_board` dismisses rows on every
    # resync, so one live row beside one dismissed one is an ordinary state —
    # and there is nothing ambiguous about it. Counting both left the single
    # live card blank with the job sitting in its own `identity_role` column.
    # Counted over ``candidates`` and not ``rows``, which is numerically the
    # same set: every row the exclusion drops already had ``dismissed_at`` set,
    # so it was never counted here anyway. Written this way so the two lines
    # cannot disagree if the exclusion is ever widened.
    live = sum(1 for row in candidates if row.dismissed_at is None)
    blind = req_id is None and role_token is None and live > 1
    return picked, LANDED_BLIND if blind else LANDED_KEYED


# How many message ids may travel in one ``WHERE message_id IN (...)``.
#
# The number itself is not the point — 750 ids (a first sync's whole scan
# target) is comfortably inside Postgres's 65535 bind-parameter ceiling, so a
# single statement would work today. The CHUNKING is the point: a bound that
# holds only because the current scan target happens to be small is not a
# bound, and the day somebody raises ``_SYNC_DEFAULT_SCAN_TARGET`` the failure
# would be a driver-level error on a query nobody edited. Explicit here, and
# pinned by tests/test_persist_message_refs_is_batched.py.
_MESSAGE_LOOKUP_CHUNK = 500


def _email_identity_parts(email) -> tuple[str | None, str | None]:
    """The (role, req_id) a STORED message names — derived once, read here.

    The same rule :func:`pipeline.identity_or_derive` applies to a message in
    flight, for a row that has been persisted. Both columns NULL means nothing
    was ever derived for this row — it predates the columns, or it came in
    through the client relay, which carries a snippet and no body — so the
    fallback re-derives from the stored snippet, which is what every caller here
    used to do unconditionally.

    Returning the PARTS rather than the sub-key because the callers mint an
    ``Application`` and need the display title and the requisition number
    separately, not just the key that distinguishes them.
    """

    return pipeline.identity_parts(
        req_id=email.identity_req_id,
        role=email.identity_role,
        subject=email.subject or "",
        snippet=email.body_snippet or "",
    )


def _adopt_mail_identity(app, role: str | None, req_id: str | None) -> bool:
    """Give a card the title and key ONE stored message names. Fill-only.

    THE TWO PATHS THAT RESOLVE A STORED MESSAGE ONTO AN EXISTING ROW — the
    review queue's "what is this?" and the orphan catch-up — both derived the
    role and then used it only when they MINTED a row. Landing on a row that
    already existed, they wrote the stage and the source and dropped the title
    on the floor (#546). Nothing repaired it afterwards: the message is linked,
    so the catch-up's own predicate excludes it, and a below-gate message never
    joins a rolled cluster, so the sync upsert's title write is never reached
    for it either. The product held the answer and threw it away.

    Measured over the 9,252-card independent corpus: 26 cards whose title is
    readable, sits in the review queue, and never arrives. On the live board on
    2026-08-27, 8 of 57 cards showed no job title and every one had
    ``position_source`` NULL — nobody typed those and nobody cleared them.

    FILL-ONLY, and deliberately narrower than the sync's rule.
    :func:`upsert_applications_for_user` also REWRITES an auto row's non-blank
    title when extraction produces something different, so that improvements
    reach rows already on the board. That is defensible there because it
    re-reads the whole cluster. It is not defensible here: this is one message,
    the classifier was unsure enough about it to ask a person, and the person
    was asked what the MESSAGE is — not what the application is called. Copying
    the sync's clause verbatim would also make the outcome depend on whether
    the stage happened to move in the same request, because the review path
    flips ``source`` to ``gmail_user`` a few lines later, and a rule whose
    effect turns on an unrelated coincidence is not a rule.

    THE IDENTITY IS STAMPED TOO, and that is not scope creep. A row that shows
    a title while staying anonymous to the resolver is the state that mints
    duplicates: ``_pick_application`` rule 3 adopts an anonymous row only when
    it is the employer's ONLY anonymous one, so at an employer holding two the
    next sync refuses to adopt and files a second card beside the one just
    titled. That state is live — on 2026-08-27 one employer on the real board
    held three rows with both identity columns NULL. The stamp is fill-if-empty
    for each column independently, which is exactly what the sync upsert
    already does on the row it lands on; this is that rule at one more call
    site, not a new one.

    ``position_source`` is deliberately left alone. NULL means "the sync owns
    this field", so this title stays the sync's to correct — for as long as the
    row still reads as a sync row. Where the same request also moves the stage,
    the review path flips ``source`` to ``gmail_user`` a few lines later, and
    the sync's rewrite clause is gated on ``_is_auto_row``; so on that path the
    title becomes effectively frozen until a split or a human edits it. Stated
    rather than fixed: unfreezing it means a third ``position_source`` value,
    and inventing one to soften a docstring is the wrong trade.

    A CONTRADICTED REQUISITION REFUSES EVERYTHING. If this message names a
    requisition and the row already carries a different one, they are two
    applications however identical the titles read — the same judgement
    :func:`_pick_application` makes before it will file across them. Without
    this the three columns fill independently and a row can end up wearing one
    requisition's number and another's title: a chimera that rule 1 then
    matches for one application while displaying the other's job. An anonymous
    row is honestly anonymous; a half-stamped one is confidently wrong.

    Returns whether anything changed, so the caller can skip a pointless write.
    """

    if req_id is not None and app.req_id is not None and app.req_id != req_id:
        return False

    changed = False
    # DEC-004: the `position_source` guard is why extraction may write here at
    # all. Removing it because "extraction works now" is the reversal that entry
    # exists to refuse -- it is the only thing between this line and a title the
    # user typed. See docs/DECISIONS.md.
    if role and not app.position and app.position_source != ROLE_FROM_USER:
        app.position = role
        changed = True
    if req_id is not None and app.req_id is None:
        # The `is None` is bookkeeping, NOT a guard, and saying so is the point:
        # the contradiction check above has already returned unless `app.req_id`
        # is None or equal to `req_id`, so dropping it here changes no stored
        # value and no test can red on it. It stays because writing the same
        # string back would dirty the row and bump `updated_at` for nothing.
        app.req_id = req_id
        changed = True
    token = pipeline.normalize_role_token(role) if role else None
    if token is not None and app.role_token is None:
        app.role_token = token
        changed = True
    return changed


async def _persist_message_refs(
    session,
    user_id: uuid.UUID,
    application_id: int | None,
    refs,
    siblings: frozenset[int] = frozenset(),
    anchored: frozenset[str] = frozenset(),
) -> dict[int, set[int]]:
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

    ``siblings`` — ids of OTHER rows at the same employer, passed only when the
    cluster being filed carries no identity of its own (no requisition id, no
    role token). Such a cluster is resolved by :func:`_pick_application`'s rule
    4 — the employer's oldest live row, a tie-break and not evidence — WHEN IT
    IS AN UPDATE. Since #641 that is the only kind that reaches the tie-break
    on the sync path: an anonymous cluster carrying a confirmation is offered to
    :func:`_is_a_further_application` first and, at an employer holding two or
    more live cards, mints its own row instead. The guard below is unchanged and
    still needed — update mail is exactly what still lands by tie-break.
    A tie-break must never overrule a link an earlier, better-informed scan
    already made, so a message already filed against a sibling STAYS there.
    Without this an ordinary sync that re-read one message without its snippet
    (a metadata-only pass names no role) walked the mail of the owner's second
    Amazon application onto his first one, emptied the row, and the emptied row
    was then dismissed — 22 times over two days, on employers that never left
    the board. Cross-employer re-pointing is untouched: that one is a change of
    evidence about who the message is from, not a tie-break.

    ``anchored`` — the message ids that GAVE this cluster its identity, which for
    an anonymous cluster is the single confirmation
    :func:`pipeline.partition_applications` built it around. Those are exempt
    from the sibling guard above, and they have to be: splitting Google's three
    confirmations into three rows means two of those messages must LEAVE the row
    they were folded onto, and the guard exists to stop exactly that move. The
    distinction the guard is really drawing is between a message a cluster
    merely guessed at and one it is defined by; before the split existed no
    anonymous cluster had the latter, so the two were the same thing. Empty for
    every identified cluster, which never passes ``siblings`` either.

    RETURNS which applications it moved an email away from, and WHERE each one
    went: ``{source_id: {destination_id, ...}}``. Re-pointing is right — the
    newest resolution of a message's employer wins — but it can leave the
    previous row with no linked mail at all, which is how application 64
    ("Together AI") ended up on the owner's board with nothing behind it. The
    caller has to decide what happens to those rows; see
    :func:`_dismiss_rows_left_without_mail`, which needs the destination to tell
    "this row's employer is gone" from "its mail was re-filed next door". It
    cannot be decided here, because a row emptied by one rolled company may be
    re-filled by the next one in the same sync.
    """

    moved_from: dict[int, set[int]] = {}

    # ONE lookup for the whole batch, not one per message.
    #
    # ``ix_emails_user_id_message_id`` served the per-message probe this used to
    # make perfectly — the query was never the cost. The COUNT of round trips
    # was: ~13 ms function→pooler in production (database/connection.py), paid
    # sequentially, once per ref. A first sync scans up to 750 messages
    # (gmail_oauth's ``_SYNC_DEFAULT_SCAN_TARGET``), so the old shape spent
    # roughly ten seconds of the serverless budget waiting on the network — and
    # the scheduled run's per-user timeout is 10 s, which is the documented
    # reason (cron.py) a first sync could be cancelled and never write a cursor.
    #
    # The dict is the loop's ONLY source of "does this message already exist",
    # including for rows the loop itself creates further down: the old code was
    # protected from a message_id repeated inside one ``refs`` list by
    # autoflush — the second probe saw the row the first iteration had just
    # added — and a prefetch taken before the loop cannot see those. Newly
    # created rows are therefore folded back in as they are made.
    #
    # Autoflush is deliberately NOT suppressed around the prefetch. Rows added
    # by an earlier call in the same session (the rolled path at the two call
    # sites in ``upsert_applications_for_user`` runs before the review-item
    # paths) must be visible here, exactly as they were before.
    existing_by_message_id: dict[str, Email] = {}
    wanted = [
        ref.message_id
        for ref in refs
        # Built from the refs that SURVIVE the undated skip below, so an
        # undated message never widens the lookup for a row that will not be
        # written.
        if pipeline.to_naive_utc(ref.received_at) is not None
    ]
    for start in range(0, len(wanted), _MESSAGE_LOOKUP_CHUNK):
        chunk = wanted[start : start + _MESSAGE_LOOKUP_CHUNK]
        for row in (
            await session.exec(
                select(Email).where(
                    Email.user_id == user_id,
                    Email.message_id.in_(chunk),
                )
            )
        ).all():
            existing_by_message_id[row.message_id] = row

    for ref in refs:
        # Naive-UTC: the Email.received_at column is TIMESTAMP WITHOUT TIME ZONE;
        # asyncpg refuses an aware datetime (from parsedate_to_datetime) here.
        received_at = pipeline.to_naive_utc(ref.received_at)
        if received_at is None:
            continue
        existing = existing_by_message_id.get(ref.message_id)
        category = _safe_category(ref.category)
        # The classifier's PROPOSAL, which only a review ref carries. Written
        # under the same settled-guard as the category below, and — like the
        # category — written UNCONDITIONALLY within it, including to None. That
        # is not an oversight of the kind the snippet and thread_id comments
        # above describe: a ref from the rolled path leaves it None because that
        # message now has a committed category, so there is no proposal
        # outstanding. Within one sync the ordering agrees —
        # ``upsert_applications_for_user`` runs before
        # ``_persist_review_items_additive`` — so a message cannot be filed and
        # then re-parked in the same pass.
        suggestion = _safe_suggestion(ref.suggested_category)
        if existing is not None:
            if application_id is not None:
                current = existing.application_id
                if current is not None and current != application_id:
                    if current in siblings and ref.message_id not in anchored:
                        # An identity-less cluster asking for a message that is
                        # already filed against another application at this same
                        # employer. It knows nothing this link does not; leave it.
                        pass
                    else:
                        moved_from.setdefault(current, set()).add(application_id)
                        existing.application_id = application_id
                else:
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
            # THE SAME RATCHET, for the identity the reader derived from the
            # body. ``None`` means this pass derived nothing — a client relay
            # item, which never had a body — and must leave a stored value
            # alone; ``""`` is a real derivation that found no title and is
            # written, because "derived, names nothing" is a different answer to
            # "never derived" and the readers act on the difference.
            #
            # This is also what heals rows written before the columns existed:
            # the next scan that reads one with a body ratchets NULL up to a
            # real value, so no backfill has to guess from a snippet that never
            # held the title in the first place.
            if ref.identity_role is not None:
                existing.identity_role = ref.identity_role[:200]
            if ref.identity_req_id is not None:
                existing.identity_req_id = ref.identity_req_id[:64]
            # A thread id, likewise: a metadata fetch that omits it must not
            # unlink a message from its conversation.
            if ref.thread_id:
                existing.thread_id = ref.thread_id
            if not (existing.user_corrected or existing.is_reviewed):
                existing.classified_as = category
                existing.suggested_category = suggestion
                existing.classification_confidence = ref.confidence
                # REPORTS, does not assert (#496). The literal "rules" used to
                # stand here while `get_classifier` is the HYBRID classifier,
                # so the column could not disagree with itself no matter which
                # layer answered. `None` means the server saw no classifier run
                # for this message (the client-relay paths) and is written as
                # NULL rather than guessed.
                existing.classification_method = ref.method
            session.add(existing)
        else:
            created = Email(
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
                identity_role=(
                    None if ref.identity_role is None else ref.identity_role[:200]
                ),
                identity_req_id=(
                    None if ref.identity_req_id is None else ref.identity_req_id[:64]
                ),
                classified_as=category,
                suggested_category=suggestion,
                classification_confidence=ref.confidence,
                # See the update branch above: carried, not asserted (#496).
                classification_method=ref.method,
            )
            session.add(created)
            # Carry it in the map so a message_id repeated later in THIS list
            # updates the row just made instead of inserting a second one. The
            # per-ref SELECT used to get this from autoflush; the batched
            # prefetch, taken before the loop, cannot.
            existing_by_message_id[ref.message_id] = created

    return moved_from


def _merge_moves(into: dict[int, set[int]], moves: dict[int, set[int]]) -> None:
    """Fold one ``{source: {destination}}`` map into the running one."""

    for source, destinations in moves.items():
        into.setdefault(source, set()).update(destinations)


async def _mail_stayed_at_this_employer(
    session, user_id: uuid.UUID, row: Application, destinations: set[int]
) -> bool:
    """Did the mail that left ``row`` land on another row of the same employer?

    ANY same-employer destination is enough to answer yes. A row whose messages
    scattered — some next door, some to a genuinely different company — is
    ambiguous, and ambiguity resolves toward keeping the application.

    Compares the way every other employer comparison in this module does, via
    :func:`pipeline.matches_company_token`, so "Amazon" and "Amazon.com" are one
    employer here exactly as they are at filing time. A destination row that has
    since vanished simply contributes nothing.
    """

    if not destinations:
        return False
    companies = (
        await session.exec(
            select(Application.company).where(
                Application.user_id == user_id,
                Application.id.in_(destinations),
            )
        )
    ).all()
    return any(
        pipeline.matches_company_token(
            row.company, pipeline.normalize_company_name(company)
        )
        for company in companies
    )


async def _dismiss_rows_left_without_mail(
    session, user_id: uuid.UUID, moved: dict[int, set[int]]
) -> list[RemovedApplication]:
    """Take off the board any AUTO row whose LAST linked email LEFT THE EMPLOYER.

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

    WHERE THE MAIL WENT decides it, which is why the caller passes destinations
    and not just a set of emptied ids. Two very different things empty a row:

    - the message now belongs to a DIFFERENT employer. Then this row was a
      misattribution of another company's mail, nothing about that employer
      remains, and an empty row is the worse state. Dismissed.
    - the message was re-filed onto a SIBLING at the same employer — a role
      token that tokenizes differently than the day the row was minted, a scan
      that could not re-derive an identity. Then the application has not gone
      anywhere; one identity resolution disagreed with another, and company-token
      reasoning cannot express "this employer is present but that requisition is
      gone". The row STAYS. It cost the owner 22 real applications to establish
      that removing a row on this evidence is the wrong trade: a stale row is a
      click to remove, a removed one is not even visible to click.

    Every removal that survives that test is now RETURNED to the caller and
    reported. The note that used to sit here — that naming these would be a lie
    because the company is still on the board under the row its mail moved to —
    described exactly the case that no longer removes anything.
    """

    if not moved:
        return []

    await session.flush()
    removed: list[RemovedApplication] = []
    now = datetime.utcnow()
    for application_id in sorted(moved):
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
        if await _mail_stayed_at_this_employer(session, user_id, row, moved[application_id]):
            continue
        row.dismissed_at = now
        row.dismissed_reason = DISMISSED_BY_RESYNC
        row.updated_at = now
        session.add(row)
        removed.append(RemovedApplication(id=row.id, company=row.company))

    if removed:
        await session.flush()
        # Ids, not company names — the ids identify the rows exactly and carry
        # no mail-derived text (see :func:`_warn_if_capped`).
        logger.info(
            "Sync left %s auto row(s) with no linked mail for user_id=%s and "
            "dismissed them (restorable): application_id=%s",
            len(removed),
            user_id,
            ", ".join(str(r.id) for r in removed),
        )
    return removed


def _safe_category(value: str) -> EmailCategory | None:
    try:
        return EmailCategory(value)
    except ValueError:
        return None


def _safe_suggestion(value: str | None) -> EmailCategory | None:
    """The eight PREDICTED labels, or None. ``needs_review`` is not one of them.

    ``suggested_category`` records what the classifier thinks a parked message
    is. ``needs_review`` is not an opinion about the message — it is the queue
    state, already carried by ``classified_as`` — so a below-gate
    ``needs_review`` verdict must not leak in here. Storing it would give the
    row a "suggestion" no human could ever confirm into anything, which is the
    frozen-forever shape ``docs/ML_CORPUS_INTEGRITY.md`` records.

    ``other`` is admitted deliberately: it is a real verdict a human can confirm
    (and the review queue does surface explicit ``needs_review`` mail that the
    classifier separately believes is noise).
    """

    if value is None:
        return None
    category = _safe_category(value)
    if category is EmailCategory.NEEDS_REVIEW:
        return None
    return category


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
    removed_out: list[RemovedApplication] | None = None,
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
    Any row that ends up genuinely removed is APPENDED to ``removed_out`` when
    the caller passes a list. An out-parameter, not a third return value, so the
    ``(created, updated)`` contract every existing caller unpacks is untouched;
    the merge functions are the only callers that need the names, and they need
    them because a sync that changes the board without saying so is the defect
    this file has now produced twice.

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
    moved: dict[int, set[int]] = {}
    # Earliest-applied first WITHIN a company. When several applications at one
    # employer meet a single pre-identity row, the earliest is the one that
    # adopts it — so the row that has been on the board (and any status the user
    # set on it) stays with the application it was actually about, and the later
    # ones are minted fresh. Across companies the order is irrelevant.
    order = sorted(rolled, key=lambda x: (x.company_token, x.applied_at or datetime.max))
    # Which row each anonymous cluster already owns. Worked out over the whole
    # list before anything is resolved, so a cluster with no link cannot take a
    # row that a later one is the home of — see :func:`_anonymous_homes`.
    homes = await _anonymous_homes(session, user_id, order)
    reserved = frozenset(homes.values())
    # Rows taken as this pass goes, minted ones included.
    claimed: set[int] = set()
    for index, r in enumerate(order):
        anonymous_cluster = r.req_id is None and r.role_token is None
        home = homes.get(index)
        existing = await _resolve_application(
            session,
            user_id,
            r,
            home,
            frozenset(claimed | (reserved - {home})) if anonymous_cluster else frozenset(),
        )
        if anonymous_cluster and existing is not None and existing.id is not None:
            claimed.add(existing.id)
        deeplink = _rolled_deeplink(r)

        # A cluster that carries no identity of its own lands on the employer's
        # oldest row by :func:`_pick_application`'s rule 4 — a stable tie-break,
        # and no evidence at all about which application the mail belongs to. It
        # may file NEW messages there; it may not take one off a sibling. Only
        # such a cluster pays for this lookup.
        siblings: frozenset[int] = frozenset()
        anchored: frozenset[str] = frozenset()
        if anonymous_cluster:
            siblings = frozenset(
                row.id
                for row in await _company_rows(session, user_id, r.company_token)
                if row.id is not None
            )
            # The confirmation this cluster IS. It may leave the row it was
            # folded onto; nothing else in the cluster may.
            anchored = frozenset(
                m.message_id
                for m in r.messages
                if m.category in pipeline.APPLIED_SIGNAL_CATEGORIES
            )

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
                    # The id, not the company name (see :func:`_warn_if_capped`).
                    logger.info(
                        "Reopened application id=%s for user_id=%s: rejected at "
                        "%s, applied again at %s → status %s",
                        existing.id,
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
            if (
                r.role
                # A role the USER typed is theirs, and no extraction result
                # supersedes it — including the one that finally starts working.
                # This is checked first and separately from the clauses below
                # because it must also beat the ``not existing.position`` case:
                # clearing a typed role sets ``position_source`` back to NULL, so
                # a row that is both empty AND still marked as the user's cannot
                # occur, and if it ever did the human's silence would still be an
                # answer. See :func:`record_role_correction`.
                and existing.position_source != ROLE_FROM_USER
                and (
                    not existing.position
                    # An auto row's role belongs to the sync, exactly as its
                    # company does. Filling only an EMPTY position means every
                    # improvement to role extraction reaches new rows and never
                    # the ones already on the board: "Path Robotics · interest in
                    # the Software Engineer, C#" survived the fix that stopped
                    # producing it, because the wrong string was already stored.
                    # A user-corrected or manual row keeps whatever the human
                    # wrote.
                    or (_is_auto_row(existing.source) and r.role != existing.position)
                )
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
            _merge_moves(
                moved,
                await _persist_message_refs(
                    session, user_id, existing.id, r.messages, siblings, anchored
                ),
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
            # A row this pass MINTED is claimed too. Only the first of an
            # employer's anonymous clusters finds no row and mints; without this
            # the second one would resolve straight onto what the first just
            # created — rule 4 returns the employer's oldest row and a row three
            # lines old still qualifies — and the three Google confirmations
            # would land back on one card having briefly been three.
            if anonymous_cluster and app.id is not None:
                claimed.add(app.id)
            _merge_moves(
                moved,
                await _persist_message_refs(
                    session, user_id, app.id, r.messages, siblings, anchored
                ),
            )
            created += 1

    # Once, after every company has had its say — a row emptied by one of them
    # may have been re-filled by another.
    removed = await _dismiss_rows_left_without_mail(session, user_id, moved)
    if removed_out is not None:
        removed_out.extend(removed)

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
    application. TWO WAYS IT DOESN'T. The endpoint's employer lookup failed and
    the decision was swallowed, leaving the row unlinked; or a later re-sync
    dismissed the card the row does name, leaving a link that outlived the only
    thing making it mean anything (#598). Both end in the same place — reviewed,
    in a filing category, on no card the user can see, off the board and out of
    the queue. This is the catch-up that un-strands them on the next sync, now
    that :func:`pipeline.resolve_employer` can name the employer from an ATS
    display-name / subject lead.

    Scoped to ``user_id`` like every other query here. Deliberately narrow: only
    rows the user actually settled (``user_corrected`` or ``is_reviewed``) with
    a filing category and NO APPLICATION OF THEIRS THAT ANSWERS FOR THEM —
    :func:`_not_filed_on_an_application_that_answers`, the same predicate the
    review queue and the ``needs_review`` tile read. An un-reviewed
    auto-classified row is excluded on purpose — by design it is either already
    linked or in the review queue, and sweeping those up would re-open the
    "fabricate a row from a low-confidence guess" bug the precision gate exists
    to prevent.

    THAT CLAUSE USED TO BE ``application_id IS NULL`` (#598), which encodes "no
    application was produced". Dismissal stopped that from being what it means:
    a message linked to a card a RE-SYNC removed produced no application the
    user can see, and is stranded in exactly the way this function exists to
    undo — reviewed, in a filing category, on no board, out of the queue. The
    catch-up stepped over the rows it was written for. The shared predicate is a
    strict WIDENING of the old clause — a NULL link makes its ``EXISTS`` false,
    so every row that used to be selected still is — and it reaches two shapes
    the NULL test could not:

      * a link to a ``resync``-dismissed card. This is #481's state. It lands
        back on that card through :func:`_resolve_application_for_email`'s link
        branch, and the else-branch below puts the card on the board again.
      * a link that resolves to no application of this user's — a dangling id,
        or a stale one naming another user's row. The resolver cannot see such a
        row either (``_company_rows`` is scoped to this user), so it falls
        through to the cascade and the message is re-filed onto a live row of
        theirs, minting one if the employer has none. The stale link is repaired
        rather than followed. NEITHER SHAPE IS REACHABLE IN PRODUCTION TODAY and
        :func:`_filed_on_an_application_that_answers` says why; this is what the
        ``EXISTS`` answers by construction, not a state anyone has observed.

    A LINK TO A HAND-DISMISSED CARD IS NOT ONE OF THEM, and that is the whole
    reason this reads the shared predicate rather than ``dismissed_at IS NULL``
    (#597). The user's own "no" answers for that card's mail: the row is
    settled, never an orphan here, and no catch-up pass may revive the card. A
    ``dismissed_at``-only test would revive it automatically on every sync,
    which is exactly what #597 decided must not happen.

    IDEMPOTENT, AND THE MECHANISM CHANGED WITH THE PREDICATE. It is no longer
    "the row gains an ``application_id`` and therefore stops matching" — the
    rows this pass newly reaches already had one, and keep having one. What is
    true after a pass is that the email points at an application that ANSWERS
    for it: one this pass minted (live), or the ``resync``-dismissed card the
    else-branch below just un-dismissed (live again), or the live row a stale
    link was re-pointed at. In every exit the ``EXISTS`` is true on the next
    run, so the predicate no longer matches and the pass terminates. Two orphans
    for one employer collapse into a single application within one pass, and an
    existing row is only ever ADVANCED (never downgraded, never un-settled).
    Returns the number of applications CREATED.

    Two residuals do NOT terminate, and neither is new: an orphan whose employer
    :func:`pipeline.resolve_employer` cannot name, and one whose category falls
    outside the filing set, are ``continue``d and stay selected on every later
    pass. The NULL test left them selected too. The pass does nothing with them
    either way, so this is a re-examined row rather than a loop.

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
                _not_filed_on_an_application_that_answers(user_id),
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

        app, landing = await _resolve_application_for_email(
            session, user_id, token, email
        )
        # DERIVED ONCE, ABOVE THE BRANCH, and the placement is load-bearing.
        # This used to sit inside the `if app is None:` below, which made it a
        # loop-carried variable for every other iteration: reading `role` in
        # the else-branch would take the PREVIOUS orphan's role — a different
        # employer's job title, written onto this employer's card, silently and
        # in production on the first multi-orphan pass. See
        # `test_the_catch_up_never_carries_one_employer_s_title_onto_another`.
        role, req_id = _email_identity_parts(email)
        if app is None:
            # Stamp the identity the message carries onto the row it mints, so
            # the next sync recognises this application instead of filing a
            # second one beside it.
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
                req_id=req_id,
                role_token=pipeline.normalize_role_token(role),
            )
            session.add(app)
            await session.flush()
            minted.add(app.id)
            created += 1
        else:
            # A human classified this message INTO a filing category, which is
            # the newest decision on record — so it restores a MACHINE-dismissed
            # row rather than filing a duplicate beside it.
            #
            # NOT "either kind", which is what this said until #597. A ``user``
            # dismissal is final: the human already answered this question about
            # this card, and a later filing decision about one of its messages
            # does not overturn it. This branch cannot see such a row —
            # :func:`_resolve_application_for_email` excludes them from both the
            # link and the cascade, so a message at a user-dismissed employer
            # arrives here with ``app is None`` and MINTS instead. That is the
            # only thing keeping the old comment from being a live violation:
            # ``_company_rows`` returns dismissed rows, so an unlinked reviewed
            # orphan could cascade onto a user-dismissed card and this branch
            # would have restored it. No guard is left here for it, because a
            # guard that cannot fire is not evidence — the exclusion is asserted
            # directly instead, in
            # ``tests/test_a_hand_dismissal_is_final.py``.
            #
            # SINCE #598 THERE ARE TWO MECHANISMS AND THEY COVER DIFFERENT ROWS.
            # The selection above no longer reaches a message LINKED to a
            # user-dismissed card at all — that card answers for its mail, so the
            # row is settled rather than orphaned. The resolver's exclusion still
            # covers the UNLINKED one, which IS selected and would otherwise
            # cascade onto the dismissed card. Neither is redundant: revert the
            # selection and the linked shape arrives here, drop the resolver's
            # filter and the unlinked one does.
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
            # The title and key this message names, onto a card that has
            # neither. Outside the stage gate above on purpose: whether the
            # stage moved says nothing about whether the card knows its job.
            #
            # NOT ON A BLIND LANDING. `LANDED_BLIND` means the cascade read
            # nothing in this message's subject or snippet and picked the
            # employer's oldest row to avoid minting a fourth card for a third
            # Google application. `role` may still be non-None there, because it
            # can come from the body-grade `identity_role` column the cascade
            # never looks at — so this is precisely where a title would be
            # stamped onto a card it does not belong to. Filing the message is
            # still the least-bad answer; claiming to know what the card is, is
            # not.
            if landing != LANDED_BLIND and _adopt_mail_identity(app, role, req_id):
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

    # Read the ids first, so the corpus can be unlinked from them before they
    # cease to exist. A queue item the user labelled but could not file (the
    # ``needs_employer`` branch of :func:`classify_review_item`) is unlinked and
    # un-reviewed, which is precisely what this deletes — and it carries a
    # ``training_data`` row pointing at it.
    doomed = (
        await session.exec(
            select(Email.id).where(
                Email.user_id == user_id,
                Email.source_account == EmailSource.GMAIL,
                # ``application_id IS NULL`` STAYS, and must not be "unified"
                # onto :func:`_not_filed_on_an_application_that_answers` (#597).
                # This is a DELETE. The NULL test is exactly what makes a row
                # carrying ANY link — to a live card, to a resync-dismissed one,
                # to a hand-dismissed one — undeletable here. Widening it to the
                # settlement predicate would hand this statement the rows whose
                # whole problem is that their link outlived the card, and destroy
                # the mail #481 is about instead of surfacing it.
                Email.application_id.is_(None),
                Email.is_reviewed == False,  # noqa: E712 — SQL boolean, not identity
                Email.message_id.in_(coverage.message_ids),
            )
        )
    ).all()
    if not doomed:
        return

    await _orphan_training_examples(session, user_id, doomed)
    # ``email_embeddings.email_id`` is a NOT NULL FK with no ``ondelete``, and a
    # Core bulk DELETE runs no ORM cascade, so on Postgres this statement is
    # refused outright while one embedding survives. Same edge, same fix, as
    # :func:`delete_application`.
    await session.exec(
        sa_delete(EmailEmbedding).where(
            EmailEmbedding.user_id == user_id, EmailEmbedding.email_id.in_(doomed)
        )
    )
    await session.exec(
        sa_delete(Email).where(Email.user_id == user_id, Email.id.in_(doomed))
    )


async def _persist_review_items(session, user_id: uuid.UUID, review) -> int:
    """Persist uncertain verdicts as unlinked needs-review Email rows.

    ``category`` stays ``needs_review`` — that is the COMMITTED state, and for a
    parked row the honest commitment is "none yet". The classifier's actual
    verdict rides in ``suggested_category``; before that column existed it was
    thrown away here, which is why the production queue held rows reading
    "needs_review at 0.92" and why no rejection ever reached the board.

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
            suggested_category=item.category,
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

    Settled is judged per (THREAD, APPLICATION) as well as per message. A
    conversation the user has already decided about must not come back to the
    queue because a later message arrived on it — that is the same "classify
    this application twice" the grouping in
    :func:`pipeline.collect_review_items` removes, only spread across two syncs
    instead of one. It carries the same identity component for the same reason
    that one does (#454): an ATS thread holds several applications, and settling
    by thread alone would let one answered rejection suppress the other three
    forever.
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
            # Second of the two hardcode sites. Same reasoning as
            # :func:`_persist_review_items`: the queue state is the commitment,
            # the verdict is the proposal.
            suggested_category=item.category,
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
                select(
                    Email.message_id,
                    Email.thread_id,
                    Email.subject,
                    Email.body_snippet,
                    # Read, not re-derived. A row whose title was printed past
                    # Gmail's ~200 characters carries the identity the reader
                    # extracted from the body; recomputing it from the snippet
                    # here would give this site a different answer to the one
                    # the queue was built with.
                    Email.identity_role,
                    Email.identity_req_id,
                ).where(
                    Email.user_id == user_id,
                    or_(*scoped),
                    # SETTLED IS THE QUEUE'S OWN PREDICATE, INVERTED (#596), and
                    # not ``application_id IS NOT NULL``. That spelling called a
                    # row linked to a RESYNC-dismissed card settled — and a settled row
                    # here does not merely skip itself, it suppresses every
                    # ARRIVING message sharing its thread and identity. So the
                    # queue showed the question while the sync used it to answer
                    # for mail the user was never shown: never stored, never
                    # queued, never counted.
                    or_(
                        Email.is_reviewed == True,  # noqa: E712 — SQL boolean
                        _filed_on_an_application_that_answers(user_id),
                    ),
                )
            )
        ).all()
        settled_messages = {row[0] for row in rows}
        # SETTLED PER (THREAD, APPLICATION) — the cross-sync twin of the key in
        # :func:`pipeline.collect_review_items`, and #454 is only half fixed
        # without it. Settling by thread alone means the user classifying ONE of
        # Verkada's four rejections permanently suppresses the other three: they
        # are filtered out here on every later sync, so the within-sync fix
        # cannot reach them. Same :func:`pipeline.review_dedup_key` as every
        # other site, computed from the stored subject and snippet.
        settled_applications = {
            pipeline.review_dedup_key(
                message_id=message_id,
                thread_id=thread_id,
                subject=subject or "",
                snippet=snippet or "",
                identity_role=identity_role,
                identity_req_id=identity_req_id,
            )
            for (
                message_id,
                thread_id,
                subject,
                snippet,
                identity_role,
                identity_req_id,
            ) in rows
            if thread_id
        }
        offered = len(refs)
        refs = [
            r
            for r in refs
            if r.message_id not in settled_messages
            and pipeline.review_dedup_key(
                message_id=r.message_id,
                thread_id=r.thread_id,
                subject=r.subject or "",
                snippet=r.snippet or "",
                identity_role=r.identity_role,
                identity_req_id=r.identity_req_id,
            )
            not in settled_applications
        ]
        # THE ONLY PLACE THE REFUSAL IS OBSERVABLE (#630). A refused ref is
        # dropped before :func:`_persist_message_refs`, so it gets no row, no
        # queue entry and no counter — the event's signature is ABSENCE, and
        # absence is not a thing a later query can find. The read-only count
        # against the owner's real mail on 2026-09-02 could only ever measure
        # the PRECONDITION for that reason, and returned 0 pairs written in a
        # later sync than a settled row they share a thread with; a corpus can
        # show the class is reachable and can never report a rate. So the count
        # is emitted here or it does not exist anywhere.
        #
        # Ids and counts only, never a subject or a snippet — same rule as
        # :func:`_warn_if_capped`.
        refused = offered - len(refs)
        if refused:
            logger.info(
                "Settled filter refused %s of %s arriving review ref(s) for "
                "user_id=%s (#630: a refused ref is never stored)",
                refused,
                offered,
                user_id,
            )

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

    Idempotent and user-scoped. ``created`` includes any application recovered
    by :func:`reconcile_orphaned_classifications`.

    ONE row can still leave the board on this path, and it is now COUNTED AND
    NAMED: an AUTO row whose last linked email was re-attributed to a different
    EMPLOYER is dismissed by :func:`_dismiss_rows_left_without_mail` (called
    from the upsert, so it applies to both merge paths). That is still not the
    removal this function promises never to make — nothing is dropped for being
    absent from a bounded scan; the row is retired because its own evidence
    turned out to belong to another company, which is the alternative to leaving
    it stranded and permanently unremovable.

    It used to be left out of ``purged`` on the grounds that the company was
    still on the board under the row its mail moved to. That was true only of
    the same-employer case, which no longer removes anything at all — so what is
    left is a company leaving the board, and the user has to be told, on the one
    surface that offers the undo. Silence here is what let 22 removals pass
    unnoticed over two days.
    """

    removed: list[RemovedApplication] = []
    created, updated = await upsert_applications_for_user(
        session, user_id, rolled, removed
    )
    # Catch up on anything the user classified that never got an application.
    created += await reconcile_orphaned_classifications(session, user_id)
    needs_review = await _persist_review_items_additive(session, user_id, review)
    await session.commit()
    return MergeResult(
        created=created,
        updated=updated,
        purged=len(removed),
        needs_review=needs_review,
        removed=tuple(removed),
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
    # The messages this scan could not settle. A row holding one of these is
    # unproven, not stale — see :func:`_scan_contradicts`.
    unsure = frozenset(item.message_id for item in review)

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
        if not _scan_contradicts(list(linked), coverage, unsure):
            continue  # unseen, unsure, or not disproven — the row stays
        row.dismissed_at = now
        row.dismissed_reason = DISMISSED_BY_RESYNC
        session.add(row)
        removed.append(RemovedApplication(id=row.id, company=row.company))
    await session.flush()

    # The upsert appends anything IT takes off the board (a row whose last email
    # turned out to be another employer's) to the same list, so one receipt
    # names every removal the run made, whatever removed it.
    created, updated = await upsert_applications_for_user(
        session, user_id, rolled, removed
    )
    # Catch up on anything the user classified that never got an application.
    # Runs AFTER the upsert so an orphan whose employer is also in the fresh
    # rollup joins that row instead of creating a duplicate.
    created += await reconcile_orphaned_classifications(session, user_id)

    await _reset_review_queue(session, user_id, coverage)
    needs_review = await _persist_review_items(session, user_id, review)

    await session.commit()
    if removed:
        # Ids, not company names (see :func:`_warn_if_capped`).
        logger.info(
            "Re-sync removed %s auto row(s) for user_id=%s: application_id=%s "
            "(dismissed, not deleted — restorable)",
            len(removed),
            user_id,
            ", ".join(str(r.id) for r in removed),
        )
    return MergeResult(
        created=created,
        updated=updated,
        purged=len(removed),
        needs_review=needs_review,
        removed=tuple(removed),
    )


async def _orphan_training_examples(
    session, user_id: uuid.UUID, email_ids
) -> None:
    """Cut the corpus's link to ``emails`` rows that are about to be deleted.

    ``training_data.email_id`` is a bare indexed integer, not a foreign key, so
    deleting an email leaves the example pointing at nothing and no constraint
    complains. That is how ``training_data`` id 2 ended up naming ``emails`` id
    35: a label with no provenance, unauditable, still read by every retrain.

    The example itself is deliberately kept — it holds the subject and body it
    was labelled from, so the text remains inspectable — but it stops claiming
    an origin it no longer has. Consequence worth knowing: a review-queue
    message the rebuild deletes and re-persists comes back with a NEW id, so a
    later classification of it writes a SECOND example rather than updating the
    first (:func:`_add_training_example` is idempotent on ``email_id``).
    """

    ids = [i for i in (email_ids or []) if i is not None]
    if not ids:
        return
    await session.exec(
        sa_update(TrainingData)
        .where(TrainingData.user_id == user_id, TrainingData.email_id.in_(ids))
        .values(email_id=None)
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
    """Apply a user's status correction to the APPLICATION, and only to it.

    Makes the status STICKY (tags the row user-owned so future syncs never
    overwrite it). Scoped to the owner; returns the updated row or None when it
    does not exist for this user.

    It labels no mail, and that is the fix rather than an omission. This used to
    walk every linked email, flag it ``user_corrected``/``is_reviewed`` and
    write a ``training_data`` example read off the new STAGE. But the user is
    answering "what stage is this APPLICATION at?", which is not an answer to
    "what is this MESSAGE?" — the only question a training example can record.
    :func:`classify_review_item` already states that distinction in the other
    direction; this is the same rule seen from the other side.

    The damage was measured, not theorised. ``training_data`` id 2 labels an
    assessment-invite message ``rejection`` because the application it belonged
    to was set to rejected, and ``withdrawn``/``ghosted`` mapped to ``other``,
    so marking a real application ghosted taught the classifier that its own
    "we received your application" confirmation was not job mail. The flags were
    the second half: ``_persist_message_refs`` refuses to re-classify anything
    flagged, so a message the user never looked at froze at whatever the rules
    last guessed — ``emails`` id 58 is stored ``needs_review`` permanently.

    Setting a status on a REMOVED row restores it. Otherwise the correction
    would land on a row nobody can see — user-owned, sticky and invisible —
    which is a worse state than either of the two it came from. Someone
    deciding what stage an application is at is telling you they want it.

    EITHER KIND, INCLUDING ``user`` — and that is consistent with #597 rather
    than an exception to it. The rule there is that a hand dismissal yields to
    nothing EXCEPT the human acting on that same card again, and this is
    precisely that act: they are looking at this application and setting its
    stage. What #597 forbids is a decision about a MESSAGE reviving a card,
    which is a different surface answering a different question.
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

    await session.commit()
    await session.refresh(app)
    return app


async def record_role_correction(
    session,
    user_id: uuid.UUID,
    application_id: int,
    role: str | None,
) -> Application | None:
    """Store the role a human typed, and stop the sync writing over it.

    Issue #72. Nothing in the Gmail path can produce a role: bodies are never
    fetched and the subjects that are name the company. So ``position`` is ""
    forever on an auto-filed row, and this is the only way one ever gets a title.

    Set and clear are one call, as they are for a deadline. ``None`` — or
    anything that is only whitespace — CLEARS both the value and the claim, and
    clearing is not optional: a UI that offers "type a role" without "I was
    wrong, forget it" leaves a typo permanently welded to the row, since the sync
    is now forbidden from correcting it. The empty string is stored rather than
    NULL because ``position`` is NOT NULL and "" is what the whole codebase
    already means by "no role" (:data:`_NO_ROLE`).

    WHY A COLUMN AND NOT THE ``source`` FLIP
    ----------------------------------------
    :func:`record_status_correction` makes a status stick by moving the row from
    ``gmail`` to ``gmail_user``, and that would have been free here. It is wrong
    here. ``_is_auto_row(source)`` gates far more than the role inside
    :func:`upsert_applications_for_user`: the status advance, the
    reopen-after-rejection evidence and the employer-name restyle all sit in the
    same ``if``. Flipping it would mean that typing a job title silently stops
    every future rejection, interview and offer email from moving that card —
    trading the missing field for a much worse one, in a way the user could not
    possibly predict from the action they took. ``position_source`` claims one
    field and leaves the row the sync's in every other respect.

    WHAT IT DELIBERATELY DOES NOT TOUCH
    -----------------------------------
    ``role_token``. That is the MAIL's identity key: ``_pick_application``
    matches a cluster's normalised title against it, and treats a row with
    ``req_id`` and ``role_token`` both NULL as adoptable in place. Writing the
    user's phrasing into it would change which future clusters resolve onto this
    row — one that would have been adopted now finds no unidentified row and
    mints a second card beside it — and since the Gmail path extracts no role
    for these rows, a token in the user's words could never be matched by
    anything anyway. Risk without benefit. It stays NULL, and the sync stays
    free to identify the row from real mail evidence later.

    Scoped to the owner; returns the updated row, or None when it is not theirs.
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

    cleaned = (role or "").strip()
    app.position = cleaned or _NO_ROLE
    app.position_source = ROLE_FROM_USER if cleaned else None
    app.updated_at = datetime.utcnow()
    session.add(app)

    await session.commit()
    await session.refresh(app)
    return app


async def dismiss_application(
    session, user_id: uuid.UUID, application_id: int
) -> bool:
    """Mark a row 'not an application' — take it off the board.

    The row disappears from the board and the summary, but the row and its
    emails stay on disk so :func:`restore_application` can put it back. It used
    to delete both, which made a misclick as final as the re-sync bug was.
    Scoped to the owner. Returns False when the row does not exist for this user.

    Like :func:`record_status_correction`, this writes NO per-message training
    example. It used to record every linked email as ``other`` while leaving
    each one's stored ``classified_as`` alone, so the corpus said "not job mail"
    about a message the database still called an application confirmation — the
    same silent disagreement, one action along, and nothing could ever notice it
    (:mod:`tests.test_training_corpus_integrity` now does).

    Making them agree instead is not available here: the stored classification
    only survives a re-sync if the email is flagged ``user_corrected``/
    ``is_reviewed``, and that flag freezes it against every future
    re-classification. Freezing mail is a bad trade on a REVERSIBLE action —
    restore would hand back a live application whose messages are stuck at
    ``other`` forever, which is exactly the defect this change removes from the
    status path. A dismissal is a statement about the row; per-message labels
    come from the review queue, where the user is looking at the message.
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

    EITHER KIND, INCLUDING ``user``, for the reason
    :func:`record_status_correction` gives: this IS the human acting on that
    same card again, which is the one thing #597 lets overturn a hand
    dismissal. It is also the button labelled Restore.

    The other half of making removal recoverable: whether the row was dismissed
    by the user or taken off by a re-sync, this returns it verbatim — same id,
    same status, same filed date — and its mail AS CURRENTLY LINKED, because
    dismissal never deleted anything. Idempotent on an already-live row. Scoped
    to the owner; ``None`` when the row is not theirs.

    NOT "same linked emails", which is what this promised until #597 and was
    already fragile before it. A dismissal deletes and moves nothing, but later
    decisions do re-file individual messages onto other rows: a re-sync that
    re-attributes mail, :func:`_settle_thread_siblings` when an answer lands
    elsewhere, and now the mint that :func:`_resolve_application_for_email`
    forces when a hand-dismissed card's own message is reclassified. Restore
    does not claw those back, and should not — each of them was a decision made
    after the dismissal. The true half of the old sentence is kept: nothing is
    deleted, so restoring is always possible.
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
    """Hard-delete an application and everything that hangs off it.

    Children before parents, in exactly the order ``cloud/account.py``'s
    ``_DELETION_ORDER`` uses for the account-wide purge —
    ``email_embeddings → contacts → interviews → emails → applications``. Not a
    coincidence and not a second opinion: every foreign key in this schema is
    declared without ``ondelete`` (see migration ``d7da4461f034``), so on
    Postgres they are all NO ACTION/RESTRICT and any other order is a 500.
    There is one right answer to "what order?" for this schema and it is already
    written down; ``tests/test_application_delete_children.py`` asserts the two
    have not drifted apart.

    What each child DESERVES, which is a different question from what order:

    - **contacts / interviews** — user-authored, and their ``application_id`` is
      NOT NULL, so "unlink and keep" is not representable. Delete or refuse are
      the only two options, and DELETE is already the deliberately-final action
      here: ``dismiss``/``restore`` is the reversible one, and it destroys
      nothing. So they go with the application. Before this, they were not
      touched at all: SQLAlchemy's default cascade tried
      ``UPDATE contacts SET application_id = NULL`` and the flush raised.
    - **emails** — derived from Gmail and re-derivable by a re-sync. Deleted, as
      they always were.
    - **email_embeddings** — derived from an email and recomputable from it.
      They die with the email. Nothing was deleting them, and because the mail
      delete is a Core bulk statement no ORM cascade ran either, so on Postgres
      the ``DELETE FROM emails`` itself was refused.
    - **training_data** — derived in origin but a HUMAN's label, holding the
      subject and body it was labelled from. Kept, and only unlinked, so it stops
      naming an ``emails`` id that no longer exists (:func:`_orphan_training_examples`).
      Destroying a user's correction is not this endpoint's decision.
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
    doomed = (
        await session.exec(
            select(Email.id).where(
                Email.user_id == user_id, Email.application_id == application_id
            )
        )
    ).all()
    await _orphan_training_examples(session, user_id, doomed)
    if doomed:
        await session.exec(
            sa_delete(EmailEmbedding).where(
                EmailEmbedding.user_id == user_id,
                EmailEmbedding.email_id.in_(doomed),
            )
        )
    await session.exec(
        sa_delete(Contact).where(
            Contact.user_id == user_id, Contact.application_id == application_id
        )
    )
    await session.exec(
        sa_delete(Interview).where(
            Interview.user_id == user_id, Interview.application_id == application_id
        )
    )
    await session.exec(
        sa_delete(Email).where(
            Email.user_id == user_id, Email.application_id == application_id
        )
    )
    await session.delete(app)
    await session.commit()
    return True


async def _mint_scanned_email(
    session,
    user_id: uuid.UUID,
    message_id: str,
    scanned: ScannedMessageIn,
) -> Email:
    """Store a live-scan message so a correction has something to land on.

    Writes exactly what a sync would have written for the same message — the
    scan's own verdict, metadata only, no bodies — under the CALLER's user id.
    It is flushed before returning because ``_add_training_example`` keys on
    ``email.id``.

    ``received_at`` goes through :func:`pipeline.to_naive_utc` for the same
    reason every other write does: ``Email.received_at`` is TIMESTAMP WITHOUT
    TIME ZONE and asyncpg refuses an aware datetime. A value that survives
    parsing but not that conversion is refused rather than replaced with now().
    """

    received_at = pipeline.to_naive_utc(scanned.received_at)
    if received_at is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This message carries no usable receive time, so it cannot be stored.",
        )

    email = Email(
        user_id=user_id,
        source_account=EmailSource.GMAIL,
        message_id=message_id,
        thread_id=scanned.thread_id,
        subject=scanned.subject,
        sender_name=scanned.sender_name,
        sender_email=scanned.sender_email,
        received_at=received_at,
        body_snippet=pipeline.unescape_entities(scanned.snippet or "")[:500] or None,
        # ``identity_role``/``identity_req_id`` are left NULL on purpose. This
        # row comes from a CLIENT-supplied scan result, which carries a snippet
        # and no body, so there is nothing to derive from that the reader cannot
        # work out itself — and a client must never get to state which
        # application a message names. NULL sends every reader back to the
        # snippet, which is exactly what this path has always done.
        classified_as=scanned.category,
        classification_confidence=scanned.confidence,
        classification_method=scanned.method,
    )
    session.add(email)
    await session.flush()
    logger.info(
        "Stored a live-scan message for user_id=%s message_id=%s so its verdict "
        "could be corrected (scan said category=%s confidence=%s)",
        user_id,
        message_id,
        scanned.category.value if scanned.category else None,
        scanned.confidence,
    )
    return email


async def classify_review_item(
    session,
    user_id: uuid.UUID,
    message_id: str,
    category: EmailCategory,
    company: str | None = None,
    application_id: int | None = None,
    scanned: ScannedMessageIn | None = None,
    confirm_new_company: bool = False,
    none_of_these: bool = False,
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

    AND IT ASKS BEFORE OPENING AN EMPLOYER THAT LOOKS LIKE A TYPO. A ``company``
    naming no stored row but sitting one edit from one that does gets the same
    treatment: nothing is filed, the item stays in the queue, and the response
    carries ``needs_company_confirmation`` plus the ``suggested_company`` to
    offer back. Re-sending with that spelling files the mail against the row
    that already exists; re-sending with ``confirm_new_company`` opens the
    separate application. It never merges on the resemblance itself — joining
    two genuinely different employers would move a live application to a
    terminal status :func:`pipeline.advance_application_status` will not let it
    leave, a worse and far less recoverable outcome than the duplicate row this
    prevents. Application 119 ("Verkeda", a fifth row beside four "Verkada"
    ones, holding the rejection that should have settled one of them) is the
    duplicate in question.

    A message that is NOT on file is a 404 unless the caller supplies
    ``scanned``, in which case it is stored first and then corrected — that is
    the live-scan path (:class:`ScannedMessageIn`). The store happens BEFORE the
    ``needs_employer`` early return on purpose: that branch commits and returns
    without filing anything, and the whole point of it is that the caller
    re-sends the same classification with a company. Minting afterwards would
    make the second half of that round trip 404 on a message the first half had
    just accepted.
    """

    email = (
        await session.exec(
            select(Email).where(
                Email.user_id == user_id, Email.message_id == message_id
            )
        )
    ).first()
    if email is None:
        if scanned is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="Review item not found."
            )
        email = await _mint_scanned_email(session, user_id, message_id, scanned)

    status_value = _lifecycle_to_status(category)
    employer = None
    # Whether the name below came from the HUMAN rather than from the mail. Only
    # a hand-typed name can carry a typo, and only a hand-typed name has someone
    # standing there to answer a question about it.
    named_by_hand = False
    if status_value is not None:
        employer = pipeline.resolve_employer(
            email.sender_email or "", email.subject or "", email.sender_name
        )
        if employer is None and company:
            employer = pipeline.employer_from_text(company)
            named_by_hand = employer is not None

    if status_value is not None and employer is None:
        # Visible failure: keep the label for training, keep the item in the
        # queue, and tell the caller what is missing.
        await _add_training_example(session, user_id, email, category)
        await session.commit()
        # Neither the subject nor the correspondent's address goes in. This
        # line named both, which is strictly more mail text than the company
        # token CodeQL flagged in :func:`_warn_if_capped` — and it is redundant
        # as well as unsafe: the message was just persisted above, so its
        # subject and sender are on file under this very ``message_id``. The
        # subject's LENGTH is the one thing the row cannot tell you cheaply
        # (a truncated subject is a common reason resolution finds nothing).
        logger.warning(
            "Review classify for user_id=%s message_id=%s needs an employer: "
            "category=%s subject_len=%s. Subject and sender are on the stored "
            "message under that id.",
            user_id,
            message_id,
            category.value,
            len(email.subject or ""),
        )
        return {
            "classified_as": category.value,
            "application_id": None,
            "needs_employer": True,
            # Carried, not omitted. This branch builds its own dict, so without
            # these a client reads ``undefined`` where every other response
            # gives it ``false`` — and ``undefined`` is falsy only until
            # somebody writes ``=== false``. Nothing was filed here, so nothing
            # was restored.
            "restored": False,
            "restored_company": None,
            "message_id": message_id,
            "detail": (
                "Could not identify the employer for this email. Re-send the "
                "same classification with a 'company' to file it."
            ),
        }

    if named_by_hand and not confirm_new_company:
        suggestion = await _misspelled_employer(session, user_id, employer[0])
        if suggestion is not None:
            # Same shape as the branch above, and for the same reason: keep the
            # label, keep the item, file nothing, and say what is missing —
            # which here is a yes or a no rather than a name.
            #
            # ``needs_employer`` rides along DELIBERATELY. A client that predates
            # this flag reads the pair as the ordinary "name the company" prompt
            # and keeps the row in the queue, where typing the offered spelling
            # files it correctly. Sending only the new flag would have those
            # clients read a resolved 2xx, drop the item off the queue and file
            # nothing — the Crusoe incident this endpoint's honesty exists to
            # prevent, reintroduced by the very change meant to make it safer.
            await _add_training_example(session, user_id, email, category)
            await session.commit()
            # Ids only, no company strings. CodeQL's clear-text-logging rule
            # reads an employer name reaching a log sink as private data, and it
            # is right enough not to argue with: the two names are recoverable
            # from this user_id and message_id by anyone entitled to them, so
            # the line loses nothing an operator needs.
            logger.info(
                "Review classify for user_id=%s message_id=%s named a company one "
                "edit from an employer already on the board — asked instead of filing",
                user_id,
                message_id,
            )
            return {
                "classified_as": category.value,
                "application_id": None,
                "needs_employer": True,
                # Same reason as the branch above: nothing filed, nothing
                # restored, and the keys are present so a client never has to
                # tell "false" from "absent".
                "restored": False,
                "restored_company": None,
                "needs_company_confirmation": True,
                "suggested_company": suggestion,
                "message_id": message_id,
                "detail": (
                    f"'{employer[1]}' looks like '{suggestion}', which is already on "
                    f"your board. Re-send with company='{suggestion}' to file this "
                    "against it, or with 'confirm_new_company' to open a separate "
                    "application."
                ),
            }

    # WHICH ACT THIS IS — read BEFORE the write below destroys the evidence.
    #
    # ``classified_as = category`` overwrites the machine's verdict in place, so
    # after that line nothing on the row can answer "did the human change it?".
    # This flag used to be written ``True`` regardless, which made a human who
    # AGREES and a human who OVERRULES byte-identical. An audit read the flag on
    # production, concluded the classifier had never once auto-detected a
    # rejection, and said so — while the Palantir message it was reading had
    # scored ``rejection`` at 0.75, the right category, held under
    # ``AUTO_FILE_GATE`` for a human who then agreed with it.
    #
    # The machine's verdict is whichever of these is on record:
    #   * ``suggested_category`` — a PARKED row's proposal, which is exactly this
    #     column's purpose and survives the overwrite below untouched;
    #   * ``classified_as`` — a COMMITTED verdict, on a row that was filed and is
    #     now being relabelled (the two ``Crusoe | Application Received`` rows at
    #     0.95 are this shape, and are almost certainly agreements).
    # ``NEEDS_REVIEW`` is not a verdict — it is the typed null of that column —
    # so it is never read as one here.
    machine_verdict = email.suggested_category
    if machine_verdict is None and email.classified_as is not EmailCategory.NEEDS_REVIEW:
        machine_verdict = email.classified_as
    if machine_verdict is None:
        # No proposal and no commitment: a live-scan row minted from a
        # ``ScannedMessageIn`` carrying ``category=None``. The human supplied the
        # first verdict rather than ruling on one, and neither word applies.
        email.review_disposition = ReviewDisposition.UNATTRIBUTED
    elif machine_verdict is category:
        email.review_disposition = ReviewDisposition.CONFIRMED
    else:
        email.review_disposition = ReviewDisposition.OVERRIDDEN

    email.classified_as = category
    email.is_reviewed = True
    # Still unconditional, and deliberately so: this flag means "a human settled
    # this row", which an agreement does just as much as an override. The four
    # queries that filter ``user_corrected.is_(False)`` are asking that question
    # and would be wrong to get "no" for a confirmed row. What the flag could
    # never say is WHICH act it was, and that is now said above.
    email.user_corrected = True
    # A human decision is not a probabilistic verdict, so it carries no
    # probability. These two lines used to be absent, and the row kept the
    # confidence and method of the verdict it had just replaced — the Inbox
    # drew "rejection · 75% · corrected by you", where 75% was the machine's
    # certainty about a DIFFERENT category. That is the ``classified_as`` defect
    # family: a stored value that forges a decision nobody made.
    #
    # NULL and not 1.0. 1.0 is a claim of total certainty on the same 0–1 scale
    # the classifier reports on, drawn by the same meter, so it re-forges the
    # thing this removes — it merely moves the lie from 75% to 100%. NULL says
    # what is true: no probabilistic verdict exists for this row, and every
    # reader already treats the column as ``Optional`` (see
    # ``MailMessageResponse.confidence`` and ``FiledMailList``'s
    # ``typeof === "number"`` guard, both of which render nothing for null).
    #
    # Nothing selects corrected rows BY confidence, so NULL cannot strand them:
    # ``scripts/weekly_labeling_workflow.py`` and
    # ``scripts/generate_ml_monitoring_report.py`` — the only two readers left
    # that compare this column — both filter ``user_corrected.is_(False)``
    # before they ever look at the number. (The desktop routers under
    # ``jobtracker/api/`` had two more such queries; #298 deleted them with the
    # rest of the unmounted desktop surface, so they are no longer a
    # consideration either way.)
    email.classification_confidence = None
    email.classification_method = ClassificationMethod.USER

    result: dict[str, object] = {
        "classified_as": category.value,
        "application_id": None,
        "needs_employer": False,
        # DID THIS ANSWER PUT A CARD BACK ON THE BOARD (#595)? A sync that
        # changes the board without saying so is a defect this repo has already
        # produced twice, and a card appearing out of a review answer is the
        # same defect from the other side: the user answered a question about a
        # MESSAGE and their board gained a row. ``restored_company`` names it so
        # a client can say which. Both stay at their defaults on every path that
        # files nothing — ``needs_employer``, the typo confirmation, ``other``,
        # ``none_of_these`` — because no landing occurs on any of them. The
        # first two return dicts of their own and therefore repeat the keys
        # rather than inheriting these.
        "restored": False,
        "restored_company": None,
    }

    # The row an answer landed on that has to come off the dismissed pile —
    # applied AFTER ``_settle_thread_siblings`` below, not here. See the
    # else-branch for why the order is load-bearing.
    restore_target: Application | None = None

    if status_value is not None and employer is not None:
        token, display = employer
        # "NONE OF THESE" SKIPS RESOLUTION ENTIRELY, and that is why it is
        # carried as its own field rather than inferred from a missing id. Both
        # resolvers below answer "which existing row is this about?", and the
        # user has just said the answer is none of them. Running them anyway
        # reaches ``_pick_application``'s rule 4 — the employer's oldest live
        # row — which on a rejection is a live application moved to a terminal
        # status against an explicit human statement, and terminal is the one
        # thing ``advance_application_status`` will not walk back.
        #
        # This is not a loosening of rule 4, which is right for the sync it was
        # written for: only a caller that ASKED and was ANSWERED reaches here,
        # and only on a literal ``True``. The mint below is what the user said —
        # a lifecycle message about an application the board does not hold IS an
        # application the board is missing — and it is the cheap direction to be
        # wrong in: a spurious row is one dismiss click, a wrongly-terminal row
        # is permanent.
        app = None
        landing = LANDED_LINKED
        if not none_of_these:
            # The user's own answer to "which application is this about?"
            # outranks every inference below it — that is the whole point of
            # asking. Still validated: the row must be theirs and must be at the
            # employer this mail actually names, so a stale or wrong id degrades
            # to the normal resolution instead of filing a message under an
            # unrelated company.
            app = await _chosen_application(session, user_id, application_id, token)
            # A row the USER picked is the most confident landing there is: they
            # were shown the board and chose. Only the fallback can be blind.
            if app is None:
                app, landing = await _resolve_application_for_email(
                    session, user_id, token, email
                )
        # DERIVED ONCE, ABOVE THE BRANCH. It used to be bound only inside the
        # mint branch, so reading it in the else-branch raised UnboundLocalError
        # mid-request — after the session.adds and before the commit. Same
        # placement as the catch-up's, for the same reason.
        role, req_id = _email_identity_parts(email)
        if app is None:
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
                req_id=req_id,
                role_token=pipeline.normalize_role_token(role),
            )
            session.add(app)
            await session.flush()
        else:
            # THE ANSWER PUTS THE CARD BACK (#595). Filing a message onto a row
            # nobody can see is a 200 that changes nothing the user can find:
            # the message leaves the queue, ``is_reviewed`` goes true so it is
            # never asked again, and the board gains nothing. That is strictly
            # worse than the unreachable state #481 reported, and it is the
            # exact behaviour :func:`reconcile_orphaned_classifications` has
            # always avoided on the same evidence — a human putting a message
            # into a filing category. The two paths are answering one question
            # and they disagreed; this is the review path catching up.
            #
            # ONLY EVER A ``resync`` ROW, and there is no guard here saying so.
            # :func:`_resolve_application_for_email` and
            # :func:`_chosen_application` both exclude user-dismissed rows from
            # every landing (#597), so ``app`` here is live or machine-dismissed
            # by construction. A defensive ``if not _user_dismissed(app)`` would
            # be a branch nothing can reach and no test could red — the
            # exclusion is proved at its own choke point instead, and the
            # never-restore case is asserted on the state of the row.
            #
            # Non-filing answers restore nothing. The categories with no
            # ``status_value`` are the three :data:`CATEGORY_TO_STATUS` does not
            # map — ``other``, ``follow_up`` and ``needs_review`` — and none of
            # them reaches this block at all. ``none_of_these`` is not a
            # category but the picker's answer, and it mints rather than
            # landing. (This said "``other`` and ``none``" until the two-card
            # fix; ``none`` is not a member of :class:`EmailCategory`, and
            # naming a category that does not exist is how a reader concludes
            # the set is smaller than it is.)
            #
            # RECORDED HERE, APPLIED AFTER ``_settle_thread_siblings``, and the
            # order is not tidiness. That query filters on
            # :func:`_not_filed_on_an_application_that_answers`, so the moment
            # this row stops being dismissed it starts ANSWERING for its own
            # mail — and SQLAlchemy autoflushes the pending update before the
            # SELECT runs. Clearing the column inline therefore excluded the
            # thread's other messages from the settle that was about to happen:
            # they kept ``is_reviewed = False`` and ``NEEDS_REVIEW``, invisible
            # today only because their card is live again, and back in the
            # queue as unanswered the next time a re-sync dismisses it. Measured
            # on the ``m-thread-older`` fixture, which is why
            # ``test_answering_the_thread_settles_the_sibling_and_the_count_
            # moves`` now asserts the sibling's stored state and not just a
            # count — a count of zero is produced by both worlds.
            #
            # The settle must see the board the QUESTION was asked against: the
            # siblings were queued because no card answered for them, and one
            # human decision settles the whole conversation.
            if app.dismissed_at is not None:
                restore_target = app

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
            # The title and key this message names, onto a card that has
            # neither. Outside the `new_status != app.status` gate above on
            # purpose: a message can name the job without moving the stage, and
            # a card that stays at `applied` still deserves to say what for.
            #
            # Never on a blind landing — see the catch-up's note. This path is
            # where it matters most: 24 of the 26 corpus cards are rejections,
            # whose snippet reliably ends mid-preamble, so the cascade goes
            # blind exactly when the stored body-grade role is the only place
            # the job is named.
            if landing != LANDED_BLIND and _adopt_mail_identity(app, role, req_id):
                # Same bookkeeping as the catch-up's. Without it a card titled
                # by a review answer does not register as touched.
                app.updated_at = datetime.utcnow()
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
    # NOW the card comes back — after the settle has read the board as it stood
    # when the question was asked. Same transaction, so the user sees one
    # atomic outcome: the thread answered and the card on the board.
    if restore_target is not None:
        restore_target.dismissed_at = None
        restore_target.dismissed_reason = None
        restore_target.updated_at = datetime.utcnow()
        session.add(restore_target)
        result["restored"] = True
        result["restored_company"] = restore_target.company
    await session.commit()
    return result


def _review_key(row: Email) -> tuple[str, str | None] | str:
    """:func:`pipeline.review_dedup_key` for a row that is already stored."""

    return pipeline.review_dedup_key(
        message_id=row.message_id,
        thread_id=row.thread_id,
        subject=row.subject or "",
        snippet=row.body_snippet or "",
        identity_role=row.identity_role,
        identity_req_id=row.identity_req_id,
    )


def _thread_sub_key(row: Email) -> str | None:
    """WHICH application a THREADED stored row names, or ``None`` for none.

    Read off the second half of the row's own :func:`_review_key` rather than
    running the identity cascade a second time, so this cannot disagree with
    the key the queue compares — including its snippet truncation. An
    unthreaded row's key is a bare message id and names nothing here; only
    threaded rows reach the caller.
    """

    key = _review_key(row)
    return key[1] if isinstance(key, tuple) else None


async def _thread_sub_keys(
    session, user_id: uuid.UUID, thread_id: str
) -> set[str]:
    """Every application THIS USER's copy of one thread names, once each.

    Scoped to ``user_id`` for the reason
    ``tests/test_a_thread_is_scoped_to_its_owner.py`` exists: a Gmail thread id
    says nothing about whose mailbox it came from, and a census that reads a
    stranger's rows lets another tenant's mail decide what this user's thread
    names.

    UNFILTERED OTHERWISE, ON PURPOSE. A message already reviewed, or already
    filed on a live card, still says the conversation names that application.
    Counting only the rows the settle can still touch would read the real
    four-role thread with three roles already answered as a one-application
    thread — and #454's 1-in-4 guess would be back through the one caller that
    is allowed to settle an unknown row.
    """

    rows = (
        await session.exec(
            select(Email).where(
                Email.user_id == user_id,
                Email.thread_id == thread_id,
            )
        )
    ).all()
    return {key for key in (_thread_sub_key(row) for row in rows) if key is not None}


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

    Narrow on purpose: only siblings that NO APPLICATION OF THIS USER'S ANSWERS
    FOR and that are un-reviewed are touched, so a message already filed on a
    card the user can see — or on one they dismissed by hand (#597) — or one
    already decided, is left alone. They are marked reviewed, given the
    chosen category and linked to the same application — but NOT flagged
    ``user_corrected``, and no training example is written for them: the human
    read one message, and only that one is honest evidence of what they were
    labelling.

    THE SETTLED-TEST IS :func:`_not_filed_on_an_application_that_answers`, THE SAME ONE
    THE QUEUE READS. It used to be ``application_id IS NULL`` spelled out here,
    which is the predicate the queue replaced — and the two disagreeing is worse
    than either being wrong alone. A thread whose messages all link to one
    dismissed card surfaces as ONE queue entry; the user answers it; under the
    old clause every sibling was read as "already filed elsewhere" and left
    un-reviewed, so it stayed in the queue and the ``needs_review`` tile did not
    move. A count that does not change when you answer it is #445/#576's defect
    arriving for exactly the rows the queue was just taught to show.

    NOT A RELINK DECISION, which is what #591 assumed. ``application_id`` here
    is the answer's own landing, and for this shape it is the dismissed row the
    sibling already pointed at: :func:`_resolve_application_for_email` consults
    the message's OWN link first and returns it as ``LANDED_LINKED``. So the
    assignment below is a write of the id the sibling already held, and
    ``is_reviewed`` is the flag that actually settles it. Where the user's
    answer DOES land somewhere else, the sibling belongs there by construction —
    it is only in this list because it shares the answered message's
    :func:`pipeline.review_dedup_key`, which is to say it is about the same
    application.
    """

    if not email.thread_id:
        return 0

    conversation = (
        await session.exec(
            select(Email).where(
                Email.user_id == user_id,
                Email.thread_id == email.thread_id,
                Email.message_id != email.message_id,
                _not_filed_on_an_application_that_answers(user_id),
                Email.is_reviewed == False,  # noqa: E712 — SQL boolean
            )
        )
    ).all()
    # SAME THREAD IS NOT ENOUGH — issue #454. A sibling is settled by this
    # decision only when it is about the SAME APPLICATION, which for an ATS
    # thread is not everything in the conversation: classifying one of Verkada's
    # four acknowledgements used to mark the other three reviewed and link them
    # to that one application, which both loses three applications and files
    # their mail on the wrong card. The Crusoe pair still settle each other —
    # neither names an application, so both keys are ``None``.
    #
    # A ROW THAT NAMES NOTHING BECAUSE NOTHING ABOUT IT IS KNOWN is settled too
    # — issue #462 — but only where "unknown" can mean exactly one thing. Both
    # identity columns NULL and an empty ``body_snippet`` is silence for lack
    # of evidence, not a reader's answer: rows predating those columns were
    # deliberately not backfilled, and :func:`_record_scanned_email` writes
    # them NULL on EVERY client-relayed row on purpose, because
    # ``PipelineItemIn`` refuses to let a client state which application a
    # message is about. That second source is permanent by security design, so
    # no migration and no backfill can close this; the rule has to be about
    # what the thread says.
    #
    # And the thread says enough only when it names ONE application. Then the
    # unknown row's application is the only one it could be. A thread naming
    # two or more is left exactly as #454 left it — asked about again, which
    # beats a 1-in-4 guess that files mail on the wrong card and can settle a
    # live application terminally. The census is over the WHOLE thread, not
    # just the rows still settleable, or three already-answered roles would
    # make a four-role thread look like a one-application one.
    #
    # ``""`` IS NOT ``None`` HERE, and :func:`pipeline.identity_never_derived`
    # is where that is spelled: a derived "names nothing" is a reader's answer
    # and stays a value meaning "the same unknown", never evidence that the
    # thread's one named application is this row's.
    decided = _review_key(email)
    keyed = [(s, _review_key(s)) for s in conversation]
    siblings = [s for s, key in keyed if key == decided]
    unknown = [
        s
        for s, key in keyed
        if key != decided
        and _thread_sub_key(s) is None
        and pipeline.identity_never_derived(
            req_id=s.identity_req_id,
            role=s.identity_role,
            snippet=s.body_snippet or "",
        )
    ]
    if unknown:
        decided_sub_key = _thread_sub_key(email)
        named = await _thread_sub_keys(session, user_id, email.thread_id)
        if decided_sub_key is not None:
            # The answered row's own name, in case it is not flushed yet.
            named.add(decided_sub_key)
        if named == {decided_sub_key}:
            siblings.extend(unknown)

    for sibling in siblings:
        sibling.is_reviewed = True
        sibling.classified_as = category
        # NOT nulled here, unlike the classified message itself, and the
        # difference is not an oversight.
        #
        # A sibling has the same defect in a quieter form — it ends up holding
        # the human's category with the classifier's confidence in the verdict
        # that category replaced. But a sibling keeps ``user_corrected = False``
        # (it records whether a human read THIS message, and nobody did), and
        # that flag is exactly what makes the null safe on the corrected row:
        # ``generate_ml_monitoring_report._count_needs_review`` and
        # ``weekly_labeling_workflow`` both select
        # ``user_corrected.is_(False) AND (confidence IS NULL OR < threshold)``
        # and neither filters ``is_reviewed``. Nulling a sibling therefore moves
        # it INTO the needs-review count, and the labeling query's
        # ``case(confidence.is_(None), -1.0)`` ordering puts it first — a
        # message whose label the human already settled, leading the queue.
        # Measured against a migrated database, not reasoned about.
        #
        # Fixing it properly means teaching those two queries about
        # ``is_reviewed``, which is a change to what the monitoring numbers mean
        # and belongs in its own PR with its own before/after counts.
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


async def _connected_account_email(
    user_id: uuid.UUID, session=None
) -> str | None:
    """The email of the user's connected Gmail account, or ``None``.

    Used only to retarget "Open in Gmail" deep links at the mailbox the user
    actually linked (the reported bug: links opened the browser-default
    ``/u/0/`` account). Best-effort — any lookup failure yields ``None`` and the
    link falls back to the ``/u/0/`` form rather than breaking the response.
    Imported lazily to keep the cloud cold-start import graph thin.

    ``session`` — the calling handler's open session. The READ handlers must
    pass it: without it this lookup opens a session of its own, which under
    NullPool is a second serial TCP+TLS+auth connection per request — measured
    at ~470 ms of ``GET /applications/{id}``'s 850 ms in issue #203. Two rules
    keep the shared-session path as safe as the separate session was:

    - call it LAST, after every row the response needs has been read. A failed
      SELECT aborts the shared transaction, and "degrade to a /u/0/ link"
      must not become "500 the endpoint";
    - read-only handlers only. A handler that commits afterwards would turn
      that same aborted transaction into a failed write, so the split/write
      paths keep their own session and simply omit the argument.
    """

    try:
        from jobtracker.credentials.cloud import get_gmail_credentials

        stored = await get_gmail_credentials(user_id, session)
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
        # Gated on the value being present, exactly as ``due_source`` is: a
        # provenance for a field holding nothing is a claim about nothing.
        position_source=app.position_source if app.position else None,
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

        # Retarget each row's "Open in Gmail" link at the connected mailbox so
        # the dashboard cards open the right account, not the browser-default
        # /u/0/. Same session, and last — see _connected_account_email.
        account_email = await _connected_account_email(user_id, session)

    return CloudApplicationListResponse(
        applications=[_serialize(app, account_email) for app in rows],
        total=total,
    )


def _filed_on_an_application_that_answers(user_id: uuid.UUID):
    """THE PRIMITIVE: "an application of this user's already answers this mail".

    A SETTLEMENT PREDICATE, NOT A VISIBILITY ONE, and the two are no longer the
    same set. It was named ``_filed_on_a_live_application`` while every caller
    asked it a settlement question, which is how #597 could be read off the
    source: the queue asked "is this on the board?" and used the answer to
    decide whether to ASK ABOUT THE MAIL. Those come apart on exactly one row
    shape — a card the user dismissed BY HAND. It is off the board and it still
    answers for its mail.

    An application answers for its mail when EITHER:

      * it is on the board (``dismissed_at IS NULL``), or
      * the user removed it themselves (``dismissed_reason = 'user'``).

    THE ORGANISING RULE, the same one the ``dismissed_reason`` constants state:
    a MACHINE's removal yields to any newer evidence, a HUMAN's removal yields
    to nothing except the human acting on that same card again. A ``resync``
    dismissal is the rebuild's opinion, and arriving mail is better evidence
    than the opinion was — so its mail comes back and asks. A ``user``
    dismissal is a standing instruction, and re-asking every week is a
    predicate overruling a person.

    DO NOT "UNIFY" THE VISIBILITY QUERIES ONTO THIS. Board listings, the
    inbox's ``on_board`` badge (#489/#491) and
    :func:`employers_with_several_applications` all ask ``dismissed_at IS
    NULL`` and must keep asking it. A user-dismissed card answers for its mail
    AND is invisible; a sweep that made those one predicate would put dismissed
    cards back on the board, which is the opposite defect and a louder one.

    A DISMISSED ROW WITH ``dismissed_reason IS NULL`` IS TREATED AS
    MACHINE-DISMISSED — the ``==`` is false for NULL under SQL three-valued
    logic, and the ``or_`` therefore does not fire. That is deliberate and it
    errs in the documented safe direction: such a row does NOT answer, so its
    mail is surfaced and the user is asked one question, rather than being
    silently swallowed. A stranded message is unreachable forever; a surfaced
    one costs a click.

    NO SUCH ROW EXISTS TODAY, and the reason is worth writing down so nobody
    builds a test on the shape. ``dismissed_at`` and ``dismissed_reason``
    arrived in the SAME revision (``e4cbb4aadccd``, both nullable, no backfill)
    and all three writers set both, so a dismissed row without a reason cannot
    predate anything. The clause defends against a FUTURE writer that forgets
    the reason, not against history. A fixture that constructs the shape is
    exercising an unreachable state and proves nothing about production.

    ONE function names these columns, and both spellings of the settled idea are
    built from it — :func:`_not_filed_on_an_application_that_answers` for the readers,
    this one for the sync's write path. They are the same question and they
    drifted apart once already (#596): #587 moved the read path to this shape
    while :func:`_persist_review_items_additive` kept ``application_id IS NOT
    NULL``, so one row was "unsettled" to the queue and "settled" to the sync.

    THE WRITE PATH IS THE COMPLEMENT OF THE QUEUE'S PREDICATE MINUS
    ``classified_as == NEEDS_REVIEW``, and the missing clause is deliberate.
    Settlement suppresses regardless of the category the row is stored under: a
    conversation answered as ``APPLIED`` months ago must keep its later siblings
    out of the queue, and a stored category is not what makes a question
    answered — a live card or a human ``is_reviewed`` is. Re-adding the
    category clause here would un-settle every already-filed thread and re-ask
    its question on the next delta, so do NOT "unify" the two predicates whole
    the next time a "one predicate, two readers" sweep comes through. The
    shared part is this function; the clauses around it belong to each caller.

    The readers used to ask ``Email.application_id IS NULL``, which encodes "a
    linked message is already filed, so there is nothing to ask". True of a
    message linked to a card on the board, FALSE of one linked to a card a
    RE-SYNC dismissed: that removal takes the row off the board, out of the
    funnel and out of every tile on the strength of a rebuild's guess, so
    nothing about its mail is settled from the user's side. Hence the join to
    ``Application`` rather than a NULL test.

    Issue #481 found the state on the owner's account. The 2026-08-22 05:02Z
    re-sync dismissed application 115 (``dismissed_reason = 'resync'``) and, in
    the same pass, re-classified email 108 below the auto-file gate to
    ``NEEDS_REVIEW``. The additive persist rewrites ``classified_as`` and never
    clears ``application_id``, so the link outlived the verdict that justified
    it. Two independently reasonable behaviours; the combination was a real
    Microsoft message on no board, in no queue, actionable from no screen.

    WHY THIS SHAPE AND NOT ``IS NULL OR application_id IN (dismissed)``. That
    form has to enumerate the ways a link can fail to name a visible card, and
    it misses one: a link pointing at a row that no longer exists, or (a stale
    link) at another user's. Asked as this ``EXISTS`` does — "is there a LIVE
    application of MINE behind this link?" — all three answer the same way, and
    the answer for a link we cannot resolve is "no", which surfaces the message
    rather than stranding it. That is the safe direction: a surfaced message
    costs one question, a stranded one is unreachable forever. The subquery
    is scoped to ``user_id`` for the same reason the mail listing scopes its
    employer lookup (#489) — a stale link must not read across users.

    THE THREE CASES ARE NOT EQUALLY REACHABLE, and saying so is the point.
    Dismissed is the one #481 found in production. Cross-user is real, is what
    the ``user_id`` clause defends, and is tested on both paths. **Deleted is
    not a state this database can hold**: revision ``a9d3e5f2c841`` re-declared
    ``emails_application_id_fkey`` as ON DELETE CASCADE, and both delete paths
    (:func:`delete_application`, ``account.py``'s ``_DELETION_ORDER``) remove a
    row's mail before the row anyway. So the ``EXISTS`` is right about a
    dangling link by construction, not because one was ever observed. It is
    written down because SQLModel declares no ``ondelete`` on the field, so a
    SQLite test CAN construct a dangling link — and a test that greens against
    a state production cannot reach proves nothing at all.

    NOT a widening of ``is_reviewed``. A message the user already answered
    stays out even when its card is later dismissed: ``is_reviewed`` records
    that the question was asked and answered, and removing the row does not
    un-answer it. Every caller keeps that clause alongside this one — the
    readers as ``is_reviewed == False``, the sync as the other arm of its
    ``or_`` — and a rewrite that drops it is not a fix, it is a second bug.

    THE INDEX COST, MEASURED — paid by the readers, i.e. by the NEGATION of
    this ``EXISTS``. ``ix_emails_review_queue`` (revision ``c8f3a1d64b27``) is
    PARTIAL on ``classified_as = 'NEEDS_REVIEW' AND application_id IS NULL AND
    is_reviewed = false``, and a partial index is usable only while its
    predicate is implied by the query's. The queue's no longer implies
    ``application_id IS NULL``, so it stops using it.
    EXPLAIN (ANALYZE, BUFFERS) against that module's 20,000-row seeded corpus,
    both statements compiled from the ORM:

        before — Index Scan using ix_emails_review_queue …… 37 buffers, 0.04 ms
        after  — Nested Loop Anti Join over
                 ix_emails_user_id_classified_as_received_at
                 + applications_pkey ………………………………………………… 42 buffers, 0.31 ms

    Not a fallback to a sequential scan: the same migration's mail index carries
    ``(user_id, classified_as, received_at DESC)``, which is the whole outer
    side, and the anti-join probes the applications PRIMARY KEY once per row it
    keeps. Five buffers, on tables holding 52 and 65 rows in production. Left
    as it is rather than re-cut, and recorded here because
    ``tests/test_read_path_indexes_postgres.py`` will NOT tell the next reader:
    it retypes the handlers' predicates as literals instead of importing them,
    so it still measures the old query and stays green. (It has drifted once
    already — its ``SUMMARY_TILE`` literal is a ``count(DISTINCT coalesce(…))``
    the tile stopped issuing in #454.)

    THOSE NUMBERS ARE #587'S, MEASURED ON THE ONE-CLAUSE FORM, AND #597 DID NOT
    RE-RUN THEM. Saying so rather than re-presenting them as a measurement of
    this predicate: no Postgres was stood up for the widening. The added
    ``dismissed_reason`` test is expected to be free — it is a second filter on
    a tuple the anti-join has already fetched through ``applications_pkey``, so
    it changes no access path and touches no extra buffer — but "expected" is
    the honest word and a measurement is what it is not.
    """

    return exists(
        select(Application.id).where(
            Application.id == Email.application_id,
            Application.user_id == user_id,
            or_(
                # On the board.
                Application.dismissed_at.is_(None),
                # Off the board, but the user's own "no" stands (#597).
                Application.dismissed_reason == DISMISSED_BY_USER,
            ),
        )
    )


def _not_filed_on_an_application_that_answers(user_id: uuid.UUID):
    """The review queue's settled-test: "no application of mine answers this".

    The MECHANICAL negation of
    :func:`_filed_on_an_application_that_answers`, which carries the reasoning,
    the settlement-vs-visibility warning, the three-case rationale for the
    ``EXISTS``, the NULL-reason direction and the index cost. Not a second
    spelling of it — #596 was two spellings drifting, and ``~`` is what makes a
    second spelling impossible rather than merely discouraged.

    THREE callers, not the two this used to name: ``GET /applications/review``,
    the ``needs_review`` tile on ``GET /applications/summary``, and
    :func:`_settle_thread_siblings` — which is a WRITE, so "the read path" is a
    convenient label rather than an accurate one. The tile is a link to the
    queue and a tile counting a different set sends the user to a screen that
    disagrees with the number they clicked. This repo has the scar
    twice over — the header said "+50 this wk" beside a momentum panel reading
    7 — so the two share the accessor rather than each spelling it out. Callers
    keep ``Email.is_reviewed == False`` alongside this one.
    """

    return ~_filed_on_an_application_that_answers(user_id)


@router.get("/summary", response_model=ApplicationSummaryResponse)
async def application_summary_cloud(
    user_id: uuid.UUID = Depends(current_user),
    week_start: str | None = Query(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=(
            "The READER's own week-start Monday, `YYYY-MM-DD`. Optional, and "
            "omitted on every server render — the server does not know the "
            "caller's zone at first paint, so the count is measured from its "
            "own UTC Monday and `week_start` in the response says so. The "
            "browser sends its Monday once it has hydrated. Must be a Monday "
            "within seven days of the server's; anything else is 422 rather "
            "than snapped (#518)."
        ),
    ),
) -> ApplicationSummaryResponse:
    """Return counts-only pipeline summary for the authenticated user.

    Powers the dashboard stat tiles + funnel without transferring a single
    application row. Two aggregate queries run against the composite
    ``(user_id, status)`` index:

    - ``GROUP BY status`` → per-status counts (≤7 rows regardless of how many
      applications the user has). ``total`` is their sum.
    - a windowed ``COUNT(*)`` for applications the user APPLIED to since a
      calendar week's Monday (see :func:`_week_start`). Not "created", which is
      when our sync inserted the row, and not a trailing seven days.

    Both are O(1) in transfer and index-assisted in the DB, so this endpoint
    stays flat as an account scales from 10 to 10,000 applications — the whole
    reason it exists instead of counting client-side over the full list.

    WHOSE MONDAY (#518). Counts alone cannot carry a zone, so this used to be
    the UTC Monday and nothing else, while the momentum caption on the same
    screen counted the READER's — and for a reader west of UTC there was a
    window each week, the size of their offset, in which the header had rolled
    over and the caption had not. The reader's Monday is now an optional
    parameter, validated by :func:`_reader_week_start`, and the Monday actually
    counted comes back in the response so the client can tell whether it needs
    to ask again. Absent the parameter the behaviour is exactly what it was.
    """

    now = datetime.utcnow()
    # THE MONDAY, and the ``or`` is the whole SSR contract: no parameter means
    # no reader to ask about, so the answer is the UTC week — byte-identical to
    # what this endpoint returned before #518, which is what makes the
    # server-rendered header safe to hydrate.
    counted_week_start = _reader_week_start(week_start, now.date()) or _week_start(now.date())
    # THE LAST DAY OF IT, and it is a `min` rather than either bound alone.
    #
    # `week_start + 6` is the week's own far edge, and it is what stops a
    # reader whose Monday is AHEAD of the server's (east of UTC, in their early
    # Monday while UTC is still Sunday) from being counted across eight days.
    #
    # `now.date()` is the "we do not count the future" rule this window has
    # always carried, and it has to stay: `POST /applications` accepts any ISO
    # `applied_date` with no upper bound (`_parse_applied_date`), so a row dated
    # next month is reachable by hand. The momentum caption drops those too —
    # `dailyCounts` discards a negative age — so keeping the clamp is what makes
    # the two surfaces agree rather than a leftover.
    #
    # With no parameter this is `min(utc_week_start + 6, today)`, which is
    # `today` on every day of the week: the default path is unchanged.
    counted_week_end = min(counted_week_start + timedelta(days=6), now.date())

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

        # COUNTED ON ``applied_date`` — when the user applied — and NOT on
        # ``created_at``, which is when our sync inserted the row (#509).
        #
        # Measured on the owner's production board the day this changed: the
        # dashboard header read "+47 this wk" for applications submitted across
        # a fortnight, because one sync had just ingested them. 47 of the 47
        # dated rows had an ``applied_date`` in a different calendar week from
        # their ``created_at``, so not one was counted correctly. The true
        # answer was 7. The number a user reads here is about THEIR week, and
        # `created_at` is a fact about our batch.
        #
        # ``applied_date`` is a DATE and the bounds are timestamps, so the
        # thresholds are converted to days explicitly rather than left to an
        # implicit cast — the comparison really is a day comparison and should
        # say so.
        #
        # A row with NO ``applied_date`` counts toward NOTHING, deliberately.
        # ``COALESCE(applied_date, created_at)`` would reintroduce the entire
        # bug for precisely the rows whose date we cannot know, and would do it
        # invisibly. On the live board every such row is a seeded demo row and
        # every row that came from real mail carries a date. ``>=`` against a
        # NULL is already NULL/false in SQL, so this is what the predicate does
        # anyway; it is written down because it is a decision, not an accident.
        #
        # `lib/dashboard/summary.ts` counts the same way for the demo twin.
        # The two must change together or the twin and the signed-in board
        # disagree about the same number, which this repo has a scar from.
        this_week = (
            await session.exec(
                select(func.count())
                .select_from(Application)
                .where(
                    Application.user_id == user_id,
                    Application.dismissed_at.is_(None),
                    Application.applied_date >= counted_week_start,
                    Application.applied_date <= counted_week_end,
                )
            )
        ).one()

        # Counted by the same key as the queue this number links to — otherwise
        # the tile says "2 need classification" for one conversation the queue
        # shows once, and the two disagree in the UI.
        #
        # NOT `COUNT(DISTINCT COALESCE(thread_id, message_id))`, which is what
        # this was until #454. That expression can only see the thread, and the
        # queue no longer keys on the thread alone: Verkada's four applications
        # share one, so the tile read 1 where the queue now lists 4. The key
        # needs the subject and snippet, which SQL here cannot parse, so the
        # rows come back and :func:`pipeline.review_dedup_key` counts them —
        # the same function the endpoint uses, so the two cannot drift.
        #
        # Bounded by the queue itself: un-reviewed ``needs_review`` rows that no
        # application of this user's answers for — on the board, or removed by
        # their own hand (#597) — see
        # :func:`_not_filed_on_an_application_that_answers`, which ``GET
        # /applications/review`` reads too so the tile and the queue it links to
        # cannot count different sets. Four columns of each.
        pending = (
            await session.exec(
                select(
                    Email.message_id,
                    Email.thread_id,
                    Email.subject,
                    Email.body_snippet,
                    # Read, not re-derived. A row whose title was printed past
                    # Gmail's ~200 characters carries the identity the reader
                    # extracted from the body; recomputing it from the snippet
                    # here would give this site a different answer to the one
                    # the queue was built with.
                    Email.identity_role,
                    Email.identity_req_id,
                ).where(
                    Email.user_id == user_id,
                    Email.classified_as == EmailCategory.NEEDS_REVIEW,
                    _not_filed_on_an_application_that_answers(user_id),
                    Email.is_reviewed == False,  # noqa: E712
                )
            )
        ).all()
        needs_review = len(
            {
                pipeline.review_dedup_key(
                    message_id=message_id,
                    thread_id=thread_id,
                    subject=subject or "",
                    snippet=snippet or "",
                    identity_role=identity_role,
                    identity_req_id=identity_req_id,
                )
                for (
                    message_id,
                    thread_id,
                    subject,
                    snippet,
                    identity_role,
                    identity_req_id,
                ) in pending
            }
        )

    status_counts: dict[str, int] = {}
    total = 0
    for status_value, count in grouped:
        key = status_value.value if hasattr(status_value, "value") else str(status_value)
        status_counts[key] = count
        total += count

    return ApplicationSummaryResponse(
        total=total,
        this_week=this_week,
        # Said out loud, not left for the client to re-derive. The browser
        # compares this with the reader's own Monday and re-asks only when they
        # differ — which is also what keeps a page rendered just before UTC
        # midnight from correcting itself against the wrong server day.
        week_start=counted_week_start,
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

    # A HAND-CREATED APPLICATION IS ALWAYS DATED, and it defaults to today.
    #
    # `applied_date` is optional on this endpoint and the Add-application form
    # leaves its date field blank by default, so a row could be created with no
    # date at all. That was invisible while "this week" counted `created_at`;
    # since #509 counts on `applied_date`, an undated row can never appear in
    # that number — silently, because `>= NULL` is false in SQL. A user who
    # typed an application in by hand and did not fill the date would simply
    # never see it in their week, with nothing anywhere saying why.
    #
    # The comment this replaced claimed every undated row was a seed row or
    # mail-derived. That was true of the board it was measured on and false as a
    # general statement: manual creation is a third source, and it is the one a
    # real user reaches.
    #
    # Today is a DEFAULT, not an invention: the form now shows today's date in
    # the field, so the value is visible and editable before it is submitted,
    # and someone back-filling an older application changes it there. Rows that
    # come from mail are unaffected — they carry the message's own receipt date
    # and never reach this line.
    applied_date = _parse_applied_date(data.applied_date) or datetime.utcnow().date()
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


def _employer_token_for(email: Email) -> str | None:
    """The employer match TOKEN this stored message resolves to, or ``None``.

    ONE ACCESSOR, because two readers need the same answer and they used to
    reach it separately: the review queue's hold reason counts an employer's
    siblings under this token, and the mail listing ships it so the filed
    ledger can ask which of those siblings a correction is about. A second
    call site spelling the arguments differently is how "two readers, one
    shape" starts, and the argument order here is not obvious — subject is
    second, the display name third.

    Returns the token half of :func:`pipeline.resolve_employer`, which is the
    key :func:`_company_rows` narrows on. The display half is deliberately not
    returned: nothing that consumes this renders it, and a display name is a
    different grade of claim (see :func:`pipeline.employer_named_in_body`).
    """

    resolved = pipeline.resolve_employer(
        email.sender_email or "", email.subject or "", email.sender_name
    )
    return resolved[0] if resolved else None


def _sibling_counts(company_names: Sequence[str | None]) -> Counter[str]:
    """How many applications sit under each employer TOKEN the resolver can emit.

    MIRRORS :func:`_company_rows`, and must keep mirroring it. That function
    answers "which rows belong to this employer" for the sync, and it does so
    with a UNION of two rules: the stored name normalized equals the token, OR
    the stored name's LEADING normalized word equals it. Both halves are
    load-bearing, and the comment there records what it cost to learn — an
    early return that kept only the exact half grew six rows each for "IXL
    Learning" and "Torc Robotics".

    Counting on the normalized full name alone — which is what this did first —
    silently misses every multi-word employer, because ``resolve_employer``
    returns a token built from the FIRST WORD of the display name:

        stored "Path Robotics" -> "path robotics"   token "path"    MISS
        stored "IXL Learning"  -> "ixl learning"    token "ixl"     MISS
        stored "Verkada"       -> "verkada"         token "verkada" match

    So the branch that needs the count would have fired only for single-word
    employers and reported a WRONG reason everywhere else, which is precisely
    the class of defect #507 exists to remove — arriving inside the fix for it.

    Two employers sharing a leading word land on one key on purpose. The
    resolver cannot tell "Path Robotics" from "Path Analytics" either, so the
    honest count for token ``path`` is both of them, and asking the user which
    application this is beats guessing one.

    Each row contributes to a key AT MOST ONCE: for a single-word employer the
    full name and the leading word are the same string, and counting it twice
    would push a lone application over the "several" threshold and ask a
    question with one possible answer.
    """

    counts: Counter[str] = Counter()
    for name in company_names:
        if not name:
            continue
        normalized = pipeline.normalize_company_name(name)
        if not normalized:
            continue
        leading = normalized.split(" ")[0]
        for key in {normalized, leading}:
            counts[key] += 1
    return counts


def _hold_reason_for(
    email: Email, siblings: "Counter[str]"
) -> tuple[str | None, str | None]:
    """Why this queue row is waiting, and the employer to confirm if there is one.

    Returns ``(reason, suggested_employer)``. The second is non-None only for
    :data:`pipeline.HOLD_CONFIRM_EMPLOYER`, where the filing path could not name
    the employer but the body does — the row needs a name to put in front of the
    user, and re-deriving it in the web would be a second reading of the same
    message that could disagree with this one.

    The employer is resolved here, once, and used for two things: whether one
    could be named at all, and how many applications sit under it. Both feed
    :func:`pipeline.hold_reason`, which owns the precedence — this function is
    the I/O-shaped half (a stored row, a count off the board) and holds no
    policy of its own.

    ``suggested_category`` is what tells a genuine "the classifier had no
    opinion" apart from a real proposal that merely scored low.
    ``classified_as`` cannot: every row in this queue stores ``needs_review``,
    which is the typed null and not a verdict. It is ALSO the category the
    fileability test needs, for the same reason: ``classified_as`` is the same
    typed null on every row here, so testing it would ask every row the same
    question and get the same answer.
    """

    subject = email.subject or ""
    sender_email = email.sender_email or ""
    snippet = (email.body_snippet or "")[: pipeline.STORED_SNIPPET_CHARS]

    # The token is the match key the counter was built under. Read through the
    # one accessor the mail listing also uses, so the queue and the ledger
    # cannot disagree about which employer a message names.
    token = _employer_token_for(email)
    sibling_count = siblings.get(token, 0) if token else 0

    reason = pipeline.hold_reason(
        confidence=email.classification_confidence,
        subject=subject,
        sender_email=sender_email,
        sender_name=email.sender_name,
        snippet=snippet,
        has_proposal=email.suggested_category is not None,
        sibling_applications=sibling_count,
        # ``EmailCategory`` is a ``str`` Enum whose values are exactly the
        # pipeline's category strings, so ``.value`` needs no translation table.
        category=(
            email.suggested_category.value
            if email.suggested_category is not None
            else None
        ),
        # The column the sync wrote from the FULL body, which the ~200-char
        # stored snippet cannot always reproduce (#484).
        stored_role=email.identity_role,
    )

    suggested_employer: str | None = None
    if reason == pipeline.HOLD_CONFIRM_EMPLOYER:
        named = pipeline.employer_named_in_body(snippet, sender_email)
        suggested_employer = named[1] if named else None
    return reason, suggested_employer


@router.get("/review", response_model=ReviewQueueResponse)
async def review_queue_cloud(
    user_id: uuid.UUID = Depends(current_user),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
) -> ReviewQueueResponse:
    """The needs-classification queue: uncertain verdicts awaiting a decision.

    These are the metadata-only Email rows the sync flagged ``needs_review``
    that no application of theirs already answers for
    (:func:`_not_filed_on_an_application_that_answers` — a card on the board, or
    one they removed by hand, which is a standing "no" and not a question) and
    that the user has not already reviewed — the real target of the dashboard's "N need classification"
    number, which is otherwise a dead count. Newest-first.

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
                    _not_filed_on_an_application_that_answers(user_id),
                    Email.is_reviewed == False,  # noqa: E712
                )
                .order_by(Email.received_at.desc())
                .limit(limit)
            )
        ).all()

        # HOW MANY APPLICATIONS EACH EMPLOYER HOLDS, for the hold reason (#507).
        #
        # One query for the whole board rather than ``_company_rows`` per queue
        # row: the queue is capped at ``limit`` and the board is small, but a
        # per-row lookup is two statements each and this answers every row at
        # once. Only the company is selected — the rows themselves are not
        # needed, just how many share an employer.
        #
        # Dismissed rows are excluded for the same reason every other tile
        # excludes them: a removed application is not one of the candidates the
        # user would be asked to choose between.
        #
        # Normalized with ``normalize_company_name`` — the SAME rules the tokens
        # were minted under. Matching on ``lower(company)`` instead is what once
        # filed a second "Together AI" row on every sync.
        company_names = (
            await session.exec(
                select(Application.company).where(
                    Application.user_id == user_id,
                    Application.dismissed_at.is_(None),
                )
            )
        ).all()

        # Same session, and last — see _connected_account_email.
        account_email = await _connected_account_email(user_id, session)

    siblings = _sibling_counts(company_names)

    items: list[ReviewItemResponse] = []
    seen_threads: set[tuple[str, str | None] | str] = set()
    for e in rows:
        # One entry per (conversation, application) — see
        # :func:`pipeline.review_dedup_key`. Mail with no thread id stands alone
        # under its own message id.
        key = pipeline.review_dedup_key(
            message_id=e.message_id,
            thread_id=e.thread_id,
            subject=e.subject or "",
            snippet=e.body_snippet or "",
            identity_role=e.identity_role,
            identity_req_id=e.identity_req_id,
        )
        if key in seen_threads:
            continue
        seen_threads.add(key)
        hold_reason_value, suggested_employer_value = _hold_reason_for(e, siblings)
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
                suggested_category=(
                    e.suggested_category.value if e.suggested_category else None
                ),
                # Stored first, re-derived only as a fallback — same reason as
                # ``stored_role`` in ``_hold_reason_for``: ``identity_role`` was
                # written from the whole body, this snippet is the first ~200
                # characters of it, and a title past that boundary exists in the
                # column and nowhere else (#484). Re-deriving first would blank
                # a role on screen that the sync had already read.
                role=e.identity_role
                or pipeline.role_from_message(
                    e.subject or "",
                    (e.body_snippet or "")[: pipeline.STORED_SNIPPET_CHARS],
                ),
                hold_reason=hold_reason_value,
                suggested_employer=suggested_employer_value,
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

    A ``company`` one edit from an employer already on the board answers with
    that flag PLUS ``needs_company_confirmation: true`` and a
    ``suggested_company``, and still files nothing — "Verkeda" beside four
    "Verkada" rows is how a rejection opened a fifth application instead of
    settling one. Re-POST with the suggested spelling to file it there, or with
    ``confirm_new_company: true`` to insist the two employers are different.

    Accepts a correction for a message this database has never seen, provided
    the caller sends its metadata as ``message`` — the live scan's rows are
    verdicts about un-stored mail, and without this they were 404s. The message
    is stored under the JWT's user id and nowhere else, so the worst a bogus id
    can do is add a row to the caller's own mail listing.
    """

    async with get_session() as session:
        # BY KEYWORD, and that is not a style preference. This is the FIFTH
        # rebuild of the classify body — browser, proxy in, proxy out, this,
        # then the function — and a positional list is how `confidence`,
        # `applied_date` and `url` were each lost on a hop like it. Positionally,
        # a field inserted into `ReviewClassifyRequest` above its neighbours
        # silently shifts every argument after it and every type still checks.
        return await classify_review_item(
            session,
            user_id,
            message_id,
            data.category,
            company=data.company,
            application_id=data.application_id,
            scanned=data.message,
            confirm_new_company=data.confirm_new_company,
            none_of_these=data.none_of_these,
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


@router.get("/mail", response_model=MailListResponse)
async def mail_listing_cloud(
    user_id: uuid.UUID = Depends(current_user),
    page: int = Query(1, ge=1, description="1-based page number."),
    page_size: int = Query(
        DEFAULT_MAIL_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Rows per page (capped so a single response stays bounded).",
    ),
    category: EmailCategory | None = Query(
        None,
        description=(
            "Filter to one stored verdict. Does not affect `category_counts`."
        ),
    ),
    q: str | None = Query(
        None, description="Case-insensitive substring match on subject/sender."
    ),
) -> MailListResponse:
    """Every message this user has stored, whatever the classifier decided.

    Declared ABOVE ``GET /{application_id}`` deliberately: FastAPI matches in
    declaration order and would otherwise try ``"mail"`` as an int path param
    and answer 422. Same pattern as ``/summary``, ``/review`` and ``/statuses``.

    WHY THIS EXISTS
    ---------------
    ``/review`` is the only other listing of classified mail, and it filters to
    ``needs_review AND not-filed-on-a-live-card AND not-yet-reviewed``. That is
    the right set for a work queue and the wrong set for a correction surface,
    because those three predicates make a verdict unreachable the moment it is
    touched:

    * a message already reviewed once drops out for good — emails 58 and 59 of
      the owner's account sit at ``needs_review`` with ``is_reviewed = true``
      and no endpoint in the product could name them, so no screen could
      change them;
    * a message filed on an application the user can see drops out too, so a
      ``rejection`` filed as ``applied`` is a wrong stored verdict a user can
      see on the board and never correct at its source;
    * and for an account whose mail all classified confidently, ``/review``
      returns zero rows and the review UI never renders at all.

    The write path never had that restriction — :func:`classify_review_item`
    selects on ``(user_id, message_id)`` alone — so correcting any of these
    already worked. What was missing was a way to *find* them. This is that
    read, and nothing more: no new write, no body, no state change.

    SHAPE
    -----
    Newest first with an ``id`` tiebreak, for the same reason the applications
    listing has one: a sync writes a batch of rows carrying identical
    ``received_at`` values, tied rows are free to come back in a different
    order per request on Postgres, and paging a partial order drops some rows
    and repeats others.

    One entry per MESSAGE — unlike ``/review``, which collapses a thread to its
    newest message because being asked the same question twice is duplicated
    work. Here the user is auditing what is stored, and every stored row is
    correctable individually, so hiding siblings would hide exactly the rows
    this endpoint exists to reach.
    """

    # Two filter sets, and the difference is the contract: `total` counts the
    # query being paged (category + q), while the chips' counts must ignore
    # `category` or every chip but the active one reads zero.
    base_filters = [Email.user_id == user_id]
    needle = (q or "").strip()
    if needle:
        like = f"%{needle}%"
        base_filters.append(
            or_(
                Email.subject.ilike(like),
                Email.sender_name.ilike(like),
                Email.sender_email.ilike(like),
            )
        )

    page_filters = list(base_filters)
    if category is not None:
        page_filters.append(Email.classified_as == category)

    offset = (page - 1) * page_size

    async with get_session() as session:
        total = (
            await session.exec(
                select(func.count()).select_from(Email).where(*page_filters)
            )
        ).one()

        grouped = (
            await session.exec(
                select(Email.classified_as, func.count())
                .where(*base_filters)
                .group_by(Email.classified_as)
            )
        ).all()

        stmt = (
            select(Email)
            .where(*page_filters)
            # The tiebreak, and it has to be here. A sync writes a batch of
            # rows inside the same second, so `received_at` alone leaves them
            # tied and Postgres may return them in a different order per
            # request — which drops and repeats rows across pages.
            .order_by(Email.received_at.desc(), Email.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await session.exec(stmt)).all()

        # ONE query for the whole page's employers, not one per row. Scoped to
        # the owner as well as the id set: a linked id is only ever this user's,
        # and re-asserting it here means a stale link cannot read across users.
        linked_ids = {e.application_id for e in rows if e.application_id is not None}
        company_by_application: dict[int, str] = {}
        # The linked rows that are still ON THE BOARD. Carried by the SAME query
        # that resolves the employer — one more selected column, no extra round
        # trip and no per-row lookup — so the two can never disagree about which
        # application they are describing (#489).
        on_board_applications: set[int] = set()
        if linked_ids:
            pairs = (
                await session.exec(
                    select(
                        Application.id,
                        Application.company,
                        Application.dismissed_at,
                    ).where(
                        Application.id.in_(linked_ids),
                        Application.user_id == user_id,
                    )
                )
            ).all()
            company_by_application = {
                application_id: company for application_id, company, _ in pairs
            }
            # ``dismissed_at IS NULL`` AND NOTHING ELSE. The badge answers
            # "is there a card for this on your board?", which is a visibility
            # question, and #481's second defect was it answering yes when the
            # board held nothing. A hand-dismissed card ANSWERS for its mail
            # (:func:`_filed_on_an_application_that_answers`) and is still not
            # on the board, so unifying the two would re-create the false badge
            # this fixed (#489/#491) — from the other direction and on rows the
            # user removed themselves.
            on_board_applications = {
                application_id
                for application_id, _, dismissed_at in pairs
                if dismissed_at is None
            }

        # Same session, and last — see _connected_account_email.
        account_email = await _connected_account_email(user_id, session)

    category_counts: dict[str, int] = {}
    for stored_category, count in grouped:
        if stored_category is None:
            # An unclassified row is real, but it has no chip to land on and
            # `dict[str, int]` has no key for it. Counted nowhere rather than
            # under a made-up name; `total` still includes it.
            continue
        key = (
            stored_category.value
            if hasattr(stored_category, "value")
            else str(stored_category)
        )
        category_counts[key] = count

    messages = [
        MailMessageResponse(
            message_id=e.message_id,
            thread_id=e.thread_id,
            subject=e.subject,
            sender_name=e.sender_name,
            sender_email=e.sender_email,
            received_at=e.received_at.isoformat() if e.received_at else None,
            # `body_snippet` — the stored preview. Never `body_text`/`body_html`.
            snippet=e.body_snippet,
            category=e.classified_as.value if e.classified_as else None,
            confidence=e.classification_confidence,
            method=e.classification_method,
            user_corrected=e.user_corrected,
            review_disposition=(
                e.review_disposition.value if e.review_disposition else None
            ),
            is_reviewed=e.is_reviewed,
            application_id=e.application_id,
            company=(
                company_by_application.get(e.application_id)
                if e.application_id is not None
                else None
            ),
            on_board=e.application_id in on_board_applications,
            # Unconditional: the population that needs it is the UNLINKED one.
            # Pure CPU over fields already loaded — no query, no body read.
            employer_token=_employer_token_for(e),
            gmail_link=pipeline.gmail_deeplink(
                thread_id=e.thread_id,
                message_id=e.message_id,
                account_email=account_email,
            ),
        )
        for e in rows
    ]

    return MailListResponse(
        messages=messages,
        total=total,
        page=page,
        page_size=page_size,
        category_counts=category_counts,
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

    The mail read is CAPPED (``_APPLICATION_MAIL_CAP``). It was unbounded, and
    an unbounded read is a latent outage rather than a slow page — one
    application's mail is small today and nothing in the product bounds it. When
    the cap binds, ``split_candidates`` comes back EMPTY rather than computed:
    the read is newest-first and the split is decided by the OLDEST message in
    each cluster, so a proposal built from a truncated set would name the wrong
    row to retain. Refusing to guess is the same discipline ``NEEDS_REVIEW``
    encodes for a classifier verdict; the messages themselves are still shown.
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
        emails = list(
            (
                await session.exec(
                    select(Email)
                    .where(
                        Email.user_id == user_id,
                        Email.application_id == application_id,
                    )
                    .order_by(Email.received_at.desc())
                    .limit(_APPLICATION_MAIL_CAP)
                )
            ).all()
        )
        truncated = _application_mail_truncated(
            emails, user_id, application_id, "GET /applications/{id}"
        )
        # Same session, and last (all rows above are already read) — see
        # _connected_account_email.
        account_email = await _connected_account_email(user_id, session)
        serialized = _serialize(app, account_email)
        messages = [_message_ref_response(e, account_email) for e in emails]
        clusters = [] if truncated else cluster_stored_mail(emails)
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

    # Deliberately on its OWN session, unlike the read handlers: this handler
    # COMMITS below, and a failed credential SELECT inside the shared session
    # would abort the transaction and turn "degrade the link" into "fail the
    # split". A rare interactive action can afford the extra connection; the
    # navigation-path reads cannot (see _connected_account_email).
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

        emails = list(
            (
                await session.exec(
                    select(Email)
                    .where(
                        Email.user_id == user_id,
                        Email.application_id == application_id,
                    )
                    # Newest-first AND capped, matching the detail read. Order
                    # does not change the clustering — `cluster_stored_mail`
                    # sorts by each cluster's earliest message — but WHICH rows
                    # a cap keeps depends on it, so the two paths must truncate
                    # the same set or the split would not be the one proposed.
                    .order_by(Email.received_at.desc())
                    .limit(_APPLICATION_MAIL_CAP)
                )
            ).all()
        )
        if _application_mail_truncated(
            emails, user_id, application_id, "POST /applications/{id}/split"
        ):
            # REFUSE, rather than split on a subset. This handler COMMITS: it
            # re-points every message it read at a new row, so a truncated read
            # does not show fewer messages, it files real mail under the wrong
            # application and there is no undo for that. 422 rather than the 409
            # below because "nothing to split" is a benign, expected answer the
            # UI renders quietly, and this is not that.
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "This application has more stored mail than the split can "
                    "read safely, so no split was performed."
                ),
            )
        clusters = cluster_stored_mail(emails)
        if len(clusters) < 2:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This application's mail describes a single application.",
            )

        retained, siblings = clusters[0], clusters[1:]

        app.req_id = retained.req_id
        app.role_token = retained.role_token
        # A title the user typed outlives the split, for the same reason it
        # outlives a sync: the mail is being re-read, and the mail is the source
        # that never had a role in it. The identity above is still re-derived —
        # that IS what the split is for, and it is the mail's to own.
        if retained.role and app.position_source != ROLE_FROM_USER:
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
    """Apply a user's status correction — and make it sticky.

    The new status is honoured verbatim (a human decision, not the advance-only
    guard) and future syncs will never overwrite it. It changes nothing about
    the linked mail: a stage is not a label for any individual message, and
    treating it as one poisoned the training corpus — see
    :func:`record_status_correction`. 404 when the row is not the caller's.
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


@router.put("/{application_id}/role", response_model=CloudApplicationResponse)
async def set_application_role_cloud(
    application_id: int,
    data: ApplicationRoleUpdate,
    user_id: uuid.UUID = Depends(current_user),
) -> CloudApplicationResponse:
    """Fill in the job title the mail never said — issue #72.

    The Gmail path is metadata-only and the ATS subjects it reads name the
    employer, so an auto-filed row's ``position`` is "" and stays "" no matter
    how good the extraction gets. This is the only way one ever gets a title,
    and the title is then the user's: later syncs will not overwrite it. Sending
    ``null``, or only whitespace, clears both the title and that claim.

    Nothing is inferred here and nothing may be. An empty role stays empty until
    a human names it — no placeholder, no guess from the company, no default.

    404 when the row is not the caller's.
    """

    async with get_session() as session:
        app = await record_role_correction(session, user_id, application_id, data.role)
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
    """'Not an application / dismiss' — take the row off the board.

    Reversible: the row leaves the board and the summary but is not deleted, so
    ``POST /applications/{id}/restore`` brings it back intact — mail, stored
    classifications and all, which is why the dismissal labels no message
    (see :func:`dismiss_application`).
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
