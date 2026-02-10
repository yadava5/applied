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
import email
import logging
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from aioimaplib import IMAP4_SSL

from jobtracker.credentials import ICloudCredentials, get_icloud_credentials

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

        # Select folder
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
                    self._imap.fetch(str(msg_num), "(UID RFC822.HEADER BODY[TEXT])"),
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
            uid = 0
            headers_raw = b""
            body_raw = b""

            # Parse response lines - aioimaplib returns a mix of bytes, bytearray, and strings
            lines = response.lines
            i = 0
            while i < len(lines):
                line = lines[i]
                
                # Convert to bytes if needed
                if isinstance(line, bytearray):
                    line = bytes(line)
                elif isinstance(line, str):
                    line = line.encode('utf-8', errors='replace')
                
                # Check if this is the initial FETCH response line
                if isinstance(line, bytes) and b"FETCH" in line:
                    # Extract UID from the line
                    if b"UID" in line:
                        uid = self._extract_uid(line)
                    
                    # The next line should be headers
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if isinstance(next_line, (bytes, bytearray)):
                            headers_raw = bytes(next_line) if isinstance(next_line, bytearray) else next_line
                    
                    # Look for body after headers
                    if i + 3 < len(lines):
                        body_line = lines[i + 3]
                        if isinstance(body_line, (bytes, bytearray)):
                            body_raw = bytes(body_line) if isinstance(body_line, bytearray) else body_line
                    
                    break
                i += 1

            if not headers_raw:
                logger.debug("No headers found in response")
                return None

            # Parse headers
            msg = email.message_from_bytes(headers_raw + b"\r\n\r\n" + body_raw)

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
            body_text = self._extract_body_from_email(msg, body_raw)

            return IMAPMessage(
                uid=uid,
                message_id=message_id,
                subject=subject,
                sender_name=sender_name,
                sender_email=sender_email,
                received_at=received_at,
                body_text=body_text,
                body_snippet=body_text[:500] if body_text else "",
                raw_headers=headers,
            )

        except Exception as e:
            logger.warning(f"Failed to parse FETCH response: {e}")
            return None

    def _extract_uid(self, line: bytes) -> int:
        """Extract UID from FETCH response line."""
        try:
            text = line.decode("utf-8", errors="replace")
            # Look for "UID <number>"
            import re

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
    ) -> str:
        """Extract plain text body from email message."""
        try:
            # If we have raw body data
            if body_raw:
                return body_raw.decode("utf-8", errors="replace")

            # Try to get payload
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            return payload.decode(charset, errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")

        except Exception as e:
            logger.debug(f"Error extracting body: {e}")

        return ""

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
