"""The CORS allowlist must not admit origins we do not own.

WHY THIS FILE EXISTS
--------------------
``_build_cors_origin_regex`` used to include a literal
``[a-zA-Z0-9-]+\\.vercel\\.app`` so preview deployments would work. Paired
with ``allow_credentials=True``, that made the allowlist effectively open:
anyone can deploy ``anything.vercel.app`` for free and the middleware would
echo their origin back with credentials permitted.

``SECURITY_AUDIT.md`` finding 2 (2026-07-22) recorded it as MEDIUM and
confirmed it against the live API — ``evil-attacker-12345.vercel.app`` was
echoed, while ``evil.example.com`` was correctly refused. It stayed open for
eleven days because **nothing tested it**. The regex is one line; one line is
exactly the kind of thing that gets edited back.

The replacement lists the deployment's OWN Vercel hostnames, which is how the
sibling project (Cadence, ``lib/middleware/cors.ts``) has always done it.

Every test below is a property of the ORIGIN POLICY, not of the string. They
would all still pass if the regex were rewritten a different way, and they all
fail if the wildcard comes back.
"""

from __future__ import annotations

import re

import pytest


def _regex_for(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed_hosts: str = "",
    vercel_url: str = "",
    production_url: str = "",
) -> re.Pattern[str]:
    """Build the live allow-origin regex under a given environment."""

    # ``VERCEL_URL`` and ``VERCEL_PROJECT_PRODUCTION_URL`` are NOT ``Settings``
    # fields -- ``config.trusted_web_hosts`` reads them out of ``os.environ``
    # on every call -- so ``setenv`` reaches them with no reload at all.
    monkeypatch.setenv("VERCEL_URL", vercel_url)
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", production_url)

    # ``cors_allowed_hosts`` IS a field, so it is set on the object rather than
    # rebuilt from the environment. The env var is comma-separated because a
    # validator splits it; the attribute takes the list that validator produces.
    hosts = [h.strip() for h in allowed_hosts.split(",") if h.strip()]

    import jobtracker.auth.supabase_jwt as auth_module
    import jobtracker.config as config_module
    import jobtracker.database.connection as connection_module

    holders = {
        id(module.settings): module.settings
        for module in (config_module, auth_module, connection_module)
    }
    for instance in holders.values():
        monkeypatch.setattr(instance, "deployment", "cloud")
        monkeypatch.setattr(instance, "cors_allowed_hosts", hosts)

    import jobtracker.main_cloud as main_cloud

    return re.compile(main_cloud._build_cors_origin_regex())


# ── the finding itself ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil-attacker-12345.vercel.app",
        "https://jobtracker.vercel.app",  # plausible-looking, still not ours
        "https://a.vercel.app",
        "https://APPLIED.vercel.app",  # case must not smuggle it through
    ],
)
def test_arbitrary_vercel_subdomains_are_refused(
    monkeypatch: pytest.MonkeyPatch, hostile: str
) -> None:
    """A vercel.app origin we do not own must not match.

    This is the regression. Anyone can register these in minutes.
    """

    regex = _regex_for(
        monkeypatch,
        allowed_hosts="jobtracker.app",
        vercel_url="applied-abc123.vercel.app",
        production_url="getapplied.vercel.app",
    )
    assert regex.fullmatch(hostile) is None, (
        f"{hostile} was admitted by the CORS allowlist. The *.vercel.app "
        "wildcard is back, and with allow_credentials=True that is an open "
        "credentialed origin allowlist."
    )


# ── what must keep working, so the fix cannot break the product ───────


def test_this_deployments_own_preview_url_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VERCEL_URL is the running deployment's own host — previews must work."""

    regex = _regex_for(monkeypatch, vercel_url="applied-git-feat-abc.vercel.app")
    assert regex.fullmatch("https://applied-git-feat-abc.vercel.app")


def test_production_url_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stable production host, which is what the web app actually uses."""

    regex = _regex_for(monkeypatch, production_url="getapplied.vercel.app")
    assert regex.fullmatch("https://getapplied.vercel.app")


def test_configured_hosts_are_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented escape hatch: JOBTRACKER_CORS_ALLOWED_HOSTS."""

    regex = _regex_for(monkeypatch, allowed_hosts="jobtracker.app,app.example.dev")
    assert regex.fullmatch("https://jobtracker.app")
    assert regex.fullmatch("https://app.example.dev")


def test_localhost_still_works_for_vercel_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regex = _regex_for(monkeypatch)
    assert regex.fullmatch("http://localhost:3000")
    assert regex.fullmatch("http://127.0.0.1:8000")


# ── the properties that make the allowlist an allowlist ───────────────


def test_unrelated_origins_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    regex = _regex_for(
        monkeypatch, allowed_hosts="jobtracker.app", production_url="getapplied.vercel.app"
    )
    for origin in (
        "https://evil.example.com",
        "https://getapplied.vercel.app.evil.com",  # suffix smuggling
        "https://notgetapplied.vercel.app",
        "https://jobtracker.app.evil.com",
    ):
        assert regex.fullmatch(origin) is None, f"{origin} was admitted"


def test_an_empty_environment_admits_nothing_but_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no Vercel vars and no configured hosts, nothing remote matches.

    Fails closed rather than open — the opposite of the behaviour this file
    exists to prevent.
    """

    regex = _regex_for(monkeypatch)
    assert regex.fullmatch("https://getapplied.vercel.app") is None
    assert regex.fullmatch("https://anything.vercel.app") is None
    assert regex.fullmatch("http://localhost:3000")
