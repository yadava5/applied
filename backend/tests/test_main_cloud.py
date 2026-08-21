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

from tests.test_cloud_routes_carry_auth import (
    INCLUDED_ROUTER_WITNESS,
    _walk_routes,
)


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
    assert payload["health"] == "/health"
    # This fixture does not set JOBTRACKER_ENABLE_DOCS, so the docs are off and
    # the root must not advertise them. It used to assert ``payload["docs"] ==
    # "/docs"``, which was true of the deployment that published its full
    # interactive API surface to the internet. The docs contract, both halves
    # of it, now lives in tests/test_api_docs_are_opt_in.py.
    assert "docs" not in payload


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
    """WHY THE WALK AND NOT ``cloud_app.routes`` (#405).

    This assertion was written as a flat scan and could not have failed. On
    FastAPI 0.141 ``include_router()`` leaves an opaque ``_IncludedRouter``
    proxy in ``app.routes`` with ``path`` None, so a flat scan sees 5 paths out
    of 29 and none of them come from a router. Adding the very route this test
    forbids, through the mechanism all 24 real routes use, left it green.

    The witness below is the fix: a path that only exists behind
    ``include_router`` must be visible, or the "not in" assertion is being made
    against a set that could not contain it either way.
    """

    paths = {getattr(route, "path", None) for route in _walk_routes(cloud_app)}

    assert INCLUDED_ROUTER_WITNESS in paths, (
        f"the route scan cannot see {INCLUDED_ROUTER_WITNESS}, which is served "
        "through include_router. Until it can, 'X is absent' says nothing: 24 "
        "of the app's 29 routes are invisible to it."
    )
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


# =============================================================================
# /health/schema — does the database agree with the code that is running?
# =============================================================================
#
# Nothing runs ``alembic upgrade head`` on a Vercel deploy, so a merged revision
# and an unmigrated database is a reachable state. When it happens, every read
# that names the new column 500s with UndefinedColumn and the failure says
# nothing about schema. These tests pin the endpoint that names it instead.


@pytest.mark.asyncio
async def test_schema_endpoint_reports_ok_when_the_database_matches(
    cloud_app, monkeypatch: pytest.MonkeyPatch
):
    """The database is stamped at the revision the code expects."""

    from jobtracker.database import schema_version

    monkeypatch.setattr(
        schema_version, "read_applied_revision", _stub_revision("c0ffee123456")
    )
    monkeypatch.setattr(schema_version, "EXPECTED_REVISION", "c0ffee123456")

    payload = await _get_schema(cloud_app)

    assert payload == {
        "expected": "c0ffee123456",
        "applied": "c0ffee123456",
        "ok": True,
    }


@pytest.mark.asyncio
async def test_schema_endpoint_reports_the_gap_without_failing(
    cloud_app, monkeypatch: pytest.MonkeyPatch
):
    """A revision merged but not applied: ok is false, the status is still 200.

    The 200 is the point. A 503 would make the ordinary window between a merge
    and its migration read as an outage to every uptime monitor, and the whole
    value of this endpoint is that it can be watched without crying wolf.
    """

    from jobtracker.database import schema_version

    monkeypatch.setattr(
        schema_version, "read_applied_revision", _stub_revision("b9e42f7c10ad")
    )
    monkeypatch.setattr(schema_version, "EXPECTED_REVISION", "c2e7f4a91b83")

    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as client:
        response = await client.get("/health/schema")

    assert response.status_code == 200
    assert response.json() == {
        "expected": "c2e7f4a91b83",
        "applied": "b9e42f7c10ad",
        "ok": False,
    }


