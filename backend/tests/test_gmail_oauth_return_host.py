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
string: the destination is never a value this deployment has not checked against
the list of hosts it serves the app on, and the check happens before the
destination can be used. Both halves are needed — a check alone is what shipped,
and it is what failed.

WHERE THE DESTINATION COMES FROM CHANGED (#333), AND THE POLICY DID NOT.
It used to come only from operator configuration (``JOBTRACKER_WEB_APP_URL``),
which is how a stale alias could sit in it for 26 days. It now comes from the
caller's own origin — the host the user is actually browsing, whose cookie they
actually hold — passed to ``/auth/gmail/authorize``, **validated there against
``config.trusted_web_hosts`` before any consent URL exists**, and carried to the
callback inside the signed ``state``. The configured value survives as a
fallback for states minted before that shipped.

The ordering is the design, and the tests below are written to catch it being
got backwards. An origin that round-tripped through ``state`` WITHOUT being
checked at mint would be an open redirect signed by us — strictly worse than
the bug being fixed, and indistinguishable from the fix by any happy-path test.
So the refusals are asserted at ``_validated_return_origin`` (the mint leg),
and the callback is asserted to have grown no destination parameter of its own.

PROVED ABLE TO FAIL. Against the pre-fix ``_web_redirect`` — which was
``base = (settings.web_app_url or "").rstrip("/")`` with no check — the four
tests below marked ``RED BEFORE`` all fail, because that code returns a 302 to
whatever host is configured (and, with nothing configured, a RELATIVE
``/settings?...`` that the browser resolves against the API's own host). The
run is in the PR body. The #333 tests were proved the same way, by two separate
mutations of ``_validated_return_origin`` — one neutering the trusted-list
check, one neutering the API's-own-origin check — because a single mutation
that disables the whole validator proves only that the suite notices *a*
change, not that each branch is load-bearing. Those runs are in that PR body.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

# The production pairing, reproduced. These are the real hostnames; the
# incident is precisely that the first two are different.
APP_HOST = "getapplied.vercel.app"
STALE_ALIAS = "jobtracker-web-five.vercel.app"
# THE HOST THIS CODE ACTUALLY RUNS ON. `VERCEL_PROJECT_PRODUCTION_URL` is
# injected per PROJECT and the backend is its own Vercel project, so what it
# names is the API — never the web app. Defaulting the fixture to APP_HOST
# would model a deployment that cannot exist, and every test below would be
# measuring a twin: a guard anchored on hosts the API cannot know would look
# fine here and 503 the moment the env var was corrected in production. That
# near-miss is why this constant is spelled out rather than defaulted.
API_HOST = "jobtracker-api-seven.vercel.app"


def _module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    web_app_url: str | None,
    production_url: str = API_HOST,
    allowed_hosts: str = APP_HOST,
    redirect_uri: str = f"https://{API_HOST}/auth/gmail/callback",
):
    """Load the Gmail OAuth router under a given deployment environment.

    The defaults are the SHAPE of the real deployment: this process is the API
    project (``production_url``), and the web host is known only because the
    operator declared it (``allowed_hosts``). A test that wants the
    undeclared case — which is what production looked like on 2026-08-14,
    proved by the CORS probe quoted in ``config.trusted_web_hosts`` — passes
    ``allowed_hosts=""``.

    ``redirect_uri`` is the API's own callback URL, and it is set here because
    it is the second thing that says "this host is the backend"
    (``config.api_own_origins``). It defaults to the API host for the same
    reason ``production_url`` does: a fixture that left it unset would leave
    that branch of the self-check untested while every test still passed.

    Reloads ``config`` first so ``settings`` (an ``lru_cache``d singleton)
    picks the environment up, then the router so it binds to the fresh module.
    """

    monkeypatch.setenv("JOBTRACKER_DEPLOYMENT", "cloud")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", production_url)
    monkeypatch.setenv("VERCEL_URL", "")
    monkeypatch.setenv("JOBTRACKER_CORS_ALLOWED_HOSTS", allowed_hosts)
    monkeypatch.setenv("JOBTRACKER_GMAIL_OAUTH_REDIRECT_URI", redirect_uri)
    monkeypatch.setenv("JOBTRACKER_WEB_APP_URL", web_app_url if web_app_url is not None else "")

    import jobtracker.config as config_module

    importlib.reload(config_module)
    # ``credentials.cloud`` does ``from jobtracker.config import settings``, so
    # it holds the PREVIOUS settings object until it is reloaded too. That
    # matters here rather than being tidiness: ``_sign_state`` signs with the
    # reloaded config's key and encrypts the PKCE verifier through this
    # module's Fernet, and two different keys make a state this deployment
    # cannot read back.
    import jobtracker.credentials.cloud as cred_cloud_module

    importlib.reload(cred_cloud_module)
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
    import jobtracker.credentials.cloud as cred_cloud_module

    importlib.reload(cred_cloud_module)
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

    Both variables, on the real deployment shape: this process is the API
    project, and the web host is trusted because the operator declared it.

    This is also the positive control for every refusal above: if the trusted
    list were empty, or the check inverted, this test goes red and the others
    would be passing for the wrong reason.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    response = gmail_oauth._web_redirect("connected")
    assert response.status_code == 302
    assert response.headers["location"] == f"https://{APP_HOST}/settings?gmail=connected"


def test_the_right_url_with_the_host_undeclared_is_refused_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The near-miss this whole guard nearly shipped, pinned.

    ``JOBTRACKER_WEB_APP_URL`` is set to exactly the right origin — and the
    guard still refuses, because this API project has no way to know that
    origin is ours unless somebody says so. That was production's actual state
    on 2026-08-14: the CORS probe in ``config.trusted_web_hosts`` shows
    ``getapplied.vercel.app`` was NOT declared, so correcting only the first
    variable would have turned "connects to the wrong host" into "cannot
    connect at all".

    Refusing is the right behaviour — a return host this deployment cannot
    vouch for is exactly what caused the incident — but the message has to
    carry the operator to the fix rather than just saying no. That is what is
    asserted here, and it is the reason this test exists at all.
    """

    gmail_oauth = _module(
        monkeypatch, web_app_url=f"https://{APP_HOST}", allowed_hosts=""
    )

    with pytest.raises(HTTPException) as excinfo:
        gmail_oauth._web_redirect("connected")

    detail = str(excinfo.value.detail)
    assert "JOBTRACKER_CORS_ALLOWED_HOSTS" in detail, (
        "the refusal names neither the second variable nor the remedy, so an "
        f"operator who set the obvious one is stuck. Got: {detail}"
    )
    assert APP_HOST in detail, "the refusal must name the host to declare"


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


def test_the_callback_cannot_be_told_where_to_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No open redirect, asserted at the leg an attacker can actually reach.

    This test used to read ``_web_redirect``'s signature and require it to take
    nothing but an outcome token. That guard was right for a destination which
    came only from operator configuration, and it is the wrong place now: since
    #333 ``_web_redirect`` IS told where to go — by ``_verify_state``, out of a
    token this backend signed, carrying an origin validated one leg earlier.
    Keeping the old assertion would have made the fix look like a regression
    and, worse, would have said nothing about the surface that matters.

    So the guard moves to ``gmail_callback`` itself, which is the endpoint an
    attacker can send a request to. Its query parameters must remain exactly
    the three Google sends. The moment someone adds ``next``/``return_to``/
    ``redirect_uri`` here, this goes red and they have to argue for it in
    review.
    """

    import inspect

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")
    parameters = list(inspect.signature(gmail_oauth.gmail_callback).parameters)

    assert parameters == ["state", "code", "error"], (
        "the Gmail callback grew a parameter. Everything it accepts comes "
        "straight off a URL Google was told to send the browser to, so a "
        "destination parameter here is an open redirect by definition. "
        f"Got: {parameters}"
    )


# ── #333: the caller's own origin, validated when the state is minted ──


def test_a_trusted_origin_is_accepted_with_web_app_url_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the change: ONE variable has to be right, not two.

    ``JOBTRACKER_WEB_APP_URL`` is unset entirely — the state production was in
    on the night of the incident, and the state a fresh deployment is in — and
    the flow still has a destination, because the caller said where it came
    from and this deployment recognised the host.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=None)

    assert gmail_oauth._validated_return_origin(f"https://{APP_HOST}") == (
        f"https://{APP_HOST}"
    )


