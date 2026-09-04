"""Cloud Gmail *web* OAuth + read/classify router (issue C5).

This is the piece that makes "Connect Gmail → read inbox → classify →
show verdicts" real on the deployed web app. It implements the standard
OAuth 2.0 **authorization-code** flow for a Google *Web application*
client — the server-side sibling of the desktop app's
``run_local_server`` flow, which cannot run on Vercel.

Endpoints
---------
- ``GET  /auth/gmail/status``    (auth) — is Gmail configured / connected?
- ``GET  /auth/gmail/authorize`` (auth) — mint the Google consent URL.
- ``GET  /auth/gmail/callback``  (no auth) — Google redirects here; we
  exchange the code for tokens, encrypt+store them, and bounce the user
  back to the web app.
- ``POST /auth/gmail/disconnect`` (auth) — revoke at Google + delete the
  stored token.
- ``GET  /gmail/inbox``          (auth) — read a bounded batch of recent
  mail and return one classifier verdict per message.

Security properties
-------------------
- **Least privilege**: only ``gmail.readonly`` is ever requested.
- **No secret exposure**: the Google client secret lives solely in the
  backend env; it is never sent to the browser and never logged. Access/
  refresh tokens are exchanged server-to-server in ``callback`` and are
  never placed in a URL or response body.
- **Encrypted at rest**: refresh tokens are stored Fernet-encrypted via
  ``jobtracker.credentials.cloud`` (C4). This module does not weaken that.
- **CSRF-safe, stateless binding**: the ``state`` parameter is a short-
  lived HS256-signed token carrying the authenticated user's id, so the
  unauthenticated callback can be bound to the right user without any
  server-side session store. A forged/expired/reused-past-expiry state is
  rejected.
- **Stateless PKCE**: ``authorize`` and ``callback`` run in *different*
  serverless invocations, so the PKCE ``code_verifier`` minted for the
  consent URL cannot live in process memory (letting the library
  autogenerate one per ``Flow`` breaks the exchange with
  ``invalid_grant`` — the callback's fresh ``Flow`` never knows the
  verifier the challenge was derived from). We generate the verifier
  ourselves, derive the S256 challenge for the consent URL from it, and
  carry the verifier across the round-trip **Fernet-encrypted inside the
  signed state** — tamper-proof via the HS256 signature, unreadable to
  the browser/Google/URL logs via the encryption, and expiring with the
  state's TTL.
- **No open redirect, with the destination taken from the caller**: the
  post-callback destination is the origin the caller started from, and it is
  checked against ``config.trusted_web_hosts`` — the same list CORS is built
  from — **when ``authorize`` mints the state**, before Google is ever
  reached. What crosses the round trip is therefore an origin this backend
  already approved, riding inside a token it signed. Validating at mint and
  not at consume is the load-bearing half: an unchecked origin round-tripping
  through ``state`` would be an open redirect carrying our own signature.
- **And it must not be US**: ``trusted_web_hosts`` contains this API's own
  hostnames, because CORS needs them there. A return origin naming the API
  passes "is it ours?" and strands the browser on a backend that serves no
  ``/settings``, so it is subtracted separately
  (``config.return_origin_is_this_api``).
- **The fallback is still allow-listed**: a request that carries no origin —
  a state minted before this shipped, or one too forged to read — falls back
  to the operator-configured ``web_app_url``, held to the same trusted-host
  rule, because "not attacker-controlled" turned out not to imply "correct".
  A stale alias of our own project satisfied the open-redirect property
  perfectly and still landed every user signed out, since cookies are scoped
  to a hostname. See ``_validated_return_origin``, ``_web_app_base`` and
  ``tests/test_gmail_oauth_return_host.py``.
- **Revocable**: disconnect calls Google's revocation endpoint and then
  deletes the local ciphertext.
- **Capped, at mint, on a resource that cannot be refilled**: the Google
  project this app publishes under admits a fixed number of users for the
  restricted ``gmail.readonly`` scope *over its whole lifetime*, and a slot is
  spent when a person reaches the consent screen — not when they finish. So
  ``authorize`` refuses once ``settings.gmail_connection_cap`` distinct users
  hold a connection, before a consent URL exists. Same ordering as the origin
  check above and for a harder reason: a bad origin can be retried, a spent
  Google slot cannot be recovered. See ``_enforce_connection_cap``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from jobtracker.auth import current_user
from jobtracker.config import (
    canonical_return_origin,
    configured_web_app_host,
    return_origin_is_this_api,
    return_origin_is_trusted,
    settings,
    web_app_host_is_trusted,
)
from jobtracker.credentials.cloud import (
    CredentialEncryptionError,
    _require_fernet,
    delete_gmail_credentials,
    get_gmail_credentials,
    save_gmail_credentials,
)
from jobtracker.credentials.types import GmailCredentials
from jobtracker.database.connection import user_id_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gmail (cloud)"])

_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_REVOKE_URI = "https://oauth2.googleapis.com/revoke"
_STATE_AUDIENCE = "jobtracker:gmail-oauth-state"


# =============================================================================
# Response models
# =============================================================================


class GmailStatusResponse(BaseModel):
    """Whether the deployment can offer Gmail, and whether this user linked it.

    Also carries the caller's sync cursor state. The web app had nothing to
    render for "last synced …" — which is precisely why the product felt like it
    never synced and invited another manual re-sync on every visit. These fields
    are additive; ``configured=False`` short-circuits before any DB read, so an
    unconfigured deployment still answers without touching Postgres.

    - ``last_sync_at`` — ISO-8601 of the last *successful* sync, never an
      attempt. ``null`` until one succeeds.
    - ``has_cursor`` — a Gmail ``historyId`` is stored, so the next sync can be
      incremental. ``false`` means the next sync is a full scan (first sync,
      post-disconnect, or an items-relay-only user).
    - ``sync_status`` / ``sync_error`` — the last recorded state
      (``idle``/``syncing``/``error``) and, on error, the failure's type name.
    """

    configured: bool
    connected: bool
    email: str | None = None
    last_sync_at: str | None = None
    has_cursor: bool = False
    sync_status: str | None = None
    sync_error: str | None = None
    # WHAT THE LAST SUCCESSFUL SYNC LOOKED AT (#422). The same partition
    # ``POST /gmail/sync`` returns, read back out of ``sync_state`` — because a
    # sync response is gone when the tab closes and the question it answers
    # ("did you see my mail?") is asked days later. One ``pipeline.ScanLedger``
    # writes FIVE of these and the sync response's five, so this endpoint and
    # that one cannot disagree about them.
    #
    # ``last_scanned`` is the sixth and it is NOT on the ledger — the pipeline
    # cannot know how many messages the scan read, only how many became items.
    # It still has one source: the handler's ``scanned`` local fills the sync
    # response's ``scanned`` and the row this reads back, in the same call. One
    # value, two surfaces; just not the same object as the other five.
    #
    # ``null`` and ``0`` are different answers and are kept different: null
    # means no sync has recorded a ledger yet (every row predating revision
    # ``a3f7d21c60be``, and any account whose only syncs failed), while 0 means
    # a sync ran and read nothing. Collapsing them would turn "we have never
    # looked" into "we looked and your mailbox was empty", which is the exact
    # confusion this issue is about.
    last_scanned: int | None = None
    last_classified: int | None = None
    last_filed: int | None = None
    last_queued: int | None = None
    last_dropped: int | None = None
    last_reached_nothing: int | None = None


class GmailAuthorizeResponse(BaseModel):
    """The Google consent URL the browser should be sent to."""

    authorization_url: str


class GmailDisconnectResponse(BaseModel):
    revoked: bool
    message: str


class InboxVerdict(BaseModel):
    """One classifier verdict for one recent message, and enough of the message
    to judge that verdict by.

    ``snippet`` is Gmail's own preview — the SAME text this verdict was reached
    from (see the classify call below) — unescaped and truncated to 500 chars,
    exactly as the filed ledger stores and serves it. Full bodies are still
    never fetched in the cloud path and never returned; that is the privacy
    line, and it has not moved. What changed is only that the preview the
    classifier already read now reaches the reader too.

    It has to, because without it a scan row was unjudgeable: subject, sender
    and a category, with a correction control and no way to see what the
    message actually said or to open it. The filed ledger has carried both
    fields since it existed, so the live scan was the one mail surface in the
    product showing a verdict the reader could not check.
    """

    message_id: str
    subject: str
    sender_email: str
    sender_name: str | None = None
    category: str
    confidence: float
    method: str
    needs_review: bool
    # ISO-8601 receipt time (from the Date header) and the normalized company
    # token this message groups under — both drive the pipeline view (age,
    # follow-up detection, per-company rollup).
    received_at: str | None = None
    company: str = ""
    # The preview, and a deep link to the message in Gmail. Both are nullable
    # and mean "not available for this row", never "empty": a message Gmail
    # returned no snippet for, or a mine running while the account link is
    # unreadable. A client must render neither rather than show a blank line or
    # a dead control.
    snippet: str | None = None
    gmail_link: str | None = None


class InboxResponse(BaseModel):
    connected: bool
    scanned: int
    verdicts: list[InboxVerdict]
    note: str
    # Server-side pagination: the opaque cursor for the next page, or null when
    # the query is exhausted. The web client loops until it reaches the user's
    # chosen count or this is null.
    next_page_token: str | None = None
    # Per-page category counts, for the live count-up while paging. The
    # canonical whole-set summary + follow-ups come from POST /gmail/pipeline.
    category_summary: dict[str, int]
    # Echo of the resolved filters so the client can label what it fetched.
    query: str
    scope: str
    range_months: int | None = None
    # How many messages this page LISTED but could not read back (a dropped
    # Gmail metadata sub-request, or metadata that would not parse). ``scanned``
    # counts only what was read, so without this a page that lost 60 of 2,000
    # messages reports 1,940 as though that were the whole mailbox.
    unreadable: int = 0
    # Gmail's own ``resultSizeEstimate`` for the query — an ESTIMATE, not a
    # count. Gmail documents it as approximate and it drifts between pages of
    # the same query, so a client using it as a progress denominator must clamp
    # it (never below what it has already fetched) and label it as approximate.
    result_size_estimate: int | None = None


class PipelineItemIn(BaseModel):
    """One classified message the client asks the pipeline analytics about.

    ``confidence`` (the classifier's confidence for ``category``) is what the
    sync now gates on: without it, a low-confidence guess used to manufacture a
    fake ``interviewing``/``offered`` row. ``thread_id``/``snippet`` let a
    persisted row deep-link + show the underlying mail in the detail view.

    EVERY STRING IS BOUNDED. Not for storage — the persist layer truncates to
    its own column widths anyway (``body_snippet`` to 500) — but because
    truncation happens far too late to matter. Pydantic parses the WHOLE body
    into Python objects before a single field is read, so an unbounded string
    is memory the process allocates on an attacker's say-so, inside a function
    with a fixed memory ceiling. The limits are generous multiples of what
    Gmail actually emits (a snippet is ~200 characters, an RFC-5321 address is
    at most 320) so nothing a real client sends is refused.

    IT DELIBERATELY DOES NOT ACCEPT ``identity_role`` / ``identity_req_id``, and
    must not learn to. Those are derived by the SERVER from the message body in
    :func:`_classify_messages`, and they decide which application a message is
    filed against and how the review queue groups decisions. Accepting them here
    would let a client reshape dedup keys and file its own mail onto whichever
    application it named. A relay item therefore leaves them unset, which means
    "not derived" and sends the reader back to the snippet — the behaviour this
    path has always had.
    """

    message_id: str = Field(max_length=256)
    category: str = Field(max_length=64)
    sender_email: str = Field(default="", max_length=512)
    subject: str = Field(default="", max_length=2000)
    sender_name: str | None = Field(default=None, max_length=512)
    received_at: str | None = Field(default=None, max_length=64)  # ISO-8601
    confidence: float = 0.0
    thread_id: str | None = Field(default=None, max_length=256)
    snippet: str = Field(default="", max_length=2000)


class PipelineAnalyzeRequest(BaseModel):
    """What the client asks the pipeline analytics about.

    BOUNDED, for the same reason every string on ``PipelineItemIn`` is, and with
    the same number as its sibling :class:`SyncRequest`. Processing already
    discards everything past ``gmail_fetch_hard_cap`` (2000) — but that slice
    happens after Pydantic has already materialised the entire list, so it caps
    the WORK and not the ALLOCATION.

    Set above the hard cap rather than at it, so this rejects abuse without ever
    turning a client that merely relayed a few too many items into a 422; that
    client's surplus is still silently dropped exactly as before.

    IT WAS THE ONE THAT WAS MISSED. ``SyncRequest.items`` carried this bound and
    this reasoning; the twin next to it carried neither, and measured (issue
    #406) that showed up as ``SYNC n=2501 -> 422`` beside
    ``PIPELINE n=100000 -> 200``, roughly 19x heap amplification inside Vercel's
    ~4.5 MB body cap, for a handler that consumes 2,000 of what it allocated.
    """

    items: list[PipelineItemIn] = Field(max_length=2500)
    stale_days: int | None = None


class FollowUpOut(BaseModel):
    message_id: str
    company: str
    subject: str
    days_since: int
    applied_at: str | None = None


class PipelineAnalyzeResponse(BaseModel):
    total: int
    job_related: int
    category_summary: dict[str, int]
    follow_ups: list[FollowUpOut]


class SyncAlreadyRunning(HTTPException):
    """429: this mailbox already has a sync in flight.

    429 RATHER THAN 409, WHICH IS WHAT "CONFLICT" WOULD OTHERWISE ARGUE FOR.
    409 is already spoken for on this endpoint: it means "Gmail is not
    connected", and the web app reads it that way in four places —
    ``SyncBar.tsx`` sets ``notConnected: res.status === 409`` and
    ``lib/gmail/server.ts`` maps 409 to ``{kind: "not_connected"}``. Reusing it
    would tell a user whose mailbox is working perfectly, and is being synced
    right now, to go and reconnect their account. Overlapping syncs are routine
    — ``SyncBar`` runs a staleness auto-sync on arrival, so landing on the
    dashboard and pressing "Sync now", or simply having two tabs open, collides
    — which makes the wrong message the COMMON case rather than an edge one.

    429 is also the honest reading. This lease is the rate limit: the section
    of work it comes from is "nothing stops a user hammering sync", and "you
    are already doing this, try again shortly" is exactly what 429 means. It
    carries ``Retry-After`` so a client can wait the right amount of time
    instead of guessing, and nothing in the web app currently reads 429 on any
    path, so the new code cannot be mistaken for an existing meaning.

    ITS OWN TYPE, not a bare ``HTTPException(429, ...)``, so the scheduled run
    can tell a lease conflict (``skipped`` — a sync is happening) from a real
    fault (``errors`` — a stale candidate list) by catching the class rather
    than comparing a number.
    """

    def __init__(self, retry_after_seconds: int = 15) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "A sync is already running for this mailbox. Wait for it to "
                "finish before starting another."
            ),
            headers={"Retry-After": str(retry_after_seconds)},
        )


class GmailRateLimited(HTTPException):
    """429: Gmail deferred this read. The same cursor will work shortly.

    NOT 500, which is what this used to be. On 2026-09-04 a live scan on the
    owner's own mailbox took ``HttpError 403 ... 'rateLimitExceeded'`` from
    ``messages.list`` and the user was told "We couldn't finish reading your
    mail" — a sentence that describes a broken server, for a mailbox that was
    working perfectly and a condition that clears on its own within a minute.

    NOT 503 EITHER, and that distinction is load-bearing:
    ``apps/web/lib/gmail/server.ts`` maps 503 onto "Gmail is not configured on
    this deployment", which is an operator problem the reader can do nothing
    about. 429 is the honest status and the only one that carries the
    information the client needs — ``Retry-After`` — so the mine can wait and
    resume from its existing ``page_token`` instead of restarting.

    Why the default is a full minute: the limit that fires here is Gmail's
    **units per minute per user** (6,000 for this project). A per-minute bucket
    refills on a minute boundary, so a shorter wait just spends another request
    to be refused again — and that second refusal costs the very budget the
    wait is supposed to be accumulating.
    """

    def __init__(self, retry_after_seconds: int = 60) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Gmail is rate-limiting this mailbox. The scan can continue "
                "from where it stopped in a moment."
            ),
            headers={"Retry-After": str(retry_after_seconds)},
        )


class SyncRequest(BaseModel):
    """Sync the classified pipeline into the user's Application rows.

    Input source — two ways to supply the scan: pass ``items`` to persist an
    already-mined set (the inbox workbench relays what it fetched), or omit them
    to have the server fetch a bounded, recent window itself and classify it
    (the dashboard's connect-time backfill). ``count``/``range``/``scope`` tune
    the server-fetch source.

    Persistence ``mode`` — how the scan is merged:

    - ``"additive"`` (DEFAULT): upsert-only. Insert newly-found applications and
      advance/refresh existing ones; NEVER delete a previously-found row just
      because this scan's window missed it. The durable path every routine/auto
      sync must use so the pipeline accumulates rather than vanishing run-to-run.
    - ``"rebuild"``: the destructive purge+rebuild — wipe the Gmail-derived board
      and rebuild it from this scan. Reserved for the EXPLICIT user "Re-sync"
      button (a deliberate "start clean"); manual/user-corrected rows are still
      preserved. **Server-fetch only**: ``mode="rebuild"`` together with
      ``items`` is REJECTED with 400, because a purge may only be computed from
      a scan the server made itself with ``scope="anywhere"``. Relayed items are
      additive-only.
    """

    # BOUNDED, for the same reason every string on ``PipelineItemIn`` is.
    # Processing already discards everything past ``gmail_fetch_hard_cap``
    # (2000) — but that slice happens after Pydantic has already materialised
    # the entire list, so it caps the WORK and not the ALLOCATION.
    #
    # Set above the hard cap rather than at it, so this rejects abuse without
    # ever turning a client that merely relayed a few too many items into a
    # 422; that client's surplus is still silently dropped exactly as before.
    items: list[PipelineItemIn] | None = Field(default=None, max_length=2500)
    count: int | None = None
    range: str | None = None
    scope: str | None = None
    mode: str | None = None


class RemovedApplicationOut(BaseModel):
    """One row a rebuild took off the board, named so the UI can say which."""

    id: int
    company: str


# Why a scan stopped, reported verbatim on the response. A bare count of what a
# scan read cannot be distinguished from coverage unless the caller is told
# whether it ran out of mail or ran out of budget — which is the whole defect.
STOPPED_COMPLETE = "complete"  # the query was exhausted: this IS everything
STOPPED_TARGET = "target"  # hit the message target; more mail matches
STOPPED_DEADLINE = "deadline"  # ran out of the serverless time budget
STOPPED_PAGE_LIMIT = "page_limit"  # hit the list-call safety rail
STOPPED_DISCONNECTED = "disconnected"  # Gmail stopped answering mid-scan
STOPPED_RELAY = "relay"  # not our scan — the client sent the items
STOPPED_RATE_LIMITED = "rate_limited"  # Gmail deferred; the window is partial


class SyncResponse(BaseModel):
    created: int
    updated: int
    applications: int  # LIVE application rows the user has after the sync
    # How many messages the scan READ. NOT coverage: read it together with
    # ``stopped_by`` (did it finish, or run out of budget?), ``unreadable``
    # (how many it listed and lost) and ``result_size_estimate`` (roughly how
    # many the query matches). "Scanned 41" alone is the same sentence whether
    # the window held 41 messages or 4,100.
    scanned: int
    # Messages this scan LISTED but could not read back — a dropped Gmail
    # metadata sub-request, or metadata that would not parse. ``scanned`` counts
    # only what was read, so this is the gap between the two.
    unreadable: int = 0
    # One of the ``STOPPED_*`` constants above.
    stopped_by: str = STOPPED_COMPLETE
    # Gmail's own ``resultSizeEstimate`` for the query — the largest one seen
    # across the scan's pages, clamped to never sit below what was actually
    # examined. An ESTIMATE and documented as approximate for large result sets:
    # a denominator to say "41 of about 1,200", never a count. ``null`` when
    # Gmail offered none (the incremental and relay paths never do).
    result_size_estimate: int | None = None
    # AUTO rows this run took off the board and how many uncertain verdicts are
    # waiting in the needs-classification queue. Usually a rebuild's "garbage
    # gone" number, but an ADDITIVE sync can report one too: a row whose last
    # email turned out to belong to another employer leaves the board on that
    # path as well, and a board that changes without saying so is the defect
    # that cost the owner 22 applications.
    purged: int = 0
    needs_review: int = 0
    # WHICH rows were removed — id + company. A re-sync that silently changes
    # the board is unreviewable: this is what lets the button report "3 filed,
    # 2 removed (MotherDuck, Supabase)" and offer an undo, since a removal is a
    # dismissal that ``POST /applications/{id}/restore`` reverses.
    removed: list[RemovedApplicationOut] = []
    # Messages the classifier called a job-application category and the pipeline
    # then DISCARDED for scoring below ``pipeline.REVIEW_FLOOR`` — no row, no
    # queue entry. Zero on a healthy sync.
    #
    # It exists because "0 created, 0 updated" is the same sentence whether the
    # mailbox was quiet or the pipeline threw four confirmations away, and on
    # 2026-08-21 it was the second one: four Microsoft applications scored
    # ``rejection`` at 0.60 off a conditional clause in the body and left
    # without a trace. See ``pipeline.DroppedVerdict``.
    #
    # A COUNT, not the messages. What was dropped is in the logs, keyed by
    # message id; a response that listed them would be re-deriving the review
    # queue with a different name and no way to act on it.
    dropped: int = 0
    # THE REST OF THE LEDGER — where every message this run looked at ended up.
    #
    # ``dropped`` above closed half of #422: a lifecycle verdict thrown away
    # under the review floor now leaves a number. The other half stayed open,
    # and it is the bigger one. A message the classifier scored ``other`` leaves
    # through the same terminal door, writes no ``emails`` row, and was counted
    # by nothing at all — so "we read your mail and discarded it" was still the
    # same response as "your mailbox was quiet", just with a different message
    # in it. These three fields are what make the difference statable.
    #
    # THEY PARTITION, and the partition is the point:
    #
    #     classified == filed + queued + dropped + reached_nothing
    #
    # An accounting that does not close is how messages go missing silently, so
    # it is asserted rather than assumed — over hand-built shapes and over the
    # 17,260-message adversarial corpus, in
    # ``tests/test_gmail_sync_says_what_it_looked_at.py``.
    #
    # ``classified`` is NOT ``scanned``. ``scanned`` is what the scan read from
    # Gmail; ``_classify_messages`` then skips the user's own sent mail before a
    # pipeline item exists, so the difference is that skip. The partition closes
    # over the narrower number because a message that never became an item was
    # never routed anywhere.
    #
    # ``queued`` is NOT ``needs_review``, and the two will legitimately
    # disagree. This is what the SCAN routed to the queue; ``needs_review`` is
    # what the MERGE then persisted, and the additive merge drops refs whose
    # thread already holds a settled sibling. Two questions, two numbers, named
    # apart on purpose — a single field would have to lie to one of them.
    #
    # ``reached_nothing`` is the one the issue is about. See
    # ``pipeline.ScanLedger``: it is the corpus harness's ``LOST`` widened to
    # what the product can compute without ground truth, so it holds genuine
    # misses and correctly-ignored noise together. Non-zero on every healthy
    # sync of a real mailbox — a newsletter belongs in it — which is why it is
    # reported beside ``classified`` and never alone.
    classified: int = 0
    filed: int = 0
    queued: int = 0
    reached_nothing: int = 0


# =============================================================================
# Per-user inbox cache (short TTL, in-process)
# =============================================================================
#
# ``GET /gmail/inbox`` is expensive: it lists + fetches metadata for up to
# ``gmail_fetch_page_size`` messages from Gmail and runs each through the
# classifier. A dashboard/inbox refresh that repeats within a few seconds
# should not pay that cost twice. We keep a tiny in-process cache keyed by
# ``user_id`` with a short TTL (``gmail_inbox_cache_ttl_seconds``).
#
# Isolation: entries are keyed strictly by the authenticated user's UUID and
# are never shared across users, so the cache cannot leak one user's mail to
# another and does not weaken auth (the JWT is still verified on every call
# before the cache is ever consulted). On serverless this is a best-effort,
# per-warm-instance cache — a cold instance simply recomputes; correctness
# never depends on a hit.
_MAX_CACHE_ENTRIES = 512
# cache_key -> (stored_at_monotonic, response, etag). The key is composite —
# per user_id AND per (query, page_size, page_token) — so paging through a
# large mine, or switching range/scope, never serves a stale page. Still keyed
# by the authenticated user's UUID first, so nothing is ever shared across
# users.
_INBOX_CACHE: dict[str, tuple[float, InboxResponse, str]] = {}


def _inbox_cache_key(
    user_id: uuid.UUID,
    *,
    query: str,
    page_size: int,
    page_token: str | None,
) -> str:
    """Composite, per-user cache key for one inbox page request."""

    return f"{user_id}|{query}|{page_size}|{page_token or ''}"


def _inbox_etag(response: InboxResponse) -> str:
    """Stable strong ETag over the verdicts this response carries."""

    digest = hashlib.sha256(
        response.model_dump_json(exclude={"note"}).encode("utf-8")
    ).hexdigest()
    return f'"{digest[:32]}"'


def _inbox_cache_get(cache_key: str) -> tuple[InboxResponse, str] | None:
    """Return a fresh cached (response, etag) for ``cache_key`` or ``None``."""

    ttl = settings.gmail_inbox_cache_ttl_seconds
    if ttl <= 0:
        return None
    entry = _INBOX_CACHE.get(cache_key)
    if entry is None:
        return None
    stored_at, response, etag = entry
    if (time.monotonic() - stored_at) > ttl:
        _INBOX_CACHE.pop(cache_key, None)
        return None
    return response, etag


def _inbox_cache_put(cache_key: str, response: InboxResponse) -> str:
    """Cache ``response`` under ``cache_key`` and return its ETag.

    Skips caching entirely when the TTL is disabled. Applies a crude size
    cap (drop the oldest entry) so a burst of distinct users/pages on one warm
    instance cannot grow the map without bound.
    """

    etag = _inbox_etag(response)
    ttl = settings.gmail_inbox_cache_ttl_seconds
    if ttl <= 0:
        return etag
    if len(_INBOX_CACHE) >= _MAX_CACHE_ENTRIES and cache_key not in _INBOX_CACHE:
        oldest_key = min(_INBOX_CACHE, key=lambda k: _INBOX_CACHE[k][0])
        _INBOX_CACHE.pop(oldest_key, None)
    _INBOX_CACHE[cache_key] = (time.monotonic(), response, etag)
    return etag


def _apply_inbox_cache_headers(response: Response, etag: str) -> None:
    """Set validator + private cache headers on an inbox response."""

    response.headers["ETag"] = etag
    ttl = max(settings.gmail_inbox_cache_ttl_seconds, 0)
    # ``private`` — this is per-user mail; never let a shared cache/CDN store it.
    response.headers["Cache-Control"] = f"private, max-age={ttl}"


# =============================================================================
# OAuth state (signed, short-lived, user-bound, carries the PKCE verifier)
# =============================================================================


def _generate_code_verifier() -> str:
    """Return a fresh PKCE code verifier (RFC 7636: 43-128 unreserved chars).

    ``token_urlsafe(64)`` yields 86 chars of ``[A-Za-z0-9_-]`` — squarely
    inside the RFC's charset and length window.
    """

    return secrets.token_urlsafe(64)


def _sign_state(
    user_id: uuid.UUID,
    code_verifier: str,
    return_origin: str | None = None,
    chained: bool = False,
) -> str:
    """Return an HS256-signed state binding the flow to ``user_id``.

    The PKCE ``code_verifier`` rides along in the ``cv`` claim,
    Fernet-encrypted with ``settings.secret_encryption_key``: the signed
    JWT makes it tamper-proof and expiring, the encryption keeps it
    secret from everything the state transits (browser history, Google,
    proxy/URL logs). Only this backend can decrypt it in the callback —
    which is what makes PKCE work across two serverless invocations.

    ``return_origin`` — where the browser goes afterwards — rides in the ``ro``
    claim, SIGNED BUT NOT ENCRYPTED, and the difference from ``cv`` is
    deliberate. The verifier is a secret; the origin is the address bar the
    user is looking at. Fernet-wrapping it would imitate the line above without
    buying anything, and would hide the one value worth being able to read off
    a state while debugging a redirect. What the signature gives it is the only
    property it needs: this backend validated it at mint
    (:func:`_validated_return_origin`) and nothing between here and the
    callback can change it.

    Omitted entirely when ``None``, rather than written as null: the callback
    distinguishes "no origin was carried" (fall back to ``web_app_url``) from
    "an origin was carried", and an absent claim is the honest spelling of the
    first.
    """

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "aud": _STATE_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=settings.gmail_oauth_state_ttl_seconds),
        "jti": secrets.token_urlsafe(16),
        "cv": _require_fernet().encrypt(code_verifier.encode("utf-8")).decode("ascii"),
    }
    if return_origin:
        payload["ro"] = return_origin
    # ``ch`` — was this consent CHAINED off a sign-in rather than chosen in
    # Settings (#510)? It has to survive the round trip to Google, and the state
    # is the only thing that does, so it rides here beside ``ro`` and is read
    # the same way.
    #
    # It selects between TWO SAME-ORIGIN PATHS this module spells out in full
    # (`/dashboard` and `/settings`) and nothing else. It is never a URL, never
    # forwarded to Google, and cannot influence ``return_origin``, which keeps
    # its own mint-time validation against ``trusted_web_hosts``. A boolean that
    # picks between two literals cannot widen the open-redirect surface.
    #
    # Written only when true, like ``ro``: an absent claim is the honest
    # spelling of "this state predates the flag", and it reads as Settings,
    # which is what every state minted before this change meant.
    if chained:
        payload["ch"] = True
    return jwt.encode(payload, settings.secret_encryption_key, algorithm="HS256")


def _verify_state(token: str) -> tuple[uuid.UUID, str, str | None, bool] | None:
    """Return ``(user_id, code_verifier, return_origin, chained)`` for a valid state.

    ``None`` for an invalid one. A state without a decryptable ``cv`` claim
    (forged, expired key, or minted by a pre-PKCE deploy) is treated as
    invalid — the callback bounces back with ``?gmail=error`` and the user
    simply reconnects.

    ``ro`` IS READ WITH ``.get`` AND ITS ABSENCE IS NOT AN ERROR. The web app
    and this API are separate Vercel projects that deploy independently, so
    there is a window in which states minted by the older web deploy arrive
    here carrying no origin. Treating that as an invalid state would break
    every connect started seconds before the deploy; it means "fall back to
    ``web_app_url``", which is exactly what that setting is still for.

    The claim is re-parsed through :func:`canonical_return_origin` rather than
    trusted as a string. That is not a second trust decision — no allowlist is
    consulted here, and the origin was checked against one at mint — it is the
    guarantee that only a shape this code can construct ever reaches a
    ``Location`` header, however the claim got into the token.
    """

    try:
        payload = jwt.decode(
            token,
            settings.secret_encryption_key,
            algorithms=["HS256"],
            audience=_STATE_AUDIENCE,
            options={"require": ["exp", "sub", "aud"]},
        )
        user_id = uuid.UUID(payload["sub"])
        code_verifier = (
            _require_fernet().decrypt(str(payload["cv"]).encode("ascii")).decode("utf-8")
        )
        claimed_origin = payload.get("ro")
        return_origin = (
            canonical_return_origin(claimed_origin)
            if isinstance(claimed_origin, str)
            else None
        )
        # ``ch`` is read with ``.get`` and compared to True rather than
        # truth-tested, for the same reason ``ro`` is re-parsed rather than
        # trusted: only a value this code could have written may reach the
        # branch, whatever else got into the token.
        chained = payload.get("ch") is True
        return user_id, code_verifier, return_origin, chained
    except (
        jwt.InvalidTokenError,
        InvalidToken,
        CredentialEncryptionError,
        KeyError,
        ValueError,
        TypeError,
    ):
        return None


# =============================================================================
# Google flow helpers
# =============================================================================


def _build_flow(code_verifier: str | None = None) -> Flow:
    """Construct a google-auth-oauthlib web ``Flow`` from operator settings.

    PKCE is managed explicitly, never autogenerated: ``authorize`` and
    ``callback`` run in different serverless invocations, so a verifier
    the library invents inside one ``Flow`` object can never reach the
    other — the exchange then fails with ``invalid_grant`` (this was the
    live "Connect Gmail → error" bug). Instead the caller passes the
    verifier explicitly on both legs; ``authorization_url`` derives the
    S256 challenge from it, ``fetch_token`` sends it back to Google.
    ``autogenerate_code_verifier=False`` is load-bearing — some library
    versions would otherwise silently replace our verifier.
    """

    client_config = {
        "web": {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [settings.gmail_oauth_redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=settings.gmail_scopes,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = settings.gmail_oauth_redirect_uri
    return flow


def _web_app_base() -> str:
    """The FALLBACK base URL to bounce the browser back to, or raise.

    NO LONGER THE PRIMARY ANSWER (#333). The destination is normally the origin
    the caller started from, validated at ``/auth/gmail/authorize`` and carried
    in the signed state; this runs only when no such origin reached the
    callback — a state minted by an older web deploy, or one too forged to
    read. Everything below is why, when it does run, it refuses rather than
    guesses.

    WHY THIS IS NOT JUST ``settings.web_app_url.rstrip("/")`` ANY MORE
    -----------------------------------------------------------------
    It was, and it sent every Gmail connect/disconnect to the wrong hostname
    for weeks. ``JOBTRACKER_WEB_APP_URL`` still named
    ``jobtracker-web-five.vercel.app`` — a pre-rename alias of the web project
    — long after the app became ``getapplied.vercel.app``. Both aliases serve
    the same deployment, so every page rendered correctly and nothing looked
    broken. But **cookies are scoped to a host**: the user's Supabase session
    exists on the name they signed in on and nowhere else. Arriving on the
    other alias is arriving signed out, so the proxy did its job and sent them
    to ``/login`` — after a successful Gmail connect, with a live session, from
    a click that never touched sign-in. Reproduced against production with no
    credentials; the two curls are quoted in ``config.trusted_web_hosts``.

    THE PROPERTY THIS PRESERVES. The destination still comes from operator
    configuration and NEVER from the request — that is the open-redirect
    guarantee in this module's header and it is untouched. What is added is the
    other half: the configured value must name a host this deployment already
    trusts as its front end (the same list CORS is built from). A hostname that
    is merely *reachable* is not the same as the hostname the session is on,
    and that distinction is the whole bug.

    WHY IT RAISES RATHER THAN GUESSING. Falling back to a host we picked would
    make a misconfiguration invisible again, one layer down. Worse, the old
    code's own fallback was silent and actively harmful: with ``web_app_url``
    unset, ``(None or "").rstrip("/")`` yields ``""`` and the target becomes
    the RELATIVE ``/settings?gmail=connected``, which the browser resolves
    against the API's host — stranding the user on the backend, which has no
    such page. 503 with a message naming the offending host is a deploy problem
    an operator can read and fix in one edit.
    """

    configured = (settings.web_app_url or "").strip().rstrip("/")
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Gmail OAuth cannot complete: JOBTRACKER_WEB_APP_URL is not set, "
                "so there is no web app to return the browser to."
            ),
        )

    if not web_app_host_is_trusted():
        host = configured_web_app_host() or ""
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Gmail OAuth cannot complete: JOBTRACKER_WEB_APP_URL points at "
                f"'{host}', which this deployment does not recognise as a host "
                "it serves the web app on. Returning the browser there would "
                "land it on a hostname that does not carry the user's session, "
                "i.e. signed out. TWO variables have to agree, and this API "
                "runs on a different Vercel project from the web app so it "
                "cannot infer the second: set JOBTRACKER_WEB_APP_URL to the "
                f"origin the app is served from, AND add '{host}' to "
                "JOBTRACKER_CORS_ALLOWED_HOSTS so this deployment knows it is "
                "ours. See config.trusted_web_hosts."
            ),
        )
    return configured


def _validated_return_origin(raw: str) -> str:
    """Approve the caller's own origin as a return destination, or refuse.

    THE ONE PLACE THE TRUST DECISION IS MADE, and it is made HERE — at
    ``/auth/gmail/authorize``, before a consent URL exists and before Google is
    ever reached — not in the callback. That ordering is the whole design of
    #333. Carrying an origin across the round trip inside a token we signed is
    only safe if we checked it before signing; a callback that validated
    instead would be an open redirect for the entire ten-minute window in which
    the check could be made to pass, and would have relocated the trust
    decision to the leg an attacker reaches.

    Three refusals, three different operator stories, so the message has to say
    which one happened:

    1. Not an origin at all — a scheme we will not emit, credentials in the
       authority, a path. :func:`config.canonical_return_origin` decides, and
       what it returns is REBUILT from parsed parts, so the string that ends up
       in the state is one this code constructed.
    2. Not ours — the hostname is outside ``config.trusted_web_hosts``. This is
       the actionable one: the operator adds it to
       ``JOBTRACKER_CORS_ALLOWED_HOSTS`` and it works.
    3. Ours, but it is THIS API. The trusted list contains the API's own
       hostnames because CORS needs them there; returning the browser to one
       strands it on a backend that serves no ``/settings``. Adding a host to
       the allowlist cannot fix this and the message must not suggest it can.

    400, NOT 503. ``_web_app_base``'s 503 means "this deployment is
    misconfigured", and ``apps/web/lib/gmail/server.ts`` maps 503 onto "Gmail
    isn't enabled on this deployment yet" — wrong and actionless for a caller
    that sent a bad origin, and precisely the dead end the authorize route
    handler's docstring exists to prevent. A 400 lands on ``?gmail=error``.
    """

    origin = canonical_return_origin(raw)
    if origin is None:
        # Truncated: this reaches logs, and the caller controls the bytes.
        shown = (raw or "").strip()[:120]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Gmail OAuth cannot start: return_origin '{shown}' is not a "
                "usable web origin. Expected exactly scheme://host[:port] — "
                "https for a remote host, http only for localhost — with no "
                "credentials, path, query or fragment."
            ),
        )

    if not return_origin_is_trusted(origin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Gmail OAuth cannot start: return_origin '{origin}' is not a "
                "host this deployment serves the web app on, so the browser "
                "would be returned to a hostname that does not carry the "
                "user's session, i.e. signed out. If this origin really is "
                "ours, add its hostname to JOBTRACKER_CORS_ALLOWED_HOSTS. See "
                "config.trusted_web_hosts."
            ),
        )

    if return_origin_is_this_api(origin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Gmail OAuth cannot start: return_origin '{origin}' is this "
                "API's own origin, not the web app's. It appears in the "
                "trusted list because CORS is built from the same list; "
                "returning the browser here would strand it on a backend that "
                "serves no /settings. Send the origin the user is actually "
                "browsing. See config.return_origin_is_this_api."
            ),
        )

    return origin


def _web_redirect(
    outcome: str, return_origin: str | None = None, chained: bool = False
) -> RedirectResponse:
    """Redirect the browser back into the web app after a Gmail round trip.

    ``outcome`` is a coarse, non-sensitive status token (``connected`` /
    ``error``); no token or email ever rides in the URL.

    ``return_origin`` IS NOT A VALUE FROM THIS REQUEST. It reaches here only
    out of :func:`_verify_state`, i.e. out of a token this backend signed,
    carrying an origin :func:`_validated_return_origin` approved before the
    consent URL was minted. The open-redirect guarantee is unchanged in
    substance and moved in mechanism: it used to rest on "the destination is
    operator configuration", and now rests on "the destination was checked
    against the operator's trusted list one leg earlier and signed". Nothing
    the callback receives from Google can influence it — see
    ``tests/test_gmail_oauth_return_host.py``, which asserts the callback grew
    no destination parameter of its own.

    ``None`` means no origin crossed the round trip (a state from an older
    deploy, or one too forged to read) and the operator-configured fallback
    answers instead.
    """

    base = return_origin or _web_app_base()
    # WHERE A CHAINED CONSENT LANDS (#510).
    #
    # Every Gmail callback used to end on `/settings`, unconditionally. That is
    # right for someone who pressed Connect there and wrong for someone who
    # just signed up: #504 chains the consent straight off a first Google
    # sign-in, so the very first screen of a brand-new account was a
    # PREFERENCES PAGE, reached by a redirect they never asked for, reporting
    # an outcome they experienced as "signing up". The report was, fairly,
    # "that is very unprofessional".
    #
    # The dashboard is where the sign-in was going before the chain got
    # involved, and it is also where the work is: a freshly connected account
    # has no `last_sync_at`, `isStale` reads a missing stamp as stale, and
    # `SyncBar`'s once-per-mount auto-sync fires on arrival. So landing there
    # shows the first scan running rather than announcing a setting changed.
    #
    # The FAILURE path lands there too and keeps its flag. A chained user whose
    # connect failed must not be dropped on a silent dashboard — the reason has
    # to travel with them, and `/settings` is not where they were going.
    page = "/dashboard" if chained else "/settings"
    target = f"{base}{page}?gmail={urllib.parse.quote(outcome)}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


def _require_configured() -> None:
    if not settings.gmail_oauth_configured:
        missing = ", ".join(
            f"JOBTRACKER_{name.upper()}"
            for name in settings.gmail_oauth_missing_fields
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Gmail OAuth is not configured on this deployment. The operator "
                "must set the missing backend environment variable(s): "
                f"{missing}."
            ),
        )


# =============================================================================
# The connection cap — rationing a resource Google will not sell back
# =============================================================================

# Where a refused visitor goes next. A cap with no contact route is a dead end,
# and a dead end is how you lose the one person who actually wanted the product.
BETA_CONTACT_EMAIL = "aesh.03.23@gmail.com"


async def gmail_connection_census(
    user_id: uuid.UUID | None = None,
) -> tuple[int, bool]:
    """``(distinct users with a connected mailbox, is ``user_id`` one of them)``.

    WHY ``gmail_sync_enrollment`` AND NOT ``user_credentials``
    ---------------------------------------------------------
    ``user_credentials`` is FORCE-RLS and holds the refresh tokens. Counting it
    from inside an authenticated request would answer 0 or 1 — every policy on
    that table is keyed to ``auth.uid()``, so the caller can only ever see their
    own row — and counting it with no identity bound answers nothing at all.
    Either way the number would be *wrong in the safe-looking direction*: a
    cap that always reads 1 admits everybody forever. Widening a policy, or
    reaching for a ``SECURITY DEFINER`` wrapper, to make that count work would
    put a new path in front of the tokens for the sake of a number that is not
    a secret — exactly what ``GmailSyncEnrollment``'s docstring exists to
    refuse.

    ``gmail_sync_enrollment`` is the membership fact with none of the secret,
    published for precisely this shape of question (the cron asks the same one),
    and its ``SELECT`` policy is permissive for the runtime role so an
    identity-less read genuinely returns every row. It is written and deleted in
    the SAME transaction as the credential, so it cannot drift from it.

    ``user_id_scope(None)`` is stated rather than assumed: this runs inside a
    request that HAS an identity bound, and the count must be the deployment's,
    not the caller's. Note that the count is deliberately identity-less while
    the membership probe below is answered from the same identity-less read —
    enrollment carries no secret, so there is nothing to scope down to.

    A ROW SURVIVING ``revoked_at`` IS CORRECT HERE, and is the opposite of what
    the cron wants from this table (``cron._probe_sync_position`` subtracts
    revoked grants so it does not waste sync slots). A user who revoked at
    Google still spent a Google slot; forgetting them would let the cap admit
    someone in a seat Google still considers occupied. Do not "fix" this to
    match the cron.

    WHAT THIS COUNT CANNOT SEE, stated because the ceiling's headroom is the
    only thing covering it: a visitor who reaches Google's consent screen and
    abandons it spends a slot and writes no row anywhere; and a user who
    disconnects deletes their row here while Google keeps the slot. So the true
    Google number is ``>=`` this one, never below it, and the conservative
    default ceiling (25 of 100) is what absorbs the difference. The honest fix
    is a ceiling well under the real cap, not a ledger table this deployment
    would have to keep truthful across a flow it does not control.

    RLS IS AN ARGUMENT FROM SOURCE HERE, NOT A TESTED FACT. The suite that
    exercises this runs on SQLite, which has no row-level security; the
    Postgres-backed proofs for this table live in ``tests/test_rls_postgres.py``.
    """

    from sqlalchemy import func as sa_func
    from sqlmodel import select

    from jobtracker.database import get_session
    from jobtracker.database.models import GmailSyncEnrollment

    with user_id_scope(None):
        async with get_session() as session:
            # ONE session for both reads: under the cloud engine's NullPool a
            # session is a fresh TCP+TLS+auth connection (~216 ms from iad1),
            # so the second statement is nearly free and a second session is
            # not (#203).
            total_row = (
                await session.exec(
                    select(sa_func.count()).select_from(GmailSyncEnrollment)
                )
            ).one()
            connected = int(
                total_row[0] if hasattr(total_row, "__getitem__") else total_row
            )

            already = False
            if user_id is not None:
                already = (
                    await session.exec(
                        select(GmailSyncEnrollment.user_id)
                        .where(GmailSyncEnrollment.user_id == user_id)
                        .limit(1)
                    )
                ).first() is not None

    return connected, already


async def _enforce_connection_cap(user_id: uuid.UUID) -> None:
    """Refuse to mint a consent URL once the beta is full. Fails CLOSED.

    THE PLACEMENT IS THE WHOLE GUARD. Google's cap on this project is spent
    when a person *reaches* the consent screen — the account is counted whether
    or not they finish, and Google's wording is that the number "cannot be reset
    or changed". A check in the callback would therefore run one leg too late,
    after the irreversible thing already happened, and would look identical in
    every test that only asserts "a stranger cannot connect". This runs before
    ``flow.authorization_url`` exists, so a refusal costs nothing.

    AN ALREADY-CONNECTED USER IS NEVER REFUSED, even over the ceiling.
    Reconnecting re-consents an account Google has already counted, so it spends
    no new slot; blocking it would break exactly the users the cap was protecting
    — including the operator, who would be locked out of their own product the
    first time a token needed re-granting. The membership probe is what makes
    this branch real, and it has its own mutation test.

    409, NOT 403 AND NOT 503. This deviates from the usual "refusal = 403" and
    the deviation is the point: ``apps/web/lib/gmail/server.ts`` maps 401/403
    onto "your session couldn't be verified — sign in again" and 503 onto "Gmail
    isn't enabled on this deployment yet". Both are false here and neither is
    actionable, which is the dead end ``_validated_return_origin`` chose 400
    over 503 to avoid. 409 is distinguishable **by status alone**, so the web
    can label it without sniffing a response body that will rot.

    A CENSUS THAT CANNOT BE TAKEN IS A REFUSAL. If the database is unreachable
    (Supabase pauses a free-tier project after seven days idle) the count is
    unknown, and "unknown" must not mean "go ahead" — that is how a guard on a
    non-renewable resource quietly stops guarding. 503 with an operator-legible
    reason, and no consent URL.
    """

    ceiling = settings.gmail_connection_cap

    try:
        connected, already_connected = await gmail_connection_census(user_id)
    except Exception as exc:  # noqa: BLE001 — refuse rather than guess
        logger.error(
            "Gmail connection cap could not be evaluated (%s); refusing to mint "
            "a consent URL.",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Gmail connect is temporarily unavailable: this deployment "
                "could not read how many mailbox connections are already in "
                "use, and it will not start a Google consent flow it cannot "
                "count. Try again shortly."
            ),
        ) from exc

    if already_connected or connected < ceiling:
        return

    logger.warning(
        "Gmail connect refused: %d/%d connections used (user_id=%s is new).",
        connected,
        ceiling,
        user_id,
    )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "The Applied beta is at capacity for Gmail connections "
            f"({connected} of {ceiling} in use), so this account cannot connect "
            "a mailbox right now. Google caps how many people this app may ever "
            "connect, and that number cannot be raised on request. Email "
            f"{BETA_CONTACT_EMAIL} to ask for a place and you will be told "
            "either way. Nothing else in Applied is affected: importing a "
            "mailbox export at /import needs no Google account and stays open."
        ),
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/auth/gmail/status", response_model=GmailStatusResponse)
async def gmail_status(
    user_id: uuid.UUID = Depends(current_user),
) -> GmailStatusResponse:
    """Report whether Gmail is available, connected, and when it last synced.

    Always 200 so the web UI can render an honest state (including "not yet
    configured by the operator") without treating it as an error.

    Sync state is served from **here** rather than a second endpoint on purpose:
    the web already fetches this on the settings and inbox screens, "last synced
    3 minutes ago" belongs directly beside "connected as <address>", and the two
    are not independently meaningful — a cursor without a connection is nothing
    to render. One round trip, one user scope, one cache policy.
    """

    if not settings.gmail_oauth_configured:
        return GmailStatusResponse(configured=False, connected=False)

    # ONE session for both reads. Each of these helpers opened its own session,
    # and under the cloud engine's NullPool a session is a fresh TCP+TLS+auth
    # connection (~216 ms from iad1) plus its own transaction-GUC round trip —
    # so this endpoint, fetched on the settings AND inbox screens, paid two
    # serial connections per render (issue #203).
    from jobtracker.cloud.sync_state import load_gmail_sync_state
    from jobtracker.database import get_session

    async with get_session() as session:
        stored = await get_gmail_credentials(user_id, session)
        if stored is None:
            return GmailStatusResponse(configured=True, connected=False)

        state = await load_gmail_sync_state(session, user_id, stored.email)
    return GmailStatusResponse(
        configured=True,
        connected=True,
        email=stored.email,
        last_sync_at=_iso_utc(state.last_sync_at if state is not None else None),
        has_cursor=bool(state is not None and state.gmail_history_id),
        sync_status=state.status if state is not None else None,
        sync_error=state.error_message if state is not None else None,
        # Straight through, NULLs included. ``state is None`` and a row whose
        # ledger columns are NULL are the same answer here — "no sync has
        # recorded one" — and neither is turned into a zero.
        last_scanned=state.last_scanned if state is not None else None,
        last_classified=state.last_classified if state is not None else None,
        last_filed=state.last_filed if state is not None else None,
        last_queued=state.last_queued if state is not None else None,
        last_dropped=state.last_dropped if state is not None else None,
        last_reached_nothing=(
            state.last_reached_nothing if state is not None else None
        ),
    )


@router.get("/auth/gmail/authorize", response_model=GmailAuthorizeResponse)
async def gmail_authorize(
    user_id: uuid.UUID = Depends(current_user),
    return_origin: str | None = Query(
        default=None,
        description=(
            "The origin (scheme://host[:port]) the caller is being browsed on, "
            "which the callback will return the browser to. Validated against "
            "this deployment's trusted web hosts HERE, before any consent URL "
            "exists, and then carried across the round trip inside the signed "
            "state. Omit it and the callback falls back to the operator's "
            "JOBTRACKER_WEB_APP_URL."
        ),
    ),
    chained: bool = Query(
        default=False,
        description=(
            "True when this consent was chained straight off a Google sign-in "
            "rather than chosen on the Settings page. It changes ONE thing: "
            "which same-origin page the callback returns the browser to "
            "(/dashboard rather than /settings). It is carried across the round "
            "trip inside the signed state and is never forwarded to Google."
        ),
    ),
) -> GmailAuthorizeResponse:
    """Return the Google consent URL for the authenticated user.

    The browser navigates to this URL (top-level) itself; we do not 302
    here so the user's JWT never has to accompany a cross-site redirect.
    ``access_type=offline`` + ``prompt=consent`` guarantee a refresh token.

    The PKCE verifier minted here reaches the callback encrypted inside
    the signed ``state`` (see ``_sign_state``). Incremental scope merging
    (``include_granted_scopes``) is deliberately NOT requested: this app
    only ever wants ``gmail.readonly``, and merged prior grants would make
    the token response's scope set diverge from the requested one, which
    strict OAuth clients reject.

    WHY THE ORIGIN IS A PARAMETER AND NOT A HEADER. This endpoint is never
    called by a browser: the web app's ``/api/gmail/authorize`` route handler
    calls it server-side with the user's Supabase JWT attached, which is why
    CORS never had to admit the web origin and why the missing allowlist entry
    went unnoticed for weeks (``config.trusted_web_hosts`` has the probe). A
    server-side caller has no ``Origin`` header to read, so it states its
    origin explicitly and this endpoint decides whether to believe it —
    against the same list, before Google is reached. Refusing here rather than
    in the callback is the point: the user is told at the click, not after
    consenting.

    THE SAME ORDERING, FOR A HARDER REASON: the beta's connection cap
    (:func:`_enforce_connection_cap`) is enforced here too. Google spends one of
    this project's lifetime user slots when a person reaches the consent
    screen, so a check at the callback would be a check after the loss. 409
    when the beta is full, with the contact route in the message; an
    already-connected user is never refused, because reconnecting spends no new
    slot.

    The cap is evaluated AFTER the origin check purely on cost — it is the only
    database read on this path (~216 ms on a cold NullPool connection) and a
    malformed origin should not pay for it. Both refusals precede the consent
    URL, which is the property that matters.
    """

    _require_configured()

    validated_origin = (
        _validated_return_origin(return_origin) if return_origin else None
    )

    await _enforce_connection_cap(user_id)

    code_verifier = _generate_code_verifier()
    flow = _build_flow(code_verifier=code_verifier)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=_sign_state(user_id, code_verifier, validated_origin, chained),
    )
    return GmailAuthorizeResponse(authorization_url=authorization_url)


@router.get("/auth/gmail/callback", include_in_schema=False)
async def gmail_callback(
    state: str | None = Query(default=None),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Handle Google's redirect: exchange the code and store the token.

    This endpoint is intentionally unauthenticated (the browser arrives
    here from Google, not from the app) — identity comes from the signed
    ``state``. On any failure we bounce back to the web app with
    ``?gmail=error`` rather than leaking details.

    So does the DESTINATION, and only from there. The state carries the origin
    the user started from, approved by ``_validated_return_origin`` one leg
    earlier; this function takes no destination parameter of its own and must
    not grow one. The two paths above that redirect *before* the state has been
    read — a provider error, and a state too forged to decode — genuinely do
    not know where the user came from and fall back to the operator's
    ``web_app_url``; there is nothing better to do, and inventing one from the
    request is the open redirect this design refuses.
    """

    if not settings.gmail_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail OAuth is not configured on this deployment.",
        )

    if error or not code or not state:
        logger.info("Gmail callback rejected: error=%s has_code=%s", error, bool(code))
        return _web_redirect("error")

    verified = _verify_state(state)
    if verified is None:
        # No readable state means no readable destination either: a forged or
        # expired token cannot tell us whether this was chained, so this falls
        # back to Settings exactly as it always did.
        logger.warning("Gmail callback rejected: invalid or expired state.")
        return _web_redirect("error")
    user_id, code_verifier, return_origin, chained = verified

    try:
        stored = await _exchange_and_store(user_id, code, code_verifier)
    except Exception as exc:  # noqa: BLE001 — never leak the token-bearing error
        logger.error(
            "Gmail token exchange failed for user_id=%s (%s).",
            user_id,
            type(exc).__name__,
        )
        return _web_redirect("error", return_origin, chained)

    logger.info("Gmail connected for user_id=%s (%s).", user_id, stored.email)
    return _web_redirect("connected", return_origin, chained)


def _exchange_code(code: str, code_verifier: str) -> GmailCredentials:
    """Blocking: redeem ``code`` (+ PKCE verifier) and read the account email.

    Module-level (rather than a closure) so tests can exercise the
    callback wiring — state round-trip, verifier hand-off, save/redirect
    honesty — without talking to Google.
    """

    flow = _build_flow(code_verifier=code_verifier)
    flow.fetch_token(code=code)
    creds = flow.credentials
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress", "unknown")
    return GmailCredentials(
        access_token=creds.token,
        refresh_token=creds.refresh_token or "",
        token_expiry=creds.expiry or (datetime.utcnow() + timedelta(hours=1)),
        email=email,
        scopes=list(creds.scopes or settings.gmail_scopes),
    )


async def _exchange_and_store(
    user_id: uuid.UUID, code: str, code_verifier: str
) -> GmailCredentials:
    """Exchange ``code`` for tokens, read the account email, and persist.

    Raises if the credential store rejects the save: a token that was
    exchanged but never stored is NOT a connection, and pretending
    otherwise would bounce the user to ``?gmail=connected`` while
    ``/auth/gmail/status`` honestly reports disconnected.

    This used to be the one place that could notice **background-sync list
    rot**: the scheduled sync enumerated its users from configuration
    (``JOBTRACKER_CRON_SYNC_USER_IDS``), so a second user who connected Gmail
    was silently never background-synced and the cron could not detect that by
    construction. There is no list to rot any more — the cron enumerates
    ``gmail_sync_enrollment``, which ``save_gmail_credentials`` writes in the
    SAME transaction as the token below, so connecting a mailbox *is* enrolling
    it. The warning that stood here is gone with the condition it warned about;
    leaving it would be a check that can no longer fail.
    """

    loop = asyncio.get_running_loop()
    stored = await loop.run_in_executor(None, _exchange_code, code, code_verifier)

    # The callback is deliberately unauthenticated (identity comes from the
    # signed ``state``), so no ``Depends(current_user)`` has bound the RLS
    # identity. ``user_credentials`` is a FORCE-RLS table, so we must scope the
    # write to this user explicitly or the INSERT's ``WITH CHECK`` fails.
    with user_id_scope(user_id):
        if not await save_gmail_credentials(user_id, stored):
            raise RuntimeError("credential store rejected the Gmail token save")

    return stored


@router.post("/auth/gmail/disconnect", response_model=GmailDisconnectResponse)
async def gmail_disconnect(
    user_id: uuid.UUID = Depends(current_user),
) -> GmailDisconnectResponse:
    """Revoke the grant at Google, delete the stored token, drop the cursor.

    The cursor is cleared FIRST and unconditionally — before the
    "was not connected" early return — because a ``historyId`` only means
    anything against the mailbox that issued it. A row surviving a disconnect
    would hand a re-linked (possibly different) account someone else's baseline,
    and an incremental sync from a foreign baseline skips mail.
    """

    from jobtracker.cloud.sync_state import clear_gmail_sync_state

    # A REVOKED GRANT MUST STILL BE DISCONNECTABLE. Disconnect is cleanup, not
    # use: the row still holds ciphertext and still has an enrollment row
    # occupying a connection-cap seat, and neither goes away on its own. Take
    # the default read here and a user whose grant Google already rejected can
    # never clear either one — `delete_gmail_credentials` below (which also
    # un-enrolls) would be unreachable behind the `stored is None` early exit.
    stored = await get_gmail_credentials(user_id, include_revoked=True)
    await clear_gmail_sync_state(user_id)
    if stored is None:
        return GmailDisconnectResponse(revoked=False, message="Gmail was not connected.")

    revoked = await _revoke_at_google(stored.refresh_token or stored.access_token)
    await delete_gmail_credentials(user_id)

    logger.info("Gmail disconnected for user_id=%s (google_revoked=%s).", user_id, revoked)
    return GmailDisconnectResponse(
        revoked=revoked,
        message=(
            "Gmail disconnected and access revoked at Google."
            if revoked
            else "Gmail disconnected; stored token deleted. Google revocation "
            "could not be confirmed — you can also remove access at "
            "myaccount.google.com/permissions."
        ),
    )


async def _revoke_at_google(token: str) -> bool:
    """Best-effort POST to Google's revocation endpoint. Never raises."""

    if not token:
        return False

    def _post() -> bool:
        data = urllib.parse.urlencode({"token": token}).encode("utf-8")
        req = urllib.request.Request(
            _REVOKE_URI,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed https URL
                return 200 <= resp.status < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Google token revocation failed: %s", type(exc).__name__)
            return False

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _post)


async def revoke_stored_gmail_grant(user_id: uuid.UUID) -> bool:
    """Revoke ``user_id``'s Gmail grant at Google, if one is stored.

    The disconnect handler above already had this shape inline; this is the
    same revocation as a callable so that account deletion can perform it too
    (issue #215) rather than growing a second implementation of Google's
    revocation protocol. ``POST /auth/gmail/disconnect`` keeps its own inline
    read because it needs the credential object anyway (to delete the row and
    to distinguish "was not connected"); both paths bottom out in
    ``_revoke_at_google``, which stays the one place that talks to Google.

    **Never raises**, and that is load-bearing for the caller in
    ``cloud/account.py``. Reading the stored credential can fail on its own —
    ``CredentialEncryptionError``/``InvalidToken`` after a Fernet key rotation,
    or a plain DB error — and an exception escaping here would 500 the account
    deletion. A grant we could not revoke is bad; a user unable to delete their
    account because of it is worse, so every failure becomes ``False`` and the
    caller decides what to do with it.

    Returns True only when Google confirmed the revocation.
    """

    try:
        # REVOKED ROWS INCLUDED, DELIBERATELY. `revoked_at` is written from a
        # string heuristic over Google's error response, and that heuristic's
        # own tests call the false positive the dangerous half — a LIVE grant
        # can carry the mark. Skipping revocation on the strength of that guess
        # would leave a real grant standing at Google after the account is
        # gone, which is the one thing this function exists to prevent. A
        # redundant revoke of an already-dead grant costs one ignored HTTP
        # call; a missed revoke of a live one is the #215 guarantee breaking.
        stored = await get_gmail_credentials(user_id, include_revoked=True)
    except Exception as exc:  # noqa: BLE001 — see docstring: must not raise
        logger.warning(
            "Could not read stored Gmail credentials to revoke for user_id=%s: %s",
            user_id,
            type(exc).__name__,
        )
        return False

    if stored is None:
        return False

    return await _revoke_at_google(stored.refresh_token or stored.access_token)


# Age filters the UI offers (months). Anything else → "all time" (no bound).
_ALLOWED_RANGE_MONTHS = frozenset({3, 6, 9, 12})


def _parse_range_months(value: str | None) -> int | None:
    """Map the ``range`` query param to a month count, or ``None`` for all-time.

    Accepts ``"3"``/``"6"``/``"9"``/``"12"`` (optionally suffixed ``m``) and
    ``"all"``/empty. Any unrecognized value falls back to all-time rather than
    erroring, so a stray param can never 500 the mine.
    """

    if value is None:
        return None
    token = value.strip().lower().rstrip("m")
    if token in ("", "all", "any", "0"):
        return None
    try:
        months = int(token)
    except ValueError:
        return None
    return months if months in _ALLOWED_RANGE_MONTHS else None


def _parse_scope(value: str | None) -> str:
    """``"anywhere"`` searches all mail (incl. archived); default ``"inbox"``."""

    return "anywhere" if (value or "").strip().lower() == "anywhere" else "inbox"


def _iso_utc(value: datetime | None) -> str | None:
    """Serialize a stored timestamp as ISO-8601 with an EXPLICIT UTC offset.

    ``sync_state.last_sync_at`` is a naive column holding UTC
    (``datetime.utcnow()``). Emitting it naive would make the browser's
    ``new Date(...)`` read it as *local* time — so a sync that just finished
    would render as "in 4 hours" for the owner in US Eastern. Getting that
    number right is the entire point of exposing it.
    """

    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 → datetime; tolerant of a trailing ``Z``."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/gmail/inbox", response_model=InboxResponse)
async def gmail_inbox(
    response: Response,
    user_id: uuid.UUID = Depends(current_user),
    if_none_match: str | None = Header(default=None),
    count: int | None = Query(default=None, ge=1),
    range: str | None = Query(default=None),  # noqa: A002 — public API name
    scope: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
    page_token: str | None = Query(default=None),
) -> InboxResponse | Response:
    """Read ONE server-side page of mail (filtered) and classify each message.

    The honest end of the pipeline, now high-volume and filterable:

    - ``range`` — ``3``/``6``/``9``/``12`` months, or all-time — becomes a
      Gmail ``newer_than:<N>m`` term.
    - ``scope`` — ``inbox`` (default) or ``anywhere`` (also searches archived /
      other-tab mail so filed-away interview & offer emails are found).
    - ``count`` — the client's total target; used only to clamp this page.
    - ``page_size`` / ``page_token`` — server-side pagination. The response
      carries ``next_page_token``; the web client loops until it reaches
      ``count`` or the token is null, showing a progress tally.

    A single invocation fetches at most ``gmail_fetch_page_size`` messages so
    it stays inside the Vercel function budget; big mines are many bounded
    pages, not one fragile mega-call.

    Bodies ARE fetched, and are never returned. This paragraph used to say
    "batched metadata gets, no bodies" and "full bodies are never fetched or
    returned"; both stopped being true when the classifier started reading
    bodies, and the distinction the sentence was reaching for is *retention*,
    not request. What actually happens: ``format="full"`` gets, capped at
    ``_MAX_BODY_CHARS``, and the body is handed to the classifier and dropped
    on the same line — see the read below and
    ``tests/test_body_is_never_persisted.py``, which fails if a marker string
    planted in a body reaches any stored column, the training table, a log
    record, or any response — THIS response included, which that test did not
    cover until 2026-08-15: a full body returned from here passed the whole
    file green. It runs in CI on pull requests touching ``backend/``; the
    repository has no branch protection, so a red run does not itself block a
    merge.

    Each verdict therefore carries the Gmail ``snippet`` rather than the text
    the verdict was actually made from, plus a deep link to the message, which
    is what makes a scan row judgeable at all. The per-user, per-page short-TTL
    cache + ``ETag``/``If-None-Match`` are unchanged; auth is verified on every
    request before the cache is consulted.
    """

    _require_configured()

    # Imported lazily so the classifier + Gmail client stay out of the cold-
    # start path for the OAuth endpoints (matches hybrid.py's cloud discipline).
    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import pipeline
    from jobtracker.cloud.gmail_client import (
        build_gmail_query,
        fetch_message_page,
        is_rate_limited_gmail_error,
    )

    range_months = _parse_range_months(range)
    mail_scope = _parse_scope(scope)
    query = build_gmail_query(range_months, mail_scope)  # type: ignore[arg-type]

    # How many this page pulls: the configured per-invocation ceiling, further
    # clamped by an explicit page_size, the total count target, and the hard cap.
    # 250, NOT Gmail's 500-id list ceiling. Quota, not the list API, is the
    # binding constraint: a page costs `20 x messages + 5` units against
    # 6,000 per minute per user, so 300 messages is the entire minute and a
    # 500-message page (10,005 units) cannot complete against a full bucket
    # however often it is retried. The literal is clamped here as well as
    # defaulted in config so that setting JOBTRACKER_GMAIL_FETCH_PAGE_SIZE=500
    # cannot silently re-arm a page size that is arithmetically impossible.
    configured_page = max(1, min(settings.gmail_fetch_page_size, 250))
    requested = page_size if page_size is not None else (count or configured_page)
    effective_page = max(
        1, min(requested, configured_page, settings.gmail_fetch_hard_cap)
    )

    cache_key = _inbox_cache_key(
        user_id, query=query, page_size=effective_page, page_token=page_token
    )
    cached = _inbox_cache_get(cache_key)
    if cached is not None:
        cached_response, etag = cached
        if if_none_match is not None and if_none_match == etag:
            not_modified = Response(status_code=status.HTTP_304_NOT_MODIFIED)
            _apply_inbox_cache_headers(not_modified, etag)
            return not_modified
        _apply_inbox_cache_headers(response, etag)
        return cached_response

    try:
        page = await fetch_message_page(
            user_id, query=query, page_size=effective_page, page_token=page_token
        )
    except Exception as exc:  # noqa: BLE001 — re-raised unless Gmail deferred
        # ONLY quota becomes a 429. A rate limit is not retried in place at
        # all (see `_RATE_LIMIT_REASONS`): a per-minute bucket does not refill
        # inside a 60 s function, so the wait belongs to the client, which has
        # no such budget and still holds the cursor.
        #
        # Everything else — a Gmail outage, a 5xx that outlived its bounded
        # retry — is left to raise and render as SCAN FAILED, because for those
        # that banner is the honest reading. Folding them into 429 would tell a
        # user to wait for something waiting cannot fix.
        if not is_rate_limited_gmail_error(exc):
            raise
        logger.warning(
            "Gmail deferred an inbox page for user_id=%s beyond retry; "
            "answering 429 so the mine can resume from its cursor.",
            user_id,
        )
        raise GmailRateLimited() from exc
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail is not connected for this user. Connect it first.",
        )

    # The connected address, for the deep links built below. Read once per
    # PAGE — not once per row, and not once per mine either: a 2,000-message
    # mine is several of these requests and so several credential reads. Only
    # past the cache check, so a cached page (which returns above carrying
    # links that were already built) costs none.
    #
    # Reaching here means the fetch found credentials, so this is effectively
    # never None (a disconnect racing the mine is the only way). The fallback
    # still matters: `gmail_deeplink` without an address emits the positional
    # ``/u/0/`` form, which is the FIRST account in the browser session and so
    # the wrong inbox for anyone signed into several Google accounts — the bug
    # already reported once against the board's links.
    stored = await get_gmail_credentials(user_id)
    account_email = stored.email if stored else None

    classifier = get_classifier()
    verdicts: list[InboxVerdict] = []
    summary = dict.fromkeys(pipeline.CANONICAL_CATEGORIES, 0)
    for msg in page.messages:
        # The body if the fetch produced one, else the snippet. Read here and
        # discarded: the ``InboxVerdict`` built below carries the SNIPPET, so
        # the body never reaches the response. See
        # ``tests/test_body_is_never_persisted.py``.
        result = await classifier.classify(
            msg.subject,
            page.bodies.get(msg.message_id) or msg.snippet,
            msg.sender_email,
        )
        category = result.category.value
        summary[category] = summary.get(category, 0) + 1
        verdicts.append(
            InboxVerdict(
                message_id=msg.message_id,
                subject=msg.subject,
                sender_email=msg.sender_email,
                sender_name=msg.sender_name,
                category=category,
                confidence=round(result.confidence, 4),
                method=result.method,
                needs_review=result.needs_review,
                received_at=msg.received_at.isoformat() if msg.received_at else None,
                company=pipeline.company_key(
                    msg.sender_email, msg.subject, msg.sender_name
                ),
                # Same unescape + 500-char truncation the store applies, so a
                # message reads identically whether it is mined or filed. `or
                # None` because a message Gmail gave no snippet for must arrive
                # as null, not "" — the row renders nothing for null and would
                # otherwise draw an empty preview line.
                snippet=pipeline.unescape_entities(msg.snippet or "")[:500] or None,
                gmail_link=pipeline.gmail_deeplink(
                    thread_id=msg.thread_id,
                    message_id=msg.message_id,
                    account_email=account_email,
                ),
            )
        )

    result_response = InboxResponse(
        connected=True,
        scanned=len(page.messages),
        verdicts=verdicts,
        next_page_token=page.next_page_token,
        category_summary=summary,
        query=query,
        scope=mail_scope,
        range_months=range_months,
        unreadable=page.unreadable,
        result_size_estimate=page.result_size_estimate,
        note=(
            "Classified from the subject and the message body using the "
            "rules-only cloud classifier (gmail.readonly). The body is read to "
            "classify and discarded — only Gmail's own short snippet is ever "
            "stored. SetFit classification runs in the desktop app."
        ),
    )

    etag = _inbox_cache_put(cache_key, result_response)
    _apply_inbox_cache_headers(response, etag)
    return result_response


@router.post(
    "/gmail/pipeline",
    response_model=PipelineAnalyzeResponse,
    dependencies=[Depends(current_user)],
)
async def gmail_pipeline(payload: PipelineAnalyzeRequest) -> PipelineAnalyzeResponse:
    """Analyze an accumulated set of verdicts: category summary + follow-ups.

    Pure aggregation over data the client already holds (no Gmail call, no
    bodies): the web client pages the mine via ``GET /gmail/inbox``, then posts
    the accumulated verdict metadata here to get the canonical whole-set
    category summary and the "No response — consider following up" flags across
    ALL pages (which no single page can compute alone).

    Auth is enforced via the route dependency (the caller's own data; 401
    without a valid JWT), and the input is bounded by the fetch hard cap so it
    cannot be abused as an unbounded compute endpoint.
    """

    from jobtracker.cloud import pipeline

    items = [
        pipeline.PipelineItem(
            message_id=item.message_id,
            category=item.category,
            sender_email=item.sender_email,
            subject=item.subject,
            sender_name=item.sender_name,
            received_at=_parse_iso(item.received_at),
        )
        for item in payload.items[: settings.gmail_fetch_hard_cap]
    ]

    stale_days = payload.stale_days or settings.gmail_followup_stale_days
    summary = pipeline.summarize(items)
    follow_ups = pipeline.flag_follow_ups(items, stale_days=stale_days)
    job_related = sum(
        summary.get(cat, 0) for cat in pipeline.JOB_LIFECYCLE_CATEGORIES
    )

    return PipelineAnalyzeResponse(
        total=len(items),
        job_related=job_related,
        category_summary=summary,
        follow_ups=[
            FollowUpOut(
                message_id=f.message_id,
                company=f.company,
                subject=f.subject,
                days_since=f.days_since,
                applied_at=f.applied_at.isoformat() if f.applied_at else None,
            )
            for f in follow_ups
        ],
    )


# Default backfill window (months) when the dashboard triggers a server-side
# sync without specifying a range.
_SYNC_DEFAULT_RANGE_MONTHS = 12

# A server-side auto sync scans a STABLE, deep-enough slice of that window: up
# to this many MESSAGES. Fixed so every routine run covers the same ground
# (durability no longer depends on which messages a single 500-cap page
# happened to catch) while staying inside the serverless time budget.
# 300, NOT 750. The old value was almost certainly derived from the OLD quota:
# 15,000 units per minute per user divided by 5 units per `messages.get` is
# exactly 750. Both halves of that arithmetic changed on 2026-05-01 — the
# ceiling fell to 6,000 and the cost rose to 20 — so the same derivation now
# yields 6000/20 = 300, and 750 became 15,005 units: two and a half minutes of
# a bucket, in a scan that has one invocation to spend.
#
# 297, NOT 300, AND THE THREE MATTER. A page is `20N + 5` units, so 300 is four
# pages — 99 + 99 + 99 + 3 — costing `1985*3 + 65 = 6,020`. Twenty over the
# ceiling, which by the exact arithmetic this file now enshrines means the
# DEFAULT full sync could never finish inside one bucket: every fresh-window
# run would end `rate_limited` rather than `target`, making the partial banner
# the common case and spending an extra invocation to discover it. 297 is three
# whole pages at 5,955 units and fits, with 45 units to spare.
#
# That mattered beyond a slow sync. A first-connect backfill has no
# continuation memory, so it re-read the same newest messages and stalled at
# the same wall on every attempt, which made `cron.py`'s stated rationale —
# that the path completing a first sync is the user's own Sync-now button —
# false. The deep-backfill path that DOES work is the workbench mine (paced by
# the client against 429s) followed by "File N into Applications", because the
# relay persist makes no Gmail calls at all.
_SYNC_DEFAULT_SCAN_TARGET = 297

# The scan used to stop after a fixed number of PAGES, which is the wrong bound
# when page sizes vary — and Gmail's do. ``maxResults`` is an upper bound, not a
# quota: the same request that yields 68 messages for ``in:inbox newer_than:3m``
# yields 41 for ``in:inbox``, so a page-count bound accumulates LESS the wider
# the window gets. Measured live on 2026-08-10 at page_size=100: 68 / 43 / 45 /
# 41 for 3m / 6m / 12m / all-time, every one of them with a next-page token. The
# user-visible result was "All time" reporting fewer scanned messages than
# "3 months" and looking broken.
#
# So the bound is the MESSAGE target, and these two are only safety rails on a
# pathological mailbox (Gmail returning a handful of ids per page forever):
#
# - ``_SYNC_MAX_LIST_CALLS`` — enough list calls to reach a 750-message target
#   even at 30 messages a page, which is well below anything observed.
# - ``_SYNC_TIME_BUDGET_SECONDS`` — the real backstop. Checked BEFORE each page
#   is started, against a monotonic deadline taken at scan entry, so a page can
#   never begin at 39 s and run past the 60 s function limit. Sized to leave
#   ~30 s for what follows the scan (rollup, the additive/rebuild merge and its
#   Supabase round-trips, the count query, the cursor write).
#
# Worst case is deliberately more expensive than the old 4-page bound: up to 25
# ``messages.list`` calls plus one metadata batch each (~1 s per page in
# practice; the inter-batch pause does not fire for a page under 100 messages),
# i.e. ~30 s of Gmail I/O instead of ~19 s, for a scan that is finally monotonic
# in the width of its window. Whichever rail stops it is REPORTED, never hidden.
_SYNC_MAX_LIST_CALLS = 25
_SYNC_TIME_BUDGET_SECONDS = 30.0


@dataclass
class _ScanOutcome:
    """What one server-side scan produced, plus the cursor to record.

    ``history_id`` is the mailbox baseline captured **before** the scan started
    (``None`` when Gmail's ``getProfile`` was unavailable — then the stored
    cursor is simply left alone and the next run is another full scan).

    ``scanned`` is what the scan READ — not what the mailbox holds and not what
    the window contains. ``unreadable``, ``stopped_by`` and
    ``result_size_estimate`` are what make that difference statable rather than
    implied; see :class:`SyncResponse` for what each one means.
    """

    items: list[Any]
    scanned: int
    incremental: bool
    history_id: str | None
    unreadable: int = 0
    stopped_by: str = STOPPED_COMPLETE
    result_size_estimate: int | None = None


async def _classify_messages(
    messages: list[Any],
    classifier: Any,
    pipeline: Any,
    bodies: dict[str, str] | None = None,
    account_email: str | None = None,
) -> list[Any]:
    """Run each fetched message through the classifier into a PipelineItem.

    ``bodies`` is the in-flight body text from the fetch (see
    ``gmail_client.MessagePage.bodies``). It is READ HERE AND NOWHERE ELSE, and
    the ``PipelineItem`` built below carries ``snippet``, never ``body``, so
    nothing downstream — persistence, the API response, ``training_data`` — can
    see the text. ``tests/test_body_is_never_persisted.py`` is the enforcement.

    WHAT IS DERIVED FROM IT, HOWEVER, IS CARRIED, and that changed on
    2026-08-23. Identity resolution used to re-derive the job title and the
    requisition number downstream from ``snippet`` — Gmail's own ~200
    characters — so a title printed past that was invisible to the board while
    the classifier, handed the whole body right here, read it perfectly. Torc
    Robotics prints "the Software Engineer I - Metrics for Release opportunity"
    at body character ~380 and its card carried no position; the shipped
    extractor returns the right answer the instant it is given the body. No
    pattern was missing. The text never arrived.

    Against a production-shaped corpus that gap was 50 applications split over
    two cards, 50 updates opening a rival card, and 81 further updates pushed
    into the review queue on top of the 371 that honestly belong there.

    Two things make carrying the derivation different from carrying the body:

    · A job title and a requisition number are BOUNDED, and
      ``applications.position`` / ``role_token`` / ``req_id`` have stored
      exactly this class of value since ``f1a2c9b73d40``. What changes is where
      the title is read from, not what kind of thing is kept. The sentinel test
      plants its marker immediately after the capture boundary, so a capture
      that ran long drags it into these fields and fails.

    · The result is PERSISTED (``emails.identity_role`` /
      ``identity_req_id``). Deriving from the body and keeping the answer only
      in flight would have been worse than the bug it fixes:
      ``pipeline.STORED_SNIPPET_CHARS`` records a queue key computed from one
      width of text and a settle key computed from another, which left the row
      unlinked, un-reviewed and re-queued on every sync forever. Storing it is
      what makes both sides of a decision read one value.

    Both fields are set to ``""`` — not left ``None`` — when the body names
    nothing, because those are different questions downstream: ``None`` means
    "never derived" and sends the reader back to the snippet, which is right for
    a client relay item and wrong for a message this function actually read.

    Falls back to the snippet when a message produced no body text, so a
    message Gmail answered with headers only classifies exactly as it did
    before rather than as an empty string — and derives its identity from that
    same snippet, which is all there is.
    """

    bodies = bodies or {}
    owner = (account_email or "").strip().lower()
    items: list[Any] = []
    for msg in messages:
        # A MESSAGE THE USER SENT IS NOT AN UPDATE ABOUT THEM.
        #
        # This is the guard that actually closes the hole, and it lives here
        # because here is where BOTH scan paths converge. The query-side
        # ``-in:sent`` in ``build_gmail_query`` only reaches the full scan; the
        # incremental path reads ``users.history.list``, which takes no query
        # and reports every change in the mailbox — including the user's own
        # replies the moment they send one.
        #
        # Structural, not textual, and it has to be: the four rows that
        # exposed this were job-search outreach the owner wrote himself, and
        # the classifier scored them ``applied`` at 0.9 on text that genuinely
        # reads like an application. No amount of pattern work fixes that,
        # because the text is not the thing that is wrong about them.
        #
        # Skipped silently rather than classified-and-dropped: an item that
        # never enters the pipeline cannot be persisted, counted, queued for
        # review, or fed to ``training_data`` as an example of anything.
        if owner and (msg.sender_email or "").strip().lower() == owner:
            continue
        text = bodies.get(msg.message_id) or msg.snippet
        result = await classifier.classify(msg.subject, text, msg.sender_email)
        items.append(
            pipeline.PipelineItem(
                message_id=msg.message_id,
                category=result.category.value,
                sender_email=msg.sender_email,
                subject=msg.subject,
                sender_name=msg.sender_name,
                received_at=msg.received_at,
                confidence=result.confidence,
                thread_id=msg.thread_id,
                snippet=msg.snippet,
                identity_role=pipeline.role_from_message(msg.subject, text) or "",
                identity_req_id=pipeline.extract_req_id(msg.subject, text) or "",
                # The layer that actually answered, not an assumption about it
                # (#496). This is the one path where a classifier really runs
                # server-side, so it is the one path that can report.
                method=result.method,
            )
        )
    return items


@dataclass
class _ScanRead:
    """What one scan read, and why it stopped reading.

    Shared by both server-side paths (full re-list and history delta) so the
    handler does not have to remember which one loses which number — the way
    ``unreadable`` was being lost here before.
    """

    items: list[Any]
    scanned: int
    unreadable: int = 0
    stopped_by: str = STOPPED_COMPLETE
    result_size_estimate: int | None = None


async def _full_scan(
    user_id: uuid.UUID,
    *,
    query: str,
    target: int,
    classifier: Any,
    pipeline: Any,
    account_email: str | None = None,
    deadline: float | None = None,
) -> _ScanRead:
    """Re-list a STABLE, deep-enough slice of the window (the fallback path).

    Bounded by MESSAGES EXAMINED, not by page count. Gmail treats ``maxResults``
    as an upper bound and hands back fewer messages per page as the query
    widens, so a page-count bound made a wider window scan *less* than a
    narrower one — see the ``_SYNC_MAX_LIST_CALLS`` commentary. Paging until the
    target is met makes the scan monotonic in the width of its window: a wider
    query can only ever match a superset of the mail, so it can only ever
    examine as many messages or more.

    Keeps paging through an EMPTY page that still carries a token — Gmail
    returns those, and treating one as the end of the mailbox is the same class
    of bug as counting pages.

    ``deadline`` is a ``time.monotonic()`` value; the default takes
    ``_SYNC_TIME_BUDGET_SECONDS`` from entry. It is checked before a page is
    STARTED so no page can begin inside the budget and finish outside it.
    """

    from jobtracker.cloud.gmail_client import (
        fetch_message_page,
        is_rate_limited_gmail_error,
    )

    if deadline is None:
        deadline = time.monotonic() + _SYNC_TIME_BUDGET_SECONDS

    items: list[Any] = []
    scanned = 0
    unreadable = 0
    estimate: int | None = None
    page_token: str | None = None
    stopped_by = STOPPED_COMPLETE

    for page_index in range(_SYNC_MAX_LIST_CALLS):
        remaining = target - scanned
        if remaining <= 0:
            stopped_by = STOPPED_TARGET
            break
        if time.monotonic() >= deadline:
            stopped_by = STOPPED_DEADLINE
            logger.warning(
                "Gmail full scan for user_id=%s stopped on its %ss time budget "
                "after %s message(s); the window is not fully covered.",
                user_id,
                _SYNC_TIME_BUDGET_SECONDS,
                scanned,
            )
            break
        try:
            page = await fetch_message_page(
                user_id,
                query=query,
                page_size=min(settings.gmail_fetch_page_size, remaining),
                page_token=page_token,
            )
        except Exception as exc:  # noqa: BLE001 — re-raised unless Gmail deferred
            # A deferred page must not sink a scan that has already read
            # several. This loop's whole contract is that an incomplete window
            # is reported as incomplete rather than claimed as whole — the
            # same treatment `STOPPED_DEADLINE` and `STOPPED_DISCONNECTED`
            # already get. Raising here would instead discard every page
            # collected so far and 500 the sync.
            if not is_rate_limited_gmail_error(exc):
                raise
            logger.warning(
                "Gmail full scan for user_id=%s stopped on a rate limit after "
                "%s message(s); the window is not fully covered.",
                user_id,
                scanned,
            )
            stopped_by = STOPPED_RATE_LIMITED
            break
        if page is None:
            if page_index == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Gmail is not connected for this user. Connect it first.",
                )
            # Gmail answered earlier pages and not this one. Whatever we hold is
            # a partial read of the window and must not be called complete.
            stopped_by = STOPPED_DISCONNECTED
            break
        items.extend(
            await _classify_messages(
                page.messages, classifier, pipeline, page.bodies, account_email
            )
        )
        scanned += len(page.messages)
        unreadable += page.unreadable
        if page.result_size_estimate is not None:
            estimate = max(estimate or 0, page.result_size_estimate)
        page_token = page.next_page_token
        if not page_token:
            break
    else:
        # The call ceiling ran out. It is only the REASON when it actually cut
        # the scan short: a last page that happened to complete the target
        # stopped on the target, and saying otherwise would report a budget
        # failure for a scan that got everything it asked for.
        if scanned >= target:
            stopped_by = STOPPED_TARGET
        else:
            stopped_by = STOPPED_PAGE_LIMIT
            logger.warning(
                "Gmail full scan for user_id=%s stopped on its %s-call list "
                "limit after %s message(s); the window is not fully covered.",
                user_id,
                _SYNC_MAX_LIST_CALLS,
                scanned,
            )

    return _ScanRead(
        items=items,
        scanned=scanned,
        unreadable=unreadable,
        stopped_by=stopped_by,
        # Never let the estimate sit below what we already read: a denominator
        # smaller than its numerator is worse than no denominator. Stays None
        # when Gmail offered none — a floor is not an estimate.
        result_size_estimate=None if estimate is None else max(estimate, scanned),
    )


async def _incremental_scan(
    user_id: uuid.UUID,
    *,
    start_history_id: str,
    target: int,
    mail_scope: str,
    classifier: Any,
    pipeline: Any,
    account_email: str | None = None,
) -> _ScanRead | None:
    """Read only what Gmail says changed since ``start_history_id``.

    ``None`` means "the cursor could not carry this run" — Gmail 404'd it as
    aged out (normal after ~a week), too much arrived to walk in one
    invocation, or the account is no longer connected. In every one of those
    cases the caller full-scans and re-baselines; none of them is a user-facing
    error.

    A usable delta is COMPLETE by construction: everything since the cursor, or
    nothing (a truncated walk falls back to the full scan rather than half-
    consuming the history). Gmail offers no ``resultSizeEstimate`` here, so the
    estimate stays ``None`` rather than being invented.
    """

    from jobtracker.cloud.gmail_client import fetch_history_messages

    page = await fetch_history_messages(
        user_id,
        start_history_id=start_history_id,
        max_messages=target,
        scope=mail_scope,  # type: ignore[arg-type]
    )
    if page is None or not page.usable:
        return None
    items = await _classify_messages(
        page.messages, classifier, pipeline, page.bodies, account_email
    )
    return _ScanRead(
        items=items,
        scanned=len(page.messages),
        unreadable=page.unreadable,
        stopped_by=STOPPED_COMPLETE,
    )


async def _history_cursor_for(
    user_id: uuid.UUID,
    payload: SyncRequest,
    *,
    rebuild: bool,
    account_email: str | None,
) -> str | None:
    """The stored ``historyId`` to sync from, or ``None`` to full-scan.

    Incremental is deliberately narrow. It is skipped when:

    - Gmail is not connected (no address to key the cursor row on);
    - ``mode="rebuild"`` — the explicit "Re-sync" button means *start clean*;
      handing its purge-and-rebuild a three-message delta would wipe every auto
      row whose company was not in that delta;
    - the caller named a ``range`` or ``count`` — they asked for a specific
      window, so scan it;
    - no cursor is stored yet (first sync, or a fresh reconnect).
    """

    if account_email is None or rebuild:
        return None
    if payload.range is not None or payload.count is not None:
        return None

    from jobtracker.cloud.sync_state import read_gmail_sync_state

    state = await read_gmail_sync_state(user_id, account_email)
    return state.gmail_history_id if state is not None else None


async def _scan_server_side(
    user_id: uuid.UUID,
    payload: SyncRequest,
    *,
    rebuild: bool,
    account_email: str | None,
) -> _ScanOutcome:
    """Fetch + classify the caller's mail, incrementally when we can."""

    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import pipeline
    from jobtracker.cloud.gmail_client import build_gmail_query, fetch_mailbox_history_id

    # Not-provided range → default backfill window; explicit "all" → no bound.
    range_months = (
        _SYNC_DEFAULT_RANGE_MONTHS
        if payload.range is None
        else _parse_range_months(payload.range)
    )
    # A scan that can REMOVE rows must be able to see everything it is judging,
    # so a rebuild always searches ``in:anywhere`` and the caller does not get a
    # say. ``_parse_scope`` defaults to ``in:inbox``, which does not search
    # archived mail: on 2026-08-10 that is why a rebuild found one job-related
    # message where the same account holds four, and deleted the two
    # applications whose ATS confirmations had been filed away. Honouring a
    # caller-supplied ``scope`` here would let a stale client, a cached form
    # value or a typo re-arm that. (The purge itself no longer trusts absence
    # either — see ``applications._scan_contradicts`` — but a destructive path
    # should not be reading half the mailbox in the first place.)
    mail_scope = "anywhere" if rebuild else _parse_scope(payload.scope)
    query = build_gmail_query(range_months, mail_scope)  # type: ignore[arg-type]
    target = max(
        1, min(payload.count or _SYNC_DEFAULT_SCAN_TARGET, settings.gmail_fetch_hard_cap)
    )
    classifier = get_classifier()

    # Capture the mailbox baseline BEFORE reading a single message. Taking it
    # afterwards would silently swallow everything that arrived while the scan
    # ran; taking it early only ever re-reads a message, which every write here
    # is idempotent against.
    history_id = await fetch_mailbox_history_id(user_id)
    if history_id is None:
        # ``fetch_mailbox_history_id`` degrades to None on ANY profile failure so
        # a bad read can never sink a sync. The cost is that a deployment where
        # getProfile fails persistently would full-scan forever while reporting
        # ``status='idle'`` — the original complaint, silently restored. Say so
        # out loud: no cursor can be written on this run.
        logger.warning(
            "Gmail baseline historyId unavailable for user_id=%s; this sync "
            "cannot advance the cursor and the next one will be a full scan.",
            user_id,
        )

    cursor = await _history_cursor_for(
        user_id, payload, rebuild=rebuild, account_email=account_email
    )
    if cursor:
        incremental = await _incremental_scan(
            user_id,
            start_history_id=cursor,
            target=target,
            mail_scope=mail_scope,
            classifier=classifier,
            pipeline=pipeline,
            account_email=account_email,
        )
        if incremental is not None:
            return _ScanOutcome(
                items=incremental.items,
                scanned=incremental.scanned,
                incremental=True,
                history_id=history_id,
                unreadable=incremental.unreadable,
                stopped_by=incremental.stopped_by,
                result_size_estimate=incremental.result_size_estimate,
            )
        logger.info(
            "Gmail history cursor unusable for user_id=%s; full scan + re-baseline.",
            user_id,
        )

    read = await _full_scan(
        user_id,
        query=query,
        target=target,
        classifier=classifier,
        pipeline=pipeline,
        account_email=account_email,
    )
    return _ScanOutcome(
        items=read.items,
        scanned=read.scanned,
        incremental=False,
        history_id=history_id,
        unreadable=read.unreadable,
        stopped_by=read.stopped_by,
        result_size_estimate=read.result_size_estimate,
    )


@router.post("/gmail/sync", response_model=SyncResponse)
async def gmail_sync(
    payload: SyncRequest,
    user_id: uuid.UUID = Depends(current_user),
) -> SyncResponse:
    """Persist the classified job-search pipeline into Application rows.

    This is what makes the dashboard show REAL data after connecting Gmail:
    the lifecycle mail (applied/interview/assessment/offer/rejection/…) is
    grouped into one application per company (furthest stage reached; rejection
    terminal) and idempotently upserted, scoped to the JWT's user.

    Input source (see :class:`SyncRequest`): persist the client's already-mined
    ``items``, or — when omitted — fetch server-side and classify. The
    server-side fetch is INCREMENTAL whenever a Gmail ``historyId`` cursor is on
    file (``users.history.list`` from the stored baseline), and falls back to the
    bounded, STABLE full window otherwise: first sync, a fresh reconnect, an
    aged-out (404) cursor, an explicit range/count, or the "Re-sync" rebuild.

    Every successful run records the caller's ``sync_state`` row —
    ``last_sync_at``, ``status`` and (server-fetch only) the mailbox baseline
    captured before the scan began. That row is what ``GET /auth/gmail/status``
    renders as "last synced …", and what stops the product from re-scanning a
    12-month window on every single visit.

    Persistence is ``additive`` by default (durable upsert-only) and only
    ``rebuild`` on the explicit "Re-sync" button — which must be a server-side
    scan, so ``items`` + ``mode="rebuild"`` is a 400. Either way the upsert is
    idempotent (re-running never duplicates) and metadata-only (no bodies are
    stored), and the orphan reconciliation runs on BOTH paths — including an
    incremental run that found nothing, so a stranded classification can never
    become unreachable just because the sync got cheaper.
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import (
        ScanCoverage,
        employers_with_several_applications,
        purge_and_rebuild_gmail_pipeline,
        sync_gmail_pipeline_additive,
        threads_naming_one_application,
    )
    from jobtracker.cloud.sync_state import (
        acquire_gmail_sync_lease,
        note_gmail_sync_failure,
        record_gmail_sync_success,
        release_gmail_sync_lease,
    )

    # Default to the durable additive merge; only an explicit "rebuild" (the
    # user's Re-sync button) may destructively purge. An unknown value is treated
    # as additive so a stray param can never trigger a data-wiping rebuild.
    mode = (payload.mode or "additive").strip().lower()
    rebuild = mode == "rebuild"

    # INVARIANT: a purge only ever comes from a SERVER-side scan with
    # ``scope="anywhere"``. Relayed ``items`` are additive-only, structurally.
    #
    # ``_scan_server_side`` forces ``in:anywhere`` for a rebuild precisely so a
    # scan that may REMOVE rows can see the archived mail it is judging. That
    # guard covers the server-fetch path and nothing else: a client that relays
    # its own ``items`` picked the window and the scope itself, and the purge
    # would then compute its coverage from a scan the server never made and
    # cannot characterise. A ``scope=inbox`` mine relayed as a rebuild is the
    # 2026-08-10 data loss with an extra step.
    #
    # Refused rather than silently coerced to additive: no shipped client sends
    # this combination, so nothing legitimate breaks, and a future "scan deeper"
    # button that got its wiring wrong must fail loudly in development instead
    # of reporting rebuild counts (``purged``, ``removed``) for a run that
    # quietly removed nothing.
    if rebuild and payload.items is not None:
        logger.warning(
            "Refused a client-relayed rebuild for user_id=%s (%s relayed items): "
            "purges may only come from a server-side anywhere-scope scan.",
            user_id,
            len(payload.items),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A rebuild cannot be run from relayed items. Only a server-side "
                "scan (which searches all mail, including archived) may remove "
                "applications. Send the items with mode='additive', or omit "
                "them and let the server scan."
            ),
        )

    # The linked address keys the cursor row. ``None`` means Gmail is not
    # connected — an items-only relay can still persist, there is just nothing to
    # key a cursor on.
    stored = await get_gmail_credentials(user_id)
    account_email = stored.email if stored else None

    # ONE sync per mailbox at a time. Nothing used to stop an authenticated
    # account firing unlimited parallel calls, each a 750-message scan, burning
    # function-seconds and the user's own Gmail quota while racing N copies of
    # the additive merge over the same rows.
    #
    # Keyed on the linked address because that is what the lease row is keyed
    # on. An items-only relay from a user with no Gmail connected has no
    # address to key on and takes no lease: it makes no Gmail calls, so the
    # cost it could multiply is not the one this guards.
    #
    # The lease EXPIRES (see ``_SYNC_LEASE_TTL_SECONDS``), so a sync killed by
    # the function ceiling cannot lock its owner out of their own mailbox.
    lease_held = False
    if account_email is not None:
        lease_held = await acquire_gmail_sync_lease(user_id, account_email)
        if not lease_held:
            raise SyncAlreadyRunning()

    try:
        if payload.items is not None:
            relayed = [
                pipeline.PipelineItem(
                    message_id=item.message_id,
                    category=item.category,
                    sender_email=item.sender_email,
                    subject=item.subject,
                    sender_name=item.sender_name,
                    received_at=_parse_iso(item.received_at),
                    confidence=item.confidence,
                    thread_id=item.thread_id,
                    snippet=item.snippet,
                )
                for item in payload.items[: settings.gmail_fetch_hard_cap]
            ]
            # WHAT THE CLIENT SAID IT READ, counted BEFORE the dedup below, so a
            # message relayed twice shows up as ``scanned > classified`` — the
            # same shape a server scan's sent-mail skip produces, and the reason
            # ``ScanLedger``'s partition closes over ``classified`` and not this.
            scanned = len(relayed)
            # ONE ITEM PER MESSAGE ID, FIRST OCCURRENCE WINS.
            #
            # ``SyncRequest.items`` has no uniqueness validator and the client
            # mine is a page loop, so one id arriving twice is reachable input,
            # not a hypothetical. Without this the SAME message could be routed
            # by two different categories and land in two buckets at once —
            # measured: a ``filed`` shape and a ``needs_review`` shape sharing
            # one id gave ``classified=1, filed=1, queued=1``, which does not
            # close, logged the overlap warning, and returned counts the
            # migration's docstring promises cannot happen.
            #
            # It was only ever a COUNTING defect — ``emails`` carries
            # ``UNIQUE ix_emails_user_id_message_id`` and ``_persist_message_refs``
            # upserts, so the second copy wrote nothing either way. Deduping
            # here rather than inside ``ledger_for_scan`` keeps the counters
            # derived from the routing outputs instead of correcting them after.
            #
            # FIRST OCCURRENCE, deliberately, and it is a real choice: two
            # copies under two categories would otherwise both be routed. Taking
            # the higher-confidence or later-ranked one would put a routing
            # PRECEDENCE rule in this handler, which is exactly the second
            # reader of a shape this module refuses to grow. A client that
            # relays one id under two categories has a bug; the sync answers it
            # with the copy it sent first, and says so in ``scanned``.
            by_message_id: dict[str, pipeline.PipelineItem] = {}
            for relayed_item in relayed:
                by_message_id.setdefault(relayed_item.message_id, relayed_item)
            items = list(by_message_id.values())
            incremental = False
            # The server did not read this mail and cannot characterise the
            # scan behind it: how far the client got, and what it lost getting
            # there, are the client's to report.
            unreadable = 0
            stopped_by = STOPPED_RELAY
            result_size_estimate: int | None = None
            # Deliberately no baseline: the client's mine can be a NARROWER
            # window than the server's own scan, so baselining from it would
            # permanently prevent the deeper full scan from ever running again.
            # The run still stamps ``last_sync_at``.
            history_id: str | None = None
        else:
            _require_configured()
            outcome = await _scan_server_side(
                user_id, payload, rebuild=rebuild, account_email=account_email
            )
            items = outcome.items
            scanned = outcome.scanned
            incremental = outcome.incremental
            history_id = outcome.history_id
            unreadable = outcome.unreadable
            stopped_by = outcome.stopped_by
            result_size_estimate = outcome.result_size_estimate

        # Roll the scan up: high-confidence lifecycle mail with a nameable
        # employer becomes a hard row, the uncertain remainder feeds the
        # needs-classification queue. How that merges into the board depends on
        # ``mode``: additive accumulates (durable, the default), rebuild REPLACES
        # (explicit Re-sync). Manual / user-corrected rows are preserved either
        # way. An empty incremental delta is NOT short-circuited — it still runs
        # the merge so reconciliation happens.
        from sqlalchemy import func as sa_func
        from sqlmodel import select as sm_select

        from jobtracker.database import get_session
        from jobtracker.database.models import Application

        async with get_session() as session:
            # WHAT THE BOARD ALREADY HOLDS. Rolling up needs it, so it is read
            # first and inside the session rather than before it. A delta is
            # usually one message, and from inside the pipeline an employer with
            # four cards and one role-less rejection in today's mail looks like
            # an employer with one — so that rejection was filed against
            # whichever card sorted first. Since a terminal status is final,
            # that freezes a live application against every later interview and
            # offer. With this, a delta routes it to the queue exactly as a
            # rebuild does.
            known_multi = await employers_with_several_applications(session, user_id)
            known_threads = await threads_naming_one_application(session, user_id)
            rolled = pipeline.roll_up_applications(items, known_multi, known_threads)
            dropped_verdicts: list[pipeline.DroppedVerdict] = []
            review = pipeline.collect_review_items(
                items, dropped_verdicts, known_multi, known_threads
            )
            if rebuild:
                # What this scan can honestly be said to have READ. The rebuild
                # may only remove a row this coverage contradicts; it is built
                # from ALL classified items (noise included) because a message
                # the scan re-read and no longer files IS the contradiction.
                merged = await purge_and_rebuild_gmail_pipeline(
                    session,
                    user_id,
                    rolled,
                    review,
                    ScanCoverage.from_items(items),
                )
            else:
                merged = await sync_gmail_pipeline_additive(
                    session, user_id, rolled, review
                )
            # WHERE EVERY MESSAGE THIS RUN LOOKED AT ENDED UP (#422). Built here
            # because here is the one place all three routing outputs exist at
            # once — and built from those outputs rather than from a second
            # reading of their conditions, so the counts cannot drift from the
            # routing the way a mirrored implementation would.
            #
            # AFTER the merge, deliberately. The partition describes the SCAN,
            # not the merge, and every field of it is already fixed by this
            # point; computing it earlier would work and would put an
            # observability calculation in front of the write that matters.
            ledger = pipeline.ledger_for_scan(items, rolled, review, dropped_verdicts)
            created = merged.created
            updated = merged.updated
            purged = merged.purged
            needs_review = merged.needs_review

            # Cursor LAST, after the scanned mail is durably persisted. The
            # merge functions commit internally, so this cannot be one atomic
            # unit with them — but the ordering gives the property that matters:
            # the only way to fail is with the cursor NOT advanced, which costs
            # one more full scan and can never skip a message.
            #
            # …and, ON AN INCREMENTAL DELTA, only when the run READ EVERYTHING
            # IT LISTED. ``unreadable`` counts ids Gmail named and whose batched
            # metadata get came back empty — a dropped sub-request, which
            # ``_batch_fetch_metadata`` logs and walks past so one bad message
            # cannot sink a page. The page is still ``usable`` (not expired, not
            # truncated), so the delta is returned and the baseline captured
            # BEFORE the run gets written. That baseline is newer than the
            # message that was lost, so every later delta starts after it and no
            # incremental sync can ever name it again — the message is skipped
            # from the middle of a window the scan did cover, which is issue
            # #166's exact shape.
            #
            # Holding the cursor costs one repeated delta (the same mail, and
            # every write on this path is idempotent); advancing it costs the
            # message. Gmail keeps ~a week of history, so a failure that keeps
            # repeating eventually 404s the cursor and re-baselines through a
            # full scan — bounded, and still never silent.
            #
            # Scoped to ``incremental`` because HOLDING only does anything
            # there. The hold preserves a STORED cursor, and preserving it is
            # what re-covers the lost message on the next delta. A full scan may
            # have no stored cursor at all — ``history_id=None`` preserves what
            # is stored, and preserving nothing records nothing — so an account
            # whose FIRST scan lost a message would never establish a cursor and
            # would full-scan on every sync forever (issue #180), which is
            # exactly the outcome the next paragraph declines to accept for a
            # different reason.
            #
            # Recording here is NOT free, and is not claimed to be: the baseline
            # is newer than the id the scan could not read, so once it lands, no
            # later delta can name that id either. What differs from the
            # incremental case is the alternative. Holding loses the same
            # message anyway — the next sync full-scans the same window and
            # fails on the same id for the same reason — and loses the cursor
            # with it. Recording keeps the cursor, and leaves the id reachable
            # by the paths that re-list from the top: an explicit Re-sync, or a
            # ``range``/``count`` request. Either way it is logged, below.
            #
            # Both full-scan routes get this and want it: the first sync of a
            # fresh account, and the re-baseline below a cursor Gmail would no
            # longer answer. ``incremental`` is True only inside ``if cursor:``
            # and only after ``_incremental_scan`` returned a usable page, so a
            # re-baseline arrives here as a full scan and records — which is the
            # whole point of having run it.
            #
            # Deliberately NOT extended to ``stopped_by != STOPPED_COMPLETE``. A
            # full scan that stops on its message target has not covered its
            # window either, but holding the cursor there would pin a large
            # mailbox into full-scanning forever without ever reaching further
            # back — a real defect with a real trade-off, and a different one.
            if account_email is not None:
                cursor_to_record = history_id
                if stopped_by == STOPPED_RATE_LIMITED and scanned == 0:
                    # A rate-limited run that read NOTHING is the one case that
                    # must not advance the baseline. The reasoning three
                    # paragraphs up — "holding loses the same message anyway,
                    # the next sync fails on the same id for the same reason" —
                    # is true for a DEADLINE and false here: a rate limit is
                    # transient by construction, so the next run reads exactly
                    # what this one could not. Recording a baseline captured
                    # before a scan that read zero messages would put every one
                    # of them permanently beyond the cursor.
                    cursor_to_record = None
                    logger.warning(
                        "Gmail sync for user_id=%s was rate-limited before it "
                        "read anything; holding the history cursor so the next "
                        "run covers the same window.",
                        user_id,
                    )
                elif incremental and history_id is not None and unreadable > 0:
                    cursor_to_record = None
                    logger.warning(
                        "Gmail sync for user_id=%s could not read %s message(s) "
                        "it listed; holding the history cursor so the next run "
                        "re-covers them instead of stepping past them.",
                        user_id,
                        unreadable,
                    )
                elif unreadable > 0 and cursor_to_record is not None:
                    # The full-scan branch: the baseline lands even though the
                    # run did not read everything it listed, which does put
                    # those ids beyond every later delta — see above for why
                    # that still beats never holding a cursor. Not silently.
                    logger.info(
                        "Gmail full scan for user_id=%s could not read %s "
                        "message(s) it listed; recording the baseline anyway "
                        "rather than pinning the account to full-scanning. "
                        "Those ids are now past the cursor; a Re-sync re-lists "
                        "them.",
                        user_id,
                        unreadable,
                    )
                await record_gmail_sync_success(
                    session,
                    user_id,
                    account_email=account_email,
                    history_id=cursor_to_record,
                    # The durable half of #422. A response answers "did you see
                    # my mail?" only for as long as the tab is open; the person
                    # diagnosing the report reads Postgres days later, which is
                    # where the answer was missing entirely.
                    #
                    # ``scanned`` is passed separately because the pipeline
                    # cannot know it: it counts what Gmail handed back, and
                    # ``_classify_messages`` skips the user's own sent mail
                    # before an item exists.
                    #
                    # ONLY REACHED WHEN ``account_email`` IS SET, which is the
                    # one gap and it is stated rather than hidden: an
                    # items-relay from a user with no Gmail connected has no row
                    # to key on and gets the response's numbers only. That is
                    # the same limit ``last_sync_at`` has had since this row
                    # existed, not a new one.
                    ledger=ledger,
                    scanned=scanned,
                )
                await session.commit()

            # LIVE rows only — a dismissed row is off the board, so counting it
            # here would make the dashboard's total disagree with the list.
            total = (
                await session.exec(
                    sm_select(sa_func.count())
                    .select_from(Application)
                    .where(
                        Application.user_id == user_id,
                        Application.dismissed_at.is_(None),
                    )
                )
            ).one()
    except HTTPException:
        # 409 not-connected / 429 already-running / 503 not-configured are the
        # caller's problem to fix, not a sync failure worth recording against
        # the mailbox.
        raise
    except Exception as exc:
        if account_email is not None:
            # Type name only — this module never puts a token-bearing repr into
            # a log or a stored field.
            await note_gmail_sync_failure(user_id, account_email, type(exc).__name__)
        raise
    finally:
        # EVERY exit, including the ``HTTPException`` re-raise above — which
        # records no failure and would otherwise hold the lease for a full TTL
        # after a 400 the user could fix and retry in seconds.
        if lease_held:
            await release_gmail_sync_lease(user_id, account_email)

    logger.info(
        "Gmail sync for user_id=%s: mode=%s incremental=%s created=%s updated=%s "
        "purged=%s needs_review=%s total=%s scanned=%s unreadable=%s stopped_by=%s "
        "estimate=%s classified=%s filed=%s queued=%s dropped=%s "
        "reached_nothing=%s removed_application_id=%s",
        user_id,
        mode,
        incremental,
        created,
        updated,
        purged,
        needs_review,
        total,
        scanned,
        unreadable,
        stopped_by,
        result_size_estimate,
        # The partition, on the one surface a deployment always has. It closes
        # against ``classified`` — see ``pipeline.ScanLedger`` — so a line where
        # it does not is itself the finding.
        ledger.classified,
        ledger.filed,
        ledger.queued,
        ledger.dropped,
        ledger.reached_nothing,
        # Ids, not company names: this record already carries ``user_id``, and
        # a company name beside it says where the user applied (see
        # ``_warn_if_capped`` in cloud/applications.py). The ids name the same
        # rows and answer the same question against the database.
        [r.id for r in merged.removed] or None,
    )
    return SyncResponse(
        created=created,
        updated=updated,
        applications=total,
        scanned=scanned,
        unreadable=unreadable,
        stopped_by=stopped_by,
        result_size_estimate=result_size_estimate,
        purged=purged,
        needs_review=needs_review,
        removed=[
            RemovedApplicationOut(id=r.id, company=r.company) for r in merged.removed
        ],
        # ONE ledger fills all five, ``dropped`` included — it used to be
        # ``len(dropped_verdicts)`` here and is now read off the same object the
        # stored row is written from, so the response and ``sync_state`` are
        # structurally incapable of reporting different numbers.
        dropped=ledger.dropped,
        classified=ledger.classified,
        filed=ledger.filed,
        queued=ledger.queued,
        reached_nothing=ledger.reached_nothing,
    )
