"""
Tests for email client modules.

These tests use mocks to avoid requiring real email credentials.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

from jobtracker.email_clients import EmailParser, ParsedEmail
from jobtracker.email_clients.gmail import MAX_RETRIES, GmailClient, GmailMessage
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

    def test_clean_body_decodes_qp_and_removes_mime_scaffolding(self):
        """Quoted-printable MIME wrappers are decoded into readable text."""
        parser = EmailParser()
        raw_body = (
            "------=_Part_99256_1978143042.1770834668631\n"
            "Content-Type: text/plain;charset=UTF-8\n"
            "Content-Transfer-Encoding: quoted-printable\n"
            "Content-ID: text-body\n\n"
            "Your application was sent to Emonics LLC=0A"
            "Python Developer, Entry Level=0A"
            "Emonics LLC=0A"
            "New York, United States=0A"
            "View job:=20https://www.linkedin.com/jobs/view/123=0A"
            "We=E2=80=99ll review your profile.\n"
        )

        cleaned = parser._clean_body(raw_body)

        assert "Content-Type" not in cleaned
        assert "=_Part_" not in cleaned
        assert "We’ll review your profile." in cleaned
        assert "Python Developer, Entry Level" in cleaned


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

    @staticmethod
    def _make_http_error(status: int, reason: str) -> HttpError:
        response = httplib2.Response({"status": str(status)})
        payload = {
            "error": {
                "code": status,
                "message": reason,
                "errors": [{"reason": reason}],
            }
        }
        return HttpError(response, json.dumps(payload).encode("utf-8"), uri="test://gmail")

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

    def test_retryable_http_error_detection(self):
        """Gmail quota/rate errors should be classified as retryable."""
        client = GmailClient()

        assert client._is_retryable_http_error(
            self._make_http_error(429, "rateLimitExceeded")
        )
        assert client._is_retryable_http_error(
            self._make_http_error(403, "userRateLimitExceeded")
        )
        assert not client._is_retryable_http_error(
            self._make_http_error(403, "forbidden")
        )

    @pytest.mark.asyncio
    async def test_execute_with_backoff_retries_then_succeeds(self):
        """Retryable HTTP errors should back off and retry."""
        client = GmailClient()
        rate_limited = self._make_http_error(429, "rateLimitExceeded")
        client._run_google_execute = AsyncMock(
            side_effect=[rate_limited, {"ok": True}]
        )

        with patch("jobtracker.email_clients.gmail.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            with patch("jobtracker.email_clients.gmail.random.uniform", return_value=0.0):
                result = await client._execute_with_backoff(lambda: {"ok": True}, "test.op")

        assert result == {"ok": True}
        assert client._run_google_execute.await_count == 2
        sleep_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_with_backoff_stops_after_max_retries(self):
        """Retry loop should re-raise once retry budget is exhausted."""
        client = GmailClient()
        rate_limited = self._make_http_error(429, "rateLimitExceeded")
        client._run_google_execute = AsyncMock(
            side_effect=[rate_limited] * MAX_RETRIES
        )

        with patch("jobtracker.email_clients.gmail.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            with patch("jobtracker.email_clients.gmail.random.uniform", return_value=0.0):
                with pytest.raises(HttpError):
                    await client._execute_with_backoff(lambda: {"ok": True}, "test.op")

        assert client._run_google_execute.await_count == MAX_RETRIES
        assert sleep_mock.await_count == MAX_RETRIES - 1


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

    @pytest.mark.asyncio
    async def test_fetch_emails_selects_inbox(self):
        """Fetching should select the requested mailbox before searching."""
        client = ICloudClient()
        client._connected = True

        mock_imap = MagicMock()
        mock_imap.select = AsyncMock(return_value=MagicMock(result="OK", lines=[]))
        mock_imap.search = AsyncMock(return_value=MagicMock(result="OK", lines=[b""]))
        client._imap = mock_imap

        messages, highest_uid = await client.fetch_emails()

        assert messages == []
        assert highest_uid == 0
        mock_imap.select.assert_awaited_once_with("INBOX")

    @pytest.mark.asyncio
    async def test_fetch_message_uses_body_peek(self):
        """Message fetch should use BODY.PEEK so IMAP does not mark as seen."""
        client = ICloudClient()
        client._connected = True
        client._imap = MagicMock()
        client._imap.fetch = AsyncMock(return_value=MagicMock(result="OK", lines=[]))

        expected = IMAPMessage(
            uid=42,
            message_id="msg-42",
            subject="Subject",
            sender_name="Sender",
            sender_email="sender@example.com",
            received_at=datetime(2026, 2, 10, 12, 0, 0),
            body_text="Body",
            body_snippet="Body",
            raw_headers={},
        )

        with patch.object(client, "_parse_fetch_response", return_value=expected):
            result = await client._fetch_message(123)

        assert result == expected
        client._imap.fetch.assert_awaited_once_with(
            "123", "(UID BODY.PEEK[])"
        )

    def test_replace_cid_sources_in_html(self):
        """CID references in HTML should be replaced with inline data URLs."""
        client = ICloudClient()
        html = '<p><img src="cid:logo-1"></p>'
        data_map = {"logo-1": "data:image/png;base64,abcd"}

        rendered = client._replace_cid_sources(html, data_map)

        assert "cid:logo-1" not in rendered
        assert "data:image/png;base64,abcd" in rendered
