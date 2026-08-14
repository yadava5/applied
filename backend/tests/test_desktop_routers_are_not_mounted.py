"""The deployed cloud app must never serve a desktop router (issue #73).

WHAT IS BEING GUARDED
---------------------
The desktop routers under ``jobtracker/api/`` and the services under
``jobtracker/services/`` have **no user scoping at all**. Every row read is of
the shape ``select(Application).where(Application.id == application_id)`` --
``jobtracker/api/applications.py`` lines 329, 410, 499, 556, 580 and 654 -- with
no ``user_id`` predicate anywhere in the module. Measured: zero occurrences of
the string ``user_id`` in ``jobtracker/api/applications.py``, against 161 in its
cloud twin ``jobtracker/cloud/applications.py``. The ``applications`` table is
multi-tenant (``models.py:293`` gives it a ``user_id`` FK to ``auth.users``), so
mounting any of these handlers on the cloud app turns every one of them into a
cross-tenant read of any row whose id a caller can enumerate.

That is not hypothetical here: this estate has already shipped a real IDOR.

THE MECHANISM THIS PINS
-----------------------
Nothing in ``jobtracker/api/`` is defensive. The separation is a property of the
deployment, and it has exactly three parts:

1. Vercel serves ``api/index.py`` (``vercel.json`` -> ``functions."api/index.py"``).
2. ``api/index.py`` puts ``backend/`` on ``sys.path`` and sets
   ``os.environ["JOBTRACKER_DEPLOYMENT"] = "cloud"`` **before** importing the
   app, deliberately overriding any stray ``desktop`` value already in the env.
3. It imports ``jobtracker.main_cloud``, whose ``include_router`` calls name
   only ``jobtracker.cloud.{applications,gmail_oauth,account}`` -- each of which
   carries ``require_user()`` and filters on ``user_id``.

So the tests below build the app *through* ``api/index.py`` -- the object Vercel
actually serves -- rather than importing ``main_cloud`` directly, and they run
the subprocess with ``JOBTRACKER_DEPLOYMENT=desktop`` explicitly set. Inheriting
``cloud`` from the parent process would let step 2 be deleted with the test
still green, which pins a proxy instead of the mechanism.

WHY PROVENANCE AND NOT PATHS
----------------------------
A path-based assertion would be wrong, and measurably so. The cloud router
declares ``APIRouter(prefix="/applications")`` (``cloud/applications.py:243``)
and so does the desktop one (``api/applications.py:34``). Four path+method pairs
collide on clean ``main``::

    GET  /applications                    POST   /applications
    GET  /applications/{application_id}   DELETE /applications/{application_id}

Asserting on paths would therefore be red on a tree with nothing wrong with it.
What distinguishes the two is where the handler is *defined*, so every route in
the built app is resolved to ``route.endpoint.__module__`` and checked against
the desktop namespace. That is also robust to a mount arriving on a prefix
nobody predicted -- including ``app.mount("/desktop", other_app)``, which puts
no routes in ``app.routes`` at all, which is why the walk below recurses. On
FastAPI 0.141 ``app.include_router()`` hides its routes the same way; see the
long note above ``_PROBE``.

WHAT THIS TEST IS **NOT**
-------------------------
It is not a fix for the scoping. Adding ``user_id`` filters to the desktop
routers is deliberately not being done: ``apps/macos`` was de-scoped on
2026-08-12, so that is work for a surface with no consumer. This test is the
containment instead -- it makes the day someone mounts them a red build rather
than an incident.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# backend/tests/ -> backend/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "backend"
_VERCEL_ENTRYPOINT = _REPO_ROOT / "api" / "index.py"

# The desktop namespaces. Derived by globbing rather than hardcoded so a desktop
# router added tomorrow is covered without anyone remembering this file exists.
_DESKTOP_PACKAGE_DIRS = {
    "jobtracker.api": _BACKEND / "jobtracker" / "api",
    "jobtracker.services": _BACKEND / "jobtracker" / "services",
}

# Modules that must be in the watched set for the guard to mean anything. If one
# of these stops resolving -- the files were moved to ``jobtracker/desktop/``,
# say -- the guard's subject has moved out from under it and it would start
# passing vacuously. Failing loudly instead is the point: this repo's recurring
# defect is checks that cannot fail.
_MUST_BE_WATCHED = frozenset(
    {
        "jobtracker.api.applications",
        "jobtracker.api.analytics",
        "jobtracker.api.emails",
        "jobtracker.services.application_insights",
        "jobtracker.services.sync",
    }
)


def _watched_modules() -> frozenset[str]:
    """Every module in the desktop namespaces, by dotted name."""

    found: set[str] = set()
    for package, directory in _DESKTOP_PACKAGE_DIRS.items():
        for path in sorted(directory.glob("*.py")):
            if path.name == "__init__.py":
                found.add(package)
            else:
                found.add(f"{package}.{path.stem}")
    return frozenset(found)


# The script runs in a subprocess for two reasons. ``api/index.py`` mutates
# ``os.environ`` and ``sys.path`` at import time and would poison the settings
# ``lru_cache`` for the rest of the pytest session; and a fresh ``sys.modules``
# is the only way the import-provenance answer is trustworthy, since an earlier
# desktop test in the same session will already have imported these modules.
#
# WALKING THE ROUTE TABLE IS NOT ``for route in app.routes``
# ----------------------------------------------------------
# It was, once. FastAPI 0.141 (the version this resolved to; ``fastapi`` is
# pinned only as ``>=0.109.0``) no longer copies an included router's routes
# into the parent's list. ``app.routes`` on the deployed app is seven entries:
# four ``APIRoute`` objects declared in ``main_cloud`` itself, and three opaque
# ``_IncludedRouter`` wrappers -- ``path`` None, ``endpoint`` None, no
# ``routes`` attribute -- standing in for all 22 routes of the three cloud
# routers. A flat scan, or a scan that recurses only through ``.routes``, sees
# none of them.
#
# That matters a great deal for a guard: a desktop router included with
# ``app.include_router(...)`` would arrive as exactly such a wrapper, and a walk
# that cannot see through it would report a clean route table forever. The
# second positive control below (``..._still_serves_its_own_routes``) is what
# caught this, which is the reason it exists.
#
# So the walk follows every child-bearing attribute it knows -- ``.routes``
# (Mount, Host, APIRouter) and ``.original_router`` (``_IncludedRouter``) -- and
# ``test_every_route_container_is_transparent...`` fails on any object that has
# neither an endpoint nor children, so the *next* FastAPI release that invents a
# new container makes this test red instead of vacuous.
#
# Paths are diagnostic only. A route reached through ``original_router`` carries
# the router's own prefix but not a prefix passed to ``include_router``, so the
# printed path may be shorter than the served one. The assertion is on the
# defining module, which no amount of prefixing changes.
_PROBE = r"""
import importlib.util, json, os, sys

