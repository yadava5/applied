"""
Database Tests
==============

Tests for database models, connection, and operations.

These tests use a temporary in-memory SQLite database
to avoid affecting the production database.

Run with:
    pytest tests/test_database.py -v
"""

import pytest
from datetime import date, datetime
from sqlmodel import select

from jobtracker.database.models import (
    Application,
    ApplicationStatus,
    Contact,
    ContactRole,
    Email,
    EmailCategory,
    EmailEmbedding,
    EmailSource,
    ClassificationMethod,
    Interview,
    InterviewStatus,
    InterviewType,
    SyncState,
    SyncStatus,
    TrainingData,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def test_session():
    """
    Create a test database session with in-memory SQLite.

    This fixture creates a fresh database for each test,
    ensuring test isolation.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    # Create in-memory database
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Provide session
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session

    # Cleanup
    await engine.dispose()


# =============================================================================
# Application Model Tests
# =============================================================================


class TestApplicationModel:
    """Tests for the Application model."""

    async def test_create_application(self, test_session):
        """Test creating a basic application."""
        app = Application(
            company="Acme Corp",
            position="Software Engineer",
        )
        test_session.add(app)
        await test_session.commit()
        await test_session.refresh(app)

        assert app.id is not None
        assert app.company == "Acme Corp"
        assert app.position == "Software Engineer"
        assert app.status == ApplicationStatus.APPLIED  # Default
        assert app.created_at is not None

    async def test_application_with_all_fields(self, test_session):
        """Test creating an application with all optional fields."""
        app = Application(
            company="Tech Inc",
            position="Senior Developer",
            status=ApplicationStatus.INTERVIEWING,
            applied_date=date(2026, 2, 1),
            source="LinkedIn",
            url="https://techinc.com/jobs/123",
            notes="Referred by John",
        )
        test_session.add(app)
        await test_session.commit()

        assert app.status == ApplicationStatus.INTERVIEWING
        assert app.applied_date == date(2026, 2, 1)
        assert app.source == "LinkedIn"

    async def test_application_status_enum(self, test_session):
        """Test all application status values."""
        statuses = [
            ApplicationStatus.APPLIED,
            ApplicationStatus.INTERVIEWING,
            ApplicationStatus.OFFERED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ACCEPTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.GHOSTED,
        ]

        for status in statuses:
            app = Application(
                company=f"Company-{status.value}",
                position="Test",
                status=status,
            )
            test_session.add(app)

        await test_session.commit()

        result = await test_session.exec(select(Application))
        apps = result.all()
        assert len(apps) == len(statuses)


# =============================================================================
# Email Model Tests
# =============================================================================


class TestEmailModel:
    """Tests for the Email model."""

    async def test_create_email(self, test_session):
        """Test creating a basic email."""
        email = Email(
            source_account=EmailSource.GMAIL,
            message_id="<abc123@mail.gmail.com>",
            received_at=datetime.utcnow(),
        )
        test_session.add(email)
        await test_session.commit()
        await test_session.refresh(email)

        assert email.id is not None
        assert email.source_account == EmailSource.GMAIL
        assert email.message_id == "<abc123@mail.gmail.com>"

    async def test_email_with_classification(self, test_session):
        """Test email with classification fields."""
        email = Email(
            source_account=EmailSource.ICLOUD,
            message_id="<def456@icloud.com>",
            received_at=datetime.utcnow(),
            subject="Interview Invitation",
            sender_email="recruiter@company.com",
            classified_as=EmailCategory.INTERVIEW,
            classification_confidence=0.92,
            classification_method=ClassificationMethod.RULES,
        )
        test_session.add(email)
        await test_session.commit()

        assert email.classified_as == EmailCategory.INTERVIEW
        assert email.classification_confidence == 0.92
        assert email.classification_method == ClassificationMethod.RULES

    async def test_email_linked_to_application(self, test_session):
        """Test linking email to application."""
        # Create application first
        app = Application(company="Test Co", position="Dev")
        test_session.add(app)
        await test_session.commit()
        await test_session.refresh(app)

        # Create email linked to application
        email = Email(
            application_id=app.id,
            source_account=EmailSource.GMAIL,
            message_id="<linked@test.com>",
            received_at=datetime.utcnow(),
        )
        test_session.add(email)
        await test_session.commit()

        assert email.application_id == app.id

    async def test_email_unique_message_id(self, test_session):
        """Test that message_id must be unique."""
        email1 = Email(
            source_account=EmailSource.GMAIL,
            message_id="<unique@test.com>",
            received_at=datetime.utcnow(),
        )
        test_session.add(email1)
        await test_session.commit()

        # Attempt to create duplicate
        email2 = Email(
            source_account=EmailSource.GMAIL,
            message_id="<unique@test.com>",  # Same message_id
            received_at=datetime.utcnow(),
        )
        test_session.add(email2)

        with pytest.raises(Exception):  # IntegrityError
            await test_session.commit()


# =============================================================================
# Contact Model Tests
# =============================================================================


class TestContactModel:
    """Tests for the Contact model."""

    async def test_create_contact(self, test_session):
        """Test creating a contact linked to application."""
        app = Application(company="Test", position="Dev")
        test_session.add(app)
        await test_session.commit()
        await test_session.refresh(app)

        contact = Contact(
            application_id=app.id,
            name="Jane Smith",
            email="jane@company.com",
            role=ContactRole.RECRUITER,
        )
        test_session.add(contact)
        await test_session.commit()

        assert contact.id is not None
        assert contact.name == "Jane Smith"
        assert contact.role == ContactRole.RECRUITER


# =============================================================================
# Interview Model Tests
# =============================================================================


class TestInterviewModel:
    """Tests for the Interview model."""

    async def test_create_interview(self, test_session):
        """Test creating an interview."""
        app = Application(company="Test", position="Dev")
        test_session.add(app)
        await test_session.commit()
        await test_session.refresh(app)

        interview = Interview(
            application_id=app.id,
            type=InterviewType.VIDEO,
            scheduled_at=datetime(2026, 2, 15, 14, 0),
            duration_minutes=60,
            location="https://zoom.us/j/123456",
            status=InterviewStatus.SCHEDULED,
        )
        test_session.add(interview)
        await test_session.commit()

        assert interview.id is not None
        assert interview.type == InterviewType.VIDEO
        assert interview.duration_minutes == 60


# =============================================================================
# Training Data Model Tests
# =============================================================================


class TestTrainingDataModel:
    """Tests for the TrainingData model."""

    async def test_create_training_data(self, test_session):
        """Test creating training data from user correction."""
        training = TrainingData(
            email_text="We regret to inform you that...",
            label=EmailCategory.REJECTION,
            source="user_correction",
        )
        test_session.add(training)
        await test_session.commit()

        assert training.id is not None
        assert training.label == EmailCategory.REJECTION
        assert training.created_at is not None


# =============================================================================
# Email Embedding Model Tests
# =============================================================================


class TestEmailEmbeddingModel:
    """Tests for the EmailEmbedding model."""

    async def test_create_embedding(self, test_session):
        """Test storing an email embedding."""
        # Create email first
        email = Email(
            source_account=EmailSource.GMAIL,
            message_id="<emb@test.com>",
            received_at=datetime.utcnow(),
        )
        test_session.add(email)
        await test_session.commit()
        await test_session.refresh(email)

        # Create embedding (fake 384-dim vector as bytes)
        import numpy as np

        fake_embedding = np.random.rand(384).astype(np.float32).tobytes()

        embedding = EmailEmbedding(
            email_id=email.id,
            label=EmailCategory.INTERVIEW,
            embedding=fake_embedding,
            model_version="e5-small-v2",
        )
        test_session.add(embedding)
        await test_session.commit()

        assert embedding.id is not None
        assert len(embedding.embedding) == 384 * 4  # 384 floats * 4 bytes


# =============================================================================
# Sync State Model Tests
# =============================================================================


class TestSyncStateModel:
    """Tests for the SyncState model."""

    async def test_create_sync_state(self, test_session):
        """Test creating sync state for Gmail."""
        state = SyncState(
            account_type=EmailSource.GMAIL,
            account_email="user@gmail.com",
            gmail_history_id="12345",
            status=SyncStatus.IDLE,
        )
        test_session.add(state)
        await test_session.commit()

        assert state.id is not None
        assert state.gmail_history_id == "12345"

    async def test_sync_state_icloud(self, test_session):
        """Test creating sync state for iCloud."""
        state = SyncState(
            account_type=EmailSource.ICLOUD,
            account_email="user@icloud.com",
            imap_last_uid=500,
            status=SyncStatus.IDLE,
        )
        test_session.add(state)
        await test_session.commit()

        assert state.imap_last_uid == 500


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Tests for common database queries."""

    async def test_filter_applications_by_status(self, test_session):
        """Test filtering applications by status."""
        # Create apps with different statuses
        apps = [
            Application(company="A", position="Dev", status=ApplicationStatus.APPLIED),
            Application(company="B", position="Dev", status=ApplicationStatus.APPLIED),
            Application(company="C", position="Dev", status=ApplicationStatus.INTERVIEWING),
            Application(company="D", position="Dev", status=ApplicationStatus.REJECTED),
        ]
        for app in apps:
            test_session.add(app)
        await test_session.commit()

        # Query by status
        result = await test_session.exec(
            select(Application).where(Application.status == ApplicationStatus.APPLIED)
        )
        applied_apps = result.all()

        assert len(applied_apps) == 2

    async def test_filter_emails_by_classification(self, test_session):
        """Test filtering emails by classification category."""
        emails = [
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<1@test>",
                received_at=datetime.utcnow(),
                classified_as=EmailCategory.REJECTION,
            ),
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<2@test>",
                received_at=datetime.utcnow(),
                classified_as=EmailCategory.REJECTION,
            ),
            Email(
                source_account=EmailSource.GMAIL,
                message_id="<3@test>",
                received_at=datetime.utcnow(),
                classified_as=EmailCategory.INTERVIEW,
            ),
        ]
        for email in emails:
            test_session.add(email)
        await test_session.commit()

        result = await test_session.exec(
            select(Email).where(Email.classified_as == EmailCategory.REJECTION)
        )
        rejections = result.all()

        assert len(rejections) == 2

    async def test_count_training_data_by_label(self, test_session):
        """Test counting training data by label."""
        data = [
            TrainingData(email_text="text1", label=EmailCategory.REJECTION),
            TrainingData(email_text="text2", label=EmailCategory.REJECTION),
            TrainingData(email_text="text3", label=EmailCategory.INTERVIEW),
            TrainingData(email_text="text4", label=EmailCategory.OFFER),
        ]
        for d in data:
            test_session.add(d)
        await test_session.commit()

        # This would be done with SQL COUNT in production
        result = await test_session.exec(
            select(TrainingData).where(TrainingData.label == EmailCategory.REJECTION)
        )
        assert len(result.all()) == 2
