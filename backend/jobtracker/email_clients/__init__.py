"""
Email Clients Module
====================

Provides async email fetching from Gmail and iCloud Mail.

Components:
-----------
- GmailClient: Gmail API OAuth2 client with incremental sync
- ICloudClient: iCloud IMAP client using aioimaplib
- EmailParser: Shared email parsing and normalization

Both clients return normalized email data that can be stored
in the database and processed by the classifier.

Usage:
------
    from jobtracker.email_clients import GmailClient, ICloudClient

    # Gmail
    gmail = GmailClient()
    if gmail.is_authenticated():
        messages, history_id = await gmail.fetch_emails()

    # iCloud
    async with ICloudClient() as icloud:
        messages, last_uid = await icloud.fetch_emails()
"""

from jobtracker.email_clients.gmail import GmailClient, GmailMessage
from jobtracker.email_clients.icloud import ICloudClient, IMAPMessage
from jobtracker.email_clients.parser import (
    EmailParser,
    ParsedEmail,
    generate_dedup_key,
    get_parser,
    is_likely_job_related,
)

__all__ = [
    # Gmail
    "GmailClient",
    "GmailMessage",
    # iCloud
    "ICloudClient",
    "IMAPMessage",
    # Parser
    "EmailParser",
    "ParsedEmail",
    "get_parser",
    "generate_dedup_key",
    "is_likely_job_related",
]
