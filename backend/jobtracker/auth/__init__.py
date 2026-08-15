"""Cloud authentication helpers.

This package is the cloud twin of the desktop's trust-local model. It
provides:

- ``supabase_jwt.current_user`` — FastAPI dependency that decodes a
  Supabase-issued HS256 JWT from the ``Authorization: Bearer <token>``
  header and returns the ``sub`` claim as a :class:`uuid.UUID`.
- ``supabase_jwt.require_user`` — convenience re-export of
  ``Depends(current_user)`` for cloud-only routers.

The cloud app builder (``jobtracker.main_cloud``) wires ``require_user``
onto every cloud-mounted router. There is no longer a second app builder:
``jobtracker.main`` and the unscoped desktop routers it mounted were
deleted with ``apps/macos`` (issue #73).
"""

from jobtracker.auth.supabase_jwt import (
    AuthError,
    current_user,
    require_user,
)

__all__ = ["AuthError", "current_user", "require_user"]
