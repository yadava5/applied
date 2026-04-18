"""Smoke tests for the cloud FastAPI app builder (issue #14, C1).

These tests only exercise the cloud shim and MUST NOT touch SQLite, the
classifier, or any credential store. Later issues add integration tests
for Postgres (C2), auth (C3), credentials (C4), and the cron endpoint
(C7).
"""

from __future__ import annotations

import importlib

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def cloud_settings(monkeypatch: pytest.MonkeyPatch):
    """Reload ``jobtracker.config`` with cloud deployment configured.

    The settings object is cached via ``lru_cache``; reload the module
    so ``deployment`` picks up the patched env var, then restore the
    desktop default on teardown to keep the remainder of the test
    session's settings singleton stable.
    """

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_CORS_ALLOWED_HOSTS", "jobtracker.app")

    import jobtracker.config as config_module

    importlib.reload(config_module)

    yield config_module.settings

    monkeypatch.undo()
    importlib.reload(config_module)


@pytest.fixture
def cloud_app(cloud_settings):
    """Import the cloud FastAPI app after cloud settings are in effect."""

    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)
    return main_cloud_module.app


@pytest.mark.asyncio
async def test_cloud_app_boots_and_health_returns_ok(cloud_app):
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["deployment"] == "cloud"
    assert payload["version"]  # non-empty


@pytest.mark.asyncio
async def test_cloud_app_root_returns_deployment_info(cloud_app):
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deployment"] == "cloud"
    assert payload["docs"] == "/docs"
    assert payload["health"] == "/health"


def test_cloud_app_does_not_import_keyring_or_aiosqlite(tmp_path):
    """Validate main_cloud's import graph stays free of desktop-only deps.

    Uses a subprocess to guarantee a fresh ``sys.modules`` — the in-process
    ``sys.modules`` will already contain ``keyring`` and ``aiosqlite`` from
    any earlier desktop test that imported ``jobtracker.main``.
    """

    import subprocess
    import sys

    script = (
        "import os, sys, json\n"
        "os.environ['JOBTRACKER_DEPLOYMENT'] = 'cloud'\n"
        "from jobtracker.main_cloud import app  # noqa: F401\n"
        "unwanted = [m for m in ('keyring', 'aiosqlite', 'torch', 'setfit') if m in sys.modules]\n"
        "print(json.dumps(unwanted))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    unwanted = __import__("json").loads(result.stdout.strip().splitlines()[-1])
    assert unwanted == [], (
        f"main_cloud pulled in desktop-only / heavy modules: {unwanted}. "
        "Credentials (C4), Postgres driver (C2), and classifier (C6) must "
        "stay out of the cloud import graph until those issues land."
    )


def test_cloud_app_does_not_register_websocket_route(cloud_app):
    paths = {getattr(route, "path", None) for route in cloud_app.routes}
    assert "/ws/sync-status" not in paths, (
        "Vercel Python runtime does not support WebSockets; /ws/sync-status "
        "is intentionally absent from the cloud app (C7 replaces it with polling)."
    )
