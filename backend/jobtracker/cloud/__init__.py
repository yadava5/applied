"""Cloud-only router package.

Modules under ``jobtracker.cloud`` contain FastAPI routers that assume
a cloud deployment (Supabase Postgres, JWT auth, no Keychain). They
are imported *only* by ``jobtracker.main_cloud``, and they are now the
only routers in the tree: the unscoped desktop package that used to sit
beside them under ``jobtracker.api`` was deleted with ``apps/macos``
(issue #73).

Keeping them in their own package still matters. ``jobtracker.main_cloud``'s
import graph must stay thin — no ``keyring``, no ``aiosqlite`` — which the
subprocess-based test in
``test_main_cloud.py::test_cloud_app_does_not_import_keyring_or_aiosqlite``
verifies per-deploy, and which
``test_the_deployed_app_is_the_cloud_app.py`` holds as an allowlist over
every mounted handler's defining module.
"""
