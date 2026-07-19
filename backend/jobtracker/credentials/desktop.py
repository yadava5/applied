"""macOS Keychain credential backend (desktop deployment).

This is a lift-and-shift of the original ``jobtracker.credentials``
module (pre-C4). Public functions retain their original signatures
and behavior so existing desktop callers (``api/auth.py``,
``email_clients/gmail.py``, ``email_clients/icloud.py``, etc.)
continue to work unchanged.

The cloud deployment uses ``jobtracker.credentials.cloud`` instead;
the two backends are completely independent — ``keyring`` is imported
only here and, critically, only *lazily* (see ``_keyring`` below) so it
never enters the cloud (Vercel) import graph. The package ``__init__``
re-exports these functions for backward compatibility, so merely
importing ``jobtracker.credentials`` — which the cloud credential store's
parent package does — would otherwise drag ``keyring`` in and break both
the serverless deploy and the import-hygiene test in
``tests/test_main_cloud.py``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from jobtracker.config import settings
from jobtracker.credentials.types import GmailCredentials, ICloudCredentials

logger = logging.getLogger(__name__)


def _keyring():
    """Import ``keyring`` + ``KeyringError`` on first use.

    Returned as a tuple so callers bind both to local names:

        keyring, KeyringError = _keyring()

    Deferring the import to call time (rather than module load) is what
    keeps the macOS-only ``keyring`` dependency out of the cloud import
    graph while leaving every function body's ``keyring.*`` calls and
    ``except KeyringError`` handlers working exactly as before.
    """

    import keyring
    from keyring.errors import KeyringError

    return keyring, KeyringError


# Service name for all JobTracker credentials in the macOS Keychain.
SERVICE_NAME = settings.keychain_service

# Keys for different credential types.
GMAIL_CREDENTIALS_KEY = "gmail_oauth"
ICLOUD_CREDENTIALS_KEY = "icloud_mail"
GMAIL_CLIENT_SECRET_KEY = "gmail_client_secret"


# -----------------------------------------------------------------------------
# Gmail credentials
# -----------------------------------------------------------------------------


def save_gmail_credentials(credentials: GmailCredentials) -> bool:
    """Save Gmail OAuth credentials to the Keychain."""

    keyring, KeyringError = _keyring()
    try:
        keyring.set_password(SERVICE_NAME, GMAIL_CREDENTIALS_KEY, credentials.to_json())
        logger.info("Gmail credentials saved for %s", credentials.email)
        return True
    except KeyringError as exc:
        logger.error("Failed to save Gmail credentials: %s", exc)
        return False


def get_gmail_credentials() -> Optional[GmailCredentials]:
    """Retrieve Gmail OAuth credentials from the Keychain."""

    keyring, KeyringError = _keyring()
    try:
        raw = keyring.get_password(SERVICE_NAME, GMAIL_CREDENTIALS_KEY)
        if raw is None:
            logger.debug("No Gmail credentials found in keychain")
            return None
        credentials = GmailCredentials.from_json(raw)
        logger.debug("Gmail credentials retrieved for %s", credentials.email)
        return credentials
    except (KeyringError, json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to retrieve Gmail credentials: %s", exc)
        return None


def delete_gmail_credentials() -> bool:
    """Delete Gmail OAuth credentials from the Keychain."""

    keyring, KeyringError = _keyring()
    try:
        keyring.delete_password(SERVICE_NAME, GMAIL_CREDENTIALS_KEY)
        logger.info("Gmail credentials deleted from keychain")
        return True
    except KeyringError as exc:
        logger.error("Failed to delete Gmail credentials: %s", exc)
        return False


def update_gmail_access_token(access_token: str, token_expiry: datetime) -> bool:
    """Update only the access token (after refresh)."""

    credentials = get_gmail_credentials()
    if credentials is None:
        logger.error("Cannot update access token: no credentials found")
        return False

    credentials.access_token = access_token
    credentials.token_expiry = token_expiry
    return save_gmail_credentials(credentials)


# -----------------------------------------------------------------------------
# Gmail client secret (Google Cloud Console download)
# -----------------------------------------------------------------------------


def save_gmail_client_secret(client_secret_json: dict) -> bool:
    """Save Gmail OAuth client secret (from Google Cloud Console)."""

    keyring, KeyringError = _keyring()
    try:
        keyring.set_password(
            SERVICE_NAME, GMAIL_CLIENT_SECRET_KEY, json.dumps(client_secret_json)
        )
        logger.info("Gmail client secret saved to keychain")
        return True
    except KeyringError as exc:
        logger.error("Failed to save Gmail client secret: %s", exc)
        return False


def get_gmail_client_secret() -> Optional[dict]:
    """Retrieve Gmail OAuth client secret from the Keychain."""

    keyring, KeyringError = _keyring()
    try:
        raw = keyring.get_password(SERVICE_NAME, GMAIL_CLIENT_SECRET_KEY)
        if raw is None:
            logger.debug("No Gmail client secret found in keychain")
            return None
        return json.loads(raw)
    except (KeyringError, json.JSONDecodeError) as exc:
        logger.error("Failed to retrieve Gmail client secret: %s", exc)
        return None


# -----------------------------------------------------------------------------
# iCloud credentials
# -----------------------------------------------------------------------------


def save_icloud_credentials(credentials: ICloudCredentials) -> bool:
    """Save iCloud Mail credentials to the Keychain."""

    keyring, KeyringError = _keyring()
    try:
        keyring.set_password(SERVICE_NAME, ICLOUD_CREDENTIALS_KEY, credentials.to_json())
        logger.info("iCloud credentials saved for %s", credentials.email)
        return True
    except KeyringError as exc:
        logger.error("Failed to save iCloud credentials: %s", exc)
        return False


def get_icloud_credentials() -> Optional[ICloudCredentials]:
    """Retrieve iCloud Mail credentials from the Keychain."""

    keyring, KeyringError = _keyring()
    try:
        raw = keyring.get_password(SERVICE_NAME, ICLOUD_CREDENTIALS_KEY)
        if raw is None:
            logger.debug("No iCloud credentials found in keychain")
            return None
        credentials = ICloudCredentials.from_json(raw)
        logger.debug("iCloud credentials retrieved for %s", credentials.email)
        return credentials
    except (KeyringError, json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to retrieve iCloud credentials: %s", exc)
        return None


def delete_icloud_credentials() -> bool:
    """Delete iCloud Mail credentials from the Keychain."""

    keyring, KeyringError = _keyring()
    try:
        keyring.delete_password(SERVICE_NAME, ICLOUD_CREDENTIALS_KEY)
        logger.info("iCloud credentials deleted from keychain")
        return True
    except KeyringError as exc:
        logger.error("Failed to delete iCloud credentials: %s", exc)
        return False


# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------


def has_gmail_credentials() -> bool:
    """Check if Gmail credentials exist in the Keychain."""

    return get_gmail_credentials() is not None


def has_icloud_credentials() -> bool:
    """Check if iCloud credentials exist in the Keychain."""

    return get_icloud_credentials() is not None


def clear_all_credentials() -> bool:
    """Clear all JobTracker credentials from the Keychain."""

    keyring, KeyringError = _keyring()
    for key in (GMAIL_CREDENTIALS_KEY, ICLOUD_CREDENTIALS_KEY, GMAIL_CLIENT_SECRET_KEY):
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except KeyringError:
            pass  # Credential doesn't exist, that's fine.

    logger.info("All credentials cleared from keychain")
    return True
