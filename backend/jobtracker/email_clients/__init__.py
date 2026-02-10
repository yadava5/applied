"""
Email Clients Module
====================

Provides async email fetching from Gmail and iCloud Mail.

Components:
-----------
- gmail_client: Gmail API OAuth2 client with incremental sync
- icloud_client: iCloud IMAP client using aioimaplib
- email_parser: Shared email parsing and normalization

Both clients return normalized email data that can be stored
in the database and processed by the classifier.

Usage:
------
    from jobtracker.email_clients import GmailClient, ICloudClient

    gmail = GmailClient()
    emails = await gmail.fetch_new_emails()
"""

# Imports will be added as modules are implemented
__all__: list[str] = []
