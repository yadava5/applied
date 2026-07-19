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
- **No open redirect**: the post-callback destination is the operator-
  configured ``web_app_url``, never a value taken from the request.
- **Revocable**: disconnect calls Google's revocation endpoint and then
  deletes the local ciphertext.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from pydantic import BaseModel

from jobtracker.auth import current_user
from jobtracker.config import settings
from jobtracker.credentials.cloud import (
    delete_gmail_credentials,
    get_gmail_credentials,
    save_gmail_credentials,
)
from jobtracker.credentials.types import GmailCredentials

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
    email: Optional[str] = None


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
    sender_name: Optional[str] = None
    category: str
    confidence: float
    method: str
    needs_review: bool


class InboxResponse(BaseModel):
    connected: bool
    scanned: int
    verdicts: list[InboxVerdict]
    note: str


# =============================================================================
# OAuth state (signed, short-lived, user-bound)
# =============================================================================


def _sign_state(user_id: uuid.UUID) -> str:
    """Return an HS256-signed state token binding the flow to ``user_id``."""

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "aud": _STATE_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=settings.gmail_oauth_state_ttl_seconds),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.secret_encryption_key, algorithm="HS256")


def _verify_state(token: str) -> Optional[uuid.UUID]:
    """Return the bound ``user_id`` if ``token`` is a valid state, else None."""

    try:
        payload = jwt.decode(
            token,
            settings.secret_encryption_key,
            algorithms=["HS256"],
            audience=_STATE_AUDIENCE,
            options={"require": ["exp", "sub", "aud"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None


# =============================================================================
# Google flow helpers
# =============================================================================


def _build_flow() -> Flow:
    """Construct a google-auth-oauthlib web ``Flow`` from operator settings."""

    client_config = {
        "web": {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [settings.gmail_oauth_redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=settings.gmail_scopes)
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Gmail OAuth is not configured on this deployment. The operator "
                "must set the Google client id/secret, redirect URI, web app URL, "
                "and encryption key."
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
    """

    _require_configured()

    flow = _build_flow()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=_sign_state(user_id),
    )
    return GmailAuthorizeResponse(authorization_url=authorization_url)


@router.get("/auth/gmail/callback", include_in_schema=False)
async def gmail_callback(
    state: Optional[str] = Query(default=None),
    code: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
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

    user_id = _verify_state(state)
    if user_id is None:
        logger.warning("Gmail callback rejected: invalid or expired state.")
        return _web_redirect("error")

    try:
        stored = await _exchange_and_store(user_id, code)
    except Exception as exc:  # noqa: BLE001 — never leak the token-bearing error
        logger.error(
            "Gmail token exchange failed for user_id=%s (%s).",
            user_id,
            type(exc).__name__,
        )
        return _web_redirect("error")

    logger.info("Gmail connected for user_id=%s (%s).", user_id, stored.email)
    return _web_redirect("connected")


async def _exchange_and_store(user_id: uuid.UUID, code: str) -> GmailCredentials:
    """Exchange ``code`` for tokens, read the account email, and persist."""

    loop = asyncio.get_event_loop()

    def _exchange() -> GmailCredentials:
        flow = _build_flow()
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

    stored = await loop.run_in_executor(None, _exchange)
    await save_gmail_credentials(user_id, stored)
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


@router.get("/gmail/inbox", response_model=InboxResponse)
async def gmail_inbox(
    user_id: uuid.UUID = Depends(current_user),
) -> InboxResponse:
    """Read a bounded batch of recent mail and classify each message.

    This is the honest end of the pipeline: real messages from the user's
    Gmail, one verdict each from the rules-only cloud classifier. Bodies are
    never returned — only the verdict metadata the tracker needs.
    """

    _require_configured()

    # Imported lazily so the classifier package stays out of the cold-start
    # path for the OAuth endpoints (matches hybrid.py's cloud discipline).
    from jobtracker.classifier import get_classifier
    from jobtracker.cloud.gmail_client import fetch_recent_messages

    messages = await fetch_recent_messages(user_id)
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail is not connected for this user. Connect it first.",
        )

    classifier = get_classifier()
    verdicts: list[InboxVerdict] = []
    for msg in messages:
        result = await classifier.classify(msg.subject, msg.snippet, msg.sender_email)
        verdicts.append(
            InboxVerdict(
                message_id=msg.message_id,
                subject=msg.subject,
                sender_email=msg.sender_email,
                sender_name=msg.sender_name,
                category=result.category.value,
                confidence=round(result.confidence, 4),
                method=result.method,
                needs_review=result.needs_review,
            )
        )

    return InboxResponse(
        connected=True,
        scanned=len(messages),
        verdicts=verdicts,
        note=(
            "Classified from subject + Gmail snippet using the rules-only cloud "
            "classifier (gmail.readonly). Full-body + SetFit classification runs "
            "in the desktop app."
        ),
    )
