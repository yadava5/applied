"""
Email synchronization API endpoints.

Handles email sync operations for connected accounts.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from jobtracker.credentials import get_gmail_credentials, get_icloud_credentials
from jobtracker.services import get_sync_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["synchronization"])


# =============================================================================
# Request/Response Models
# =============================================================================


class SyncRequest(BaseModel):
    """Request to trigger email sync."""

    accounts: Optional[list[str]] = Field(
        default=None,
        description="Accounts to sync. None = all connected accounts.",
        examples=[["gmail", "icloud"], ["gmail"], None],
    )


class SyncResultResponse(BaseModel):
    """Response after sync operation."""

    success: bool
    accounts_synced: list[str]
    emails_fetched: int
    emails_saved: int
    emails_skipped: int
    errors: list[str]
    duration_seconds: float


class SyncStatusResponse(BaseModel):
    """Current sync status for all accounts."""

    gmail: Optional[dict] = None
    icloud: Optional[dict] = None
    last_sync: Optional[datetime] = None


# =============================================================================
# Endpoints
# =============================================================================


@router.post("", response_model=SyncResultResponse)
async def trigger_sync(request: SyncRequest = SyncRequest()) -> SyncResultResponse:
    """
    Trigger email synchronization.

    Syncs emails from connected accounts (Gmail and/or iCloud).

    - If no accounts specified, syncs all connected accounts.
    - Uses incremental sync (only fetches new emails since last sync).
    - Deduplicates emails by Message-ID.
    """
    service = get_sync_service()

    # Check if any accounts are connected
    gmail_creds = get_gmail_credentials()
    icloud_creds = get_icloud_credentials()

    if not gmail_creds and not icloud_creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No email accounts connected. Connect Gmail or iCloud first.",
        )

    # Filter to requested accounts
    if request.accounts:
        if "gmail" in request.accounts and not gmail_creds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Gmail account not connected",
            )
        if "icloud" in request.accounts and not icloud_creds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="iCloud account not connected",
            )

    # Run sync
    try:
        if request.accounts and len(request.accounts) == 1:
            # Sync specific account
            if request.accounts[0] == "gmail":
                result = await service.sync_gmail()
            elif request.accounts[0] == "icloud":
                result = await service.sync_icloud()
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown account type: {request.accounts[0]}",
                )
        else:
            # Sync all
            result = await service.sync_all()

        return SyncResultResponse(
            success=result.success,
            accounts_synced=result.accounts_synced,
            emails_fetched=result.emails_fetched,
            emails_saved=result.emails_saved,
            emails_skipped=result.emails_skipped,
            errors=result.errors,
            duration_seconds=result.duration_seconds,
        )

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status() -> SyncStatusResponse:
    """
    Get current sync status for all accounts.

    Returns last sync time and status for each connected account.
    """
    from jobtracker.database import get_session
    from jobtracker.database.models import EmailSource, SyncState
    from sqlalchemy import select

    gmail_status = None
    icloud_status = None
    last_sync = None

    async with get_session() as session:
        # Get Gmail sync state
        result = await session.exec(
            select(SyncState).where(SyncState.account_type == EmailSource.GMAIL)
        )
        gmail_state = result.first()
        if gmail_state:
            gmail_status = {
                "email": gmail_state.account_email,
                "status": gmail_state.status.value,
                "last_sync": gmail_state.last_sync_at.isoformat() if gmail_state.last_sync_at else None,
                "error": gmail_state.error_message,
            }
            if gmail_state.last_sync_at:
                last_sync = gmail_state.last_sync_at

        # Get iCloud sync state
        result = await session.exec(
            select(SyncState).where(SyncState.account_type == EmailSource.ICLOUD)
        )
        icloud_state = result.first()
        if icloud_state:
            icloud_status = {
                "email": icloud_state.account_email,
                "status": icloud_state.status.value,
                "last_sync": icloud_state.last_sync_at.isoformat() if icloud_state.last_sync_at else None,
                "error": icloud_state.error_message,
            }
            if icloud_state.last_sync_at:
                if last_sync is None or icloud_state.last_sync_at > last_sync:
                    last_sync = icloud_state.last_sync_at

    return SyncStatusResponse(
        gmail=gmail_status,
        icloud=icloud_status,
        last_sync=last_sync,
    )
