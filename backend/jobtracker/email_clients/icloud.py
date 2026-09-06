"""
iCloud Mail IMAP client with async support.

This module handles:
- Async IMAP connection to iCloud Mail
- Email fetching via IMAP
- Incremental sync using UIDs
- Connection management and reconnection

iCloud IMAP Settings:
- Server: imap.mail.me.com
- Port: 993 (SSL/TLS)
- Authentication: App-specific password (required with 2FA)

User Setup Requirements:
1. Enable Two-Factor Authentication for Apple ID
2. Generate an app-specific password at appleid.apple.com
3. Store the app-specific password (not main Apple ID password)
"""

import asyncio
import base64
import email
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from aioimaplib import IMAP4_SSL

from jobtracker.credentials import ICloudCredentials, get_icloud_credentials
from jobtracker.email_clients.html_text import (
    SCRIPT_OR_STYLE,
    TAG,
    WHITESPACE,
    cap_html,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# iCloud IMAP server settings
ICLOUD_IMAP_HOST = "imap.mail.me.com"
ICLOUD_IMAP_PORT = 993

# Connection settings
CONNECTION_TIMEOUT = 30  # seconds
IDLE_TIMEOUT = 29 * 60  # 29 minutes (IMAP IDLE refresh)

# Fetch settings
MAX_FETCH_SIZE = 100  # Messages per batch
FETCH_DELAY = 0.05  # 50ms between fetches to be polite


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class IMAPMessage:
    """Parsed IMAP message in normalized format."""

    uid: int  # IMAP UID (unique within mailbox)
    message_id: str  # Message-ID header (globally unique)
    subject: str
    sender_name: Optional[str]
    sender_email: str
    received_at: datetime
    body_text: str
    body_snippet: str
    raw_headers: dict
    body_html: Optional[str] = None


# =============================================================================
# iCloud IMAP Client
# =============================================================================


class ICloudClient:
    """
    Async iCloud Mail IMAP client.

    Usage:
        client = ICloudClient()
        if not client.has_credentials():
            raise ValueError("iCloud credentials required")

        async with client:
            messages = await client.fetch_emails(since_uid=12345)
    """

    def __init__(self):
        self._imap: Optional[IMAP4_SSL] = None
        self._connected = False

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "ICloudClient":
        """Connect on context enter."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Disconnect on context exit."""
        await self.disconnect()

    # -------------------------------------------------------------------------
    # Credentials
    # -------------------------------------------------------------------------

    def has_credentials(self) -> bool:
        """Check if iCloud credentials are stored."""
        return get_icloud_credentials() is not None

    def get_account_email(self) -> Optional[str]:
        """Get the stored iCloud email address."""
        creds = get_icloud_credentials()
        return creds.email if creds else None

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    async def connect(self) -> bool:
        """
        Connect to iCloud IMAP server.

        Returns:
            True if connected successfully, False otherwise.
        """
        if self._connected:
            return True

        credentials = get_icloud_credentials()
        if credentials is None:
            logger.error("iCloud credentials not found")
            return False

        try:
            # Create SSL context
            ssl_context = ssl.create_default_context()

            # Connect to IMAP server
            self._imap = IMAP4_SSL(
                host=ICLOUD_IMAP_HOST,
                port=ICLOUD_IMAP_PORT,
                ssl_context=ssl_context,
                timeout=CONNECTION_TIMEOUT,
            )

            # Wait for connection
            await self._imap.wait_hello_from_server()

            # Login
            response = await self._imap.login(
                credentials.email, credentials.app_password
            )

            if response.result != "OK":
                logger.error(f"iCloud login failed: {response}")
                return False

            self._connected = True
            logger.info(f"Connected to iCloud IMAP as {credentials.email}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to iCloud: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self._imap and self._connected:
            try:
                await self._imap.logout()
            except Exception as e:
                logger.debug(f"Error during disconnect: {e}")
            finally:
                self._connected = False
                self._imap = None
                logger.debug("Disconnected from iCloud IMAP")

    async def _ensure_connected(self) -> None:
        """Ensure we're connected, reconnect if needed."""
        if not self._connected:
            success = await self.connect()
            if not success:
                raise RuntimeError("Failed to connect to iCloud IMAP")

    # -------------------------------------------------------------------------
    # Email Fetching
    # -------------------------------------------------------------------------

    async def fetch_emails(
        self,
        since_uid: Optional[int] = None,
        since_date: Optional[datetime] = None,
        folder: str = "INBOX",
        max_results: int = 5000,  # Increased limit for comprehensive fetch
    ) -> tuple[list[IMAPMessage], int]:
        """
        Fetch emails from iCloud.

        Args:
            since_uid: Only fetch messages with UID greater than this (incremental).
            since_date: Only fetch messages since this date.
            folder: IMAP folder to fetch from (default: INBOX).
            max_results: Maximum number of messages to fetch.

        Returns:
            Tuple of (list of messages, highest UID seen for next sync).
        """
        await self._ensure_connected()

        # Select mailbox. Unread preservation is handled by BODY.PEEK in fetch.
        response = await self._imap.select(folder)
        if response.result != "OK":
            logger.error(f"Failed to select folder {folder}: {response}")
            return [], since_uid or 0

        messages: list[IMAPMessage] = []
        highest_uid = since_uid or 0

        try:
            # Build search criteria
            search_criteria = await self._build_search_criteria(since_uid, since_date)

            # Search for messages
            response = await self._imap.search(search_criteria)
            if response.result != "OK":
                logger.warning(f"Search failed: {response}")
                return [], highest_uid

            # Parse message sequence numbers
            message_nums = self._parse_search_response(response)
            if not message_nums:
                logger.debug("No new messages found")
                return [], highest_uid

            # Limit results
            message_nums = message_nums[-max_results:]

            logger.info(f"Found {len(message_nums)} messages to fetch")

            # Fetch messages
            for msg_num in message_nums:
                try:
                    await asyncio.sleep(FETCH_DELAY)

                    message = await self._fetch_message(msg_num)
                    if message:
                        messages.append(message)
                        highest_uid = max(highest_uid, message.uid)

                except Exception as e:
                    logger.warning(f"Failed to fetch message {msg_num}: {e}")

            logger.info(f"Fetched {len(messages)} emails from iCloud")

        except Exception as e:
            logger.error(f"Error fetching emails: {e}")

        return messages, highest_uid

    async def _build_search_criteria(
        self, since_uid: Optional[int], since_date: Optional[datetime]
    ) -> str:
        """Build IMAP search criteria string."""
        criteria = []

        if since_uid:
            # Fetch messages with UID > since_uid
            criteria.append(f"UID {since_uid + 1}:*")
        elif since_date:
            # Fetch messages since date
            date_str = since_date.strftime("%d-%b-%Y")
            criteria.append(f"SINCE {date_str}")
        else:
            # Default: last 30 days
            default_since = datetime.now() - timedelta(days=30)
            date_str = default_since.strftime("%d-%b-%Y")
            criteria.append(f"SINCE {date_str}")

        return " ".join(criteria) if criteria else "ALL"

    def _parse_search_response(self, response) -> list[int]:
        """Parse IMAP search response to get message numbers."""
        try:
            # Response format varies, extract message numbers
            for line in response.lines:
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                parts = str(line).split()
                # Filter to just numbers
                nums = [int(p) for p in parts if p.isdigit()]
                if nums:
                    return nums
            return []
        except Exception as e:
            logger.warning(f"Failed to parse search response: {e}")
            return []

    async def _fetch_message(self, msg_num: int) -> Optional[IMAPMessage]:
        """Fetch and parse a single message."""
        try:
            # Fetch message with UID (with timeout)
            try:
                response = await asyncio.wait_for(
                    # BODY.PEEK[] fetches the full raw message without setting \\Seen.
                    self._imap.fetch(str(msg_num), "(UID BODY.PEEK[])"),
                    timeout=15.0  # 15 second timeout per message
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout fetching message {msg_num}")
                return None

            if response.result != "OK":
                logger.warning(f"Error fetching message {msg_num}: {response.result}")
                return None

            parsed = self._parse_fetch_response(response)
            if parsed is None:
                logger.debug(f"Failed to parse message {msg_num}, response lines: {len(response.lines)}")
            return parsed

        except Exception as e:
            logger.warning(f"Error fetching message {msg_num}: {e}")
            return None

    def _parse_fetch_response(self, response) -> Optional[IMAPMessage]:
        """Parse IMAP FETCH response into IMAPMessage."""
        try:
            uid, raw_message = self._extract_uid_and_raw_message(response)
            if not raw_message:
                logger.debug("No raw RFC822 payload found in FETCH response")
                return None

            msg = email.message_from_bytes(raw_message)

            # Extract header values
            headers = {key.lower(): val for key, val in msg.items()}

            # Extract sender
            from_header = msg.get("From", "")
            sender_name, sender_email = parseaddr(from_header)
            sender_name = self._decode_header(sender_name) if sender_name else None

            # Extract subject
            subject = self._decode_header(msg.get("Subject", "(No Subject)"))

            # Extract date
            date_header = msg.get("Date", "")
            received_at = self._parse_date(date_header)

            # Extract Message-ID
            message_id = msg.get("Message-ID", f"icloud-{uid}")
            message_id = message_id.strip("<>")

            # Extract body
            fallback_payload = b""
            if not msg.is_multipart():
                payload = msg.get_payload(decode=True)
                if isinstance(payload, bytes):
                    fallback_payload = payload

            body_text, body_html = self._extract_body_from_email(msg, fallback_payload)
            snippet_source = body_text or self._strip_html(body_html or "")

            return IMAPMessage(
                uid=uid,
                message_id=message_id,
                subject=subject,
                sender_name=sender_name,
                sender_email=sender_email,
                received_at=received_at,
                body_text=body_text,
                body_snippet=snippet_source[:500] if snippet_source else "",
                body_html=body_html,
                raw_headers=headers,
            )

        except Exception as e:
            logger.warning(f"Failed to parse FETCH response: {e}")
            return None

    def _extract_uid_and_raw_message(self, response) -> tuple[int, bytes]:
        """Extract UID and RFC822 payload bytes from FETCH response lines."""
        uid = 0
        raw_message = b""
        lines = response.lines

        for idx, line in enumerate(lines):
            line_bytes = self._line_to_bytes(line)
            if b"FETCH" not in line_bytes:
                continue

            if b"UID" in line_bytes:
                uid = self._extract_uid(line_bytes)

            literal_size_match = re.search(rb"\{(\d+)\}", line_bytes)
            if literal_size_match:
                literal_size = int(literal_size_match.group(1))
                collected = bytearray()
                next_idx = idx + 1
                while next_idx < len(lines) and len(collected) < literal_size:
                    candidate = self._line_to_bytes(lines[next_idx])
                    collected.extend(candidate)
                    next_idx += 1
                raw_message = bytes(collected[:literal_size])
            else:
                # Fallback when server does not include explicit literal size.
                next_idx = idx + 1
                while next_idx < len(lines):
                    candidate = self._line_to_bytes(lines[next_idx])
                    if candidate.startswith(b")") or b" OK " in candidate:
                        next_idx += 1
                        continue
                    raw_message = candidate
                    break

            if raw_message:
                break

        return uid, raw_message

    def _line_to_bytes(self, line) -> bytes:
        """Normalize aioimaplib response line into bytes."""
        if isinstance(line, bytes):
            return line
        if isinstance(line, bytearray):
            return bytes(line)
        return str(line).encode("utf-8", errors="replace")

    def _extract_uid(self, line: bytes) -> int:
        """Extract UID from FETCH response line."""
        try:
            text = line.decode("utf-8", errors="replace")
            # Look for "UID <number>"
            match = re.search(r"UID\s+(\d+)", text)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return 0

    def _decode_header(self, header: str) -> str:
        """Decode RFC 2047 encoded header."""
        try:
            decoded_parts = decode_header(header)
            result = []
            for part, charset in decoded_parts:
                if isinstance(part, bytes):
                    charset = charset or "utf-8"
                    result.append(part.decode(charset, errors="replace"))
                else:
                    result.append(part)
            return "".join(result)
        except Exception:
            return header

    def _parse_date(self, date_str: str) -> datetime:
        """Parse email date header."""
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now()

    def _extract_body_from_email(
        self, msg: email.message.Message, body_raw: bytes
    ) -> tuple[str, Optional[str]]:
        """Extract plain text and HTML body from email message."""
        try:
            plain_text = ""
            html_body: Optional[str] = None
            cid_attachments: dict[str, str] = {}

            # If we have raw body data, use it as a fallback.
            raw_decoded = body_raw.decode("utf-8", errors="replace") if body_raw else ""

            # Try to get payload
            if msg.is_multipart():
                for part in msg.walk():
                    if part.is_multipart():
                        continue

                    content_type = part.get_content_type()
                    payload = part.get_payload(decode=True)

                    content_id = (part.get("Content-ID") or "").strip("<>")
                    if content_id and payload:
                        cid_attachments[content_id] = (
                            f"data:{content_type};base64,"
                            f"{base64.b64encode(payload).decode('ascii')}"
                        )

                    if content_type == "text/plain" and not plain_text:
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            plain_text = payload.decode(charset, errors="replace")
                    elif content_type == "text/html" and html_body is None:
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            html_body = payload.decode(charset, errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")
                    if msg.get_content_type() == "text/html":
                        html_body = decoded
                    else:
                        plain_text = decoded

            if not plain_text and raw_decoded:
                if self._looks_like_html(raw_decoded):
                    html_body = html_body or raw_decoded
                    plain_text = self._strip_html(raw_decoded)
                else:
                    plain_text = raw_decoded

            if not plain_text and html_body:
                plain_text = self._strip_html(html_body)

            if html_body and cid_attachments:
                html_body = self._replace_cid_sources(html_body, cid_attachments)

            return plain_text, html_body

        except Exception as e:
            logger.debug(f"Error extracting body: {e}")

        return "", None

    def _looks_like_html(self, value: str) -> bool:
        """Heuristic to detect HTML payloads."""
        lowered = value.lower()
        return "<html" in lowered or "<body" in lowered or "<div" in lowered

    def _strip_html(self, html: str) -> str:
        """Convert HTML to plain text for snippet/search fallback."""
        # Script/style bodies go first, or they survive tag stripping as text.
        # A time bound. See ``MAX_HTML_CHARS``; ``cap_html`` also refuses to
        # leave a stylesheet open, which would reach the reader as prose.
        html = cap_html(html)
        html = SCRIPT_OR_STYLE.sub(" ", html)
        html = TAG.sub(" ", html)
        html = WHITESPACE.sub(" ", html)
        return html.strip()

    def _replace_cid_sources(self, html: str, cid_attachments: dict[str, str]) -> str:
        """Replace cid: links in HTML with data URLs when inline attachments exist."""
        if not cid_attachments:
            return html

        def _replace(match: re.Match[str]) -> str:
            cid = match.group(1).strip("<>")
            return cid_attachments.get(cid, match.group(0))

        return re.sub(r"cid:\s*<?([^\"'>\s]+)>?", _replace, html, flags=re.I)

    # -------------------------------------------------------------------------
    # Folder Operations
    # -------------------------------------------------------------------------

    async def list_folders(self) -> list[str]:
        """List available IMAP folders."""
        await self._ensure_connected()

        try:
            response = await self._imap.list()
            if response.result != "OK":
                return []

            folders = []
            for line in response.lines:
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                # Parse folder name from response
                # Format: (\HasNoChildren) "/" "FolderName"
                import re

                match = re.search(r'"([^"]+)"$', str(line))
                if match:
                    folders.append(match.group(1))

            return folders

        except Exception as e:
            logger.error(f"Failed to list folders: {e}")
            return []

    # -------------------------------------------------------------------------
    # Connection Test
    # -------------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """Test if we can connect with stored credentials."""
        try:
            success = await self.connect()
            if success:
                await self.disconnect()
            return success
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
