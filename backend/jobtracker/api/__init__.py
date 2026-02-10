"""
API Module
==========

FastAPI route handlers for the JobTracker REST API.

Routers:
--------
- auth_routes: Gmail OAuth and iCloud credential management
- email_routes: Email sync and listing
- application_routes: Job application CRUD
- analytics_routes: Statistics and trends
- websocket: Real-time sync status via WebSocket

All routes are mounted on the main FastAPI app at:
    http://127.0.0.1:8000

API documentation is auto-generated at:
    http://127.0.0.1:8000/docs (Swagger UI)
    http://127.0.0.1:8000/redoc (ReDoc)

Usage:
------
    from jobtracker.api import auth_router, email_router

    app.include_router(auth_router, prefix="/auth")
    app.include_router(email_router, prefix="/emails")
"""

# Imports will be added as modules are implemented
__all__: list[str] = []
