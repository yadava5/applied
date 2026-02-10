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

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.credentials import get_gmail_credentials, get_icloud_credentials
from jobtracker.database import get_session
from jobtracker.database.models import Email, EmailSource, SyncState, SyncStatus
from jobtracker.email_clients import (
    GmailClient,
    ICloudClient,
    ParsedEmail,
    generate_dedup_key,
    get_parser,
)

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
        saved = 0
        skipped = 0

        async with get_session() as session:
            for parsed in emails:
                # Check for duplicate
                existing = await session.exec(
                    select(Email).where(Email.message_id == parsed.message_id)
                )
                if existing.first():
                    skipped += 1
                    continue

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
                    body_snippet=parsed.body_snippet,
                    raw_headers=str(parsed.raw_headers) if parsed.raw_headers else None,
                )
                session.add(email)
                saved += 1

            await session.commit()

        logger.info(f"Saved {saved} emails, skipped {skipped} duplicates")
        return saved, skipped

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
