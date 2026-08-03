"""
Email synchronization service.

This module orchestrates email syncing from all connected accounts
(Gmail, iCloud) and stores them in the database.

Features:
- Sync from multiple email sources
- Incremental sync using history IDs (Gmail) and UIDs (IMAP)
- Deduplication via Message-ID
- Track sync state per account
- Async operations with progress reporting
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.classifier import get_classifier
from jobtracker.credentials import get_gmail_credentials, get_icloud_credentials
from jobtracker.database import get_session
from jobtracker.database.models import Email, EmailSource, SyncState, SyncStatus
from jobtracker.email_clients import (
    GmailClient,
    ICloudClient,
    ParsedEmail,
    get_parser,
)
from jobtracker.tracking import get_application_linker

logger = logging.getLogger(__name__)


# =============================================================================
# Data Types
# =============================================================================


class SyncEventType(Enum):
    """Types of sync events for progress reporting."""

    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class SyncProgress:
    """Progress information during sync."""

    account: str  # "gmail" or "icloud"
    event: SyncEventType
    emails_fetched: int = 0
    emails_total: int = 0
    emails_saved: int = 0
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    accounts_synced: list[str]
    emails_fetched: int
    emails_saved: int
    emails_skipped: int  # Duplicates
    errors: list[str]
    duration_seconds: float


# =============================================================================
# Sync Service
# =============================================================================


class SyncService:
    """
    Service for synchronizing emails from connected accounts.

    Usage:
        service = SyncService()

        # Sync all accounts
        result = await service.sync_all()

        # Sync specific account
        result = await service.sync_gmail()

        # With progress callback
        async def on_progress(progress: SyncProgress):
            print(f"Synced {progress.emails_saved} emails...")

        result = await service.sync_all(progress_callback=on_progress)
    """

    def __init__(self):
        self._gmail_client: Optional[GmailClient] = None
        self._icloud_client: Optional[ICloudClient] = None
        self._parser = get_parser()

    # -------------------------------------------------------------------------
    # Main Sync Methods
    # -------------------------------------------------------------------------

    async def sync_all(
        self,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
        since_date: Optional[datetime] = None,
        full_sync: bool = False,
    ) -> SyncResult:
        """
        Sync emails from all connected accounts.

        Args:
            progress_callback: Optional callback for progress updates.
            since_date: Only fetch emails after this date.
            full_sync: If True, ignores last sync position.

        Returns:
            SyncResult with summary of sync operation.
        """
        start_time = datetime.now()
        accounts_synced = []
        total_fetched = 0
        total_saved = 0
        total_skipped = 0
        errors = []

        # Check which accounts are connected
        gmail_creds = get_gmail_credentials()
        icloud_creds = get_icloud_credentials()

        # Sync Gmail
        if gmail_creds:
            try:
                result = await self.sync_gmail(
                    progress_callback,
                    since_date=since_date,
                    full_sync=full_sync,
                )
                if result.success:
                    accounts_synced.append("gmail")
                    total_fetched += result.emails_fetched
                    total_saved += result.emails_saved
                    total_skipped += result.emails_skipped
                else:
                    errors.extend(result.errors)
            except Exception as e:
                logger.error(f"Gmail sync failed: {e}")
                errors.append(f"Gmail: {str(e)}")

        # Sync iCloud
        if icloud_creds:
            try:
                result = await self.sync_icloud(
                    progress_callback,
                    since_date=since_date,
                    full_sync=full_sync,
                )
                if result.success:
                    accounts_synced.append("icloud")
                    total_fetched += result.emails_fetched
                    total_saved += result.emails_saved
                    total_skipped += result.emails_skipped
                else:
                    errors.extend(result.errors)
            except Exception as e:
                logger.error(f"iCloud sync failed: {e}")
                errors.append(f"iCloud: {str(e)}")

        duration = (datetime.now() - start_time).total_seconds()

        return SyncResult(
            success=len(errors) == 0,
            accounts_synced=accounts_synced,
            emails_fetched=total_fetched,
            emails_saved=total_saved,
            emails_skipped=total_skipped,
            errors=errors,
            duration_seconds=duration,
        )

    async def sync_gmail(
        self,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
        since_date: Optional[datetime] = None,
        full_sync: bool = False,
    ) -> SyncResult:
        """
        Sync emails from Gmail account.

        Args:
            progress_callback: Optional callback for progress updates.
            since_date: Only fetch emails after this date.
            full_sync: If True, ignores last sync position.
        """
        start_time = datetime.now()

        # Report start
        if progress_callback:
            progress_callback(
                SyncProgress(account="gmail", event=SyncEventType.STARTED)
            )

        try:
            # Get or create Gmail client
            if self._gmail_client is None:
                self._gmail_client = GmailClient()

            # Check authentication
            if not self._gmail_client.is_authenticated():
                return SyncResult(
                    success=False,
                    accounts_synced=[],
                    emails_fetched=0,
                    emails_saved=0,
                    emails_skipped=0,
                    errors=["Gmail not authenticated"],
                    duration_seconds=0,
                )

            # Get sync state (skip if full_sync)
            since_history_id = None
            gmail_email = await self._gmail_client.get_account_email() or ""
            async with get_session() as session:
                # Query for sync state using SQLModel select
                result = await session.exec(
                    select(SyncState).where(
                        SyncState.account_type == EmailSource.GMAIL.value,
                        SyncState.account_email == gmail_email
                    )
                )
                # result.first() returns a Row tuple, get the actual object
                row = result.first()
                if row is not None:
                    state = row[0] if hasattr(row, '__getitem__') else row
                    if not full_sync:
                        since_history_id = state.gmail_history_id
                else:
                    # Create new sync state if doesn't exist
                    state = SyncState(
                        account_type=EmailSource.GMAIL.value,
                        account_email=gmail_email,
                        status=SyncStatus.IDLE.value,
                    )
                    session.add(state)
                    await session.commit()

            # Update sync state to syncing
            await self._update_sync_status(
                EmailSource.GMAIL, SyncStatus.SYNCING
            )

            # Fetch emails with optional date filter
            messages, new_history_id = await self._gmail_client.fetch_emails(
                since_history_id=since_history_id,
                since_date=since_date,
            )

            # Report progress
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        account="gmail",
                        event=SyncEventType.PROGRESS,
                        emails_fetched=len(messages),
                    )
                )

            # Parse and save emails
            saved, skipped = await self._save_emails(
                [self._parser.from_gmail(msg) for msg in messages],
                progress_callback,
            )

            # Update sync state
            await self._update_sync_state(
                EmailSource.GMAIL,
                gmail_history_id=new_history_id,
                status=SyncStatus.IDLE,
            )

            duration = (datetime.now() - start_time).total_seconds()

            # Report completion
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        account="gmail",
                        event=SyncEventType.COMPLETED,
                        emails_fetched=len(messages),
                        emails_saved=saved,
                    )
                )

            return SyncResult(
                success=True,
                accounts_synced=["gmail"],
                emails_fetched=len(messages),
                emails_saved=saved,
                emails_skipped=skipped,
                errors=[],
                duration_seconds=duration,
            )

        except Exception as e:
            logger.error(f"Gmail sync error: {e}")

            # Update sync state to error
            await self._update_sync_status(
                EmailSource.GMAIL, SyncStatus.ERROR, str(e)
            )

            if progress_callback:
                progress_callback(
                    SyncProgress(
                        account="gmail",
                        event=SyncEventType.ERROR,
                        error_message=str(e),
                    )
                )

            return SyncResult(
                success=False,
                accounts_synced=[],
                emails_fetched=0,
                emails_saved=0,
                emails_skipped=0,
                errors=[str(e)],
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )

    async def sync_icloud(
        self,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
        since_date: Optional[datetime] = None,
        full_sync: bool = False,
    ) -> SyncResult:
        """
        Sync emails from iCloud account.

        Args:
            progress_callback: Optional callback for progress updates.
            since_date: Only fetch emails after this date.
            full_sync: If True, ignores last sync position.
        """
        start_time = datetime.now()

        # Report start
        if progress_callback:
            progress_callback(
                SyncProgress(account="icloud", event=SyncEventType.STARTED)
            )

        try:
            # Get or create iCloud client
            if self._icloud_client is None:
                self._icloud_client = ICloudClient()

            # Check credentials
            if not self._icloud_client.has_credentials():
                return SyncResult(
                    success=False,
                    accounts_synced=[],
                    emails_fetched=0,
                    emails_saved=0,
                    emails_skipped=0,
                    errors=["iCloud not configured"],
                    duration_seconds=0,
                )

            # Get sync state (skip if full_sync)
            since_uid = None
            icloud_email = self._icloud_client.get_account_email() or ""
            async with get_session() as session:
                # Query for sync state using SQLModel select
                result = await session.exec(
                    select(SyncState).where(
                        SyncState.account_type == EmailSource.ICLOUD.value,
                        SyncState.account_email == icloud_email
                    )
                )
                # result.first() returns a Row tuple, get the actual object
                row = result.first()
                if row is not None:
                    state = row[0] if hasattr(row, '__getitem__') else row
                    if not full_sync:
                        since_uid = state.imap_last_uid
                else:
                    # Create new sync state if doesn't exist
                    state = SyncState(
                        account_type=EmailSource.ICLOUD.value,
                        account_email=icloud_email,
                        status=SyncStatus.IDLE.value,
                    )
                    session.add(state)
                    await session.commit()

            # Update sync state to syncing
            await self._update_sync_status(
                EmailSource.ICLOUD, SyncStatus.SYNCING
            )

            # Connect and fetch emails with optional date filter
            async with self._icloud_client:
                messages, new_last_uid = await self._icloud_client.fetch_emails(
                    since_uid=since_uid,
                    since_date=since_date,
                )

            # Report progress
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        account="icloud",
                        event=SyncEventType.PROGRESS,
                        emails_fetched=len(messages),
                    )
                )

            # Parse and save emails
            account_email = self._icloud_client.get_account_email() or ""
            saved, skipped = await self._save_emails(
                [self._parser.from_icloud(msg, account_email) for msg in messages],
                progress_callback,
            )

            # Update sync state
            await self._update_sync_state(
                EmailSource.ICLOUD,
                imap_last_uid=new_last_uid,
                status=SyncStatus.IDLE,
            )

            duration = (datetime.now() - start_time).total_seconds()

            # Report completion
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        account="icloud",
                        event=SyncEventType.COMPLETED,
                        emails_fetched=len(messages),
                        emails_saved=saved,
                    )
                )

            return SyncResult(
                success=True,
                accounts_synced=["icloud"],
                emails_fetched=len(messages),
                emails_saved=saved,
                emails_skipped=skipped,
                errors=[],
                duration_seconds=duration,
            )

        except Exception as e:
            logger.error(f"iCloud sync error: {e}")

            # Update sync state to error
            await self._update_sync_status(
                EmailSource.ICLOUD, SyncStatus.ERROR, str(e)
            )

            if progress_callback:
                progress_callback(
                    SyncProgress(
                        account="icloud",
                        event=SyncEventType.ERROR,
                        error_message=str(e),
                    )
                )

            return SyncResult(
                success=False,
                accounts_synced=[],
                emails_fetched=0,
                emails_saved=0,
                emails_skipped=0,
                errors=[str(e)],
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )

    # -------------------------------------------------------------------------
    # Database Operations
    # -------------------------------------------------------------------------

    async def _save_emails(
        self,
        emails: list[ParsedEmail],
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
    ) -> tuple[int, int]:
        """
        Save parsed emails to database.

        Returns:
            Tuple of (saved count, skipped count).
        """
        classifier = get_classifier()
        linker = get_application_linker()
        saved = 0
        skipped = 0
        updated = 0
        saved_email_ids: list[int] = []

        async with get_session() as session:
            for parsed in emails:
                if not self._is_parsed_email_usable(parsed):
                    skipped += 1
                    continue

                # Check for duplicate
                existing_result = await session.exec(
                    select(Email).where(Email.message_id == parsed.message_id)
                )
                existing_row = existing_result.first()
                if existing_row:
                    existing_email = (
                        existing_row[0]
                        if hasattr(existing_row, "__getitem__")
                        else existing_row
                    )
                    if self._merge_existing_email_content(existing_email, parsed):
                        session.add(existing_email)
                        updated += 1
                    skipped += 1
                    continue

                try:
                    classification = await classifier.classify(
                        parsed.subject or "",
                        parsed.body_text or parsed.body_snippet or "",
                        parsed.sender_email,
                    )
                except Exception as exc:
                    logger.warning(
                        "Classification failed for message %s, defaulting to OTHER: %s",
                        parsed.message_id,
                        exc,
                    )
                    classification = None

                # Create email record
                email = Email(
                    source_account=EmailSource(parsed.source_account),
                    message_id=parsed.message_id,
                    thread_id=parsed.thread_id,
                    subject=parsed.subject,
                    sender_name=parsed.sender_name,
                    sender_email=parsed.sender_email,
                    received_at=parsed.received_at,
                    body_text=parsed.body_text,
                    body_html=parsed.body_html,
                    body_snippet=parsed.body_snippet,
                    classified_as=classification.category if classification else None,
                    classification_confidence=classification.confidence if classification else None,
                    classification_method=classification.method if classification else None,
                    raw_headers=str(parsed.raw_headers) if parsed.raw_headers else None,
                )
                session.add(email)
                await session.flush()
                if email.id is not None:
                    saved_email_ids.append(email.id)
                saved += 1

            await session.commit()

        # Link after commit so IDs and persisted classification are available.
        if saved_email_ids:
            await self._link_saved_emails(saved_email_ids, linker)

        logger.info(
            "Saved %s emails, updated %s existing, skipped %s duplicates",
            saved,
            updated,
            skipped,
        )
        return saved, skipped

    def _merge_existing_email_content(self, email: Email, parsed: ParsedEmail) -> bool:
        """
        Enrich an existing email row when duplicate Message-ID is fetched again.

        This keeps old records up to date after parser improvements (for example,
        when earlier syncs stored plain text but later parsing can provide HTML).
        """
        changed = False

        incoming_html = (parsed.body_html or "").strip()
        incoming_text = (parsed.body_text or "").strip()
        incoming_snippet = (parsed.body_snippet or "").strip()

        existing_html = (email.body_html or "").strip()
        existing_text = (email.body_text or "").strip()
        existing_snippet = (email.body_snippet or "").strip()

        if incoming_html and not existing_html:
            email.body_html = incoming_html
            changed = True

        # Prefer richer text content when existing row is empty or clearly shorter.
        if incoming_text and (
            not existing_text or len(incoming_text) > len(existing_text) + 200
        ):
            email.body_text = incoming_text
            changed = True

        if incoming_snippet and not existing_snippet:
            email.body_snippet = incoming_snippet
            changed = True

        if parsed.sender_name and not email.sender_name:
            email.sender_name = parsed.sender_name
            changed = True

        if parsed.thread_id and not email.thread_id:
            email.thread_id = parsed.thread_id
            changed = True

        if parsed.raw_headers and not email.raw_headers:
            email.raw_headers = str(parsed.raw_headers)
            changed = True

        if changed:
            email.updated_at = datetime.now()

        return changed

    def _is_parsed_email_usable(self, parsed: ParsedEmail) -> bool:
        """
        Filter out parser artifacts that are not useful as real emails.
        """
        subject = (parsed.subject or "").strip().lower()
        sender = (parsed.sender_email or "").strip()
        message_id = (parsed.message_id or "").strip()

        if not message_id:
            return False

        # Some IMAP edge cases can produce synthetic IDs with no sender/subject.
        if message_id.startswith("icloud-") and not sender and subject in {
            "",
            "(no subject)",
            "no subject",
        }:
            logger.debug("Skipping iCloud parser artifact message: %s", message_id)
            return False

        return True

    async def _link_saved_emails(
        self,
        email_ids: list[int],
        linker,
    ) -> None:
        """Link newly saved emails to applications when possible."""
        async with get_session() as session:
            result = await session.exec(
                select(Email)
                .where(Email.id.in_(email_ids))
                .order_by(Email.received_at.asc())
            )
            rows = result.all()
            emails = [row[0] if hasattr(row, "__getitem__") else row for row in rows]

        for email in emails:
            try:
                await linker.process_email(email, auto_create=True)
            except Exception as exc:
                logger.warning("Failed to auto-link email %s: %s", email.id, exc)

    async def _get_or_create_sync_state(
        self, session: AsyncSession, account_type: EmailSource, account_email: str
    ) -> SyncState:
        """Get or create sync state for an account."""
        # Use .value for enum comparison (model stores strings)
        result = await session.exec(
            select(SyncState).where(
                SyncState.account_type == account_type.value,
                SyncState.account_email == account_email,
            )
        )
        state = result.first()

        if state is None:
            state = SyncState(
                account_type=account_type.value,
                account_email=account_email,
                status=SyncStatus.IDLE.value,
            )
            session.add(state)
            await session.commit()
            await session.refresh(state)

        return state

    async def _update_sync_state(
        self,
        account_type: EmailSource,
        gmail_history_id: Optional[str] = None,
        imap_last_uid: Optional[int] = None,
        status: Optional[SyncStatus] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update sync state for an account."""
        from sqlalchemy import update

        async with get_session() as session:
            # Build update values (use .value for enums)
            values = {}
            if gmail_history_id is not None:
                values["gmail_history_id"] = gmail_history_id
            if imap_last_uid is not None:
                values["imap_last_uid"] = imap_last_uid
            if status is not None:
                values["status"] = status.value  # Store enum value
                if status == SyncStatus.IDLE:
                    values["last_sync_at"] = datetime.now()
            if error_message is not None or "status" in values:
                values["error_message"] = error_message

            if values:
                stmt = (
                    update(SyncState)
                    .where(SyncState.account_type == account_type.value)  # Use .value
                    .values(**values)
                )
                await session.exec(stmt)
                await session.commit()

    async def _update_sync_status(
        self,
        account_type: EmailSource,
        status: SyncStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """Update just the sync status."""
        await self._update_sync_state(
            account_type, status=status, error_message=error_message
        )


# =============================================================================
# Singleton
# =============================================================================

_sync_service: Optional[SyncService] = None


def get_sync_service() -> SyncService:
    """Get singleton sync service instance."""
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service
