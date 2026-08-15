"""Everything Vercel serves is defined in the cloud namespace (issue #73).

WHAT THIS FILE USED TO BE
-------------------------
``test_desktop_routers_are_not_mounted.py``. The desktop routers under
``jobtracker/api/`` and the services under ``jobtracker/services/`` had **no
user scoping at all**: every row read was of the shape
``select(Application).where(Application.id == application_id)``, with zero
occurrences of the string ``user_id`` in ``jobtracker/api/applications.py``
against 161 in its cloud twin. The ``applications`` table is multi-tenant, so
mounting any of those handlers on the cloud app would have turned each into a
cross-tenant read of any row whose id a caller could enumerate. Nothing in that
package was defensive; the separation was a property of the deployment, and this
file existed to make the day someone mounted them a red build rather than an
incident.

THOSE ROUTERS NO LONGER EXIST. They were deleted, along with
``jobtracker/main.py`` and ``apps/macos`` (de-scoped 2026-08-12), because the
surface they served had no consumer. That is a strictly stronger guarantee than
"not mounted" -- but it is a DIFFERENT guarantee, so the assertions changed
shape rather than being deleted.

The old file's own instruction, "if they moved, update ``_DESKTOP_PACKAGE_DIRS``
-- do not delete this assertion", was written against the routers being MOVED.
Deleted is not moved, and the replacement below is not weaker: the mount check
is now an ALLOWLIST rather than a denylist, so it covers a namespace nobody has
thought of yet, including one added tomorrow.

WHAT IS STILL BEING GUARDED
---------------------------
Three mechanisms, all of which survive the deletion untouched:

1. Vercel serves ``api/index.py`` (``vercel.json`` -> ``functions."api/index.py"``).
2. ``api/index.py`` puts ``backend/`` on ``sys.path`` and sets
   ``os.environ["JOBTRACKER_DEPLOYMENT"] = "cloud"`` **before** importing the
   app, deliberately overriding any stray ``desktop`` value already in the env.
   That variable still gates SQLite-vs-Postgres and Keychain-vs-cloud
   credentials, so it is load-bearing whether or not a desktop app exists.
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
Unchanged, and still the right call. A route's path says nothing about who
wrote its handler: ``app.mount("/desktop", other_app)`` puts no routes in
``app.routes`` at all, and on FastAPI 0.141 ``app.include_router()`` hides its
routes the same way (see the long note above ``_PROBE``). What distinguishes a
handler is where it is *defined*, so every route in the built app is resolved to
``route.endpoint.__module__`` and checked against an allowlist of cloud
namespaces. No amount of prefixing changes that answer.
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

# The namespaces a deployed handler is ALLOWED to come from. An allowlist, not a
# denylist, and that is the whole change of shape: the old denylist named
# ``jobtracker.api`` and ``jobtracker.services`` by hand, so a router added in a
# third package would have sailed past it. This form fails on anything it has
# not been told about, which is the correct default for a multi-tenant app whose
# scoping lives in the handler rather than the framework.
_ALLOWED_ROUTE_NAMESPACES = (
    "jobtracker.cloud",
    "jobtracker.main_cloud",
    # FastAPI's own machinery: /openapi.json, /docs, /redoc when enabled.
    "fastapi",
    "starlette",
)

# Packages that must NOT come back. Deleting one is only permanent if something
# notices it returning; without this, ``jobtracker/api/`` could be restored by a
# stray merge or a revert and the allowlist above would only catch it once a
# route were actually mounted, which is one step too late.
_DELETED_DESKTOP_PACKAGES = (
    _BACKEND / "jobtracker" / "api",
    _BACKEND / "jobtracker" / "services",
)

# ...and the single module, checked as a file.
_DELETED_DESKTOP_MODULES = (_BACKEND / "jobtracker" / "main.py",)


def _resurrected() -> list[Path]:
    """Deleted desktop source that is back on disk.

    Deliberately keyed on ``*.py`` files rather than on the directory existing.
    ``git rm -r`` leaves the directory behind whenever anything untracked was
    inside it (a ``__pycache__``, typically), and switching branches does the
    same, so a check on ``Path.is_dir()`` goes red on a tree with nothing wrong
    with it. That is how an assertion gets deleted rather than fixed.

    Not weaker: a resurrected package has modules in it. An empty directory
    serves no routes and imports nothing.
    """

    found = [path for path in _DELETED_DESKTOP_MODULES if path.is_file()]
    for package in _DELETED_DESKTOP_PACKAGES:
        found.extend(sorted(package.rglob("*.py")))
    return found

# Positive control for the check above. If the repo layout moves under this file
# -- a rename of ``backend/``, say -- every "does not exist" assertion would pass
# vacuously while pointing at nothing. These must exist for that check to mean
# anything, and this repo's recurring defect is checks that cannot fail.
_MUST_STILL_EXIST = (
    _BACKEND / "jobtracker" / "cloud" / "applications.py",
    _BACKEND / "jobtracker" / "main_cloud.py",
    _VERCEL_ENTRYPOINT,
)


# The script runs in a subprocess for two reasons. ``api/index.py`` mutates
# ``os.environ`` and ``sys.path`` at import time and would poison the settings
# ``lru_cache`` for the rest of the pytest session; and a fresh ``sys.modules``
# is the only way the import-provenance answer is trustworthy.
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
# That matters a great deal for a guard: a router included with
# ``app.include_router(...)`` arrives as exactly such a wrapper, and a walk that
# cannot see through it would report a clean route table forever. The positive
# control below (``..._still_serves_its_own_routes``) is what caught this, which
# is the reason it exists.
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
                       or m == "jobtracker.services" or m.startswith("jobtracker.services.")
                       or m == "jobtracker.main"),
}))
"""