@pytest.mark.asyncio
async def test_schema_endpoint_survives_a_database_it_cannot_read(cloud_app):
    """No stubs: hit the real read path against a database with no version table.

    A paused Supabase project, a revoked grant and a never-migrated database all
    arrive here the same way — the query raises and the reader swallows it. The
    free tier pauses after seven days idle, so this is a routine state, not an
    exotic one, and the endpoint must answer rather than 500.

    Deliberately unstubbed. Patching the reader would prove only that the
    handler forwards whatever it is given, which is the half that was never in
    doubt; this exercises the ``except`` branch in ``read_applied_revision``
    through the running app.
    """

    payload = await _get_schema(cloud_app)

    assert payload["applied"] is None
    assert payload["ok"] is False
    assert payload["expected"]  # still reports what the code wants


def _stub_revision(value):
    async def _read(_session):
        return value

    return _read


async def _get_schema(cloud_app) -> dict:
    transport = ASGITransport(app=cloud_app)
    async with AsyncClient(transport=transport, base_url="http://cloud-test") as client:
        response = await client.get("/health/schema")
    assert response.status_code == 200
    return response.json()


def test_cloud_app_does_not_import_the_desktop_email_clients():
    """The desktop mail clients stay out of the deployed import graph.

    WHY THIS EXISTS, specifically. ``docs/google/RESTRICTED-SCOPE-JUSTIFICATION.md``
    is submitted to Google for restricted-scope OAuth review. It tells a reviewer
    that ``emails.body_text`` / ``body_html`` / ``raw_headers`` are legacy desktop
    columns which nothing in the hosted app can write, because the only code that
    writes them lives under ``jobtracker/email_clients/`` and that package is not
    reachable from ``main_cloud``.

    An earlier draft of that document claimed THIS FILE enforced it. It did not:
    ``grep -c email_clients`` on this module returned 0. The sibling test above
    guards ``keyring``, ``aiosqlite``, ``torch`` and ``setfit``, and says nothing
    about mail clients. The filing has been corrected to state the fact without
    claiming a gate; this test is the gate, so the stronger sentence can be true.

    THE POSITIVE CONTROL IS THE POINT. A scan for "did this package get imported"
    passes trivially if the package cannot be imported at all, if it was renamed,
    or if the prefix is misspelled — the exact "check that cannot fail" shape this
    repo keeps rediscovering. So the subprocess also imports the package on
    purpose afterwards and asserts the SAME expression then finds it. If the
    detector cannot see the package when it is genuinely loaded, this test fails
    rather than reporting a clean import graph it never actually measured.
    """

    import json
    import subprocess
    import sys

    script = (
        "import os, sys, json, importlib\n"
        "os.environ['JOBTRACKER_DEPLOYMENT'] = 'cloud'\n"
        "PKG = 'jobtracker.email_clients'\n"
        "def loaded():\n"
        "    return sorted(m for m in sys.modules if m == PKG or m.startswith(PKG + '.'))\n"
        "from jobtracker.main_cloud import app  # noqa: F401\n"
        "leaked = loaded()\n"
        "control_error = None\n"
        "try:\n"
        "    importlib.import_module(PKG)\n"
        "except Exception as exc:\n"
        "    control_error = f'{type(exc).__name__}: {exc}'\n"
        "print(json.dumps({\n"
        "    'leaked': leaked,\n"
        "    'after_explicit_import': loaded(),\n"
        "    'control_error': control_error,\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])

    assert data["leaked"] == [], (
        "main_cloud reached the desktop mail clients: "
        f"{data['leaked']}. The Google restricted-scope filing tells a reviewer "
        "that no hosted code path can write emails.body_text / body_html / "
        "raw_headers, and that is only true while this package stays out of the "
        "deployed import graph."
    )

    # The control. Without it, every assertion above is satisfied by a package
    # that simply cannot be imported, and this test would go green over nothing.
    assert data["control_error"] is None, (
        "jobtracker.email_clients could not be imported at all "
        f"({data['control_error']}), so the check above proved nothing. Fix the "
        "import or this gate is decorative."
    )
    assert data["after_explicit_import"], (
        "importing jobtracker.email_clients did not make it visible to the very "
        "expression used to detect a leak, so that expression cannot detect one. "
        "The package was probably renamed; update PKG."
    )
