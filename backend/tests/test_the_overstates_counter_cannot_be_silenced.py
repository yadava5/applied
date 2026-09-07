"""#748 — a card either overstates or it does not, wherever its mail ended up.

The defect
----------
``card_overstates`` was computed only for cases whose message reached
``Replay.reviewed`` — the review queue. Everything else took an early
``continue``. So the counter's population was downstream of the additive
persist's settled filter, which is one of the things it exists to notice.

Measured on the full corpus, driving ``scripts/run_independent_corpus.py``.
Reverting #454's identity component inside ``_persist_review_items_additive``
— keying ``settled_applications`` and the arriving-ref filter on the THREAD
alone at both sites — makes filing strictly worse::

    clean            suppressed   0   queued 2833   CARD-OVERSTATES 260
    thread-alone     suppressed 602   queued 2231   CARD-OVERSTATES   0

602 more messages refused a row, 602 fewer in the queue, and the defect count
reads zero. Not because a card got better: because the evidence stopped being
stored. A corpus run whose headline defect count is 0 is exactly what a green
result looks like.

After the fix the same mutation leaves ``CARD-OVERSTATES`` at **260** and
raises ``SUPPRESSED-AS-SETTLED`` to 602, which is the shape the numbers should
have had all along — two counters answering two questions.

Why this file does not run that mutation
-----------------------------------------
The full replay is minutes per arm, twice. This pins the MECHANISM instead, on
a hand-built ``Replay``: two arms that differ only in WHERE the corrective mail
ended up, and the counter must not care. That is the property the corpus
measurement demonstrated, and it reds on the same deletion.
"""

from __future__ import annotations

from tests.corpus_independent.generate import Case
from tests.corpus_independent.harness import Replay, score_board

CARD = "row1:Tamariskholtreach Analytics"


def _case(message_id: str, *, card_status: str | None, joins: str | None = None) -> Case:
    """A minimal case. Only the fields ``score_board`` reads are meaningful."""
    return Case(
        message_id=message_id,
        thread_id="t1",
        subject="An update",
        sender="careers@halberd.test",
        sender_name="Halberd",
        body="body",
        delivered="body",
        received_at="2026-09-01T00:00:00Z",
        family="rescinded-offer",
        expected_category="rejection",
        identity="halberd|__apply0__",
        employer="Halberd",
        card_status=card_status,
        joins=joins,
    )


def _replay(*, reviewed: set[str], suppressed: set[str], on_card: list[str]) -> Replay:
    """The offer is filed and the card reads ``offered``; the truth is ``rejected``."""
    return Replay(
        groups=[(CARD, on_card)],
        reviewed=reviewed,
        dropped=set(),
        suppressed=suppressed,
        synced=set(),
        status={CARD: "offered"},
        title={CARD: ("Halberd", "Analyst")},
        verdict={},
    )


#: The offer, filed, and the withdrawal that should have corrected it.
OFFER = "m-offer"
WITHDRAWAL = "m-withdrawal"

CASES = [
    _case(OFFER, card_status="offered"),
    _case(WITHDRAWAL, card_status="rejected", joins=OFFER),
]


def test_the_card_overstates_when_the_correction_is_in_the_queue() -> None:
    """Arm 1 — the pre-existing path, and the control for arm 2.

    If this ever stops firing, arm 2 proves nothing: two zeros would agree.
    """
    score = score_board(
        _replay(reviewed={WITHDRAWAL}, suppressed=set(), on_card=[OFFER]), CASES
    )

    assert score.card_overstates == 1


def test_the_card_still_overstates_when_the_correction_was_suppressed() -> None:
    """Arm 2 — the fix. Same board, same truth, the mail refused a row instead.

    This is the whole issue: the card reads ``offered`` and the mail that makes
    it ``rejected`` never reached it. Where it went is a different question with
    its own counter. Delete the ``_overstates`` call from the ``label is None``
    branch and this reds while arm 1 stays green.
    """
    score = score_board(
        _replay(reviewed=set(), suppressed={WITHDRAWAL}, on_card=[OFFER]), CASES
    )

    assert score.card_overstates == 1


def test_the_two_arms_agree() -> None:
    """Stated as its own claim, because it is the property and not a side effect.

    A counter whose population is fixed independently of the behaviour under
    test returns the same number under both. That is what makes it able to fall
    the wrong way when something really does get worse.
    """
    queued = score_board(
        _replay(reviewed={WITHDRAWAL}, suppressed=set(), on_card=[OFFER]), CASES
    )
    settled = score_board(
        _replay(reviewed=set(), suppressed={WITHDRAWAL}, on_card=[OFFER]), CASES
    )

    assert queued.card_overstates == settled.card_overstates


def test_a_card_that_is_behind_reality_is_not_counted() -> None:
    """The directional negative, so this is not "count every unfiled message".

    A card reading ``applied`` while an offer waits in the queue is BEHIND, not
    ahead — incomplete and true as far as it goes. ``_overstates`` reads the
    direction off the product's own ``_STATUS_RANK``, and this pins that it
    still does after the population widened.
    """
    behind = Replay(
        groups=[(CARD, [OFFER])],
        reviewed=set(),
        suppressed={WITHDRAWAL},
        dropped=set(),
        synced=set(),
        status={CARD: "applied"},
        title={CARD: ("Halberd", "Analyst")},
        verdict={},
    )
    cases = [
        _case(OFFER, card_status="applied"),
        _case(WITHDRAWAL, card_status="offered", joins=OFFER),
    ]

    assert score_board(behind, cases).card_overstates == 0
