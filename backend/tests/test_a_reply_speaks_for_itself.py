"""THE CLASSIFIER READS WHOSE WORDS THEY ARE.

Issue #441, found by the 10,040-message adversarial corpus and confirmed
against the owner's real mailbox. Two mechanisms, one defect:

  · QUOTED HISTORY WAS SCORED AS THIS MESSAGE'S OWN. A reply carries the
    message it replies to, and the scoring walk had no notion of authorship. In
    the corpus, 200 of 200 follow-ups that quote their own confirmation read as
    ``applied``, so an interview invitation never advanced the card it belonged
    to. It is also the mechanism behind #417: a withdrawal that quotes the
    offer it is withdrawing scores the offer, 164 of 260.

  · A REPLY'S SUBJECT WAS SCORED AS A HEADLINE. A strong subject match is worth
    +6, double a body match, because a sender who puts the verdict in the
    subject means it. Clients copy the subject onto every reply, so
    "Re: Thank you for applying to X" is what the interview invitation, the
    rejection and the scheduling note in that thread ALL look like. The doubler
    handed every one of them to ``applied`` before a word of the body was read.

WHAT MUST NOT BREAK is half this file. The quote is very often the only place
the ROLE appears, so a fix that hides it from identity extraction repairs
classification by breaking grouping. And a bare forward — "fyi" over a quoted
rejection — has written nothing readable, so scoring only its own words scores
nothing at all.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import (
    _MIN_ASSERTED_CHARS,
    asserted_text,
    get_rules_classifier,
    strip_quoted_history,
)
from jobtracker.cloud.pipeline import (
    AUTO_FILE_GATE,
    REVIEW_FLOOR,
    role_from_message,
)
from jobtracker.database.models import EmailCategory

ATS = "no-reply@greenhouse.io"

QUOTED_INVITE = (
    "Hi Ayush, Following up on the below — we would like to invite you to "
    "interview next week. Are you available Thursday?\n\n"
    "On Tuesday, Cedarhollow Systems Recruiting wrote:\n"
    "> Hi Ayush, Thank you for applying to the Backend Engineer position at\n"
    "> Cedarhollow Systems. Your application has been received.\n"
)

QUOTED_WITHDRAWAL = (
    "Hi Ayush, We are sorry to say we must withdraw the offer of employment "
    "extended to you last week. The role has been closed.\n\n"
    "On Monday, Cedarhollow Systems Talent wrote:\n"
    "> Hi Ayush, We are delighted to extend you an offer to join\n"
    "> Cedarhollow Systems as a Backend Engineer.\n"
)


@pytest.fixture()
def rules():
    return get_rules_classifier()


# ── the quote is not this message's claim ────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        QUOTED_INVITE,
        # No attribution line at all: some clients write only the ``>``.
        "We would like to invite you to interview next week.\n"
        "> Thank you for applying to the Backend Engineer position.\n",
        "We would like to invite you to interview next week.\n\n"
        "-----Original Message-----\n"
        "Thank you for applying to the Backend Engineer position.\n",
        "We would like to invite you to interview next week.\n\n"
        "Begin forwarded message:\n"
        "Thank you for applying to the Backend Engineer position.\n",
    ],
)
def test_the_quote_is_dropped_whatever_the_client_marks_it_with(body: str) -> None:
    kept = strip_quoted_history(body)
    assert "interview" in kept
    assert "Thank you for applying" not in kept, (
        f"the quote survived: {kept!r}. Four clients, four markers, and a "
        "reply that keeps its history is scored as if it wrote it."
    )


def test_a_reply_inside_its_own_confirmation_thread_is_not_a_confirmation(
    rules,
) -> None:
    """The corpus family, as one assertion. 200 of 200 before the fix."""

    result = rules.classify(
        "Re: Thank you for applying to Cedarhollow Systems", QUOTED_INVITE, ATS
    )
    assert result.category is not EmailCategory.APPLIED, (
        f"a follow-up in a confirmation thread read as {result.category.value} "
        "at "
        f"{result.confidence}. Every invitation a recruiter sends by replying "
        "to their own acknowledgement lands on this, and the card never "
        "advances past applied."
    )


def test_a_withdrawal_that_quotes_the_offer_is_not_an_offer(rules) -> None:
    """#417's mechanism. The mail's own words withdraw; the quote extends."""

    result = rules.classify(
        "Re: Your offer from Cedarhollow Systems", QUOTED_WITHDRAWAL, ATS
    )
    assert result.confidence < AUTO_FILE_GATE, (
        f"a withdrawal was auto-filed as {result.category.value} at "
        f"{result.confidence}. This is the only error in the corpus that "
        "asserts something FALSE about someone's life rather than leaving them "
        "where they were, and it reached the board without asking."
    )
    # STATED AS "NOT AUTO-FILED" AND NOT AS "READ AS A REJECTION", because the
    # second is not true yet and this file will not claim it. Stripping the
    # quote takes the corpus family from 164 wrong to 0 wrong and 260
    # ABSTAINED: the product stops asserting an offer nobody made, and starts
    # asking. Reading it correctly needs withdrawal vocabulary the rules do not
    # have ("withdraw the offer", "rescind"), which is what remains of #417.


