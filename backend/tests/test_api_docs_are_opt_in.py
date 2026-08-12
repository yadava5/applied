"""The cloud API must not publish its interactive docs by accident.

WHAT SHIPPED, AND WHAT THESE TESTS PIN

``jobtracker.main_cloud`` built its ``FastAPI`` with ``docs_url="/docs"``,
``redoc_url="/redoc"`` and ``openapi_url="/openapi.json"`` unconditionally, so
the production deployment served its complete interactive API surface to
anybody who asked. Measured against the live service on 2026-08-12::

    $ curl -s https://jobtracker-api-seven.vercel.app/
    {"name":"Applied", ... ,"docs":"/docs", ...}

THE FIX THAT WOULD NOT HAVE WORKED

Gating on ``settings.environment`` -- ``if settings.environment !=
"production"`` -- looks like the answer and is worthless here. Nothing sets
``JOBTRACKER_ENVIRONMENT`` on Vercel, so the deployed API reports
``"development"``, the field's default. That condition is *false* in
production; the docs would still have been served, and the repository would
have gained another check that cannot fail. The same trap swallows
``environment == "development"`` as an allow-condition: production satisfies it.

So the property under test is not "docs are off in production" (which depends
on configuration that is not there). It is stronger and does not depend on any
configuration at all:

    A DEPLOYMENT THAT CONFIGURES NOTHING SERVES NO DOCS.

WHY THE FIRST TEST IS A SUBPROCESS

Two reasons, one of them a hazard. ``tests/conftest.py`` sets
``JOBTRACKER_ENVIRONMENT=test`` for the whole session, and *that* is what
routes ``Settings.database_url`` to in-memory SQLite (``config.py``). Deleting
it in-process and reloading the config module would silently recompute the URL
to the real on-disk database under ``~/Library/Application Support``. Nothing
in these routes touches the DB today, but it is one import away.

Second, a subprocess with every ``JOBTRACKER_*`` variable stripped is the only
way to exercise the real env -> Settings -> FastAPI chain in the shape
production actually runs in. Reaching in and patching the settings object would
prove the gate reads a boolean, not that the boolean is False when a serverless
function boots with an empty environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _run_in_clean_env(script: str) -> dict:
    """Execute ``script`` with every JOBTRACKER_* variable removed.

    Returns the JSON object the script prints on its last stdout line. The
    child's ``cwd`` is the backend package root (this file's grandparent) so
    ``jobtracker`` imports the tree under test; ``PYTHONPATH`` carries it too
    in case the child is started from somewhere else.
    """

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    env = {k: v for k, v in os.environ.items() if not k.startswith("JOBTRACKER_")}
    env["PYTHONPATH"] = backend_dir
    # Desktop keyring is not on the cloud import path, but a stray macOS
    # Keychain prompt in CI would hang the child; the null backend is what
    # backend-ci.yml uses for the same reason.
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=backend_dir,
        env=env,
    )
    assert result.returncode == 0, (
        f"probe subprocess failed ({result.returncode}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


_PROBE = """
import asyncio, json, os, sys

# Deployment mode is what api/index.py forces on Vercel; it is not
# "environment configuration" in the sense under test and says nothing
# about docs.
os.environ["JOBTRACKER_DEPLOYMENT"] = "cloud"
{extra_env}

from jobtracker.config import settings
from jobtracker.main_cloud import app
from httpx import ASGITransport, AsyncClient

async def probe():
    codes = {{}}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://cloud-probe") as client:
        for path in {paths!r}:
            codes[path] = (await client.get(path)).status_code
        root = (await client.get("/")).json()
        health = (await client.get("/health")).json()
    # getattr with a sentinel, deliberately: if the gate is ever deleted these
    # settings vanish, and a probe that raised AttributeError would turn every
    # test below into a setup error whose message is about a missing attribute
    # rather than about docs being served. A test must fail on the property it
    # names.
    print(json.dumps({{
        "codes": codes,
        "root": root,
        "health": health,
        "enable_docs": getattr(settings, "enable_docs", "<absent>"),
        "environment_is_configured": getattr(
            settings, "environment_is_configured", "<absent>"
        ),
        "jobtracker_env_vars": sorted(
            k for k in os.environ if k.startswith("JOBTRACKER_")
        ),
    }}))

