"""
Services Module
===============

Business logic layer for JobTracker operations.

Components:
-----------
- sync_service: Orchestrates email sync from Gmail and iCloud
- classification_service: Manages email classification pipeline
- analytics_service: Computes statistics and trends
- task_manager: Background task tracking and status

Services coordinate between the API layer and lower-level
components (database, email clients, classifier).

Usage:
------
    from jobtracker.services import SyncService, AnalyticsService

    sync = SyncService()
    result = await sync.sync_all_accounts()
"""

# Imports will be added as modules are implemented
__all__: list[str] = []
