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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Literal, Optional

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

# Gmail's own ceiling on ``messages.list`` maxResults per page.
_GMAIL_LIST_PAGE_MAX = 500

# Where to look for mail. ``inbox`` is least-surprising; ``anywhere`` also
# searches archived / other-tab / all-mail so interview & offer emails that
# were filed away (the #1 "lost invite" pain point) are still found.
MailScope = Literal["inbox", "anywhere"]


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


@dataclass
class MessagePage:
    """One server-side page of fetched messages plus the cursor to continue.

    ``next_page_token`` is Gmail's own opaque continuation token: ``None`` when
    the query is exhausted. ``list_pages_walked`` is the number of
    ``messages.list`` calls this page made (always 1 with the default
    page-size = list-ceiling alignment) — surfaced for observability/tests.
    """

    messages: list[CloudGmailMessage]
    next_page_token: Optional[str]
    list_pages_walked: int = 1


def build_gmail_query(
    range_months: Optional[int] = None,
    scope: MailScope = "inbox",
) -> str:
    """Compose a Gmail search query from the UI's range + scope filters.

    - ``scope="inbox"`` → base ``in:inbox``; ``scope="anywhere"`` → ``in:anywhere``
      (includes archived / all-mail so filed-away interview & offer mail is found).
    - ``range_months`` adds Gmail's ``newer_than:<N>m`` age filter; ``None`` /
      non-positive means "all time" (no age bound).

    Gmail's query grammar is space-separated AND terms, so we just join the
    base scope with the optional age term.
    """

    base = "in:anywhere" if scope == "anywhere" else "in:inbox"
    if range_months and range_months > 0:
        return f"{base} newer_than:{int(range_months)}m"
    return base


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


def _batch_fetch_metadata(
    service: Any,
    ids: list[str],
    *,
    batch_size: int,
    pause_seconds: float,
) -> dict[str, dict]:
    """Fetch Subject/From/Date + snippet for ``ids`` via Gmail batch requests.

    Instead of one ``messages.get`` round-trip per id (which turns a 1000-id
    page into 1000 serial HTTP calls and a serverless timeout), we group the
    gets into ``new_batch_http_request`` batches of at most ``batch_size``
    (Gmail caps a batch at 100). Each 100-message metadata batch costs ~500
    quota units, so we sleep ``pause_seconds`` between batches to stay under
    the per-user ~250 units/sec limit.

    Returns a ``{message_id: raw_metadata_response}`` map. Individual failed
    sub-requests are dropped (logged by type only), never raised — one bad
    message must not sink the whole page.
    """

    results: dict[str, dict] = {}

    def _on_result(request_id: str, response: Any, exception: Any) -> None:
        if exception is not None:
            logger.warning(
                "Gmail metadata sub-request failed: %s", type(exception).__name__
            )
            return
        if response is not None:
            results[request_id] = response

    chunk = max(1, min(batch_size, 100))
    for start in range(0, len(ids), chunk):
        window = ids[start : start + chunk]
        batch = service.new_batch_http_request(callback=_on_result)
        for message_id in window:
            batch.add(
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ),
                request_id=message_id,
            )
        batch.execute()
        if pause_seconds and (start + chunk) < len(ids):
            time.sleep(pause_seconds)

    return results


def _collect_page(
    service: Any,
    *,
    query: str,
    page_size: int,
    page_token: Optional[str],
) -> MessagePage:
    """List one page of ids for ``query`` then batch-fetch their metadata.

    Pure with respect to Gmail *transport*: it drives whatever ``service`` it
    is handed, so tests inject a fake service and exercise pagination + batch
    collection + ordering without a token. ``page_size`` is clamped to Gmail's
    500-id ``messages.list`` ceiling, so exactly one list call feeds one page
    and Gmail's ``nextPageToken`` becomes our cursor.
    """

    limit = max(1, min(page_size, _GMAIL_LIST_PAGE_MAX))
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=limit, pageToken=page_token)
        .execute()
    )
    refs = listing.get("messages", []) or []
    ids = [ref["id"] for ref in refs[:limit] if ref.get("id")]
    next_token = listing.get("nextPageToken")

    if not ids:
        return MessagePage(messages=[], next_page_token=next_token)

    metadata = _batch_fetch_metadata(
        service,
        ids,
        batch_size=settings.gmail_batch_size,
        pause_seconds=settings.gmail_batch_pause_seconds,
    )

    # Preserve Gmail's newest-first list order; drop ids whose metadata get
    # failed rather than emitting a hollow row.
    out: list[CloudGmailMessage] = []
    for message_id in ids:
        raw = metadata.get(message_id)
        if raw is None:
            continue
        parsed = _parse_metadata_message(raw)
        if parsed is not None:
            out.append(parsed)

    return MessagePage(messages=out, next_page_token=next_token)


async def fetch_message_page(
    user_id: uuid.UUID,
    *,
    query: str = DEFAULT_QUERY,
    page_size: Optional[int] = None,
    page_token: Optional[str] = None,
) -> Optional[MessagePage]:
    """Fetch one server-side page of messages for ``user_id``.

    Returns ``None`` when Gmail is not connected (so the router can answer
    409); otherwise a :class:`MessagePage` (possibly empty) with the cursor to
    request the next page. Read-only, metadata-only: ``messages.list`` +
    batched ``messages.get(format="metadata")`` — no bodies, no mutation.
    """

    creds = await load_valid_credentials(user_id)
    if creds is None:
        return None

    size = page_size or settings.gmail_fetch_page_size
    loop = asyncio.get_event_loop()

    def _run() -> MessagePage:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return _collect_page(
            service, query=query, page_size=size, page_token=page_token
        )

    return await loop.run_in_executor(None, _run)


async def fetch_recent_messages(
    user_id: uuid.UUID,
    *,
    max_results: Optional[int] = None,
    query: str = DEFAULT_QUERY,
) -> Optional[list[CloudGmailMessage]]:
    """Fetch a single bounded page of recent messages for ``user_id``.

    Backwards-compatible convenience over :func:`fetch_message_page`: returns
    just the message list (no cursor) for callers that want one quick batch.
    Returns ``None`` when Gmail is not connected.
    """

    limit = max_results or settings.gmail_fetch_max_results
    page = await fetch_message_page(user_id, query=query, page_size=limit)
    if page is None:
        return None
    return page.messages


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