def test_the_words_that_reach_the_classifier_are_only_this_sender_s(rules) -> None:
    """Stated on the text rather than the verdict, so it cannot pass by luck."""

    kept = asserted_text(QUOTED_WITHDRAWAL)
    assert "withdraw the offer" in kept
    assert "delighted to extend" not in kept


# ── what must not break ──────────────────────────────────────────────────────


def test_identity_still_reads_the_whole_message() -> None:
    """THE CONSTRAINT THAT SHAPES THE FIX.

    The reply names no role. The quote does. Role extraction reads the raw
    snippet and must keep doing so — a fix that put extraction behind this seam
    would repair classification by breaking the grouping that decides which
    card a message lands on, which is a strictly worse trade.
    """

    assert "Backend Engineer" not in strip_quoted_history(QUOTED_INVITE)
    assert (
        role_from_message(
            "Re: Thank you for applying to Cedarhollow Systems", QUOTED_INVITE
        )
        == "Backend Engineer"
    ), (
        "the role was lost with the quote. Identity must see the whole "
        "message; only scoring loses the history."
    )


@pytest.mark.parametrize("filler", ["fyi", "see below", "?" * 20])
def test_a_bare_forward_falls_back_to_its_quote(filler: str) -> None:
    """A reply that says nothing has not said anything.

    Someone forwarding a rejection to themselves with "fyi" over it has written
    no readable words. Scoring only those means scoring nothing, which abstains
    on a message whose verdict is sitting right there. So a reply that adds no
    substance keeps the whole body, and only a reply that SAYS something gets
    to speak over its history.
    """

    assert len(filler) < _MIN_ASSERTED_CHARS
    body = f"{filler}\n\nOn Tuesday, Talent wrote:\n> We regret to inform you.\n"
    assert strip_quoted_history(body) == body


def test_just_enough_of_its_own_words_and_the_quote_goes() -> None:
    """The other side of the same threshold, so it is pinned from both ends.

    Without this pair the constant is a number nothing checks, and it is
    exactly the kind of thing a later reader deletes as arbitrary.
    """

    own = "x" * (_MIN_ASSERTED_CHARS + 1)
    body = f"{own}\n\nOn Tuesday, Talent wrote:\n> We regret to inform you.\n"
    assert strip_quoted_history(body) == own

    thin = "x" * (_MIN_ASSERTED_CHARS - 1)
    body = f"{thin}\n\nOn Tuesday, Talent wrote:\n> We regret to inform you.\n"
    assert strip_quoted_history(body) == body


@pytest.mark.parametrize(
    "body",
    [
        "We wrote to you on Tuesday about your application and have not heard back.",
        "On the question of relocation: we can discuss it on the call.",
        "Thank you for applying to the Backend Engineer position at Cedarhollow.",
    ],
)
def test_prose_that_merely_resembles_an_attribution_is_left_alone(body: str) -> None:
    """The markers are anchored to the start of a line for this reason.

    "We wrote to you on Tuesday" is not an attribution, and a rejection must
    not lose its verdict to a loose match.
    """

    assert strip_quoted_history(body) == body


def test_a_message_with_no_quote_is_returned_untouched() -> None:
    plain = "Hi Ayush, Unfortunately we will not be moving forward. Best of luck."
    assert strip_quoted_history(plain) == plain
    assert asserted_text(plain) == asserted_text(asserted_text(plain))


# ── the subject is about the thread ──────────────────────────────────────────


