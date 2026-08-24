"""A product's signup confirmation is not a job application (#493).

Why this file exists
--------------------

``pending_application.strong`` carried ``(verify|confirm) your e.?mail``. In a
subject that is +6, which is score 6, margin 6, confidence 0.90 — over
``AUTO_FILE_GATE`` — so every SaaS product that sends a double-opt-in became a
job application with a card on the board, and one of them invented an employer
out of its sender domain.

The corpus could not see it. ``test_independent_corpus.py`` generates job mail;
it contains no product-signup verification at all, so the control #464 cited
("ats-relay-noise holds at 2") scored identically before and after. A gate that
cannot fail is not a gate, and this repository keeps a ledger of those.

What this file pins
-------------------

The rule is about EVIDENCE, not about a vendor or a sender. A message that asks
you to confirm an address, and says nothing else that ties it to employment,
must not be stated as a lifecycle fact. The wordings below are synthetic and
generic on purpose: the real messages that prompted this are in a private
mailbox, this repository is public, and a test keyed to one vendor's sentence
would be exactly the narrow patch the fix was chosen to avoid.

The controls are the half that makes it worth anything. Job-anchored
verification mail must STILL auto-file — otherwise this file passes just as
happily against a classifier that has forgotten how to read verification mail
at all.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import get_rules_classifier
from jobtracker.cloud.pipeline import AUTO_FILE_GATE

#: Product signup / account mail. None of it mentions a job, a role, a
#: position, an employer or an application process.
PRODUCT_SIGNUP = [
    pytest.param(
        "Confirm your email address",
        "Confirm your email address. Follow the link below to confirm this "
        "address and finish signing up.",
        id="database-vendor-double-opt-in",
    ),
    pytest.param(
        "[Acme Cloud] Click this link to confirm your email address",
        "Confirm your email address by clicking on this link. If you did not "
        "create an account, you can ignore this message.",
        id="dev-tool-signup",
    ),
    pytest.param(
        "Verify your email",
        "Pay faster at every store where our checkout is accepted.",
        id="payments-product",
    ),
    pytest.param(
        "Please confirm your e-mail",
        "You are receiving this because you signed up for an application. "
        "Confirm the address to finish creating your account.",
        id="the-homonym",
        # "signed up for an APPLICATION" — software, not employment. This is
        # why a "require a job-anchor word" guard was measured and rejected:
        # the anchor is present and means something else, and the phrase sits
        # inside the ~200 characters production actually classifies.
    ),
]

#: The same ask, from an employer, about a job. These MUST still be filed.
JOB_ANCHORED = [
    pytest.param(
        "Verify your email to complete your application",
        "Please verify your email address to complete your application for "
        "the Software Engineer position.",
        id="verification-that-names-the-application",
    ),
    pytest.param(
        "[Action Required] Your Northwind Robotics Application",
        "Please verify your email address before we can review your "
        "application.",
        id="the-459-family",
    ),
]


@pytest.mark.parametrize(("subject", "body"), PRODUCT_SIGNUP)
def test_a_signup_confirmation_is_never_stated_as_a_lifecycle_fact(subject, body):
    """The defect. Not "is classified `other`" — "is not asserted at me".

    Deliberately asserted against the GATE rather than against a category. A
    later change may legitimately give these mail a category; what it may not
    do is auto-file one, because auto-filing is what mints the card and the
    fabricated employer.
    """

    result = get_rules_classifier().classify(subject, body, sender_email=None)
    assert result.confidence < AUTO_FILE_GATE, (
        f"{subject!r} would be auto-filed as {result.category.value} at "
        f"{result.confidence}. Nothing in this message says it is about a job."
    )


@pytest.mark.parametrize(("subject", "body"), JOB_ANCHORED)
def test_verification_mail_about_a_real_application_still_files(subject, body):
    """The control, and the reason the test above cannot be passed by amnesia.

    Without this, deleting every pending pattern in the file would turn the
    first test green.
    """

    result = get_rules_classifier().classify(subject, body, sender_email=None)
    assert result.confidence >= AUTO_FILE_GATE, (
        f"{subject!r} scored {result.category.value} at {result.confidence}, "
        "under the auto-file gate — real verification mail stopped filing"
    )
    assert result.category.value == "pending_application"


def test_the_two_sets_are_told_apart_by_evidence_not_by_sender():
    """Both sets are classified with ``sender_email=None``.

    Stated as its own test because it is the property that keeps the fix
    general. If either set above ever needs a sender to be sorted correctly,
    the rule has become a domain allowlist and this file should fail rather
    than be quietly given one.
    """

    classifier = get_rules_classifier()
    filed = {
        classifier.classify(p.values[0], p.values[1], None).confidence >= AUTO_FILE_GATE
        for p in PRODUCT_SIGNUP
    }
    assert filed == {False}, "a product signup was filed without any sender hint"
