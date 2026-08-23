"""A Lever confirmation names the title plainly, and it was being walked past.

MEASURED IN THE OWNER'S MAILBOX on 2026-08-23. Ten cards on the live board
carried no position. Pulling all ten FULL BODIES out of Gmail — not the stored
snippet — settled which of them were defects:

  · Google (three cards), IXL, Twitch, Jump Trading and Supabase (two cards)
    name no role ANYWHERE in the body. Google's says only "if your skills and
    experience are a strong match for the role"; Jump's says "a fit for any of
    our open positions". Those eight cards are the product being honest, and a
    rule that filled them in would be inventing data.

  · Palantir and Torc both spell the title out. Two different defects.

THIS FILE IS PALANTIR'S HALF. Its confirmation arrives from
``no-reply@hire.lever.co``, and the title sits at character ~95 — well inside
the ~200 characters the stored snippet holds, so the extractor READ the words
and returned None anyway:

    Hi Ayush, Thank you for submitting your application to be a Software
    Engineer, New Grad at Palantir. Our team is reviewing your application...

None of the four existing ``_ROLE_BODY_PATTERNS`` can see it. There is no
``role:`` label, no article anchoring a trailing "position"/"role" noun, and no
parenthesised requisition to terminate the capture. The title is simply stated
between "to be a" and the employer's own name.

Torc's half is NOT here and is not a pattern problem: its title sits at body
character ~380, and the existing extractor gets it right the moment it is
handed the body. The sync never hands it the body — ``_classify_messages``
gives the classifier the full text and gives the identity resolver
``msg.snippet``. That is a separate, structural fix.

WHY THE NEW RULE IS SAFE, and both halves are mutation-verified below:

  · It is anchored on the application word. "to be a <Title> at <Employer>" is
    ordinary English that usually has nothing to do with applying, and the
    control for it — "we have invited you to be a Mentor at Palantir
    University" — is Title-Case and possessive-free, so neither the article
    tempering nor the possessive guard that protect the older patterns can see
    anything wrong with it. Only the missing verb refuses it.

  · The employer terminates the capture, and must be capitalised. Accepting any
    word after "at" lets "a Software Engineer at a company like Palantir"
    through.

  · It is LAST in the tuple. :func:`role_from_message` returns the first
    pattern that yields a clean role, so this rule can only fire where every
    other rule already found nothing, and cannot alter a capture the board
    already has.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from jobtracker.cloud.pipeline import (
    _ROLE_BODY_PATTERNS,
    _ROLE_TRAILING_REQ,
    PipelineItem,
    _clean_role,
    application_sub_key,
    partition_applications,
    role_from_message,
)


def _lever_item(
    message_id: str,
    thread_id: str,
    subject: str,
    snippet: str,
    category: str,
    received_at: datetime,
) -> PipelineItem:
    """One message as the sync hands it to identity resolution."""

    return PipelineItem(
        message_id=message_id,
        category=category,
        sender_email="no-reply@hire.lever.co",
        subject=subject,
        sender_name="Palantir Technologies",
        received_at=received_at,
        confidence=0.95,
        thread_id=thread_id,
        snippet=snippet,
    )

# The real message, as it arrives. Gmail's snippet is ~200 characters and this
# is what it holds; the title is inside it.
PALANTIR_CONFIRMATION = (
    "Hi Ayush, Thank you for submitting your application to be a Software "
    "Engineer, New Grad at Palantir. Our team is reviewing your application "
    "and will be in touch if we think you're a potential match"
)

# Its rejection, four days later, from the same Lever address. This one the
# older patterns already read — from the SUBJECT — and the two have to agree or
# the rejection opens a second card instead of closing the first.
PALANTIR_REJECTION_SUBJECT = (
    "Thank you from Palantir Technologies - Ayush Yadav - Software Engineer, New Grad"
)


def test_the_lever_confirmation_names_its_role() -> None:
    assert role_from_message("Your application has been received!", PALANTIR_CONFIRMATION) == (
        "Software Engineer, New Grad"
    )


def test_the_confirmation_and_its_rejection_stay_one_application() -> None:
    """The card gains a title WITHOUT its rejection losing its way to it.

    This is the regression the rule could plausibly have caused and does not.
    Before it, both Palantir messages resolved to ``None`` and rule 3 of
    :func:`partition_applications` — "names no role, employer has exactly one
    cluster" — carried the rejection onto the confirmation's row. Giving the
    confirmation an identity could have left the rejection stranded against a
    cluster it no longer matched.

    It does not: the rejection still names nothing, the employer still has
    exactly one cluster, and rule 3 still fires. One cluster, both messages,
    and now it has a title.

    THE REJECTION'S SUBJECT IS NOT READ, and that is a real residual rather
    than something this test papers over. Lever writes the title into it
    ("Thank you from <Employer> - <Name> - <Role>") and no
    ``_role_from_subject`` rule parses that shape, so the rejection is placed by
    having no identity rather than by having a matching one. At an employer with
    two role-less cards that is the difference between routing and a review
    queue entry — filed separately, not fixed here.
    """

    assert application_sub_key(PALANTIR_REJECTION_SUBJECT, "") is None

    confirmation = _lever_item(
        "m1",
        "19fef5720d70b0c6",
        "Your application has been received!",
        PALANTIR_CONFIRMATION,
        "applied",
        datetime(2026, 8, 11, 5, 41),
    )
    rejection = _lever_item(
        "m2",
        "1a001b68983e59a3",
        PALANTIR_REJECTION_SUBJECT,
        "Dear Ayush, Thank you for your interest in Palantir. After careful "
        "consideration, we regret to inform you that we will not be proceeding "
        "with your candidacy for this role at this time.",
        "rejection",
        datetime(2026, 8, 14, 19, 18),
    )

    clusters, unplaced = partition_applications([confirmation, rejection])

    assert unplaced == []
    assert len(clusters) == 1
    assert clusters[0].role == "Software Engineer, New Grad"
    assert [i.message_id for i in clusters[0].items] == ["m1", "m2"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Thank you for submitting your application to be a Software Engineer, "
            "New Grad at Palantir.",
            "Software Engineer, New Grad",
        ),
        (
            "your application to be an Infrastructure Engineer at Stripe.",
            "Infrastructure Engineer",
        ),
        (
            "We received your application to be the Staff Data Engineer at Figma.",
            "Staff Data Engineer",
        ),
    ],
)
def test_the_articles_lever_actually_uses(text: str, expected: str) -> None:
    assert role_from_message("", text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # The verb anchor is the only thing that refuses these two.
        "We have invited you to be a Mentor at Palantir University.",
        "You were nominated to be a Speaker at Palantir Summit.",
        # The employer must be capitalised, or the capture has no real end.
        "your application to be a Software Engineer at a company like Palantir.",
        # A possessive employer is not a job title — the guard the DoorDash
        # pattern needed, carried over here rather than re-derived.
        "your application to be a Palantir's Software Engineer at Palantir.",
    ],
)
def test_it_refuses_what_is_not_an_application(text: str) -> None:
    assert role_from_message("", text) is None


#: Three wordings, each owned by a DIFFERENT earlier pattern. Used twice below:
#: once to show the new rule did not disturb them, once to show it cannot even
#: see them.
OWNED_BY_AN_EARLIER_PATTERN = {
    # Ashby's explicit label.
    "Thank you for applying to our role: Software Engineer I, Storage.": (
        "Software Engineer I, Storage"
    ),
    # The article-anchored form, with its innermost-anchor tempering.
    "Thank you for your interest in SimpliSafe and our Software Engineer I- "
    "User Systems position.": "Software Engineer I- User Systems",
    # Microsoft's parenthesised requisition terminator.
    "submit your application for Software Engineer II (Job number: 200045485).": (
        "Software Engineer II"
    ),
}


def test_appending_the_rule_changed_no_existing_capture() -> None:
    """Every wording an earlier pattern owns still resolves the same way."""

    for text, expected in OWNED_BY_AN_EARLIER_PATTERN.items():
        assert role_from_message("", text) == expected


def test_the_new_rule_cannot_even_see_what_the_others_own() -> None:
    """Disjointness, which is the real property — and the one worth testing.

    THIS TEST REPLACES A CLAIM THAT COULD NOT FAIL. The assertion above was
    written with the docstring "if this rule is ever moved ahead of another, one
    of these would start resolving through the new one instead". That was
    wrong: none of the three wordings contains "to be a", so the new pattern
    cannot match them at ANY position, and the test passed identically with the
    rule moved to the front. Measured across the whole independent corpus, the
    order change moves 0 of 17,260 cases.

    So being last is not what makes the rule safe — being DISJOINT is, and that
    is a stronger property. This asserts it directly: the new pattern matches
    none of the text the earlier patterns own. Widening its anchor until it
    overlaps one of them turns this red, which is exactly the change that would
    make placement start to matter.
    """

    new_rule = _ROLE_BODY_PATTERNS[-1]
    for text in OWNED_BY_AN_EARLIER_PATTERN:
        assert new_rule.search(text) is None, text


def test_when_both_anchors_share_a_sentence_the_earlier_pattern_still_wins() -> None:
    """The ordering guard, on text constructed to make ordering matter.

    CONSTRUCTED, not observed — no real message has been seen carrying both
    anchors with two different titles, which is why the disjointness test above
    is the one that speaks about real mail. This one exists so the tuple's ORDER
    has a test at all: it is the only input in this file whose answer depends on
    where the rule sits.
    """

    both = (
        "Thank you for applying to our role: Site Reliability Engineer. We have "
        "logged your application to be a Backend Engineer at Northwind as well."
    )

    assert role_from_message("", both) == "Site Reliability Engineer"

    reordered = (_ROLE_BODY_PATTERNS[-1], *_ROLE_BODY_PATTERNS[:-1])
    first_match = next(
        role
        for role in (
            _clean_role(m.group("role"))
            for m in (p.search(both) for p in reordered)
            if m is not None
        )
        if role is not None
    )
    assert first_match == "Backend Engineer"


class TestBothGuardsCarryWeight:
    """Revert each half separately; each has a case only it refuses.

    A guard no test can distinguish from its absence is either untested or
    unnecessary, and this rule has two of them.
    """

    ROLE = r"(?P<role>[A-Z](?:(?!'s\s)[^.!?\n]){3,90}?)"
    REAL = (
        "Thank you for submitting your application to be a Software Engineer, "
        "New Grad at Palantir."
    )

    def _capture(self, pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text)
        return _clean_role(match.group("role")) if match else None

    def test_without_the_application_verb_an_invitation_becomes_a_job(self) -> None:
        mutated = re.compile(
            r"\bto\s+be\s+(?:an?|the)\s+" + self.ROLE + _ROLE_TRAILING_REQ + r"\s+at\s+[A-Z]"
        )
        invitation = "We have invited you to be a Mentor at Palantir University."

        assert self._capture(mutated, self.REAL) == "Software Engineer, New Grad"
        assert self._capture(mutated, invitation) == "Mentor"
        assert role_from_message("", invitation) is None

    def test_without_the_capitalised_employer_the_capture_has_no_end(self) -> None:
        mutated = re.compile(
            r"\b(?:application|applying|applied)\b[^.!?\n]{0,40}?"
            r"\bto\s+be\s+(?:an?|the)\s+" + self.ROLE + _ROLE_TRAILING_REQ + r"\s+at\s+\w"
        )
        vague = "your application to be a Software Engineer at a company like Palantir."

        assert self._capture(mutated, self.REAL) == "Software Engineer, New Grad"
        assert self._capture(mutated, vague) == "Software Engineer"
        assert role_from_message("", vague) is None
