from datetime import datetime

from jobtracker.database.models import Email, EmailSource
from jobtracker.email_clients import ParsedEmail
from jobtracker.services.sync import SyncService


class TestSyncServiceDuplicateEnrichment:
    def test_merge_existing_email_content_backfills_missing_fields(self):
        service = SyncService()

        existing = Email(
            source_account=EmailSource.ICLOUD,
            message_id="icloud:test-1",
            subject="Subject",
            sender_email="jobs-noreply@linkedin.com",
            received_at=datetime.utcnow(),
            body_text="short body",
            body_html=None,
            body_snippet=None,
            raw_headers=None,
        )

        parsed = ParsedEmail(
            source_account="icloud",
            message_id="icloud:test-1",
            thread_id=None,
            subject="Subject",
            sender_name="LinkedIn",
            sender_email="jobs-noreply@linkedin.com",
            received_at=datetime.utcnow(),
            body_text="longer body content " * 80,
            body_snippet="clean snippet",
            raw_headers={"content-type": "multipart/alternative"},
            body_html="<html><body><p>Rendered HTML</p></body></html>",
        )

        changed = service._merge_existing_email_content(existing, parsed)

        assert changed is True
        assert existing.body_html is not None
        assert "Rendered HTML" in existing.body_html
        assert existing.body_text is not None
        assert len(existing.body_text) > 500
        assert existing.body_snippet == "clean snippet"
        assert existing.sender_name == "LinkedIn"
        assert existing.raw_headers is not None

    def test_merge_existing_email_content_keeps_richer_existing_payload(self):
        service = SyncService()

        existing = Email(
            source_account=EmailSource.GMAIL,
            message_id="gmail:test-2",
            subject="Subject",
            sender_email="sender@example.com",
            received_at=datetime.utcnow(),
            body_text="existing " * 200,
            body_html="<html><body>existing</body></html>",
            body_snippet="existing snippet",
            raw_headers="{'x-test':'1'}",
        )

        parsed = ParsedEmail(
            source_account="gmail",
            message_id="gmail:test-2",
            thread_id="abc",
            subject="Subject",
            sender_name="Sender",
            sender_email="sender@example.com",
            received_at=datetime.utcnow(),
            body_text="short incoming",
            body_snippet="incoming snippet",
            raw_headers={"x-test": "2"},
            body_html="<html><body>incoming</body></html>",
        )

        changed = service._merge_existing_email_content(existing, parsed)

        assert changed is True  # thread_id and sender_name can still be enriched
        assert existing.body_text is not None
        assert len(existing.body_text) > len("short incoming")
        assert existing.body_html == "<html><body>existing</body></html>"
        assert existing.body_snippet == "existing snippet"
        assert existing.thread_id == "abc"
        assert existing.sender_name == "Sender"
