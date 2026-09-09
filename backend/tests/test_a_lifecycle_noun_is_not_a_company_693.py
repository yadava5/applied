"""A sender display name that names a MESSAGE must not become an employer.

#535 closed this vocabulary on the SUBJECT path: `resolve_employer` was minting
companies called Invitation, Decision and Sorry out of ordinary ATS subject
lines and auto-filing them. The sender DISPLAY NAME is a second door onto the
same board, and the same words walked back in through it. Measured on `main` at
`b75f7909`, sender `no-reply@sendgrid.example`:

    display "Reminder"        -> ('reminder', 'Reminder')
    display "Invitation"      -> ('invitation', 'Invitation')
    display "Assessments"     -> ('assessments', 'Assessments')
    display "Decision"        -> ('decision', 'Decision')
    display "Congratulations" -> ('congratulations', 'Congratulations')

Two of those five are named in #535's own title.

WHY THE GENERIC-TEAM NAMES WERE ALREADY SAFE and these were not: "Talent Team",
"Recruiting" and "Notifications" are in `_COMPANY_STOPWORDS`; the message nouns
were in no set the display-name path consults. It is a vocabulary gap, not a
mechanism gap, which is why the fix is a set and not a new rule.

THE COST IS ASSERTED HERE RATHER THAN LEFT TO BE DISCOVERED. On this path the
token reaching `_valid_company_token` is the LEADING WORD of the display name,
so refusing this vocabulary also refuses an employer whose name BEGINS with one
of these words — `test_the_cost_of_the_refusal_is_a_leading_word` pins that. It
is #535's own trade: a refusal reaches the review queue and asks, a mint files a
card named "Reminder" and asks nobody.

THE INDEPENDENT CORPUS CANNOT EXPRESS ANY OF THIS. Its employers are invented
two-word brands, so no case carries a display name that is a message noun, and
`resolve_employer` returns None for exactly 403 cases before this change and 403
after. That is #531's shape again: a defect the graded corpus is structurally
unable to see, which is why the evidence here is the product's own function
called directly.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud import pipeline

#: A generic ESP on a RESERVED domain, so `docs/TEST_DATA_POLICY.md`'s real-domain
#: carve-out is not needed here — which was
#: checked rather than assumed: `resolve_employer` keys the relay test on the
#: domain BRAND, not the registrable domain, so `sendgrid.example` and
#: `sendgrid.net` behave identically here — both refuse to read an employer out
#: of the domain and fall through to the sender display name, which is the path
#: this file is about. A neutral reserved domain would NOT do: `relay.example`
#: resolves ('relay', 'Relay') from the domain itself and never reaches the
#: display name at all, so the brand has to be one the relay set carries.
RELAY = "no-reply@sendgrid.example"

#: The five reproduced above, plus the rest of the vocabulary. Each one is a
#: display name a transactional sender really uses.
MINTED_BEFORE = [
    "Invitation",
    "Reminder",
    "Assessments",
    "Assessment",
    "Decision",
    "Congratulations",
    "Screening",
    "Alerts",
    "Scheduling",
]


@pytest.mark.parametrize("display", MINTED_BEFORE)
def test_a_message_noun_is_not_an_employer(display: str) -> None:
    """The defect. Every one of these minted a company before the fix."""

    assert pipeline.resolve_employer(RELAY, "an update", display) is None, (
        f"display name {display!r} on a relay resolved an employer; it names a "
        "message, not a company, and a card built from it is #535's defect on "
        "the sender-name path"
    )


def test_a_real_employer_on_the_same_relay_still_resolves() -> None:
    """THE CONTROL, and it is the whole reason the set is not wider.

    A refusal that also refused ordinary company names would be a worse defect
    than the one being fixed, and it would be invisible: nothing on the board
    says "a card was not created". The same sender, the same subject, an
    ordinary two-word brand.
    """

    assert pipeline.resolve_employer(RELAY, "an update", "Northwind Labs") == (
        "northwind",
        "Northwind Labs",
    )
    # And a single-word brand, because the refusal above is a single-word test
    # and a control that only used two words could not tell the two apart.
    assert pipeline.resolve_employer(RELAY, "an update", "Handshake") == (
        "handshake",
        "Handshake",
    )


def test_the_cost_of_the_refusal_is_a_leading_word() -> None:
    """THE TRADE, pinned so it cannot be forgotten or later called a surprise.

    On this path `_valid_company_token` receives the LEADING WORD of the display
    name, not the whole of it — traced through the function rather than assumed
    — so an employer whose name begins with a message noun is refused too.
    "Assessment Systems Corporation" is a real shape and it resolved
    ('assessment', 'Assessment Systems Corporation') before this change.

    That is the direction #535 already chose for the same words on the subject
    path, and the next test measures why it is the cheap one.
    """

    assert pipeline.resolve_employer(
        RELAY, "an update", "Assessment Systems Corporation"
    ) is None


def test_a_refused_display_name_still_reaches_a_person() -> None:
    """The refusal must ASK, not drop — otherwise it trades a bad card for silence.

    `hold_reason` is the read path's own answer to "why is this in the queue",
    and it is derived from the same `resolve_employer` the sync used rather than
    from a second reading. Both of its answers here put the row in front of a
    person; which one depends on whether the body names the company in a shape
    `employer_named_in_body` can read.
    """

    invited = "You have been invited by Northwind Labs to complete an assessment."
    assert pipeline.hold_reason(
        confidence=0.95,
        subject="Assessment invitation",
        sender_email=RELAY,
        sender_name="Reminder",
        snippet=invited,
        category="assessment",
    ) == pipeline.HOLD_CONFIRM_EMPLOYER

    assert pipeline.hold_reason(
        confidence=0.95,
        subject="Assessment invitation",
        sender_email=RELAY,
        sender_name="Reminder",
        snippet="Thank you for applying.",
        category="assessment",
    ) == pipeline.HOLD_NO_EMPLOYER


def test_the_refusal_is_the_set_and_not_something_else() -> None:
    """THE MUTATION CONTROL. Take a word out and its display name mints again.

    Without this the parametrized test above would pass for any reason at all —
    a sender the resolver happened to refuse, a subject that named nothing — and
    would keep passing if `_MESSAGE_NOUNS` were emptied. Removing exactly one
    word must restore exactly that one defect and leave the rest refused.
    """

    without = pipeline._MESSAGE_NOUNS - {"reminder"}
    original = pipeline._MESSAGE_NOUNS
    try:
        pipeline._MESSAGE_NOUNS = without
        assert pipeline.resolve_employer(RELAY, "an update", "Reminder") == (
            "reminder",
            "Reminder",
        ), "removing the word did not restore the defect, so the set is not what refuses it"
        assert pipeline.resolve_employer(RELAY, "an update", "Invitation") is None
    finally:
        pipeline._MESSAGE_NOUNS = original
    assert pipeline.resolve_employer(RELAY, "an update", "Reminder") is None
