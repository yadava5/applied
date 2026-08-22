"""Run the corpus through the WHOLE product and score what ends up on the board.

Two scores, because a message can pass one and fail the other and the product
only works when it passes both:

**Classification.** ``RulesClassifier.classify`` over what production would
actually hand it — ``extract_body_text(payload) or snippet``, expressed here as
each case's ``delivered`` field. Scored three ways rather than two: CORRECT,
WRONG (a confident verdict that is not the right one), and ABSTAINED (below
``REVIEW_FLOOR``, so the product says nothing). Abstention is the safe failure
and must not be averaged into the same number as being confidently wrong.

**The board.** The classified messages are fed through the real
``roll_up_applications`` / ``collect_review_items`` and the real
``upsert_applications_for_user`` against a real session, IN DAY-SIZED BATCHES —
which is what an incremental sync is. Then the board is read back out of the
``applications`` and ``emails`` tables and compared to ground truth.

WHY BATCHES OF A DAY. A sync rolls up whatever arrived since the last one. One
message at a time would be 10,040 syncs and is not what happens; the whole
mailbox at once is a rebuild and hides every defect that only appears in a
delta — which is exactly how a fix shipped on 2026-08-21 that worked on a
rebuild and did nothing on the syncs that run. A day is the honest middle and
the one the corpus's dates are built for.

Board failure modes, scored per MESSAGE against ground truth rather than by
per-employer cardinality, because "2 cards where 2 were expected" is satisfied
even when both messages sit on the wrong cards:

* **SPLIT** — one ground-truth application over more than one card. Counted as
  extra cards, so a three-way split scores 2.
* **MERGE** — one card holding more than one ground-truth application. The
  strictly worse failure: it destroys a record silently, and a rejection landing
  on the wrong one of four cards settles a live application terminally.
* **NOISE ON A CARD** — mail that must never become an application, on one.
* **SHOULD HAVE GONE TO REVIEW** — role-less mail at a multi-application
  employer that got guessed onto a card instead of being asked about.

``expect_review`` cases are scored in their own bucket: being unplaceable is the
DESIGNED answer there, and counting designed behaviour as failure would swamp
the table.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlmodel import select

from jobtracker.classifier.rules import RulesClassifier
from jobtracker.cloud import pipeline
from jobtracker.cloud.applications import (
    Application,
    Email,
    employers_with_several_applications,
    threads_naming_one_application,
    upsert_applications_for_user,
)

from .generate import Case

_USER = uuid.UUID("00000000-0000-0000-0000-00000000c0de")

#: One classifier for the whole run. Constructing it per message would dominate
#: the wall clock and measure nothing.
_CLASSIFIER = RulesClassifier()

CORRECT, WRONG, ABSTAINED = "correct", "wrong", "abstained"


@dataclass(frozen=True)
class Verdict:
    case: Case
    category: str
    confidence: float
    bucket: str
    auto_filed: bool


def classify_all(cases: list[Case]) -> list[Verdict]:
    """The classifier's answer for every message, as production would get it."""

    out: list[Verdict] = []
    for case in cases:
        result = _CLASSIFIER.classify(case.subject, case.delivered, case.sender)
        category = result.category.value
        confidence = result.confidence
        if confidence < pipeline.REVIEW_FLOOR:
            bucket = ABSTAINED
        elif category == case.expected_category:
            bucket = CORRECT
        else:
            bucket = WRONG
        out.append(
            Verdict(
                case=case,
                category=category,
                confidence=confidence,
                bucket=bucket,
                auto_filed=confidence >= pipeline.AUTO_FILE_GATE,
            )
        )
    return out


@dataclass
class ClassifierScore:
    total: int = 0
    correct: int = 0
    wrong: int = 0
    abstained: int = 0
    auto_filed: int = 0
    auto_filed_wrong: int = 0
    by_family: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def score_classifier(verdicts: list[Verdict]) -> ClassifierScore:
    score = ClassifierScore(total=len(verdicts))
    for v in verdicts:
        setattr(score, v.bucket, getattr(score, v.bucket) + 1)
        score.by_family[v.case.family][v.bucket] += 1
        if v.auto_filed:
            score.auto_filed += 1
            if v.bucket == WRONG:
                score.auto_filed_wrong += 1
                score.by_family[v.case.family]["auto_filed_wrong"] += 1
    return score


# ── the board ────────────────────────────────────────────────────────────────


