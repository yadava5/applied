"""A consent chained off a sign-in returns to the dashboard, not Settings (#510).

Every Gmail callback used to end on `/settings`, unconditionally. That is right
for someone who pressed Connect there, and wrong for someone who just signed
up: #504 chains the consent straight off a first Google sign-in, so the first
screen of a brand-new account was a preferences page, reached by a redirect the
user never asked for, reporting an outcome they experienced as "signing up".

The flag has to survive a round trip through Google, so it rides in the signed
state beside ``ro``. These tests pin BOTH destinations. Asserting only that a
chained connect lands on the dashboard would pass against a function that had
simply been rewritten to send everyone there, which would break the deliberate
Connect-in-Settings path — so the Settings case is the control and is not
optional.
"""

from __future__ import annotations

import uuid

import pytest

from jobtracker.cloud import gmail_oauth


def _location(response) -> str:
    return response.headers["location"]


def test_a_chained_connect_lands_on_the_dashboard() -> None:
    assert "/dashboard?gmail=connected" in _location(
        gmail_oauth._web_redirect("connected", "https://example.test", chained=True)
    )


def test_a_settings_connect_still_lands_on_settings() -> None:
    """THE CONTROL. Without this, sending everyone to the dashboard passes."""
    assert "/settings?gmail=connected" in _location(
        gmail_oauth._web_redirect("connected", "https://example.test", chained=False)
    )


def test_the_default_is_settings_so_an_older_state_is_unchanged() -> None:
    """A state minted before this flag existed carries no ``ch`` claim.

    The web app and this API deploy independently, so states from the previous
    deploy are in flight during every release. Absent must mean what it always
    meant.
    """
    assert "/settings?gmail=connected" in _location(
        gmail_oauth._web_redirect("connected", "https://example.test")
    )


@pytest.mark.parametrize("outcome", ["error", "auth", "unavailable", "capacity"])
def test_a_chained_FAILURE_also_lands_on_the_dashboard_and_carries_its_reason(
    outcome: str,
) -> None:
    """A chained user whose connect failed must not be dropped somewhere silent.

    They were never going to Settings, so bouncing them there explains a
    failure next to a button they did not press. The reason travels with them
    instead — the dashboard renders it (`GmailNotice`).
    """
    location = _location(
        gmail_oauth._web_redirect(outcome, "https://example.test", chained=True)
    )
    assert "/dashboard?gmail=" in location
    assert outcome in location


def test_the_flag_survives_the_round_trip_inside_the_signed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """END TO END through the real sign/verify pair.

    The tests above exercise `_web_redirect` with a boolean handed to it
    directly, which passes perfectly well against a `_sign_state` that never
    writes the claim and a `_verify_state` that never reads it — the whole
    mechanism missing, and every assertion green. This is the wiring.

    A real key is minted and the modules reloaded for the reason
    ``test_gmail_oauth_return_host._module`` documents: ``credentials.cloud``
    binds ``settings`` at import, so signing with a freshly configured key
    while encrypting through a stale Fernet produces a state this deployment
    cannot read back.
    """

    import importlib

    from cryptography.fernet import Fernet

    monkeypatch.setenv("JOBTRACKER_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())

    import jobtracker.config as config_module

    importlib.reload(config_module)
    import jobtracker.credentials.cloud as cred_cloud_module

    importlib.reload(cred_cloud_module)
    module = importlib.reload(gmail_oauth)

    user_id = uuid.uuid4()

    chained = module._verify_state(
        module._sign_state(user_id, "verifier-value", "https://example.test", True)
    )
    assert chained is not None
    assert chained[3] is True, "the chained flag did not survive the round trip"

    # THE CONTROL. Without it, a `_verify_state` hard-coded to return True
    # passes the assertion above.
    deliberate = module._verify_state(
        module._sign_state(user_id, "verifier-value", "https://example.test", False)
    )
    assert deliberate is not None
    assert deliberate[3] is False

    # The verifier still round-trips: this change must not have disturbed PKCE.
    assert chained[1] == "verifier-value"


def test_the_flag_cannot_name_a_destination() -> None:
    """It selects between two literals in this module and is not a path.

    The security property that matters here is unchanged by #510 and this
    states it: whatever ``chained`` is, the host comes from ``return_origin``
    (validated at mint) and the path is one of two constants.
    """
    for chained in (True, False):
        location = _location(
            gmail_oauth._web_redirect("connected", "https://example.test", chained)
        )
        assert location.startswith("https://example.test/")
        path = location.split("https://example.test", 1)[1].split("?", 1)[0]
        assert path in {"/dashboard", "/settings"}
