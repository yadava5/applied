"""The review queue's hold reason, and the two employer-resolution gaps it exposed.

Three separate defects meet in this file, and they are tested together because
they were found together, from one user report: three rejections sitting in the
review queue labelled "held for a missing employer name" about subject lines
that named the employer in plain English.

  * #507 — the queue INFERRED the reason from ``confidence`` and could not tell
    when the inference was wrong. On the reported rows the guess happened to be
    right, which is why it needed a test rather than a look.
  * #512 — "Thank you for your interest in <Employer>", the standard opening of
    an ATS rejection, resolved to no employer at all.
  * #508 — ``_names_the_relay`` refused any token in ``RELAY_DOMAINS`` whatever
    relay had actually sent the message, so a real rejection from Handshake,
    relayed by Ashby, was unattributable.

The negative controls are the point of this file, not padding. Both fixes
LOOSEN a gate that exists to keep invented employers off the board, and an
invented employer is a worse defect than the one being fixed — so every
loosening here is paired with the case it must still refuse.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline

GREENHOUSE = "no-reply@us.greenhouse-mail.io"
ASHBY = "no-reply@ashbyhq.com"


# --- #512: "thank you for your interest in <Employer>" ------------------------


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("Thank you for your interest in Verkada, Ayush", "Verkada"),
        ("Thanks for your interest in Stripe", "Stripe"),
        ("Thank you so much for your interest in Anthropic", "Anthropic"),
        # The phrase and a role in one subject: the role must not become the
        # employer, and the existing anchored pattern still answers it.
        ("Thank you for your interest in the Backend Engineer role at Verkada", "Verkada"),
    ],
)
def test_a_rejection_opening_names_its_employer(subject: str, expected: str) -> None:
    resolved = pipeline.resolve_employer(GREENHOUSE, subject)
    assert resolved is not None, f"no employer resolved from {subject!r}"
    assert resolved[1] == expected


@pytest.mark.parametrize(
    "subject",
    [
        # THE REGRESSION THIS PATTERN NEARLY SHIPPED. Written with every prefix
        # group optional, it collapsed to a bare "interest in <Capitalized>" and
        # matched job-alert mail, minting employers called "Machine Learning"
        # and "Data Science" — and because `resolve_employer` gates
        # `_qualifies_for_hard_row`, those become CARDS ON THE BOARD.
        "Jobs matching your interest in Machine Learning",
        "We noticed your interest in Data Science",
        "New roles based on interest in Product Design",
        "Your interest in Cloud Engineering",
        # Stopword guards, which is a DIFFERENT guard from the anchor above —
        # these four passed even while the pattern was broken, which is exactly
        # why they were not sufficient as the only controls.
        "Thank you for your interest in our team",
        "Thank you for your interest in the position",
    ],
)
def test_an_interest_phrase_without_a_thank_you_names_no_employer(subject: str) -> None:
    assert pipeline.resolve_employer(GREENHOUSE, subject) is None


# --- #508: a relay brand that is also an employer -----------------------------


def test_a_relay_brand_named_through_a_DIFFERENT_relay_is_an_employer() -> None:
    """Handshake hires, and Ashby carried this one."""
    resolved = pipeline.resolve_employer(
        ASHBY,
        "Update on Associate Software Engineer, Operator Experience with Handshake",
        "Handshake Recruiting Team",
    )
    assert resolved is not None
    assert resolved[1] == "Handshake"


def test_a_relay_brand_named_through_ITS_OWN_relay_is_still_the_courier() -> None:
    """THE CONTROL for the test above, and the one a blanket fix would break.

    ``joinhandshake.com`` yields the brand ``joinhandshake``, which neither
    prefix test relates to ``handshake`` — so without the containment arm this
    resolves to "Handshake" and the precision gate has been opened on exactly
    the garbage it exists to refuse.
    """
    assert (
        pipeline.resolve_employer(
            "no-reply@joinhandshake.com", "Your application", "Handshake"
        )
        is None
    )


@pytest.mark.parametrize(
    "token, brand, is_the_relay",
    [
        ("handshake", "ashby", False),
        ("handshake", "ashbyhq", False),
        ("handshake", "joinhandshake", True),
        ("handshake", "handshake", True),
        # Documented behaviour that must not change: "Ashby" is the courier for
        # ashbyhq.com.
        ("ashby", "ashbyhq", True),
        ("greenhouse", "greenhouse-mail", True),
        ("verkada", "greenhouse-mail", False),
        # No relay identified at all — the vocabulary is the only signal left.
        ("greenhouse", "", True),
        ("verkada", "", False),
        # SHORT relay names are refused whatever carried the message. Without
        # this, "Gem" — a real recruiting CRM, three letters — resolved as an
        # EMPLOYER through Ashby, because the length guard on the containment
        # arm only applied when no relay was known. Three letters is not enough
        # signal to tell a company from a courier.
        ("gem", "ashbyhq", True),
        ("aol", "ashbyhq", True),
        # ...and a LONG relay brand named through another relay still resolves,
        # which is the whole point of the change. Lever is a real company.
        ("lever", "greenhouse-mail", False),
    ],
)
def test_names_the_relay_asks_about_THIS_relay(
    token: str, brand: str, is_the_relay: bool
) -> None:
    assert pipeline._names_the_relay(token, brand) is is_the_relay


# --- #507: the hold reason ----------------------------------------------------


def _reason(**kwargs: object) -> str:
    base = {
        "confidence": 0.95,
        "subject": "Thank you for applying to Verkada",
        "sender_email": GREENHOUSE,
        "sender_name": None,
        "snippet": "",
        "has_proposal": True,
        "sibling_applications": 0,
    }
    base.update(kwargs)
    return pipeline.hold_reason(**base)  # type: ignore[arg-type]


def test_a_gated_row_with_no_nameable_employer_is_the_only_missing_employer() -> None:
    assert _reason(subject="A subject naming nobody") == pipeline.HOLD_NO_EMPLOYER


def test_a_gated_row_that_cannot_be_placed_asks_which_application() -> None:
    """Employer known, role unknown, several applications under it.

    This is the case the old confidence-based guess got WRONG — it scores above
    the gate, so it was told its employer could not be named while the employer
    sat in its own subject line.
    """
    assert (
        _reason(subject="Thank you for your interest in Verkada", sibling_applications=4)
        == pipeline.HOLD_WHICH_APPLICATION
    )


def test_one_application_at_an_employer_is_not_a_which_question() -> None:
    """A question with one possible answer is not a question.

    With a single row the message lands on it regardless, so an unnameable role
    holds nothing up and must not be reported as though it did.
    """
    assert (
        _reason(subject="Thank you for your interest in Verkada", sibling_applications=1)
        != pipeline.HOLD_WHICH_APPLICATION
    )


def test_a_named_role_is_placeable_even_among_several() -> None:
    assert (
        _reason(
            subject="Thank you for applying to Verkada",
            snippet="applying to the Backend Engineer, Alarms role at Verkada",
            sibling_applications=4,
        )
        != pipeline.HOLD_WHICH_APPLICATION
    )


def test_below_the_gate_the_question_is_confidence_not_the_obstacle() -> None:
    """PRECEDENCE. Under the gate the classifier itself was unsure, so the row
    must not be told about an obstacle it never reached."""
    assert _reason(confidence=0.80, subject="A subject naming nobody") == pipeline.HOLD_BELOW_GATE


def test_no_proposal_is_distinct_from_a_weak_one() -> None:
    assert _reason(confidence=0.80, has_proposal=False) == pipeline.HOLD_NO_PROPOSAL


def test_under_the_floor_an_ATS_row_says_why_it_was_kept() -> None:
    assert _reason(confidence=0.55) == pipeline.HOLD_ATS_FLOOR


def test_every_reason_is_one_the_web_knows() -> None:
    """A reason outside the vocabulary renders as silence on the web, so a new
    member added here without adding it there disappears from the UI."""
    for confidence in (0.0, 0.55, 0.70, 0.80, 0.85, 0.95, 1.0):
        for siblings in (0, 1, 4):
            for proposal in (True, False):
                assert (
                    _reason(
                        confidence=confidence,
                        sibling_applications=siblings,
                        has_proposal=proposal,
                    )
                    in pipeline.HOLD_REASONS
                )


def test_a_missing_confidence_is_not_treated_as_confident() -> None:
    """None must not read as 1.0 and send an unscored row down the gated branch."""
    assert _reason(confidence=None, has_proposal=False) == pipeline.HOLD_NO_PROPOSAL
