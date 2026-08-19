"""``"linkedin.com" in sender`` is true for ``…@evil-linkedin.com.attacker.io``.

CodeQL ``py/incomplete-url-substring-sanitization``, alert 50, on
``hybrid._forced_other_reason``. The line above it —
``any(token in sender_lower for token in NON_APPLICATION_SENDERS)`` — has the
same shape and was not flagged.

WHAT IT IS AND IS NOT. This guard decides whether a message is forced to OTHER
(a job-alert digest) instead of being read as an application lifecycle event.
It is a classification decision, not an authentication or authorisation
boundary. The realistic harm is a crafted sender domain steering mail into or
out of the digest bucket — a message that should have been filed as an
application getting dropped, or the reverse. Not account compromise.

TWO DEFECTS, TWO DIFFERENT FIXES. ``linkedin.com`` is a DOMAIN and gets the
anchored match ``rules.is_ats_sender`` already uses: the domain IS the listed
domain or is a proper subdomain of it, with the dot as the boundary — because
``endswith("linkedin.com")`` still matches ``evil-linkedin.com``.
``NON_APPLICATION_SENDERS`` holds MAILBOX names (``jobalerts``,
``jobs-noreply``, ``newsletter``, …), not domains, so domain parsing is the
wrong instrument for it; what it needs is a structural boundary — the token has
to be part of the local part, or a whole domain label, not an arbitrary
substring of the address.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.hybrid import HybridClassifier

# Exactly one NON_APPLICATION_PATTERNS hit ("unsubscribe"), no lifecycle
# vocabulary — the state in which the sender check alone decides the verdict.
ONE_DIGEST_SIGNAL = "Roles we thought you would like.\nUnsubscribe"
NEUTRAL_SUBJECT = "This week from the team"


def _guard(sender: str | None) -> str | None:
    return HybridClassifier()._forced_other_reason(
        NEUTRAL_SUBJECT, ONE_DIGEST_SIGNAL, sender
    )


@pytest.mark.parametrize(
    "sender",
    [
        "notifications@evil-linkedin.com.attacker.io",
        "jobs-noreply@linkedin.com.attacker.io",
        "hello@notlinkedin.com",
        "hello@linkedin.com.co",
        "linkedin.com@attacker.io",
    ],
)
def test_lookalike_domains_are_not_linkedin(sender: str) -> None:
    """A domain anyone can register must not read as LinkedIn."""

    assert _guard(sender) != "linkedin_job_alert_content", (
        f"{sender} was accepted as LinkedIn"
    )


@pytest.mark.parametrize(
    "sender",
    [
        "messages-noreply@linkedin.com",
        "notifications-noreply@e.linkedin.com",
        "no-reply@bounce.linkedin.com",
        "MESSAGES-NOREPLY@LinkedIn.com",
    ],
)
def test_real_linkedin_senders_still_match(sender: str) -> None:
    """Equivalence: every address that fired before must still fire."""

    assert _guard(sender) == "linkedin_job_alert_content", (
        f"{sender} stopped being recognised as LinkedIn"
    )


@pytest.mark.parametrize(
    "sender",
    [
        # The token sits in a registrable domain the attacker owns, not in the
        # mailbox name and not as a label of a mail service.
        "hello@acme-newsletterhub.example",
        "hello@sales.marketingagency.example",
        "hello@promotionsystems.example",
        "hello@jobalertsandmore.example",
    ],
)
def test_mailbox_tokens_do_not_match_an_arbitrary_substring(sender: str) -> None:
    """``newsletter`` inside ``newsletterhub`` is not a newsletter mailbox."""

    assert _guard(sender) != "sender_plus_digest_content", (
        f"{sender} matched a NON_APPLICATION_SENDERS token by substring"
    )


@pytest.mark.parametrize(
    "sender",
    [
        "jobalerts@acme.example",
        "jobs-noreply@acme.example",
        "alerts-noreply@acme.example",
        "newsletter@acme.example",
        "marketing@acme.example",
        "promotions@acme.example",
        "jobalerts-noreply@acme.example",
        "no-reply@newsletter.acme.example",
        "no-reply@marketing.acme.example",
        "JobAlerts@Acme.example",
    ],
)
def test_real_digest_mailboxes_still_match(sender: str) -> None:
    """Equivalence: the mailbox names the guard exists for keep matching."""

    assert _guard(sender) == "sender_plus_digest_content", (
        f"{sender} stopped being recognised as a digest sender"
    )


def test_no_sender_is_still_no_hit() -> None:
    """One digest signal and no sender is not enough to force OTHER."""

    assert _guard(None) is None
    assert _guard("") is None
    assert _guard("someone@acme.example") is None
