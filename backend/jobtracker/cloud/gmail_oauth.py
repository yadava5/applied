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
- **No open redirect**: the post-callback destination is the operator-
  configured ``web_app_url``, never a value taken from the request.
- **Revocable**: disconnect calls Google's revocation endpoint and then
  deletes the local ciphertext.
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
from pydantic import BaseModel

from jobtracker.auth import current_user
from jobtracker.config import settings
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
    """

    message_id: str
    category: str
    sender_email: str = ""
    subject: str = ""
    sender_name: str | None = None
    received_at: str | None = None  # ISO-8601
    confidence: float = 0.0
    thread_id: str | None = None
    snippet: str = ""


class PipelineAnalyzeRequest(BaseModel):
    items: list[PipelineItemIn]
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

    items: list[PipelineItemIn] | None = None
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


# =============================================================================
# Per-user inbox cache (short TTL, in-process)
# =============================================================================
#
# ``GET /gmail/inbox`` is expensive: it lists + fetches metadata for up to
# ``gmail_fetch_max_results`` messages from Gmail and runs each through the
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


def _sign_state(user_id: uuid.UUID, code_verifier: str) -> str:
    """Return an HS256-signed state binding the flow to ``user_id``.

    The PKCE ``code_verifier`` rides along in the ``cv`` claim,
    Fernet-encrypted with ``settings.secret_encryption_key``: the signed
    JWT makes it tamper-proof and expiring, the encryption keeps it
    secret from everything the state transits (browser history, Google,
    proxy/URL logs). Only this backend can decrypt it in the callback —
    which is what makes PKCE work across two serverless invocations.
    """

    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "aud": _STATE_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=settings.gmail_oauth_state_ttl_seconds),
        "jti": secrets.token_urlsafe(16),
        "cv": _require_fernet().encrypt(code_verifier.encode("utf-8")).decode("ascii"),
    }
    return jwt.encode(payload, settings.secret_encryption_key, algorithm="HS256")


def _verify_state(token: str) -> tuple[uuid.UUID, str] | None:
    """Return ``(user_id, code_verifier)`` for a valid state, else ``None``.

    A state without a decryptable ``cv`` claim (forged, expired key, or
    minted by a pre-PKCE deploy) is treated as invalid — the callback
    bounces back with ``?gmail=error`` and the user simply reconnects.
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
        return user_id, code_verifier
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


def _web_redirect(outcome: str) -> RedirectResponse:
    """Redirect the browser back to the web app's settings page.

    ``outcome`` is a coarse, non-sensitive status token (``connected`` /
    ``error``); no token or email ever rides in the URL.
    """

    base = (settings.web_app_url or "").rstrip("/")
    target = f"{base}/settings?gmail={urllib.parse.quote(outcome)}"
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

    stored = await get_gmail_credentials(user_id)
    if stored is None:
        return GmailStatusResponse(configured=True, connected=False)

    from jobtracker.cloud.sync_state import read_gmail_sync_state

    state = await read_gmail_sync_state(user_id, stored.email)
    return GmailStatusResponse(
        configured=True,
        connected=True,
        email=stored.email,
        last_sync_at=_iso_utc(state.last_sync_at if state is not None else None),
        has_cursor=bool(state is not None and state.gmail_history_id),
        sync_status=state.status if state is not None else None,
        sync_error=state.error_message if state is not None else None,
    )


