"""
Tests for email client modules.

These tests use mocks to avoid requiring real email credentials.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jobtracker.email_clients import EmailParser, ParsedEmail
from jobtracker.email_clients.gmail import GmailClient, GmailMessage
from jobtracker.email_clients.icloud import ICloudClient, IMAPMessage
from jobtracker.email_clients.parser import (
    generate_dedup_key,
    is_likely_job_related,
)


# =============================================================================
# Email Parser Tests
# =============================================================================


class TestEmailParser:
    """Tests for the unified email parser."""

    def test_parser_from_gmail(self):
        """Test parsing Gmail message to unified format."""
        parser = EmailParser()

        gmail_msg = GmailMessage(
            message_id="12345abc",
            thread_id="thread-123",
            subject="Your application to Acme Corp",
            sender_name="HR Team",
            sender_email="hr@acme.com",
            received_at=datetime(2026, 2, 9, 10, 30),
            body_text="Thank you for applying to Acme Corp.",
            body_snippet="Thank you for applying...",
            raw_headers={"from": "HR Team <hr@acme.com>"},
        )

        parsed = parser.from_gmail(gmail_msg)

        assert parsed.source_account == "gmail"
        assert "gmail:" in parsed.message_id
        assert parsed.thread_id == "thread-123"
        assert parsed.subject == "Your application to Acme Corp"
        assert parsed.sender_email == "hr@acme.com"

    def test_parser_from_icloud(self):
        """Test parsing IMAP message to unified format."""
        parser = EmailParser()

        imap_msg = IMAPMessage(
            uid=54321,
            message_id="<unique@example.com>",
            subject="Interview Invitation",
            sender_name="Recruiter",
            sender_email="recruiter@company.com",
            received_at=datetime(2026, 2, 9, 14, 0),
            body_text="We would like to schedule an interview.",
            body_snippet="We would like to schedule...",
            raw_headers={"from": "Recruiter <recruiter@company.com>"},
        )

        parsed = parser.from_icloud(imap_msg)

        assert parsed.source_account == "icloud"
        assert "icloud:" in parsed.message_id
        assert parsed.thread_id is None  # IMAP doesn't have threads
        assert parsed.subject == "Interview Invitation"
        assert parsed.sender_email == "recruiter@company.com"

    def test_clean_subject(self):
        """Test subject cleaning."""
        parser = EmailParser()

        # Empty subject
        assert parser._clean_subject("") == "(No Subject)"
        assert parser._clean_subject(None) == "(No Subject)"

        # Normal subject
        assert parser._clean_subject("Hello World") == "Hello World"

        # Whitespace normalization
        assert parser._clean_subject("Hello    World") == "Hello World"

    def test_normalize_email(self):
        """Test email normalization."""
        parser = EmailParser()

        assert parser._normalize_email("Test@Example.COM") == "test@example.com"
        assert parser._normalize_email("  email@test.com  ") == "email@test.com"
        assert parser._normalize_email("") == ""


class TestDeduplication:
    """Tests for email deduplication."""

    def test_generate_dedup_key(self):
        """Test deduplication key generation."""
        parsed = ParsedEmail(
            source_account="gmail",
            message_id="gmail:12345",
            thread_id=None,
            subject="Test",
            sender_name=None,
            sender_email="test@test.com",
            received_at=datetime.now(),
            body_text="Test body",
            body_snippet="Test body",
            raw_headers={},
        )

        key = generate_dedup_key(parsed)
        assert key == "gmail:12345"

    def test_different_sources_different_keys(self):
        """Test that same message from different sources has different keys."""
        base = {
            "thread_id": None,
            "subject": "Test",
            "sender_name": None,
            "sender_email": "test@test.com",
            "received_at": datetime.now(),
            "body_text": "Test body",
            "body_snippet": "Test body",
            "raw_headers": {},
        }

        gmail = ParsedEmail(source_account="gmail", message_id="gmail:123", **base)
        icloud = ParsedEmail(source_account="icloud", message_id="icloud:123", **base)

        assert generate_dedup_key(gmail) != generate_dedup_key(icloud)


class TestJobRelatedDetection:
    """Tests for job-related email detection."""

    def test_detect_ats_domain(self):
        """Test detection of ATS email domains."""
        parsed = ParsedEmail(
            source_account="gmail",
            message_id="gmail:123",
            thread_id=None,
            subject="Regular email",
            sender_name=None,
            sender_email="noreply@greenhouse.io",
            received_at=datetime.now(),
            body_text="Generic content",
            body_snippet="Generic...",
            raw_headers={},
        )

        assert is_likely_job_related(parsed) is True

    def test_detect_job_subject(self):
        """Test detection of job-related subject."""
        parsed = ParsedEmail(
            source_account="gmail",
            message_id="gmail:123",
            thread_id=None,
            subject="Your application has been received",
            sender_name=None,
            sender_email="hr@random-company.com",
            received_at=datetime.now(),
            body_text="Thanks for applying",
            body_snippet="Thanks...",
            raw_headers={},
        )

        assert is_likely_job_related(parsed) is True

    def test_non_job_email(self):
        """Test that regular emails are not flagged."""
        parsed = ParsedEmail(
            source_account="gmail",
            message_id="gmail:123",
            thread_id=None,
            subject="Your order has shipped",
            sender_name=None,
            sender_email="noreply@amazon.com",
            received_at=datetime.now(),
            body_text="Your package is on the way",
            body_snippet="Your package...",
            raw_headers={},
        )

        assert is_likely_job_related(parsed) is False


# =============================================================================
# Gmail Client Tests (Mocked)
# =============================================================================


class TestGmailClient:
    """Tests for Gmail client with mocked API."""

    def test_is_authenticated_no_creds(self):
        """Test authentication check with no credentials."""
        with patch(
            "jobtracker.email_clients.gmail.get_gmail_credentials", return_value=None
        ):
            client = GmailClient()
            assert client.is_authenticated() is False

    def test_is_authenticated_with_creds(self):
        """Test authentication check with credentials."""
        mock_creds = MagicMock()
        mock_creds.email = "test@gmail.com"

        with patch(
            "jobtracker.email_clients.gmail.get_gmail_credentials",
            return_value=mock_creds,
        ):
            client = GmailClient()
            assert client.is_authenticated() is True


# =============================================================================
# iCloud Client Tests (Mocked)
# =============================================================================


class TestICloudClient:
    """Tests for iCloud client with mocked IMAP."""

    def test_has_credentials_no_creds(self):
        """Test credentials check with no credentials."""
        with patch(
            "jobtracker.email_clients.icloud.get_icloud_credentials",
            return_value=None,
        ):
            client = ICloudClient()
            assert client.has_credentials() is False

    def test_has_credentials_with_creds(self):
        """Test credentials check with credentials."""
        mock_creds = MagicMock()
        mock_creds.email = "test@icloud.com"

        with patch(
            "jobtracker.email_clients.icloud.get_icloud_credentials",
            return_value=mock_creds,
        ):
            client = ICloudClient()
            assert client.has_credentials() is True

    def test_get_account_email(self):
        """Test getting account email."""
        mock_creds = MagicMock()
        mock_creds.email = "test@icloud.com"

        with patch(
            "jobtracker.email_clients.icloud.get_icloud_credentials",
            return_value=mock_creds,
        ):
            client = ICloudClient()
            assert client.get_account_email() == "test@icloud.com"
