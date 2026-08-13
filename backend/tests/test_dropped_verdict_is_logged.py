"""The pipeline's one terminal drop must leave a trace — plus the real shape.

WHY THIS FILE EXISTS
--------------------
Applied recorded ZERO non-applied application statuses in production while 50
tests about rejections passed. The tests passed because every rejection fixture
in this suite pins ``AMAZON_SENDER`` (a corporate domain, so
:func:`pipeline.resolve_employer` succeeds on its first step) and
``AMAZON_SUBJECT`` (which carries the "to Amazon" anchor), and hardcodes the
category and confidence so the classifier never runs — see
``test_stage_write_policy.py`` and ``test_application_identity.py``. Those
fixtures guarantee the precondition that FAILS in production, so no amount of
them could catch this.

The shape that actually fails is an ATS relay sender with no display name and a
subject carrying no employer anchor. Modelled here on a real message:

    subject  Anthropic Follow-Up for TPU Kernel Engineer | Ayush Yadav
    sender   no-reply@us.greenhouse-mail.io
    name     (none)

``us.greenhouse-mail.io`` is not the employer, the display name is absent, and
the subject names the company only as a bare leading word with no "to <company>"
anchor — so ``resolve_employer`` returns None and the message can never become
an application row.

WHAT IS AND IS NOT COVERED HERE
-------------------------------
The PIPELINE half of that shape is correct today and is pinned below: the real
verdict survives into the review item. The PERSISTENCE half is not fixed — the
review item's category is thrown away in
``applications._persist_review_items_additive``, which hardcodes
``category="needs_review"``. That fix is BLOCKED, not forgotten: the review
queue and the dashboard's "held for your review" count both select on
``Email.classified_as == NEEDS_REVIEW`` (``cloud/applications.py`` lines 2746
and 2856), so carrying the real verdict through empties the queue. Nine tests
in this suite prove it. Fixing it requires deciding the queue's contract first,
which is a separate change; the test that pins ``classified_as == "rejection"``
lands with it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from jobtracker.cloud import pipeline as p

# The real message, verbatim in the parts that matter.
ANTHROPIC_SUBJECT = "Anthropic Follow-Up for TPU Kernel Engineer | Ayush Yadav"
GREENHOUSE_RELAY = "no-reply@us.greenhouse-mail.io"
WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _real_shape(message_id: str, category: str, confidence: float) -> p.PipelineItem:
    """The production failing shape: relay sender, no display name, no anchor."""

    return p.PipelineItem(
        message_id=message_id,
        category=category,
        sender_email=GREENHOUSE_RELAY,
        subject=ANTHROPIC_SUBJECT,
        sender_name=None,  # the relay sends none, and that is the whole problem
        received_at=WHEN,
        confidence=confidence,
    )


# =============================================================================
# The real shape, through the pure pipeline
# =============================================================================


def test_the_real_failing_shape_names_no_employer() -> None:
    """The precondition every existing rejection fixture accidentally avoids.

    This is the assertion that would have flagged the fixtures as unrepresentative:
    on the real shape, employer resolution fails outright, so no rejection can
    ever reach an application row by the rollup route.
    """

    assert p.resolve_employer(GREENHOUSE_RELAY, ANTHROPIC_SUBJECT, None) is None

    item = _real_shape("anthropic-rej-1", "rejection", 0.93)
    assert p._qualifies_for_hard_row(item) is None
    assert p.roll_up_applications([item]) == []


def test_an_anchorless_ats_rejection_keeps_its_real_verdict_into_the_queue() -> None:
    """The review item carries ``rejection``, not ``needs_review``.

    The pure pipeline is the half of this that already works, and it must stay
    working: it is the only place the real verdict still exists before
    persistence overwrites it. If ``collect_review_items`` is ever "simplified"
    to stamp every queued item ``needs_review``, the verdict is gone before the
    persist-layer fix could even matter, and this goes red.
    """

    item = _real_shape("anthropic-rej-1", "rejection", 0.93)
    review = p.collect_review_items([item])

    assert [r.message_id for r in review] == ["anthropic-rej-1"]
    assert review[0].category == "rejection"
    # No employer was invented on the way past — the honest outcome.
    assert review[0].company_display is None


# =============================================================================
# Fix 2 — the terminal drop is no longer silent
# =============================================================================


def test_a_confident_dropped_verdict_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A confident verdict that produces NOTHING must say so.

    ``follow_up`` is excluded from filing by design and from the review queue by
    design, so a confident one vanishes completely: no application row, no queue
    entry, no counter. That silence is what let three separate persistence drops
    ship unnoticed. The log line is the instrument.
    """

    item = _real_shape("anthropic-followup-1", "follow_up", 0.90)

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.pipeline"):
        review = p.collect_review_items([item])

    # Behaviour is unchanged: it is still dropped.
    assert review == []
    assert p.roll_up_applications([item]) == []

    records = [r for r in caplog.records if r.name == "jobtracker.cloud.pipeline"]
    assert len(records) == 1, f"expected exactly one drop record, got {records}"
    message = records[0].getMessage()
    # The three facts the brief requires: category, confidence, message id.
    assert "follow_up" in message
    assert "0.90" in message
    assert "anthropic-followup-1" in message


def test_a_non_canonical_category_is_logged_too(caplog: pytest.LogCaptureFixture) -> None:
    """A category outside the vocabulary is a bug, and bugs must be visible."""

    item = _real_shape("anthropic-unknown-1", "rejected", 0.95)  # note: not "rejection"

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.pipeline"):
        assert p.collect_review_items([item]) == []

    records = [r for r in caplog.records if r.name == "jobtracker.cloud.pipeline"]
    assert len(records) == 1
    assert "rejected" in records[0].getMessage()


def test_ordinary_inbox_noise_does_not_flood_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """The auto-file gate is what keeps this instrument usable.

    The cloud rules classifier returns ``other`` at confidence 0.0, and the bulk
    of any real scan is ``other``. Logging every dropped item unconditionally
    would put a line per junk email into the deployment log, which is how an
    instrument gets ignored and then removed. Below the gate: dropped, silent.
    """

    noise = [
        p.PipelineItem(
            message_id=f"noise-{i}",
            category="other",
            sender_email="news@digest.example",
            subject="Weekly digest",
            received_at=WHEN,
            confidence=0.0,
        )
        for i in range(5)
    ]
    # A lifecycle verdict too weak for even the review floor is dropped quietly
    # as well — that is the precision gate doing its job, not an anomaly.
    weak = _real_shape("weak-1", "rejection", 0.42)

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.pipeline"):
        assert p.collect_review_items([*noise, weak]) == []

    assert [r for r in caplog.records if r.name == "jobtracker.cloud.pipeline"] == []
