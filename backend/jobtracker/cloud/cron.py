"""Scheduled background sync for the cloud deployment (issue #23, C7).

WHAT THIS IS FOR — AND WHAT IT IS NOT FOR
-----------------------------------------
The issue this implements says "without automated sync, users' inboxes never
refresh". That was true when it was written and is no longer: the web shell
runs a staleness auto-sync on arrival (``apps/web/components/dashboard/
SyncBar.tsx``), so opening the board already refreshes it. Repeating the old
framing would be claiming a fix for a bug that is fixed.

What still does not happen is anything **while the user is away**. The change
ledger ("what happened since your last visit") can only report changes the
open tab itself just fetched, and a notification has nothing to fire on. A
scheduled sync is what turns "something happened while you were gone" into a
real event with a real timestamp. That is the value here.

HOW VERCEL ACTUALLY INVOKES THIS — the issue's spec was written against an
assumption the platform does not hold
------------------------------------------------------------------------
Issue #23 specifies ``POST /cron/sync`` gated on a header
``x-vercel-cron-secret``. Vercel does neither of those things:

- "To trigger a cron job, Vercel makes an HTTP **GET** request to your
  project's production deployment URL, using the ``path`` provided in your
  project's ``vercel.json``." — https://vercel.com/docs/cron-jobs
- "The value of the variable will be automatically sent as an
  ``Authorization`` header when Vercel invokes your cron job." …
  "The ``authorization`` header will have the ``Bearer`` prefix for the
  value." — https://vercel.com/docs/cron-jobs/manage-cron-jobs

A POST-only route would therefore 405 on every scheduled invocation forever,
and a gate that only reads ``x-vercel-cron-secret`` would 403 on every one.
Both are failures that *look* like a working configuration from the outside —
the cron appears in the dashboard, it fires, and nothing syncs. So this route
answers **GET and POST**, and accepts the secret from **either** carrier:
Vercel's ``Authorization: Bearer <secret>`` or the issue's
``x-vercel-cron-secret``, the latter kept because it is what the manual probe
in the issue's validation plan sends and what an external scheduler would be
told to send.

THE SECRET
----------
Read from ``settings.vercel_cron_secret`` (env
``JOBTRACKER_VERCEL_CRON_SECRET``), falling back to the bare ``CRON_SECRET``
env var — which is the variable **Vercel itself** reads to build the
``Authorization`` header, so allowing it removes a real footgun: setting only
``CRON_SECRET`` (the name every Vercel doc and dashboard hint uses) would
otherwise leave the app with no configured secret and 403 the platform's own
requests. Never a literal, never logged, never returned.

Missing configuration **fails closed** (403), deliberately. The alternative —
"no secret set, so let everyone in" — turns an unconfigured deployment into an
open endpoint that iterates every user's mailbox on demand.

WHAT BOUNDS THE WORK
--------------------
Three bounds, and it is worth being precise about which one actually binds:

- ``settings.sync_batch_size`` caps how many users one invocation may touch.
  It is the ceiling, not the operative bound.
- ``_CRON_PER_USER_TIMEOUT_SECONDS`` isolates one slow mailbox from the batch.
- ``_CRON_RUN_BUDGET_SECONDS`` is what usually stops the run. ``vercel.json``
  gives ``api/index.py`` ``maxDuration: 60``; at 10 s per user the deadline is
  reached after ~4 users long before a batch cap of 100 is. Presenting the cap
  as "the bound" would be presenting a limit that never binds.

Candidates are ordered least-recently-synced first (never-synced first), so a
run that stops on its deadline does not starve the users it did not reach —
they sort to the front of the next one.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import case
from sqlalchemy import func as sa_func
from sqlmodel import select

from jobtracker.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Cron (cloud)"])


# The header the issue specifies, kept alongside Vercel's own Authorization
# carrier. Lower-case because Starlette's Headers mapping is case-insensitive
# but the constant is compared against nothing else.
CRON_SECRET_HEADER = "x-vercel-cron-secret"

# One user's sync may not hold the batch hostage. Ten seconds is issue #23's
# figure and it is kept, but the trade-off is real and is not hidden: a FIRST
# sync scans up to ``_SYNC_DEFAULT_SCAN_TARGET`` (750) messages against a 30 s
# scan budget, so it can exceed this and be cancelled — that run persists no
# cursor and its error lands in ``errors[]`` where it is visible. An
# incremental delta on an established cursor is a couple of Gmail calls and
# finishes well inside it. The path that completes a first sync is the user's
# own "Sync now" button, which gets the whole 60 s function budget.
_CRON_PER_USER_TIMEOUT_SECONDS = 10.0

# Checked BEFORE a user's sync is started, against a monotonic deadline taken
# at entry, so no user's sync can begin inside the budget and run past the
# function's 60 s ceiling. Sized to leave room for the enumeration query and
# the response.
_CRON_RUN_BUDGET_SECONDS = 45.0

# Why a run stopped. Same discipline as ``stopped_by`` on the sync response: a
# count of users synced is not coverage unless the caller is told whether the
# run ran out of users or ran out of budget.
STOPPED_COMPLETE = "complete"  # every candidate in this batch was attempted
STOPPED_DEADLINE = "deadline"  # the run's time budget ran out
STOPPED_BATCH = "batch"  # the batch cap was reached; more users are waiting


class CronSyncResponse(BaseModel):
    """What one scheduled run did.

    ``users_synced`` and ``errors`` are the shape issue #23 specifies. The rest
    exists because the two numbers alone cannot tell an operator apart the two
    ways this returns ``{"users_synced": 0, "errors": []}``: nobody has
    connected a mailbox, or the enumeration query found nothing it was allowed
    to see (see :func:`list_syncable_user_ids`).
    """

    users_synced: int = Field(description="Users whose sync completed without raising.")
    errors: list[str] = Field(
        default_factory=list,
        description=(
            "One entry per user whose sync failed or timed out, as "
            "'<user_id>: <ExceptionType>'. Exception *messages* are "
            "deliberately excluded — a Gmail/HTTP error can carry a token in "
            "its repr and this payload is returned over the wire."
        ),
    )
    candidates: int = Field(
        default=0,
        description=(
            "Users this run enumerated as having a connected mailbox, before "
            "any sync was attempted. Zero here means the enumeration found "
            "nobody — a different fault from every sync failing."
        ),
    )
    stopped_by: str = Field(
        default=STOPPED_COMPLETE,
        description="complete | deadline | batch — why the run stopped.",
    )


def _configured_secret() -> str | None:
    """The shared secret this deployment expects, or ``None`` if unconfigured.

    ``settings.vercel_cron_secret`` first (``JOBTRACKER_VERCEL_CRON_SECRET``,
    the field issue #23 names), then the bare ``CRON_SECRET`` Vercel reads when
    it builds the ``Authorization`` header. Read at call time, not import: a
    serverless instance is long-lived and the settings singleton is rebound by
    the test fixtures.
    """

    configured = settings.vercel_cron_secret
    if configured:
        return configured
    return os.environ.get("CRON_SECRET") or None


def _presented_secrets(request: Request) -> list[str]:
    """Every secret the caller offered, from either accepted carrier.

    A list rather than a single value so that presenting one correct header and
    one wrong one is an accept, not a reject — the manual probe in the issue's
    validation plan sends ``x-vercel-cron-secret`` while a browser or proxy may
    attach an unrelated ``Authorization``.
    """

    offered: list[str] = []

    header = request.headers.get(CRON_SECRET_HEADER)
    if header:
        offered.append(header.strip())

    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            offered.append(value.strip())

    return offered


def _authorize(request: Request) -> None:
    """403 unless the caller presented the configured secret.

    Compared with :func:`hmac.compare_digest`, not ``==``. This is a security
    boundary and the naive comparison leaks the shared secret a byte at a time
    to anyone who can time the endpoint; a scheduled endpoint is exactly the
    kind of surface nobody watches while it is being probed.

    ``compare_digest`` is still called against a placeholder when nothing was
    presented, so the unauthenticated path costs the same as the wrong-secret
    path and the *presence* of a header is not itself distinguishable by
    timing.
    """

    expected = _configured_secret()
    if not expected:
        # FAIL CLOSED. An unconfigured deployment refuses the cron rather than
        # serving it to anybody. That is a cron which visibly never works,
        # which is recoverable; the other way round is an open endpoint that
        # walks every user's mailbox.
        logger.error(
            "POST /cron/sync refused: no cron secret configured. Set "
            "JOBTRACKER_VERCEL_CRON_SECRET (or CRON_SECRET) in the Vercel "
            "project environment and redeploy, or the schedule will 403 "
            "forever while looking configured in the dashboard."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cron sync is not configured on this deployment.",
        )

    expected_bytes = expected.encode("utf-8")
    offered = _presented_secrets(request) or [""]
    if not any(
        hmac.compare_digest(candidate.encode("utf-8"), expected_bytes)
        for candidate in offered
    ):
        logger.warning(
            "Rejected an unauthenticated /cron/sync call (%s carrier(s) offered).",
            len(offered),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing cron secret.",
        )


async def list_syncable_user_ids(limit: int) -> list[uuid.UUID]:
    """Users with a connected Gmail mailbox, least-recently-synced first.

    Ordering is what makes a bounded batch fair: a run that stops on its
    deadline leaves the users it skipped at the front of the next run's queue,
    so nobody is starved by the batch cap. Never-synced users sort first — they
    are the ones with an empty board.

    ``last_sync_at`` is read as a correlated scalar sub-select taking the
    ``min`` over the user's Gmail ``sync_state`` rows rather than a join, so a
    user with more than one linked address yields exactly one row.

    .. warning::

       **This query returns nothing in production.** ``user_credentials`` has
       Row-Level Security ENABLEd and FORCEd (alembic ``c4user_creds_rls`` /
       ``c5_force_user_credentials_rls``) with
       ``USING (user_id = auth.uid())``, and the runtime role is NOBYPASSRLS.
       A cron has no authenticated user, so
       ``database.connection._apply_transaction_gucs`` leaves
       ``request.jwt.claims`` unset, ``auth.uid()`` is NULL, and the policy
       matches no row. On SQLite — which has no RLS — the same query returns
       every user, so the unit tests below are green while production syncs
       nobody.

       That is not hypothetical and it is not fixed here: fixing it is a
       change to a security boundary (either a new GUC-gated SELECT policy, or
       a privileged non-pooler read) and belongs in its own decision. The
       Postgres-backed test
       ``tests/test_rls_postgres.py::test_cron_enumeration_sees_no_users_without_identity``
       pins the fact so it cannot be re-discovered by accident.
    """

    from jobtracker.cloud.sync_state import GMAIL_ACCOUNT_TYPE
    from jobtracker.credentials.cloud import KIND_GMAIL
    from jobtracker.database import get_session
    from jobtracker.database.models import SyncState, UserCredential

    last_sync = (
        select(sa_func.min(SyncState.last_sync_at))
        .where(
            SyncState.user_id == UserCredential.user_id,
            SyncState.account_type == GMAIL_ACCOUNT_TYPE,
        )
        .scalar_subquery()
    )

    statement = (
        select(UserCredential.user_id)
        .where(UserCredential.kind == KIND_GMAIL)
        # Two sort keys instead of ``NULLS FIRST``: the latter needs SQLite
        # >= 3.30 and this query has to mean the same thing on both backends.
        .order_by(
            case((last_sync.is_(None), 0), else_=1).asc(),
            last_sync.asc(),
            UserCredential.user_id.asc(),
        )
        .limit(limit)
    )

    async with get_session() as session:
        rows = (await session.exec(statement)).all()

    # ``session.exec`` yields scalars for a single-column select on some
    # SQLModel/SQLAlchemy combinations and Row objects on others; normalise.
    return [row[0] if hasattr(row, "__getitem__") else row for row in rows]


async def _sync_one_user(user_id: uuid.UUID) -> None:
    """Run the ordinary cloud sync for one user, as that user.

    Two things make this the *same* code path the "Sync now" button takes,
    which is the point — a scheduled sync that drifted from the interactive one
    would be a second sync implementation to keep correct:

    1. ``gmail_sync`` is called directly. It is a plain async function; the
       ``Depends(current_user)`` default is inert on a direct call, so the
       user is supplied explicitly instead of resolved from a JWT.
    2. ``user_id_scope`` binds the RLS identity for the duration. Without it
       every read inside — the stored credential, the applications merge, the
       cursor write — runs with ``auth.uid()`` NULL and fails closed. The
       Gmail OAuth callback does the same thing for the same reason.

    ``SyncRequest()`` with every field defaulted is deliberate: no ``count``
    and no ``range``, because ``_history_cursor_for`` skips the incremental
    delta whenever either is supplied. A cron that passed a batch size as
    ``count`` would full-scan a 12-month window every 15 minutes forever and
    never use the cursor it just wrote.
    """

    from jobtracker.cloud.gmail_oauth import SyncRequest, gmail_sync
    from jobtracker.database.connection import user_id_scope

    with user_id_scope(user_id):
        await gmail_sync(SyncRequest(), user_id=user_id)


@router.api_route(
    "/cron/sync",
    methods=["GET", "POST"],
    response_model=CronSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Scheduled sync for every connected mailbox",
    # Kept OUT of the OpenAPI document, the same way the Gmail OAuth callback
    # is. Two reasons, one of them mechanical: nothing a browser runs may call
    # this, so publishing it only advertises the surface and adds a method to
    # the generated web client that would be a bug to use — and FastAPI derives
    # one ``operationId`` per *function*, so a two-method route emits the same
    # id twice and ``scripts/generate_api_schema.sh`` would feed the client
    # codegen a duplicate. Reachability is unaffected; the route is mounted.
    include_in_schema=False,
)
async def cron_sync(request: Request) -> CronSyncResponse:
    """Sync a bounded batch of users' mailboxes on a schedule.

    Authenticated by the shared cron secret only — there is no JWT here and no
    ``Depends(current_user)``. Each user's sync then runs under that user's own
    RLS identity (see :func:`_sync_one_user`), so the absence of a caller
    identity never becomes an unscoped read.

    One user's failure may not abort the batch: every per-user call is wrapped
    in its own timeout and its own ``except``, and the failure is reported in
    ``errors`` rather than raised. A 500 here would lose the users that had
    already synced from the response, and Vercel does not retry a failed cron
    invocation.

    Idempotent by construction, which is what Vercel's cron delivery
    guarantees require ("cron delivery can also occasionally invoke the same
    scheduled run more than once"): the underlying merge is the *additive*
    upsert, so a duplicate invocation re-reads the same mail and writes the
    same rows. Nothing here increments.
    """

    _authorize(request)

    deadline = time.monotonic() + _CRON_RUN_BUDGET_SECONDS
    batch_size = max(1, settings.sync_batch_size)

    candidates = await list_syncable_user_ids(batch_size)
    if not candidates:
        # Said out loud rather than returned as a bland zero. On Postgres this
        # is the expected result of the RLS gap documented on
        # ``list_syncable_user_ids`` — an operator staring at
        # ``{"users_synced": 0}`` has no way to tell that from "nobody has
        # connected Gmail yet".
        logger.warning(
            "Scheduled sync found no users with a connected mailbox. On "
            "Postgres this is also what RLS returns to a caller with no "
            "identity — see jobtracker.cloud.cron.list_syncable_user_ids."
        )
        return CronSyncResponse(users_synced=0, errors=[], candidates=0)

    synced = 0
    errors: list[str] = []
    stopped_by = STOPPED_COMPLETE

    for user_id in candidates:
        # Checked before the sync STARTS, so a user's 10 s cannot begin at
        # 44 s and finish past the function's 60 s ceiling.
        if time.monotonic() >= deadline:
            stopped_by = STOPPED_DEADLINE
            logger.warning(
                "Scheduled sync stopped on its %ss budget after %s of %s "
                "user(s); the remainder sort to the front of the next run.",
                _CRON_RUN_BUDGET_SECONDS,
                synced + len(errors),
                len(candidates),
            )
            break

        try:
            await asyncio.wait_for(
                _sync_one_user(user_id),
                timeout=_CRON_PER_USER_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            errors.append(f"{user_id}: TimeoutError")
            logger.warning(
                "Scheduled sync for user_id=%s exceeded its %ss timeout and "
                "was cancelled; no cursor was advanced, so the next run "
                "re-covers the same mail.",
                user_id,
                _CRON_PER_USER_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — one user may not sink the batch
            # Type name only. A Gmail/HTTP error's ``str()`` can carry a token
            # or a request URL, and this list is returned over the wire.
            errors.append(f"{user_id}: {type(exc).__name__}")
            logger.warning(
                "Scheduled sync for user_id=%s failed (%s).",
                user_id,
                type(exc).__name__,
            )
        else:
            synced += 1
    else:
        # Every candidate was attempted. If the batch cap is what produced the
        # candidate list in the first place, more users are waiting.
        if len(candidates) >= batch_size:
            stopped_by = STOPPED_BATCH

    logger.info(
        "Scheduled sync: candidates=%s users_synced=%s errors=%s stopped_by=%s",
        len(candidates),
        synced,
        len(errors),
        stopped_by,
    )

    return CronSyncResponse(
        users_synced=synced,
        errors=errors,
        candidates=len(candidates),
        stopped_by=stopped_by,
    )
