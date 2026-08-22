"""A phrase in a conditional clause is not a verdict.

REPORTED FROM LIVE USE on 2026-08-21: "I applied to 4 new Microsoft and a
Google application, but when I sync it in the app, I'm not getting anything?"

Four confirmations, one employer, five minutes apart, all in the inbox and
marked IMPORTANT fifteen minutes before the sync ran. None produced a row of
any kind. Each carried this near the end of an otherwise ordinary confirmation:

    If you see the job moved to an inactive state, that means the position is
    either no longer open, you withdrew from consideration, or you were not
    selected for the role.

Nothing has been decided. It explains what the dashboard would show if things
later went badly. Two STRONG rejection patterns fired on "you were not selected
for the role", the message scored ``rejection`` at 0.60, and at that confidence
``pipeline.collect_review_items`` discarded it — under ``REVIEW_FLOOR``, and
from a sender that is not on ``ATS_DOMAINS`` so the ATS floor did not catch it
either. No card, no queue entry, no counter, no log line.

TWO DEFECTS, AND THE FIRST ONE ALONE FIXES NOTHING
--------------------------------------------------
Measured before anything was written:

    conditional suppressed                          -> OTHER   0.50   (dropped)
    conditional suppressed + footer not counted     -> APPLIED 0.80   (queued)

The marketing negative ``\\b(unsubscribe|manage preferences|newsletter|digest)\\b``
sits on the negative list of applied, rejection, offer AND follow_up, and every
transactional ATS mail ends with an unsubscribe link. It hits each candidate
equally so it never changes the WINNER — only the absolute score, which is what
``confidence`` is computed from. On this message it was worth exactly the
difference between a queue entry and silent destruction.

THE CEILING, STATED PLAINLY. 0.80 clears ``REVIEW_FLOOR`` and does NOT clear
``AUTO_FILE_GATE``. These messages now reach the review queue, one entry each.
They do not land on the board by themselves. The subject "Thank you for your
application!" matches no ``applied`` SUBJECT pattern, which is what would be
needed to reach 0.90, and adding one is a separate change with its own risk.

THE BODIES BELOW ARE RECONSTRUCTED, NOT COPIED. The real messages carry the
owner's name, his address and per-message tracking tokens; none of that belongs
in a committed fixture. What is faithful is the SHAPE — including the dot-laden
tracking link immediately before the conditional, which is the detail a
clean-prose fixture would miss. See ``test_a_tracking_url_does_not_defeat_the_mask``.

The same set runs against the browser port in
``apps/web/tests/e2e/import.spec.ts``: ``/import`` classifies with
``lib/demo/rulesLayer.ts``, in the tab, with no account, and a fix that lands on
only one of the two layers is half a fix.
"""

from __future__ import annotations

import pytest

from jobtracker.classifier.rules import asserted_text, get_rules_classifier
from jobtracker.cloud.pipeline import AUTO_FILE_GATE, REVIEW_FLOOR
from jobtracker.database.models import EmailCategory

SUBJECT = "Thank you for your application!"
SENDER = "donotreply@email.careers.example"

#: The conditional explainer, verbatim in the part that matters.
CONDITIONAL = (
    "If you see the job moved to an inactive state, that means the position is "
    "either no longer open, you withdrew from consideration, or you were not "
    "selected for the role."
)

#: A tracking link shaped like the real one: base64 with dots in it, sitting
#: immediately before the conditional sentence. The dots are the whole point.
TRACKING_LINK = (
    "https://example-ats.test/vsimp?d=.eJwViTEOgCAQwP5ys5LzDhCY_IkhSIQoOmBcjH8Xly"
    "ZtHyh1nfMCDq2RbFk3DJJJdRCLzzs48LEmIVkQT-ufRDgLtH3H42o77DlszY.Lj6ZStc7Wcyj5J3x"
    "&n=https%3A%2F%2Fapply.example-ats.test%2Fcareers%2Fdashboard"
)


