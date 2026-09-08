"""A refusal about a PERSON is not a rejection of an application — issue #522.

"Unfortunately we were unable to confirm your student status. During the review
process …" is a discount-eligibility refusal. It has nothing to do with a job,
and the classifier scored it ``rejection`` 0.70: the review queue, under a
suggestion for a company the reader never applied to.

WHAT IT MATCHED, AND WHY THAT IS THE WHOLE BUG. Exactly one pattern:
``unfortunately.{0,50}(not|won't|will not|unable)`` in ``REJECTION.strong``,
+3 from the body against 0 in every other category. "unfortunately", "unable
to", "review process", "declined", "was unsuccessful" describe ANY negative
determination; nothing in the rules layer asked what KIND. That is a genre
question, and this file is about the answer to it.

WHY THE FIX IS NOT IN ``_NOISE_NEGATIVES``, which is where the issue proposed
it and where its siblings (``your course``, the OTP set, the commerce set) all
live. Membership there is what lets a strong BODY match outrank a genre filter
— and the strong body match on this mail IS ``unfortunately … unable``. So the
exemption fires on exactly the message the filter is for.
:func:`test_the_filter_is_inert_inside_the_noise_negatives` runs both arms and
is the executable form of that claim; it is #521's finding one category over.

BOTH WAYS ROUND. Every refusal below has a twin one noun away that is a real
rejection and must keep its verdict, because a family of refusals alone is
green for a filter that deletes the category. The corpus family
``eligibility-verification`` in ``tests/corpus_independent/generate.py`` is the
same split at 120 cases; this file holds the shapes that corpus cannot show —
the confidence COST (its twins arrive over an ATS relay, and the +0.05 bonus
puts the cost back), and the wording the defect does not reach at all.

Every employer, sender and body here is invented. The real message is not
reproduced, per #593.
"""

from __future__ import annotations

import re

import pytest

from jobtracker.classifier import rules as rules_module
from jobtracker.classifier.rules import PATTERNS, RulesClassifier
from jobtracker.cloud import pipeline
from jobtracker.cloud.pipeline import resolve_employer
from jobtracker.database.models import EmailCategory

# Instantiated directly rather than through get_rules_classifier(): the module
# singleton would make this file's behaviour depend on what ran before it.
CLASSIFIER = RulesClassifier()

#: The filter this file is about, read out of the definition site rather than
#: restated. A copy here would pass for a pattern that had been edited away.
#:
#: TOLERANT ON PURPOSE, with :func:`test_the_filter_is_where_it_says_it_is`
#: carrying the presence claim. A bare ``next()`` raises at import when the
#: pattern is deleted, and every test in the file then ERRORS — which reds, but
#: says "collection failed" rather than "the refusal is a rejection again". The
#: deletion mutation has to produce the second message to be worth running.
#: ``(?!)`` is the empty negative lookahead: it matches nothing, anywhere.
_NEVER = r"(?!)"
FILTER = next(
    (p for p in PATTERNS[EmailCategory.REJECTION].negative if p.startswith(r"\b(?:kyc|")),
    _NEVER,
)


def test_the_filter_is_where_it_says_it_is() -> None:
    """The presence claim, so deleting the pattern reds something that names it."""
    assert FILTER is not _NEVER, (
        "no #522 filter in PATTERNS[REJECTION].negative. Every other assertion "
        "in this file is now being made against a classifier that has no genre "
        "filter for eligibility and identity verification at all."
    )


def classify(subject: str, body: str, sender: str):
    return CLASSIFIER.classify(subject=subject, body=body, sender_email=sender)


# ---------------------------------------------------------------------------
# The refusals: a determination about a person, in a rejection's vocabulary
# ---------------------------------------------------------------------------

#: ``(label, subject, sender, body)``. Every one of these scored ``rejection``
#: 0.70 before the filter existed — measured, not assumed; the deletion
#: mutation in this file's docstring for
#: :func:`test_the_refusals_come_back_without_the_pattern` is what keeps that
#: true.
REFUSALS = [
    pytest.param(
        "We need more information to approve your Student status",
        "verify@verifyfast.example",
        "An update on verifying your eligibility. Thank you for uploading your "
        "documentation for confirmation. Unfortunately we were unable to confirm "
        "your status. During the review process it was not possible to match the "
        "document you sent.",
        id="student-status",
    ),
    pytest.param(
        "We could not verify your address",
        "no-reply@addrcheck.example",
        "Unfortunately we were unable to verify your address. Our review process "
        "could not match the proof of address you uploaded, so your submission "
        "was declined. Please upload a clearer document to continue.",
        id="proof-of-address",
    ),
    pytest.param(
        "Your identity check was unsuccessful",
        "compliance@ledgerpay.example",
        "Thank you for submitting your documents for our know your customer "
        "checks. Unfortunately we could not complete your KYC review, so the "
        "submission was not approved. You may try again with a clearer photo.",
        id="kyc",
    ),
    pytest.param(
        "Identity verification declined",
        "trust@parcelhold.example",
        "Unfortunately we are unable to complete identity verification for your "
        "account. During the review process the document you sent could not be "
        "read, so the request was declined.",
        id="identity-verification",
    ),
    pytest.param(
        "Your account recovery request was declined",
        "support@mailnest.example",
        "Unfortunately we could not complete your account recovery request. The "
        "review process was unable to match the details you provided against the "
        "account on file.",
        id="account-recovery",
    ),
    pytest.param(
        "Student verification: more information needed",
        "students@campusverify.example",
        "Unfortunately we were unable to confirm your student status from the "
        "document you uploaded. Our review process needs a dated enrolment letter "
        "before the discount can be applied.",
        id="student-verification",
    ),
]


