"""A lifecycle verdict the pipeline throws away must leave a number behind.

REPORTED FROM LIVE USE on 2026-08-21: "I applied to 4 new Microsoft and a
Google application, but when I sync it in the app, I'm not getting anything?"

The sync was healthy. All four Microsoft confirmations were in the inbox,
marked IMPORTANT, fifteen minutes before the run. Production shows the run
inserted exactly one ``emails`` row (the Google one) and nothing else, and the
four Microsoft messages have no row of any kind — not an application, not a
review-queue entry, not even a stored email.

They left through the single terminal drop in
:func:`pipeline.collect_review_items`. Each scored ``rejection`` at 0.60,
under ``REVIEW_FLOOR``; ``donotreply@email.careers.microsoft.com`` is not on
``rules.ATS_DOMAINS``, so the ATS floor did not catch them either.

WHAT THIS FILE IS ABOUT is not the verdict — that is the classifier's problem
and has its own fix. It is the SILENCE. The drop wrote no row, no counter and
no log line, because the log was gated at ``AUTO_FILE_GATE`` (0.85) and these
scored 0.60. From the product's side "we discarded four of your applications"
and "your mailbox was quiet" were the same response: ``created=0, updated=0``.

Diagnosing it took a mailbox read and a local reproduction of the pipeline.
That is the cost this file is here to stop anyone paying twice.

THE CONTROL THAT MATTERS is :func:`test_the_old_confidence_gate_would_have_
missed_all_four`. Every drop these messages make is far below the threshold the
old log line used, so a report keyed on confidence is structurally incapable of
naming them. Without that assertion, a future "simplification" back to
``>= AUTO_FILE_GATE`` leaves every test here green and restores the exact
silence that cost four applications.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from jobtracker.cloud import pipeline as p

#: The four real applications, with the requisition numbers Microsoft printed.
MICROSOFT_IDS = [
    "1a02341f84f11426",
    "1a023443b385563f",
    "1a023453e5cd359d",
    "1a023464635139a1",
]

SENDER = "donotreply@email.careers.microsoft.com"
SUBJECT = "Thank you for your application!"

#: The verdict the live classifier returns for these bodies. Measured, not
#: assumed: the body's conditional explainer ("if you see the job moved to an
#: inactive state, that means ... you were not selected for the role") fires two
#: strong rejection patterns, and the marketing footer's "Unsubscribe" takes 5
#: off every category, leaving rejection on top with a score of 1 → 0.60.
MEASURED_CATEGORY = "rejection"
MEASURED_CONFIDENCE = 0.60


def _microsoft(message_id: str) -> p.PipelineItem:
    return p.PipelineItem(
        message_id=message_id,
        category=MEASURED_CATEGORY,
        sender_email=SENDER,
        sender_name="Microsoft Careers",
        subject=SUBJECT,
        received_at=datetime(2026, 8, 21, 7, 38, tzinfo=UTC),
        confidence=MEASURED_CONFIDENCE,
        # Gmail threaded all four: byte-identical sender and subject.
        thread_id="1a02341f84f11426",
        snippet="Thank you for taking the time to submit your application",
    )


def test_the_four_that_vanished_are_counted() -> None:
    """The defect as the user met it, stated as one number."""

    items = [_microsoft(mid) for mid in MICROSOFT_IDS]
    dropped: list[p.DroppedVerdict] = []

    rolled = p.roll_up_applications(items)
    review = p.collect_review_items(items, dropped)

    assert rolled == [], "precondition: these produce no application row"
    assert review == [], "precondition: these produce no review-queue entry"
    assert len(dropped) == 4, (
        f"four messages left the pipeline and {len(dropped)} were reported. A sync "
        "that discards mail while answering 'created=0, updated=0' is "
        "indistinguishable from a quiet mailbox, which is exactly how these four "
        "applications went missing without anything to look at."
    )
    assert {d.message_id for d in dropped} == set(MICROSOFT_IDS)
    assert all(d.category == MEASURED_CATEGORY for d in dropped)


def test_the_old_confidence_gate_would_have_missed_all_four() -> None:
    """THE CONTROL. Confidence cannot be what decides whether a drop is reported.

    The previous log line fired only at/above ``AUTO_FILE_GATE``. These four sit
    at 0.60 — below the review floor, nowhere near the gate — so that condition
    was false for every one of them. This is the assertion that fails if anyone
    re-gates the report on confidence, and it is the only one here that would
    have caught the original bug.
    """

    assert MEASURED_CONFIDENCE < p.REVIEW_FLOOR < p.AUTO_FILE_GATE

    reported_by_the_old_gate = [
        mid for mid in MICROSOFT_IDS if MEASURED_CONFIDENCE >= p.AUTO_FILE_GATE
    ]
    assert reported_by_the_old_gate == [], (
        "sanity: the old gate is silent on this shape by construction"
    )

    dropped: list[p.DroppedVerdict] = []
    p.collect_review_items([_microsoft(m) for m in MICROSOFT_IDS], dropped)
    assert len(dropped) == 4, (
        "the report must key on 'was this a lifecycle verdict', not on how "
        "confident the classifier happened to be. The confident drops are the "
        "DESIGNED ones (follow_up); the unconfident ones are the accidents."
    )


def test_every_lifecycle_drop_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A deployment with no way to read the response still gets a line."""

    with caplog.at_level(logging.WARNING, logger=p.logger.name):
        p.collect_review_items([_microsoft(MICROSOFT_IDS[0])])

    lines = [r for r in caplog.records if "BELOW the review floor" in r.getMessage()]
    assert len(lines) == 1, (
        "the drop is terminal and leaves no row behind, so the log line is the "
        "only durable evidence it happened at all"
    )
    assert MICROSOFT_IDS[0] in lines[0].getMessage()


