"""The Gmail OAuth callback must not return the browser to a host that does
not carry the user's session.

THE INCIDENT THIS PINS
----------------------
The owner reported, having just published the OAuth app: *"i was trying to
disconnect and connect ... it just took 2 times the auth, and after 2nd time,
it goes to landing and then when clicking on sign-in it skips the login page,
and goes to the dashboard!"*

Read as a sign-in bug it makes no sense — sign-in was never broken. Measured
against production on 2026-08-14, with no credentials and no session:

    $ curl -sD - "https://jobtracker-api-seven.vercel.app/auth/gmail/callback\
?state=bogus&code=bogus"
    HTTP/2 302
    location: https://jobtracker-web-five.vercel.app/settings?gmail=error

    $ curl -sD - "https://jobtracker-web-five.vercel.app/settings?gmail=connected"
    HTTP/2 307
    location: /login?gmail=connected&redirect=%2Fsettings

``jobtracker-web-five.vercel.app`` is a pre-rename alias of the web project.
It still serves the whole app, so nothing looked broken. But **cookies are
scoped to a host** and the session lives on ``getapplied.vercel.app``, so
arriving on the other alias is arriving signed out — and the proxy correctly
sent him to ``/login``. Every symptom follows from that one fact, including the
last one: his session on the original host was never touched, which is exactly
why clicking "Sign in" there skipped ``/login`` and went straight to the
dashboard.

WHY IT SURVIVED. The deployment held TWO independent answers to "which host is
the web app?" — the CORS allowlist, derived from the hostnames Vercel injects,
and the hand-set ``JOBTRACKER_WEB_APP_URL``. Nothing compared them. A stale
alias in the second one is invisible to every test in this repository and to
every check in CI, because both hostnames really do serve the app; the
difference is only which one the browser's cookies are on. That is the
"checks that cannot fail" shape: a fact stated twice, verified once.

WHAT THIS FILE ASSERTS. Properties of the return-destination POLICY, not of any
string: the destination still comes only from operator configuration (the
open-redirect guarantee in the router's header is untouched), and it must name
a host this deployment already trusts as its front end. Both halves are needed
— the first alone is what shipped, and it is what failed.

PROVED ABLE TO FAIL. Against the pre-fix ``_web_redirect`` — which was
``base = (settings.web_app_url or "").rstrip("/")`` with no check — the four
tests below marked ``RED BEFORE`` all fail, because that code returns a 302 to
whatever host is configured (and, with nothing configured, a RELATIVE
``/settings?...`` that the browser resolves against the API's own host). The
run is in the PR body.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

# The production pairing, reproduced. These are the two real hostnames; the
# incident is precisely that they are different.
APP_HOST = "getapplied.vercel.app"
STALE_ALIAS = "jobtracker-web-five.vercel.app"


def _module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    web_app_url: str | None,
    production_url: str = APP_HOST,
    allowed_hosts: str = "",
):
    """Load the Gmail OAuth router under a given deployment environment.

    Reloads ``config`` first so ``settings`` (an ``lru_cache``d singleton)
    picks the environment up, then the router so it binds to the fresh module.
    """

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", production_url)
    monkeypatch.setenv("VERCEL_URL", "")
    monkeypatch.setenv("JOBTRACKER_CORS_ALLOWED_HOSTS", allowed_hosts)
    monkeypatch.setenv("JOBTRACKER_WEB_APP_URL", web_app_url if web_app_url is not None else "")

    import jobtracker.config as config_module

    importlib.reload(config_module)
    import jobtracker.cloud.gmail_oauth as gmail_oauth

    importlib.reload(gmail_oauth)
    return gmail_oauth


@pytest.fixture(autouse=True)
def _restore_settings(monkeypatch: pytest.MonkeyPatch):
    """Leave the settings singleton as we found it.

    Without this the next test file in the session inherits a cloud config —
    the same guard ``test_cors_origin_regex.py`` carries, for the same reason.
    """

    yield
    monkeypatch.undo()
    import jobtracker.config as config_module

    importlib.reload(config_module)
    import jobtracker.cloud.gmail_oauth as gmail_oauth

    importlib.reload(gmail_oauth)


# ── the incident itself ───────────────────────────────────────────────


def test_the_stale_alias_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED BEFORE. The exact production misconfiguration, byte for byte.

    Pre-fix this returned ``302 -> https://jobtracker-web-five.vercel.app/
    settings?gmail=connected``, which is a signed-out landing for every user
    whose session is on ``getapplied.vercel.app``.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{STALE_ALIAS}")

    with pytest.raises(HTTPException) as excinfo:
        gmail_oauth._web_redirect("connected")

    message = str(getattr(excinfo.value, "detail", excinfo.value))
    assert STALE_ALIAS in message, (
        "the refusal must NAME the offending host — an operator reading a 503 "
        f"needs to know which value to change. Got: {message}"
    )


@pytest.mark.parametrize(
    "hostile",
    [
        f"https://{STALE_ALIAS}",
        "https://jobtracker-web-five.vercel.app/",  # trailing slash, same host
        "https://evil.example.com",
        "https://getapplied.vercel.app.evil.com",  # suffix smuggling
        "https://notgetapplied.vercel.app",
        "https://GETAPPLIED.vercel.app.evil.com",  # case must not smuggle it
    ],
)
def test_untrusted_return_hosts_are_refused(
    monkeypatch: pytest.MonkeyPatch, hostile: str
) -> None:
    """RED BEFORE. No host outside the deployment's own list may be a target.

    The suffix-smuggling cases are here because the check is on the parsed
    ``hostname``, not on a substring or a ``startswith`` — the two ways this
    kind of guard is usually written wrong.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=hostile)

    with pytest.raises(HTTPException):
        gmail_oauth._web_redirect("connected")


