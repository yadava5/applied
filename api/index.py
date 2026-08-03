"""
Vercel Python runtime entrypoint.

Vercel's ``@vercel/python`` runtime detects an ASGI callable at
``api/index.py`` and serves it directly. We force cloud mode at import
time so the cloud variant of the FastAPI app (``main_cloud``) is built
— NOT the desktop one in ``main.py``, which expects SQLite + Keychain
+ WebSockets.

Every incoming request to the Vercel deployment is rewritten by
``/vercel.json`` to ``api/index.py`` so FastAPI's internal router
handles the path resolution.

This file is intentionally tiny; all logic lives under
``backend/jobtracker/``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the backend package is importable when Vercel builds from repo
# root. Vercel's build step runs `pip install -r requirements.txt`
# against the root requirements.txt, which does NOT include the local
# `backend/` package — so we make the `backend/` path importable here.
_backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(_backend_path) not in sys.path:
    sys.path.insert(0, str(_backend_path))

# Force cloud deployment mode before importing the FastAPI app. This
# overrides any stray `JOBTRACKER_DEPLOYMENT=desktop` in the env so the
# cloud app is always built under the serverless entrypoint.
os.environ["JOBTRACKER_DEPLOYMENT"] = "cloud"

from jobtracker.main_cloud import app  # noqa: E402

__all__ = ["app"]