spec = importlib.util.spec_from_file_location("vercel_entrypoint", %(entrypoint)r)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = module.app


def children_of(route):
    found = []
    nested = getattr(route, "routes", None)
    if nested:
        found.extend(nested)
    # FastAPI >= 0.141: include_router() leaves a ``_IncludedRouter`` proxy in
    # app.routes and keeps the real APIRouter on ``original_router``.
    original = getattr(route, "original_router", None)
    if original is not None:
        found.extend(getattr(original, "routes", None) or [])
    return found


def walk(routes, seen=None):
    seen = set() if seen is None else seen
    for route in routes:
        if id(route) in seen:
            continue
        seen.add(id(route))
        endpoint = getattr(route, "endpoint", None)
        kids = children_of(route)
        yield {
            "path": getattr(route, "path", None),
            "name": getattr(route, "name", None),
            "methods": sorted(getattr(route, "methods", None) or []),
            "module": getattr(endpoint, "__module__", None),
            "qualname": getattr(endpoint, "__qualname__", None),
            "kind": type(route).__name__,
            "has_endpoint": endpoint is not None,
            "children": len(kids),
        }
        yield from walk(kids, seen)


import fastapi
from jobtracker.config import settings
import jobtracker.main_cloud as main_cloud

print(json.dumps({
    "routes": list(walk(app.routes)),
    "top_level_routes": len(app.routes),
    "fastapi_version": fastapi.__version__,
    "deployment": settings.deployment,
    "title": app.title,
    "env_deployment": os.environ.get("JOBTRACKER_DEPLOYMENT"),
    "is_main_cloud_app": app is main_cloud.app,
    "imported": sorted(m for m in sys.modules
                       if m == "jobtracker.api" or m.startswith("jobtracker.api.")
                       or m == "jobtracker.services" or m.startswith("jobtracker.services.")),
}))
"""


@pytest.fixture(scope="module")
def deployed_app_probe() -> dict:
    """Build the app the way Vercel does and report its whole route table.

    ``JOBTRACKER_DEPLOYMENT=desktop`` is set in the child's environment on
    purpose. ``api/index.py`` is supposed to overwrite it; if that line is ever
    removed, this fixture's app is the desktop one and the assertions below say
    so. Inheriting the parent's value would make that deletion invisible.
    """

    env = dict(os.environ)
    env["JOBTRACKER_DEPLOYMENT"] = "desktop"
    env.setdefault("JOBTRACKER_ENVIRONMENT", "test")
    env.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

    result = subprocess.run(
        [sys.executable, "-c", _PROBE % {"entrypoint": str(_VERCEL_ENTRYPOINT)}],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0, (
        "Could not build the deployed app from api/index.py -- the guard could "
        "not run, which is not the same as passing.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_guard_watches_the_modules_it_claims_to():
    """Positive control: the watched set is non-empty and names the real files.

    Without this, moving or renaming the desktop routers would leave every
    assertion below trivially true and the guard would go on reporting green
    while watching nothing.
    """

    watched = _watched_modules()

    assert watched, (
        f"No desktop modules found under {sorted(_DESKTOP_PACKAGE_DIRS)}. The "
        "guard is watching an empty set and cannot fail."
    )
    missing = _MUST_BE_WATCHED - watched
    assert not missing, (
        f"Expected desktop modules are no longer where the guard looks: {sorted(missing)}. "
        "If they moved, update _DESKTOP_PACKAGE_DIRS -- do not delete this "
        "assertion. The routers are still unscoped wherever they now live."
    )


def test_vercel_entrypoint_forces_cloud_mode_over_a_desktop_env():
    """Step 2 of the mechanism: the entrypoint overrides the environment.

    Deliberately separate from the route-table tests. If this one is the only
    red, the forcing line in ``api/index.py`` went missing; if the route tests
    are also red, a desktop router was mounted. Different faults, different fix.
    """

    env = dict(os.environ)
    env["JOBTRACKER_DEPLOYMENT"] = "desktop"
    env.setdefault("JOBTRACKER_ENVIRONMENT", "test")
    env.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

    result = subprocess.run(
        [sys.executable, "-c", _PROBE % {"entrypoint": str(_VERCEL_ENTRYPOINT)}],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    probe = json.loads(result.stdout.strip().splitlines()[-1])

    assert probe["env_deployment"] == "cloud", (
        "api/index.py no longer forces JOBTRACKER_DEPLOYMENT=cloud before "
        f"importing the app (env is {probe['env_deployment']!r} after import). "
        "A deployment carrying a stray 'desktop' value would then build the "
        "desktop app, SQLite and Keychain and unscoped routers included."
    )
    assert probe["deployment"] == "cloud"
    assert "(cloud)" in probe["title"], (
        f"The app served by api/index.py is titled {probe['title']!r}; the cloud "
        "app titles itself '<name> (cloud)'."
    )
    assert probe["is_main_cloud_app"], (
        "api/index.py's ``app`` is not ``jobtracker.main_cloud.app``. Whatever "
        "it now serves, the route-table guarantees below were established "
        "against main_cloud and no longer apply to what is deployed."
    )


def test_no_deployed_route_is_served_by_an_unscoped_desktop_handler(
    deployed_app_probe: dict,
):
    """The guard proper. Nothing in the deployed route table may come from
    ``jobtracker.api.*`` or ``jobtracker.services.*``.

    Keyed on the defining module, not the path: the cloud and desktop
    applications routers share the ``/applications`` prefix, so four
    path+method pairs collide on a perfectly healthy tree.
    """

    watched = _watched_modules()

    offenders = [
        route
        for route in deployed_app_probe["routes"]
        if route["module"] in watched
    ]

    assert not offenders, (
        "The deployed cloud app is serving handlers defined in the desktop "
        "routers, which have NO user scoping -- every one of these is a "
        "cross-tenant read or write:\n"
        + "\n".join(
            f"  {'/'.join(r['methods']) or r['kind']:<22} {r['path']:<40} "
            f"<- {r['module']}.{r['qualname']}"
            for r in offenders
        )
        + "\n\nThis is issue #73's dormant risk going live. Do not fix it by "
        "adding user_id filters to jobtracker/api/ -- that surface is de-scoped "
        "and untested. Add a scoped twin under jobtracker/cloud/ (see "
        "jobtracker/cloud/applications.py) and mount that instead."
    )


def test_the_deployed_app_still_serves_its_own_routes(deployed_app_probe: dict):
    """Second positive control: the probe really did enumerate a route table.

    An entrypoint that built an empty app, or a walk that returned nothing,
    would satisfy the assertion above for the wrong reason. Pin the routes the
    cloud app is supposed to have, by provenance, so "no desktop routes" is a
    statement about a populated table.
    """

    modules = {route["module"] for route in deployed_app_probe["routes"]}

    assert "jobtracker.cloud.applications" in modules, (
        "The deployed app has no routes from the cloud applications router. "
        f"Modules seen: {sorted(m for m in modules if m)}"
    )
    assert {"jobtracker.cloud.gmail_oauth", "jobtracker.cloud.account"} <= modules
    assert "/health" in {route["path"] for route in deployed_app_probe["routes"]}


def test_every_route_container_is_transparent_to_the_walk(deployed_app_probe: dict):
    """No object in the route tree may be opaque -- endpoint-less and childless.

    This is the assertion that keeps the guard honest across FastAPI upgrades.
    ``fastapi`` is pinned as ``>=0.109.0``, so the shape of ``app.routes`` is
    not fixed: 0.141 replaced the included routers' entries with
    ``_IncludedRouter`` proxies that expose neither ``endpoint`` nor ``routes``,
    and a walk written against the older shape silently stopped seeing 22 of the
    26 routes. If a future release invents another container, this test names it
    and the walk gets taught about it -- instead of the mount check quietly
    becoming a test of nothing.
    """

    opaque = [
        route
        for route in deployed_app_probe["routes"]
        if not route["has_endpoint"] and not route["children"]
    ]

    assert not opaque, (
        "The route walk hit objects it cannot see through, so it cannot prove "
        "anything about what is mounted behind them:\n"
        + "\n".join(f"  {r['kind']} path={r['path']!r} name={r['name']!r}" for r in opaque)
        + f"\n\nfastapi=={deployed_app_probe['fastapi_version']}. Teach "
        "``children_of()`` in this file how to reach that container's routes; "
        "do not delete this assertion."
    )


def test_the_desktop_modules_are_not_even_imported(deployed_app_probe: dict):
    """Belt and braces: the desktop namespace stays out of the cloud graph.

    Weaker than the route check on its own -- an import can be present and
    nothing mounted -- but it fails one step *earlier* than a mount does, and it
    keeps ``keyring``/``aiosqlite`` out of a serverless bundle that has a 250 MB
    ceiling. The route table is the contract; this is the smoke alarm.
    """

    assert deployed_app_probe["imported"] == [], (
        "Building the deployed app pulled desktop modules into sys.modules: "
        f"{deployed_app_probe['imported']}. If the route check above is green, "
        "nothing is mounted and this is only an import -- still wrong, because "
        "the cloud graph is meant to be free of jobtracker.api / "
        "jobtracker.services entirely, and an import is the step before a "
        "mount. If it is red too, read that one first: it is the leak."
    )