@pytest.mark.parametrize(("subject", "sender", "body"), REFUSALS)
def test_a_verification_refusal_is_not_a_rejection(
    subject: str, sender: str, body: str
) -> None:
    """None of these may reach the review queue as a suggested rejection.

    ``REVIEW_FLOOR`` and not merely "is not REJECTION": a wrong verdict under
    the floor is dropped, and dropping mail that is not job mail is the correct
    outcome. What must not happen is a rejection SUGGESTION for a company the
    reader never applied to.
    """
    result = classify(subject, body, sender)

    assert result.category != EmailCategory.REJECTION, (
        f"{subject!r} is still scored a rejection at {result.confidence:.2f}. "
        f"Matched: {result.matched_patterns}"
    )
    assert result.confidence < pipeline.REVIEW_FLOOR


@pytest.mark.parametrize(("subject", "sender", "body"), REFUSALS)
def test_the_sender_would_have_named_a_company(
    subject: str, sender: str, body: str
) -> None:
    """WHY the verdict is the only thing standing in the way.

    ``resolve_employer`` reads a corporate name straight off these sender
    domains, so a refusal that cleared ``AUTO_FILE_GATE`` would mint a card for
    a company that was never applied to. Pinned rather than fixed: the employer
    resolver is right to name what it sees, and #522 is a classification bug.
    """
    assert resolve_employer(sender, subject, None) is not None


# ---------------------------------------------------------------------------
# The other way round: one noun away, and still a rejection
# ---------------------------------------------------------------------------

#: ``(subject, sender, body)`` — a real rejection whose wording sits one noun
#: from a refusal above. Each scored ``rejection`` at 0.90 or better BEFORE the
#: filter existed, which is what makes it a control rather than a case that
#: would pass on an empty classifier.
TWINS = [
    pytest.param(
        "Update on your application to Marlowcastle Systems",
        "no-reply@marlowcastle.example",
        "Unfortunately we were unable to verify your references for the Data "
        "Engineer role, so we are not moving forward with your application at "
        "Marlowcastle Systems.",
        id="references-not-identity",
    ),
    pytest.param(
        "Your Brightfen Labs application",
        "no-reply@brightfen.example",
        "Your background check is complete. Unfortunately we are unable to "
        "proceed with your application for the Platform Engineer position at "
        "Brightfen Labs.",
        id="background-check-not-address-verification",
    ),
    pytest.param(
        "Thank you from Quillstone Data",
        "no-reply@quillstone.example",
        "Unfortunately we were unable to verify your employment history, and we "
        "will not be proceeding with your candidacy for the Backend Engineer "
        "role at Quillstone Data.",
        id="employment-history-not-proof-of-identity",
    ),
    pytest.param(
        "Your application to the Fernbrook Student Engineering Programme",
        "no-reply@fernbrook.example",
        "Thank you for applying to the Fernbrook Student Engineering Programme. "
        "Unfortunately we are unable to offer you a position on this year's "
        "programme and will not be moving forward with your application.",
        id="student-programme-not-student-status",
    ),
    pytest.param(
        "Update on your Halewood Systems application",
        "no-reply@halewood.example",
        "Thank you for submitting your documents. Unfortunately, after review, "
        "we are not moving forward with your candidacy for the Site Reliability "
        "Engineer position at Halewood Systems.",
        id="documents-not-proof-of-address",
    ),
]


@pytest.mark.parametrize(("subject", "sender", "body"), TWINS)
def test_the_twin_one_noun_away_is_still_a_rejection(
    subject: str, sender: str, body: str
) -> None:
    """The half that a refusal-only family cannot check.

    "verify your references", "background check", "employment verification",
    "student engineering programme" and "submitting your documents" are what
    genuine job mail calls the same act. A filter wide enough to swallow one of
    them would send a real rejection to ``other`` 0.50, where the pipeline
    destroys it silently — the worst failure this product has.
    """
    result = classify(subject, body, sender)

    assert result.category == EmailCategory.REJECTION, (
        f"{subject!r} stopped being a rejection: {result.category.value} at "
        f"{result.confidence:.2f}. Matched: {result.matched_patterns}"
    )
    assert result.confidence >= pipeline.REVIEW_FLOOR


