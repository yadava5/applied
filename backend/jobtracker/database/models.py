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

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


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
    INTERVIEW = "interview"
    REJECTION = "rejection"
    OFFER = "offer"
    ASSESSMENT = "assessment"
    FOLLOW_UP = "follow_up"
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

    id: Optional[int] = Field(default=None, primary_key=True)

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

    id: Optional[int] = Field(default=None, primary_key=True)

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
    classification_method: Optional[ClassificationMethod] = Field(
        default=None,
        description="Method used for classification",
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

    id: Optional[int] = Field(default=None, primary_key=True)

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

    id: Optional[int] = Field(default=None, primary_key=True)

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

    id: Optional[int] = Field(default=None, primary_key=True)

    # Training example
    email_text: str = Field(description="Email text content")
    label: EmailCategory = Field(index=True, description="Correct classification label")
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

    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key to email
    email_id: int = Field(
        foreign_key="emails.id",
        unique=True,
        index=True,
        description="Associated email ID",
    )

    # Embedding data
    label: EmailCategory = Field(index=True, description="Classification label")
    embedding: bytes = Field(description="Serialized numpy array (384 floats)")
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

    id: Optional[int] = Field(default=None, primary_key=True)

    # Account info
    account_type: EmailSource = Field(description="Gmail or iCloud")
    account_email: str = Field(unique=True, description="Account email address")

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

    # Status
    status: SyncStatus = Field(default=SyncStatus.IDLE, description="Current sync status")
    error_message: Optional[str] = Field(default=None, description="Last error message")
