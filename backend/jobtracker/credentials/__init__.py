"""JobTracker credential-management dispatcher (issue #21, C4).

The original single-file ``jobtracker.credentials`` module was split into
a package so desktop and cloud deployments can use completely separate
backends:

- ``jobtracker.credentials.desktop`` — macOS Keychain via ``keyring``.
  Synchronous API (the historical one). ``import keyring`` lives here
  and nowhere else, so it never enters the cloud import graph.

- ``jobtracker.credentials.cloud`` — Supabase Postgres rows encrypted
  with Fernet. Async API that takes an explicit ``user_id: UUID`` as
  first argument. Used by cloud-only routers (Gmail web OAuth in C5,
  iCloud web form in C5, cron sync in C7).

For **backward compatibility** every public symbol from
``jobtracker.credentials.desktop`` is re-exported at the package top
level. This means historical imports such as::

    from jobtracker.credentials import save_gmail_credentials

continue to work verbatim on desktop. Cloud routers import from the
fully-qualified ``jobtracker.credentials.cloud`` module to avoid any
ambiguity about which backend they are speaking to.

The dispatcher does NOT switch backends at import time based on
``settings.deployment``. Keeping the two backends behind separate
module paths makes the boundary explicit and prevents
accidental-wrong-backend bugs — callers have to name the backend they
want.
"""

from jobtracker.credentials.desktop import (
    GMAIL_CLIENT_SECRET_KEY,
    GMAIL_CREDENTIALS_KEY,
    ICLOUD_CREDENTIALS_KEY,
    SERVICE_NAME,
    clear_all_credentials,
    delete_gmail_credentials,
    delete_icloud_credentials,
    get_gmail_client_secret,
    get_gmail_credentials,
    get_icloud_credentials,
    has_gmail_credentials,
    has_icloud_credentials,
    save_gmail_client_secret,
    save_gmail_credentials,
    save_icloud_credentials,
    update_gmail_access_token,
)
from jobtracker.credentials.types import GmailCredentials, ICloudCredentials

__all__ = [
    "GmailCredentials",
    "ICloudCredentials",
    "GMAIL_CLIENT_SECRET_KEY",
    "GMAIL_CREDENTIALS_KEY",
    "ICLOUD_CREDENTIALS_KEY",
    "SERVICE_NAME",
    "clear_all_credentials",
    "delete_gmail_credentials",
    "delete_icloud_credentials",
    "get_gmail_client_secret",
    "get_gmail_credentials",
    "get_icloud_credentials",
    "has_gmail_credentials",
    "has_icloud_credentials",
    "save_gmail_client_secret",
    "save_gmail_credentials",
    "save_icloud_credentials",
    "update_gmail_access_token",
]
