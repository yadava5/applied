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

import pathlib
import re

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


# --- the three refusals of `_qualifies_for_hard_row`, all modelled -----------
#
# `hold_reason` used to mirror two of the three grounds on which a confident
# message is refused a board row, which is why it needed a fallthrough. These
# pin the third, and pin what the fallthrough is left meaning.


def test_a_confident_follow_up_is_not_held_for_its_employer() -> None:
    """`_qualifies_for_hard_row` excludes ``follow_up`` BY NAME, at any score.

    Before this, such a row reported an employer or role problem it did not
    have — the same class of false lead as #507, just one branch further in.
    """
    assert (
        _reason(subject="Thank you for your interest in Verkada", category="follow_up")
        == pipeline.HOLD_NOT_FILEABLE
    )


@pytest.mark.parametrize("category", ["other", "needs_review"])
def test_a_category_outside_the_lifecycle_is_never_an_employer_problem(category: str) -> None:
    assert (
        _reason(subject="Thank you for your interest in Verkada", category=category)
        == pipeline.HOLD_NOT_FILEABLE
    )


@pytest.mark.parametrize("category", ["applied", "rejection", "offer", "assessment", "interview"])
def test_a_fileable_category_still_reports_the_real_obstacle(category: str) -> None:
    """The CONTROL for the two above.

    Without this pair, a `not_fileable` that fired on everything would satisfy
    them both and the branch would be untested in the direction that matters.
    """
    assert _reason(subject="A subject naming nobody", category=category) == (
        pipeline.HOLD_NO_EMPLOYER
    )


def test_an_absent_category_degrades_to_the_old_behaviour() -> None:
    """`None` means the caller could not say, and must not mint a reason."""
    assert _reason(subject="A subject naming nobody", category=None) == (
        pipeline.HOLD_NO_EMPLOYER
    )


def test_a_confident_row_with_no_proposal_says_so_before_anything_else() -> None:
    """Confident that it cannot tell IS `no_proposal`, not the fallthrough.

    The gate used to be read first, so this state fell past every branch and
    landed on "held, and we can't say why" — a shrug about the one case the
    vocabulary already had an exact word for.
    """
    assert (
        _reason(confidence=0.95, has_proposal=False, subject="Thank you for applying to Verkada")
        == pipeline.HOLD_NO_PROPOSAL
    )


# --- the employer the BODY names --------------------------------------------


def test_a_subject_that_names_nobody_still_asks_about_the_body_name() -> None:
    """#512's third row: the subject carries the role and the candidate, the
    body's first line carries the employer, and the queue denied both."""
    assert (
        _reason(
            subject="Granitethwaitevale Follow-Up for TPU Kernel Engineer | A Candidate",
            snippet=(
                "Hi there, Thank you so much for your interest in Granitethwaitevale "
                "and for the time you have invested in our process."
            ),
        )
        == pipeline.HOLD_CONFIRM_EMPLOYER
    )


def test_no_employer_anywhere_is_still_no_employer() -> None:
    """The CONTROL. `confirm_employer` must not swallow the real case, or the
    only honest "missing employer" left in the vocabulary becomes unreachable
    and #512's sentence is un-provable in the direction it was wrong."""
    assert (
        _reason(subject="A subject naming nobody", snippet="No company is named here at all.")
        == pipeline.HOLD_NO_EMPLOYER
    )


def test_the_body_pass_stops_at_a_full_stop() -> None:
    """A body is prose and a subject is not.

    The shared subject capture reads "…interest in Granitethwaitevale. After
    careful consideration" as a company two words long. The TOKEN would still
    have been right, which is exactly why a token-level assertion could not
    have caught it — and why this one is on the DISPLAY name.
    """
    named = pipeline.employer_named_in_body(
        "Thank you for your interest in Granitethwaitevale. After careful consideration we",
        "no-reply@hire.lever.co",
    )
    assert named is not None
    assert named[1] == "Granitethwaitevale"


@pytest.mark.parametrize(
    "snippet",
    [
        # A ROLE where the company would be. The determiner is what gives it
        # away, and `_COMPANY_STOPWORDS` is what acts on that.
        "Thank you for your interest in the Software Engineer, C# position at Acme",
        "Thank you for your interest in our Associate Software Engineer role",
        # Lowercase — never a company under a case-sensitive capture.
        "Thank you for your interest in potential opportunities with Acme",
        "Thank you for your interest in joining the flock here at Acme",
    ],
)
def test_body_prose_that_is_not_a_company_names_none(snippet: str) -> None:
    """Measured on 40 real messages: these are the shapes that would have been
    dangerous, and none of them matches. Pinned so a later loosening of the
    capture has to argue with them."""
    assert pipeline.employer_named_in_body(snippet, "no-reply@us.greenhouse-mail.io") is None