@pytest.mark.parametrize(
    "hostile",
    [
        f"https://{STALE_ALIAS}",  # the incident's own host, now caller-supplied
        "https://evil.example.com",
        "https://getapplied.vercel.app.evil.com",  # suffix smuggling
        "https://notgetapplied.vercel.app",
        "https://GETAPPLIED.vercel.app.evil.com",  # case must not smuggle it
        "https://evil.example.com/getapplied.vercel.app",  # path smuggling
        "https://getapplied.vercel.app@evil.com",  # userinfo: trusted host FIRST
        "https://getapplied.vercel.app:pass@evil.com",  # ... with a password too
        "http://evil.example.com",  # scheme downgrade, remote host
        "javascript:alert(1)",  # not a web origin at all
        "//getapplied.vercel.app",  # scheme-relative, no scheme to check
        "",
    ],
)
def test_an_untrusted_origin_is_refused_at_mint(
    monkeypatch: pytest.MonkeyPatch, hostile: str
) -> None:
    """RED WITHOUT THE GUARD. Nothing outside the trusted list may be a target.

    Refused at ``/auth/gmail/authorize``, i.e. before a consent URL exists and
    before Google is ever reached, which is the ordering the whole design rests
    on. The userinfo cases are the reason
    ``config.canonical_return_origin`` rebuilds its answer from parsed parts
    instead of returning the caller's bytes: ``https://<trusted>@evil.com``
    reads as the trusted host to a human and resolves to ``evil.com``.

    ``400``, not ``503`` — a bad origin is the caller's problem, and the web
    app maps 503 onto "Gmail isn't enabled on this deployment yet", which would
    be a wrong and actionless message.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    with pytest.raises(HTTPException) as excinfo:
        gmail_oauth._validated_return_origin(hostile)

    assert excinfo.value.status_code == 400, (
        "an untrusted origin is a bad request, not a broken deployment; 503 "
        "renders as 'Gmail isn't enabled here yet' in the web app"
    )


def test_the_refusal_names_the_origin_and_the_remedy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal an operator cannot act on is a dead end.

    The same standard the configured-host refusal is already held to: name the
    offending value, and name the one variable that would make it work.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    with pytest.raises(HTTPException) as excinfo:
        gmail_oauth._validated_return_origin(f"https://{STALE_ALIAS}")

    detail = str(excinfo.value.detail)
    assert STALE_ALIAS in detail, f"the refusal must NAME the origin. Got: {detail}"
    assert "JOBTRACKER_CORS_ALLOWED_HOSTS" in detail, (
        f"the refusal must name the variable that would admit it. Got: {detail}"
    )


def test_the_apis_own_host_is_refused_even_though_it_is_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED WITHOUT THE SELF-CHECK. The stranded-on-the-backend case.

    ``config.trusted_web_hosts`` contains this API's own hostnames — it is
    built from ``VERCEL_URL``/``VERCEL_PROJECT_PRODUCTION_URL`` and CORS needs
    them there — so "is this origin ours?" answers YES for the one destination
    that is guaranteed to be wrong. The API serves no ``/settings``; returning
    the browser here is the same broken outcome as an unset return host, in a
    different costume. ``config.trusted_web_hosts`` stated this and declined to
    fix it; this is the fix, and this is the test that says the trusted-list
    check alone does not cover it.

    Asserted through the FULL default environment, not a hand-built list: the
    only reason this origin is dangerous is that the real deployment really
    does trust it.
    """

    import jobtracker.config as config_module

    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    assert config_module.return_origin_is_trusted(f"https://{API_HOST}") is True, (
        "the premise of this test is gone: the API's own host is no longer in "
        "the trusted list, so the refusal below could be passing for the wrong "
        "reason"
    )

    with pytest.raises(HTTPException) as excinfo:
        gmail_oauth._validated_return_origin(f"https://{API_HOST}")

    detail = str(excinfo.value.detail)
    assert excinfo.value.status_code == 400
    assert API_HOST in detail
    assert "JOBTRACKER_CORS_ALLOWED_HOSTS" not in detail, (
        "this refusal must NOT suggest the allowlist as a remedy — the host is "
        f"already on it, and adding it again fixes nothing. Got: {detail}"
    )


