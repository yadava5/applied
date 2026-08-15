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

WHO GETS SYNCED — AND WHY IT IS A TABLE, NOT AN ENV VAR
-------------------------------------------------------
The obvious implementation reads ``user_credentials`` to find everyone with a
connected mailbox. That was the first implementation, and on Postgres it
returned **nobody**: the table has Row-Level Security ENABLEd and FORCEd with
``USING (user_id = auth.uid())`` against a NOBYPASSRLS role, and a cron carries
no JWT, so ``auth.uid()`` is NULL and the policy matches no row. SQLite has no
RLS, so every unit test was green while production synced zero users.

The second implementation gave the cron an *identity* rather than an exemption,
and took the identities from configuration —
``JOBTRACKER_CRON_SYNC_USER_IDS``. That worked and it did not scale: a user who
connected Gmail was not background-synced until an operator edited the Vercel
environment and redeployed. It broke at user #3, not at scale.

The set now comes from ``gmail_sync_enrollment`` (revision ``e2b6f0a4d517``,
issue #291): the *membership fact* — who holds a Gmail credential — published
to a table that holds nothing else, no ciphertext and no address, with a
``SELECT`` policy an identity-less connection can satisfy. So enumeration is
**one query with no identity bound**, the allowlist is gone, and a user who
links Gmail is a scheduled-sync candidate from that instant with no operator
action at all. ``settings.cron_sync_user_ids`` is no longer consulted anywhere.

That table is written and deleted in the same transaction as the credential
itself (``jobtracker.credentials.cloud``), so the two cannot drift. What it
cannot see is *revocation* — a grant the user withdrew at Google sets
``user_credentials.revoked_at`` and leaves the enrollment row standing — so
membership is still confirmed per user below.

Every user's sync then runs inside ``user_id_scope(uid)`` — the same mechanism
the Gmail OAuth **callback** uses to write ``user_credentials`` without a
request JWT, applied per transaction with ``set_config(..., is_local => true)``
so PgBouncer can never hand a stale identity to the next tenant. Every read and
write passes RLS exactly as a signed-in request's would.

The three alternatives to a separate table were argued and rejected in
``e2b6f0a4d517``'s docstring (a ``SECURITY DEFINER`` wrapper, a ``BYPASSRLS``
cron role, a privileged direct-host read). Please do not re-propose them.

