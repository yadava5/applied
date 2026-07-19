"""Cloud-safe Gmail *read* client (issue C5).

This is the cloud twin of ``jobtracker.email_clients.gmail.GmailClient``.
The desktop client cannot run on Vercel: it uses ``run_local_server`` (a
desktop consent flow) and the macOS-Keychain credential backend, whose
module (``jobtracker.credentials.desktop``) imports ``keyring``. Pulling
that into the serverless import graph would break the deploy and the
import-hygiene test in ``tests/test_main_cloud.py``.

So this module deliberately:

- reads/writes tokens **only** through ``jobtracker.credentials.cloud``
  (Fernet-encrypted Postgres rows, keyed by ``user_id``);
- builds a ``google.oauth2.credentials.Credentials`` from the stored
  token + the operator-supplied web client id/secret, refreshing (and
  re-persisting) the access token when it has expired;
- fetches a small, bounded batch of recent messages with ``format=
  "metadata"`` — Subject/From/Date headers plus Gmail's own ``snippet``.
  We never download full bodies in the cloud path: the snippet is enough
  signal for the rules classifier, keeps each serverless call fast, and
  is the more privacy-preserving default (less content leaves Gmail).

Scope stays least-privilege ``gmail.readonly`` throughout. Tokens are
never logged and never returned to callers of the HTTP layer.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from jobtracker.config import settings
from jobtracker.credentials.cloud import (
    get_gmail_credentials,
    update_gmail_access_token,
)
from jobtracker.credentials.types import GmailCredentials

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Only fetch messages that plausibly belong to a job search. This mirrors
# the desktop default of scanning inbox mail but keeps the cloud read
# cheap; the classifier does the real filtering.
DEFAULT_QUERY = "in:inbox"


@dataclass
class CloudGmailMessage:
    """A single Gmail message reduced to the fields classification needs."""

    message_id: str
    thread_id: str
    subject: str
    sender_name: Optional[str]
    sender_email: str
    snippet: str
    received_at: Optional[datetime]


def _google_credentials_from_stored(stored: GmailCredentials) -> Credentials:
    """Build a google-auth ``Credentials`` from an encrypted stored token.

    The client id/secret come from settings (operator env), never from the
    stored blob — so a leaked DB row alone cannot mint new access tokens.
    """

    return Credentials(
        token=stored.access_token,
        refresh_token=stored.refresh_token or None,
        token_uri=_TOKEN_URI,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=list(stored.scopes or settings.gmail_scopes),
    )


async def load_valid_credentials(user_id: uuid.UUID) -> Optional[Credentials]:
    """Return refreshed, ready-to-use google credentials for ``user_id``.

    Returns ``None`` when the user has not connected Gmail. Refreshes the
    access token when it is within the expiry buffer and persists the new
    token (encrypted) so subsequent invocations reuse it. Refresh failures
    (e.g. a revoked grant) are logged without the token value and surfaced
    as ``None`` so the caller degrades to "reconnect required".
    """

    stored = await get_gmail_credentials(user_id)
    if stored is None:
        return None

    creds = _google_credentials_from_stored(stored)

    if stored.is_expired():
        if not stored.refresh_token:
            logger.warning(
                "Gmail token expired and no refresh_token on file for user_id=%s; "
                "user must reconnect.",
                user_id,
            )
            return None
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: creds.refresh(Request()))
        except Exception as exc:  # noqa: BLE001 — google refresh raises broadly
            # Never log the exception's token-bearing repr; log its type only.
            logger.error(
                "Gmail token refresh failed for user_id=%s (%s); reconnect required.",
                user_id,
                type(exc).__name__,
            )
            return None

        await update_gmail_access_token(
            user_id,
            access_token=creds.token,
            token_expiry=creds.expiry or (datetime.utcnow() + timedelta(hours=1)),
        )

    return creds


async def fetch_recent_messages(
    user_id: uuid.UUID,
    *,
    max_results: Optional[int] = None,
    query: str = DEFAULT_QUERY,
) -> Optional[list[CloudGmailMessage]]:
    """Fetch a bounded batch of recent messages for ``user_id``.

    Returns ``None`` when Gmail is not connected (so the router can answer
    409). Returns a possibly-empty list otherwise. Read-only: uses
    ``messages.list`` + ``messages.get(format="metadata")`` — no body
    download, no mutation.
    """

    creds = await load_valid_credentials(user_id)
    if creds is None:
        return None

    limit = max_results or settings.gmail_fetch_max_results
    loop = asyncio.get_event_loop()

    def _run() -> list[CloudGmailMessage]:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        listing = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit)
            .execute()
        )
        refs = listing.get("messages", []) or []
        out: list[CloudGmailMessage] = []
        for ref in refs[:limit]:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=ref["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                )
                .execute()
            )
            parsed = _parse_metadata_message(msg)
            if parsed is not None:
                out.append(parsed)
        return out

    return await loop.run_in_executor(None, _run)


def _parse_metadata_message(raw: dict) -> Optional[CloudGmailMessage]:
    """Parse a ``format=metadata`` Gmail response into a CloudGmailMessage."""

    try:
        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }
        sender_name, sender_email = parseaddr(headers.get("from", ""))
        received_at: Optional[datetime]
        try:
            received_at = parsedate_to_datetime(headers.get("date", ""))
        except (TypeError, ValueError):
            received_at = None
        return CloudGmailMessage(
            message_id=raw.get("id", ""),
            thread_id=raw.get("threadId", ""),
            subject=headers.get("subject", "(No Subject)"),
            sender_name=sender_name or None,
            sender_email=sender_email,
            snippet=raw.get("snippet", "") or "",
            received_at=received_at,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse Gmail metadata message: %s", type(exc).__name__)
        return None
