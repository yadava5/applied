"""Four Microsoft applications must be four applications.

REPORTED FROM LIVE USE on 2026-08-21: "I applied to 4 new Microsoft and a
Google application, but when I sync it in the app, I'm not getting anything."

The sync was healthy. All four confirmations were sitting in the inbox, marked
IMPORTANT, received at 07:38:41, 07:41:09, 07:42:15 and 07:43:23, hours before
the sync ran. Four applications, four roles, four requisition numbers. Not one
produced a row.

The wordings below are the real ones, taken from the mailbox:

    Hi Ayush, Thank you for taking the time to submit your application for
    Software Engineer II (Job number: 200045485). We're glad you're interested
    in a career at Microsoft...

TWO SEPARATE MISSES, and the identity one is the load-bearing half:

  · ``_REQ_ID_PATTERNS`` required the literal word "id". Microsoft writes
    "Job number". So `extract_req_id` returned None for every Microsoft
    confirmation ever received, and identity fell back to the role token.

  · No ``_ROLE_BODY_PATTERNS`` entry matched either. Microsoft puts no article
    before the title and no "position"/"role" keyword after it, so the role
    token was also None. That is why the Microsoft card on the live board has
    an empty ``position``.

With both null, four distinct applications at one employer are
indistinguishable, and `_pick_application` files a message with no identity
onto the employer's existing row.

WHY THE NEGATIVE CONTROLS ARE HALF THIS FILE. A wrong requisition id is
strictly worse than no requisition id: a message with no identity joins the
employer's existing row, while a WRONG id mints a duplicate card for a job
already on the board. "number" is a much weaker token than "id" and appears
all over employer boilerplate, so the prefix is mandatory in the new pattern
and these tests are what hold it mandatory.
"""

from __future__ import annotations

import pytest

from jobtracker.cloud.pipeline import extract_req_id, role_from_message

SUBJECT = "Thank you for your application!"

#: The four real applications, as they arrived.
MICROSOFT = [
    ("Software Engineer II", "200045485"),
    ("Customer Experience Engineer", "200049333"),
    ("Software Engineer", "200043070"),
    ("Pre-Training", "200007619"),
]


def _snippet(role: str, number: str) -> str:
    """Microsoft's confirmation, in the shape Gmail's snippet delivers it."""

    return (
        f"Hi Ayush, Thank you for taking the time to submit your application "
        f"for {role} (Job number: {number}). We're glad you're interested in a "
        f"career at Microsoft, and we're here to help"
    )


@pytest.mark.parametrize(("role", "number"), MICROSOFT)
def test_a_microsoft_confirmation_yields_its_requisition_number(role: str, number: str) -> None:
    assert extract_req_id(SUBJECT, _snippet(role, number)) == number


@pytest.mark.parametrize(("role", "number"), MICROSOFT)
def test_a_microsoft_confirmation_yields_its_role(role: str, number: str) -> None:
    assert role_from_message(SUBJECT, _snippet(role, number)) == role


def test_four_applications_to_one_employer_are_four_identities() -> None:
    """The defect as the user met it, stated as one assertion.

    Before the fix every one of these was ``(None, None)``, so all four
    resolved onto the same row and the board did not change after the sync.
    """

    identities = {
        (role_from_message(SUBJECT, _snippet(role, number)), extract_req_id(SUBJECT, _snippet(role, number)))
        for role, number in MICROSOFT
    }
    assert len(identities) == 4, (
        f"four Microsoft applications collapsed to {len(identities)} identity/identities: "
        f"{sorted(identities)}. They arrived within five minutes of each other at one "
        "employer that already had a row, so a collapse here is invisible on the board."
    )
    assert (None, None) not in identities


@pytest.mark.parametrize(
    "text",
    [
        "Your order number: 100238471 has shipped",
        "Case number 5567123 was opened on your behalf",
        "Call us at number 8005551234 with questions",
        "Tracking number: 992837465521",
        "Invoice no. 44821 is attached",
        "Our support reference 5567123 is closed",
    ],
)
def test_a_bare_number_is_never_a_requisition_id(text: str) -> None:
    """The prefix is mandatory for the weak nouns, and this is what holds it so.

    A false shared id merges two genuinely different applications; a false
    distinct id splits one. Employer boilerplate is full of numbers.
    """

    assert extract_req_id("", text) is None


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        (
            "Thank you for Applying to Amazon!",
            "Your application (ID: 3177934) has been received.",
            "3177934",
        ),
        ("Application received", "Requisition R-4821 confirmed.", "R-4821"),
        ("Job ID 12345", "", "12345"),
    ],
)
def test_the_requisition_shapes_that_already_worked_still_work(
    subject: str, body: str, expected: str
) -> None:
    assert extract_req_id(subject, body) == expected


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        (
            "Thank you for applying to Discord!",
            "Thank you for applying to the Software Engineer position at Discord.",
            "Software Engineer",
        ),
        (
            "Thank you for your interest in SimpliSafe",
            "Thank you for your interest in SimpliSafe and our Software Engineer I- "
            "User Systems position.",
            "Software Engineer I- User Systems",
        ),
        (
            "Thanks for applying",
            "Thank you for applying to our role: Software Engineer I, Storage.",
            "Software Engineer I, Storage",
        ),
    ],
)
def test_the_role_shapes_that_already_worked_still_work(
    subject: str, body: str, expected: str
) -> None:
    """The new body pattern is appended, so it can only fire where the earlier
    ones did not. These three are the wordings whose captures were hardest to
    get right; a regression here means the new pattern is stealing matches."""

    assert role_from_message(subject, body) == expected


def test_one_gmail_thread_can_hold_four_applications() -> None:
    """End to end through the roll-up, with the real delivery shape.

    GMAIL PUT ALL FOUR IN ONE THREAD. The sender and the subject are
    byte-identical across the four messages
    (``donotreply@email.careers.microsoft.com`` / ``Thank you for your
    application!``), so Gmail threaded four unrelated applications together and
    every one of them carries ``thread_id='1a02341f84f11426'``.

    That is the case the whole report turns on, and it is not exotic: a large
    employer sends one identically-titled confirmation per application, and a
    person applies to large employers repeatedly. The thread is a delivery-side
    grouping and must not be allowed to act as identity.

    Before the fix the four yielded ``(None, None)`` each, so they were one
    application in a single thread, at an employer that already had a row.
    """

    from datetime import datetime, timedelta

    from jobtracker.cloud.pipeline import PipelineItem, roll_up_applications

    base = datetime(2026, 8, 21, 7, 38)
    items = [
        PipelineItem(
            message_id=f"m{i}",
            category="applied",
            sender_email="donotreply@email.careers.microsoft.com",
            sender_name="Microsoft Careers",
            subject=SUBJECT,
            received_at=base + timedelta(minutes=offset),
            confidence=0.9,
            # One thread. All four.
            thread_id="1a02341f84f11426",
            snippet=_snippet(role, number),
        )
        for i, ((role, number), offset) in enumerate(zip(MICROSOFT, (0, 3, 4, 5)))
    ]

    rolled = roll_up_applications(items)

    assert len(rolled) == 4, (
        f"four applications in one Gmail thread rolled up into {len(rolled)}. "
        "A thread is how the mail was delivered, not what it is about."
    )
    assert {r.req_id for r in rolled} == {number for _role, number in MICROSOFT}
    assert {r.role for r in rolled} == {role for role, _number in MICROSOFT}
    assert all(len(r.messages) == 1 for r in rolled)
