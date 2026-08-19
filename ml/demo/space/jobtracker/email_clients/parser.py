"""
Unified email parser for normalizing Gmail and IMAP messages.

This module provides a common interface for converting emails from
different sources (Gmail API, IMAP) into a unified format that
matches our database schema.

Features:
- Normalize Gmail API format and IMAP format into common schema
- Extract and clean email body text
- Parse sender information
- Generate unique message identifiers
- Handle various encodings
"""

import hashlib
import html
import logging
import quopri
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from jobtracker.email_clients.gmail import GmailMessage
from jobtracker.email_clients.html_text import SCRIPT_OR_STYLE, TAG, WHITESPACE
from jobtracker.email_clients.icloud import IMAPMessage

logger = logging.getLogger(__name__)


# =============================================================================
# Unified Email Format
# =============================================================================


@dataclass
class ParsedEmail:
    """
    Unified email format matching database schema.

    This is the common format used throughout the application,
    regardless of email source (Gmail, iCloud).
    """

    # Source information
    source_account: str  # "gmail" or "icloud"
    message_id: str  # Unique message identifier
    thread_id: Optional[str]  # Thread/conversation ID (Gmail only)

    # Email content
    subject: str
    sender_name: Optional[str]
    sender_email: str
    received_at: datetime
    body_text: str
    body_snippet: str  # First 500 chars

    # Raw data for debugging
    raw_headers: dict
    body_html: Optional[str] = None


# =============================================================================
# Email Parser
# =============================================================================


