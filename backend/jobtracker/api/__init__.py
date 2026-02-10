"""
API Module
==========

FastAPI route handlers for the JobTracker REST API.

Routers:
--------
- auth_router: Gmail OAuth and iCloud credential management
- sync_router: Email synchronization
- emails_router: Email listing and details
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
    from jobtracker.api import auth_router, sync_router, emails_router

    app.include_router(auth_router)
    app.include_router(sync_router)
    app.include_router(emails_router)
"""

from jobtracker.api.auth import router as auth_router
from jobtracker.api.emails import router as emails_router
from jobtracker.api.sync import router as sync_router

__all__ = [
    "auth_router",
    "sync_router",
    "emails_router",
]
