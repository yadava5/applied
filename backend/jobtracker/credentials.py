"""
Secure credential management using macOS Keychain.

This module provides a unified interface for storing and retrieving
sensitive credentials (OAuth tokens, passwords) using the system keychain.

Uses the `keyring` library which automatically uses the macOS Keychain
backend on macOS systems.

Security Notes:
- Credentials are stored encrypted in the system keychain
- Access requires user authentication (Touch ID / password)
- Each credential is scoped to the JobTracker application
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import keyring
from keyring.errors import KeyringError

from jobtracker.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class GmailCredentials:
    """Gmail OAuth2 credentials stored in keychain."""

    access_token: str
    refresh_token: str
    token_expiry: datetime
    email: str
    scopes: list[str]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expiry": self.token_expiry.isoformat(),
            "email": self.email,
            "scopes": self.scopes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GmailCredentials":
        """Create from dictionary (JSON deserialization)."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            token_expiry=datetime.fromisoformat(data["token_expiry"]),
            email=data["email"],
            scopes=data.get("scopes", []),
        )

    def is_expired(self) -> bool:
        """Check if access token has expired."""
        # Add 5-minute buffer before actual expiry
        from datetime import timedelta

        return datetime.now() >= (self.token_expiry - timedelta(minutes=5))


@dataclass
class ICloudCredentials:
    """iCloud Mail credentials stored in keychain."""

    email: str
    app_password: str  # App-specific password (not the main Apple ID password)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "email": self.email,
            "app_password": self.app_password,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ICloudCredentials":
        """Create from dictionary (JSON deserialization)."""
        return cls(
            email=data["email"],
            app_password=data["app_password"],
        )


# =============================================================================
# Keychain Keys
# =============================================================================

# Service name for all JobTracker credentials
SERVICE_NAME = settings.keychain_service

# Keys for different credential types
GMAIL_CREDENTIALS_KEY = "gmail_oauth"
ICLOUD_CREDENTIALS_KEY = "icloud_mail"
GMAIL_CLIENT_SECRET_KEY = "gmail_client_secret"


# =============================================================================
# Gmail Credential Management
# =============================================================================


def save_gmail_credentials(credentials: GmailCredentials) -> bool:
    """
    Save Gmail OAuth credentials to keychain.

    Args:
        credentials: Gmail OAuth credentials to store.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        # Store as JSON string (keyring stores strings)
        json_data = json.dumps(credentials.to_dict())
        keyring.set_password(SERVICE_NAME, GMAIL_CREDENTIALS_KEY, json_data)
        logger.info(f"Gmail credentials saved for {credentials.email}")
        return True
    except KeyringError as e:
        logger.error(f"Failed to save Gmail credentials: {e}")
        return False


def get_gmail_credentials() -> Optional[GmailCredentials]:
    """
    Retrieve Gmail OAuth credentials from keychain.

    Returns:
        GmailCredentials if found, None otherwise.
    """
    try:
        json_data = keyring.get_password(SERVICE_NAME, GMAIL_CREDENTIALS_KEY)
        if json_data is None:
            logger.debug("No Gmail credentials found in keychain")
            return None

        data = json.loads(json_data)
        credentials = GmailCredentials.from_dict(data)
        logger.debug(f"Gmail credentials retrieved for {credentials.email}")
        return credentials
    except (KeyringError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to retrieve Gmail credentials: {e}")
        return None


def delete_gmail_credentials() -> bool:
    """
    Delete Gmail OAuth credentials from keychain.

    Returns:
        True if deleted successfully, False otherwise.
    """
    try:
        keyring.delete_password(SERVICE_NAME, GMAIL_CREDENTIALS_KEY)
        logger.info("Gmail credentials deleted from keychain")
        return True
    except KeyringError as e:
        logger.error(f"Failed to delete Gmail credentials: {e}")
        return False


def update_gmail_access_token(
    access_token: str, token_expiry: datetime
) -> bool:
    """
    Update only the access token (after refresh).

    Args:
        access_token: New access token.
        token_expiry: New expiry time.

    Returns:
        True if updated successfully, False otherwise.
    """
    credentials = get_gmail_credentials()
    if credentials is None:
        logger.error("Cannot update access token: no credentials found")
        return False

    credentials.access_token = access_token
    credentials.token_expiry = token_expiry
    return save_gmail_credentials(credentials)


# =============================================================================
# Gmail Client Secret Management
# =============================================================================


def save_gmail_client_secret(client_secret_json: dict) -> bool:
    """
    Save Gmail OAuth client secret (from Google Cloud Console).

    This is the client_secret.json downloaded from Google Cloud Console.

    Args:
        client_secret_json: The full client_secret.json content.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        json_data = json.dumps(client_secret_json)
        keyring.set_password(SERVICE_NAME, GMAIL_CLIENT_SECRET_KEY, json_data)
        logger.info("Gmail client secret saved to keychain")
        return True
    except KeyringError as e:
        logger.error(f"Failed to save Gmail client secret: {e}")
        return False