# ---------------------------------------------------------------------------
# The twins that are actually directional
# ---------------------------------------------------------------------------
#
# THE SIX ABOVE DO NOT GRADE A WIDENING, and that is measured rather than
# suspected. Widen the filter's object slot to `verify your \w+` — which does
# then match "verify your references" — and all six still pass: each carries
# TWO strong patterns, so -5 leaves 4, which is `winner_score >= 4 and margin
# >= 2` and lands on 0.80, over `REVIEW_FLOOR`. A control that survives the
# mutation it was written for is not a control (#455's shape).
#
# What is directional is a rejection sitting on the LOWEST rung the classifier
# has: one strong body match, score 3, confidence exactly 0.70. That is also
# the shape #521 named as the worst failure this pipeline has — a
# weak-but-genuine message that a single -5 takes to `other` 0.50, under
# `REVIEW_FLOOR`, where nothing is shown to anyone. Each one below sits one
# noun from a DIFFERENT arm of the filter's alternation, so a widening of any
# arm reds here and names itself.

WEAK_TWINS = [
    pytest.param(
        "Update on your Marlowcastle Systems application",
        "no-reply@marlowcastle.example",
        "Thank you for the documents you sent. Unfortunately we were unable to "
        "verify your references, so we cannot take your application any further.",
        id="arm-verify-your-OBJECT",
    ),
    pytest.param(
        "Update on your Quillstone Data application",
        "no-reply@quillstone.example",
        "Our employment verification came back incomplete. Unfortunately we are "
        "unable to take things any further with you for this opening.",
        id="arm-OBJECT-verification",
    ),
    pytest.param(
        "Update on your Halewood Systems application",
        "no-reply@halewood.example",
        "We could not confirm your eligibility to work in this country. "
        "Unfortunately we are unable to take your candidacy further.",
        id="arm-that-does-not-exist-eligibility",
    ),
    pytest.param(
        "Update on your Fernbrook application",
        "no-reply@fernbrook.example",
        "Unfortunately we could not place you on the Fernbrook student "
        "engineering programme this year, and your application is now closed.",
        id="arm-student-status",
    ),
    pytest.param(
        "Update on your Ashvale Robotics application",
        "no-reply@ashvale.example",
        "We have reviewed the proof of experience you sent. Unfortunately we are "
        "unable to take your candidacy further for this opening.",
        id="arm-proof-of-OBJECT",
    ),
]


@pytest.mark.parametrize(("subject", "sender", "body"), WEAK_TWINS)
def test_a_rejection_on_the_lowest_rung_survives_the_filter(
    subject: str, sender: str, body: str
) -> None:
    """0.70 exactly, and one -5 would destroy it.

    ``== 0.70`` and not ``>= REVIEW_FLOOR``: the whole value of these cases is
    that they have no slack. If one of them ever gains a second strong match it
    stops being able to fail, and pinning the rung is what makes that visible
    the day it happens rather than the day a widening ships.
    """
    result = classify(subject, body, sender)

    assert result.category == EmailCategory.REJECTION, (
        f"{subject!r} was destroyed: {result.category.value} at "
        f"{result.confidence:.2f}. A widened filter took a genuine rejection "
        f"below REVIEW_FLOOR, where the pipeline shows it to nobody. "
        f"Matched: {result.matched_patterns}"
    )
    assert result.confidence == pytest.approx(pipeline.REVIEW_FLOOR), (
        "this case is only a control while it sits ON the floor with a single "
        f"strong match; it is now {result.confidence:.2f}"
    )


# The cost, measured on the one shape that pays it.
_COST_SUBJECT = "Update on your Ashvale Robotics application"
_COST_SENDER = "no-reply@ashvale.example"
_COST_BODY = (
    "We have completed identity verification for your candidate profile. After "
    "careful consideration we have decided not to move forward with your "
    "application for the Robotics Engineer role at Ashvale Robotics. We wish "
    "you the best in your search."
)


def test_what_the_filter_costs_a_rejection_that_carries_its_words() -> None:
    """A real rejection that DOES say "identity verification" still auto-files.

    This is the bound, not a near-miss: the message carries the filter's own
    vocabulary and a full verdict, so it pays the -5 in full. 12 - 5 = 7, which
    is still ``winner_score >= 6 and margin >= 3`` — 0.95 -> 0.90, over
    ``AUTO_FILE_GATE``.

    The corpus family cannot show this. Its twins arrive over an ATS relay and
    the +0.05 sender bonus takes 0.90 straight back to 0.95, so the cost is
    invisible there and is pinned here instead, off-relay, where it shows.
    """
    result = classify(_COST_SUBJECT, _COST_BODY, _COST_SENDER)

    assert result.category == EmailCategory.REJECTION
    assert result.confidence >= pipeline.AUTO_FILE_GATE
    assert result.confidence == pytest.approx(0.90), (
        "the cost of the filter on this shape has moved; it was 0.95 before "
        "#522 and 0.90 after"
    )