WHAT ENUMERATION COSTS — AND WHY IT IS ONE CONNECTION
------------------------------------------------------
Ranking least-recently-synced-first needs each candidate's cursor, and
``sync_state`` is FORCE-RLS too: that read only works under that user's own
identity. Done the obvious way it is one *session* per user, and under the
cloud engine's NullPool a session is a fresh TCP+TLS+auth connection — ~216 ms
from iad1 (issue #203). At 300 enrolled users that is 65 s of enumeration
against a 45 s run budget: the schedule would spend every invocation deciding
who to sync and sync nobody.

So the probes share **one** connection and re-bind the identity per
*transaction*: bind the user, read, ``ROLLBACK``, bind the next. That is not a
loophole around the isolation rule, it is the same guarantee the whole app
already runs on — the GUCs are set ``is_local => true``, so they die with the
transaction, which is exactly why PgBouncer's transaction pooling is safe here
in the first place. The ``ROLLBACK`` is load-bearing and not tidiness: without
it the next user's statements join the *open* transaction and run under the
previous user's identity. Pinned, in both directions, by
``tests/test_rls_postgres.py::test_the_probe_loop_rebinds_identity_per_transaction``
and its negative twin.

Cost, after: one connection plus one round trip per user (~13 ms function →
pooler), instead of one connection per user.

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
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
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

# The most enrolled users a single run will PROBE while building its candidate
# list. See :func:`list_syncable_user_ids` for why the batch cap does not bound
# that loop and what this rail costs.
#
# DELIBERATELY ABOVE ``settings.sync_batch_size`` (default 100). Set below it,
# the enumeration could never return as many candidates as the batch allows, so
# ``len(candidates) >= batch_size`` would be unsatisfiable and ``STOPPED_BATCH``
# would become a state the response could never report — a reachable-looking
# branch that is structurally dead, which is the defect shape this module has
# already been through once.
#
# It is not the operative bound and is not presented as one: the run's own
# deadline is, exactly as ``_CRON_RUN_BUDGET_SECONDS`` is the operative bound on
# the sync loop. A probe is now one round trip on an already-open connection
# (~13 ms), not a fresh connection (~216 ms), so 200 of them cost ~2.6 s of the
# 45 s budget rather than all of it. This is the rail for the case the deadline
# cannot catch, and it is far above the enrolled population this deployment has.
_CRON_MAX_PROBES = 200
STOPPED_BATCH = "batch"  # the batch cap was reached; more users are waiting


class CronSyncResponse(BaseModel):
    """What one scheduled run did.

    ``users_synced`` and ``errors`` are the shape issue #23 specifies. The rest
    exists because the two numbers alone cannot tell an operator apart the two
    ways this returns ``{"users_synced": 0, "errors": []}``: nobody has
    connected a mailbox at all, or everybody enrolled has since revoked the
    grant at Google (see :func:`list_syncable_user_ids`).
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
            "Users this run enumerated as enrolled AND still holding a live "
            "Gmail credential, before any sync was attempted. Zero here means "
            "the enumeration found nobody — a different fault from every sync "
            "failing."
        ),
    )
    skipped: int = Field(
        default=0,
        description=(
            "Users whose sync was declined because one was already running for "
            "that mailbox (429). NOT an error: it is the per-user lease doing "
            "its job, and it happens routinely when a user is syncing in the "
            "browser as the schedule fires. Counted separately so it can never "
            "make an otherwise-healthy run report failure."
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


async def list_enrolled_user_ids() -> list[uuid.UUID]:
    """Every user who holds a Gmail credential — ONE query, no identity bound.

    ``gmail_sync_enrollment`` exists so this question has an answer the cron can
    ask (revision ``e2b6f0a4d517``, issue #291). It carries a ``SELECT`` policy
    with a permissive predicate for the runtime role precisely because a policy
    the cron's identity-less connection could not satisfy would rebuild the
    problem one table to the left. The row is a membership fact and nothing
    else: a user id and when it was enrolled.

    ``user_id_scope(None)`` is explicit rather than incidental. The handler has
    no identity bound, but stating it means this read cannot silently start
    running under some caller's identity if it is ever called from one — the
    ``search_path``-poisoning lesson applied to tenant identity.

    Ordered by ``user_id`` so a run that has to stop short stops at a
    reproducible place. The order is not the *sync* order — that is decided by
    :func:`list_syncable_user_ids` from each user's cursor.
    """

    from jobtracker.database import get_session
    from jobtracker.database.connection import user_id_scope
    from jobtracker.database.models import GmailSyncEnrollment

    with user_id_scope(None):
        async with get_session() as session:
            rows = (
                await session.exec(
                    select(GmailSyncEnrollment.user_id).order_by(
                        GmailSyncEnrollment.user_id
                    )
                )
            ).all()

    # ``session.exec`` yields a bare scalar for a single-column select on some
    # SQLModel/SQLAlchemy combinations and a Row on others; normalise.
    return [row[0] if hasattr(row, "__getitem__") else row for row in rows]


async def _probe_sync_position(
    conn: Any, user_id: uuid.UUID
) -> tuple[bool, datetime | None]:
    """Ask, **as ``user_id``**, whether Gmail is live and when it last synced.

    Runs on the caller's already-open connection (see
    :func:`list_syncable_user_ids`), inside ``user_id_scope(user_id)``. Scoping
    is not optional even though the statements carry an explicit
    ``WHERE user_id = ...``: ``user_credentials`` and ``sync_state`` are both
    FORCE-RLS, so an identity-less read returns nothing at all on Postgres
    regardless of the filter. The filter and the policy agree, which is the
    point — this reads exactly what a signed-in request for that user would
    read, and nothing else is reachable from inside the block.

    THE CALLER MUST END THE TRANSACTION AFTER THIS RETURNS. The identity is a
    transaction-local GUC; it is re-applied on each ``begin`` from the
    ContextVar this function sets. Leave the transaction open and the next
    user's reads run under *this* user's identity. That is why the loop in
    :func:`list_syncable_user_ids` rolls back every iteration, and why the
    Postgres suite asserts both that it re-binds and that omitting the rollback
    does not.

    There is deliberately no ``asyncio.gather`` over this: a ContextVar set
    outside a task set is inherited by every task in it, and one connection
    cannot hold two identities at once anyway.

    Returns ``(has_gmail, last_sync_at)``. ``last_sync_at`` is the ``min`` over
    the user's Gmail ``sync_state`` rows, so a user with more than one linked
    address still yields one value — the oldest, which is the one that decides
    how urgently they need a run.
    """

    from jobtracker.cloud.sync_state import GMAIL_ACCOUNT_TYPE
    from jobtracker.credentials.cloud import KIND_GMAIL
    from jobtracker.database.connection import user_id_scope
    from jobtracker.database.models import SyncState, UserCredential

    with user_id_scope(user_id):
        connected = (
            await conn.execute(
                select(UserCredential.user_id)
                .where(
                    UserCredential.user_id == user_id,
                    UserCredential.kind == KIND_GMAIL,
                    # A grant the user revoked at Google is not a connected
                    # mailbox, and enrollment cannot see that: revocation marks
                    # ``revoked_at`` and leaves the enrollment row standing.
                    # Without this the row's mere existence kept answering "yes"
                    # forever: the user was picked as a candidate every fifteen
                    # minutes, spent one of the ~4 slots this run can afford on a
                    # sync that could only fail, and crowded out someone whose
                    # mail still works.
                    UserCredential.revoked_at.is_(None),
                )
                .limit(1)
            )
        ).first()
        if connected is None:
            return False, None

        last_sync = (
            await conn.execute(
                select(sa_func.min(SyncState.last_sync_at)).where(
                    SyncState.user_id == user_id,
                    SyncState.account_type == GMAIL_ACCOUNT_TYPE,
                )
            )
        ).scalar()

    return True, last_sync


async def list_syncable_user_ids(
    limit: int, *, deadline: float | None = None
) -> list[uuid.UUID]:
    """Enrolled users with a live Gmail mailbox, least-recently-synced first.

    Two halves, and the split is the whole design:

    1. **Who may be synced comes from ``gmail_sync_enrollment``** — one query,
       no identity, no configuration (:func:`list_enrolled_user_ids`). An empty
       table returns ``[]``: a deployment nobody has connected Gmail to syncs
       nobody, which is the same fail-closed default the allowlist had without
       the operator step the allowlist needed.
    2. **Whether they are syncable is still asked of the database**, once per
       user and under that user's own identity (:func:`_probe_sync_position`).
       Enrollment is a claim about a credential *existing*, not about it still
       working: a user who revoked the grant at Google keeps their enrollment
       row. Without this check the response's ``candidates`` would stop meaning
       "users with a connected mailbox" and ``errors[]`` would carry an entry
       for the same revoked user every fifteen minutes forever.

    Ordering is what makes a bounded batch fair: a run that stops on its
    deadline leaves the users it skipped at the front of the next run's queue,
    so nobody is starved by the batch cap. Never-synced users sort first — they
    are the ones with an empty board. The sort happens in Python because the
    candidates do not come from one query, and the key mirrors the SQL it
    replaces exactly: never-synced first, then oldest sync first, then user id.

    COST. ONE connection for the whole enumeration — the probe loop re-binds the
    identity per transaction on a connection it opens once, rather than opening
    a session per user. Under NullPool a session is a fresh TCP+TLS+auth
    connection at ~216 ms (issue #203), so the previous shape spent 65 s
    enumerating 300 users against a 45 s budget and could sync nobody at all.
    Now it is one connection plus one round trip per user. ``limit`` still does
    NOT bound the loop — the cap is applied to the sorted result, because
    ordering by cursor requires knowing every candidate's cursor.

    So the loop is bounded twice: by ``_CRON_MAX_PROBES``, and by the run's own
    deadline if the caller passes one. Both are reported rather than silent —
    an enumeration that stopped early is the difference between "nobody needed
    syncing" and "we never looked".

    WHAT THE BOUND COSTS, said plainly. A probe cap necessarily ranks only the
    users it reached, and the enumeration order is stable, so past the cap the
    fairness guarantee does not hold: those users are not ranked at all and
    would need a rotation this does not implement. Inside the cap — which now
    costs ~2.6 s rather than the whole run — the property is exactly as before.
    The log line says so when it binds.
    """

    from jobtracker.database.connection import get_engine

    enrolled = await list_enrolled_user_ids()
    if not enrolled:
        # An operator staring at ``{"users_synced": 0}`` cannot tell "nobody has
        # connected a mailbox" from "every sync failed" — so say which.
        logger.warning(
            "Scheduled sync found nobody enrolled: gmail_sync_enrollment is "
            "empty, so no user has connected a Gmail mailbox on this "
            "deployment. The schedule will keep succeeding while syncing "
            "nobody until someone completes the Gmail OAuth flow."
        )
        return []

    # (never_synced_rank, last_sync_at, user_id) — the SQL ORDER BY, in Python.
    ranked: list[tuple[int, datetime, uuid.UUID]] = []
    probed = 0
    async with get_engine().connect() as conn:
        for user_id in enrolled:
            if probed >= _CRON_MAX_PROBES or (
                deadline is not None and time.monotonic() >= deadline
            ):
                logger.warning(
                    "Scheduled sync enumerated only %s of %s enrolled user(s) "
                    "(%s). The users past that point were not ranked and cannot "
                    "be picked this run.",
                    probed,
                    len(enrolled),
                    "probe cap" if probed >= _CRON_MAX_PROBES else "run deadline",
                )
                break
            probed += 1
            try:
                has_gmail, last_sync = await _probe_sync_position(conn, user_id)
            finally:
                # THE ROLLBACK IS THE ISOLATION. The identity GUC is
                # transaction-local and is re-applied on the next ``begin``;
                # ending the transaction here is what makes the next iteration
                # bind the next user instead of inheriting this one. In a
                # ``finally`` so a failed probe cannot leave a bound transaction
                # open for whoever runs next on this connection.
                await conn.rollback()
            if not has_gmail:
                continue
            ranked.append(
                (
                    0 if last_sync is None else 1,
                    last_sync if last_sync is not None else datetime.min,
                    user_id,
                )
            )

    if not ranked:
        # The other way to reach zero, and it has a different remedy: people ARE
        # enrolled, but every one of them revoked the grant at Google.
        logger.warning(
            "Scheduled sync: none of the %s enrolled user(s) still holds a live "
            "Gmail credential — every one has been revoked at Google and needs "
            "reconnecting.",
            len(enrolled),
        )

    ranked.sort()
    return [user_id for _, _, user_id in ranked[:limit]]


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

    The ``with`` stays INSIDE this function — one binding per user, per unit of
    work. It must never be hoisted around the caller's loop and this must never
    become an ``asyncio.gather`` with the binding outside the tasks: a
    ContextVar set outside a task set is inherited by every task in it, and one
    tenant's identity bound while another tenant's sync runs is a cross-tenant
    write. That is the ``search_path`` poisoning incident's shape carrying
    tenant identity instead of a schema name. Pinned by
    ``tests/test_rls_postgres.py::test_cron_syncs_only_the_enrolled_user_and_leaks_no_identity``.

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

    INVARIANT — THIS HANDLER TAKES NO USER-SELECTING INPUT, EVER.
    The only parameter is the raw ``Request``, and nothing below reads a query
    parameter, a path parameter, a body field or a header to decide *whose*
    mailbox to touch: the set of users comes from ``gmail_sync_enrollment`` and
    from nowhere else. That is not a
    stylistic preference. This route authenticates a *caller* (a shared cron
    secret) and then acts with *other people's* authority — the textbook
    confused-deputy setup — so anyone holding the secret would be able to name
    a victim the moment a ``user_id`` parameter appears here. Adding one turns
    a scheduled job into an arbitrary-tenant sync trigger. Pinned by
    ``tests/test_cron_sync.py::test_the_handler_ignores_any_user_selecting_input``.

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

    # Function-level, like ``_sync_one_user``'s import of the same module: it
    # pulls in the Google client libraries, which must not be paid at
    # collection time.
    from jobtracker.cloud.gmail_oauth import SyncAlreadyRunning

    deadline = time.monotonic() + _CRON_RUN_BUDGET_SECONDS
    batch_size = max(1, settings.sync_batch_size)

    candidates = await list_syncable_user_ids(batch_size, deadline=deadline)
    if not candidates:
        # Said out loud rather than returned as a bland zero, and the two
        # reasons are separated because they have different remedies, and the
        # separation is logged by :func:`list_syncable_user_ids`, which is where
        # the enrolled count is already in hand — asking again here would be a
        # second ~216 ms connection to re-learn something just read.
        return CronSyncResponse(users_synced=0, errors=[], candidates=0)

    synced = 0
    skipped = 0
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
        except SyncAlreadyRunning:
            # THE LEASE, NOT A FAULT. A user syncing in the browser as the
            # schedule fires makes ``gmail_sync`` answer 429, and counting that
            # as an error would turn the honest status code below into a false
            # red on the exact signal it exists to make trustworthy — the sync
            # it collided with is a sync that HAPPENED.
            #
            # Matched on the TYPE, not the status code, so that "Gmail is not
            # connected" (409 — a genuine fault, the candidate list is stale)
            # cannot be swallowed by the same branch.
            skipped += 1
            logger.info(
                "Scheduled sync skipped user_id=%s: a sync is already running "
                "for that mailbox.",
                user_id,
            )
        except HTTPException as exc:
            errors.append(f"{user_id}: HTTP{exc.status_code}")
            logger.warning(
                "Scheduled sync for user_id=%s failed (HTTP %s).",
                user_id,
                exc.status_code,
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
        "Scheduled sync: candidates=%s users_synced=%s skipped=%s errors=%s "
        "stopped_by=%s",
        len(candidates),
        synced,
        skipped,
        len(errors),
        stopped_by,
    )

    # A RUN THAT SYNCED NOBODY AND FAILED EVERYBODY IS NOT A SUCCESS.
    #
    # This returned 200 no matter what happened. Vercel's cron dashboard reads
    # the status code and nothing else, so the schedule showed green while
    # every user's sync raised — the estate's "checks that cannot fail" shape,
    # on the one surface nobody watches by hand.
    #
    # The condition is deliberately the narrowest one that cannot false-alarm:
    # errors present AND not a single user synced. A partial failure still
    # returns 200 because a run that synced four of five users did work, and a
    # dashboard that goes red on every transient single-user blip is a
    # dashboard that gets muted. ``skipped`` is excluded from the numerator by
    # construction — a lease conflict means a sync was already running, so a
    # run that skipped everyone collided with real work rather than failing.
    #
    # 503 rather than 500: this is "the dependency did not answer", it is
    # retryable, and Vercel does not retry a failed cron invocation either way.
    # The body is still the full CronSyncResponse — a status code alone would
    # lose which users failed and why, which is the other half of being honest.
    body = CronSyncResponse(
        users_synced=synced,
        errors=errors,
        candidates=len(candidates),
        skipped=skipped,
        stopped_by=stopped_by,
    )
    if errors and synced == 0:
        logger.error(
            "Scheduled sync synced NOBODY: %s candidate(s), %s error(s), "
            "%s skipped. Answering 503 so the schedule does not show green.",
            len(candidates),
            len(errors),
            skipped,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(),
        )
    return body
