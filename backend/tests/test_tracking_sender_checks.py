"""``tracking/`` asks the classifier what a digest is, and matches domains on a dot.

Two defects, both found while fixing CodeQL alert 50
(``py/incomplete-url-substring-sanitization``) on ``classifier/hybrid.py`` and
both deliberately left out of that change. Neither is CodeQL-flagged, because
neither looks like a URL check — which is why this file exists.

1. ``linker._looks_like_digest_or_promo`` carried its own copy of
   ``NON_APPLICATION_SENDERS``, and the copy had already drifted: four tokens of
   the canonical six, missing ``alerts-noreply`` and ``promotions``. It matched
   them with ``token in sender``, unanchored over the WHOLE address.

2. ``extractor.CompanyExtractor.extract`` matched ``DOMAIN_TO_COMPANY`` with
   ``domain.endswith(known_domain)`` and no dot boundary, so
   ``evil-greenhouse.io`` read as Greenhouse and ``evil-google.com`` was
   attributed to Google at 0.95 confidence.

The two halves of defect 1 were wrong in OPPOSITE directions — the missing
tokens let real digests through the guard, the containment swept in mail that
was not a digest at all — so a corpus total that does not move proves nothing on
its own. The per-address halves below are what pin it.

THE DURABLE HALF IS THE DRIFT GATE, not the two fixes. The list is now read from
one place, so drift is only possible by someone writing a second one; the tests
at the bottom are parametrized over the LIVE constant, so a token added to
``NON_APPLICATION_SENDERS`` extends them automatically and a token dropped from
``tracking/``'s view of it fails them by name. A test that merely asserted "the
import exists" would pass forever and is the ``if (exists)`` shape this codebase
already has a note about.

Not in scope, and deliberately left alone: ``linker.NON_PERSON_SENDER_TOKENS``.
It shares two strings with ``NON_APPLICATION_SENDERS`` and is not a copy of it —
it answers "is this address a human?" for contact extraction, a different
question with a different list.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from jobtracker.classifier import hybrid, rules
from jobtracker.classifier.hybrid import NON_APPLICATION_SENDERS, _is_digest_mailbox
from jobtracker.database.models import Email, EmailCategory, EmailSource
from jobtracker.tracking import extractor as extractor_mod
from jobtracker.tracking import linker as linker_mod
from jobtracker.tracking.extractor import CompanyExtractor
from jobtracker.tracking.linker import ApplicationLinker

# One content hit, deliberately: ``_looks_like_digest_or_promo`` skips on two
# content hits ALONE, so at two the sender no longer decides anything and the
# test would pass without reading the sender at all. At exactly one, the guard's
# answer IS the sender predicate's answer, which is what these assert.
ONE_CONTENT_HIT = "Unsubscribe"


def _email(sender: str, body: str = ONE_CONTENT_HIT, subject: str = "Hello") -> Email:
    """An unsaved ``Email``. Nothing here touches a session or the DB."""

    return Email(
        user_id=uuid.uuid4(),
        source_account=EmailSource.GMAIL,
        message_id=f"tracking-sender-checks-{sender}",
        received_at=datetime(2026, 8, 19, 12, 0, 0),
        subject=subject,
        sender_email=sender,
        body_text=body,
        classified_as=EmailCategory.NEEDS_REVIEW,
    )


@pytest.fixture(scope="module")
def guard() -> ApplicationLinker:
    return ApplicationLinker()


@pytest.fixture(scope="module")
def company() -> CompanyExtractor:
    return CompanyExtractor()


def test_the_fixture_body_lands_exactly_one_content_hit(guard: ApplicationLinker) -> None:
    """The premise the sender tests rest on, checked rather than assumed.

    If ``ONE_CONTENT_HIT`` ever matched two patterns, every "the guard fires"
    assertion below would go green through the content branch and stop reading
    the sender — green for a reason that has nothing to do with what is being
    tested. That is the failure this file is guarding other files against, so
    it does not get to make it itself.
    """

    text = guard._email_text(_email("someone@example.com"))
    hits = sum(1 for p in guard._non_application_patterns if p.search(text))
    assert hits == 1, f"{ONE_CONTENT_HIT!r} matched {hits} content patterns, not 1"


# =============================================================================
# Defect 1 — the drifted fourth copy of NON_APPLICATION_SENDERS
# =============================================================================


@pytest.mark.parametrize("sender", ["alerts-noreply@acme.example", "promotions@acme.example"])
def test_the_two_tokens_the_copy_had_lost_now_reach_the_linker(
    guard: ApplicationLinker, sender: str
) -> None:
    """``alerts-noreply`` and ``promotions`` are the measured drift.

    Canonical ``NON_APPLICATION_SENDERS`` holds six tokens; the copy in
    ``linker`` held four. These two addresses are exactly what the gap cost:
    a job-alert digest that ``hybrid`` forces to OTHER, which ``linker`` waved
    through towards ``_find_or_create_application``.
    """

    assert _is_digest_mailbox(sender) is True
    assert guard._looks_like_digest_or_promo(_email(sender)) is True
    assert guard._should_skip_email(_email(sender)) is True


def test_a_lookalike_domain_no_longer_reads_as_a_digest_mailbox(
    guard: ApplicationLinker,
) -> None:
    """The other half, in the other direction: containment was too wide.

    ``token in sender`` asked whether the token appeared ANYWHERE in the whole
    address, so a domain anyone can register carried it past the guard and got
    real mail skipped. The boundary is now structural — local part, or a whole
    label of the domain.
    """

    assert guard._looks_like_digest_or_promo(_email("hello@acme-newsletterhub.example")) is False
    assert guard._looks_like_digest_or_promo(_email("careers@marketingpartners.example")) is False


@pytest.mark.parametrize(
    "sender",
    [
        "jobalerts-noreply@acme.example",  # token inside the local part
        "no-reply@marketing.acme.example",  # token as a whole domain label
        "newsletter@acme.example",  # token IS the local part
    ],
)
def test_the_addresses_the_guard_exists_for_still_fire(
    guard: ApplicationLinker, sender: str
) -> None:
    """Anchoring must not cost the guard the mail it was written to catch."""

    assert guard._looks_like_digest_or_promo(_email(sender)) is True


# =============================================================================
# Defect 2 — DOMAIN_TO_COMPANY matched with no dot boundary
# =============================================================================


def test_a_greenhouse_lookalike_is_not_treated_as_an_ats_relay(
    company: CompanyExtractor,
) -> None:
    """``evil-greenhouse.io`` used to end with ``greenhouse.io``, so it WAS one.

    Reading a sender as an ATS relay is not cosmetic: it turns on the
    display-name fallback below, so the extractor took the employer from a
    string the sender controls entirely. ``rules.is_ats_sender`` has rejected
    this shape since #260; the extractor is only now agreeing with it.
    """

    name, confidence, method = company.extract(
        sender_email="careers@evil-greenhouse.io",
        subject="An update",
        body="",
        sender_name="Northwind Recruiting",
    )
    assert (name, confidence, method) == ("Evil-Greenhouse", 0.7, "domain_inferred")
    assert rules.is_ats_sender("careers@evil-greenhouse.io") is False


def test_a_google_lookalike_is_not_attributed_to_google(company: CompanyExtractor) -> None:
    """The misfiling this defect actually causes.

    ``domain_direct`` is the 0.95-confidence branch — the most confident answer
    the extractor gives — and ``evil-google.com`` reached it. That is a card
    filed under the wrong employer, from a domain anyone can register.
    """

    name, confidence, method = company.extract(
        sender_email="hr@evil-google.com", subject="Hello", body=""
    )
    assert name != "Google"
    assert method != "domain_direct"
    assert (name, confidence, method) == ("Evil-Google", 0.7, "domain_inferred")


@pytest.mark.parametrize(
    ("sender", "expected"),
    [
        ("hr@google.com", "Google"),  # the domain itself
        ("hr@mail.google.com", "Google"),  # a proper subdomain
        ("hr@careers.spacex.com", "SpaceX"),
    ],
)
def test_real_employer_domains_are_still_attributed(
    company: CompanyExtractor, sender: str, expected: str
) -> None:
    """Equivalence, the half that matters most: legitimate mail is unmoved."""

    name, confidence, method = company.extract(sender_email=sender, subject="Hello", body="")
    assert (name, method) == (expected, "domain_direct")
    assert confidence == 0.95


@pytest.mark.parametrize(
    "sender",
    [
        "no-reply@us.greenhouse-mail.io",  # the relay Greenhouse actually uses
        "no-reply@greenhouse.io",
        "no-reply@lever.co",
        "hr@tenant.myworkday.com",
        "hr@tenant.workday.com",
    ],
)
def test_real_ats_relays_are_still_read_as_ats(company: CompanyExtractor, sender: str) -> None:
    """The ATS branch still turns on for every relay in the corpus.

    ``myworkday.com`` and ``workday.com`` are the one pair in
    ``DOMAIN_TO_COMPANY`` where one key is a string suffix of the other. The
    loop breaks on its first hit, so under the old containment the ORDER of the
    dict decided the answer; anchored, the two are disjoint and both resolve on
    their own terms. Both are asserted so a reordering cannot go unnoticed.
    """

    name, _, method = company.extract(
        sender_email=sender, subject="An update", body="", sender_name="Northwind Recruiting"
    )
    assert (name, method) == ("Northwind Recruiting", "sender_name")


# =============================================================================
# The drift gate
# =============================================================================


def test_tracking_reads_the_one_digest_predicate(guard: ApplicationLinker) -> None:
    """``linker`` uses the classifier's function OBJECT, not a copy of its body.

    On its own this would be close to unfalsifiable, which is why it is the
    smallest of the three gates here and not the only one — the parametrized
    pair below fail on behaviour even if someone reproduces the predicate under
    the same name.
    """

    assert linker_mod._is_digest_mailbox is hybrid._is_digest_mailbox
    assert extractor_mod.domain_matches is rules.domain_matches


@pytest.mark.parametrize("token", NON_APPLICATION_SENDERS)
def test_every_canonical_token_reaches_the_linker_guard(
    guard: ApplicationLinker, token: str
) -> None:
    """Parametrized over the LIVE list, so it grows with it.

    This is the test the original drift would have failed: with four of six
    tokens hardcoded in ``linker``, ``alerts-noreply`` and ``promotions`` come
    up red and name themselves. Add a seventh token to
    ``NON_APPLICATION_SENDERS`` and it is covered here the same day.
    """

    assert guard._looks_like_digest_or_promo(_email(f"{token}@acme.example")) is True, (
        f"{token!r} is in classifier NON_APPLICATION_SENDERS but tracking/linker.py "
        f"does not act on it — the two have drifted apart again."
    )


@pytest.mark.parametrize("token", NON_APPLICATION_SENDERS)
def test_no_canonical_token_matches_unanchored_in_the_linker_guard(
    guard: ApplicationLinker, token: str
) -> None:
    """…and the same list, held against the other failure mode.

    A domain that merely CONTAINS the token is not a digest mailbox. Revert
    ``linker`` to ``token in sender`` and every entry here goes red.
    """

    sender = f"hello@acme-{token}hub.example"
    assert guard._looks_like_digest_or_promo(_email(sender)) is False, (
        f"{sender!r} matched on {token!r} as a bare substring — tracking/linker.py "
        f"is back to unanchored containment."
    )


@pytest.mark.parametrize(
    "sender",
    [
        "jobalerts@acme.example",
        "jobalerts-noreply@acme.example",
        "alerts-noreply@acme.example",
        "promotions@acme.example",
        "no-reply@marketing.acme.example",
        "no-reply@promotions.acme.example",
        "hello@acme-newsletterhub.example",
        "hello@acme-promotionsdept.example",
        "careers@acme.example",
        "recruiting@northwind.example",
        "",
    ],
)
def test_the_two_call_sites_answer_identically(guard: ApplicationLinker, sender: str) -> None:
    """``hybrid`` and ``linker`` must never disagree about what a digest is.

    ``rules.is_ats_sender``'s docstring states the rule for the ATS list: two
    call sites that answer differently is a bug nobody could read off either
    one. The same applies here — ``hybrid`` forces the mail to OTHER and
    ``linker`` declines to build an application from it, and a message that gets
    one without the other is filed on a verdict the classifier did not reach.
    """

    assert guard._looks_like_digest_or_promo(_email(sender)) is _is_digest_mailbox(sender)