@pytest.mark.parametrize(
    ("snippet", "sender"),
    [
        ("Thank you for your interest in Ashby and our platform", "no-reply@ashbyhq.com"),
        ("Thank you for your interest in Greenhouse", "no-reply@us.greenhouse-mail.io"),
        ("Thank you for your interest in Lever", "no-reply@hire.lever.co"),
    ],
)
def test_the_body_pass_refuses_to_name_the_courier(snippet: str, sender: str) -> None:
    """Body prose is the weakest signal here, so it gets the strictest fence:
    a capture naming the SENDING relay is refused."""
    assert pipeline.employer_named_in_body(snippet, sender) is None


def test_the_courier_fence_does_not_refuse_a_real_employer(
) -> None:
    """The CONTROL for the fence, and the #508 distinction it must keep.

    A company that also sells recruiting software is still an employer when a
    DIFFERENT relay carries its mail. Refusing this would rebuild #508 inside
    the body pass.
    """
    named = pipeline.employer_named_in_body(
        "Thank you for your interest in Handshake! We have received your application",
        "no-reply@ashbyhq.com",
    )
    assert named is not None
    assert named[0] == "handshake"


def test_the_body_name_never_reaches_the_filing_path() -> None:
    """DISPLAY GRADE, and this is the assertion that keeps it that way.

    `_qualifies_for_hard_row` gates on `resolve_employer`, so if the body pass
    ever leaked into it, the ATS rejection preamble — which is the exact
    population this pattern reads — would start minting board rows. #166
    refused that trade and this is the tripwire on it.
    """
    subject = "Granitethwaitevale Follow-Up for TPU Kernel Engineer | A Candidate"
    snippet = "Thank you so much for your interest in Granitethwaitevale and for the time"

    assert pipeline.employer_named_in_body(snippet, "no-reply@us.greenhouse-mail.io") is not None
    # …and the filing-grade resolver, given the same message, still refuses.
    assert pipeline.resolve_employer("no-reply@us.greenhouse-mail.io", subject, None) is None


def test_a_role_past_the_snippet_is_read_from_the_stored_column() -> None:
    """`identity_role` is written from the FULL body; the snippet is its first
    ~200 characters. Re-deriving from the snippet asks "which application?"
    about a row the sync placed without trouble (#484)."""
    assert (
        _reason(
            subject="Thank you for your interest in Verkada",
            snippet="a body whose title sits past the stored boundary",
            sibling_applications=4,
            stored_role="Embedded Software Engineer, Access Control",
        )
        != pipeline.HOLD_WHICH_APPLICATION
    )


def test_without_the_stored_column_the_same_row_is_unplaceable() -> None:
    """The CONTROL for the line above: it must be the COLUMN doing the work,
    not the subject quietly carrying the role all along."""
    assert (
        _reason(
            subject="Thank you for your interest in Verkada",
            snippet="a body whose title sits past the stored boundary",
            sibling_applications=4,
            stored_role=None,
        )
        == pipeline.HOLD_WHICH_APPLICATION
    )


def test_the_web_knows_every_reason_this_module_can_emit() -> None:
    """THE CROSS-LANGUAGE LOCKSTEP.

    `holdReasonSentence` renders NOTHING for a reason it does not recognise —
    deliberately, so an unknown reason degrades to silence instead of a guess.
    That safety property is also what makes a drift invisible: add a member
    here, forget the web, and the row simply stops explaining itself while
    every suite stays green. This is the only thing that would say so.
    """

    web = (
        pathlib.Path(__file__).resolve().parents[2]
        / "apps"
        / "web"
        / "lib"
        / "dashboard"
        / "review.ts"
    )
    assert web.exists(), f"{web} is missing — the parity guard cannot run"

    source = web.read_text()
    block = source[source.index("export const HOLD_REASONS") : source.index("] as const;")]
    on_the_web = set(re.findall(r'"([a-z_]+)"', block))

    assert on_the_web == set(pipeline.HOLD_REASONS), (
        "the hold-reason vocabularies have drifted — "
        f"backend only: {sorted(set(pipeline.HOLD_REASONS) - on_the_web)}, "
        f"web only: {sorted(on_the_web - set(pipeline.HOLD_REASONS))}"
    )


def test_the_web_knows_every_reason_this_module_can_emit() -> None:
    """THE CROSS-LANGUAGE LOCKSTEP.

    `holdReasonSentence` renders NOTHING for a reason it does not recognise —
    deliberately, so an unknown reason degrades to silence instead of a guess.
    That safety property is also what makes a drift invisible: add a member
    here, forget the web, and the row simply stops explaining itself while
    every suite stays green. This is the only thing that would say so.
    """

    web = (
        pathlib.Path(__file__).resolve().parents[2]
        / "apps"
        / "web"
        / "lib"
        / "dashboard"
        / "review.ts"
    )
    assert web.exists(), f"{web} is missing — the parity guard cannot run"

    source = web.read_text()
    block = source[source.index("export const HOLD_REASONS") : source.index("] as const;")]
    on_the_web = set(re.findall(r'"([a-z_]+)"', block))

    assert on_the_web == set(pipeline.HOLD_REASONS), (
        "the hold-reason vocabularies have drifted — "
        f"backend only: {sorted(set(pipeline.HOLD_REASONS) - on_the_web)}, "
        f"web only: {sorted(on_the_web - set(pipeline.HOLD_REASONS))}"
    )