class EmailParser:
    """
    Parser for normalizing emails from different sources.

    Usage:
        parser = EmailParser()

        # From Gmail
        gmail_msg = GmailMessage(...)
        parsed = parser.from_gmail(gmail_msg)

        # From iCloud
        imap_msg = IMAPMessage(...)
        parsed = parser.from_icloud(imap_msg, email="user@icloud.com")
    """

    def from_gmail(self, msg: GmailMessage, email: str = "") -> ParsedEmail:
        """
        Convert Gmail API message to unified format.

        Args:
            msg: Gmail message from Gmail API.
            email: User's Gmail address (for source tracking).

        Returns:
            Parsed email in unified format.
        """
        return ParsedEmail(
            source_account="gmail",
            message_id=self._normalize_message_id(msg.message_id, "gmail"),
            thread_id=msg.thread_id,
            subject=self._clean_subject(msg.subject),
            sender_name=msg.sender_name,
            sender_email=self._normalize_email(msg.sender_email),
            received_at=msg.received_at,
            body_text=self._clean_body(msg.body_text),
            body_html=self._clean_html(msg.body_html),
            body_snippet=self._generate_snippet(
                msg.body_text,
                msg.body_snippet,
                msg.body_html,
            ),
            raw_headers=msg.raw_headers,
        )

    def from_icloud(self, msg: IMAPMessage, email: str = "") -> ParsedEmail:
        """
        Convert IMAP message to unified format.

        Args:
            msg: IMAP message from iCloud.
            email: User's iCloud address (for source tracking).

        Returns:
            Parsed email in unified format.
        """
        return ParsedEmail(
            source_account="icloud",
            message_id=self._normalize_message_id(msg.message_id, "icloud"),
            thread_id=None,  # IMAP doesn't have native threading
            subject=self._clean_subject(msg.subject),
            sender_name=msg.sender_name,
            sender_email=self._normalize_email(msg.sender_email),
            received_at=msg.received_at,
            body_text=self._clean_body(msg.body_text),
            body_html=self._clean_html(msg.body_html),
            body_snippet=self._generate_snippet(
                msg.body_text,
                msg.body_snippet,
                msg.body_html,
            ),
            raw_headers=msg.raw_headers,
        )

    # -------------------------------------------------------------------------
    # Normalization Helpers
    # -------------------------------------------------------------------------

    def _normalize_message_id(self, raw_id: str, source: str) -> str:
        """
        Normalize message ID to a consistent format.

        Gmail uses internal IDs, IMAP uses Message-ID headers.
        We prefix with source to ensure uniqueness.
        """
        # Clean the ID
        clean_id = raw_id.strip().strip("<>")

        # If it's empty or invalid, generate one
        if not clean_id or len(clean_id) < 5:
            # Generate from hash
            hash_input = f"{source}-{datetime.now().isoformat()}-{raw_id}"
            clean_id = hashlib.sha256(hash_input.encode()).hexdigest()[:32]

        return f"{source}:{clean_id}"

    def _normalize_email(self, email_addr: str) -> str:
        """Normalize email address to lowercase."""
        if not email_addr:
            return ""
        return email_addr.lower().strip()

    def _clean_subject(self, subject: str) -> str:
        """Clean and normalize email subject."""
        if not subject:
            return "(No Subject)"

        # Decode if needed
        subject = subject.strip()

        # Remove excessive whitespace
        subject = re.sub(r"\s+", " ", subject)

        # Truncate very long subjects
        if len(subject) > 500:
            subject = subject[:497] + "..."

        return subject or "(No Subject)"

    def _clean_body(self, body: str) -> str:
        """Clean email body text."""
        if not body:
            return ""

        # Normalize line endings
        body = body.replace("\r\n", "\n").replace("\r", "\n")
        body = self._decode_transfer_encoding(body)
        body = self._strip_mime_scaffolding(body)

        # Convert HTML-ish payloads to text for downstream classification/extraction.
        if self._looks_like_html(body):
            body = self._html_to_text(body)

        # Decode HTML entities after transfer-encoding cleanup.
        body = html.unescape(body)

        # Remove excessive blank lines
        body = re.sub(r"\n{3,}", "\n\n", body)
        body = re.sub(r"[ \t]+\n", "\n", body)

        # Remove common email signatures/footers
        body = self._remove_common_footers(body)

        # Strip leading/trailing whitespace
        body = body.strip()

        return body

    def _decode_transfer_encoding(self, body: str) -> str:
        """Best-effort decode of quoted-printable text bodies."""
        # Only attempt expensive decode when transfer-encoding artifacts are present.
        if "=" not in body:
            return body

        looks_qp = bool(
            re.search(r"=[0-9A-Fa-f]{2}", body) or re.search(r"=\n", body)
        )
        if not looks_qp:
            return body

        try:
            decoded = quopri.decodestring(body.encode("utf-8", errors="ignore"))
            return decoded.decode("utf-8", errors="replace")
        except Exception:
            return body

    def _strip_mime_scaffolding(self, body: str) -> str:
        """Remove common MIME wrapper lines leaked from raw IMAP text payloads."""
        # Remove boundary delimiter lines (e.g. "------=_Part_...").
        body = re.sub(r"(?m)^--[-_A-Za-z0-9.=:/+]+(?:--)?\s*$", "", body)

        # Remove MIME header lines that can leak into plain text payloads.
        body = re.sub(
            r"(?mi)^(?:content-(?:type|transfer-encoding|id|disposition)|mime-version):.*$",
            "",
            body,
        )

        # Remove folded header continuation lines.
        body = re.sub(r"(?m)^[ \t]+(?:charset|boundary)=?.*$", "", body)

        return body

    def _remove_common_footers(self, body: str) -> str:
        """Remove common email footers and signatures."""
        # Common signature indicators
        signature_patterns = [
            r"\n--\s*\n.*$",  # Standard -- signature marker
            r"\nSent from my .*$",  # Mobile signatures
            r"\nGet Outlook for .*$",
            r"\n_{10,}.*$",  # Long underscore separators
        ]

        for pattern in signature_patterns:
            body = re.sub(pattern, "", body, flags=re.DOTALL | re.IGNORECASE)

        return body

    def _clean_html(self, body_html: Optional[str]) -> Optional[str]:
        """Normalize raw HTML while keeping markup intact for rendering."""
        if not body_html:
            return None

        cleaned = body_html.strip()
        if not cleaned:
            return None

        # Cap stored HTML size to keep DB rows reasonable.
        if len(cleaned) > 300_000:
            cleaned = cleaned[:300_000]

        return cleaned

    def _looks_like_html(self, value: str) -> bool:
        """Heuristic to detect HTML payloads."""
        lowered = value.lower()
        return "<html" in lowered or "<body" in lowered or "<div" in lowered

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to rough plain text for snippets/classification fallback."""
        # Remove script/style blocks before stripping all tags, or their
        # contents survive as text. The pattern lives in ``html_text`` so this
        # module, ``gmail`` and ``icloud`` cannot drift apart again.
        html = SCRIPT_OR_STYLE.sub(" ", html)
        html = TAG.sub(" ", html)
        return WHITESPACE.sub(" ", html).strip()

    def _generate_snippet(
        self,
        body: str,
        existing_snippet: str = "",
        body_html: Optional[str] = None,
    ) -> str:
        """Generate a 500-char snippet from body or use existing."""
        # Prefer existing snippet if clean
        if existing_snippet and len(existing_snippet) >= 50:
            snippet = existing_snippet
        else:
            snippet = body
            if not snippet and body_html:
                snippet = self._html_to_text(body_html)

        if not snippet:
            return ""

        # Clean and truncate
        snippet = re.sub(r"\s+", " ", snippet).strip()

        if len(snippet) > 500:
            # Try to cut at word boundary
            snippet = snippet[:500]
            last_space = snippet.rfind(" ")
            if last_space > 400:
                snippet = snippet[:last_space]
            snippet += "..."

        return snippet


# =============================================================================
# Deduplication
# =============================================================================


def generate_dedup_key(parsed: ParsedEmail) -> str:
    """
    Generate a key for deduplication.

    Uses Message-ID which should be globally unique.
    Falls back to hash of content if Message-ID is missing.
    """
    return parsed.message_id


def emails_are_duplicate(email1: ParsedEmail, email2: ParsedEmail) -> bool:
    """Check if two parsed emails are duplicates."""
    return generate_dedup_key(email1) == generate_dedup_key(email2)


# =============================================================================
# Job-Related Detection (Preliminary)
# =============================================================================

# Common job-related sender domains
JOB_RELATED_DOMAINS = {
    # ATS (Applicant Tracking Systems)
    "greenhouse.io",
    "lever.co",
    "workday.com",
    "myworkday.com",
    "icims.com",
    "smartrecruiters.com",
    "jobvite.com",
    "ashbyhq.com",
    "bamboohr.com",
    "jazz.co",
    "recruitee.com",
    "breezy.hr",
    "workable.com",
    # Job boards
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "dice.com",
    "angel.co",
    "wellfound.com",
    "hired.com",
    "triplebyte.com",
    "ycombinator.com",
}

# Common job-related subject patterns
JOB_SUBJECT_PATTERNS = [
    r"application",
    r"interview",
    r"offer",
    r"position",
    r"opportunity",
    r"role\b",
    r"candidate",
    r"resume",
    r"recruiter",
    r"hiring",
    r"job\b",
]


def is_likely_job_related(parsed: ParsedEmail) -> bool:
    """
    Quick check if an email is likely job-related.

    This is a preliminary filter, not the full classification.
    Used to prioritize emails for detailed classification.
    """
    # Check sender domain
    sender_email = parsed.sender_email.lower()
    for domain in JOB_RELATED_DOMAINS:
        if domain in sender_email:
            return True

    # Check subject
    subject_lower = parsed.subject.lower()
    for pattern in JOB_SUBJECT_PATTERNS:
        if re.search(pattern, subject_lower, re.IGNORECASE):
            return True

    return False


# =============================================================================
# Singleton Parser
# =============================================================================

# Global parser instance
_parser: Optional[EmailParser] = None


def get_parser() -> EmailParser:
    """Get singleton parser instance."""
    global _parser
    if _parser is None:
        _parser = EmailParser()
    return _parser