@pytest.fixture(scope="module")
def deployed_app_probe() -> dict:
    """Build the app the way Vercel does and report its whole route table.

    ``JOBTRACKER_DEPLOYMENT=desktop`` is set in the child's environment on
    purpose. ``api/index.py`` is supposed to overwrite it; if that line is ever
    removed, this fixture's app is built under a desktop settings object and the
    assertions below say so. Inheriting the parent's value would make that
    deletion invisible.
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


def test_the_unscoped_desktop_surface_is_gone_and_stays_gone():
    """The routers with no ``user_id`` predicate must not exist at all.

    The strongest form of issue #73's containment, and the one that replaced the
    old ``_MUST_BE_WATCHED`` census. Deleting a package only stays deleted if
    something notices it coming back -- a revert, a bad merge, or somebody
    reviving the desktop app without reviving its scoping.

    If this goes red because the desktop app is being brought back deliberately:
    do NOT delete the assertion. Add ``user_id`` filters and a ``require_user()``
    dependency to every handler first, then decide what this file should assert
    about the new surface.
    """

    # Positive control first: without it, a repo-layout change would make every
    # assertion below true about a directory that is not there.
    missing_anchors = [p for p in _MUST_STILL_EXIST if not p.exists()]
    assert not missing_anchors, (
        "The paths this guard navigates from are not where it looks: "
        f"{[str(p) for p in missing_anchors]}. The 'does not exist' assertions "
        "below would pass vacuously. Fix the paths -- the surface they describe "
        "has moved, it has not been proven absent."
    )

    resurrected = _resurrected()
    assert not resurrected, (
        "The unmounted, unscoped desktop surface is back on disk:\n"
        + "\n".join(f"  {p.relative_to(_REPO_ROOT)}" for p in resurrected)
        + "\n\nEvery handler in jobtracker/api/ read rows as "
        "`select(Application).where(Application.id == id)` with no user_id "
        "predicate, against a multi-tenant table. It was deleted rather than "
        "fixed because `apps/macos` was de-scoped and it had no consumer. If it "
        "is genuinely coming back, it needs scoping BEFORE it needs a home."
    )


def test_vercel_entrypoint_forces_cloud_mode_over_a_desktop_env():
    """The entrypoint overrides the environment.

    Deliberately separate from the route-table tests. If this one is the only
    red, the forcing line in ``api/index.py`` went missing; if the route tests
    are also red, something else is being served. Different faults, different fix.

    Still load-bearing with no desktop app in the tree: ``settings.deployment``
    is what selects Postgres over SQLite and the encrypted-row credential store
    over the macOS Keychain. A deployment carrying a stray ``desktop`` value and
    no forcing line would fail at runtime, in production, on the first request.
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
        f"importing the app (env is {probe['env_deployment']!r} after import)."
    )
    # This is the assertion that discriminates: ``settings.deployment`` is read
    # from the environment, so it says "cloud" only if step 2 actually ran.
    assert probe["deployment"] == "cloud"
    # The title is NOT a mode check and is not presented as one -- main_cloud
    # hardcodes ``f"{settings.app_name} (cloud)"`` whatever the deployment says.
    # It is here to catch the app object being swapped for a different one
    # entirely, which the identity assertion below then localises.
    assert "(cloud)" in probe["title"], (
        f"The app served by api/index.py is titled {probe['title']!r}; the cloud "
        "app titles itself '<name> (cloud)'."
    )
    assert probe["is_main_cloud_app"], (
        "api/index.py's ``app`` is not ``jobtracker.main_cloud.app``. Whatever "
        "it now serves, the route-table guarantees below were established "
        "against main_cloud and no longer apply to what is deployed."
    )