def test_the_apis_own_host_is_refused_from_the_redirect_uri_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off Vercel there are no injected hostnames, and the case is the same.

    ``gmail_oauth_redirect_uri`` names the API's own callback URL by
    definition, so it is the self-identifying fact that survives when
    ``VERCEL_*`` is absent. Without this branch the guard above would be
    Vercel-shaped, and a self-hosted deployment could strand its users while
    every test stayed green.
    """

    gmail_oauth = _module(
        monkeypatch,
        web_app_url=f"https://{APP_HOST}",
        production_url="",
        allowed_hosts=f"{APP_HOST},{API_HOST}",
        redirect_uri=f"https://{API_HOST}/auth/gmail/callback",
    )

    with pytest.raises(HTTPException) as excinfo:
        gmail_oauth._validated_return_origin(f"https://{API_HOST}")

    assert API_HOST in str(excinfo.value.detail)


def test_local_development_splits_the_two_by_PORT(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Localhost is one hostname running two different servers.

    ``localhost`` is in the trusted list for ``vercel dev``, and locally the
    web app is on :3000 while this API is on :8000 — the same host. Subtracting
    the API by HOSTNAME would refuse the web app too and make local development
    impossible, which is one of the outcomes #333 exists to deliver; comparing
    at ORIGIN granularity keeps them apart. Both halves are asserted, because
    the accept alone would pass with the self-check deleted and the refuse
    alone would pass with the whole host banned.
    """

    gmail_oauth = _module(
        monkeypatch,
        web_app_url=None,
        production_url="",
        allowed_hosts="",
        redirect_uri="http://localhost:8000/auth/gmail/callback",
    )

    assert (
        gmail_oauth._validated_return_origin("http://localhost:3000")
        == "http://localhost:3000"
    ), "local development must work with no allowlist entry and no web_app_url"

    with pytest.raises(HTTPException):
        gmail_oauth._validated_return_origin("http://localhost:8000")


