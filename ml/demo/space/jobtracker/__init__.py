"""
JobTracker Backend
==================

Email-powered job application tracker with ML classification.

This package provides:
- Async FastAPI backend for email syncing and classification
- Gmail OAuth2 and iCloud IMAP integration
- 3-layer hybrid ML classifier (rules → embeddings → SetFit)
- SQLite database with async access via aiosqlite

Modules:
--------
- database: Async SQLite models and connection management
- email_clients: Gmail and iCloud email fetching
- classifier: Rule-based, embedding, and SetFit classifiers
- services: Business logic for sync, classification, analytics
- api: FastAPI route handlers

Usage:
------
    $ uvicorn jobtracker.main:app --host 127.0.0.1 --port 8000
"""

__version__ = "0.1.0"
__author__ = "Ayush Yadav"
