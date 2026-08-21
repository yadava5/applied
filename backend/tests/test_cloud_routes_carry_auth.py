"""Every route the cloud app serves is authenticated, or is on a list that says why.

WHY THIS FILE EXISTS (#405). ``test_main_cloud.py`` already asserted something
about the route table, and it could not see 24 of the 29 routes.

FastAPI 0.141 does not copy an included router's routes into the parent's
list. ``app.include_router()`` leaves an opaque ``_IncludedRouter`` proxy in
``app.routes`` with ``path`` None, ``endpoint`` None and no ``routes``
attribute, and keeps the real ``APIRouter`` on ``original_router``. Every one
of Applied's 24 real endpoints arrives that way, so a flat
``for route in app.routes`` sees this::

    ['/health', '/health/schema', '/health/gmail-capacity', '/', '/auth/me',
     None, None, None, None]

Nine entries, five of them paths. The recursive walk below sees 29.

That was proven by injection rather than argued: appending an unauthenticated
``@router.get("/ws/sync-status")`` to ``cloud/cron.py`` left the existing guard
green and the whole suite green, while a route enumerator showed the new route
live and unauthenticated. A check that cannot see the thing it checks is worse
than no check, because its green is still counted.

THE LIVE POSTURE WAS NEVER BROKEN, and this file does not claim to have found a
hole. 29 routes, 23 authenticated, and the 6 public ones below are each public
on purpose. What was broken is that nothing would have noticed if that stopped
being true.

WHAT MAKES THIS ONE ABLE TO FAIL. Three assertions, and the first two exist
because "no route is unauthenticated" is trivially true of an empty set:

  1. The walk must reach a floor of routes AND must find a specific path that
     only arrives through ``include_router``. If FastAPI changes how it stores
     included routers again, this reds instead of quietly going blind.
  2. Every entry in PUBLIC must still exist. A stale allowlist is how an
     exemption outlives the reason for it, and a deleted-then-restored route
     would otherwise inherit its old exemption silently.
  3. Then, and only then: every route not in PUBLIC resolves ``current_user``
     somewhere in its dependency tree.

MUTATION-TESTED AT INTRODUCTION (2026-08-21), each break run and reverted:

  · an unauthenticated route added through ``include_router``  → 1 fail (3)
  · an authenticated route's ``current_user`` removed          → 1 fail (3)
  · a PUBLIC entry pointed at a path that does not exist       → 1 fail (2)
  · the walker reduced to a flat scan of ``app.routes``        → 2 fails (1),
    which is the control proving the other assertions are not passing on an
    empty set
"""

from __future__ import annotations

import importlib
from typing import Any, Iterator

import pytest

# ---------------------------------------------------------------------------
# The public surface, and why each entry is on it.
#
# A route is on this list only when serving it to an anonymous caller is the
# intended behaviour. Two of the six are not really anonymous and the
# distinction matters: they authenticate by a mechanism that is not a user
# session, so `current_user` is legitimately absent while the route is not
# actually open.
#
# KEYED ON (METHOD, PATH), NOT PATH. A path-keyed exemption exempts every verb
# on that path, including verbs that do not exist yet: adding `DELETE /health`
# tomorrow would inherit the liveness probe's permission without anybody
# writing it down. That is the same shape as the stale-entry failure the
# allowlist test below exists to catch, so it is closed the same way.
# `/cron/sync` is the one entry that genuinely serves two verbs, and it has to
# say so twice.
# ---------------------------------------------------------------------------
PUBLIC: dict[tuple[str, str], str] = {
    ("GET", "/"): "deployment banner: name, version, deployment mode. No user data.",
    ("GET", "/health"): "liveness probe. Vercel and uptime checks call it unauthenticated.",
    ("GET", "/health/schema"): "reports whether the expected tables exist. No row data.",
    ("GET", "/health/gmail-capacity"): (
        "reports remaining connection slots against the hand-managed cap (#290). "
        "A count, not a roster."
    ),
    ("GET", "/auth/gmail/callback"): (
        "Google redirects the browser here with no session cookie, so it CANNOT "
        "require one. It is not open: the `state` parameter is signed and is "
        "what binds the callback to the user who started the flow."
    ),
    ("GET", "/cron/sync"): (
        "the scheduled sync. Authenticated by a shared secret rather than a user "
        "session, and it fails CLOSED when that secret is unconfigured."
    ),
    ("POST", "/cron/sync"): "same endpoint, same shared secret, same fail-closed behaviour.",
}


def _verbs(route: Any) -> list[str]:
    """The methods a route serves, minus the two Starlette adds for free.

    HEAD is auto-registered alongside GET and OPTIONS is CORS preflight;
    neither is a hand-written handler, and requiring an exemption for each
    would make the allowlist twice as long and half as readable.
    """

    return sorted(set(getattr(route, "methods", None) or []) - {"HEAD", "OPTIONS"})

