"""
Tests for Phase 5+ API endpoints.

Covers:
- WebSocket sync status stream
- Review queue and application-linking regressions
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import select, text

from jobtracker.database import get_session, init_db
from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Contact,
    ContactRole,
    Email,
    EmailCategory,
    EmailSource,
    Interview,
    InterviewStatus,
    InterviewType,
)
from jobtracker.main import app
from jobtracker.tracking import get_application_linker
from jobtracker.tracking.extractor import extract_company_and_position


async def _reset_analytics_tables() -> None:
    await init_db()
    async with get_session() as session:
        await session.exec(text("DELETE FROM contacts"))
        await session.exec(text("DELETE FROM interviews"))
        await session.exec(text("DELETE FROM email_embeddings"))
        await session.exec(text("DELETE FROM emails"))
        await session.exec(text("DELETE FROM applications"))
        await session.exec(text("DELETE FROM training_data"))
        await session.commit()


class TestAnalyticsDeScoped:
    @pytest.mark.asyncio
    async def test_overview_endpoint_not_exposed(self, test_client: AsyncClient):
        response = await test_client.get("/analytics/overview")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_trends_endpoint_not_exposed(self, test_client: AsyncClient):
        response = await test_client.get("/analytics/trends?period=weekly&months=3")
        assert response.status_code == 404


class TestSyncWebSocket:
    def test_sync_status_websocket_connects(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/sync-status") as websocket:
                payload = websocket.receive_json()
                assert payload["event"] == "connected"
                assert "timestamp" in payload


class TestReviewQueueAPI:
    @pytest.mark.asyncio
    async def test_needs_review_includes_full_body(self, test_client: AsyncClient):
        await _reset_analytics_tables()

        now = datetime.utcnow()

        async with get_session() as session:
            review_email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<needs-review-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Please pick an interview slot",
                sender_email="recruiter@acme.com",
                classified_as=EmailCategory.INTERVIEW,
                classification_confidence=0.42,
                body_snippet="Interview scheduling details",
                body_text="Full email body with scheduling options and interview context.",
                user_corrected=False,
            )
            session.add(review_email)
            await session.commit()

        response = await test_client.get("/classify/needs-review?limit=10&offset=0")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_count"] == 1
        assert payload["emails"][0]["current_category"] == "interview"
        assert payload["emails"][0]["snippet"] == "Interview scheduling details"
        assert payload["emails"][0]["body_text"] == (
            "Full email body with scheduling options and interview context."
        )

    @pytest.mark.asyncio
    async def test_needs_review_count_handles_enum_storage_case(self, test_client: AsyncClient):
        await _reset_analytics_tables()

        now = datetime.utcnow()

        async with get_session() as session:
            review_email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<needs-review-count-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Interview follow-up",
                sender_email="recruiter@acme.com",
                classified_as=EmailCategory.INTERVIEW,
                classification_confidence=0.35,
                user_corrected=False,
            )
            session.add(review_email)
            await session.commit()

        response = await test_client.get("/classify/needs-review/count")
        assert response.status_code == 200
        payload = response.json()
        assert payload["needs_review_count"] == 1

    @pytest.mark.asyncio
    async def test_needs_review_threshold_is_85_percent(self, test_client: AsyncClient):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            low_confidence = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<needs-review-threshold-low-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Application update",
                sender_email="recruiter@acme.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.84,
                body_text="Your application is under review.",
                user_corrected=False,
            )
            high_confidence = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<needs-review-threshold-high-{now.timestamp()}@test.com>",
                received_at=now + timedelta(minutes=1),
                subject="Application update",
                sender_email="recruiter@acme.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.90,
                body_text="Your application is under review.",
                user_corrected=False,
            )
            session.add(low_confidence)
            session.add(high_confidence)
            await session.commit()

        count_response = await test_client.get("/classify/needs-review/count")
        assert count_response.status_code == 200
        count_payload = count_response.json()
        assert count_payload["needs_review_count"] == 1

        list_response = await test_client.get("/classify/needs-review?limit=20&offset=0")
        assert list_response.status_code == 200
        list_payload = list_response.json()
        assert list_payload["total_count"] == 1
        assert list_payload["emails"][0]["confidence"] == pytest.approx(0.84, abs=1e-6)

    @pytest.mark.asyncio
    async def test_approve_review_queue_item_adds_training_signal(
        self,
        test_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await _reset_analytics_tables()
        now = datetime.utcnow()
        from jobtracker.api import classification as classification_api

        mock_classifier = SimpleNamespace(add_correction=AsyncMock())
        monkeypatch.setattr(classification_api, "get_classifier", lambda: mock_classifier)

        async with get_session() as session:
            email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<approve-needs-review-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Interview scheduling for Acme",
                sender_email="recruiter@acme.com",
                classified_as=EmailCategory.INTERVIEW,
                classification_confidence=0.45,
                body_text="Please select your preferred interview time.",
                user_corrected=False,
                is_reviewed=False,
            )
            session.add(email)
            await session.commit()
            await session.refresh(email)
            email_id = email.id

        response = await test_client.post(f"/classify/needs-review/{email_id}/approve")
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["approved_category"] == "interview"
        assert mock_classifier.add_correction.await_count == 1

        correction_call = mock_classifier.add_correction.await_args_list[0]
        assert correction_call.args[0] == email_id
        assert correction_call.args[1] == "Interview scheduling for Acme"
        assert correction_call.args[2] == "Please select your preferred interview time."
        assert correction_call.args[3] == EmailCategory.INTERVIEW

        async with get_session() as session:
            result = await session.exec(select(Email).where(Email.id == email_id))
            row = result.first()
            assert row is not None
            stored = row[0] if hasattr(row, "__getitem__") else row
            assert stored.user_corrected is True
            assert stored.is_reviewed is True
            assert stored.classification_method == "user"
            assert stored.classification_confidence == pytest.approx(1.0, abs=1e-6)


class TestClassificationGuards:
    @pytest.mark.asyncio
    async def test_job_alert_digest_classified_as_other(self, test_client: AsyncClient):
        response = await test_client.post(
            "/classify",
            json={
                "subject": "LinkedIn Job Alerts: 25 new roles for you",
                "body": (
                    "Jobs you may be interested in. View all jobs and manage "
                    "preferences. Unsubscribe anytime."
                ),
                "sender_email": "jobalerts-noreply@linkedin.com",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["category"] == "other"


class TestClassificationRegressions:
    @pytest.mark.asyncio
    async def test_fanduel_application_confirmation_not_classified_as_other(
        self,
        test_client: AsyncClient,
    ):
        response = await test_client.post(
            "/classify",
            json={
                "subject": "Thank you for applying to FanDuel",
                "body": (
                    "Hi Ayush, thank you for your interest in FanDuel and for your "
                    "application to our Software Engineer role. "
                    "Our Talent Acquisition team will review your details. "
                    "Manage preferences: unsubscribe"
                ),
                "sender_email": "no-reply@fanduel.com",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["category"] == "applied"

    @pytest.mark.asyncio
    async def test_linkedin_application_sent_not_classified_as_other(
        self,
        test_client: AsyncClient,
    ):
        response = await test_client.post(
            "/classify",
            json={
                "subject": "Ayush, your application was sent to Fanduel Inc.",
                "body": (
                    "Your application was sent to Fanduel Inc. Software Engineer. "
                    "View job and send a message. Unsubscribe from these updates."
                ),
                "sender_email": "jobs-noreply@linkedin.com",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["category"] == "applied"

    @pytest.mark.asyncio
    async def test_application_for_position_at_company_subject_prefers_applied(
        self,
        test_client: AsyncClient,
    ):
        response = await test_client.post(
            "/classify",
            json={
                "subject": "Your application for IT Operations Engineer at Superhuman",
                "body": (
                    "Thanks for applying. We will review your application and "
                    "reach out with next steps."
                ),
                "sender_email": "no-reply@us.greenhouse-mail.io",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["category"] == "applied"

    @pytest.mark.asyncio
    async def test_application_to_position_at_company_subject_prefers_applied(
        self,
        test_client: AsyncClient,
    ):
        response = await test_client.post(
            "/classify",
            json={
                "subject": "Your application to Founding Software Engineer at Axiom (YC W25)",
                "body": "Your application has been received and is under review.",
                "sender_email": "jobs-noreply@linkedin.com",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["category"] == "applied"

    @pytest.mark.asyncio
    async def test_incomplete_application_prompt_classified_as_pending_application(
        self,
        test_client: AsyncClient,
    ):
        response = await test_client.post(
            "/classify",
            json={
                "subject": "Complete your application for Software Engineer",
                "body": (
                    "You're almost done. Please complete your application "
                    "before we can review your candidacy."
                ),
                "sender_email": "notifications@greenhouse.io",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["category"] == "pending_application"

class TestExtractionRegressions:
    def test_extract_company_from_thank_you_from_subject(self):
        extraction = extract_company_and_position(
            "no-reply@join.matchgroupcareers.com",
            "Thank You from Tinder",
            (
                "Thank you so much for taking the time to meet our team. "
                "We are excited for your future as our candidate."
            ),
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "tinder"

    def test_extract_company_from_application_to_position_at_company_subject(self):
        extraction = extract_company_and_position(
            "jobs-noreply@linkedin.com",
            "Your application to Machine Learning Research Engineer - Training at EPM Scientific",
            "This is your update from EPM Scientific.",
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "epm scientific"
        assert extraction.position is not None
        assert "machine learning research engineer" in extraction.position.lower()

    def test_extract_company_from_workday_submission_template_body(self):
        extraction = extract_company_and_position(
            "hpe@myworkday.com",
            "Thank you for your online submission",
            (
                "Dear Ayush, Thank you for your interest in working with "
                "Hewlett Packard Enterprise. A recruiter will contact you."
            ),
            sender_name="Hewlett Packard Enterprise",
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "hewlett packard enterprise"

    def test_extract_company_and_position_from_joining_us_here_at_template(self):
        extraction = extract_company_and_position(
            "no-reply@ashbyhq.com",
            "We received your application for Software Engineer (entry)!",
            (
                "Thank you for your interest in joining us here at Jerry! "
                "We have received your application to the Software Engineer "
                "(entry) position."
            ),
            sender_name="Jerry",
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "jerry"
        assert extraction.position is not None
        assert "software engineer" in extraction.position.lower()

    def test_position_extraction_ignores_selection_process_phrase(self):
        extraction = extract_company_and_position(
            "no-reply@stubhub.com",
            "Thank you for applying to StubHub",
            (
                "Thank you for applying for the Software Engineer I - Marketplace "
                "Operations (New Grad) role at StubHub! We are currently reviewing "
                "applications and will keep you updated on your status as we move "
                "through the selection process."
            ),
        )

        assert extraction.position is not None
        assert "software engineer" in extraction.position.lower()
        assert "selection process" not in extraction.position.lower()

    def test_extract_company_and_position_from_application_for_subject(self):
        extraction = extract_company_and_position(
            "no-reply@us.greenhouse-mail.io",
            "Your application for IT Operations Engineer at Superhuman",
            "Thanks for applying.",
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "superhuman"
        assert extraction.position is not None
        assert "it operations engineer" in extraction.position.lower()

    def test_extract_company_and_position_with_parenthetical_company_suffix(self):
        extraction = extract_company_and_position(
            "jobs-noreply@linkedin.com",
            "Your application to Founding Software Engineer at Axiom (YC W25)",
            "Application confirmation",
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "axiom"
        assert extraction.position is not None
        assert "founding software engineer" in extraction.position.lower()

    def test_extract_company_and_position_from_linkedin_update_subject(self):
        extraction = extract_company_and_position(
            "jobs-noreply@linkedin.com",
            "Update on your application at Superhuman",
            (
                "Your application to Software Engineer, Backend at Superhuman "
                "was viewed by the hiring team."
            ),
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "superhuman"
        assert extraction.position is not None
        assert "software engineer" in extraction.position.lower()

    def test_extract_position_from_application_sent_to_company_for_role(self):
        extraction = extract_company_and_position(
            "jobs-noreply@linkedin.com",
            "Your application was sent to Nuro",
            (
                "Good news. Your application was sent to Nuro for Senior "
                "Software Engineer role."
            ),
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "nuro"
        assert extraction.position is not None
        assert "software engineer" in extraction.position.lower()

    def test_extract_position_from_linkedin_multiline_confirmation_block(self):
        extraction = extract_company_and_position(
            "jobs-noreply@linkedin.com",
            "Ayush , your application was sent to Emonics LLC",
            (
                "Your application was sent to Emonics LLC\n"
                "Python Developer, Entry Level\n"
                "Emonics LLC\n"
                "New York, United States\n"
                "View job: https://www.linkedin.com/comm/jobs/view/123"
            ),
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "emonics"
        assert extraction.position is not None
        assert "python developer" in extraction.position.lower()

    def test_extract_position_from_linkedin_one_line_confirmation_block(self):
        extraction = extract_company_and_position(
            "jobs-noreply@linkedin.com",
            "Ayush , your application was sent to Verkada",
            (
                "Your application was sent to Verkada Associate Solutions Engineer, "
                "San Mateo Verkada San Mateo, CA View job: "
                "https://www.linkedin.com/comm/jobs/view/3765968680/"
            ),
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "verkada"
        assert extraction.position is not None
        assert "associate solutions engineer" in extraction.position.lower()

    def test_extract_position_from_thank_you_subject_with_dash(self):
        extraction = extract_company_and_position(
            "no-reply@asm.com",
            "Thank you for applying to ASM - Software Engineer - Early Career (Spring 2026)",
            "Thank you for applying.",
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "asm"
        assert extraction.position is not None
        assert "software engineer" in extraction.position.lower()

    def test_extract_company_ignores_position_of_phrase(self):
        extraction = extract_company_and_position(
            "hpe@myworkday.com",
            "Thank you for your application to 1202397 Software Engineer I",
            (
                "Thank you for your interest in the Hewlett Packard Enterprise (HPE) "
                "position of 1202397 Software Engineer I."
            ),
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "hewlett packard enterprise (hpe)"
        assert extraction.position is not None
        assert "software engineer" in extraction.position.lower()

    def test_extract_position_with_comma_from_role_at_company_template(self):
        extraction = extract_company_and_position(
            "no-reply@us.greenhouse-mail.io",
            "Thank you for applying to Verkada",
            (
                "Thank you so much for applying to the Associate Solutions Engineer, "
                "San Mateo role at Verkada!"
            ),
        )

        assert extraction.company is not None
        assert extraction.company.lower() == "verkada"
        assert extraction.position is not None
        assert "associate solutions engineer, san mateo" in extraction.position.lower()

    def test_extract_company_from_a_career_at_template(self):
        extraction = extract_company_and_position(
            "rbc@myworkday.com",
            "Thank You For Applying!",
            (
                "A career at RBC is an opportunity to shape the future. "
                "We have received your application for the Junior AI Engineer role."
            ),
            sender_name="Workday",
        )

        assert extraction.company is not None
        assert extraction.company == "RBC"
        assert extraction.position is not None
        assert "junior ai engineer" in extraction.position.lower()


class TestApplicationDetailAndActions:
    @pytest.mark.asyncio
    async def test_application_detail_includes_full_email_body(self, test_client: AsyncClient):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            app_row = Application(
                company="Acme Corp",
                position="Software Engineer",
                status=ApplicationStatus.INTERVIEWING,
                applied_date=date.today() - timedelta(days=10),
            )
            session.add(app_row)
            await session.commit()
            await session.refresh(app_row)

            email_row = Email(
                application_id=app_row.id,
                source_account=EmailSource.GMAIL,
                message_id=f"<detail-email-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Interview invitation",
                sender_email="recruiter@acme.com",
                classified_as=EmailCategory.INTERVIEW,
                classification_confidence=0.91,
                body_snippet="Quick snippet",
                body_text="Full email body with interview details and scheduling context.",
            )
            session.add(email_row)
            await session.commit()

        response = await test_client.get(f"/applications/{app_row.id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["email_count"] == 1
        assert payload["emails"][0]["body_text"] == (
            "Full email body with interview details and scheduling context."
        )
        assert payload["emails"][0]["body_snippet"] == "Quick snippet"
        assert payload["emails"][0]["confidence"] == pytest.approx(0.91, abs=1e-6)

    @pytest.mark.asyncio
    async def test_mark_not_job_reclassifies_emails_and_removes_application(
        self,
        test_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await _reset_analytics_tables()
        now = datetime.utcnow()
        from jobtracker.api import applications as applications_api

        mock_classifier = SimpleNamespace(add_correction=AsyncMock())
        monkeypatch.setattr(applications_api, "get_classifier", lambda: mock_classifier)

        async with get_session() as session:
            app_row = Application(
                company="Noise Corp",
                position="Unknown Position",
                status=ApplicationStatus.APPLIED,
                applied_date=date.today(),
            )
            session.add(app_row)
            await session.commit()
            await session.refresh(app_row)

            email_row = Email(
                application_id=app_row.id,
                source_account=EmailSource.GMAIL,
                message_id=f"<mark-not-job-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Weekly digest",
                sender_email="newsletter@example.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.62,
            )
            session.add(email_row)
            await session.commit()
            await session.refresh(email_row)
            email_id = email_row.id

        response = await test_client.post(f"/applications/{app_row.id}/mark-not-job")
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["emails_reclassified"] == 1
        assert mock_classifier.add_correction.await_count == 1
        correction_call = mock_classifier.add_correction.await_args_list[0]
        assert correction_call.args[0] == email_id
        assert correction_call.args[3] == EmailCategory.OTHER

        async with get_session() as session:
            app_check = await session.exec(
                select(Application).where(Application.id == app_row.id)
            )
            assert app_check.first() is None

            email_check = await session.exec(select(Email).where(Email.id == email_id))
            row = email_check.first()
            assert row is not None
            email = row[0] if hasattr(row, "__getitem__") else row
            assert email.application_id is None
            assert email.classified_as == EmailCategory.OTHER
            assert email.user_corrected is True


class TestApplicationChildRowsOnDelete:
    """The desktop half of "deleting an application orphans or 500s its children".

    ``contacts.application_id`` and ``interviews.application_id`` are NOT NULL
    foreign keys onto ``applications.id``, and the desktop linker
    (``jobtracker/tracking/linker.py``) is what writes both. Neither endpoint
    that removes an application used to touch them, so SQLAlchemy's default
    cascade tried to de-associate the children by nulling their FK and the flush
    raised — a 500, with the application still on the board.

    Emails are treated differently ON PURPOSE and that difference is not an
    oversight: ``emails.application_id`` is Optional, and the desktop database is
    the user's own mail archive, so a message survives the application being
    removed. A contact and an interview have no such life of their own — the
    column cannot be nulled — so the only two answers available are "delete with
    the parent" or "refuse the delete", and both endpoints here are already the
    explicitly-destructive action.
    """

    @pytest.mark.asyncio
    async def test_mark_not_job_deletes_required_children_before_app_delete(
        self,
        test_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await _reset_analytics_tables()
        now = datetime.utcnow()
        from jobtracker.api import applications as applications_api

        mock_classifier = SimpleNamespace(add_correction=AsyncMock())
        monkeypatch.setattr(applications_api, "get_classifier", lambda: mock_classifier)

        async with get_session() as session:
            app_row = Application(
                company="Noise Corp",
                position="Unknown Position",
                status=ApplicationStatus.APPLIED,
                applied_date=date.today(),
            )
            session.add(app_row)
            await session.commit()
            await session.refresh(app_row)

            session.add(
                Email(
                    application_id=app_row.id,
                    source_account=EmailSource.GMAIL,
                    message_id=f"<not-job-children-{now.timestamp()}@test.com>",
                    received_at=now,
                    subject="Weekly digest",
                    sender_email="newsletter@example.com",
                    classified_as=EmailCategory.APPLIED,
                    classification_confidence=0.62,
                )
            )
            session.add(
                Contact(
                    application_id=app_row.id,
                    name="Dana Recruiter",
                    email="dana@noisecorp.example",
                    role=ContactRole.RECRUITER,
                )
            )
            session.add(
                Interview(
                    application_id=app_row.id,
                    type=InterviewType.PHONE,
                    scheduled_at=now,
                    status=InterviewStatus.SCHEDULED,
                )
            )
            await session.commit()

        response = await test_client.post(f"/applications/{app_row.id}/mark-not-job")
        assert response.status_code == 200, response.text
        assert response.json()["emails_reclassified"] == 1

        async with get_session() as session:
            remaining_app = (
                await session.exec(
                    select(Application).where(Application.id == app_row.id)
                )
            ).first()
            assert remaining_app is None
            contacts = (
                await session.exec(
                    select(Contact).where(Contact.application_id == app_row.id)
                )
            ).all()
            interviews = (
                await session.exec(
                    select(Interview).where(Interview.application_id == app_row.id)
                )
            ).all()
            assert contacts == []
            assert interviews == []

    @pytest.mark.asyncio
    async def test_delete_application_deletes_required_children(
        self,
        test_client: AsyncClient,
    ):
        """The site PR #12 did not cover: plain ``DELETE /applications/{id}``.

        Same schema, same NOT NULL children, same failure — one endpoint over.
        """

        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            app_row = Application(
                company="Acme",
                position="Backend Engineer",
                status=ApplicationStatus.APPLIED,
                applied_date=date.today(),
            )
            session.add(app_row)
            await session.commit()
            await session.refresh(app_row)

            mail = Email(
                application_id=app_row.id,
                source_account=EmailSource.GMAIL,
                message_id=f"<delete-children-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Thanks for applying",
                sender_email="jobs@acme.example",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.9,
            )
            session.add(mail)
            session.add(
                Contact(
                    application_id=app_row.id,
                    name="Dana Recruiter",
                    email="dana@acme.example",
                    role=ContactRole.RECRUITER,
                )
            )
            session.add(
                Interview(
                    application_id=app_row.id,
                    type=InterviewType.TECHNICAL,
                    scheduled_at=now,
                    status=InterviewStatus.SCHEDULED,
                )
            )
            await session.commit()
            await session.refresh(mail)
            email_id = mail.id

        response = await test_client.delete(f"/applications/{app_row.id}")
        assert response.status_code == 204, response.text

        async with get_session() as session:
            assert (
                await session.exec(
                    select(Application).where(Application.id == app_row.id)
                )
            ).first() is None
            assert (
                await session.exec(
                    select(Contact).where(Contact.application_id == app_row.id)
                )
            ).all() == []
            assert (
                await session.exec(
                    select(Interview).where(Interview.application_id == app_row.id)
                )
            ).all() == []
            # The desktop contract for mail is UNLINK, not delete — the local
            # database is the user's own archive.
            kept = (await session.exec(select(Email).where(Email.id == email_id))).first()
            assert kept is not None
            mail_row = kept[0] if hasattr(kept, "__getitem__") else kept
            assert mail_row.application_id is None


class TestAnalyticsTrendsDeScoped:
    @pytest.mark.asyncio
    async def test_trends_sorted_and_deduplicated_per_app_category_week(
        self,
        test_client: AsyncClient,
    ):
        response = await test_client.get("/analytics/trends?period=weekly&months=3")
        assert response.status_code == 404


class TestLinkingBehavior:
    @pytest.mark.asyncio
    async def test_applied_emails_same_company_without_position_create_separate_apps(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            first_email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<nuro-1-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Your application has been received",
                sender_email="jobs@nuro.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.9,
                body_text="Thank you for applying to Nuro.",
            )
            second_email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<nuro-2-{now.timestamp()}@test.com>",
                received_at=now + timedelta(minutes=1),
                subject="Your application has been received",
                sender_email="jobs@nuro.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.91,
                body_text="Thanks for applying to Nuro.",
            )
            session.add(first_email)
            session.add(second_email)
            await session.commit()
            await session.refresh(first_email)
            await session.refresh(second_email)

            first_id = first_email.id
            second_id = second_email.id

        linker = get_application_linker()

        async with get_session() as session:
            first_loaded = (await session.exec(select(Email).where(Email.id == first_id))).first()
            second_loaded = (await session.exec(select(Email).where(Email.id == second_id))).first()

        assert first_loaded is not None
        assert second_loaded is not None

        first_loaded = first_loaded[0] if hasattr(first_loaded, "__getitem__") else first_loaded
        second_loaded = second_loaded[0] if hasattr(second_loaded, "__getitem__") else second_loaded

        first_app = await linker.process_email(first_loaded)
        second_app = await linker.process_email(second_loaded)

        assert first_app is not None
        assert second_app is not None
        assert first_app.id != second_app.id

        async with get_session() as session:
            apps = (await session.exec(select(Application))).all()
            assert len(apps) == 2

    @pytest.mark.asyncio
    async def test_reprocessing_same_applied_email_without_position_is_idempotent(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<nuro-idempotent-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Thank you for applying to Nuro",
                sender_email="no-reply@us.greenhouse-mail.io",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.93,
                body_text=(
                    "Hello Ayush, thank you for applying to Nuro. "
                    "We appreciate your interest and will review your application."
                ),
            )
            session.add(email)
            await session.commit()
            await session.refresh(email)
            email_id = email.id

        linker = get_application_linker()

        async with get_session() as session:
            loaded = (await session.exec(select(Email).where(Email.id == email_id))).first()

        assert loaded is not None
        loaded = loaded[0] if hasattr(loaded, "__getitem__") else loaded

        first_app = await linker.process_email(loaded)
        second_app = await linker.process_email(loaded)

        assert first_app is not None
        assert second_app is not None
        assert first_app.id == second_app.id

        async with get_session() as session:
            apps = (await session.exec(select(Application))).all()
            assert len(apps) == 1

    @pytest.mark.asyncio
    async def test_reprocessing_upgrades_unknown_position_when_role_is_later_extracted(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<upgrade-position-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Thank you for applying to Nuro",
                sender_email="no-reply@us.greenhouse-mail.io",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.93,
                body_text="Thank you for applying to Nuro.",
            )
            session.add(email)
            await session.commit()
            await session.refresh(email)
            email_id = email.id

        linker = get_application_linker()

        async with get_session() as session:
            loaded = (await session.exec(select(Email).where(Email.id == email_id))).first()
        loaded = loaded[0] if hasattr(loaded, "__getitem__") else loaded
        assert loaded is not None

        first_app = await linker.process_email(loaded)
        assert first_app is not None
        assert first_app.position.lower() == "unknown position"

        async with get_session() as session:
            db_email = (await session.exec(select(Email).where(Email.id == email_id))).first()
            db_email = db_email[0] if hasattr(db_email, "__getitem__") else db_email
            assert db_email is not None
            db_email.body_text = (
                "Thank you for your interest in Nuro and for your application "
                "to our Software Engineer role."
            )
            session.add(db_email)
            await session.commit()

        async with get_session() as session:
            loaded_again = (await session.exec(select(Email).where(Email.id == email_id))).first()
        loaded_again = loaded_again[0] if hasattr(loaded_again, "__getitem__") else loaded_again
        assert loaded_again is not None

        second_app = await linker.process_email(loaded_again)
        assert second_app is not None
        assert second_app.id == first_app.id
        assert "software engineer" in second_app.position.lower()

        async with get_session() as session:
            apps = (await session.exec(select(Application))).all()
            assert len(apps) == 1

    @pytest.mark.asyncio
    async def test_reprocessing_normalizes_noisy_position_prefix(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            app_row = Application(
                company="Verkada",
                position="applying to the Associate Solutions Engineer, San Mateo",
                status=ApplicationStatus.APPLIED,
                applied_date=now.date(),
            )
            session.add(app_row)
            await session.commit()
            await session.refresh(app_row)

            email = Email(
                application_id=app_row.id,
                source_account=EmailSource.ICLOUD,
                message_id=f"<verkada-noisy-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Thank you for applying to Verkada",
                sender_email="no-reply@us.greenhouse-mail.io",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.9,
                body_text=(
                    "Thank you so much for applying to the Associate Solutions Engineer, "
                    "San Mateo role at Verkada!"
                ),
            )
            session.add(email)
            await session.commit()
            await session.refresh(email)
            email_id = email.id

        linker = get_application_linker()

        async with get_session() as session:
            loaded = (await session.exec(select(Email).where(Email.id == email_id))).first()
        loaded = loaded[0] if hasattr(loaded, "__getitem__") else loaded
        assert loaded is not None

        linked = await linker.process_email(loaded)
        assert linked is not None
        assert linked.id == app_row.id
        assert linked.position.lower() == "associate solutions engineer, san mateo"

    @pytest.mark.asyncio
    async def test_applied_emails_same_company_different_positions_create_separate_apps(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            first_email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<nuro-role-a-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Thank you for applying to Nuro",
                sender_email="jobs@nuro.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.95,
                body_text=(
                    "Thank you for your interest in Nuro and for your application "
                    "to our Software Engineer role."
                ),
            )
            second_email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<nuro-role-b-{now.timestamp()}@test.com>",
                received_at=now + timedelta(minutes=1),
                subject="Thank you for applying to Nuro",
                sender_email="jobs@nuro.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.94,
                body_text=(
                    "Thank you for your interest in Nuro and for your application "
                    "to our Data Engineer role."
                ),
            )
            session.add(first_email)
            session.add(second_email)
            await session.commit()
            await session.refresh(first_email)
            await session.refresh(second_email)

            first_id = first_email.id
            second_id = second_email.id

        linker = get_application_linker()

        async with get_session() as session:
            first_loaded = (
                await session.exec(select(Email).where(Email.id == first_id))
            ).first()
            second_loaded = (
                await session.exec(select(Email).where(Email.id == second_id))
            ).first()

        assert first_loaded is not None
        assert second_loaded is not None

        first_loaded = (
            first_loaded[0] if hasattr(first_loaded, "__getitem__") else first_loaded
        )
        second_loaded = (
            second_loaded[0] if hasattr(second_loaded, "__getitem__") else second_loaded
        )

        first_app = await linker.process_email(first_loaded)
        second_app = await linker.process_email(second_loaded)

        assert first_app is not None
        assert second_app is not None
        assert first_app.id != second_app.id

        async with get_session() as session:
            apps = (await session.exec(select(Application))).all()
            assert len(apps) == 2

    @pytest.mark.asyncio
    async def test_subject_only_positions_create_distinct_apps_for_same_company(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            first_email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<superhuman-role-a-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Your application for IT Operations Engineer at Superhuman",
                sender_email="no-reply@us.greenhouse-mail.io",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.95,
                body_text="Application received.",
            )
            second_email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<superhuman-role-b-{now.timestamp()}@test.com>",
                received_at=now + timedelta(minutes=1),
                subject="Your application for Early Career Program at Superhuman",
                sender_email="no-reply@us.greenhouse-mail.io",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.95,
                body_text="Application received.",
            )
            session.add(first_email)
            session.add(second_email)
            await session.commit()
            await session.refresh(first_email)
            await session.refresh(second_email)

            first_id = first_email.id
            second_id = second_email.id

        linker = get_application_linker()

        async with get_session() as session:
            first_loaded = (
                await session.exec(select(Email).where(Email.id == first_id))
            ).first()
            second_loaded = (
                await session.exec(select(Email).where(Email.id == second_id))
            ).first()

        assert first_loaded is not None
        assert second_loaded is not None

        first_loaded = (
            first_loaded[0] if hasattr(first_loaded, "__getitem__") else first_loaded
        )
        second_loaded = (
            second_loaded[0] if hasattr(second_loaded, "__getitem__") else second_loaded
        )

        first_app = await linker.process_email(first_loaded)
        second_app = await linker.process_email(second_loaded)

        assert first_app is not None
        assert second_app is not None
        assert first_app.id != second_app.id
        assert first_app.company.lower() == "superhuman"
        assert second_app.company.lower() == "superhuman"

    @pytest.mark.asyncio
    async def test_same_company_domain_different_roles_create_distinct_apps(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            first_email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<stubhub-role-a-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Thank you for your application",
                sender_email="careers@stubhub.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.91,
                body_text=(
                    "Thank you for your interest in StubHub. "
                    "We have received your application for Senior Software Engineer role."
                ),
            )
            second_email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<stubhub-role-b-{now.timestamp()}@test.com>",
                received_at=now + timedelta(minutes=1),
                subject="Thank you for your application",
                sender_email="careers@stubhub.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.92,
                body_text=(
                    "Thank you for your interest in StubHub. "
                    "We have received your application for Data Engineer role."
                ),
            )
            session.add(first_email)
            session.add(second_email)
            await session.commit()
            await session.refresh(first_email)
            await session.refresh(second_email)

            first_id = first_email.id
            second_id = second_email.id

        linker = get_application_linker()

        async with get_session() as session:
            first_loaded = (
                await session.exec(select(Email).where(Email.id == first_id))
            ).first()
            second_loaded = (
                await session.exec(select(Email).where(Email.id == second_id))
            ).first()

        assert first_loaded is not None
        assert second_loaded is not None

        first_loaded = (
            first_loaded[0] if hasattr(first_loaded, "__getitem__") else first_loaded
        )
        second_loaded = (
            second_loaded[0] if hasattr(second_loaded, "__getitem__") else second_loaded
        )

        first_app = await linker.process_email(first_loaded)
        second_app = await linker.process_email(second_loaded)

        assert first_app is not None
        assert second_app is not None
        assert first_app.id != second_app.id
        assert first_app.company.lower() == "stubhub"
        assert second_app.company.lower() == "stubhub"
        assert "software engineer" in first_app.position.lower()
        assert "data engineer" in second_app.position.lower()

    @pytest.mark.asyncio
    async def test_applied_no_position_links_to_same_day_positioned_app(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            existing_app = Application(
                company="FanDuel",
                position="Software Engineer",
                status=ApplicationStatus.APPLIED,
                applied_date=now.date(),
            )
            session.add(existing_app)
            await session.commit()
            await session.refresh(existing_app)

            email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<fanduel-linkedin-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Ayush, your application was sent to Fanduel Inc.",
                sender_email="jobs-noreply@linkedin.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.92,
                body_text="Your application was sent to Fanduel Inc.",
            )
            session.add(email)
            await session.commit()
            await session.refresh(email)
            email_id = email.id

        linker = get_application_linker()

        async with get_session() as session:
            loaded = (
                await session.exec(select(Email).where(Email.id == email_id))
            ).first()

        assert loaded is not None
        loaded = loaded[0] if hasattr(loaded, "__getitem__") else loaded
        linked_app = await linker.process_email(loaded)

        assert linked_app is not None
        assert linked_app.id == existing_app.id

        async with get_session() as session:
            apps = (await session.exec(select(Application))).all()
            assert len(apps) == 1

    @pytest.mark.asyncio
    async def test_workday_applied_email_links_with_company_from_template(self):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<workday-hpe-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Thank you for your online submission",
                sender_name="Hewlett Packard Enterprise",
                sender_email="hpe@myworkday.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.9,
                body_text=(
                    "Thank you for your interest in working with Hewlett Packard "
                    "Enterprise. A recruiter will contact you."
                ),
            )
            session.add(email)
            await session.commit()
            await session.refresh(email)
            email_id = email.id

        linker = get_application_linker()

        async with get_session() as session:
            loaded = (await session.exec(select(Email).where(Email.id == email_id))).first()

        assert loaded is not None
        loaded = loaded[0] if hasattr(loaded, "__getitem__") else loaded
        app = await linker.process_email(loaded)

        assert app is not None
        assert app.company.lower() == "hewlett packard enterprise"

        async with get_session() as session:
            db_email = (await session.exec(select(Email).where(Email.id == email_id))).first()
            assert db_email is not None
            db_email = db_email[0] if hasattr(db_email, "__getitem__") else db_email
            assert db_email.application_id is not None


class TestPhase7SmartFeatures:
    @pytest.mark.asyncio
    async def test_applications_search_uses_email_fts(self, test_client: AsyncClient):
        await _reset_analytics_tables()
        now = datetime.utcnow()
        unique_term = "quantumzebrafts"

        async with get_session() as session:
            application = Application(
                company="Acme Robotics",
                position="ML Engineer",
                status=ApplicationStatus.APPLIED,
                applied_date=(now - timedelta(days=3)).date(),
                notes="General application note",
            )
            session.add(application)
            await session.commit()
            await session.refresh(application)

            email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<fts-email-{now.timestamp()}@test.com>",
                application_id=application.id,
                received_at=now,
                subject="Interview details",
                sender_email="recruiter@acme.com",
                classified_as=EmailCategory.INTERVIEW,
                classification_confidence=0.93,
                body_text=f"We liked your profile. Token: {unique_term}",
            )
            session.add(email)
            await session.commit()

        response = await test_client.get(f"/applications?search={unique_term}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["applications"][0]["company"] == "Acme Robotics"

    @pytest.mark.asyncio
    async def test_emails_search_uses_fts_body_text(self, test_client: AsyncClient):
        await _reset_analytics_tables()
        now = datetime.utcnow()
        unique_term = "mailsearchtokenxyz"

        async with get_session() as session:
            email = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<fts-body-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Status update",
                sender_email="talent@example.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.9,
                body_text=f"Long message containing {unique_term} for search coverage.",
            )
            session.add(email)
            await session.commit()

        response = await test_client.get(f"/emails?search={unique_term}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert "fts-body" in payload["emails"][0]["message_id"]

    @pytest.mark.asyncio
    async def test_emails_unlinked_only_filters_to_unlinked_job_categories(self, test_client: AsyncClient):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            app = Application(
                company="Linked Co",
                position="Engineer",
                status=ApplicationStatus.APPLIED,
                applied_date=now.date(),
            )
            session.add(app)
            await session.commit()
            await session.refresh(app)

            unlinked_job = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<unlinked-job-{now.timestamp()}@test.com>",
                received_at=now,
                subject="Interview update",
                sender_email="talent@company.com",
                classified_as=EmailCategory.INTERVIEW,
                classification_confidence=0.93,
                application_id=None,
            )
            unlinked_pending = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<unlinked-pending-{now.timestamp()}@test.com>",
                received_at=now - timedelta(seconds=30),
                subject="Complete your application",
                sender_email="talent@company.com",
                classified_as=EmailCategory.PENDING_APPLICATION,
                classification_confidence=0.91,
                application_id=None,
            )
            linked_job = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<linked-job-{now.timestamp()}@test.com>",
                received_at=now - timedelta(minutes=1),
                subject="Thanks for applying",
                sender_email="talent@company.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.95,
                application_id=app.id,
            )
            unlinked_non_job = Email(
                source_account=EmailSource.ICLOUD,
                message_id=f"<unlinked-other-{now.timestamp()}@test.com>",
                received_at=now - timedelta(minutes=2),
                subject="Newsletter",
                sender_email="news@example.com",
                classified_as=EmailCategory.OTHER,
                classification_confidence=1.0,
                application_id=None,
            )
            session.add(unlinked_job)
            session.add(unlinked_pending)
            session.add(linked_job)
            session.add(unlinked_non_job)
            await session.commit()

        response = await test_client.get("/emails?unlinked_only=true")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        message_ids = {entry["message_id"] for entry in payload["emails"]}
        assert any("unlinked-job" in message_id for message_id in message_ids)
        assert any("unlinked-pending" in message_id for message_id in message_ids)

    @pytest.mark.asyncio
    async def test_list_applications_auto_marks_ghosted(self, test_client: AsyncClient):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            stale_application = Application(
                company="Old Co",
                position="Backend Engineer",
                status=ApplicationStatus.APPLIED,
                applied_date=(now - timedelta(days=45)).date(),
            )
            session.add(stale_application)
            await session.commit()
            await session.refresh(stale_application)
            stale_id = stale_application.id

        response = await test_client.get("/applications")
        assert response.status_code == 200
        payload = response.json()
        row = next(item for item in payload["applications"] if item["id"] == stale_id)
        assert row["status"] == ApplicationStatus.GHOSTED.value

    @pytest.mark.asyncio
    async def test_follow_up_reminders_endpoint(self, test_client: AsyncClient):
        await _reset_analytics_tables()
        now = datetime.utcnow()

        async with get_session() as session:
            stale_application = Application(
                company="Reminder Co",
                position="Platform Engineer",
                status=ApplicationStatus.APPLIED,
                applied_date=(now - timedelta(days=10)).date(),
            )
            session.add(stale_application)
            await session.commit()
            await session.refresh(stale_application)

            email = Email(
                source_account=EmailSource.GMAIL,
                message_id=f"<followup-{now.timestamp()}@test.com>",
                application_id=stale_application.id,
                received_at=now - timedelta(days=10),
                subject="Thanks for applying",
                sender_email="noreply@reminderco.com",
                classified_as=EmailCategory.APPLIED,
                classification_confidence=0.9,
                body_text="We received your application.",
            )
            session.add(email)
            await session.commit()

        response = await test_client.get("/applications/insights/follow-up-reminders?stale_days=7&ghosted_days=30")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["reminders"][0]["company"] == "Reminder Co"
        assert payload["reminders"][0]["days_since_activity"] >= 7

    @pytest.mark.asyncio
    async def test_lite_mode_toggle_api(self, test_client: AsyncClient):
        initial = await test_client.get("/classify/lite-mode")
        assert initial.status_code == 200

        enable = await test_client.put("/classify/lite-mode", json={"enabled": True})
        assert enable.status_code == 200
        assert enable.json()["enabled"] is True

        disable = await test_client.put("/classify/lite-mode", json={"enabled": False})
        assert disable.status_code == 200
        assert disable.json()["enabled"] is False
