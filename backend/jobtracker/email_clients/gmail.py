"""
Gmail API client with OAuth2 authentication.

This module handles:
- OAuth2 authentication flow (consent screen → token)
- Token refresh when expired
- Email fetching via Gmail API
- Incremental sync using historyId
- Pagination for large mailboxes

Gmail API Scopes:
- gmail.readonly: Read-only access to emails (sufficient for our needs)

Rate Limits:
- 250 quota units per user per second
- messages.list = 5 units, messages.get = 5 units
- We implement exponential backoff for 429 errors
"""

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jobtracker.config import settings
from jobtracker.credentials import (
    GmailCredentials,
    get_gmail_client_secret,
    get_gmail_credentials,
    save_gmail_credentials,
    update_gmail_access_token,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Gmail API scopes (read-only is sufficient)
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Labels to search for job-related emails
# We search across all mail, then filter
DEFAULT_QUERY = "in:inbox OR in:sent"

# Maximum results per page (Gmail API max is 500)
MAX_RESULTS_PER_PAGE = 100

# Rate limiting
RATE_LIMIT_DELAY = 0.1  # 100ms between requests
MAX_RETRIES = 3
BACKOFF_FACTOR = 2


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class GmailMessage:
    """Parsed Gmail message in normalized format."""

    message_id: str  # Gmail message ID
    thread_id: str
    subject: str
    sender_name: Optional[str]
    sender_email: str
    received_at: datetime
    body_text: str
    body_snippet: str
    raw_headers: dict
    body_html: Optional[str] = None


# =============================================================================
# Gmail Client
# =============================================================================


class GmailClient:
    """
    Gmail API client with OAuth2 authentication.

    Usage:
        client = GmailClient()
        if not client.is_authenticated():
            await client.authenticate()

        messages = await client.fetch_emails(since_history_id="12345")
    """

    def __init__(self):
        self._service = None
        self._credentials: Optional[GmailCredentials] = None

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def is_authenticated(self) -> bool:
        """Check if we have valid credentials."""
        creds = get_gmail_credentials()
        return creds is not None

    def _get_google_credentials(self) -> Optional[Credentials]:
        """Convert stored credentials to Google Credentials object."""
        stored = get_gmail_credentials()
        if stored is None:
            return None

        return Credentials(
            token=stored.access_token,
            refresh_token=stored.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._get_client_id(),
            client_secret=self._get_client_secret_value(),
            scopes=SCOPES,
        )

    def _get_client_id(self) -> Optional[str]:
        """Get client ID from stored client secret."""
        client_secret = get_gmail_client_secret()
        if client_secret and "installed" in client_secret:
            return client_secret["installed"].get("client_id")
        return None

    def _get_client_secret_value(self) -> Optional[str]:
        """Get client secret value from stored client secret."""
        client_secret = get_gmail_client_secret()
        if client_secret and "installed" in client_secret:
            return client_secret["installed"].get("client_secret")
        return None

    async def authenticate(self, client_secret_path: Optional[str] = None) -> bool:
        """
        Perform OAuth2 authentication flow.

        This opens a browser window for the user to authorize the application.

        Args:
            client_secret_path: Path to client_secret.json from Google Cloud Console.
                              If not provided, uses stored client secret.

        Returns:
            True if authentication successful, False otherwise.
        """
        try:
            # Get client secret
            if client_secret_path:
                import json

                with open(client_secret_path) as f:
                    client_secret = json.load(f)
            else:
                client_secret = get_gmail_client_secret()

            if client_secret is None:
                logger.error(
                    "No Gmail client secret available. "
                    "Please provide client_secret.json from Google Cloud Console."
                )
                return False

            # Create OAuth flow
            flow = InstalledAppFlow.from_client_config(client_secret, SCOPES)

            # Run the OAuth flow (opens browser)
            # Use run_local_server for desktop apps
            loop = asyncio.get_event_loop()
            credentials = await loop.run_in_executor(
                None,
                lambda: flow.run_local_server(
                    port=8080, prompt="consent", authorization_prompt_message=""
                ),
            )

            # Get user email from Gmail profile (more reliable than oauth2 userinfo)
            service = build("gmail", "v1", credentials=credentials)
            profile = service.users().getProfile(userId="me").execute()
            email = profile.get("emailAddress", "unknown")

            # Store credentials
            gmail_creds = GmailCredentials(
                access_token=credentials.token,
                refresh_token=credentials.refresh_token,
                token_expiry=credentials.expiry or (datetime.now() + timedelta(hours=1)),
                email=email,
                scopes=list(credentials.scopes or SCOPES),
            )
            save_gmail_credentials(gmail_creds)

            logger.info(f"Gmail authentication successful for {email}")
            return True

        except Exception as e:
            logger.error(f"Gmail authentication failed: {e}")
            return False

    async def refresh_token_if_needed(self) -> bool:
        """
        Refresh access token if expired.

        Returns:
            True if token is valid (refreshed or not expired), False otherwise.
        """
        stored = get_gmail_credentials()
        if stored is None:
            logger.error("No Gmail credentials to refresh")
            return False

        if not stored.is_expired():
            return True

        try:
            creds = self._get_google_credentials()
            if creds is None:
                return False

            # Refresh the token
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: creds.refresh(Request()))

            # Update stored credentials
            update_gmail_access_token(
                access_token=creds.token,
                token_expiry=creds.expiry or (datetime.now() + timedelta(hours=1)),
            )

            logger.info("Gmail access token refreshed")
            return True

        except Exception as e:
            logger.error(f"Failed to refresh Gmail token: {e}")
            return False

    # -------------------------------------------------------------------------
    # Service Management
    # -------------------------------------------------------------------------

    async def _get_service(self):
        """Get or create Gmail API service."""
        if self._service is not None:
            return self._service

        # Ensure token is valid
        if not await self.refresh_token_if_needed():
            raise RuntimeError("Gmail authentication required")

        creds = self._get_google_credentials()
        if creds is None:
            raise RuntimeError("Gmail credentials not found")

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # -------------------------------------------------------------------------
    # Email Fetching
    # -------------------------------------------------------------------------

    async def fetch_emails(
        self,
        since_history_id: Optional[str] = None,
        since_date: Optional[datetime] = None,
        max_results: int = 5000,  # Increased limit for comprehensive fetch
        query: str = DEFAULT_QUERY,
    ) -> tuple[list[GmailMessage], Optional[str]]:
        """
        Fetch emails from Gmail.

        Args:
            since_history_id: Only fetch changes since this historyId (incremental sync).
                            If None, fetches recent emails (full sync).
            since_date: Only fetch emails received after this date.
            max_results: Maximum number of emails to fetch.
            query: Gmail search query (default: inbox and sent).

        Returns:
            Tuple of (list of messages, new historyId for next sync).
        """
        service = await self._get_service()
        messages: list[GmailMessage] = []
        new_history_id: Optional[str] = None

        # Build query with date filter if provided
        effective_query = query
        if since_date:
            # Gmail uses after:YYYY/MM/DD format
            date_str = since_date.strftime("%Y/%m/%d")
            effective_query = f"{query} after:{date_str}"
            logger.info(f"Gmail query with date filter: {effective_query}")

        try:
            if since_history_id and not since_date:
                # Incremental sync using history API (only if no date filter)
                messages, new_history_id = await self._fetch_incremental(
                    service, since_history_id, max_results
                )
            else:
                # Full sync - fetch messages matching query
                messages, new_history_id = await self._fetch_full(
                    service, effective_query, max_results
                )

            logger.info(f"Fetched {len(messages)} emails from Gmail")
            return messages, new_history_id

        except HttpError as e:
            if e.resp.status == 404 and since_history_id:
                # History ID is too old, need full sync
                logger.warning("Gmail history too old, performing full sync")
                return await self._fetch_full(service, effective_query, max_results)
            raise

    async def _fetch_full(
        self, service, query: str, max_results: int
    ) -> tuple[list[GmailMessage], Optional[str]]:
        """Fetch messages using messages.list (full sync)."""
        messages: list[GmailMessage] = []
        page_token = None
        fetched = 0

        loop = asyncio.get_event_loop()

        while fetched < max_results:
            # Rate limiting
            await asyncio.sleep(RATE_LIMIT_DELAY)

            # List messages
            response = await loop.run_in_executor(
                None,
                lambda: service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=min(MAX_RESULTS_PER_PAGE, max_results - fetched),
                    pageToken=page_token,
                )
                .execute(),
            )

            message_refs = response.get("messages", [])
            if not message_refs:
                break

            # Fetch full message content for each
            for msg_ref in message_refs:
                if fetched >= max_results:
                    break

                try:
                    message = await self._fetch_message(service, msg_ref["id"])
                    if message:
                        messages.append(message)
                        fetched += 1
                except HttpError as e:
                    if e.resp.status == 429:
                        # Rate limited, back off
                        await asyncio.sleep(1)
                        continue
                    logger.warning(f"Failed to fetch message {msg_ref['id']}: {e}")

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        # Get current history ID
        profile = await loop.run_in_executor(
            None, lambda: service.users().getProfile(userId="me").execute()
        )
        history_id = profile.get("historyId")

        return messages, history_id

    async def _fetch_incremental(
        self, service, since_history_id: str, max_results: int
    ) -> tuple[list[GmailMessage], Optional[str]]:
        """Fetch new/changed messages using history API (incremental sync)."""
        messages: list[GmailMessage] = []
        message_ids_to_fetch: set[str] = set()

        loop = asyncio.get_event_loop()

        # Get history changes
        page_token = None
        while True:
            await asyncio.sleep(RATE_LIMIT_DELAY)

            response = await loop.run_in_executor(
                None,
                lambda: service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=since_history_id,
                    historyTypes=["messageAdded"],
                    pageToken=page_token,
                )
                .execute(),
            )

            # Collect message IDs from history
            for history in response.get("history", []):
                for added in history.get("messagesAdded", []):
                    message_ids_to_fetch.add(added["message"]["id"])

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        # Fetch full content for new messages
        for msg_id in list(message_ids_to_fetch)[:max_results]:
            try:
                message = await self._fetch_message(service, msg_id)
                if message:
                    messages.append(message)
            except HttpError as e:
                logger.warning(f"Failed to fetch message {msg_id}: {e}")

        # Get current history ID from response
        new_history_id = response.get("historyId")

        return messages, new_history_id

    async def _fetch_message(self, service, message_id: str) -> Optional[GmailMessage]:
        """Fetch and parse a single message."""
        loop = asyncio.get_event_loop()

        await asyncio.sleep(RATE_LIMIT_DELAY)

        response = await loop.run_in_executor(
            None,
            lambda: service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute(),
        )

        return self._parse_message(response)

    def _parse_message(self, raw: dict) -> Optional[GmailMessage]:
        """Parse Gmail API response into GmailMessage."""
        try:
            headers = {
                h["name"].lower(): h["value"]
                for h in raw.get("payload", {}).get("headers", [])
            }

            # Extract sender
            from_header = headers.get("from", "")
            sender_name, sender_email = parseaddr(from_header)

            # Extract subject
            subject = headers.get("subject", "(No Subject)")

            # Extract date
            date_str = headers.get("date", "")
            received_at = self._parse_date(date_str)

            # Extract body
            body_text, body_html = self._extract_bodies(raw.get("payload", {}))
            if not body_text and body_html:
                body_text = self._strip_html(body_html)
            snippet_source = raw.get("snippet", "") or body_text
            if not snippet_source and body_html:
                snippet_source = self._strip_html(body_html)

            return GmailMessage(
                message_id=raw["id"],
                thread_id=raw.get("threadId", ""),
                subject=subject,
                sender_name=sender_name if sender_name else None,
                sender_email=sender_email,
                received_at=received_at,
                body_text=body_text,
                body_snippet=snippet_source[:500],
                body_html=body_html,
                raw_headers=headers,
            )
        except Exception as e:
            logger.warning(f"Failed to parse message: {e}")
            return None

    def _extract_bodies(self, payload: dict) -> tuple[str, Optional[str]]:
        """Extract plain text and HTML bodies from Gmail payload."""
        plain_text = ""
        html_body: Optional[str] = None

        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if mime_type == "text/plain":
            plain_text = self._decode_body_data(body_data)
            return plain_text, None

        if mime_type == "text/html":
            html_body = self._decode_body_data(body_data)
            return "", html_body or None

        for part in payload.get("parts", []):
            part_mime = part.get("mimeType", "")
            if part_mime.startswith("multipart/"):
                nested_text, nested_html = self._extract_bodies(part)
                if nested_text and not plain_text:
                    plain_text = nested_text
                if nested_html and not html_body:
                    html_body = nested_html
                continue

            if part_mime == "text/plain" and not plain_text:
                plain_text = self._decode_body_data(part.get("body", {}).get("data", ""))
            elif part_mime == "text/html" and not html_body:
                decoded_html = self._decode_body_data(part.get("body", {}).get("data", ""))
                html_body = decoded_html or html_body

        return plain_text, html_body

    def _decode_body_data(self, data: str) -> str:
        """Decode url-safe base64 body payload safely."""
        if not data:
            return ""
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _strip_html(self, html: str) -> str:
        """Strip HTML tags and return plain text."""
        import re

        # Remove script and style elements
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.I)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.I)
        # Remove HTML tags
        html = re.sub(r"<[^>]+>", " ", html)
        # Normalize whitespace
        html = re.sub(r"\s+", " ", html)
        return html.strip()

    def _parse_date(self, date_str: str) -> datetime:
        """Parse email date header."""
        from email.utils import parsedate_to_datetime

        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now()

    # -------------------------------------------------------------------------
    # Account Info
    # -------------------------------------------------------------------------

    async def get_account_email(self) -> Optional[str]:
        """Get the authenticated account's email address."""
        creds = get_gmail_credentials()
        return creds.email if creds else None

    async def get_profile(self) -> Optional[dict]:
        """Get Gmail profile information."""
        try:
            service = await self._get_service()
            loop = asyncio.get_event_loop()
            profile = await loop.run_in_executor(
                None, lambda: service.users().getProfile(userId="me").execute()
            )
            return profile
        except Exception as e:
            logger.error(f"Failed to get Gmail profile: {e}")
            return None
