"""
Services Module
===============

Business logic layer for JobTracker operations.

Components:
-----------
- SyncService: Orchestrates email sync from Gmail and iCloud
- Application insights: ghosted detection + follow-up reminders

Services coordinate between the API layer and lower-level
components (database, email clients, classifier).

Usage:
------
    from jobtracker.services import get_sync_service

    service = get_sync_service()
    result = await service.sync_all()
"""

from jobtracker.services.sync import (
    SyncEventType,
    SyncProgress,
    SyncResult,
    SyncService,
    get_sync_service,
)
from jobtracker.services.application_insights import (
    FollowUpReminder,
    get_follow_up_reminders,
    mark_ghosted_applications,
)

__all__ = [
    "SyncService",
    "SyncResult",
    "SyncProgress",
    "SyncEventType",
    "get_sync_service",
    "FollowUpReminder",
    "get_follow_up_reminders",
    "mark_ghosted_applications",
]
