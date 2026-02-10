"""
Services Module
===============

Business logic layer for JobTracker operations.

Components:
-----------
- SyncService: Orchestrates email sync from Gmail and iCloud
- classification_service: Manages email classification pipeline (Phase 3)
- analytics_service: Computes statistics and trends (Phase 7)

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

__all__ = [
    "SyncService",
    "SyncResult",
    "SyncProgress",
    "SyncEventType",
    "get_sync_service",
]
