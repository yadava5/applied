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


def test_cloud_classifier_is_rules_only_and_skips_heavy_ml_imports():
    """Issue #17 (C6) — rules-only cloud classifier + import hygiene.

    Two invariants are validated in a single subprocess so the test
    stays at 1 new case (155 expected total) and so both assertions
    run against a pristine ``sys.modules``:

    1. Importing the classifier and calling ``classify()`` under
       ``JOBTRACKER_DEPLOYMENT=cloud`` must not drag ``torch``,
       ``sentence_transformers``, ``setfit``, or ``transformers`` into
       ``sys.modules``. Together those wheels exceed Vercel's 250 MB
       unzipped function budget, and even on Pro their cold-start cost
       blows the 60 s wall clock. A subprocess provides a clean
       ``sys.modules`` so prior desktop tests in the same pytest session
       cannot pollute the assertion.
    2. The cloud classifier must return ``{category, confidence,
       method: "rules"}`` for rules hits and
       ``{other, 0.0, rules}`` for rules misses — *never* escalate to
       embeddings or SetFit.
    """

    import json
    import subprocess
    import sys

    script = (
        "import os, sys, json, asyncio\n"
        "os.environ['JOBTRACKER_DEPLOYMENT'] = 'cloud'\n"
        "from jobtracker.classifier import get_classifier\n"
        "classifier = get_classifier()\n"
        "assert classifier._cloud_rules_only is True, 'cloud flag not wired'\n"
        "assert classifier._lite_mode is True, 'cloud must imply lite_mode'\n"
        "hit = asyncio.run(classifier.classify(\n"
        "    'Re: Your application',\n"
        "    'Thank you for applying to our engineering role.',\n"
        "    'noreply@greenhouse.io',\n"
        "))\n"
        "miss = asyncio.run(classifier.classify('Hello', 'Just saying hi', None))\n"
        "heavy = [m for m in ('torch', 'sentence_transformers', 'setfit', 'transformers') if m in sys.modules]\n"
        "submods = [m for m in (\n"
        "    'jobtracker.classifier.embeddings',\n"
        "    'jobtracker.classifier.setfit_model',\n"
        ") if m in sys.modules]\n"
        "print(json.dumps({\n"
        "    'heavy': heavy,\n"
        "    'submods': submods,\n"
        "    'hit': {'category': hit.category.value, 'method': hit.method, 'confidence': hit.confidence},\n"
        "    'miss': {'category': miss.category.value, 'method': miss.method, 'confidence': miss.confidence},\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["heavy"] == [], (
        "cloud classifier pulled heavy ML deps into sys.modules: "
        f"{payload['heavy']}. hybrid.py must keep torch / sentence-transformers "
        "/ setfit behind in-method lazy imports."
    )
    assert payload["submods"] == [], (
        "cloud classifier imported the embeddings or setfit_model submodule: "
        f"{payload['submods']}. The cloud short-circuit in hybrid.classify() "
        "must return before ``self._embeddings`` or ``self._setfit`` is read."
    )

    # Rules hit: keep rules' category + confidence, tag method="rules".
    assert payload["hit"]["method"] == "rules"
    assert payload["hit"]["category"] != "other"
    assert payload["hit"]["confidence"] > 0.0

    # Rules miss: collapse to ``{other, 0.0, rules}`` — no further layers.
    assert payload["miss"] == {
        "category": "other",
        "method": "rules",
        "confidence": 0.0,
    }