def _item(v: Verdict) -> pipeline.PipelineItem:
    """A verdict as the pipeline receives it.

    The CLASSIFIER's category and confidence, never the ground truth: feeding
    the expected category here would measure the identity layer over a mailbox
    the product never sees, and every number would be optimistic by exactly the
    classifier's error rate.
    """

    return pipeline.PipelineItem(
        message_id=v.case.message_id,
        thread_id=v.case.thread_id,
        subject=v.case.subject,
        sender_email=v.case.sender,
        sender_name=v.case.sender_name,
        received_at=v.case.received_at,
        category=v.category,
        confidence=v.confidence,
        snippet=v.case.delivered,
    )


async def replay(session, verdicts: list[Verdict]) -> list[tuple[str, list[str]]]:
    """Sync the corpus in day-sized batches; return the board it produces."""

    by_day: dict[int, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        by_day[v.case.received_at.toordinal()].append(v)

    for day in sorted(by_day):
        batch = [_item(v) for v in by_day[day]]
        known_multi = await employers_with_several_applications(session, _USER)
        known_threads = await threads_naming_one_application(session, _USER)
        rolled = pipeline.roll_up_applications(batch, known_multi, known_threads)
        if rolled:
            await upsert_applications_for_user(session, _USER, rolled)
            await session.commit()

    rows = (
        await session.exec(
            select(Application)
            .where(Application.user_id == _USER)
            .order_by(Application.id)
        )
    ).all()
    emails = (
        await session.exec(
            select(Email).where(
                Email.user_id == _USER, Email.application_id.is_not(None)
            )
        )
    ).all()
    filed: dict[int, list[str]] = defaultdict(list)
    for e in emails:
        filed[e.application_id].append(e.message_id)
    # A dismissed row is not on the board; counting one would report a card the
    # user cannot see.
    return [
        (f"row{r.id}:{r.company}", sorted(filed.get(r.id, [])))
        for r in rows
        if r.dismissed_at is None
    ]


@dataclass
class Failure:
    mode: str
    family: str
    detail: str
    message_ids: tuple[str, ...] = ()


@dataclass
class BoardScore:
    cards: int = 0
    splits: int = 0
    merges: int = 0
    noise_on_card: int = 0
    wrong_review: int = 0
    failures: list[Failure] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.splits + self.merges + self.noise_on_card + self.wrong_review


def score_board(
    groups: list[tuple[str, list[str]]], cases: list[Case]
) -> BoardScore:
    by_mid = {c.message_id: c for c in cases}
    score = BoardScore(cards=len(groups))

    ident_cards: dict[str, set[str]] = defaultdict(set)
    for label, mids in groups:
        for mid in mids:
            case = by_mid.get(mid)
            if case is not None and case.identity is not None:
                ident_cards[case.identity].add(label)

    for ident, labels in sorted(ident_cards.items()):
        if len(labels) > 1:
            example = next(c for c in cases if c.identity == ident)
            score.splits += len(labels) - 1
            score.failures.append(
                Failure(
                    mode="SPLIT",
                    family=example.family,
                    detail=f"one application over {len(labels)} cards",
                    message_ids=tuple(
                        sorted(c.message_id for c in cases if c.identity == ident)
                    ),
                )
            )

    for label, mids in groups:
        idents = {
            by_mid[m].identity
            for m in mids
            if m in by_mid and by_mid[m].identity is not None
        }
        if len(idents) > 1:
            family = by_mid[mids[0]].family if mids and mids[0] in by_mid else "?"
            score.merges += len(idents) - 1
            score.failures.append(
                Failure(
                    mode="MERGE",
                    family=family,
                    detail=f"card {label!r} holds {len(idents)} applications",
                    message_ids=tuple(mids),
                )
            )
        noise = [
            m
            for m in mids
            if m in by_mid and by_mid[m].identity is None and not by_mid[m].expect_review
        ]
        if noise:
            score.noise_on_card += len(noise)
            score.failures.append(
                Failure(
                    mode="NOISE-ON-CARD",
                    family=by_mid[noise[0]].family,
                    detail=f"{len(noise)} message(s) that must mint nothing landed on {label!r}",
                    message_ids=tuple(noise),
                )
            )

    on_a_card = {m for _label, mids in groups for m in mids}
    for case in cases:
        if case.expect_review and case.message_id in on_a_card:
            score.wrong_review += 1
            score.failures.append(
                Failure(
                    mode="SHOULD-HAVE-GONE-TO-REVIEW",
                    family=case.family,
                    detail="role-less mail at a multi-application employer was guessed onto a card",
                    message_ids=(case.message_id,),
                )
            )
    return score


def rank(score: BoardScore) -> list[tuple[str, str, int]]:
    tally: Counter[tuple[str, str]] = Counter()
    for f in score.failures:
        weight = max(1, len(f.message_ids) - 1) if f.mode != "SHOULD-HAVE-GONE-TO-REVIEW" else 1
        tally[(f.mode, f.family)] += weight
    return [(mode, family, n) for (mode, family), n in tally.most_common()]
