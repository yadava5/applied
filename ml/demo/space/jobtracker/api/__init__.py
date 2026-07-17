"""
API Module
==========

FastAPI route handlers for the JobTracker REST API.

Routers:
--------
- auth_router: Gmail OAuth and iCloud credential management
- sync_router: Email synchronization
- emails_router: Email listing and details
- classification_router: Email classification and user corrections (Phase 3)
- application_routes: Job application CRUD (Phase 4)
- analytics_routes: Statistics and trends (Phase 7)
- websocket: Real-time sync status via WebSocket (Phase 7)

All routes are mounted on the main FastAPI app at:
    http://127.0.0.1:8000

API documentation is auto-generated at:
    http://127.0.0.1:8000/docs (Swagger UI)
    http://127.0.0.1:8000/redoc (ReDoc)

Usage:
------
    from jobtracker.api import auth_router, sync_router, emails_router, classification_router

    app.include_router(auth_router)
    app.include_router(sync_router)
    app.include_router(emails_router)
    app.include_router(classification_router)
"""

from jobtracker.api.applications import router as applications_router
from jobtracker.api.analytics import router as analytics_router
from jobtracker.api.auth import router as auth_router
from jobtracker.api.classification import router as classification_router
from jobtracker.api.emails import router as emails_router
from jobtracker.api.sync import router as sync_router
from jobtracker.api.websocket import router as websocket_router

__all__ = [
    "applications_router",
    "analytics_router",
    "auth_router",
    "sync_router",
    "emails_router",
    "classification_router",
    "websocket_router",
]