# ---------------------------------------------------------------------------
# What this file does NOT cover, said rather than implied
# ---------------------------------------------------------------------------


def test_the_defect_is_one_pattern_and_this_wording_never_reached_it() -> None:
    """A refusal in the same genre that was ALREADY ``other``, kept as a limit.

    The whole defect is the reach of ONE pattern's window. 68 characters sit
    between "Unfortunately" and the negation here, ``.{0,50}`` does not stretch
    that far, and the message scores no strong or weak pattern in any category
    — so it was ``other`` 0.50 before the filter existed and would be ``other``
    0.50 with the filter deleted.

    IT NAMES NO PHRASE THE FILTER MATCHES, and that is deliberate rather than
    incidental. The first draft of this case said "know your customer" and
    "identity verification", which made it green for TWO independent reasons at
    once and let the docstring's claim — that the filter is not what makes it
    pass — go unchecked. With no phrase in common there is exactly one cause.

    It is here because a family of wordings like this one would grade nothing
    at all, and that is worth an assertion rather than a comment.
    """
    body = (
        "Thank you for uploading your documents. Unfortunately, following a "
        "careful examination of everything you sent us, we were not able to "
        "complete our checks, and the request was declined during our review "
        "process."
    )
    assert not re.search(FILTER, body, re.IGNORECASE)
    result = classify("Your submission was declined", body, "checks@parcelhold.example")

    assert result.category == EmailCategory.OTHER
    assert result.confidence == pytest.approx(0.50)


@pytest.mark.parametrize(
    "phrase",
    [
        "eligibility",
        "background check",
        "employment verification",
        "reference check",
        "work authorization",
        "verification",
    ],
)
def test_the_words_job_mail_uses_were_left_out(phrase: str) -> None:
    """The exclusions are asserted, not just described in a comment.

    Each of these belongs to this genre in ordinary speech AND to real job mail
    — "eligibility to work", an offer-stage background check, a reference
    check. Putting any of them in the filter would take a genuine rejection
    that mentions one below ``REVIEW_FLOOR``. The comment beside the pattern in
    ``rules.py`` says so; this is what makes the claim checkable.
    """
    assert not re.search(FILTER, phrase, re.IGNORECASE), (
        f"{phrase!r} now matches the #522 filter. It appears in genuine job "
        "mail, so a rejection carrying it would lose 5 points it needs."
    )


# ---------------------------------------------------------------------------
# The placement is load-bearing, and it is proved by running the other arm
# ---------------------------------------------------------------------------


def test_the_filter_is_inert_inside_the_noise_negatives(monkeypatch) -> None:
    """The measurement that overrides #522's own proposal.

    The issue asked for this in ``_NOISE_NEGATIVES``, beside ``your course``
    and the OTP set. Membership there means a strong BODY match may outrank the
    negative — and the strong body match on this mail is
    ``unfortunately.{0,50}(not|…)`` itself, so ``has_strong_body`` is True for
    ``rejection`` and the exemption fires on exactly the message the filter
    exists for.

    Both arms, on the reported shape:

        in `_NOISE_NEGATIVES`   [NEGATIVE-OUTRANKED]  rejection 0.70
        out of it               [NEGATIVE]            other     0.50

    Compiling a fresh classifier inside the monkeypatch is required: the
    exemption is read at classify time from the frozenset, but a classifier
    built before the patch holds its own compiled lists.
    """
    subject, sender, body = (
        "We need more information to approve your Student status",
        "verify@verifyfast.example",
        "An update on verifying your eligibility. Thank you for uploading your "
        "documentation for confirmation. Unfortunately we were unable to confirm "
        "your status. During the review process it was not possible to match the "
        "document you sent.",
    )

    assert FILTER not in rules_module._NOISE_NEGATIVES

    monkeypatch.setattr(
        rules_module,
        "_NOISE_NEGATIVES",
        frozenset(rules_module._NOISE_NEGATIVES | {FILTER}),
    )
    outranked = RulesClassifier().classify(subject=subject, body=body, sender_email=sender)

    assert outranked.category == EmailCategory.REJECTION, (
        "the exemption no longer makes this filter inert. If `has_strong_body` "
        "has changed shape, the placement argument in rules.py needs re-running "
        "rather than the assertion needs relaxing."
    )
    assert f"[NEGATIVE-OUTRANKED] {FILTER}" in outranked.matched_patterns