def test_a_healthy_scan_reports_nothing_dropped() -> None:
    """THE OTHER HALF OF THE CONTROL — a counter that only ever goes up is noise.

    A confident, filable confirmation must leave ``dropped`` at zero, or the
    number means "a sync happened" rather than "something was thrown away".
    """

    good = p.PipelineItem(
        message_id="healthy-1",
        category="applied",
        sender_email="no-reply@greenhouse.io",
        sender_name="Cedar Labs",
        subject="Thank you for applying to Cedar Labs",
        received_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        confidence=0.95,
        thread_id="t-healthy-1",
        snippet="We have received your application.",
    )
    dropped: list[p.DroppedVerdict] = []
    rolled = p.roll_up_applications([good], )
    p.collect_review_items([good], dropped)

    assert rolled, "precondition: this one really does file"
    assert dropped == []


def test_ordinary_inbox_noise_is_not_counted_as_a_drop() -> None:
    """Bounding the number, so it stays worth reading.

    ``other`` is the bulk of every scan. If newsletters counted, a sync would
    report hundreds dropped and the figure would say nothing about whether the
    user lost an application.
    """

    noise = [
        p.PipelineItem(
            message_id=f"noise-{i}",
            category="other",
            sender_email="news@example.test",
            sender_name="Example Weekly",
            subject="Your weekly digest",
            received_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
            confidence=0.0,
            thread_id=f"t-noise-{i}",
            snippet="This week in tech.",
        )
        for i in range(25)
    ]
    dropped: list[p.DroppedVerdict] = []
    p.collect_review_items(noise, dropped)
    assert dropped == []


def test_a_confident_follow_up_is_dropped_by_design_and_not_counted() -> None:
    """The one lifecycle-ish drop that is deliberate stays out of the number.

    ``follow_up`` is excluded from the queue on purpose. Counting it would make
    ``dropped`` non-zero on syncs where nothing went wrong.
    """

    follow_up = p.PipelineItem(
        message_id="follow-up-1",
        category="follow_up",
        sender_email="no-reply@greenhouse.io",
        sender_name="Cedar Labs",
        subject="Following up on my application",
        received_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        confidence=0.90,
        thread_id="t-follow-up-1",
        snippet="Just checking in.",
    )
    dropped: list[p.DroppedVerdict] = []
    p.collect_review_items([follow_up], dropped)
    assert dropped == []


def test_the_out_parameter_is_optional() -> None:
    """Every existing caller passes one argument and must keep working."""

    assert p.collect_review_items([_microsoft(MICROSOFT_IDS[0])]) == []