asyncio.run(probe())
"""


@pytest.fixture(scope="module")
def unconfigured_probe() -> dict:
    """Boot the cloud app with an empty JOBTRACKER_* environment."""

    return _run_in_clean_env(
        _PROBE.format(paths=DOC_PATHS, extra_env="")
    )


def test_unconfigured_deployment_serves_no_docs(unconfigured_probe: dict) -> None:
    """/docs, /redoc and /openapi.json are 404 when nothing is configured.

    This is the regression that was live in production. It fails if the gate is
    removed, and it also fails if the gate is rewritten in terms of
    ``environment`` -- because in this probe, as on Vercel, ``environment`` is
    the unset default.
    """

    # Guard the guard: if the child inherited configuration, the 404s below
    # would prove nothing about a bare deployment. JOBTRACKER_DEPLOYMENT is the
    # one exception -- api/index.py sets it unconditionally on Vercel and it
    # carries no information about docs.
    assert unconfigured_probe["jobtracker_env_vars"] == ["JOBTRACKER_DEPLOYMENT"], (
        "the probe subprocess was not actually unconfigured: "
        f"{unconfigured_probe['jobtracker_env_vars']}"
    )

    assert unconfigured_probe["codes"] == dict.fromkeys(DOC_PATHS, 404), (
        "the cloud API published interactive docs on a deployment that "
        f"configured nothing: {unconfigured_probe['codes']}. Docs must be "
        "opt-in via JOBTRACKER_ENABLE_DOCS; a gate on `environment` does not "
        "work because production's environment IS the default."
    )
    # Supporting detail, asserted after the property so a regression reports
    # the 200s rather than a bookkeeping mismatch.
    assert unconfigured_probe["enable_docs"] is False
    assert unconfigured_probe["environment_is_configured"] is False


def test_unconfigured_root_does_not_advertise_docs(unconfigured_probe: dict) -> None:
    """The root route must not hand out a link to a page it does not serve."""

    root = unconfigured_probe["root"]
    assert "docs" not in root, (
        f"GET / advertised docs at {root.get('docs')!r} while /docs returns "
        f"{unconfigured_probe['codes']['/docs']}."
    )
    # The rest of the root contract is unchanged.
    assert root["deployment"] == "cloud"
    assert root["health"] == "/health"


def test_unconfigured_health_does_not_claim_an_environment(
    unconfigured_probe: dict,
) -> None:
    """/health reports null, not "development", when nobody configured one.

    The deployed API answered ``"environment":"development"`` for months. That
    was not a report; it was the default leaking out through a field typed as
    if it were a measurement.
    """

    health = unconfigured_probe["health"]
    assert health["status"] == "ok"
    assert health["environment"] is None, (
        f"/health asserted environment={health['environment']!r} on a "
        "deployment that never configured one."
    )


@pytest.fixture(scope="module")
def docs_enabled_probe() -> dict:
    """Boot the cloud app with the docs opt-in explicitly turned on."""

    return _run_in_clean_env(
        _PROBE.format(
            paths=DOC_PATHS,
            extra_env=(
                'os.environ["JOBTRACKER_ENABLE_DOCS"] = "true"\n'
                'os.environ["JOBTRACKER_ENVIRONMENT"] = "development"\n'
            ),
        )
    )


def test_opt_in_serves_docs_redoc_and_openapi(docs_enabled_probe: dict) -> None:
    """JOBTRACKER_ENABLE_DOCS=true brings all three endpoints back.

    Without this the "fix" could be a hard-coded ``None`` and every other test
    here would still pass, leaving no way to read the API locally.
    """

    assert docs_enabled_probe["codes"] == dict.fromkeys(DOC_PATHS, 200), (
        "JOBTRACKER_ENABLE_DOCS=true did not restore the interactive docs: "
        f"{docs_enabled_probe['codes']}"
    )
    assert docs_enabled_probe["enable_docs"] is True


def test_opt_in_root_advertises_the_docs_it_serves(docs_enabled_probe: dict) -> None:
    """When docs are mounted the root advertises them, and at the served path."""

    root = docs_enabled_probe["root"]
    assert root["docs"] == "/docs"
    assert docs_enabled_probe["codes"][root["docs"]] == 200


def test_configured_health_reports_the_configured_environment(
    docs_enabled_probe: dict,
) -> None:
    """An environment that WAS configured is reported, not suppressed.

    The honesty fix must not degrade into "never say anything".
    """

    assert docs_enabled_probe["health"]["environment"] == "development"
    assert docs_enabled_probe["environment_is_configured"] is True


def test_openapi_document_is_still_buildable_without_the_route() -> None:
    """``app.openapi()`` works even with the HTTP route switched off.

    ``scripts/generate_api_schema.sh`` imports the app and calls
    ``app.openapi()`` to regenerate ``apps/web/lib/api/schema.d.ts``; the
    e2e workflow fails the build if the committed bindings drift. Passing
    ``openapi_url=None`` must remove the *route*, not the document -- otherwise
    disabling docs quietly breaks the web client's typed contract.
    """

    probe = _run_in_clean_env(
        'import json, os\n'
        'os.environ["JOBTRACKER_DEPLOYMENT"] = "cloud"\n'
        'from jobtracker.main_cloud import app\n'
        'doc = app.openapi()\n'
        'print(json.dumps({\n'
        '    "openapi_url": app.openapi_url,\n'
        '    "paths": len(doc["paths"]),\n'
        '    "has_health": "/health" in doc["paths"],\n'
        '}))\n'
    )

    assert probe["openapi_url"] is None, "the /openapi.json route should be off"
    assert probe["has_health"] is True
    assert probe["paths"] > 1, probe


# -----------------------------------------------------------------------------
# WHY THERE IS NO IN-PROCESS `importlib.reload` VARIANT HERE
#
# The obvious way to add an in-process case is the fixture idiom in
# test_main_cloud.py: monkeypatch the env, ``importlib.reload`` jobtracker.config
# and jobtracker.main_cloud, yield the app, reload again on teardown. It was
# written that way first, and it turned 14 unrelated tests red -- every test in
# test_auth_supabase_jwt.py and test_application_delete_children.py. Reloading
# jobtracker.config rebinds the module-level ``settings`` singleton, and every
# module that had already done ``from jobtracker.config import settings`` keeps
# the old object while anything importing afterwards gets the new one; reloading
# main_cloud then rebuilds the app and its routers around the second copy.
#
# test_main_cloud.py gets away with it only because "main_cloud" sorts after
# almost everything else, so its wreckage lands at the end of the session. This
# file sorts near the top. Measured:
#
#   pytest tests/test_auth_supabase_jwt.py tests/test_application_delete_children.py
#       -> 23 passed
#   pytest tests/test_api_docs_are_opt_in.py <same two>
#       -> 14 failed, 17 passed
#   pytest tests/test_api_docs_are_opt_in.py <same two> -k "not survives_a_module_reload"
#       -> 30 passed
#
# The subprocess probes above cover the same property with a stronger guarantee
# and no shared state, so the reload variant bought nothing. Do not add one.
# -----------------------------------------------------------------------------