def test_a_reply_subject_does_not_outvote_the_body(rules) -> None:
    """The doubler, and why a reply does not earn it.

    Same words in the subject, same words in the body, one message a reply and
    one not. The fresh one is a confirmation; the reply is whatever its body
    says it is.
    """

    body = (
        "Hi Ayush, We would like to invite you to interview next week. "
        "Please pick a time that works."
    )
    fresh = rules.classify("Thank you for applying to Cedarhollow", body, ATS)
    reply = rules.classify("Re: Thank you for applying to Cedarhollow", body, ATS)

    assert reply.category is EmailCategory.INTERVIEW, (
        f"a reply carrying an interview invitation read as "
        f"{reply.category.value}: its subject was copied from the "
        "acknowledgement it is replying to."
    )
    assert reply.scores["applied"] < fresh.scores["applied"], (
        "the reply must score the copied subject at LESS than the fresh one, "
        "or nothing has changed"
    )


def test_a_reply_subject_still_counts_for_something(rules) -> None:
    """Demoted, not discarded, and this is the control on that choice.

    A bare "Re: Your application" with an uninformative body carries the
    thread's subject as its only signal. Throwing it away entirely would leave
    the classifier with nothing at all, which is a different failure.
    """

    thin = "Hi Ayush, Please see the attached."
    with_subject = rules.classify("Re: Thank you for applying to Cedar", thin, ATS)
    without = rules.classify("Re: hello", thin, ATS)
    assert with_subject.scores["applied"] > without.scores["applied"]


# ── Microsoft's wording ──────────────────────────────────────────────────────

MICROSOFT_SUBJECT = "Thank you for your application!"
MICROSOFT = [
    ("Software Engineer II", "200045485"),
    ("Customer Experience Engineer", "200049333"),
    ("Software Engineer", "200043070"),
    ("Pre-Training", "200007619"),
    ("Software Engineer-MCAPS Core", "200044387"),
]


def _microsoft(role: str, number: str) -> str:
    return (
        f"Hi Ayush, Thank you for taking the time to submit your application "
        f"for {role} (Job number: {number}). We are glad you are interested in "
        f"a career at Microsoft, and we are here to help"
    )


@pytest.mark.parametrize(("role", "number"), MICROSOFT)
def test_a_microsoft_confirmation_reaches_the_board(
    rules, role: str, number: str
) -> None:
    """Five real messages, none of which could ever be filed.

    ``test_identity_from_microsoft_confirmations.py`` fixed how these four
    would be TOLD APART. It never asked whether any of them arrives: nothing in
    the rules matched Microsoft's wording, in the subject or in the body, so
    each scored 0.80 — four points under the gate — and sat in the review
    queue. The report was "I applied to 4 new Microsoft and a Google
    application, but when I sync it in the app, I'm not getting anything", and
    the identity work answered the second half of that sentence only.

    Message ids, all in the owner's mailbox: 1a02341f84f11426,
    1a023443b385563f, 1a023453e5cd359d, 1a023464635139a1, 19ff98d36594296d.
    """

    result = rules.classify(
        MICROSOFT_SUBJECT,
        _microsoft(role, number),
        "donotreply@email.careers.microsoft.com",
    )
    assert result.category is EmailCategory.APPLIED
    assert result.confidence >= AUTO_FILE_GATE, (
        f"{role} scored {result.confidence}, under the {AUTO_FILE_GATE} gate. "
        "A confirmation naming the act, the role and the requisition number is "
        "not a message a person should have to confirm by hand."
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Thank you for your application! We are delighted to extend you an "
            "offer to join us.",
            EmailCategory.OFFER,
        ),
        (
            "Thank you for your application. We would like to invite you to "
            "interview next week. Please pick a time.",
            EmailCategory.INTERVIEW,
        ),
        (
            "Thank you for your application. Please complete the online "
            "assessment within 5 days.",
            EmailCategory.ASSESSMENT,
        ),
        (
            "Thank you for your application. Unfortunately we are not moving "
            "forward with your candidacy.",
            EmailCategory.REJECTION,
        ),
    ],
)
def test_the_courtesy_opener_does_not_decide_the_category(
    rules, body: str, expected: EmailCategory
) -> None:
    """WHY THE MICROSOFT PATTERN IS WEAK AND NOT STRONG. Measured, not assumed.

    "Thank you for your application" prefixes rejections, invitations and
    offers exactly as happily as it prefixes confirmations: it is a courtesy,
    not a verdict. Tried at ``strong`` first, where a subject match is worth +6
    — three of these four came back ``applied``. At weak it contributes without
    deciding, and Microsoft still clears the gate because its BODY names the
    specific act.
    """

    result = rules.classify("Thank you for your application", body, ATS)
    assert result.category is expected, (
        f"a courtesy opener in the subject overruled the body, which says "
        f"{expected.value}. That is the +6 subject doubler applied to a phrase "
        "that means nothing on its own."
    )
    assert result.confidence >= REVIEW_FLOOR
