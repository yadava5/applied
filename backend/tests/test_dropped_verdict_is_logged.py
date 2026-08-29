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

``us.greenhouse-mail.io`` is not the employer and the display name is absent,
so the subject is the only thing left that can name the company.

THAT SUBJECT NOW RESOLVES, AND THIS FILE HAD TO BE REWRITTEN FOR IT (#512).
Until the leading-segment rule learned to stop at a lifecycle word, the
lowercase "for" broke the company's run to the ``|`` and ``resolve_employer``
returned None — so a rejection the classifier scored at 0.93 produced no card,
which is the defect the owner reported twice. Three tests here asserted that
None. They were the inverted-gate shape: an assertion that PINS the broken
answer goes red on the repair and defends the bug, and all three did.

They now assert the fix, each paired with a subject that is genuinely
anchorless — "Update on your application | <name>", which names nobody and must
still resolve to nothing. That pairing is the point: the fix has to be readable
as "this one resolves and that one does not", or the next rewrite loosens the
rule until every rejection mints a company out of its own job title.

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
#: The same relay and the same absent display name, with a subject that names
#: nobody. The control for every assertion about the one above: without it,
#: "the employer resolves" is satisfied by a rule that resolves everything.
ANCHORLESS_SUBJECT = "Update on your application | Ayush Yadav"
GREENHOUSE_RELAY = "no-reply@us.greenhouse-mail.io"
WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _real_shape(
    message_id: str,
    category: str,
    confidence: float,
    subject: str = ANTHROPIC_SUBJECT,
    sender: str = GREENHOUSE_RELAY,
) -> p.PipelineItem:
    """The production failing shape: relay sender, no display name.

    ``sender`` is a parameter because ONE test here needs a message the reader
    sent rather than one a relay delivered — see
    :func:`test_a_confident_dropped_verdict_is_logged` and #458.
    """

    return p.PipelineItem(
        message_id=message_id,
        category=category,
        sender_email=sender,
        subject=subject,
        sender_name=None,  # the relay sends none, and that is the whole problem
        received_at=WHEN,
        confidence=confidence,
    )


# =============================================================================
# The real shape, through the pure pipeline
# =============================================================================


def test_the_real_failing_shape_now_names_its_employer_and_files() -> None:
    """The reported defect, and the assertion that used to pin it (#512).

    This test asserted ``resolve_employer(...) is None`` — the broken answer —
    from the day the file was written until the leading-segment rule was fixed.
    Read at the time it looked like a careful negative: the fixtures elsewhere
    in the suite all avoid this shape, and pinning what production really did
    was the honest move. It is still the inverted-gate shape, because the thing
    it pinned was a defect, and it went red the moment the defect was repaired.

    What it must say instead is what the user asked for: the employer is in the
    subject, so name it and file the card.
    """

    assert p.resolve_employer(GREENHOUSE_RELAY, ANTHROPIC_SUBJECT, None) == (
        "anthropic",
        "Anthropic",
    )

    item = _real_shape("anthropic-rej-1", "rejection", 0.93)
    assert p._qualifies_for_hard_row(item) is not None
    rolled = p.roll_up_applications([item])
    assert [r.company_display for r in rolled] == ["Anthropic"]


def test_a_subject_that_names_nobody_still_reaches_no_application_row() -> None:
    """THE CONTROL for the test above, and the harder half to keep true.

    This is the filing path: whatever ``resolve_employer`` returns becomes a
    card. A rule loose enough to rescue the Anthropic subject by taking "the
    leading words of anything" mints a company called "Update On Your"
    here — and that card is on the board under a name nobody chose. Refusing is
    the safe answer; the row goes to the queue and a person decides.
    """

    assert p.resolve_employer(GREENHOUSE_RELAY, ANCHORLESS_SUBJECT, None) is None

    item = _real_shape("anchorless-rej-1", "rejection", 0.93, ANCHORLESS_SUBJECT)
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

    item = _real_shape("anchorless-rej-1", "rejection", 0.93, ANCHORLESS_SUBJECT)
    review = p.collect_review_items([item])

    assert [r.message_id for r in review] == ["anchorless-rej-1"]
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

    THE SENDER MOVED OFF THE RELAY (#458), and the reason is the point of this
    file rather than a detail of this test. Until then the fixture here was the
    relay shape at the top — the REAL Anthropic subject, delivered by
    Greenhouse — and this test asserted that it produced nothing. That is the
    inverted-gate shape the module docstring describes, twice over: the message
    it pinned as correctly dropped is a real rejection, and eleven of its kind
    reached nothing in the corpus for exactly this reason. ``follow_up`` from a
    relay now reaches the queue.

    What this test is actually for is the LOG, and the shape that still drops
    is the one the category names: mail the reader sent. So the fixture is that
    message, sent by the reader, and the instrument is unchanged.
    """

    item = _real_shape(
        "anthropic-followup-1", "follow_up", 0.90, sender="ayush@example.com"
    )

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
    """``other`` is what keeps this instrument usable — NOT the confidence gate.

    The cloud rules classifier returns ``other`` at confidence 0.0, and the bulk
    of any real scan is ``other``. Logging every dropped item unconditionally
    would put a line per junk email into the deployment log, which is how an
    instrument gets ignored and then removed. So ``other`` is dropped silently,
    and that half of this test is unchanged.

    WHAT CHANGED, 2026-08-21, AND WHY THIS TEST WAS DEFENDING A BUG
    ---------------------------------------------------------------
    This test used to assert that the weak LIFECYCLE verdict below was dropped
    silently too, on the reasoning that the auto-file gate is what bounds the
    volume. That reasoning was wrong, and it was load-bearing: it made "a
    rejection the classifier scored at 0.42 disappears without a trace" a pinned
    guarantee of this suite.

    Four Microsoft application confirmations then did exactly that in
    production. Each scored ``rejection`` at 0.60 off a conditional clause in
    the body, each was under ``REVIEW_FLOOR``, and each left through this drop
    with no row, no queue entry, no counter and no log line. The user's report
    was "I'm not getting anything" and there was nothing to look at; diagnosing
    it took a mailbox read and a local reproduction of the pipeline.

    The gate is now "is this a LIFECYCLE verdict", not "was the classifier
    confident" — which is the right axis, because the confident drops are the
    DESIGNED ones (``follow_up``, asserted above) and the unconfident ones are
    the accidents. Volume stays bounded by ``other`` taking the silent path,
    which is what the first half of this test pins.

    See ``tests/test_lifecycle_drop_is_counted.py`` for the four real messages
    and ``pipeline.DroppedVerdict`` for the count the sync now returns.
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
    #
    # The sender is NOT the Greenhouse relay. It used to be, and that made this
    # fixture the #166 shape by accident: a ``rejection`` at 0.42 from a known
    # ATS now reaches the review queue via the ATS floor instead of being
    # dropped — ``test_the_ats_floor_rescues_the_weak_ats_rejection`` below is
    # that same item asserted the other way round. What THIS test is about is
    # the log staying quiet below the auto-file gate, so the fixture moves to a
    # sender the floor does not cover and goes on testing exactly that.
    weak = p.PipelineItem(
        message_id="weak-1",
        category="rejection",
        sender_email="recruiting@acme.com",
        subject="Update on your application",
        sender_name=None,
        received_at=WHEN,
        confidence=0.42,
    )

    with caplog.at_level(logging.WARNING, logger="jobtracker.cloud.pipeline"):
        assert p.collect_review_items([*noise, weak]) == []

    records = [r for r in caplog.records if r.name == "jobtracker.cloud.pipeline"]

    # The volume bound: twenty-five newsletters must still cost zero lines.
    assert [r for r in records if "noise-" in r.getMessage()] == [], (
        "``other`` is the bulk of every scan and must stay silent, or the log "
        "becomes unreadable and the instrument gets removed"
    )

    # The repair: the one LIFECYCLE verdict is reported. Paired with the
    # assertion above as its control — together they say "bound the volume by
    # category, not by confidence", which is the whole change.
    lifecycle = [r for r in records if "weak-1" in r.getMessage()]
    assert len(lifecycle) == 1, (
        "a rejection the classifier scored at 0.42 is mail it believed was "
        "about a job application, and dropping it in silence is what cost the "
        "owner four Microsoft applications on 2026-08-21"
    )
    assert "BELOW the review floor" in lifecycle[0].getMessage()


def test_the_ats_floor_rescues_the_weak_ats_rejection() -> None:
    """The other half of the fixture above — issue #166's fix, on this shape.

    ``rejection`` at 0.42 from ``no-reply@us.greenhouse-mail.io`` is precisely
    the message that used to vanish: below ``REVIEW_FLOOR`` so no queue entry,
    and below ``AUTO_FILE_GATE`` so not even a log line. It now reaches the
    queue — and only the queue.

    Note what does NOT change: confidence. #512 taught the resolver to read the
    employer out of this subject, which is a different question from how sure
    the classifier is about the verdict. At 0.42 the message still reaches the
    queue and only the queue — it now arrives with the employer's name on it,
    which is the difference between "we are not sure what this is" and "we are
    not sure what this is and cannot tell you who it is from".
    """

    weak = _real_shape("weak-ats-1", "rejection", 0.42)

    assert p.roll_up_applications([weak]) == []
    review = p.collect_review_items([weak])
    assert [r.message_id for r in review] == ["weak-ats-1"]
    assert review[0].category == "rejection"
    assert review[0].company_display == "Anthropic"

    # The control, same floor, a subject naming nobody: the queue entry must
    # still name no company rather than inventing one.
    blind = _real_shape("weak-ats-2", "rejection", 0.42, ANCHORLESS_SUBJECT)
    assert p.roll_up_applications([blind]) == []
    queued = p.collect_review_items([blind])
    assert [r.message_id for r in queued] == ["weak-ats-2"]
    assert queued[0].category == "rejection"
    assert queued[0].company_display is None
