"""A CONTACT-FORM AUTORESPONDER IS NOT AN APPLICATION EVENT.

Reported on the owner's real board: a company he had cold-emailed sat in the
review queue as though it were an application update. He had applied to them
separately, days earlier, and that confirmation had already filed its own card
correctly. The queue was asking him about a robot saying "thanks, we got your
message".

THE MECHANISM, reproduced before anything was changed. The mail is a reply to
HIS OWN outreach, so the client copied HIS subject onto it — and his subject
said, in the first person, that he had applied for the role. Scored:

    {applied: 2, everything else: 0}
    [STRONG-SUBJECT] applied.{0,20}(for|to).{0,40}(position|role|job)

One match, on words he wrote himself, and nothing else in the message
contributed at all. That is 0.70 — exactly ``REVIEW_FLOOR`` — so the product
queued it.

THE FIX IS ONE RULE, NOT TWO. The pattern never said WHOSE application it
meant. An employer writes "you applied for the X role"; a candidate writes
"applied for the X role". It matched both, so a first-person sentence was read
as an employer's assertion about the reader. It is anchored in the second
person now, and the pronoun has to run STRAIGHT INTO the verb — cold outreach
says "you" and "your" constantly, so mere proximity is defeated by the exact
text the anchor exists to refuse.

This is NOT the same repair as #348, which demoted
``your application for <Role> at <Company>`` OUT of ``strong``: that phrasing
is a thread subject every reply inherits and it must stay weak, which is why
``your`` is deliberately absent from the anchor. Measured before touching
either: the anchored pattern matches 0 of the 17,260 independent-corpus cases,
and the sibling ``application.{0,20}(for|to)...`` matches 1,695 and is
untouched.

A SECOND RULE WAS MEASURED AND NOT SHIPPED. "Thank you for getting in touch"
acknowledges a message rather than an application, and adding it to
``applied``'s genre filters looked obvious. Inside ``_NOISE_NEGATIVES`` it is
nearly inert — the careers autoresponder it was written for carries "reviewing
applications", a strong BODY match, which exempts it in exactly the case it was
meant to catch. Outside ``_NOISE_NEGATIVES`` it fires, and a weak-but-genuine
confirmation opening with the same courtesy drops SILENTLY. The phrase appears
0 times in the corpus and once in the owner's whole stored mailbox, so neither
risk is measurable; #521 carries it, with the corpus family it needs first.
``rules.py`` says the same beside the list so it is not re-proposed as new.

WHAT MUST NOT BREAK: the real confirmation from the same employer, and the
second-person phrasing an employer actually uses. Both are asserted below
against the same fixtures, so a fix that buys this one by breaking those cannot
pass.

Every fixture here is invented. The shape is the owner's; the words are not.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import get_rules_classifier
from jobtracker.cloud.pipeline import AUTO_FILE_GATE, REVIEW_FLOOR
from jobtracker.database.models import EmailCategory

#: The employer's own contact inbox — a plus-addressed no-reply, NOT an ATS.
CONTACT_INBOX = "info+noreply@haldensystems.example"
ATS = "no-reply@greenhouse.io"

#: The subject is the OWNER'S, quoted back by the reply. First person: it says
#: an application happened, and never says whose.
OUTREACH_REPLY_SUBJECT = (
    "Re: Built an agentic compiler for embedded targets, applied for the "
    "Platform Engineer role"
)

#: A canned acknowledgement of a MESSAGE. Nothing here is about an application.
CONTACT_FORM_ACK = (
    "Thank you for getting in touch with us at Halden Systems! We appreciate "
    "you taking the time to connect with our team. While we aren't always able "
    "to send an individual response to every message, please know that we read "
    "them all."
)

#: The same employer's real confirmation, which filed its own card correctly.
REAL_CONFIRMATION_SUBJECT = "Thanks for applying to Halden Systems!"
REAL_CONFIRMATION_BODY = (
    "Thanks for applying to Halden Systems! We have received your application "
    "for the Platform Engineer position and our team will review it shortly."
)

#: The phrasing an EMPLOYER uses for the same fact — second person, and it must
#: keep scoring after the anchor lands.
EMPLOYER_SECOND_PERSON = (
    "Hi Ayush, you applied for the Platform Engineer position at Halden "
    "Systems on Monday. Here is what happens next."
)

#: THE HARDER OUTREACH SHAPE, and the one that makes the anchor load-bearing on
#: its own. Cold outreach is written TO somebody, so it says "you" and "your"
#: constantly — a pronoun merely NEAR "applied" is therefore no anchor at all,
#: it is the same text the pattern is supposed to refuse. Its body says nothing
#: job-related at all, so the anchor is the ONLY thing standing between this
#: message and the review queue at 0.70.
OUTREACH_REPLY_SUBJECT_SECOND_PERSON = (
    "Re: Loved what your team is building and what you have shipped, applied "
    "for the Platform Engineer role"
)
NEUTRAL_AUTOREPLY = (
    "This mailbox is monitored during business hours. Someone will review your "
    "note and respond if there is a fit."
)


@pytest.fixture()
def rules():
    return get_rules_classifier()


def test_an_autoresponder_to_the_owners_outreach_never_reaches_the_queue(rules):
    """THE DEFECT. Held at 0.70 on one match, in words the owner wrote."""
    result = rules.classify(OUTREACH_REPLY_SUBJECT, CONTACT_FORM_ACK, CONTACT_INBOX)

    assert result.confidence < REVIEW_FLOOR, (
        "a canned reply to the owner's own outreach reached the review queue: "
        f"{result.category} at {result.confidence}. Matched: "
        f"{result.matched_patterns}"
    )


def test_the_first_person_subject_is_not_an_employers_claim(rules):
    """The narrow half: the quoted subject alone must not name a category."""
    result = rules.classify(OUTREACH_REPLY_SUBJECT, "", CONTACT_INBOX)

    assert result.category is not EmailCategory.APPLIED, (
        "a subject the OWNER wrote about his own application was read as the "
        f"employer asserting it: {result.matched_patterns}"
    )


# ── the controls: none of this may be bought by breaking a real confirmation ──


def test_the_same_employers_real_confirmation_still_auto_files(rules):
    result = rules.classify(REAL_CONFIRMATION_SUBJECT, REAL_CONFIRMATION_BODY, ATS)

    assert result.category is EmailCategory.APPLIED
    assert result.confidence >= AUTO_FILE_GATE, (
        f"the genuine confirmation stopped clearing the gate: {result.confidence}"
    )


def test_an_employer_saying_you_applied_still_scores(rules):
    """The anchor keeps the phrasing an employer actually uses."""
    result = rules.classify(
        "An update on your application", EMPLOYER_SECOND_PERSON, ATS
    )

    assert result.category is EmailCategory.APPLIED, (
        f"second-person employer phrasing stopped matching: {result.matched_patterns}"
    )


def test_a_second_person_pitch_does_not_smuggle_the_subject_back_in(rules):
    """Proximity is not an anchor; same-clause contiguity is.

    This subject says "your" and "you have" within a few words of "applied", so
    a pronoun-nearby rule passes it — and cold outreach reads like this
    constantly, which makes it the shape the anchor most has to refuse. The
    body is a neutral away-message with no job wording at all, so nothing else
    can rescue the verdict: if this comes back APPLIED, the anchor is doing no
    work.
    """

    result = rules.classify(
        OUTREACH_REPLY_SUBJECT_SECOND_PERSON, NEUTRAL_AUTOREPLY, CONTACT_INBOX
    )

    assert result.confidence < REVIEW_FLOOR, (
        "a pitch that happens to say 'you' scored as the employer's own claim: "
        f"{result.category} at {result.confidence} — {result.matched_patterns}"
    )
