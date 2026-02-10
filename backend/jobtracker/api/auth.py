"""
Authentication API endpoints.

Handles OAuth flows and credential management for:
- Gmail (OAuth2)
- iCloud Mail (app-specific password)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from jobtracker.credentials import (
    GmailCredentials,
    ICloudCredentials,
    delete_gmail_credentials,
    delete_icloud_credentials,
    get_gmail_credentials,
    get_icloud_credentials,
    has_gmail_credentials,
    has_icloud_credentials,
    save_gmail_client_secret,
    save_icloud_credentials,
)
from jobtracker.email_clients import GmailClient, ICloudClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


# =============================================================================
# Request/Response Models
# =============================================================================


class GmailClientSecretRequest(BaseModel):
    """Request to set up Gmail client secret."""

    client_secret: dict = Field(
        ...,
        description="The client_secret.json content from Google Cloud Console",
        examples=[
            {
                "installed": {
                    "client_id": "xxx.apps.googleusercontent.com",
                    "client_secret": "xxx",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        ],
    )


class GmailAuthResponse(BaseModel):
    """Response after Gmail authentication."""

    success: bool
    email: Optional[str] = None
    message: str


class ICloudAuthRequest(BaseModel):
    """Request to authenticate with iCloud."""

    email: EmailStr = Field(..., description="iCloud email address")
    app_password: str = Field(
        ...,
        description="App-specific password from Apple ID settings",
        min_length=10,
    )


class ICloudAuthResponse(BaseModel):
    """Response after iCloud authentication."""

    success: bool
    email: Optional[str] = None
    message: str


class AccountStatus(BaseModel):
    """Status of a connected email account."""

    connected: bool
    email: Optional[str] = None


class AuthStatusResponse(BaseModel):
    """Response for auth status check."""

    gmail: AccountStatus
    icloud: AccountStatus


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status() -> AuthStatusResponse:
    """
    Get authentication status for all accounts.

    Returns which email accounts are connected.
    """
    gmail_creds = get_gmail_credentials()
    icloud_creds = get_icloud_credentials()

    return AuthStatusResponse(
        gmail=AccountStatus(
            connected=gmail_creds is not None,
            email=gmail_creds.email if gmail_creds else None,
        ),
        icloud=AccountStatus(
            connected=icloud_creds is not None,
            email=icloud_creds.email if icloud_creds else None,
        ),
    )


# -------------------------------------------------------------------------
# Gmail
# -------------------------------------------------------------------------


@router.post("/gmail/client-secret")
async def set_gmail_client_secret(request: GmailClientSecretRequest) -> dict:
    """
    Store Gmail OAuth client secret.

    This must be called before initiating Gmail OAuth flow.
    The client_secret.json comes from Google Cloud Console.
    """
    # Validate structure
    if "installed" not in request.client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client secret format. Must contain 'installed' key.",
        )

    required_fields = ["client_id", "client_secret", "auth_uri", "token_uri"]
    installed = request.client_secret["installed"]
    missing = [f for f in required_fields if f not in installed]

    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required fields: {missing}",
        )

    # Save to keychain
    success = save_gmail_client_secret(request.client_secret)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save client secret to keychain",
        )

    return {"success": True, "message": "Gmail client secret stored successfully"}


@router.post("/gmail/authenticate", response_model=GmailAuthResponse)
async def authenticate_gmail() -> GmailAuthResponse:
    """
    Start Gmail OAuth2 authentication flow.

    Opens a browser window for the user to grant access.
    Requires client secret to be set first via /gmail/client-secret.
    """
    client = GmailClient()

    try:
        success = await client.authenticate()

        if success:
            creds = get_gmail_credentials()
            return GmailAuthResponse(
                success=True,
                email=creds.email if creds else None,
                message="Gmail authentication successful",
            )
        else:
            return GmailAuthResponse(
                success=False,
                message="Gmail authentication failed. Check logs for details.",
            )

    except Exception as e:
        logger.error(f"Gmail auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.delete("/gmail")
async def disconnect_gmail(delete_emails: bool = False) -> dict:
    """
    Disconnect Gmail account.

    Removes stored OAuth credentials from keychain.

    Args:
        delete_emails: If True, also deletes all emails from this account.
    """
    if not has_gmail_credentials():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gmail account not connected",
        )

    emails_deleted = 0
    if delete_emails:
        # Import here to avoid circular imports
        from sqlalchemy import delete

        from jobtracker.database import get_session
        from jobtracker.database.models import Email, EmailSource, SyncState

        async with get_session() as session:
            # Delete emails from Gmail
            result = await session.exec(
                delete(Email).where(Email.source_account == EmailSource.GMAIL)
            )
            emails_deleted = result.rowcount if hasattr(result, "rowcount") else 0

            # Delete sync state for Gmail
            await session.exec(
                delete(SyncState).where(
                    SyncState.account_type == EmailSource.GMAIL.value
                )
            )
            await session.commit()

    success = delete_gmail_credentials()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete Gmail credentials",
        )

    message = "Gmail account disconnected"
    if delete_emails:
        message += f" and {emails_deleted} emails deleted"

    return {"success": True, "message": message, "emails_deleted": emails_deleted}


# -------------------------------------------------------------------------
# iCloud
# -------------------------------------------------------------------------


@router.post("/icloud", response_model=ICloudAuthResponse)
async def authenticate_icloud(request: ICloudAuthRequest) -> ICloudAuthResponse:
    """
    Connect iCloud Mail account.

    Requires an app-specific password generated from Apple ID settings.
    The app-specific password is stored securely in macOS Keychain.

    To generate an app-specific password:
    1. Go to appleid.apple.com
    2. Sign in with your Apple ID
    3. Go to Security > App-Specific Passwords
    4. Click Generate Password
    5. Enter "JobTracker" as the password label
    6. Copy the generated password (format: xxxx-xxxx-xxxx-xxxx)
    """
    # Create and save credentials
    credentials = ICloudCredentials(
        email=request.email,
        app_password=request.app_password,
    )

    # Test connection before saving
    client = ICloudClient()

    # Temporarily save to test
    save_icloud_credentials(credentials)

    try:
        success = await client.test_connection()

        if success:
            return ICloudAuthResponse(
                success=True,
                email=request.email,
                message="iCloud Mail connected successfully",
            )
        else:
            # Remove invalid credentials
            delete_icloud_credentials()
            return ICloudAuthResponse(
                success=False,
                message="Failed to connect to iCloud. Check email and app-specific password.",
            )

    except Exception as e:
        logger.error(f"iCloud auth error: {e}")
        # Remove credentials on error
        delete_icloud_credentials()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Connection test failed: {str(e)}",
        )


@router.delete("/icloud")
async def disconnect_icloud(delete_emails: bool = False) -> dict:
    """
    Disconnect iCloud Mail account.

    Removes stored credentials from keychain.

    Args:
        delete_emails: If True, also deletes all emails from this account.
    """
    if not has_icloud_credentials():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="iCloud account not connected",
        )

    emails_deleted = 0
    if delete_emails:
        # Import here to avoid circular imports
        from sqlalchemy import delete

        from jobtracker.database import get_session
        from jobtracker.database.models import Email, EmailSource, SyncState

        async with get_session() as session:
            # Delete emails from iCloud
            result = await session.exec(
                delete(Email).where(Email.source_account == EmailSource.ICLOUD)
            )
            emails_deleted = result.rowcount if hasattr(result, "rowcount") else 0

            # Delete sync state for iCloud
            await session.exec(
                delete(SyncState).where(
                    SyncState.account_type == EmailSource.ICLOUD.value
                )
            )
            await session.commit()

    success = delete_icloud_credentials()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete iCloud credentials",
        )

    message = "iCloud account disconnected"
    if delete_emails:
        message += f" and {emails_deleted} emails deleted"

    return {"success": True, "message": message, "emails_deleted": emails_deleted}