#: The walk has to see at least this many endpoints. The app serves 29; a floor
#: rather than an equality so adding a route does not red an unrelated PR, and
#: a floor at all so a walk that goes blind cannot pass.
MIN_ROUTES = 25

#: A path that exists ONLY behind ``include_router``. If the walk cannot reach
#: this, it is not reaching the 24 routes that carry every user's data.
INCLUDED_ROUTER_WITNESS = "/applications"


@pytest.fixture
def cloud_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("JOBTRACKER_CORS_ALLOWED_HOSTS", "jobtracker.app")

    import jobtracker.config as config_module

    importlib.reload(config_module)
    yield config_module.settings
    monkeypatch.undo()
    importlib.reload(config_module)


@pytest.fixture
def cloud_app(cloud_settings):
    import jobtracker.main_cloud as main_cloud_module

    importlib.reload(main_cloud_module)
    return main_cloud_module.app


def _children_of(route: Any) -> list[Any]:
    """Both ways a route can hold other routes on FastAPI 0.141."""

    found: list[Any] = list(getattr(route, "routes", None) or [])
    included = getattr(route, "original_router", None)
    if included is not None:
        found.extend(getattr(included, "routes", None) or [])
    return found


def _walk(routes: Any, seen: set[int] | None = None) -> Iterator[Any]:
    seen = set() if seen is None else seen
    for route in routes:
        if id(route) in seen:
            continue
        seen.add(id(route))
        yield route
        yield from _walk(_children_of(route), seen)


def _walk_routes(app: Any) -> Iterator[Any]:
    """Every route the app serves, including the ones ``include_router`` hides.

    Exported because ``test_main_cloud.py`` makes an "X is absent" assertion
    that was being evaluated against a set which could not have contained X.
    One walker, one place to fix when FastAPI moves the routes again.
    """

    return _walk(app.routes)


def _endpoints(app: Any) -> list[Any]:
    return [r for r in _walk_routes(app) if getattr(r, "endpoint", None) is not None]


def _dependency_names(route: Any) -> set[str]:
    """Every dependency in the route's tree, not just the top level.

    Auth can be declared on the route, on the router, or inside another
    dependency. Reading only the first level would call a route unauthenticated
    because its guard is one layer down, and the fix for that false positive is
    usually to weaken the assertion.
    """

    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return names

    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", str(call)))
        stack.extend(getattr(dep, "dependencies", None) or [])
    return names


def test_the_route_walk_actually_reaches_the_included_routers(cloud_app):
    """The control. Every assertion below is "no route is X"; on an empty
    walk they all pass while measuring nothing, and an empty walk is exactly
    what the guard this file replaces was doing."""

    endpoints = _endpoints(cloud_app)
    flat = [r for r in cloud_app.routes if getattr(r, "endpoint", None) is not None]

    assert len(endpoints) >= MIN_ROUTES, (
        f"the route walk found {len(endpoints)} endpoints, below the floor of "
        f"{MIN_ROUTES}. A flat scan of app.routes finds {len(flat)} on this "
        "FastAPI version, so this is the walk going blind rather than the app "
        "shrinking. Check _children_of against how include_router stores its "
        "routes in the installed FastAPI."
    )

    paths = {getattr(r, "path", None) for r in endpoints}
    assert INCLUDED_ROUTER_WITNESS in paths, (
        f"{INCLUDED_ROUTER_WITNESS} is served but the walk cannot see it. Every "
        "route carrying user data arrives through include_router, so a walk "
        "that misses this one is checking only the health endpoints."
    )


def test_every_public_route_on_the_allowlist_still_exists(cloud_app):
    """A stale exemption is how a route stays public after the reason stops
    applying, and how a deleted route's exemption silently adopts whatever
    later takes its path."""

    served = {
        (verb, getattr(r, "path", None)) for r in _endpoints(cloud_app) for verb in _verbs(r)
    }
    stale = sorted(entry for entry in PUBLIC if entry not in served)
    assert not stale, (
        f"these routes are exempted from authentication but are not served: {stale}. "
        "Remove them from PUBLIC. An allowlist entry with nothing behind it is a "
        "standing permission waiting for a future route to inherit."
    )


def test_every_route_that_is_not_deliberately_public_requires_a_user(cloud_app):
    unauthenticated = []
    for route in _endpoints(cloud_app):
        path = getattr(route, "path", None)
        guarded = "current_user" in _dependency_names(route)
        for verb in _verbs(route):
            if guarded or (verb, path) in PUBLIC:
                continue
            endpoint = getattr(route, "endpoint", None)
            where = getattr(endpoint, "__module__", "?")
            unauthenticated.append(f"{verb:8} {path}   ({where})")

    assert not unauthenticated, (
        "these routes are served to anyone with the URL:\n  "
        + "\n  ".join(unauthenticated)
        + "\n\nEvery route resolves `current_user` unless it is on PUBLIC in this "
        "file with a written reason. If one of these is meant to be public, add "
        "it there and say why; if it is not, it is serving user data to anonymous "
        "callers right now."
    )
