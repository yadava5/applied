"""
Database Models
===============

SQLModel table definitions for the JobTracker database.

Tables:
-------
- Application: Job applications (company, position, status)
- Email: Synced emails with classification
- Contact: Recruiters and hiring managers
- Interview: Scheduled interviews
- TrainingData: User corrections for ML training
- EmailEmbedding: Stored embeddings for similarity matching
- SyncState: Email account sync status

All models use SQLModel which combines SQLAlchemy ORM with
Pydantic validation. This enables type-safe database operations
and automatic API serialization.

Usage:
------
    from jobtracker.database.models import Application, Email

    app = Application(company="Acme Corp", position="Software Engineer")
    email = Email(subject="Your application", classified_as="applied")
"""

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

# =============================================================================
# Multi-tenancy sentinel
# =============================================================================
#
# Every entity table carries a ``user_id`` FK to ``auth.users(id)`` once the
# cloud deployment is live. Desktop (single-user SQLite) and pytest (in-memory
# SQLite) have no Supabase auth, so inserts would have no real UUID to put in
# the column. Rather than make the column nullable at the Python level (which
# would force every cloud query to handle None), we use a fixed sentinel UUID
# for local/test contexts. The cloud middleware (``auth.supabase_jwt``)
# overrides this with the JWT's ``sub`` claim per request.
#
# The sentinel is also what Alembic backfills existing rows with before the
# ``NOT NULL`` step, so local databases migrated from pre-C3 schemas keep
# working without user intervention.
LOCAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _user_id_field(*, index_name: str | None = None) -> "Field":
    """Factory for the ``user_id`` column shared by every entity table.

    Uses SQLAlchemy 2.0's ``sa.Uuid`` type which renders as native ``UUID``
    on Postgres and ``CHAR(32)`` on SQLite — the single declaration works
    across desktop (SQLite), tests (SQLite in-memory), and cloud (Postgres).
    """

    return Field(
        default=LOCAL_USER_ID,
        sa_column=Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
            index=True,
        ),
        description="Supabase auth.users(id) owner of this row.",
    )


# =============================================================================
# Enums
# =============================================================================


class ApplicationStatus(str, Enum):
    """Possible statuses for a job application."""

    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFERED = "offered"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"
    GHOSTED = "ghosted"


class EmailCategory(str, Enum):
    """Classification categories for job-related emails."""

    APPLIED = "applied"
    PENDING_APPLICATION = "pending_application"
    INTERVIEW = "interview"
    REJECTION = "rejection"
    OFFER = "offer"
    ASSESSMENT = "assessment"
    FOLLOW_UP = "follow_up"
    NEEDS_REVIEW = "needs_review"  # Uncertain - human should review
    OTHER = "other"


class ClassificationMethod(str, Enum):
    """Method used to classify an email."""

    RULES = "rules"
    SIMILARITY = "similarity"
    SETFIT = "setfit"
    USER = "user"
    FALLBACK = "fallback"


class EmailSource(str, Enum):
    """Source email account type."""

    GMAIL = "gmail"
    ICLOUD = "icloud"


class InterviewType(str, Enum):
    """Types of interviews."""

    PHONE = "phone"
    VIDEO = "video"
    ONSITE = "onsite"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    PANEL = "panel"


class InterviewStatus(str, Enum):
    """Interview scheduling status."""

    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class ContactRole(str, Enum):
    """Role of a contact person."""

    RECRUITER = "recruiter"
    HIRING_MANAGER = "hiring_manager"
    HR = "hr"
    OTHER = "other"


class SyncStatus(str, Enum):
    """Email sync status."""

    IDLE = "idle"
    SYNCING = "syncing"
    ERROR = "error"


# =============================================================================
# Base Models
# =============================================================================


class TimestampMixin(SQLModel):
    """Mixin for created_at and updated_at timestamps."""

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Record creation timestamp",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Record last update timestamp",
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


# =============================================================================
# Application Model
# =============================================================================


