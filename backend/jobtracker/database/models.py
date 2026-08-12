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
    """Possible statuses for a job application.

    THE canonical stage vocabulary. Everything that needs the list — the API
    body models, ``GET /applications/statuses``, the rollup's rank tables, the
    web's ``<select>`` — derives from here rather than restating it, because
    three hand-written copies is exactly how the board came to offer a stage
    (``assessment``) that the API answered with a 422. The word is settable now;
    the lesson is not about the word but about the copies.

    ``assessment`` IS a member, as of 2026-08-12: see :data:`CATEGORY_TO_STATUS`
    for the decision and why it changed.

    DECLARATION ORDER IS THE API'S ORDER. ``APPLICATION_STATUSES``, the
    endpoint's list and the web's mirror all take their order from here, so a
    member is inserted at its lifecycle position, never appended.

    The member NAMES are what Postgres stores — SQLModel/SQLAlchemy persist an
    enum's name, not its value — so the ``applicationstatus`` type holds
    ``'ASSESSMENT'`` while the API speaks ``'assessment'``. Adding a member
    therefore needs a migration that adds the UPPERCASE label
    (``b9e42f7c10ad``), and the SQLite suites cannot see that difference because
    ``sa.Enum`` renders as ``VARCHAR`` there.
    """

    APPLIED = "applied"
    ASSESSMENT = "assessment"
    INTERVIEWING = "interviewing"
    OFFERED = "offered"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"
    GHOSTED = "ghosted"


# The stage vocabulary as plain strings, in declaration order — DERIVED from the
# enum, so it cannot drift from it. This is what the API serves and what any
# other vocabulary (a UI select, a rank table) must be checked against.
APPLICATION_STATUSES: tuple[str, ...] = tuple(s.value for s in ApplicationStatus)

# The stage a brand-new row starts at (also ``Application.status``'s default).
DEFAULT_APPLICATION_STATUS: ApplicationStatus = ApplicationStatus.APPLIED


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


