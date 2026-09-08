"""Issue #800: an offer withdrawal that nothing recorded, as a queue-presence gate.

What was broken
---------------

A long-form offer withdrawal — one whose own text is long enough to survive
quote-stripping, so #417's retraction cap never sees it — classifies ``other``
at 0.50. Reproduced at HEAD, and the matched patterns are the whole story::

    long-form withdrawal -> OTHER 0.50  matched: ['[NEGATIVE] offer',
                                                  '[NEGATIVE] offer']
    REVIEW_FLOOR = 0.7

Under the floor, so ``collect_review_items`` took its terminal drop: no
``emails`` row, no queue entry, and the offer it cancels still filed on the
board reading ``offered``.

There is NO PER-MESSAGE TRACE of that loss, and the one counter it touches
cannot see it. ``DroppedVerdict`` is scoped to lifecycle categories and ``other``
is not one, so the message lands in ``ScanLedger.reached_nothing`` — the bucket
that also holds every newsletter in the mailbox. "No counter" would be wrong;
the sharp statement is that no counter can tell this apart from noise.

What the fix is, and what it deliberately is not
------------------------------------------------

ADMISSION, NOT A CONFIDENCE LIFT (DEC-010). Both #800 and #814 propose lifting
into ``[0.70, 0.85)``. That is not what is built and the difference is the whole
design: the stored confidence STAYS 0.50, because 0.50 is what the classifier
honestly believes about a message it has no withdrawal class for. What changes
is who gets asked. :func:`test_r1_the_arm_admits_without_touching_the_score`
pins the number so a later "simplification" into a score adjustment reds here.

The precedent is #166's own rescue, which queues a 0.42 untouched, and
``test_dropped_verdict_is_logged.py`` states it in as many words: "Note what
does NOT change: confidence".

Why the gate of record is R2 and not R1
---------------------------------------

R1 is a unit assertion on ``collect_review_items``. It reds today for one
reason — the floor.

R2 replays through the SYNC ENTRYPOINT, and it reds today for TWO. Past the
floor there is a second drop site: ``_persist_review_items_additive``'s settled
filter refuses an arriving review ref whose ``review_dedup_key`` matches a
message already filed on an answering application, BEFORE any ``emails`` row
exists. A withdrawal arriving in the offer's own thread and naming the same role
is #417's documented real shape and is exactly that filter's trigger class. The
filter's premise — "something already answers for this thread" — is false when
the arrival CONTRADICTS what answered.

MEASURED, in that order, on this branch: with the admission arm landed and the
settled-filter carve-out NOT yet written, R2 failed with the withdrawal admitted
to the queue by ``collect_review_items`` and then refused a row by the persist,
leaving it with no ``emails`` row exactly as before. A fix that shipped R1 alone
would have been green over the case that matters.

Test data
---------

Wholly invented employers on RFC-reserved, un-routable ``.test`` domains, per
``docs/TEST_DATA_POLICY.md``. No wording, employer or address here comes from a
real mailbox. The bodies are written to land in a confidence band and the band
is the only thing about them that is real.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta

from sqlmodel import select

from jobtracker.classifier.rules import RulesClassifier
from jobtracker.cloud import applications, pipeline
from jobtracker.cloud.applications import Application, Email
from jobtracker.database.models import ApplicationStatus
from tests.corpus_independent import harness
from tests.corpus_independent.generate import Case, snippet_of
from tests.corpus_independent.harness import classify_all, replay

_USER: uuid.UUID = harness._USER

_EPOCH = datetime(2026, 4, 6, 9, 15)

_FAMILY = "offer-withdrawal-direct"

#: WRITTEN OUT, one literal per employer, never assembled from a token at
#: runtime. ``scripts/check_test_data.py`` matches ADDRESSES IN THE TEXT with a
#: regex, and ``talent@{token}.test`` contains a brace where the domain starts —
#: so an f-string address scans as zero hits and the gate stays green whatever
#: the domain later becomes. Same reasoning, and the same measurement, as
#: ``test_settled_filter_drops_an_uncertain_update.py``.
_SENDERS = {
    "kelvedon": "talent@kelvedon.test",
    "marrowby": "talent@marrowby.test",
    "penhale": "talent@penhale.test",
    "quillon": "talent@quillon.test",
    "tarnwick": "talent@tarnwick.test",
}

#: NOT an ATS domain, and that is the point of the whole family. #166's floor
#: keeps sub-floor mail a known relay carried, so a withdrawal sent through one
#: is already queued and was before #800 existed. The exposed case — and the
#: likelier shape for a rescission — is a person writing directly.
_NON_ATS = "kelvedon.test"


def _offer_body(display: str) -> str:
    """An offer strong enough to AUTO-FILE, which is what mints the card.

    Measured: ``offer`` at 0.95, clear of ``AUTO_FILE_GATE``. A plainly-worded
    offer lands at exactly 0.70 and only reaches the queue, which would leave
    the board with no ``OFFERED`` card and make every assertion below vacuous —
    so the band is asserted in :func:`test_the_family_lands_where_the_gate_needs`
    rather than assumed.
    """

    return (
        f"Hi Ayush, I am pleased to offer you the position of Backend Engineer at "
        f"{display}. Please find the formal offer letter attached with details of "
        "compensation and your proposed start date. We would like you to join us."
    )


def _withdrawal_body(display: str) -> str:
    """The long form. Its own text carries the retraction; nothing is quoted."""

    return (
        "Hi Ayush, I am writing with difficult news about the Backend Engineer "
        "position. Following a change to our headcount plan this quarter, we must "
        f"withdraw the offer we extended to you last week at {display}. This "
        "decision is not a reflection of your interview performance, which the "
        "panel rated highly."
    )


def _case(
    *,
    mid: str,
    thread: str,
    subject: str,
    body: str,
    sender: str,
    sender_name: str,
    day: int,
    expected_category: str,
    identity: str | None,
    employer: str | None,
    note: str,
) -> Case:
    return Case(
        message_id=mid,
        thread_id=thread,
        subject=subject,
        sender=sender,
        sender_name=sender_name,
        body=body,
        delivered=body,
        received_at=_EPOCH + timedelta(days=day),
        family=_FAMILY,
        expected_category=expected_category,
        identity=identity,
        employer=employer,
        note=note,
    )


def _offer(display: str, token: str, thread: str, mid: str, day: int) -> Case:
    return _case(
        mid=mid,
        thread=thread,
        subject=f"Offer of employment - Backend Engineer at {display}",
        body=_offer_body(display),
        sender=_SENDERS[token],
        sender_name=f"{display} Talent",
        day=day,
        expected_category="offer",
        identity=f"{token}|backend engineer",
        employer=token,
        note="clears the auto-file gate and mints the OFFERED card",
    )


def _withdrawal(
    display: str, token: str, thread: str, mid: str, day: int, note: str
) -> Case:
    return _case(
        mid=mid,
        thread=thread,
        subject=f"Regarding your offer - {display}",
        body=_withdrawal_body(display),
        sender=_SENDERS[token],
        sender_name=f"{display} Talent",
        day=day,
        expected_category="other",
        identity=None,
        employer=token,
        note=note,
    )


def _item(
    *,
    mid: str,
    subject: str,
    body: str,
    sender: str = _SENDERS["kelvedon"],
    sender_name: str = "Kelvedon Talent",
    category: str = "other",
    confidence: float = 0.50,
    thread: str = "th-r1",
) -> pipeline.PipelineItem:
    """One ``PipelineItem``, for the assertions that do not need a database."""

    return pipeline.PipelineItem(
        message_id=mid,
        thread_id=thread,
        subject=subject,
        sender_email=sender,
        sender_name=sender_name,
        received_at=_EPOCH,
        category=category,
        confidence=confidence,
        snippet=body,
    )


def _collect(
    items: list[pipeline.PipelineItem], contested: frozenset[str]
) -> tuple[list[pipeline.ReviewItem], list[pipeline.DroppedVerdict]]:
    dropped: list[pipeline.DroppedVerdict] = []
    review = pipeline.collect_review_items(
        items, dropped, frozenset(), frozenset(), contested
    )
    return review, dropped


# ---------------------------------------------------------------------------
# The band, asserted before anything depends on it
# ---------------------------------------------------------------------------


def test_the_family_lands_where_the_gate_needs() -> None:
    """The premises every assertion below rests on, executed rather than assumed.

    Three of them, and each has already been the reason a gate in this repository
    measured nothing:

    1. the withdrawal is UNDER the floor — at or above it the message was never
       dropped and #800 does not exist;
    2. the offer is at or above the GATE — below it no ``OFFERED`` card is minted
       and every board assertion in R2 passes vacuously;
    3. the withdrawal's sender is NOT an ATS — on a relay #166's floor already
       kept it and the new arm is not what admitted it.
    """

    classifier = RulesClassifier()

    withdrawal = classifier.classify(
        f"Regarding your offer - Kelvedon", _withdrawal_body("Kelvedon"), None
    )
    assert withdrawal.category.value == "other"
    assert withdrawal.confidence < pipeline.REVIEW_FLOOR, (
        f"the withdrawal scored {withdrawal.confidence}, at or above the floor: "
        "it would never have been dropped and this whole family is pointless"
    )

    offer = classifier.classify(
        "Offer of employment - Backend Engineer at Kelvedon",
        _offer_body("Kelvedon"),
        None,
    )
    assert offer.category.value == "offer"
    assert offer.confidence >= pipeline.AUTO_FILE_GATE, (
        f"the offer scored {offer.confidence} and will not auto-file; R2's "
        "OFFERED card would never exist and its assertions would be vacuous"
    )

    assert not pipeline.is_ats_sender(_SENDERS["kelvedon"]), (
        "the sender is a known ATS relay, so #166's floor keeps this message "
        "and the arm under test is not what admits it"
    )


# ---------------------------------------------------------------------------
# R1 — the unit gate
# ---------------------------------------------------------------------------


def test_r1_the_arm_admits_without_touching_the_score() -> None:
    """R1. Non-ATS, ``other`` at 0.50, own-text retraction, employer contested.

    "KEPT" IS ASSERTED AS OFFERED AND HOLDING A ROW — one ``ReviewItem``, with
    the message's own id — and never as "absent from the dropped set", which a
    message that never reached the decision would satisfy just as well.

    THE CONFIDENCE ASSERTION IS THE POINT OF THIS TEST. It is what pins the
    mechanism as admission rather than the score lift both issues ask for, and a
    later change that implements the lift instead reds here rather than shipping
    a board that files an offer withdrawal as something.
    """

    item = _item(
        mid="r1-withdrawal",
        subject="Regarding your offer - Kelvedon",
        body=_withdrawal_body("Kelvedon"),
    )
    review, dropped = _collect([item], frozenset({"kelvedon"}))

    assert [r.message_id for r in review] == ["r1-withdrawal"]
    row = review[0]
    assert row.confidence == 0.50, (
        f"the stored confidence moved to {row.confidence}. The fix is ADMISSION: "
        "who gets asked changes, the score does not (#166 queues a 0.42 untouched)"
    )
    assert row.hold_reason == pipeline.HOLD_CONTRADICTS_FILED
    assert row.hold_reason in pipeline.HOLD_REASONS
    assert row.company_display == "Kelvedon", (
        "a queue row with no employer against it is a worse row to hand a person"
    )
    # The item is `other`, so it was never a DroppedVerdict either way — asserted
    # so a reader does not take the empty list as evidence of the admission.
    assert dropped == []


def test_r1_the_reason_is_not_derivable_from_the_row_it_describes() -> None:
    """Why the reason is STORED, shown rather than argued (#800, and #507's shape).

    ``hold_reason`` re-derives seven of its eight answers from the message, and
    for those that is right. Run against this row's own inputs it returns
    ``below_gate`` — "the classifier was unsure" — which is a true sentence about
    the score and a false one about why the row is here.

    So the two values are DIFFERENT, deliberately and permanently, and this test
    exists to keep them different: a later "simplification" that routes the
    contradiction reason back through re-derivation reds here.
    """

    derived = pipeline.hold_reason(
        confidence=0.50,
        subject="Regarding your offer - Kelvedon",
        sender_email=_SENDERS["kelvedon"],
        sender_name="Kelvedon Talent",
        snippet=_withdrawal_body("Kelvedon"),
        has_proposal=True,
        category="other",
    )
    assert derived == pipeline.HOLD_BELOW_GATE
    assert derived != pipeline.HOLD_CONTRADICTS_FILED


# ---------------------------------------------------------------------------
# The directional controls — these must NOT move
# ---------------------------------------------------------------------------


def test_n1_the_same_text_with_no_live_card_is_still_dropped() -> None:
    """N1. THE CONTROL THAT SEPARATES THIS FROM A KEYWORD IN A FLOOR COSTUME.

    Byte-identical withdrawal text, one thing varied: the board holds no offer
    at this employer. If the message is admitted anyway then what admitted it was
    the wording, the ``contested`` argument is decoration, and every claim this
    change makes about reading the board is false.

    ONE VARIABLE. The item is the same object shape, the same sender, the same
    subject and the same body as R1's; only ``contested`` differs.
    """

    item = _item(
        mid="n1-withdrawal",
        subject="Regarding your offer - Kelvedon",
        body=_withdrawal_body("Kelvedon"),
    )
    review, dropped = _collect([item], frozenset())

    assert review == []
    # It leaves by the same door as before: `other` is not a lifecycle category,
    # so it is not even counted — it reaches nothing, indistinguishable from a
    # newsletter, which is the defect stated precisely.
    assert dropped == []

    ledger = pipeline.ledger_for_scan([item], [], [], [])
    assert ledger.reached_nothing == 1
    assert ledger.queued == 0


def test_n1_the_only_difference_is_the_board() -> None:
    """N1's premise: the two runs differ in ONE argument and nothing else.

    A two-variable pair proves neither variable. The items are compared field by
    field so "identical text" is executed rather than claimed.
    """

    kept = _item(
        mid="same",
        subject="Regarding your offer - Kelvedon",
        body=_withdrawal_body("Kelvedon"),
    )
    dropped_item = _item(
        mid="same",
        subject="Regarding your offer - Kelvedon",
        body=_withdrawal_body("Kelvedon"),
    )
    assert kept == dropped_item

    assert len(_collect([kept], frozenset({"kelvedon"}))[0]) == 1
    assert len(_collect([dropped_item], frozenset())[0]) == 0


def test_n4_the_arm_cannot_fire_at_or_above_the_review_floor() -> None:
    """N4. #417's territory is untouched — the new arm is unreachable up there.

    A retraction scoring at or above the floor is the case #417 already caps and
    already queues. If this arm could reach it there would be two decisions about
    one message, and the newer one would be labelling a row #417 admitted.

    Walked across the band rather than asserted at one point, so a later change
    to the guard has to move a boundary and not merely a number.
    """

    for confidence in (0.70, 0.80, 0.84, 0.85, 0.95):
        item = _item(
            mid=f"n4-{confidence}",
            subject="Regarding your offer - Kelvedon",
            body=_withdrawal_body("Kelvedon"),
            category="offer",
            confidence=confidence,
        )
        review, _ = _collect([item], frozenset({"kelvedon"}))
        reasons = {r.hold_reason for r in review}
        assert pipeline.HOLD_CONTRADICTS_FILED not in reasons, (
            f"the contradiction arm claimed a message at {confidence}, which is "
            "#417's case and was already handled before this change"
        )


def test_n4_a_relayed_withdrawal_keeps_the_reason_the_ats_floor_gave_it() -> None:
    """N4, second half. #166's rows do not get relabelled by this change.

    An ATS-relayed withdrawal was kept by the ATS floor before #800 existed, so
    the reason it carries has to stay ``ats_floor``: the row is here because a
    relay carried it, and claiming otherwise would assert a decision that did not
    happen. This is also what makes the corpus delta for this change zero rather
    than 260 rows moving their reason — measured, and the arm is guarded on it.
    """

    # SOURCED FROM THE CORPUS GENERATOR, never written out here. The address has
    # to be a REAL relay — `is_ats_sender` matches `rules.ATS_DOMAINS`, and no
    # reserved domain is on that list, so a `.test` sender would make this
    # control assert the opposite of what it is for. `ATS_SENDERS` is already
    # recorded in the test-data baseline through `generate.py`, so reading it
    # keeps this file free of a new non-reserved address (DEC-008 exists for the
    # case where one must be written out; this is the case where it need not be).
    from tests.corpus_independent.generate import ATS_SENDERS

    relay = sorted(ATS_SENDERS)[0]
    assert pipeline.is_ats_sender(relay), "the premise of this control is the sender"

    item = _item(
        mid="n4-relayed",
        subject="Regarding your offer - Kelvedon",
        body=_withdrawal_body("Kelvedon"),
        sender=relay,
    )
    review, _ = _collect([item], frozenset({"kelvedon"}))

    assert [r.message_id for r in review] == ["n4-relayed"]
    assert review[0].hold_reason is None, (
        "the row is here because an ATS relayed it; the read path derives "
        "ats_floor for it and this change must not overwrite that"
    )


def test_n5_conditional_and_candidate_authored_stay_dropped() -> None:
    """N5. Two near-misses that must not move, and neither needs a new wording.

    · CONDITIONAL — ``asserted_text`` strips a conditional clause before either
      vocabulary is consulted, so "if the offer were withdrawn…" carries no
      assertion to read.
    · CANDIDATE-AUTHORED — "I am withdrawing my application" fails the other side
      of the conjunction. #447's phrase set describes the reader's process as a
      CORRESPONDENT speaks of it ("your application", "the offer"); the reader's
      own possessive matches nothing in it. PINNED AS DROPPED, which is the
      behaviour this change chooses: the user knows they withdrew, and a queue
      row asking them to confirm their own decision is the ``follow_up`` mistake
      #458 describes from the other direction.
    """

    conditional = _item(
        mid="n5-conditional",
        subject="Regarding your offer - Kelvedon",
        body=(
            "Hi Ayush, A note on process. If the offer were withdrawn for any "
            "reason, our policy is to give you two weeks notice in writing. "
            "Nothing has changed and we are excited for you to join us."
        ),
    )
    candidate = _item(
        mid="n5-candidate",
        subject="Withdrawing my application",
        body=(
            "Hi, After much thought I am withdrawing my application for the "
            "Backend Engineer role. Thank you for your time and please keep me "
            "in mind for future openings."
        ),
    )

    for item in (conditional, candidate):
        review, _ = _collect([item], frozenset({"kelvedon"}))
        assert review == [], f"{item.message_id} was admitted and must not be"


def test_n5_a_negated_retraction_is_admitted_and_that_is_a_known_cost() -> None:
    """N5's third case, PINNED AS ADMITTED — which is not what #800 asked for.

    "We will not be withdrawing the offer" is admitted. It should not be, and it
    cannot be excluded within the constraints this change is built under:
    ``asserted_text`` handles quotes and conditionals and there is NO negation
    facility anywhere in ``rules.py`` to reuse, so refusing it means authoring a
    refutation wording from an example written by the author of this change.
    ``docs/CLASSIFIER_RULES_GOVERNANCE.md`` refuses exactly that twice
    (``9e013ff``, ``91838a6``), and per #531 the grading corpus holds no
    rescission wordings, so the new pattern would be graded only by its own
    author's fixtures. Governance wins; the false positive is accepted and named.

    THE COST IS ONE REVIEW-QUEUE ROW, and it is bounded by the same reasoning
    #447 records one function up: nothing files, no status moves,
    ``_qualifies_for_hard_row`` is untouched. The user is asked to look at a
    message about an offer they hold.

    ASSERTED RATHER THAN LEFT SILENT so the gap is a fact in the suite instead of
    a paragraph in a commit nobody reads. A later change that adds a negation
    handler reds this test, and updating it is how that change announces itself.
    """

    negated = _item(
        mid="n5-negated",
        subject="Regarding your offer - Kelvedon",
        body=(
            "Hi Ayush, To clear up the confusion from this morning: we will not "
            "be withdrawing the offer we extended to you. It stands exactly as "
            "written and we look forward to hearing your answer this week."
        ),
    )
    review, _ = _collect([negated], frozenset({"kelvedon"}))

    assert [r.message_id for r in review] == ["n5-negated"]
    assert review[0].hold_reason == pipeline.HOLD_CONTRADICTS_FILED
    assert review[0].confidence == 0.50


def test_n6_the_row_names_the_card_the_message_names() -> None:
    """N6. A decoy employer also at OFFERED; the message names the other one.

    Two claims, and the second is the one a set-membership bug would pass:
    the decoy's presence does not admit a message that names somebody else, and
    the row that IS admitted carries the named employer.
    """

    contested = frozenset({"kelvedon", "marrowby"})

    names_marrowby = _item(
        mid="n6-marrowby",
        subject="Regarding your offer - Marrowby",
        body=_withdrawal_body("Marrowby"),
        sender=_SENDERS["marrowby"],
        sender_name="Marrowby Talent",
    )
    review, _ = _collect([names_marrowby], contested)
    assert [r.company_display for r in review] == ["Marrowby"]

    # A third employer with NO card: the two decoys must not carry it in.
    names_penhale = _item(
        mid="n6-penhale",
        subject="Regarding your offer - Penhale",
        body=_withdrawal_body("Penhale"),
        sender=_SENDERS["penhale"],
        sender_name="Penhale Talent",
    )
    assert _collect([names_penhale], contested)[0] == []


def test_n6_two_withdrawals_are_two_rows() -> None:
    """N6, second half. Two contested employers, two messages, two rows.

    Separate threads, so this is a claim about the arm and not about
    ``review_dedup_key``'s collapsing.
    """

    items = [
        _item(
            mid="n6-two-kelvedon",
            subject="Regarding your offer - Kelvedon",
            body=_withdrawal_body("Kelvedon"),
            thread="th-a",
        ),
        _item(
            mid="n6-two-marrowby",
            subject="Regarding your offer - Marrowby",
            body=_withdrawal_body("Marrowby"),
            sender=_SENDERS["marrowby"],
            sender_name="Marrowby Talent",
            thread="th-b",
        ),
    ]
    review, _ = _collect(items, frozenset({"kelvedon", "marrowby"}))
    assert sorted(r.message_id for r in review) == [
        "n6-two-kelvedon",
        "n6-two-marrowby",
    ]
    assert all(r.hold_reason == pipeline.HOLD_CONTRADICTS_FILED for r in review)


def test_the_retraction_pattern_stays_linear_on_a_long_body() -> None:
    """The widened input class, timed rather than argued.

    ``_RETRACTION``'s own docstring bounds its ReDoS reasoning to "a span shorter
    than ``_MIN_ASSERTED_CHARS``" — #417 only ever handed it a short reply. This
    change hands it a whole snippet, so the existing safety claim does not cover
    the new use and is re-established here instead of inherited.

    Every quantifier in the pattern is bounded over a class excluding the
    sentence delimiter, so the walk should be linear. The adversarial shape is
    the one those bounds are about: the trigger word, then a long run of the
    character class with the closing word never arriving.
    """

    adversarial = "the offer " + ("no longer " + "x" * 29 + " ") * 2000
    assert len(adversarial) > 70_000

    start = time.perf_counter()
    pipeline.retracts_an_application("Regarding your offer", adversarial)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, (
        f"the predicate took {elapsed:.2f}s on a {len(adversarial)}-character "
        "body; the bounded-quantifier claim does not survive the wider input"
    )


# ---------------------------------------------------------------------------
# R2 — the gate of record
# ---------------------------------------------------------------------------


def family() -> list[Case]:
    """The offer, then its withdrawal, in the SAME Gmail conversation.

    ONE THREAD IS THE POINT. #417 records that the real shape of a withdrawal is
    a reply inside the offer's own thread, and it is that shape — same thread,
    same role, so the same ``review_dedup_key`` — that reaches the settled
    filter. A withdrawal on a fresh thread would clear the floor fix and never
    exercise the second drop site at all.

    NINE DAYS APART, so the offer is filed by an earlier sync than the one that
    delivers the withdrawal. That is the ordinary shape and it is also the one
    where the settled filter has a stored row to consult.
    """

    return [
        _offer("Kelvedon", "kelvedon", "th-r2-kelvedon", "r2-offer", 0),
        _withdrawal(
            "Kelvedon",
            "kelvedon",
            "th-r2-kelvedon",
            "r2-withdrawal",
            9,
            note="the message #800 is about: same thread, under the floor, direct sender",
        ),
    ]


async def _rows_for(session, message_ids) -> set[str]:
    return set(
        (
            await session.exec(
                select(Email.message_id).where(
                    Email.user_id == _USER,
                    Email.message_id.in_(list(message_ids)),
                )
            )
        ).all()
    )


async def test_r2_a_withdrawal_reaches_the_queue_through_the_sync(
    test_session,
) -> None:
    """R2, THE GATE OF RECORD. Replayed through the sync entrypoint, end to end.

    RED TODAY TWICE, which is why this and not R1 is the gate: the review floor
    drops the message, and past that the settled filter refuses it a row because
    the offer it contradicts already answers for the thread.

    FOUR CLAIMS, each asserted rather than inferred:

    1. the offer auto-filed and the board really does read ``offered`` — without
       that there is no contested card and nothing below means anything;
    2. the withdrawal holds an ``emails`` row, which is the thing its absence
       cost: no row was the whole defect;
    3. it is IN THE QUEUE, and was not merely stored;
    4. it was not suppressed on the way — asserted separately from (2), because
       "no row" and "refused a row" are the same observation and different bugs.
    """

    cases = family()
    replayed = await replay(test_session, classify_all(cases))

    # 1 — the premise, read off the board the product would show.
    card = (
        await test_session.exec(
            select(Application).where(Application.user_id == _USER)
        )
    ).all()
    assert len(card) == 1, f"expected one card, got {[c.company for c in card]}"
    assert card[0].status == ApplicationStatus.OFFERED, (
        f"the board reads {card[0].status}; there is no contested offer and "
        "every assertion below would pass vacuously"
    )

    # 2 — NOT REFUSED, ASSERTED FIRST, and the order is the instrument.
    #
    # "no row" and "offered a row and refused one" are the same observation of
    # the database and two different bugs. Asserting the absence of a row first
    # would report both as "the withdrawal never arrived", so the discriminating
    # claim goes ahead of it: the ref reached the settled filter and the filter
    # kept it. Removing the carve-out reds THIS line, naming the second drop
    # site; breaking the admission arm reds the next one instead.
    assert replayed.suppressed == set(), (
        f"the persist refused {sorted(replayed.suppressed)} — the message reached "
        "the queue and was denied a row by the settled filter, which is the "
        "SECOND drop site and not the review floor"
    )

    # 3 — the row. This is the defect, stated as an observation of the database.
    assert await _rows_for(test_session, {"r2-withdrawal"}) == {"r2-withdrawal"}

    # 4 — the queue.
    assert "r2-withdrawal" in replayed.reviewed

    # The message was never a `DroppedVerdict` in either world — `other` is not a
    # lifecycle category — so its absence there is asserted as the non-evidence
    # it is, not as a pass.
    assert "r2-withdrawal" not in replayed.dropped


async def test_r2_the_stored_row_carries_the_reason_and_not_a_lifted_score(
    test_session,
) -> None:
    """R2's second half: WHAT the queue got, not merely that it got something.

    The confidence assertion is the same pin as R1's, made one layer further out
    — against the value actually written to the database, after the persist,
    where a score adjustment anywhere in the path would show up.
    """

    cases = family()
    await replay(test_session, classify_all(cases))

    row = (
        await test_session.exec(
            select(Email).where(
                Email.user_id == _USER, Email.message_id == "r2-withdrawal"
            )
        )
    ).one()

    assert row.hold_reason == pipeline.HOLD_CONTRADICTS_FILED
    assert row.classification_confidence == 0.50, (
        f"the persisted confidence is {row.classification_confidence}; the fix "
        "is admission and must not move the score"
    )
    # The queue's committed state is still the typed null, and the verdict is
    # still only a proposal — this change does not make `other` a commitment.
    assert row.classified_as.value == "needs_review"
    assert row.suggested_category.value == "other"


async def test_r2_the_ledger_still_closes_with_the_message_in_queued(
    test_session,
) -> None:
    """The partition, over the batch that delivers the withdrawal (#800 item 7).

    The message moves from ``reached_nothing`` to ``queued``, and
    ``classified == filed + queued + dropped + reached_nothing`` still holds.
    It is a set difference rather than a subtraction, so this cannot go negative
    — what it CAN do is put one message in two buckets, which is the overlap the
    ledger warns about and what an arm that also filed would produce.
    """

    cases = family()
    verdicts = classify_all(cases)
    await replay(test_session, verdicts)

    withdrawal = [v for v in verdicts if v.case.message_id == "r2-withdrawal"]
    batch = [harness._item(v) for v in withdrawal]

    contested = await applications.employers_with_a_live_offer(test_session, _USER)
    assert contested, "the board did not report a contested employer after the replay"

    dropped: list[pipeline.DroppedVerdict] = []
    review = pipeline.collect_review_items(
        batch, dropped, frozenset(), frozenset(), contested
    )
    rolled = pipeline.roll_up_applications(batch, frozenset(), frozenset())
    ledger = pipeline.ledger_for_scan(batch, rolled, review, dropped)

    assert ledger.classified == (
        ledger.filed + ledger.queued + ledger.dropped + ledger.reached_nothing
    )
    assert ledger.queued == 1
    assert ledger.reached_nothing == 0
    assert ledger.filed == 0, "the arm must route to the queue and never file"


async def test_n2_the_relay_noise_family_admits_nothing_with_offers_seeded(
    test_session,
) -> None:
    """N2. The 400 ``ats-relay-noise`` messages, replayed WITH contested employers.

    THE DENOMINATOR IS PRINTED, because a zero with nothing behind it is this
    repository's recurring defect. Three numbers, not one: how many messages were
    replayed, how many employer tokens were seeded contested, and how many of the
    messages actually RESOLVE to a seeded token. The third is what makes the zero
    mean something — a seed the arm never looks up would report the same zero as
    a working predicate.

    THE SEED IS DERIVED THE WAY THE ARM LOOKS IT UP, not read off ``Case.employer``.
    The noise family's ground truth employer is ``None`` by construction — it is
    mail about nobody's application — so seeding from that field would seed
    nothing and this control would be the empty measurement it exists to avoid.
    ``resolve_employer`` is what the arm calls, so it is what builds the set.

    MAXIMALLY HOSTILE, deliberately: every employer these 400 messages resolve to
    is seeded as holding a live offer at once. That is a board no user has, and
    it is the point — if the predicate can be made to fire by the sender's
    company having an offer, this is the run where it happens.
    """

    from tests.corpus_independent.generate import generate

    noise = [c for c in generate(20260822) if c.family == "ats-relay-noise"]
    assert len(noise) == 400, f"the noise family is {len(noise)}, not 400"

    resolved = {}
    for case in noise:
        named = pipeline.resolve_employer(case.sender, case.subject, case.sender_name)
        if named:
            resolved[case.message_id] = named[0]
    contested = frozenset(resolved.values())

    # THE PRECONDITION, asserted before the zero is believed: the seeded set is
    # non-empty AND a real share of the family resolves into it.
    assert contested, "no employer resolved from 400 noise messages; the seed is empty"
    assert len(resolved) >= 200, (
        f"only {len(resolved)} of {len(noise)} noise messages resolve to an "
        "employer at all; the contested lookup is mostly unreachable and a zero "
        "here would be measuring that instead of the predicate"
    )

    items = [
        _item(
            mid=case.message_id,
            subject=case.subject,
            body=snippet_of(case.body),
            sender=case.sender,
            sender_name=case.sender_name or "",
            thread=case.thread_id or case.message_id,
        )
        for case in noise
    ]
    review, _ = _collect(items, contested)
    admitted = [r.message_id for r in review if r.hold_reason == pipeline.HOLD_CONTRADICTS_FILED]

    assert admitted == [], (
        f"{len(admitted)} admissions from {len(noise)} ats-relay-noise messages, "
        f"{len(resolved)} of which resolve to one of {len(contested)} employer "
        f"tokens seeded as holding a live offer: {admitted[:10]}"
    )


def test_the_stored_reason_shortcut_is_scoped_to_the_one_reason() -> None:
    """The read path's early return must not swallow OTHER reasons' extras.

    ``_hold_reason_for`` returns ``(reason, suggested_employer)``, and the second
    is the name #512 exists for: a row whose filing path could not name the
    employer but whose body does gets "is this Kelvedon?" instead of the sentence
    that reads as a lie.

    THE TRAP THIS PINS. ``MessageRef.hold_reason`` is a general carrier with a
    ratchet, so the shortcut has to be keyed on the reason that CANNOT be
    re-derived and not on "anything is stored". Written the wide way — a
    membership test against ``HOLD_REASONS`` — it reads correctly today, because
    nothing else writes the column, and silently blanks the suggested employer
    the first time any other arm records one. That is a defect that ships green,
    so it is asserted here rather than left to the next author.

    Constructed against the real function with a stub row: this is a claim about
    precedence, and going through a sync would prove it for one route only.
    """

    from jobtracker.database.models import EmailCategory

    # THE SHAPE THAT EARNS `confirm_employer`, copied in structure from
    # `test_hold_reason_and_employer_gaps.py`: a relay the filing path cannot
    # resolve an employer from, a subject that names nobody, and a body whose
    # first line does. The sender is read from the corpus generator rather than
    # written out, for the same reason as the relay in N4 above.
    from tests.corpus_independent.generate import ATS_SENDERS

    class _Row:
        user_corrected = False
        is_reviewed = False
        identity_role = None
        classification_confidence = 0.95
        sender_name = None
        subject = "An update on your application | A Candidate"
        sender_email = sorted(ATS_SENDERS)[0]
        body_snippet = (
            "Hi there, Thank you so much for your interest in Kelvedon and for "
            "the time you have invested in our process."
        )

        def __init__(self, stored, suggested) -> None:
            self.hold_reason = stored
            self.suggested_category = suggested

    siblings: dict[str, int] = {}

    derived, name = applications._hold_reason_for(
        _Row(None, EmailCategory.APPLIED), siblings
    )
    assert derived == pipeline.HOLD_CONFIRM_EMPLOYER, (
        f"the fixture no longer earns confirm_employer (got {derived}); it cannot "
        "pin the shortcut's scope"
    )
    assert name, "the baseline row has no suggested employer; nothing to lose"

    still, still_named = applications._hold_reason_for(
        _Row(pipeline.HOLD_CONFIRM_EMPLOYER, EmailCategory.APPLIED), siblings
    )
    assert still == pipeline.HOLD_CONFIRM_EMPLOYER
    assert still_named == name, (
        "the stored-reason shortcut swallowed suggested_employer — scope it to "
        "HOLD_CONTRADICTS_FILED, the only reason that cannot be re-derived"
    )

    contradiction, no_name = applications._hold_reason_for(
        _Row(pipeline.HOLD_CONTRADICTS_FILED, EmailCategory.OTHER), siblings
    )
    assert contradiction == pipeline.HOLD_CONTRADICTS_FILED
    assert no_name is None