class Application(TimestampMixin, table=True):
    """
    Job application record.

    Represents a single job application to a company/position.
    Links to related emails, contacts, and interviews.
    """

    __tablename__ = "applications"
    __table_args__ = (
        sa.Index("ix_applications_user_id_status", "user_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (Supabase auth.users.id). Defaults to the local-user sentinel on
    # desktop/tests; cloud writes set this from the validated JWT ``sub``.
    user_id: uuid.UUID = _user_id_field()

    # Core fields
    company: str = Field(index=True, description="Company name")
    position: str = Field(description="Job position/title")
    status: ApplicationStatus = Field(
        default=ApplicationStatus.APPLIED,
        index=True,
        description="Current application status",
    )

    # Application details
    applied_date: Optional[date] = Field(default=None, description="Date of application")
    source: Optional[str] = Field(default=None, description="Where you found the job")
    url: Optional[str] = Field(default=None, description="Job posting URL")
    notes: Optional[str] = Field(default=None, description="Personal notes")

    # Relationships
    emails: list["Email"] = Relationship(back_populates="application")
    contacts: list["Contact"] = Relationship(back_populates="application")
    interviews: list["Interview"] = Relationship(back_populates="application")


# =============================================================================
# Email Model
# =============================================================================


class Email(TimestampMixin, table=True):
    """
    Synced email record with classification.

    Stores email content and metadata, classification results,
    and linkage to applications.
    """

    __tablename__ = "emails"
    __table_args__ = (
        sa.Index("ix_emails_user_id_received_at", "user_id", "received_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (Supabase auth.users.id).
    user_id: uuid.UUID = _user_id_field()

    # Foreign key to application (optional - unlinked emails allowed)
    application_id: Optional[int] = Field(
        default=None,
        foreign_key="applications.id",
        index=True,
        description="Linked application ID",
    )

    # Email metadata
    source_account: EmailSource = Field(index=True, description="Gmail or iCloud")
    message_id: str = Field(unique=True, index=True, description="Email Message-ID header")
    thread_id: Optional[str] = Field(default=None, description="Gmail thread ID")

    # Email content
    subject: Optional[str] = Field(default=None, description="Email subject")
    sender_name: Optional[str] = Field(default=None, description="Sender display name")
    sender_email: Optional[str] = Field(default=None, description="Sender email address")
    received_at: datetime = Field(index=True, description="Email receive timestamp")
    body_text: Optional[str] = Field(default=None, description="Plain text body")
    body_html: Optional[str] = Field(
        default=None,
        description="Raw HTML body when available for rich rendering",
    )
    body_snippet: Optional[str] = Field(
        default=None,
        max_length=500,
        description="First 500 chars for preview",
    )

    # Classification
    classified_as: Optional[EmailCategory] = Field(
        default=None,
        index=True,
        description="ML classification result",
    )
    classification_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Classification confidence (0.0-1.0)",
    )
    classification_method: Optional[str] = Field(
        default=None,
        description="Method used for classification (rules, embeddings, setfit, fallback, user_correction)",
    )

    # User interaction
    user_corrected: bool = Field(default=False, description="Was classification corrected?")
    is_reviewed: bool = Field(default=False, description="Has user reviewed this email?")

    # Raw data
    raw_headers: Optional[str] = Field(
        default=None,
        description="JSON of email headers for debugging",
    )

    # Relationships
    application: Optional[Application] = Relationship(back_populates="emails")
    embedding: Optional["EmailEmbedding"] = Relationship(back_populates="email")


# =============================================================================
# Contact Model
# =============================================================================


class Contact(TimestampMixin, table=True):
    """
    Contact person associated with an application.

    Stores recruiters, hiring managers, and other contacts
    extracted from email signatures or manually added.
    """

    __tablename__ = "contacts"
    __table_args__ = (
        sa.Index("ix_contacts_user_id_application_id", "user_id", "application_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (Supabase auth.users.id).
    user_id: uuid.UUID = _user_id_field()

    # Foreign key to application
    application_id: int = Field(
        foreign_key="applications.id",
        index=True,
        description="Associated application ID",
    )

    # Contact info
    name: Optional[str] = Field(default=None, description="Contact name")
    email: str = Field(description="Contact email address")
    role: Optional[ContactRole] = Field(default=None, description="Contact role")
    notes: Optional[str] = Field(default=None, description="Notes about contact")

    # Relationships
    application: Application = Relationship(back_populates="contacts")


# =============================================================================
# Interview Model
# =============================================================================


class Interview(TimestampMixin, table=True):
    """
    Interview record associated with an application.

    Tracks scheduled, completed, and cancelled interviews
    with type, time, and location details.
    """

    __tablename__ = "interviews"
    __table_args__ = (
        sa.Index("ix_interviews_user_id_application_id", "user_id", "application_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (Supabase auth.users.id).
    user_id: uuid.UUID = _user_id_field()

    # Foreign key to application
    application_id: int = Field(
        foreign_key="applications.id",
        index=True,
        description="Associated application ID",
    )

    # Interview details
    type: Optional[InterviewType] = Field(default=None, description="Interview type")
    scheduled_at: Optional[datetime] = Field(default=None, description="Scheduled time")
    duration_minutes: Optional[int] = Field(default=None, description="Expected duration")
    location: Optional[str] = Field(default=None, description="Location or video link")
    notes: Optional[str] = Field(default=None, description="Interview notes")
    status: InterviewStatus = Field(
        default=InterviewStatus.SCHEDULED,
        description="Interview status",
    )

    # Relationships
    application: Application = Relationship(back_populates="interviews")


# =============================================================================
# Training Data Model
# =============================================================================


class TrainingData(SQLModel, table=True):
    """
    User corrections for ML model training.

    When a user corrects a misclassified email, the correction
    is stored here for SetFit retraining.
    """

    __tablename__ = "training_data"
    __table_args__ = (
        sa.Index("ix_training_data_user_id_label", "user_id", "label"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (Supabase auth.users.id).
    user_id: uuid.UUID = _user_id_field()

    # Link to original email (optional)
    email_id: Optional[int] = Field(
        default=None,
        index=True,
        unique=True,
        description="Associated email ID (if from user correction)",
    )

    # Training example content
    subject: Optional[str] = Field(default=None, description="Email subject")
    body_text: Optional[str] = Field(default=None, description="Email body text")

    # Legacy field - combined text (for backwards compatibility)
    email_text: Optional[str] = Field(default=None, description="Combined email text (legacy)")

    # Label (stored as string for flexibility)
    label: str = Field(index=True, description="Correct classification label")
    source: str = Field(
        default="user_correction",
        description="Source of training data",
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When correction was made",
    )


# =============================================================================
# Email Embedding Model
# =============================================================================


class EmailEmbedding(SQLModel, table=True):
    """
    Stored embeddings for similarity-based classification.

    Embeddings are stored as BLOBs in SQLite for reliability
    (transactional, backed up automatically).
    """

    __tablename__ = "email_embeddings"
    __table_args__ = (
        sa.Index("ix_email_embeddings_user_id_label", "user_id", "label"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (Supabase auth.users.id).
    user_id: uuid.UUID = _user_id_field()

    # Foreign key to email
    email_id: int = Field(
        foreign_key="emails.id",
        unique=True,
        index=True,
        description="Associated email ID",
    )

    # Embedding data (label stored as string for flexibility)
    label: str = Field(index=True, description="Classification label")
    embedding: Optional[bytes] = Field(default=None, description="Serialized numpy array (384 floats)")
    model_version: str = Field(
        default="e5-small-v2",
        description="Embedding model version",
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When embedding was created",
    )

    # Relationships
    email: Email = Relationship(back_populates="embedding")


# =============================================================================
# Sync State Model
# =============================================================================


class SyncState(SQLModel, table=True):
    """
    Email account sync state tracking.

    Stores the last sync position for incremental syncing
    of Gmail (historyId) and iCloud (IMAP UID).
    """

    __tablename__ = "sync_state"
    # ``account_email`` is unique *per user* (composite), not globally unique.
    # Two different Supabase users connecting the same iCloud account is a
    # legitimate cloud case that global-uniqueness would block. Desktop stays
    # single-user so the constraint is equivalent in practice.
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "account_email", name="uq_sync_state_user_account"
        ),
        sa.Index(
            "ix_sync_state_user_id_account_email", "user_id", "account_email"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Owner (Supabase auth.users.id).
    user_id: uuid.UUID = _user_id_field()

    # Account info - use string column to store enum values (not names)
    account_type: str = Field(description="Gmail or iCloud")
    account_email: str = Field(description="Account email address")

    # Sync state
    last_sync_at: Optional[datetime] = Field(default=None, description="Last sync timestamp")
    gmail_history_id: Optional[str] = Field(
        default=None,
        description="Gmail historyId for incremental sync",
    )
    imap_last_uid: Optional[int] = Field(
        default=None,
        description="IMAP last UID for incremental sync",
    )

    # Status - use string column to store enum values
    status: str = Field(default="idle", description="Current sync status")
    error_message: Optional[str] = Field(default=None, description="Last error message")