def test_an_unset_web_app_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED BEFORE. Unset used to degrade into a RELATIVE redirect.

    ``(None or "").rstrip("/")`` is ``""``, so the target became
    ``/settings?gmail=connected`` — resolved by the browser against the API's
    own hostname, stranding the user on a backend that serves no such page.
    A silent wrong answer, which is the failure mode this whole file is about.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=None)

    with pytest.raises(HTTPException) as excinfo:
        gmail_oauth._web_redirect("connected")

    assert "JOBTRACKER_WEB_APP_URL" in str(getattr(excinfo.value, "detail", excinfo.value)), (
        "the refusal must name the variable to set"
    )


# ── what must keep working, so the guard cannot break the product ─────


def test_the_apps_own_production_host_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The correct configuration — what production must be changed to.

    This is also the positive control for every refusal above: if the trusted
    list were empty, or the check inverted, this test goes red and the others
    would be passing for the wrong reason.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    response = gmail_oauth._web_redirect("connected")
    assert response.status_code == 302
    assert response.headers["location"] == f"https://{APP_HOST}/settings?gmail=connected"


def test_a_trailing_slash_is_still_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator pasting the URL with a trailing slash must not break it.

    The old code tolerated this and the guard must not quietly stop doing so —
    a fix that makes a working configuration fail is not a fix.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}/")

    assert (
        gmail_oauth._web_redirect("error").headers["location"]
        == f"https://{APP_HOST}/settings?gmail=error"
    )


def test_a_custom_domain_declared_by_the_operator_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented escape hatch keeps working.

    ``JOBTRACKER_CORS_ALLOWED_HOSTS`` is how a custom domain is declared today.
    Because the return host now reads the SAME list, declaring the domain once
    makes both CORS and this redirect accept it — which is the property that
    stops the two from drifting apart again.
    """

    gmail_oauth = _module(
        monkeypatch,
        web_app_url="https://applied.example.com",
        production_url=APP_HOST,
        allowed_hosts="applied.example.com",
    )

    assert (
        gmail_oauth._web_redirect("connected").headers["location"]
        == "https://applied.example.com/settings?gmail=connected"
    )


def test_localhost_still_works_for_local_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``vercel dev`` serves the web app on localhost:3000; the port varies."""

    gmail_oauth = _module(monkeypatch, web_app_url="http://localhost:3000", production_url="")

    assert (
        gmail_oauth._web_redirect("connected").headers["location"]
        == "http://localhost:3000/settings?gmail=connected"
    )


# ── the property the router's header promises ─────────────────────────


def test_the_destination_never_comes_from_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No open redirect: ``_web_redirect`` takes only an outcome token.

    Asserted on the SIGNATURE rather than by driving a hostile request, so it
    stays true for a caller that does not exist yet. The moment someone adds a
    ``next``/``return_to`` parameter here, this goes red and they have to argue
    for it in review — which is the whole point of the module header's
    "never a value taken from the request".
    """

    import inspect

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")
    parameters = list(inspect.signature(gmail_oauth._web_redirect).parameters)

    assert parameters == ["outcome"], (
        "_web_redirect grew a parameter. If it can be told where to go, the "
        f"open-redirect guarantee in the router's header is gone. Got: {parameters}"
    )


def test_health_reports_the_return_host_and_whether_it_is_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED BEFORE (the fields did not exist). The stale value must be VISIBLE.

    The guard above only fires when somebody runs a Gmail connect, which is how
    the real misconfiguration survived 26 days: nothing an operator could look
    at said the return host was wrong, and the wrong host served the app
    perfectly. ``/health`` is the thing that gets looked at.

    Asserted through the same predicate the guard uses, on the same
    environment, so the endpoint cannot report "trusted" about a value the
    callback would refuse — the two answers are one function.
    """

    import jobtracker.config as config_module

    _module(monkeypatch, web_app_url=f"https://{STALE_ALIAS}")
    assert config_module.configured_web_app_host() == STALE_ALIAS
    assert config_module.web_app_host_is_trusted() is False, (
        "the incident's own configuration reported itself as trusted"
    )

    _module(monkeypatch, web_app_url=f"https://{APP_HOST}")
    assert config_module.configured_web_app_host() == APP_HOST
    assert config_module.web_app_host_is_trusted() is True, (
        "the CORRECT configuration reported itself as untrusted — the check is "
        "inverted or the trusted list is empty, and every refusal above is "
        "passing for the wrong reason"
    )

    _module(monkeypatch, web_app_url=None)
    assert config_module.configured_web_app_host() is None
    assert config_module.web_app_host_is_trusted() is False


def test_the_outcome_token_is_escaped_into_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one value that does reach the URL is quoted.

    ``outcome`` is internal today, but it is the only thing interpolated into
    the ``Location`` header, so the escaping is worth a test rather than a
    reading of the source.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    location = gmail_oauth._web_redirect("er ror&x=1").headers["location"]
    assert location == f"https://{APP_HOST}/settings?gmail=er%20ror%26x%3D1"