@router.get("/auth/gmail/authorize", response_model=GmailAuthorizeResponse)
async def gmail_authorize(
    user_id: uuid.UUID = Depends(current_user),
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
    """

    _require_configured()

    code_verifier = _generate_code_verifier()
    flow = _build_flow(code_verifier=code_verifier)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=_sign_state(user_id, code_verifier),
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
        logger.warning("Gmail callback rejected: invalid or expired state.")
        return _web_redirect("error")
    user_id, code_verifier = verified

    try:
        stored = await _exchange_and_store(user_id, code, code_verifier)
    except Exception as exc:  # noqa: BLE001 — never leak the token-bearing error
        logger.error(
            "Gmail token exchange failed for user_id=%s (%s).",
            user_id,
            type(exc).__name__,
        )
        return _web_redirect("error")

    logger.info("Gmail connected for user_id=%s (%s).", user_id, stored.email)
    return _web_redirect("connected")


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

    stored = await get_gmail_credentials(user_id)
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

    A single invocation fetches at most ``gmail_fetch_page_size`` messages
    (batched metadata gets, no bodies) so it stays inside the Vercel function
    budget; big mines are many bounded pages, not one fragile mega-call.

    Full bodies are never fetched or returned. Each verdict carries the Gmail
    ``snippet`` the classification was made from plus a deep link to the
    message, which is what makes a scan row judgeable at all. The per-user,
    per-page short-TTL cache + ``ETag``/``If-None-Match`` are unchanged; auth is
    verified on every request before the cache is consulted.
    """

    _require_configured()

    # Imported lazily so the classifier + Gmail client stay out of the cold-
    # start path for the OAuth endpoints (matches hybrid.py's cloud discipline).
    from jobtracker.classifier import get_classifier
    from jobtracker.cloud import pipeline
    from jobtracker.cloud.gmail_client import build_gmail_query, fetch_message_page

    range_months = _parse_range_months(range)
    mail_scope = _parse_scope(scope)
    query = build_gmail_query(range_months, mail_scope)  # type: ignore[arg-type]

    # How many this page pulls: the configured per-invocation ceiling, further
    # clamped by an explicit page_size, the total count target, and the hard cap.
    configured_page = max(1, min(settings.gmail_fetch_page_size, 500))
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

    page = await fetch_message_page(
        user_id, query=query, page_size=effective_page, page_token=page_token
    )
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
        result = await classifier.classify(msg.subject, msg.snippet, msg.sender_email)
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
            "Classified from subject + Gmail snippet using the rules-only cloud "
            "classifier (gmail.readonly). Full-body + SetFit classification runs "
            "in the desktop app."
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
_SYNC_DEFAULT_SCAN_TARGET = 750

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


async def _classify_messages(messages: list[Any], classifier: Any, pipeline: Any) -> list[Any]:
    """Run each fetched message through the classifier into a PipelineItem."""

    items: list[Any] = []
    for msg in messages:
        result = await classifier.classify(msg.subject, msg.snippet, msg.sender_email)
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

    from jobtracker.cloud.gmail_client import fetch_message_page

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
        page = await fetch_message_page(
            user_id,
            query=query,
            page_size=min(settings.gmail_fetch_page_size, remaining),
            page_token=page_token,
        )
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
        items.extend(await _classify_messages(page.messages, classifier, pipeline))
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
    items = await _classify_messages(page.messages, classifier, pipeline)
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
        purge_and_rebuild_gmail_pipeline,
        sync_gmail_pipeline_additive,
    )
    from jobtracker.cloud.sync_state import (
        note_gmail_sync_failure,
        record_gmail_sync_success,
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

    try:
        if payload.items is not None:
            items = [
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
            scanned = len(items)
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
        rolled = pipeline.roll_up_applications(items)
        review = pipeline.collect_review_items(items)

        from sqlalchemy import func as sa_func
        from sqlmodel import select as sm_select

        from jobtracker.database import get_session
        from jobtracker.database.models import Application

        async with get_session() as session:
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
                if incremental and history_id is not None and unreadable > 0:
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
        # 409 not-connected / 503 not-configured are the caller's problem to
        # fix, not a sync failure worth recording against the mailbox.
        raise
    except Exception as exc:
        if account_email is not None:
            # Type name only — this module never puts a token-bearing repr into
            # a log or a stored field.
            await note_gmail_sync_failure(user_id, account_email, type(exc).__name__)
        raise

    logger.info(
        "Gmail sync for user_id=%s: mode=%s incremental=%s created=%s updated=%s "
        "purged=%s needs_review=%s total=%s scanned=%s unreadable=%s stopped_by=%s "
        "estimate=%s removed=%s",
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
        [r.company for r in merged.removed] or None,
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
    )