# What a classifier verdict means for the application it belongs to — the ONE
# statement of the category → stage mapping.
#
# ``assessment`` is the interesting one, and it is BOTH a category and a stage.
# It maps to itself.
#
# This reverses the decision recorded here until 2026-08-12, which folded it
# into ``interviewing`` on the grounds that "the product does not make that
# distinction". The product's owner does, on his own mail, and that is the
# authority that settles a vocabulary question: a real message from Roblox was
# five self-serve timed tasks with a seven-day expiry — no human, no scheduling,
# no call — and the board said "interviewing" about it. A tracker whose one
# screen names the wrong thing is wrong, however consistent it is internally.
#
# What actually changed, beyond the owner's verdict:
#
# - An EXPIRY is a different kind of time from a scheduled slot. Since
#   ``b7c31e0d94aa`` a row carries ``due_at``, so the difference between "you
#   must act before Friday" and "someone will meet you on Friday" is now a
#   fact the schema can hold; a stage that says which one this is makes the
#   deadline legible instead of decorative.
# - The rollup had ALREADY ranked it separately (``pipeline._STAGE_RANK`` has
#   ranked ``assessment`` between applied and interview since it was written).
#   The old decision cited that ranking as evidence the distinction was not
#   made, when it was in fact evidence that everything except the enum made it.
# - The cost cited against it — an ``ALTER TYPE applicationstatus ADD VALUE``
#   against live Postgres — is real but one-way and cheap; ``b9e42f7c10ad``
#   does it, forward-only, because Postgres has no ``DROP VALUE``.
#
# Deliberately UNCHANGED, so this stays a vocabulary change and not a redesign:
#
# - the classifier's category vocabulary (:class:`EmailCategory`, nine values)
#   and the corpus labelled with it — no retraining, no relabelling;
# - the terminal set (rejected/accepted/withdrawn/ghosted) — an assessment is
#   in-flight, so ``assessment`` is not terminal;
# - the monotonic rule in ``pipeline.advance_application_status`` — mail may
#   still only push a row FORWARD, so a re-test mailed to a row already at
#   ``interviewing`` leaves it at ``interviewing`` (its deadline still lands,
#   because ``due_at`` is recomputed independently of status);
# - application identity (employer + req_id-or-role) — a second requisition is
#   still a separate row that starts its own journey.
#
# Categories absent from this map (``follow_up``, ``needs_review``, ``other``)
# assert no stage at all: a follow-up is chasing an application, not a stage of
# one, and the other two are noise or a holding pen. That is what keeps the two
# vocabularies distinct now that they overlap by one member: a category is a
# claim about a MESSAGE, a status is a fact about an APPLICATION, and only the
# six categories below say anything about the second.
CATEGORY_TO_STATUS: dict[EmailCategory, ApplicationStatus] = {
    EmailCategory.APPLIED: ApplicationStatus.APPLIED,
    EmailCategory.PENDING_APPLICATION: ApplicationStatus.APPLIED,
    EmailCategory.ASSESSMENT: ApplicationStatus.ASSESSMENT,
    EmailCategory.INTERVIEW: ApplicationStatus.INTERVIEWING,
    EmailCategory.OFFER: ApplicationStatus.OFFERED,
    EmailCategory.REJECTION: ApplicationStatus.REJECTED,
}


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

    # Removal is RECOVERABLE, never a DELETE. Nothing automated may destroy an
    # application: the re-sync rebuild and the user's "not an application"
    # dismiss both set these instead, which hides the row from the board while
    # the row and its emails stay on disk for an undo. ``NULL`` = live.
    # ``dismissed_reason`` records WHO removed it (``user`` / ``resync``) —
    # fresh mail may resurrect an automated removal, but never a human's.
    dismissed_at: Optional[datetime] = Field(
        default=None,
        description="When the row was removed from the board (NULL = live)",
    )
    dismissed_reason: Optional[str] = Field(
        default=None,
        description="Who removed it: 'user' (explicit dismiss) or 'resync'",
    )

    # Identity WITHIN an employer. Until 2026-08-11 the identity of an
    # application was its company alone, so four different Amazon requisitions
    # applied for on one evening became one row and three real applications were
    # invisible. These two are what tell them apart on the next sync:
    # ``req_id`` is the employer's own requisition number when it prints one
    # ("(ID: 3177934)"), ``role_token`` the normalized job title. Both NULL is
    # legitimate and means the mail named no role anywhere — that employer keeps
    # exactly one row, which is the honest floor rather than a guess.
    #
    # Re-applying after a rejection does NOT produce a second row, and the
    # comment that used to sit here claiming it did was wrong in both halves.
    # ``_company_rows`` filters on owner and company token only — no status, and
    # "live" there means not-dismissed, which a rejected row still is — so a
    # fresh confirmation for the same role resolves straight onto the settled
    # row. What happens instead is REOPEN-IN-PLACE: ``roll_up_applications``
    # reads a cluster's status from the mail strictly newer than its newest
    # dated rejection, and ``upsert_applications_for_user`` lets a rejected AUTO
    # row leave the terminal state only on that evidence. One identity is one
    # row across any number of attempts — the board shows a single card whose
    # ``applied_date`` keeps the FIRST filing.
    #
    # Still deliberately NOT a unique constraint, for two reasons that survive
    # that correction. No column tuple expresses the identity the resolver
    # actually uses: it matches a normalized company TOKEN against the stored
    # display name, which the sync itself restyles ("Doordash" → "DoorDash").
    # And both columns are legitimately NULL for an employer that names no role,
    # where NULLs do not collide — so the constraint would police only the rows
    # that never needed policing.
    req_id: Optional[str] = Field(
        default=None,
        index=True,
        description="Employer's own requisition id for this application, if any",
    )
    role_token: Optional[str] = Field(
        default=None,
        description="Normalized job title, used to tell one employer's applications apart",
    )

    # When something is DUE — the assessment window, the take-home deadline, the
    # date an offer must be answered by. NULL means no deadline is known, which
    # is the honest default: a deadline is only ever recorded because a message
    # stated one or a human typed one. It is never inferred.
    due_at: Optional[datetime] = Field(
        default=None,
        index=True,
        description="When this application's next obligation is due (UTC)",
    )
    # Who put it there: 'mail' (extracted from an explicit statement) or 'user'.
    # The distinction is load-bearing — a sync may refresh a 'mail' deadline as
    # later mail supersedes it, and must never touch one a human set.
    due_source: Optional[str] = Field(
        default=None,
        description="Origin of due_at: 'mail' (extracted) or 'user' (typed)",
    )

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
        # Uniqueness of a provider message id is PER OWNER, not global. Every
        # lookup in the cloud path is already scoped ``(user_id, message_id)``;
        # a global UNIQUE meant the second user to receive the same Gmail
        # message id would hit a unique violation and 500 their whole sync.
        # Same shape of de-globalization that revision ``6e64c46d32fd`` applied
        # to ``sync_state.account_email``.
        sa.Index("ix_emails_user_id_message_id", "user_id", "message_id", unique=True),
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
    # Indexed but NOT globally unique — uniqueness is the composite
    # ``(user_id, message_id)`` index declared in ``__table_args__``.
    message_id: str = Field(index=True, description="Email Message-ID header")
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