def confirmation(link: str = TRACKING_LINK) -> str:
    return (
        "Hi there, Thank you for taking the time to submit your application for "
        "Software Engineer II (Job number: 200045485). We are glad you are "
        "interested in a career here, and we are here to help you find your next "
        "role. You may not receive feedback on your application directly, but "
        "please know that it is being evaluated. Updates regarding your "
        f"application status can be viewed through your Action Center[]({link}). "
        f"{CONDITIONAL} We encourage you to check back frequently.\n\n"
        "Thank you, Recruiting\n\nThis email was sent to you by us. [Unsubscribe]"
    )


@pytest.fixture()
def rules():
    return get_rules_classifier()


def test_the_confirmation_that_was_thrown_away_reads_as_an_application(rules) -> None:
    """The defect as the user met it."""

    result = rules.classify(SUBJECT, confirmation(), SENDER)

    assert result.category is EmailCategory.APPLIED, (
        f"an application confirmation read as {result.category.value}. The only "
        "negative language in it is a conditional explaining what an inactive "
        f"dashboard state would mean. scores={result.scores}"
    )
    assert result.confidence >= REVIEW_FLOOR, (
        f"confidence {result.confidence} is under the {REVIEW_FLOOR} review "
        "floor, which is where these four messages were destroyed rather than "
        "queued"
    )


def test_the_ceiling_is_the_review_queue_not_the_board(rules) -> None:
    """Stated as an assertion so nobody reads the fix as more than it is.

    This message reaches a human. It does not file itself. If a later change
    pushes it over ``AUTO_FILE_GATE`` that is a real product decision and this
    test is where it gets made deliberately rather than by accident.
    """

    result = rules.classify(SUBJECT, confirmation(), SENDER)
    assert REVIEW_FLOOR <= result.confidence < AUTO_FILE_GATE, (
        f"confidence is {result.confidence}; the fix was measured and reported "
        f"as landing in [{REVIEW_FLOOR}, {AUTO_FILE_GATE}) — the review queue"
    )


def test_a_tracking_url_does_not_defeat_the_mask(rules) -> None:
    """The real message's shape, not a clean-prose stand-in.

    A dot-laden tracking link sits immediately before the conditional. The mask
    has to reach past it, and the message has to classify the same way it would
    with a short link.
    """

    assert "." in TRACKING_LINK, "the fixture is only interesting if the URL has dots"

    with_link = confirmation(TRACKING_LINK)
    without_link = confirmation("https://example-ats.test/dashboard")

    assert "not selected" not in asserted_text(with_link), (
        "the conditional survived the mask when a URL full of dots preceded it"
    )
    assert (
        rules.classify(SUBJECT, with_link, SENDER).category
        == rules.classify(SUBJECT, without_link, SENDER).category
    ), "the same message classified differently depending on how its links were shaped"


def test_an_abbreviation_inside_a_conditional_does_not_end_it() -> None:
    """THE ASSERTION THAT EARNS THE CAPITAL-LETTER GUARD.

    Sentences are split on ``(?<=[.!?])\\s+`` and a fragment that does not begin
    like a sentence is glued back on. Drop that second step and the dot in an
    abbreviation ends the sentence early — so a conditional's marker lands in
    one fragment and the phrase it governs in the next, the mask cannot reach
    the phrase, and the message goes back to reading as a rejection.

    This test exists because mutation testing found the guard unheld: removing
    it left every other test in this file green. Two other pieces of
    "defensive" machinery in this same fix were deleted for exactly that reason
    (a URL strip, and a claim about dot-laden links). This one is kept because
    it can now fail.
    """

    body = (
        "Thank you for submitting your application. If the status changes e.g. "
        "to inactive, that means the position is closed or you were not "
        "selected for the role."
    )
    masked = asserted_text(body)
    assert "not selected" not in masked, (
        "an abbreviation ended the conditional early, so the phrase it governs "
        f"escaped the mask: {masked!r}"
    )