def test_every_deployed_route_is_defined_in_the_cloud_namespace(
    deployed_app_probe: dict,
):
    """The mount guard, as an ALLOWLIST.

    The predecessor named ``jobtracker.api`` and ``jobtracker.services`` and
    failed if a route came from either. That could only ever catch the two
    packages someone remembered to list -- and both are now deleted, which would
    have left it green forever against an empty set.

    This form inverts it: a deployed handler must be defined in a namespace on
    :data:`_ALLOWED_ROUTE_NAMESPACES`, every one of which carries
    ``require_user()`` and filters on ``user_id``. A router mounted from any
    other package -- restored, vendored, or newly written -- is red here on the
    commit that mounts it, without anybody having to predict its name.

    Keyed on the defining module, not the path, for the reason in the module
    docstring.
    """

    offenders = [
        route
        for route in deployed_app_probe["routes"]
        if route["module"] is not None
        and not route["module"].startswith(_ALLOWED_ROUTE_NAMESPACES)
    ]

    assert not offenders, (
        "The deployed cloud app is serving handlers defined outside the cloud "
        "namespace. Nothing outside jobtracker.cloud is known to scope its "
        "queries by user_id, and the applications table is multi-tenant:\n"
        + "\n".join(
            f"  {'/'.join(r['methods']) or r['kind']:<22} {r['path']:<40} "
            f"<- {r['module']}.{r['qualname']}"
            for r in offenders
        )
        + "\n\nThis is issue #73's dormant risk going live. Do not silence it by "
        "widening _ALLOWED_ROUTE_NAMESPACES. Give the handler a require_user() "
        "dependency and a user_id predicate, put it under jobtracker/cloud/ "
        "(see jobtracker/cloud/applications.py), and mount that instead."
    )


def test_the_deployed_app_still_serves_its_own_routes(deployed_app_probe: dict):
    """Positive control: the probe really did enumerate a route table.

    An entrypoint that built an empty app, or a walk that returned nothing,
    would satisfy the assertion above for the wrong reason -- and now more
    easily than before, because an allowlist is satisfied by zero routes. Pin
    the routes the cloud app is supposed to have, by provenance, so "everything
    is allowed" is a statement about a populated table.
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
    ceiling. Kept after the deletion because the import is what a resurrection
    would produce FIRST, before any route is registered.
    """

    assert deployed_app_probe["imported"] == [], (
        "Building the deployed app pulled desktop modules into sys.modules: "
        f"{deployed_app_probe['imported']}. Those packages were deleted; if they "
        "are importable again, read "
        "test_the_unscoped_desktop_surface_is_gone_and_stays_gone first."
    )