class UserCredential(SQLModel, table=True):
    """
    Encrypted third-party credentials (cloud deployment only).

    Stores Gmail OAuth tokens and iCloud app-specific passwords as
    Fernet-encrypted blobs, scoped to the authenticated Supabase user.
    Desktop uses macOS Keychain via ``jobtracker.credentials.desktop``
    and never writes to this table.

    See ``jobtracker.credentials.cloud`` for the read/write API and
    ``jobtracker.config.secret_encryption_key`` for the encryption key.

    Composite PK (user_id, kind) means at most one row per user per
    credential type; re-issuing a Gmail OAuth token overwrites the
    existing row.
    """

    __tablename__ = "user_credentials"
    __table_args__ = (
        sa.PrimaryKeyConstraint("user_id", "kind", name="pk_user_credentials"),
        sa.CheckConstraint(
            "kind IN ('gmail_oauth', 'icloud_mail')",
            name="ck_user_credentials_kind",
        ),
        sa.Index("ix_user_credentials_kind", "kind"),
    )

    # Owner (Supabase auth.users.id). NOT using the shared
    # ``_user_id_field()`` factory here because this table's PK *is*
    # (user_id, kind) — we want the column declared with an explicit
    # SA column object that participates in the composite PK.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        description="Supabase auth.users(id) owner of this credential.",
    )

    # Credential type discriminator. Text, not Python enum — the
    # CHECK constraint (see __table_args__) enforces valid values and
    # keeps the column portable across SQLite/Postgres.
    kind: str = Field(
        sa_column=Column("kind", sa.Text, nullable=False),
        description="Credential kind: 'gmail_oauth' or 'icloud_mail'.",
    )

    # Fernet token: base64url(version || timestamp || iv || ciphertext || hmac).
    # Fernet embeds its own IV, so ``nonce`` is reserved for a future AEAD
    # upgrade and currently stored as an empty byte string.
    ciphertext: bytes = Field(
        sa_column=Column("ciphertext", sa.LargeBinary, nullable=False),
        description="Fernet-encrypted credential blob.",
    )
    nonce: bytes = Field(
        default=b"",
        sa_column=Column("nonce", sa.LargeBinary, nullable=False),
        description="Reserved for AEAD nonce (unused by Fernet).",
    )

    # Encryption key id — supports rotation. Active key is named 'v1'.
    key_id: str = Field(
        default="v1",
        sa_column=Column("key_id", sa.Text, nullable=False, server_default="v1"),
        description="Identifier of the encryption key used (rotation support).",
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
