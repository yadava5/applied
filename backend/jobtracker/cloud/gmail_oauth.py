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
from datetime import UTC, datetime, timedelta

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
    """Whether the deployment can offer Gmail, and whether this user linked it."""

    configured: bool
    connected: bool
    email: str | None = None


class GmailAuthorizeResponse(BaseModel):
    """The Google consent URL the browser should be sent to."""

    authorization_url: str


class GmailDisconnectResponse(BaseModel):
    revoked: bool
    message: str


class InboxVerdict(BaseModel):
    """One classifier verdict for one recent message. No body is included."""

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
    # follow-up detection, per-company rollup). Never any body content.
    received_at: str | None = None
    company: str = ""


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
      preserved.
    """

    items: list[PipelineItemIn] | None = None
    count: int | None = None
    range: str | None = None
    scope: str | None = None
    mode: str | None = None


class SyncResponse(BaseModel):
    created: int
    updated: int
    applications: int  # total application rows the user has after the sync
    scanned: int
    # Stale AUTO rows removed by the rebuild (the "garbage gone" number) and how
    # many uncertain verdicts are waiting in the needs-classification queue.
    purged: int = 0
    needs_review: int = 0


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
    """Report whether Gmail is available and whether this user has connected.

    Always 200 so the web UI can render an honest state (including "not yet
    configured by the operator") without treating it as an error.
    """

    if not settings.gmail_oauth_configured:
        return GmailStatusResponse(configured=False, connected=False)

    stored = await get_gmail_credentials(user_id)
    return GmailStatusResponse(
        configured=True,
        connected=stored is not None,
        email=stored.email if stored else None,
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
    """Revoke the grant at Google and delete the stored (encrypted) token."""

    stored = await get_gmail_credentials(user_id)
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

    Bodies are never returned — only verdict metadata. The per-user, per-page
    short-TTL cache + ``ETag``/``If-None-Match`` are unchanged; auth is verified
    on every request before the cache is consulted.
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

# A server-side auto sync scans a STABLE, deep-enough slice of that window:
# up to this many messages across at most this many bounded pages. Fixed so
# every routine run covers the same ground (durability no longer depends on
# which messages a single 500-cap page happened to catch) while staying inside
# the serverless time budget.
_SYNC_DEFAULT_SCAN_TARGET = 750
_SYNC_MAX_PAGES = 4


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
    ``items``, or — when omitted — fetch a bounded, STABLE recent window
    server-side and classify it. Persistence is ``additive`` by default (durable
    upsert-only) and only ``rebuild`` on the explicit "Re-sync" button. Either
    way the upsert is idempotent (re-running never duplicates) and metadata-only
    (no bodies are stored).
    """

    from jobtracker.cloud import pipeline
    from jobtracker.cloud.applications import (
        purge_and_rebuild_gmail_pipeline,
        sync_gmail_pipeline_additive,
    )

    # Default to the durable additive merge; only an explicit "rebuild" (the
    # user's Re-sync button) may destructively purge. An unknown value is treated
    # as additive so a stray param can never trigger a data-wiping rebuild.
    mode = (payload.mode or "additive").strip().lower()
    rebuild = mode == "rebuild"

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
    else:
        _require_configured()
        from jobtracker.classifier import get_classifier
        from jobtracker.cloud.gmail_client import build_gmail_query, fetch_message_page

        # Not-provided range → default backfill window; explicit "all" → no bound.
        range_months = (
            _SYNC_DEFAULT_RANGE_MONTHS
            if payload.range is None
            else _parse_range_months(payload.range)
        )
        mail_scope = _parse_scope(payload.scope)
        query = build_gmail_query(range_months, mail_scope)  # type: ignore[arg-type]

        # Scan a fixed, deep-enough target across bounded pages so a routine
        # auto-sync reliably finds the user's whole recent pipeline and every run
        # covers the same ground — no longer leaving durability to whichever
        # messages one 500-cap page happened to catch.
        target = max(
            1, min(payload.count or _SYNC_DEFAULT_SCAN_TARGET, settings.gmail_fetch_hard_cap)
        )

        classifier = get_classifier()
        items = []
        scanned = 0
        page_token: str | None = None
        for page_index in range(_SYNC_MAX_PAGES):
            remaining = target - scanned
            if remaining <= 0:
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
                break
            for msg in page.messages:
                result = await classifier.classify(
                    msg.subject, msg.snippet, msg.sender_email
                )
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
            scanned += len(page.messages)
            page_token = page.next_page_token
            if not page_token or not page.messages:
                break

    # Roll the scan up: high-confidence lifecycle mail with a nameable employer
    # becomes a hard row, the uncertain remainder feeds the needs-classification
    # queue. How that merges into the board depends on ``mode``: additive
    # accumulates (durable, the default), rebuild REPLACES (explicit Re-sync).
    # Manual / user-corrected rows are preserved either way.
    rolled = pipeline.roll_up_applications(items)
    review = pipeline.collect_review_items(items)

    from sqlalchemy import func as sa_func
    from sqlmodel import select as sm_select

    from jobtracker.database import get_session
    from jobtracker.database.models import Application

    async with get_session() as session:
        if rebuild:
            created, updated, purged, needs_review = await purge_and_rebuild_gmail_pipeline(
                session, user_id, rolled, review
            )
        else:
            created, updated, purged, needs_review = await sync_gmail_pipeline_additive(
                session, user_id, rolled, review
            )
        total = (
            await session.exec(
                sm_select(sa_func.count())
                .select_from(Application)
                .where(Application.user_id == user_id)
            )
        ).one()

    logger.info(
        "Gmail sync for user_id=%s: mode=%s created=%s updated=%s purged=%s "
        "needs_review=%s total=%s scanned=%s",
        user_id,
        mode,
        created,
        updated,
        purged,
        needs_review,
        total,
        scanned,
    )
    return SyncResponse(
        created=created,
        updated=updated,
        applications=total,
        scanned=scanned,
        purged=purged,
        needs_review=needs_review,
    )