def get_gmail_client_secret() -> Optional[dict]:
    """
    Retrieve Gmail OAuth client secret from keychain.

    Returns:
        Client secret dict if found, None otherwise.
    """
    try:
        json_data = keyring.get_password(SERVICE_NAME, GMAIL_CLIENT_SECRET_KEY)
        if json_data is None:
            logger.debug("No Gmail client secret found in keychain")
            return None

        return json.loads(json_data)
    except (KeyringError, json.JSONDecodeError) as e:
        logger.error(f"Failed to retrieve Gmail client secret: {e}")
        return None


# =============================================================================
# iCloud Credential Management
# =============================================================================


def save_icloud_credentials(credentials: ICloudCredentials) -> bool:
    """
    Save iCloud Mail credentials to keychain.

    Args:
        credentials: iCloud credentials (email + app-specific password).

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        json_data = json.dumps(credentials.to_dict())
        keyring.set_password(SERVICE_NAME, ICLOUD_CREDENTIALS_KEY, json_data)
        logger.info(f"iCloud credentials saved for {credentials.email}")
        return True
    except KeyringError as e:
        logger.error(f"Failed to save iCloud credentials: {e}")
        return False


def get_icloud_credentials() -> Optional[ICloudCredentials]:
    """
    Retrieve iCloud Mail credentials from keychain.

    Returns:
        ICloudCredentials if found, None otherwise.
    """
    try:
        json_data = keyring.get_password(SERVICE_NAME, ICLOUD_CREDENTIALS_KEY)
        if json_data is None:
            logger.debug("No iCloud credentials found in keychain")
            return None

        data = json.loads(json_data)
        credentials = ICloudCredentials.from_dict(data)
        logger.debug(f"iCloud credentials retrieved for {credentials.email}")
        return credentials
    except (KeyringError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to retrieve iCloud credentials: {e}")
        return None


def delete_icloud_credentials() -> bool:
    """
    Delete iCloud Mail credentials from keychain.

    Returns:
        True if deleted successfully, False otherwise.
    """
    try:
        keyring.delete_password(SERVICE_NAME, ICLOUD_CREDENTIALS_KEY)
        logger.info("iCloud credentials deleted from keychain")
        return True
    except KeyringError as e:
        logger.error(f"Failed to delete iCloud credentials: {e}")
        return False


# =============================================================================
# Utility Functions
# =============================================================================


def has_gmail_credentials() -> bool:
    """Check if Gmail credentials exist in keychain."""
    return get_gmail_credentials() is not None


def has_icloud_credentials() -> bool:
    """Check if iCloud credentials exist in keychain."""
    return get_icloud_credentials() is not None


def clear_all_credentials() -> bool:
    """
    Clear all JobTracker credentials from keychain.

    Use with caution - this removes all stored auth data.

    Returns:
        True if all credentials cleared successfully.
    """
    success = True

    # Try to delete each credential type (ignore if not found)
    for key in [GMAIL_CREDENTIALS_KEY, ICLOUD_CREDENTIALS_KEY, GMAIL_CLIENT_SECRET_KEY]:
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except KeyringError:
            pass  # Credential doesn't exist, that's fine

    logger.info("All credentials cleared from keychain")
    return success
