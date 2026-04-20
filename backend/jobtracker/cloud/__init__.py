"""Cloud-only router package.

Modules under ``jobtracker.cloud`` contain FastAPI routers that assume
a cloud deployment (Supabase Postgres, JWT auth, no Keychain). They
are imported *only* by ``jobtracker.main_cloud``. Keeping them in their
own package means:

- ``jobtracker.api`` (desktop routers) never has to branch on
  deployment mode; its imports can keep pulling in ``keyring`` /
  ``keychain`` helpers.
- ``jobtracker.main_cloud``'s import graph stays thin (no desktop
  side-effect imports), which the subprocess-based test in
  ``test_main_cloud.py::test_cloud_app_does_not_import_keyring_or_aiosqlite``
  verifies per-deploy.

Downstream cloud issues (C11–C16) add more scoped routers here:
``emails.py``, ``interviews.py``, ``contacts.py``, etc.
"""