def test_the_approved_origin_is_rebuilt_not_echoed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What goes into the signed state is a string this code constructed.

    The distinction that makes the smuggling cases above a closed class rather
    than a list: an approved-then-echoed input leaves a parser differential
    between Python and the browser, and only one of them decides where the user
    lands. Trailing slash, port and case are normalised away, so the value the
    callback puts in a ``Location`` header can only be
    ``scheme://host[:port]``.
    """

    gmail_oauth = _module(monkeypatch, web_app_url=None)

    for submitted in (
        f"https://{APP_HOST}/",
        f"https://{APP_HOST.upper()}",
        f"  https://{APP_HOST}  ",
        f"https://{APP_HOST}:443",
    ):
        assert gmail_oauth._validated_return_origin(submitted) == f"https://{APP_HOST}"


def test_the_origin_survives_the_state_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mint → verify → redirect, with the fallback unset so it cannot help.

    The seam this change adds, end to end at unit level: the origin approved at
    mint is the origin the callback redirects to, and nothing on that path
    consults ``JOBTRACKER_WEB_APP_URL`` — asserted by leaving it unset, which
    makes ``_web_app_base`` raise if it is ever reached.
    """

    import uuid

    from cryptography.fernet import Fernet

    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    gmail_oauth = _module(monkeypatch, web_app_url=None)

    user_id = uuid.uuid4()
    state = gmail_oauth._sign_state(
        user_id,
        gmail_oauth._generate_code_verifier(),
        gmail_oauth._validated_return_origin(f"https://{APP_HOST}"),
    )

    verified = gmail_oauth._verify_state(state)
    assert verified is not None
    assert verified[0] == user_id
    assert verified[2] == f"https://{APP_HOST}"

    assert (
        gmail_oauth._web_redirect("connected", verified[2]).headers["location"]
        == f"https://{APP_HOST}/settings?gmail=connected"
    )


def test_a_state_with_no_origin_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """The independent-deploy window, which is a real ten minutes.

    The web app and this API are separate Vercel projects. States minted by the
    older web deploy arrive carrying no ``ro`` claim, and must fall back rather
    than be rejected — rejecting them would break every connect started
    seconds before a deploy, for no security gain: the fallback is held to the
    same trusted-host rule.
    """

    import uuid

    from cryptography.fernet import Fernet

    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    state = gmail_oauth._sign_state(uuid.uuid4(), gmail_oauth._generate_code_verifier())
    verified = gmail_oauth._verify_state(state)

    assert verified is not None, "a state without an origin is valid, not forged"
    assert verified[2] is None
    assert (
        gmail_oauth._web_redirect("connected", verified[2]).headers["location"]
        == f"https://{APP_HOST}/settings?gmail=connected"
    )


def test_a_state_signed_with_another_key_cannot_supply_an_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The signature is what makes the carried origin trustworthy.

    An attacker who could mint states could redirect anywhere, so the property
    worth pinning is that they cannot: a state carrying a hostile ``ro`` and a
    valid-looking everything-else is rejected outright when it was signed with
    a key this deployment does not hold.
    """

    import uuid
    from datetime import UTC, datetime, timedelta

    import jwt
    from cryptography.fernet import Fernet

    ours = Fernet.generate_key().decode()
    theirs = Fernet.generate_key().decode()
    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", ours)
    gmail_oauth = _module(monkeypatch, web_app_url=f"https://{APP_HOST}")

    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "jobtracker:gmail-oauth-state",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "cv": Fernet(theirs.encode()).encrypt(b"verifier").decode("ascii"),
            "ro": "https://evil.example.com",
        },
        theirs,
        algorithm="HS256",
    )

    assert gmail_oauth._verify_state(forged) is None


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