def test_the_same_clause_asserted_is_still_a_rejection(rules) -> None:
    """THE CONTROL.

    A fix that suppresses the PHRASE rather than its MOOD passes every test
    above and silently stops the product ever detecting a rejection — which,
    per the project's own notes, it has never once managed to do.
    """

    body = (
        "Hi there,\n\nThank you for your interest in the Software Engineer II "
        "position and for the time you spent with our team.\n\nAfter careful "
        "consideration, you were not selected for the role. We had a number of "
        "strong candidates and the decision was a difficult one.\n\nWe wish you "
        "the very best in your search.\n"
    )
    result = rules.classify("Update on your application", body, "talent@acme.example")

    assert result.category is EmailCategory.REJECTION
    assert result.confidence >= AUTO_FILE_GATE, (
        f"an asserted rejection must still auto-file; got {result.confidence}"
    )


def test_a_verdict_before_an_if_in_the_same_sentence_survives() -> None:
    """The mask runs from the marker to the end of ITS SENTENCE, not over the
    whole sentence. "You were not selected for the role, and if you would like
    feedback please ask" is a real rejection whose verdict sits before the
    marker."""

    kept = asserted_text(
        "You were not selected for the role, and if you would like feedback "
        "please reply to this message."
    )
    assert "not selected for the role" in kept, f"the mask ate the verdict: {kept!r}"
    assert "feedback" not in kept, f"the mask did not reach the conditional: {kept!r}"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Thank you for applying. We will be in touch.",
        "No conditional here at all.",
    ],
)
def test_asserted_text_is_idempotent_and_harmless_without_a_conditional(text: str) -> None:
    once = asserted_text(text)
    assert once == text
    assert asserted_text(once) == once


def test_a_marketing_footer_no_longer_erases_a_verdict_the_body_states(rules) -> None:
    """The second half of the fix, isolated from the first."""

    body = (
        "Hi there,\n\nWe have received your application for the Software Engineer "
        "position. Our team reviews every application and will be in touch if "
        "there is a match.\n\nRecruiting\n\nUnsubscribe or manage preferences.\n"
    )
    result = rules.classify("We have received your application", body, SENDER)
    assert result.category is EmailCategory.APPLIED
    assert result.confidence >= AUTO_FILE_GATE


def test_a_job_alert_is_still_not_an_application(rules) -> None:
    """THE GENRE-FILTER CONTROL — c0031's shape, asserted here too.

    The marketing negatives exist for exactly this mail. Relaxing them so a
    footer cannot erase a real verdict must not re-admit it.
    """

    body = (
        "New jobs matching your alert. Ironvale is interviewing now. Apply today "
        "and get an offer faster.\n\nUnsubscribe from job alerts.\n"
    )
    result = rules.classify(
        "5 new Software Engineer jobs for you", body, "alerts@jobboard.example"
    )
    assert result.category is EmailCategory.OTHER, (
        f"a job alert was filed as {result.category.value}; the genre filters "
        f"stopped doing the job they were written for. scores={result.scores}"
    )


def test_a_strong_subject_alone_does_not_outrank_a_genre_filter(rules) -> None:
    """EARNED, NOT DESIGNED.

    The first version of this fix let any strong match outrank a genre filter.
    That took ``test_safety_net_is_dead_253.py``'s fixture — subject "Thanks for
    applying", body "your course is unfortunately over" — from OTHER to APPLIED,
    because a +6 subject hit outranked the ``your course`` filter that had
    correctly read it as course mail.

    A subject is a headline and the cheapest part of a message to make look like
    job mail. A genre filter reading the BODY outranks it, not the reverse.
    """

    result = rules.classify("Thanks for applying", "your course is unfortunately over", None)
    assert result.category is EmailCategory.OTHER, (
        f"scores={result.scores}; a subject line alone must not be able to "
        "overrule a genre filter that read the body"
    )
